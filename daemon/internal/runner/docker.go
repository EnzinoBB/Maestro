package runner

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os/exec"
	"sort"
	"strings"
	"time"
)

// DockerRunner is a thin wrapper around the docker CLI. Phase 1 prioritises
// small footprint over dependency richness; we do not link the docker engine
// SDK to keep the daemon binary tiny.
type DockerRunner struct {
	Bin string // path to docker binary (default "docker")
}

func NewDockerRunner() *DockerRunner {
	return &DockerRunner{Bin: "docker"}
}

func (d *DockerRunner) Name() string { return "docker" }

func (d *DockerRunner) docker(ctx context.Context, args ...string) (string, string, error) {
	var out, errb bytes.Buffer
	cmd := exec.CommandContext(ctx, d.bin(), args...)
	cmd.Stdout = &out
	cmd.Stderr = &errb
	err := cmd.Run()
	return out.String(), errb.String(), err
}

func (d *DockerRunner) bin() string {
	if d.Bin == "" {
		return "docker"
	}
	return d.Bin
}

// containerName returns the desired container name, falling back to rca-<id>.
func containerName(d *ComponentDeploy) string {
	if n, ok := d.Run["container_name"].(string); ok && n != "" {
		return n
	}
	return "rca-" + d.ComponentID
}

func (d *DockerRunner) inspect(ctx context.Context, name string) (map[string]any, error) {
	out, errOut, err := d.docker(ctx, "inspect", "--type", "container", name)
	if err != nil {
		if strings.Contains(errOut, "No such object") || strings.Contains(errOut, "no such container") {
			return nil, nil
		}
		return nil, fmt.Errorf("docker inspect: %v: %s", err, errOut)
	}
	var arr []map[string]any
	if err := json.Unmarshal([]byte(out), &arr); err != nil || len(arr) == 0 {
		return nil, nil
	}
	return arr[0], nil
}

func (d *DockerRunner) pullIfNeeded(ctx context.Context, image string, policy string) (string, error) {
	switch policy {
	case "never":
		return "", nil
	case "always":
		_, errOut, err := d.docker(ctx, "pull", image)
		if err != nil {
			return "", fmt.Errorf("docker pull %s: %v: %s", image, err, errOut)
		}
		return "", nil
	default: // if_not_present (default)
		_, _, err := d.docker(ctx, "image", "inspect", image)
		if err == nil {
			return "", nil
		}
		_, errOut, err := d.docker(ctx, "pull", image)
		if err != nil {
			return "", fmt.Errorf("docker pull %s: %v: %s", image, err, errOut)
		}
	}
	return "", nil
}

func (d *DockerRunner) buildArgs(dp *ComponentDeploy, name, image string) []string {
	args := []string{"run", "-d", "--name", name}
	// restart policy
	if r, _ := dp.Run["restart"].(string); r != "" && r != "no" {
		args = append(args, "--restart", r)
	}
	// ports
	if ps, ok := dp.Run["ports"].([]any); ok {
		for _, p := range ps {
			if s, ok := p.(string); ok && s != "" {
				args = append(args, "-p", s)
			}
		}
	}
	// volumes
	if vs, ok := dp.Run["volumes"].([]any); ok {
		for _, v := range vs {
			if s, ok := v.(string); ok && s != "" {
				args = append(args, "-v", s)
			}
		}
	}
	// env vars (sorted for determinism)
	env := map[string]string{}
	if e, ok := dp.Run["env"].(map[string]any); ok {
		for k, v := range e {
			env[k] = fmt.Sprint(v)
		}
	}
	for k, v := range dp.Secrets {
		env[k] = v
	}
	keys := make([]string, 0, len(env))
	for k := range env {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		args = append(args, "-e", k+"="+env[k])
	}
	// networks (first one only — `docker run --network` accepts only one at run time)
	if ns, ok := dp.Run["networks"].([]any); ok && len(ns) > 0 {
		if s, ok := ns[0].(string); ok && s != "" {
			args = append(args, "--network", s)
		}
	}
	// label for traceability
	args = append(args, "--label", "rca.component_id="+dp.ComponentID)
	args = append(args, "--label", "rca.component_hash="+dp.TargetHash)

	args = append(args, image)

	// command override
	if cmd, ok := dp.Run["command"].([]any); ok && len(cmd) > 0 {
		for _, c := range cmd {
			if s, ok := c.(string); ok {
				args = append(args, s)
			}
		}
	}
	return args
}

func (d *DockerRunner) removeIfExists(ctx context.Context, name string) error {
	// stop first (ignore errors), then remove
	_, _, _ = d.docker(ctx, "rm", "-f", name)
	return nil
}

// Deploy removes any existing container, pulls the image if needed, and starts a new one.
func (d *DockerRunner) Deploy(ctx context.Context, dp *ComponentDeploy) (*DeployResult, error) {
	t0 := time.Now()
	phases := []PhaseResult{}

	// image resolution
	image, _ := dp.Run["image"].(string)
	if image == "" {
		src := dp.Source
		if src != nil {
			img, _ := src["image"].(string)
			tag, _ := src["tag"].(string)
			if img != "" {
				if tag == "" {
					tag = "latest"
				}
				image = img + ":" + tag
			}
		}
	}
	if image == "" {
		return &DeployResult{OK: false, ComponentID: dp.ComponentID,
			Error: &ErrorInfo{Code: "validation_error",
				Message: "docker deploy requires run.image or source.image",
			},
		}, nil
	}

	// fetch phase
	fp := time.Now()
	policy, _ := asSource(dp.Source)["pull_policy"].(string)
	if _, err := d.pullIfNeeded(ctx, image, policy); err != nil {
		phases = append(phases, PhaseResult{Name: "fetch", OK: false,
			DurationMS: time.Since(fp).Milliseconds(), Detail: err.Error()})
		return &DeployResult{OK: false, ComponentID: dp.ComponentID,
			Phases: phases,
			Error: &ErrorInfo{Code: "fetch_failed", Phase: "fetch",
				Message: err.Error(),
				SuggestedFix: "check docker registry credentials and network",
			},
		}, nil
	}
	phases = append(phases, PhaseResult{Name: "fetch", OK: true, DurationMS: time.Since(fp).Milliseconds()})

	// stop old
	sp := time.Now()
	name := containerName(dp)
	_ = d.removeIfExists(ctx, name)
	phases = append(phases, PhaseResult{Name: "stop_old", OK: true, DurationMS: time.Since(sp).Milliseconds()})

	// start
	startP := time.Now()
	args := d.buildArgs(dp, name, image)
	out, errOut, err := d.docker(ctx, args...)
	if err != nil {
		phases = append(phases, PhaseResult{Name: "start", OK: false,
			DurationMS: time.Since(startP).Milliseconds(), Detail: errOut})
		return &DeployResult{OK: false, ComponentID: dp.ComponentID,
			Phases: phases,
			Error: &ErrorInfo{Code: "runtime_error", Phase: "start",
				Message: strings.TrimSpace(errOut),
				SuggestedFix: "check `docker logs` on the host for details",
			},
		}, nil
	}
	containerID := strings.TrimSpace(out)
	phases = append(phases, PhaseResult{Name: "start", OK: true, DurationMS: time.Since(startP).Milliseconds()})

	// healthcheck phase
	hp := time.Now()
	var hcDetail string
	if dp.Healthcheck != nil {
		hc := RunHealthcheck(ctx, dp.Healthcheck)
		if !hc.OK {
			phases = append(phases, PhaseResult{Name: "health", OK: false,
				DurationMS: time.Since(hp).Milliseconds(), Detail: hc.Detail})
			return &DeployResult{OK: false, ComponentID: dp.ComponentID,
				Phases: phases,
				Error: &ErrorInfo{Code: "healthcheck_failed", Phase: "health",
					Message: hc.Detail,
					SuggestedFix: "inspect container logs; ensure service is listening",
				},
				RuntimeInfo: &RuntimeInfo{ContainerID: containerID},
			}, nil
		}
		hcDetail = hc.Type
	}
	phases = append(phases, PhaseResult{Name: "health", OK: true,
		DurationMS: time.Since(hp).Milliseconds(), Detail: hcDetail})

	return &DeployResult{
		OK: true, ComponentID: dp.ComponentID, NewHash: dp.TargetHash,
		DurationMS: time.Since(t0).Milliseconds(),
		Phases: phases,
		RuntimeInfo: &RuntimeInfo{
			ContainerID:   containerID,
			ContainerName: name,
			StartedAt:     time.Now().UTC().Format(time.RFC3339),
		},
	}, nil
}

func asSource(m map[string]any) map[string]any {
	if m == nil {
		return map[string]any{}
	}
	return m
}

func (d *DockerRunner) Start(ctx context.Context, dp *ComponentDeploy) error {
	_, errOut, err := d.docker(ctx, "start", containerName(dp))
	if err != nil {
		return fmt.Errorf("docker start: %v: %s", err, errOut)
	}
	return nil
}

func (d *DockerRunner) Stop(ctx context.Context, dp *ComponentDeploy, graceful time.Duration) error {
	secs := int(graceful.Seconds())
	if secs <= 0 {
		secs = 10
	}
	_, errOut, err := d.docker(ctx, "stop", "-t", fmt.Sprint(secs), containerName(dp))
	if err != nil {
		return fmt.Errorf("docker stop: %v: %s", err, errOut)
	}
	return nil
}

func (d *DockerRunner) Status(ctx context.Context, dp *ComponentDeploy) (Status, *RuntimeInfo, error) {
	info, err := d.inspect(ctx, containerName(dp))
	if err != nil {
		return StatusUnknown, nil, err
	}
	if info == nil {
		return StatusStopped, nil, errors.New("container not found")
	}
	state, _ := info["State"].(map[string]any)
	running, _ := state["Running"].(bool)
	id, _ := info["Id"].(string)
	started, _ := state["StartedAt"].(string)
	ri := &RuntimeInfo{ContainerID: id, StartedAt: started}
	if running {
		return StatusRunning, ri, nil
	}
	return StatusStopped, ri, nil
}

func (d *DockerRunner) Logs(ctx context.Context, dp *ComponentDeploy, lines int, since time.Time) ([]string, error) {
	if lines <= 0 {
		lines = 100
	}
	args := []string{"logs", "--tail", fmt.Sprint(lines), containerName(dp)}
	out, errOut, err := d.docker(ctx, args...)
	if err != nil {
		return nil, fmt.Errorf("docker logs: %v: %s", err, errOut)
	}
	out += errOut // docker mixes streams sometimes
	out = strings.TrimRight(out, "\n")
	if out == "" {
		return []string{}, nil
	}
	return strings.Split(out, "\n"), nil
}
