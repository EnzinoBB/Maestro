package config

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestLoadFromFile(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "maestrod.yaml")
	require.NoError(t, os.WriteFile(p, []byte(`
host_id: testhost
endpoint: wss://cp/ws/daemon
token: abc
working_dir: /tmp/maestrod
`), 0o644))
	c, err := Load(p)
	require.NoError(t, err)
	require.Equal(t, "testhost", c.HostID)
	require.Equal(t, "wss://cp/ws/daemon", c.Endpoint)
	require.Equal(t, filepath.Join("/tmp/maestrod", "state.db"), c.StatePath)
	require.Equal(t, 30, c.MetricsIntervS)
}

func TestEnvOverrides(t *testing.T) {
	t.Setenv("MAESTROD_HOST_ID", "envhost")
	t.Setenv("MAESTROD_ENDPOINT", "ws://x")
	c, err := Load("")
	require.NoError(t, err)
	require.Equal(t, "envhost", c.HostID)
	require.Equal(t, "ws://x", c.Endpoint)
}

func TestValidateMissing(t *testing.T) {
	_, err := Load("")
	require.Error(t, err)
}

func TestLoadNormalizesHTTPEndpointToWS(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.yaml")
	body := []byte(`
host_id: host1
endpoint: https://cp.example/ws/daemon
token: t
`)
	if err := os.WriteFile(path, body, 0600); err != nil {
		t.Fatal(err)
	}
	c, err := Load(path)
	if err != nil {
		t.Fatalf("Load err: %v", err)
	}
	if c.Endpoint != "wss://cp.example/ws/daemon" {
		t.Fatalf("expected wss:// endpoint, got %q", c.Endpoint)
	}
}

func TestLoadLeavesWSEndpointAlone(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.yaml")
	body := []byte(`
host_id: host1
endpoint: wss://cp.example/ws/daemon
token: t
`)
	if err := os.WriteFile(path, body, 0600); err != nil {
		t.Fatal(err)
	}
	c, err := Load(path)
	if err != nil {
		t.Fatalf("Load err: %v", err)
	}
	if c.Endpoint != "wss://cp.example/ws/daemon" {
		t.Fatalf("expected endpoint unchanged, got %q", c.Endpoint)
	}
}
