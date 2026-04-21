package ws

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"time"
)

// Message mirrors docs/protocol.md envelope.
type Message struct {
	ID        string          `json:"id"`
	Type      string          `json:"type"`
	InReplyTo string          `json:"in_reply_to,omitempty"`
	Payload   json.RawMessage `json:"payload,omitempty"`
	TS        string          `json:"ts,omitempty"`
}

// Type constants
const (
	TypeHello    = "hello"
	TypeHelloAck = "hello_ack"
	TypeBye      = "bye"
	TypePing     = "ping"
	TypePong     = "pong"

	TypeReqStateGet = "request.state.get"
	TypeResStateGet = "response.state.get"
	TypeReqDeploy   = "request.deploy"
	TypeResDeploy   = "response.deploy"
	TypeReqStart    = "request.start"
	TypeResStart    = "response.start"
	TypeReqStop     = "request.stop"
	TypeResStop     = "response.stop"
	TypeReqRestart  = "request.restart"
	TypeResRestart  = "response.restart"
	TypeReqLogsTail = "request.logs.tail"
	TypeResLogsTail = "response.logs.tail"
	TypeReqHealth   = "request.healthcheck.run"
	TypeResHealth   = "response.healthcheck.run"

	TypeEventStatus   = "event.status_change"
	TypeEventMetrics  = "event.metrics"
	TypeEventHCFailed = "event.healthcheck_failed"
)

func newID(prefix string) string {
	var b [6]byte
	if _, err := rand.Read(b[:]); err != nil {
		return prefix + "-" + time.Now().UTC().Format("150405.000")
	}
	return prefix + "-" + hex.EncodeToString(b[:])
}

// NewMessage builds a message with the given type and payload (any JSON-marshallable value).
func NewMessage(t string, payload any) (Message, error) {
	m := Message{
		ID:   newID("dmn"),
		Type: t,
		TS:   time.Now().UTC().Format("2006-01-02T15:04:05Z"),
	}
	if payload != nil {
		data, err := json.Marshal(payload)
		if err != nil {
			return m, err
		}
		m.Payload = data
	}
	return m, nil
}

// NewReply builds a reply message to another's id.
func NewReply(to Message, t string, payload any) (Message, error) {
	m, err := NewMessage(t, payload)
	if err != nil {
		return m, err
	}
	m.InReplyTo = to.ID
	return m, nil
}
