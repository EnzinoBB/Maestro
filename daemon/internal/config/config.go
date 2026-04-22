package config

import (
	"fmt"
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

// Config holds daemon configuration loaded from /etc/maestrod/config.yaml.
type Config struct {
	HostID         string `yaml:"host_id"`
	Endpoint       string `yaml:"endpoint"`
	Token          string `yaml:"token"`
	WorkingDir     string `yaml:"working_dir"`
	StatePath      string `yaml:"state_path"`
	DockerEnabled  bool   `yaml:"docker_enabled"`
	SystemdEnabled bool   `yaml:"systemd_enabled"`
	Insecure       bool   `yaml:"insecure"`
	MetricsIntervS int    `yaml:"metrics_interval_sec"`
}

func (c *Config) Defaults() {
	if c.WorkingDir == "" {
		c.WorkingDir = "/var/lib/maestrod"
	}
	if c.StatePath == "" {
		c.StatePath = filepath.Join(c.WorkingDir, "state.db")
	}
	if c.MetricsIntervS == 0 {
		c.MetricsIntervS = 30
	}
}

func (c *Config) Validate() error {
	if c.HostID == "" {
		return fmt.Errorf("host_id is required")
	}
	if c.Endpoint == "" {
		return fmt.Errorf("endpoint is required")
	}
	return nil
}

// Load reads config from path; env vars override: MAESTROD_HOST_ID, MAESTROD_ENDPOINT,
// MAESTROD_TOKEN, MAESTROD_WORKING_DIR, MAESTROD_INSECURE=1.
func Load(path string) (*Config, error) {
	c := &Config{}
	if path != "" {
		data, err := os.ReadFile(path)
		if err != nil && !os.IsNotExist(err) {
			return nil, fmt.Errorf("read %s: %w", path, err)
		}
		if len(data) > 0 {
			if err := yaml.Unmarshal(data, c); err != nil {
				return nil, fmt.Errorf("parse %s: %w", path, err)
			}
		}
	}
	if v := os.Getenv("MAESTROD_HOST_ID"); v != "" {
		c.HostID = v
	}
	if v := os.Getenv("MAESTROD_ENDPOINT"); v != "" {
		c.Endpoint = v
	}
	if v := os.Getenv("MAESTROD_TOKEN"); v != "" {
		c.Token = v
	}
	if v := os.Getenv("MAESTROD_WORKING_DIR"); v != "" {
		c.WorkingDir = v
	}
	if v := os.Getenv("MAESTROD_STATE_PATH"); v != "" {
		c.StatePath = v
	}
	if v := os.Getenv("MAESTROD_INSECURE"); v == "1" || v == "true" {
		c.Insecure = true
	}
	if os.Getenv("MAESTROD_DOCKER") != "0" {
		c.DockerEnabled = true
	}
	if os.Getenv("MAESTROD_SYSTEMD") != "0" {
		c.SystemdEnabled = true
	}
	c.Defaults()
	return c, c.Validate()
}
