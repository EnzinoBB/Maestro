package runner

import (
	"context"
	"time"
)

// ComponentDeploy is the fully-prepared spec sent by the control plane.
// Only the fields relevant for Phase 1 are represented.
type ComponentDeploy struct {
	ComponentID string                 `json:"component_id"`
	TargetHash  string                 `json:"target_hash"`
	DeployMode  string                 `json:"deploy_mode"`
	Source      map[string]any         `json:"source"`
	BuildSteps  []BuildStep            `json:"build_steps"`
	ConfigFiles []ConfigFile           `json:"config_files"`
	Run         map[string]any         `json:"run"`
	Healthcheck map[string]any         `json:"healthcheck"`
	Secrets     map[string]string      `json:"secrets"`
	TimeoutSec  int                    `json:"timeout_sec"`
	Extra       map[string]any         `json:"-"`
}

type BuildStep struct {
	Command    string            `json:"command"`
	Env        map[string]string `json:"env"`
	WorkingDir string            `json:"working_dir"`
	Timeout    string            `json:"timeout"`
}

type ConfigFile struct {
	Dest       string `json:"dest"`
	Mode       int    `json:"mode"`
	ContentB64 string `json:"content_b64"`
}

type DeployResult struct {
	OK          bool            `json:"ok"`
	ComponentID string          `json:"component_id"`
	NewHash     string          `json:"new_hash"`
	DurationMS  int64           `json:"duration_ms"`
	Phases      []PhaseResult   `json:"phases"`
	Error       *ErrorInfo      `json:"error,omitempty"`
	RuntimeInfo *RuntimeInfo    `json:"runtime_info,omitempty"`
}

type PhaseResult struct {
	Name       string `json:"name"`
	OK         bool   `json:"ok"`
	DurationMS int64  `json:"duration_ms"`
	Detail     string `json:"detail,omitempty"`
}

type ErrorInfo struct {
	Code          string `json:"code"`
	Phase         string `json:"phase,omitempty"`
	Message       string `json:"message"`
	Details       any    `json:"details,omitempty"`
	SuggestedFix  string `json:"suggested_fix,omitempty"`
}

type RuntimeInfo struct {
	PID           int    `json:"pid,omitempty"`
	ContainerID   string `json:"container_id,omitempty"`
	ContainerName string `json:"container_name,omitempty"`
	UnitName      string `json:"unit_name,omitempty"`
	WorkDir       string `json:"work_dir,omitempty"`
	StartedAt     string `json:"started_at,omitempty"`
}

type Status string

const (
	StatusRunning  Status = "running"
	StatusStopped  Status = "stopped"
	StatusFailed   Status = "failed"
	StatusUnknown  Status = "unknown"
	StatusDeploying Status = "deploying"
)

// Runner is the capability interface a component type implements (docker, systemd).
type Runner interface {
	Name() string
	Deploy(ctx context.Context, d *ComponentDeploy) (*DeployResult, error)
	Start(ctx context.Context, d *ComponentDeploy) error
	Stop(ctx context.Context, d *ComponentDeploy, graceful time.Duration) error
	Status(ctx context.Context, d *ComponentDeploy) (Status, *RuntimeInfo, error)
	Logs(ctx context.Context, d *ComponentDeploy, lines int, since time.Time) ([]string, error)
}
