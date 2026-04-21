package runner

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"runtime"
	"strconv"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestHTTPCheckOK(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(200)
	}))
	defer srv.Close()
	res := RunHealthcheck(context.Background(), map[string]any{
		"type": "http", "url": srv.URL, "expect_status": 200,
		"retries": 2, "timeout": "2s", "interval": "50ms",
	})
	require.True(t, res.OK, res.Detail)
}

func TestHTTPCheckBadStatus(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(503)
	}))
	defer srv.Close()
	res := RunHealthcheck(context.Background(), map[string]any{
		"type": "http", "url": srv.URL, "expect_status": 200,
		"retries": 2, "timeout": "2s", "interval": "50ms",
	})
	require.False(t, res.OK)
	require.Contains(t, res.Detail, "503")
}

func TestTCPCheck(t *testing.T) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	defer l.Close()
	_, port, _ := net.SplitHostPort(l.Addr().String())
	p, _ := strconv.Atoi(port)
	res := RunHealthcheck(context.Background(), map[string]any{
		"type": "tcp", "host": "127.0.0.1", "port": p,
		"retries": 1, "timeout": "500ms",
	})
	require.True(t, res.OK, res.Detail)
}

func TestCommandCheck(t *testing.T) {
	// Skip on Windows: echo is a shell builtin, not an exec target.
	if runtime.GOOS == "windows" {
		t.Skip("windows: echo is a shell builtin")
	}
	res := RunHealthcheck(context.Background(), map[string]any{
		"type": "command", "command": "/bin/true",
		"retries": 1, "timeout": "5s",
	})
	require.True(t, res.OK, res.Detail)
}
