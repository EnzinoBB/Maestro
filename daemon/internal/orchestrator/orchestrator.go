package orchestrator

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"runtime"
	"time"

	"github.com/maestro-project/maestro-daemon/internal/metrics"
	"github.com/maestro-project/maestro-daemon/internal/runner"
	"github.com/maestro-project/maestro-daemon/internal/state"
	"github.com/maestro-project/maestro-daemon/internal/ws"
)

// Orchestrator wires the WS client, state store and runners together.
// It implements the set of Handler functions for ws.Client.
type Orchestrator struct {
	Store   state.Store
	Docker  *runner.DockerRunner
	Systemd *runner.SystemdRunner
	Version string
	Logger  *slog.Logger
}

func (o *Orchestrator) logger() *slog.Logger {
	if o.Logger != nil {
		return o.Logger
	}
	return slog.Default()
}

func (o *Orchestrator) runnersAvailable() []string {
	out := []string{}
	if o.Docker != nil {
		out = append(out, "docker")
	}
	if o.Systemd != nil {
		out = append(out, "systemd")
	}
	return out
}

// HelloInfo returns runtime info to include in hello_ack.
func (o *Orchestrator) HelloInfo() ws.HandshakeInfo {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	comps, _ := o.Store.List(ctx)
	refs := make([]ws.ComponentRef, 0, len(comps))
	for _, c := range comps {
		refs = append(refs, ws.ComponentRef{
			ID: c.ID, ComponentHash: c.ComponentHash, Status: c.Status,
		})
	}
	return ws.HandshakeInfo{
		DaemonVersion:    o.Version,
		RunnersAvailable: o.runnersAvailable(),
		ComponentsKnown:  refs,
		System: map[string]any{
			"goos":   runtime.GOOS,
			"goarch": runtime.GOARCH,
		},
	}
}

// Handlers returns a map of request types → handlers suitable for ws.Client.
func (o *Orchestrator) Handlers() map[string]ws.Handler {
	return map[string]ws.Handler{
		ws.TypeReqStateGet: o.handleStateGet,
		ws.TypeReqDeploy:   o.handleDeploy,
		ws.TypeReqStart:    o.handleStart,
		ws.TypeReqStop:     o.handleStop,
		ws.TypeReqRestart:  o.handleRestart,
		ws.TypeReqLogsTail: o.handleLogsTail,
		ws.TypeReqHealth:   o.handleHealthcheck,
	}
}

func (o *Orchestrator) runnerFor(runnerName string) (runner.Runner, error) {
	switch runnerName {
	case "docker":
		if o.Docker == nil {
			return nil, errors.New("docker runner not configured")
		}
		return o.Docker, nil
	case "systemd":
		if o.Systemd == nil {
			return nil, errors.New("systemd runner not configured")
		}
		return o.Systemd, nil
	default:
		return nil, fmt.Errorf("unknown runner %q", runnerName)
	}
}

// ---- handlers ----------------------------------------------------------

type stateGetPayload struct {
	Components []string `json:"components"`
}

func (o *Orchestrator) handleStateGet(ctx context.Context, msg ws.Message) (string, any, error) {
	var req stateGetPayload
	_ = ws.ParsePayload(msg, &req)
	comps, err := o.Store.List(ctx)
	if err != nil {
		return ws.TypeResStateGet, map[string]any{"components": []any{}, "error": err.Error()}, nil
	}
	out := []map[string]any{}
	for _, c := range comps {
		if len(req.Components) > 0 {
			found := false
			for _, want := range req.Components {
				if want == c.ID {
					found = true
					break
				}
			}
			if !found {
				continue
			}
		}
		entry := map[string]any{
			"id":             c.ID,
			"status":         c.Status,
			"component_hash": c.ComponentHash,
			"runner":         c.Runner,
		}
		if c.ContainerID != "" {
			entry["container_id"] = c.ContainerID
		}
		if c.UnitName != "" {
			entry["unit_name"] = c.UnitName
		}
		if c.StartedAt != nil {
			entry["started_at"] = c.StartedAt.UTC().Format(time.RFC3339)
		}
		if c.LastHCAt != nil {
			entry["last_healthcheck"] = map[string]any{
				"ok": c.LastHCOK,
				"ts": c.LastHCAt.UTC().Format(time.RFC3339),
			}
		}
		out = append(out, entry)
	}
	return ws.TypeResStateGet, map[string]any{"components": out}, nil
}

func (o *Orchestrator) handleDeploy(ctx context.Context, msg ws.Message) (string, any, error) {
	var dep runner.ComponentDeploy
	if err := json.Unmarshal(msg.Payload, &dep); err != nil {
		return ws.TypeResDeploy, map[string]any{
			"ok": false,
			"error": map[string]any{"code": "validation_error", "message": err.Error()},
		}, nil
	}
	if dep.ComponentID == "" {
		return ws.TypeResDeploy, map[string]any{
			"ok": false,
			"error": map[string]any{"code": "validation_error", "message": "component_id required"},
		}, nil
	}
	runnerName, _ := dep.Run["type"].(string)
	rn, err := o.runnerFor(runnerName)
	if err != nil {
		return ws.TypeResDeploy, map[string]any{
			"ok": false, "component_id": dep.ComponentID,
			"error": map[string]any{
				"code": "not_supported", "message": err.Error(),
				"suggested_fix": "deploy on a host whose daemon has the runner enabled",
			},
		}, nil
	}
	o.logger().Info("deploy starting", "component", dep.ComponentID, "runner", runnerName)

	// Mark deploying
	_ = o.Store.Upsert(ctx, &state.Component{
		ID: dep.ComponentID, Status: "deploying",
		ComponentHash: dep.TargetHash, Runner: runnerName,
	})

	tmo := 600 * time.Second
	if dep.TimeoutSec > 0 {
		tmo = time.Duration(dep.TimeoutSec) * time.Second
	}
	dctx, cancel := context.WithTimeout(ctx, tmo)
	defer cancel()

	res, err := rn.Deploy(dctx, &dep)
	if err != nil {
		o.logger().Error("deploy transport failure", "err", err)
		return ws.TypeResDeploy, map[string]any{
			"ok": false, "component_id": dep.ComponentID,
			"error": map[string]any{"code": "internal", "message": err.Error()},
		}, nil
	}

	comp := &state.Component{
		ID: dep.ComponentID,
		Status: func() string {
			if res.OK {
				return string(runner.StatusRunning)
			}
			return string(runner.StatusFailed)
		}(),
		ComponentHash: dep.TargetHash,
		Runner:        runnerName,
	}
	if res.RuntimeInfo != nil {
		comp.ContainerID = res.RuntimeInfo.ContainerID
		comp.ContainerName = res.RuntimeInfo.ContainerName
		comp.UnitName = res.RuntimeInfo.UnitName
		comp.WorkDir = res.RuntimeInfo.WorkDir
		if res.RuntimeInfo.StartedAt != "" {
			if t, err := time.Parse(time.RFC3339, res.RuntimeInfo.StartedAt); err == nil {
				comp.StartedAt = &t
			}
		}
	}
	_ = o.Store.Upsert(ctx, comp)
	if res.OK {
		_ = o.Store.AppendHistory(ctx, dep.ComponentID, dep.TargetHash)
	}

	payload := map[string]any{
		"ok":           res.OK,
		"component_id": dep.ComponentID,
		"new_hash":     res.NewHash,
		"duration_ms":  res.DurationMS,
		"phases":       res.Phases,
	}
	if res.Error != nil {
		payload["error"] = res.Error
	}
	if res.RuntimeInfo != nil {
		payload["runtime"] = res.RuntimeInfo
	}
	return ws.TypeResDeploy, payload, nil
}

type componentOpPayload struct {
	ComponentID      string `json:"component_id"`
	GracefulTimeoutS int    `json:"graceful_timeout_sec"`
}

func (o *Orchestrator) resolveRunnerForComponent(ctx context.Context, id string) (runner.Runner, *runner.ComponentDeploy, error) {
	c, err := o.Store.Get(ctx, id)
	if err != nil {
		return nil, nil, err
	}
	rn, err := o.runnerFor(c.Runner)
	if err != nil {
		return nil, nil, err
	}
	// Minimal reconstruction: for start/stop we only need name/id
	dep := &runner.ComponentDeploy{
		ComponentID: c.ID,
		Run:         map[string]any{"container_name": containerNameOrDefault(c), "unit_name": unitNameOrDefault(c)},
	}
	return rn, dep, nil
}

func containerNameOrDefault(c *state.Component) string {
	if c.ContainerName != "" {
		return c.ContainerName
	}
	return "maestro-" + c.ID
}

func unitNameOrDefault(c *state.Component) string {
	if c.UnitName != "" {
		return c.UnitName
	}
	return "maestro-" + c.ID + ".service"
}

func (o *Orchestrator) handleStart(ctx context.Context, msg ws.Message) (string, any, error) {
	var req componentOpPayload
	if err := ws.ParsePayload(msg, &req); err != nil || req.ComponentID == "" {
		return ws.TypeResStart, map[string]any{"ok": false, "error": map[string]string{"code": "validation_error", "message": "component_id required"}}, nil
	}
	rn, dep, err := o.resolveRunnerForComponent(ctx, req.ComponentID)
	if err != nil {
		return ws.TypeResStart, map[string]any{"ok": false, "error": map[string]string{"code": "not_found", "message": err.Error()}}, nil
	}
	if err := rn.Start(ctx, dep); err != nil {
		return ws.TypeResStart, map[string]any{"ok": false, "error": map[string]string{"code": "runtime_error", "message": err.Error()}}, nil
	}
	o.markStatus(ctx, req.ComponentID, "running")
	return ws.TypeResStart, map[string]any{"ok": true, "component_id": req.ComponentID}, nil
}

func (o *Orchestrator) handleStop(ctx context.Context, msg ws.Message) (string, any, error) {
	var req componentOpPayload
	if err := ws.ParsePayload(msg, &req); err != nil || req.ComponentID == "" {
		return ws.TypeResStop, map[string]any{"ok": false, "error": map[string]string{"code": "validation_error", "message": "component_id required"}}, nil
	}
	rn, dep, err := o.resolveRunnerForComponent(ctx, req.ComponentID)
	if err != nil {
		return ws.TypeResStop, map[string]any{"ok": false, "error": map[string]string{"code": "not_found", "message": err.Error()}}, nil
	}
	graceful := time.Duration(req.GracefulTimeoutS) * time.Second
	if graceful == 0 {
		graceful = 10 * time.Second
	}
	if err := rn.Stop(ctx, dep, graceful); err != nil {
		return ws.TypeResStop, map[string]any{"ok": false, "error": map[string]string{"code": "runtime_error", "message": err.Error()}}, nil
	}
	o.markStatus(ctx, req.ComponentID, "stopped")
	return ws.TypeResStop, map[string]any{"ok": true, "component_id": req.ComponentID}, nil
}

func (o *Orchestrator) handleRestart(ctx context.Context, msg ws.Message) (string, any, error) {
	var req componentOpPayload
	if err := ws.ParsePayload(msg, &req); err != nil || req.ComponentID == "" {
		return ws.TypeResRestart, map[string]any{"ok": false, "error": map[string]string{"code": "validation_error", "message": "component_id required"}}, nil
	}
	rn, dep, err := o.resolveRunnerForComponent(ctx, req.ComponentID)
	if err != nil {
		return ws.TypeResRestart, map[string]any{"ok": false, "error": map[string]string{"code": "not_found", "message": err.Error()}}, nil
	}
	_ = rn.Stop(ctx, dep, 10*time.Second)
	if err := rn.Start(ctx, dep); err != nil {
		return ws.TypeResRestart, map[string]any{"ok": false, "error": map[string]string{"code": "runtime_error", "message": err.Error()}}, nil
	}
	o.markStatus(ctx, req.ComponentID, "running")
	return ws.TypeResRestart, map[string]any{"ok": true, "component_id": req.ComponentID}, nil
}

type logsReq struct {
	ComponentID string `json:"component_id"`
	Lines       int    `json:"lines"`
}

func (o *Orchestrator) handleLogsTail(ctx context.Context, msg ws.Message) (string, any, error) {
	var req logsReq
	_ = ws.ParsePayload(msg, &req)
	if req.ComponentID == "" {
		return ws.TypeResLogsTail, map[string]any{"ok": false, "error": map[string]string{"code": "validation_error", "message": "component_id required"}}, nil
	}
	if req.Lines <= 0 {
		req.Lines = 200
	}
	rn, dep, err := o.resolveRunnerForComponent(ctx, req.ComponentID)
	if err != nil {
		return ws.TypeResLogsTail, map[string]any{"ok": false, "error": map[string]string{"code": "not_found", "message": err.Error()}}, nil
	}
	lines, err := rn.Logs(ctx, dep, req.Lines, time.Time{})
	if err != nil {
		return ws.TypeResLogsTail, map[string]any{"ok": false, "error": map[string]string{"code": "runtime_error", "message": err.Error()}}, nil
	}
	return ws.TypeResLogsTail, map[string]any{
		"ok": true, "component_id": req.ComponentID, "lines": lines,
	}, nil
}

type hcReq struct {
	ComponentID string         `json:"component_id"`
	Healthcheck map[string]any `json:"healthcheck"`
}

func (o *Orchestrator) handleHealthcheck(ctx context.Context, msg ws.Message) (string, any, error) {
	var req hcReq
	_ = ws.ParsePayload(msg, &req)
	if req.Healthcheck == nil {
		return ws.TypeResHealth, map[string]any{"ok": true, "type": "none"}, nil
	}
	res := runner.RunHealthcheck(ctx, req.Healthcheck)
	if req.ComponentID != "" {
		o.markHealth(ctx, req.ComponentID, res.OK)
	}
	return ws.TypeResHealth, map[string]any{
		"ok": res.OK, "type": res.Type, "detail": res.Detail,
	}, nil
}

// ---- helpers -----------------------------------------------------------

func (o *Orchestrator) markStatus(ctx context.Context, id, status string) {
	c, err := o.Store.Get(ctx, id)
	if err != nil {
		return
	}
	c.Status = status
	_ = o.Store.Upsert(ctx, c)
}

func (o *Orchestrator) markHealth(ctx context.Context, id string, ok bool) {
	c, err := o.Store.Get(ctx, id)
	if err != nil {
		return
	}
	now := time.Now().UTC()
	c.LastHCAt = &now
	c.LastHCOK = ok
	_ = o.Store.Upsert(ctx, c)
}

// PublishMetrics sends a periodic event.metrics. Meant to be called from a ticker.
//
// Payload contract (v1, see CP M2 spec):
//
//	{
//	  "ts":      RFC3339 timestamp,
//	  "samples": [{scope, scope_id, metric, value}, ...],
//	}
//
// host_id is intentionally omitted from the payload — the CP fills it in
// from the WS connection's registered host_id (see metrics.handler).
// scope_id for host-scoped samples is left empty for the same reason.
func (o *Orchestrator) PublishMetrics(ctx context.Context, client *ws.Client) error {
	comps, err := o.Store.List(ctx)
	if err != nil {
		return err
	}

	samples := []map[string]any{}

	// Host samples (CPU%, RAM%, load1).
	for _, hs := range metrics.CollectHost(ctx) {
		samples = append(samples, map[string]any{
			"scope":    "host",
			"scope_id": "",
			"metric":   hs.Metric,
			"value":    hs.Value,
		})
	}

	// Per-component healthcheck liveness: 1 if last hc OK, 0 if failed,
	// omitted entirely if no healthcheck has run yet. Also build a
	// name→id map for the docker stats collector (container naming
	// convention is "maestro-<component_id>").
	nameToCid := map[string]string{}
	for _, c := range comps {
		if c.LastHCAt != nil {
			v := 0.0
			if c.LastHCOK {
				v = 1.0
			}
			samples = append(samples, map[string]any{
				"scope":    "component",
				"scope_id": c.ID,
				"metric":   "healthcheck_ok",
				"value":    v,
			})
		}
		nameToCid["maestro-"+c.ID] = c.ID
	}

	// Per-container CPU + RAM (best-effort; returns nil if docker
	// is unavailable, no samples emitted in that case).
	for _, ds := range metrics.CollectDocker(ctx, nameToCid) {
		samples = append(samples, map[string]any{
			"scope":    ds.Scope,
			"scope_id": ds.ScopeID,
			"metric":   ds.Metric,
			"value":    ds.Value,
		})
	}

	payload := map[string]any{
		"ts":      time.Now().UTC().Format(time.RFC3339),
		"samples": samples,
	}
	return client.SendEvent(ws.TypeEventMetrics, payload)
}
