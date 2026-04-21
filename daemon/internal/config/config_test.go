package config

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestLoadFromFile(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "rcad.yaml")
	require.NoError(t, os.WriteFile(p, []byte(`
host_id: testhost
endpoint: wss://cp/ws/daemon
token: abc
working_dir: /tmp/rcad
`), 0o644))
	c, err := Load(p)
	require.NoError(t, err)
	require.Equal(t, "testhost", c.HostID)
	require.Equal(t, "wss://cp/ws/daemon", c.Endpoint)
	require.Equal(t, filepath.Join("/tmp/rcad", "state.db"), c.StatePath)
	require.Equal(t, 30, c.MetricsIntervS)
}

func TestEnvOverrides(t *testing.T) {
	t.Setenv("RCAD_HOST_ID", "envhost")
	t.Setenv("RCAD_ENDPOINT", "ws://x")
	c, err := Load("")
	require.NoError(t, err)
	require.Equal(t, "envhost", c.HostID)
	require.Equal(t, "ws://x", c.Endpoint)
}

func TestValidateMissing(t *testing.T) {
	_, err := Load("")
	require.Error(t, err)
}
