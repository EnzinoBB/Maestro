package ws

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math/rand"
	"net/http"
	"net/url"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"
)

// Handler processes an incoming request message and returns a reply payload.
// Return a nil payload to ignore. For events, use the special SendEvent API.
type Handler func(ctx context.Context, msg Message) (replyType string, payload any, err error)

// HandshakeInfo sent to the control plane on hello_ack.
type HandshakeInfo struct {
	DaemonVersion    string         `json:"daemon_version"`
	RunnersAvailable []string       `json:"runners_available"`
	ComponentsKnown  []ComponentRef `json:"components_known"`
	System           map[string]any `json:"system"`
}

type ComponentRef struct {
	ID            string `json:"id"`
	ComponentHash string `json:"component_hash"`
	Status        string `json:"status"`
}

type Client struct {
	Endpoint     string
	Token        string
	HostID       string
	Version      string
	Insecure     bool
	Hello        func() HandshakeInfo
	Handlers     map[string]Handler
	OnConnected  func(ctx context.Context)
	ReconnectMin time.Duration
	ReconnectMax time.Duration
	Logger       *slog.Logger

	conn       atomic.Pointer[websocket.Conn]
	sendMu     sync.Mutex
	connected  atomic.Bool
	stop       chan struct{}
}

func (c *Client) logger() *slog.Logger {
	if c.Logger != nil {
		return c.Logger
	}
	return slog.Default()
}

func (c *Client) Connected() bool { return c.connected.Load() }

// Run blocks until ctx is done. It keeps the connection alive, reconnecting on failure.
func (c *Client) Run(ctx context.Context) error {
	if c.stop == nil {
		c.stop = make(chan struct{})
	}
	if c.ReconnectMin == 0 {
		c.ReconnectMin = time.Second
	}
	if c.ReconnectMax == 0 {
		c.ReconnectMax = 60 * time.Second
	}
	if c.Handlers == nil {
		c.Handlers = map[string]Handler{}
	}
	backoff := c.ReconnectMin
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		err := c.connectOnce(ctx)
		if err != nil {
			c.logger().Warn("ws connect failed", "err", err, "backoff", backoff)
			jitter := time.Duration(rand.Int63n(int64(backoff / 5)))
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(backoff + jitter):
			}
			backoff *= 2
			if backoff > c.ReconnectMax {
				backoff = c.ReconnectMax
			}
			continue
		}
		backoff = c.ReconnectMin
	}
}

func (c *Client) connectOnce(ctx context.Context) error {
	u, err := url.Parse(c.Endpoint)
	if err != nil {
		return err
	}
	q := u.Query()
	q.Set("host_id", c.HostID)
	if c.Token != "" {
		q.Set("token", c.Token)
	}
	u.RawQuery = q.Encode()

	dialer := *websocket.DefaultDialer
	dialer.HandshakeTimeout = 15 * time.Second
	if c.Insecure {
		dialer.TLSClientConfig = &tls.Config{InsecureSkipVerify: true}
	}
	hdr := http.Header{}
	if c.Token != "" {
		hdr.Set("Authorization", "Bearer "+c.Token)
	}
	hdr.Set("X-Maestro-Daemon-Id", c.HostID)
	hdr.Set("X-Maestro-Daemon-Version", c.Version)

	conn, resp, err := dialer.DialContext(ctx, u.String(), hdr)
	if err != nil {
		if resp != nil {
			return fmt.Errorf("dial: %w (status %d)", err, resp.StatusCode)
		}
		return fmt.Errorf("dial: %w", err)
	}
	c.conn.Store(conn)
	c.connected.Store(true)
	defer func() {
		c.connected.Store(false)
		conn.Close()
		c.conn.Store(nil)
	}()

	// Expect hello
	var hello Message
	if err := conn.ReadJSON(&hello); err != nil {
		return fmt.Errorf("read hello: %w", err)
	}
	if hello.Type != TypeHello {
		return fmt.Errorf("expected hello, got %q", hello.Type)
	}
	info := HandshakeInfo{}
	if c.Hello != nil {
		info = c.Hello()
	}
	ack, err := NewReply(hello, TypeHelloAck, info)
	if err != nil {
		return err
	}
	if err := c.writeJSON(conn, ack); err != nil {
		return fmt.Errorf("write hello_ack: %w", err)
	}

	c.logger().Info("ws connected", "endpoint", c.Endpoint, "host_id", c.HostID)
	if c.OnConnected != nil {
		c.OnConnected(ctx)
	}

	// Heartbeat writer
	hbCtx, hbCancel := context.WithCancel(ctx)
	defer hbCancel()
	go c.heartbeatLoop(hbCtx, conn, 15*time.Second)

	// Read loop
	for {
		var msg Message
		if err := conn.ReadJSON(&msg); err != nil {
			return fmt.Errorf("read: %w", err)
		}
		c.handle(ctx, conn, msg)
	}
}

func (c *Client) heartbeatLoop(ctx context.Context, conn *websocket.Conn, interval time.Duration) {
	t := time.NewTicker(interval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			m, _ := NewMessage(TypePing, nil)
			if err := c.writeJSON(conn, m); err != nil {
				return
			}
		}
	}
}

func (c *Client) writeJSON(conn *websocket.Conn, m Message) error {
	c.sendMu.Lock()
	defer c.sendMu.Unlock()
	return conn.WriteJSON(m)
}

func (c *Client) handle(ctx context.Context, conn *websocket.Conn, msg Message) {
	switch msg.Type {
	case TypePing:
		pong := Message{ID: msg.ID, Type: TypePong, InReplyTo: msg.ID}
		_ = c.writeJSON(conn, pong)
		return
	case TypePong:
		return
	}

	h, ok := c.Handlers[msg.Type]
	if !ok {
		errPayload := map[string]any{
			"ok": false,
			"error": map[string]string{
				"code":    "not_supported",
				"message": "unknown request type: " + msg.Type,
			},
		}
		reply, _ := NewReply(msg, "response.error", errPayload)
		_ = c.writeJSON(conn, reply)
		return
	}

	go func() {
		// Each request handled in its own goroutine to allow concurrency.
		opCtx, cancel := context.WithTimeout(ctx, 15*time.Minute)
		defer cancel()
		replyType, payload, err := h(opCtx, msg)
		if err != nil && replyType == "" {
			replyType = "response.error"
			payload = map[string]any{
				"ok":    false,
				"error": map[string]string{"code": "internal", "message": err.Error()},
			}
		}
		if replyType == "" {
			return
		}
		reply, berr := NewReply(msg, replyType, payload)
		if berr != nil {
			c.logger().Error("reply marshal", "err", berr)
			return
		}
		if werr := c.writeJSON(conn, reply); werr != nil {
			c.logger().Error("reply send", "err", werr)
		}
	}()
}

// SendEvent publishes an event (async, not a reply). Returns error if offline.
func (c *Client) SendEvent(eventType string, payload any) error {
	conn := c.conn.Load()
	if conn == nil || !c.connected.Load() {
		return errors.New("not connected")
	}
	m, err := NewMessage(eventType, payload)
	if err != nil {
		return err
	}
	return c.writeJSON(conn, m)
}

// Payload helpers --------------------------------------------------------

func ParsePayload[T any](msg Message, out *T) error {
	if len(msg.Payload) == 0 {
		return nil
	}
	return json.Unmarshal(msg.Payload, out)
}
