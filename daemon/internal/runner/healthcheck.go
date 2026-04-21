package runner

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"os/exec"
	"strings"
	"time"
)

type HealthResult struct {
	OK      bool   `json:"ok"`
	Type    string `json:"type"`
	Detail  string `json:"detail,omitempty"`
	Elapsed int64  `json:"elapsed_ms"`
}

func parseDuration(s string, fallback time.Duration) time.Duration {
	if s == "" {
		return fallback
	}
	d, err := time.ParseDuration(s)
	if err != nil {
		return fallback
	}
	return d
}

// RunHealthcheck executes the healthcheck described by the spec and retries
// according to its own schedule, up to `retries` attempts separated by `interval`.
// A nil spec is treated as OK.
func RunHealthcheck(ctx context.Context, spec map[string]any) HealthResult {
	if spec == nil {
		return HealthResult{OK: true, Type: "none"}
	}
	t, _ := spec["type"].(string)
	start := time.Now()
	interval := parseDuration(asString(spec["interval"]), 5*time.Second)
	timeout := parseDuration(asString(spec["timeout"]), 5*time.Second)
	startPeriod := parseDuration(asString(spec["start_period"]), 0)
	retries := 3
	if n, ok := spec["retries"].(float64); ok {
		retries = int(n)
	} else if n, ok := spec["retries"].(int); ok {
		retries = n
	}

	if startPeriod > 0 {
		select {
		case <-ctx.Done():
			return HealthResult{OK: false, Type: t, Detail: "cancelled", Elapsed: time.Since(start).Milliseconds()}
		case <-time.After(startPeriod):
		}
	}

	var lastErr string
	for i := 0; i < retries; i++ {
		res := runOnce(ctx, t, spec, timeout)
		if res.OK {
			res.Elapsed = time.Since(start).Milliseconds()
			return res
		}
		lastErr = res.Detail
		select {
		case <-ctx.Done():
			return HealthResult{OK: false, Type: t, Detail: "cancelled: " + lastErr, Elapsed: time.Since(start).Milliseconds()}
		case <-time.After(interval):
		}
	}
	return HealthResult{OK: false, Type: t, Detail: lastErr, Elapsed: time.Since(start).Milliseconds()}
}

func asString(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

func runOnce(ctx context.Context, t string, spec map[string]any, timeout time.Duration) HealthResult {
	c, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	switch t {
	case "http":
		return checkHTTP(c, spec)
	case "tcp":
		return checkTCP(c, spec)
	case "command":
		return checkCommand(c, spec)
	default:
		return HealthResult{OK: false, Type: t, Detail: "unknown healthcheck type"}
	}
}

func checkHTTP(ctx context.Context, spec map[string]any) HealthResult {
	url, _ := spec["url"].(string)
	if url == "" {
		return HealthResult{OK: false, Type: "http", Detail: "missing url"}
	}
	exp := 200
	if n, ok := spec["expect_status"].(float64); ok {
		exp = int(n)
	} else if n, ok := spec["expect_status"].(int); ok {
		exp = n
	}
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return HealthResult{OK: false, Type: "http", Detail: err.Error()}
	}
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return HealthResult{OK: false, Type: "http", Detail: err.Error()}
	}
	defer resp.Body.Close()
	if resp.StatusCode != exp {
		return HealthResult{OK: false, Type: "http",
			Detail: fmt.Sprintf("got status %d, expected %d", resp.StatusCode, exp)}
	}
	return HealthResult{OK: true, Type: "http"}
}

func checkTCP(ctx context.Context, spec map[string]any) HealthResult {
	host, _ := spec["host"].(string)
	if host == "" {
		host = "127.0.0.1"
	}
	var port int
	if n, ok := spec["port"].(float64); ok {
		port = int(n)
	} else if n, ok := spec["port"].(int); ok {
		port = n
	}
	if port == 0 {
		return HealthResult{OK: false, Type: "tcp", Detail: "missing port"}
	}
	addr := fmt.Sprintf("%s:%d", host, port)
	d := net.Dialer{}
	conn, err := d.DialContext(ctx, "tcp", addr)
	if err != nil {
		return HealthResult{OK: false, Type: "tcp", Detail: err.Error()}
	}
	_ = conn.Close()
	return HealthResult{OK: true, Type: "tcp"}
}

func checkCommand(ctx context.Context, spec map[string]any) HealthResult {
	cmd, _ := spec["command"].(string)
	if cmd == "" {
		return HealthResult{OK: false, Type: "command", Detail: "missing command"}
	}
	parts := strings.Fields(cmd)
	if len(parts) == 0 {
		return HealthResult{OK: false, Type: "command", Detail: "empty command"}
	}
	c := exec.CommandContext(ctx, parts[0], parts[1:]...)
	out, err := c.CombinedOutput()
	if err != nil {
		return HealthResult{OK: false, Type: "command",
			Detail: fmt.Sprintf("exit error: %v: %s", err, strings.TrimSpace(string(out)))}
	}
	return HealthResult{OK: true, Type: "command"}
}
