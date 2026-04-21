package state

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestCRUDAndHistory(t *testing.T) {
	dir := t.TempDir()
	st, err := Open(filepath.Join(dir, "s.db"))
	require.NoError(t, err)
	defer st.Close()

	ctx := context.Background()
	now := time.Now()
	err = st.Upsert(ctx, &Component{
		ID: "api", Status: "running", ComponentHash: "h1",
		Runner: "docker", ContainerID: "c1", StartedAt: &now, LastHCOK: true,
	})
	require.NoError(t, err)

	c, err := st.Get(ctx, "api")
	require.NoError(t, err)
	require.Equal(t, "running", c.Status)
	require.Equal(t, "h1", c.ComponentHash)
	require.True(t, c.LastHCOK)

	// Update
	err = st.Upsert(ctx, &Component{ID: "api", Status: "stopped", ComponentHash: "h1", Runner: "docker"})
	require.NoError(t, err)
	c, err = st.Get(ctx, "api")
	require.NoError(t, err)
	require.Equal(t, "stopped", c.Status)

	// List
	err = st.Upsert(ctx, &Component{ID: "db", Status: "running"})
	require.NoError(t, err)
	lst, err := st.List(ctx)
	require.NoError(t, err)
	require.Len(t, lst, 2)

	// History
	err = st.AppendHistory(ctx, "api", "h1")
	require.NoError(t, err)
	err = st.AppendHistory(ctx, "api", "h2")
	require.NoError(t, err)
	hist, err := st.History(ctx, "api", 10)
	require.NoError(t, err)
	require.Len(t, hist, 2)
	require.Equal(t, "h2", hist[0].ComponentHash)

	// Delete
	require.NoError(t, st.Delete(ctx, "api"))
	_, err = st.Get(ctx, "api")
	require.ErrorIs(t, err, ErrNotFound)
}
