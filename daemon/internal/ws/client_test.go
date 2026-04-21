package ws

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"github.com/stretchr/testify/require"
)

func TestHandshakeAndRequest(t *testing.T) {
	upgrader := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}
	done := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		require.NoError(t, err)
		defer conn.Close()

		// Send hello
		hello := Message{ID: "s-1", Type: TypeHello, Payload: json.RawMessage(`{"server_version":"test"}`)}
		require.NoError(t, conn.WriteJSON(hello))

		// Expect hello_ack
		var ack Message
		require.NoError(t, conn.ReadJSON(&ack))
		require.Equal(t, TypeHelloAck, ack.Type)

		// Send a request
		req := Message{ID: "s-2", Type: TypeReqStateGet,
			Payload: json.RawMessage(`{}`)}
		require.NoError(t, conn.WriteJSON(req))

		// Expect a reply with same in_reply_to
		var resp Message
		_ = conn.SetReadDeadline(time.Now().Add(3 * time.Second))
		require.NoError(t, conn.ReadJSON(&resp))
		require.Equal(t, "s-2", resp.InReplyTo)
		require.Equal(t, TypeResStateGet, resp.Type)
		close(done)
	}))
	defer srv.Close()

	url := "ws" + strings.TrimPrefix(srv.URL, "http")
	c := &Client{
		Endpoint: url,
		HostID:   "test",
		Version:  "t1",
		Handlers: map[string]Handler{
			TypeReqStateGet: func(ctx context.Context, msg Message) (string, any, error) {
				return TypeResStateGet, map[string]any{"components": []any{}}, nil
			},
		},
		Hello: func() HandshakeInfo {
			return HandshakeInfo{DaemonVersion: "t1", RunnersAvailable: []string{"docker"}}
		},
		ReconnectMin: 100 * time.Millisecond,
		ReconnectMax: 300 * time.Millisecond,
	}
	ctx, cancel := context.WithCancel(context.Background())
	go func() {
		_ = c.Run(ctx)
	}()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("timeout")
	}
	cancel()
}
