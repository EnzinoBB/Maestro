package config

import (
	"runtime"
	"testing"
)

func TestPlatformGating_DisablesSystemdOnDarwin(t *testing.T) {
	c := &Config{SystemdEnabled: true}
	applyPlatformDefaults(c)
	if runtime.GOOS == "darwin" && c.SystemdEnabled {
		t.Fatal("expected SystemdEnabled=false on darwin, got true")
	}
	if runtime.GOOS == "linux" && !c.SystemdEnabled {
		t.Fatal("expected SystemdEnabled=true on linux, got false")
	}
}

func TestPlatformGating_LeavesDockerEnabledAlone(t *testing.T) {
	c := &Config{DockerEnabled: true, SystemdEnabled: true}
	applyPlatformDefaults(c)
	if !c.DockerEnabled {
		t.Fatal("expected DockerEnabled=true after platform gating, got false")
	}
}
