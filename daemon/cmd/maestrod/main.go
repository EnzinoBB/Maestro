package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/maestro-project/maestro-daemon/internal/config"
	"github.com/maestro-project/maestro-daemon/internal/metrics"
	"github.com/maestro-project/maestro-daemon/internal/orchestrator"
	"github.com/maestro-project/maestro-daemon/internal/runner"
	"github.com/maestro-project/maestro-daemon/internal/state"
	"github.com/maestro-project/maestro-daemon/internal/ws"
)

const Version = "0.1.0"

func main() {
	var (
		cfgPath    = flag.String("config", "/etc/maestrod/config.yaml", "Path to daemon config")
		showVer    = flag.Bool("version", false, "Print version and exit")
		debug      = flag.Bool("debug", false, "Enable debug logging")
	)
	flag.Parse()
	if *showVer {
		fmt.Printf("maestrod %s\n", Version)
		return
	}

	lvl := slog.LevelInfo
	if *debug {
		lvl = slog.LevelDebug
	}
	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: lvl}))
	slog.SetDefault(log)

	cfg, err := config.Load(*cfgPath)
	if err != nil {
		log.Error("config load failed", "err", err)
		os.Exit(2)
	}
	log.Info("maestrod starting", "version", Version, "host_id", cfg.HostID, "endpoint", cfg.Endpoint)

	st, err := state.Open(cfg.StatePath)
	if err != nil {
		log.Error("state open failed", "err", err)
		os.Exit(2)
	}
	defer st.Close()

	orch := &orchestrator.Orchestrator{
		Store:   st,
		Version: Version,
		Logger:  log,
	}
	if cfg.DockerEnabled {
		orch.Docker = runner.NewDockerRunner()
	}
	if cfg.SystemdEnabled {
		orch.Systemd = runner.NewSystemdRunner()
	}

	client := &ws.Client{
		Endpoint: cfg.Endpoint,
		Token:    cfg.Token,
		HostID:   cfg.HostID,
		Version:  Version,
		Insecure: cfg.Insecure,
		Hello:    orch.HelloInfo,
		Handlers: orch.Handlers(),
		Logger:   log,
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigc := make(chan os.Signal, 1)
	signal.Notify(sigc, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-sigc
		log.Info("signal received, shutting down")
		cancel()
	}()

	go metrics.Run(ctx, time.Duration(cfg.MetricsIntervS)*time.Second, orch, client)

	if err := client.Run(ctx); err != nil && err != context.Canceled {
		log.Error("ws client terminated", "err", err)
	}
}
