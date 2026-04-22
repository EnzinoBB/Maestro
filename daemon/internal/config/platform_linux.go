//go:build linux

package config

// applyPlatformDefaults adjusts Config for the current OS. On Linux, no change.
func applyPlatformDefaults(_ *Config) {}
