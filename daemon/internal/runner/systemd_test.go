package runner

import (
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestRenderUnitMinimal(t *testing.T) {
	d := &ComponentDeploy{
		ComponentID: "demo",
		Run: map[string]any{
			"command":           "/usr/bin/node /opt/demo/server.js",
			"working_directory": "/opt/demo",
			"user":              "demo",
			"env":               map[string]any{"NODE_ENV": "production", "PORT": 3000},
			"restart":           "on-failure",
			"restart_sec":       7,
		},
	}
	out, err := RenderUnit(d)
	require.NoError(t, err)
	require.Contains(t, out, "ExecStart=/usr/bin/node /opt/demo/server.js")
	require.Contains(t, out, "WorkingDirectory=/opt/demo")
	require.Contains(t, out, "User=demo")
	require.Contains(t, out, "Environment=NODE_ENV=production")
	require.Contains(t, out, "Environment=PORT=3000")
	require.Contains(t, out, "Restart=on-failure")
	require.Contains(t, out, "RestartSec=7")
}

func TestRenderUnitMissingCommand(t *testing.T) {
	d := &ComponentDeploy{ComponentID: "x", Run: map[string]any{}}
	_, err := RenderUnit(d)
	require.Error(t, err)
}

func TestUnitName(t *testing.T) {
	require.Equal(t, "maestro-foo.service", unitName(&ComponentDeploy{ComponentID: "foo", Run: map[string]any{}}))
	require.Equal(t, "maestro-custom.service", unitName(&ComponentDeploy{ComponentID: "foo", Run: map[string]any{"unit_name": "custom"}}))
	require.Equal(t, "bar.service", unitName(&ComponentDeploy{ComponentID: "foo", Run: map[string]any{"unit_name": "bar.service"}}))
}

func TestWriteConfigFilesBadBase64(t *testing.T) {
	dir := t.TempDir()
	err := WriteConfigFiles(dir, []ConfigFile{{Dest: "conf.txt", Mode: 0o600, ContentB64: "!!!not base64!!!"}})
	require.Error(t, err)
	require.True(t, strings.Contains(err.Error(), "decode"))
}
