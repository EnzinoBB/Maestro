package metrics

import (
	"context"
	"time"

	"github.com/rca-project/rca-daemon/internal/orchestrator"
	"github.com/rca-project/rca-daemon/internal/ws"
)

// Run publishes metrics via the orchestrator every `interval` until ctx is done.
func Run(ctx context.Context, interval time.Duration, orch *orchestrator.Orchestrator, client *ws.Client) {
	if interval <= 0 {
		interval = 30 * time.Second
	}
	t := time.NewTicker(interval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			if client.Connected() {
				_ = orch.PublishMetrics(ctx, client)
			}
		}
	}
}
