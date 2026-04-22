//go:build darwin

package config

// applyPlatformDefaults adjusts Config for the current OS. On Darwin, systemd
// is not available, so SystemdEnabled is always forced off regardless of
// config file contents or env vars.
func applyPlatformDefaults(c *Config) {
	c.SystemdEnabled = false
}
