//go:build windows

package config

// applyPlatformDefaults adjusts Config for the current OS. On Windows we
// inherit defaults set elsewhere; the daemon is supported on Linux only,
// but a no-op stub here lets developers `go build` and `go test` on
// Windows machines without breaking package consumers (e.g. for editing
// metrics/host probes).
func applyPlatformDefaults(_ *Config) {}
