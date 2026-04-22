package runner

import (
	"bytes"
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"text/template"
	"time"
)

const systemdUnitTemplate = `[Unit]
Description=Maestro managed: {{.ComponentID}}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={{.Command}}
{{- if .WorkingDirectory }}
WorkingDirectory={{.WorkingDirectory}}
{{- end }}
{{- if .User }}
User={{.User}}
{{- end }}
{{- if .Group }}
Group={{.Group}}
{{- end }}
{{- range $k, $v := .Env }}
Environment={{$k}}={{$v}}
{{- end }}
Restart={{.Restart}}
RestartSec={{.RestartSec}}
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
`

// SystemdRunner deploys a component as a managed systemd service.
type SystemdRunner struct {
	WorkingDirRoot string                   // root for component files (e.g. /opt/maestro)
	UnitDir        string                   // where to write unit files (/etc/systemd/system)
	Systemctl      string                   // path to systemctl
	Exec           func(context.Context, string, ...string) (string, string, error) // overridable for tests
}

func NewSystemdRunner() *SystemdRunner {
	return &SystemdRunner{
		WorkingDirRoot: "/opt/maestro",
		UnitDir:        "/etc/systemd/system",
		Systemctl:      "systemctl",
	}
}

func (r *SystemdRunner) Name() string { return "systemd" }

func (r *SystemdRunner) systemctl(ctx context.Context, args ...string) (string, string, error) {
	if r.Exec != nil {
		return r.Exec(ctx, r.Systemctl, args...)
	}
	var out, errb bytes.Buffer
	cmd := exec.CommandContext(ctx, r.Systemctl, args...)
	cmd.Stdout = &out
	cmd.Stderr = &errb
	err := cmd.Run()
	return out.String(), errb.String(), err
}

func unitName(d *ComponentDeploy) string {
	if u, ok := d.Run["unit_name"].(string); ok && u != "" {
		if strings.HasSuffix(u, ".service") {
			return u
		}
		return "maestro-" + u + ".service"
	}
	return "maestro-" + d.ComponentID + ".service"
}

func (r *SystemdRunner) componentDir(d *ComponentDeploy) string {
	return filepath.Join(r.WorkingDirRoot, d.ComponentID)
}

type unitCtx struct {
	ComponentID      string
	Command          string
	WorkingDirectory string
	User             string
	Group            string
	Env              map[string]string
	Restart          string
	RestartSec       int
}

// RenderUnit returns the unit file contents for the given deploy spec.
func RenderUnit(d *ComponentDeploy) (string, error) {
	run := d.Run
	cmd, _ := run["command"].(string)
	if cmd == "" {
		return "", errors.New("systemd run requires 'command'")
	}
	wd, _ := run["working_directory"].(string)
	user, _ := run["user"].(string)
	group, _ := run["group"].(string)
	restart, _ := run["restart"].(string)
	if restart == "" {
		restart = "on-failure"
	}
	restartSec := 5
	if n, ok := run["restart_sec"].(float64); ok {
		restartSec = int(n)
	} else if n, ok := run["restart_sec"].(int); ok {
		restartSec = n
	}
	env := map[string]string{}
	if e, ok := run["env"].(map[string]any); ok {
		for k, v := range e {
			env[k] = fmt.Sprint(v)
		}
	}
	for k, v := range d.Secrets {
		env[k] = v
	}
	// Deterministic order
	keys := make([]string, 0, len(env))
	for k := range env {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	ordered := map[string]string{}
	for _, k := range keys {
		ordered[k] = env[k]
	}
	ctx := unitCtx{
		ComponentID:      d.ComponentID,
		Command:          cmd,
		WorkingDirectory: wd,
		User:             user,
		Group:            group,
		Env:              ordered,
		Restart:          restart,
		RestartSec:       restartSec,
	}
	tmpl := template.Must(template.New("unit").Parse(systemdUnitTemplate))
	var out bytes.Buffer
	if err := tmpl.Execute(&out, ctx); err != nil {
		return "", err
	}
	return out.String(), nil
}

func writeConfigFiles(baseDir string, files []ConfigFile) error {
	for _, f := range files {
		dest := f.Dest
		if dest == "" {
			continue
		}
		if !filepath.IsAbs(dest) {
			dest = filepath.Join(baseDir, dest)
		}
		if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
			return fmt.Errorf("mkdir %s: %w", filepath.Dir(dest), err)
		}
		data, err := base64.StdEncoding.DecodeString(f.ContentB64)
		if err != nil {
			return fmt.Errorf("decode %s: %w", dest, err)
		}
		mode := os.FileMode(f.Mode)
		if mode == 0 {
			mode = 0o640
		}
		if err := os.WriteFile(dest, data, mode); err != nil {
			return fmt.Errorf("write %s: %w", dest, err)
		}
	}
	return nil
}

func (r *SystemdRunner) Deploy(ctx context.Context, d *ComponentDeploy) (*DeployResult, error) {
	t0 := time.Now()
	phases := []PhaseResult{}

	// Prepare component directory
	dir := r.componentDir(d)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, fmt.Errorf("mkdir %s: %w", dir, err)
	}
	phases = append(phases, PhaseResult{Name: "prepare", OK: true, DurationMS: time.Since(t0).Milliseconds()})

	// Write config files
	cp := time.Now()
	if err := writeConfigFiles(dir, d.ConfigFiles); err != nil {
		phases = append(phases, PhaseResult{Name: "config", OK: false, DurationMS: time.Since(cp).Milliseconds(), Detail: err.Error()})
		return &DeployResult{OK: false, ComponentID: d.ComponentID, Phases: phases,
			Error: &ErrorInfo{Code: "config_error", Phase: "config", Message: err.Error()}}, nil
	}
	phases = append(phases, PhaseResult{Name: "config", OK: true, DurationMS: time.Since(cp).Milliseconds()})

	// Render and write unit file
	up := time.Now()
	unit, err := RenderUnit(d)
	if err != nil {
		phases = append(phases, PhaseResult{Name: "unit", OK: false, DurationMS: time.Since(up).Milliseconds(), Detail: err.Error()})
		return &DeployResult{OK: false, ComponentID: d.ComponentID, Phases: phases,
			Error: &ErrorInfo{Code: "validation_error", Phase: "unit", Message: err.Error()}}, nil
	}
	uName := unitName(d)
	unitPath := filepath.Join(r.UnitDir, uName)
	if err := os.WriteFile(unitPath, []byte(unit), 0o644); err != nil {
		phases = append(phases, PhaseResult{Name: "unit", OK: false, DurationMS: time.Since(up).Milliseconds(), Detail: err.Error()})
		return &DeployResult{OK: false, ComponentID: d.ComponentID, Phases: phases,
			Error: &ErrorInfo{Code: "runtime_error", Phase: "unit", Message: err.Error(),
				SuggestedFix: "run daemon as root or grant write to " + r.UnitDir}}, nil
	}
	phases = append(phases, PhaseResult{Name: "unit", OK: true, DurationMS: time.Since(up).Milliseconds()})

	// daemon-reload, enable, restart
	for _, step := range [][]string{
		{"daemon-reload"},
		{"enable", uName},
		{"restart", uName},
	} {
		sp := time.Now()
		if _, errOut, err := r.systemctl(ctx, step...); err != nil {
			phases = append(phases, PhaseResult{Name: "systemctl." + step[0], OK: false,
				DurationMS: time.Since(sp).Milliseconds(), Detail: errOut})
			return &DeployResult{OK: false, ComponentID: d.ComponentID, Phases: phases,
				Error: &ErrorInfo{Code: "runtime_error", Phase: "systemctl", Message: errOut,
					SuggestedFix: "check systemd logs: journalctl -xe -u " + uName}}, nil
		}
		phases = append(phases, PhaseResult{Name: "systemctl." + step[0], OK: true, DurationMS: time.Since(sp).Milliseconds()})
	}

	// healthcheck
	hp := time.Now()
	var hcDetail string
	if d.Healthcheck != nil {
		hc := RunHealthcheck(ctx, d.Healthcheck)
		if !hc.OK {
			phases = append(phases, PhaseResult{Name: "health", OK: false, DurationMS: time.Since(hp).Milliseconds(), Detail: hc.Detail})
			return &DeployResult{OK: false, ComponentID: d.ComponentID, Phases: phases,
				Error: &ErrorInfo{Code: "healthcheck_failed", Phase: "health", Message: hc.Detail,
					SuggestedFix: "inspect journalctl -u " + uName}}, nil
		}
		hcDetail = hc.Type
	}
	phases = append(phases, PhaseResult{Name: "health", OK: true, DurationMS: time.Since(hp).Milliseconds(), Detail: hcDetail})

	return &DeployResult{
		OK: true, ComponentID: d.ComponentID, NewHash: d.TargetHash,
		DurationMS: time.Since(t0).Milliseconds(),
		Phases: phases,
		RuntimeInfo: &RuntimeInfo{
			UnitName: uName, WorkDir: dir,
			StartedAt: time.Now().UTC().Format(time.RFC3339),
		},
	}, nil
}

func (r *SystemdRunner) Start(ctx context.Context, d *ComponentDeploy) error {
	_, errOut, err := r.systemctl(ctx, "start", unitName(d))
	if err != nil {
		return fmt.Errorf("systemctl start: %v: %s", err, errOut)
	}
	return nil
}

func (r *SystemdRunner) Stop(ctx context.Context, d *ComponentDeploy, graceful time.Duration) error {
	_, errOut, err := r.systemctl(ctx, "stop", unitName(d))
	if err != nil {
		return fmt.Errorf("systemctl stop: %v: %s", err, errOut)
	}
	return nil
}

func (r *SystemdRunner) Status(ctx context.Context, d *ComponentDeploy) (Status, *RuntimeInfo, error) {
	out, _, err := r.systemctl(ctx, "is-active", unitName(d))
	state := strings.TrimSpace(out)
	ri := &RuntimeInfo{UnitName: unitName(d)}
	// is-active returns non-zero for inactive; treat as stopped.
	_ = err
	switch state {
	case "active":
		return StatusRunning, ri, nil
	case "activating":
		return StatusDeploying, ri, nil
	case "inactive", "deactivating":
		return StatusStopped, ri, nil
	case "failed":
		return StatusFailed, ri, nil
	default:
		return StatusUnknown, ri, nil
	}
}

func (r *SystemdRunner) Logs(ctx context.Context, d *ComponentDeploy, lines int, since time.Time) ([]string, error) {
	if lines <= 0 {
		lines = 100
	}
	args := []string{"-u", unitName(d), "--no-pager", "-n", fmt.Sprint(lines), "-o", "short-iso"}
	var out, errb bytes.Buffer
	cmd := exec.CommandContext(ctx, "journalctl", args...)
	cmd.Stdout = &out
	cmd.Stderr = &errb
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("journalctl: %v: %s", err, errb.String())
	}
	s := strings.TrimRight(out.String(), "\n")
	if s == "" {
		return []string{}, nil
	}
	return strings.Split(s, "\n"), nil
}
