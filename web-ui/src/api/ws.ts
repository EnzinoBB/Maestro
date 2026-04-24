/**
 * Minimal reconnecting WebSocket client for /ws/ui.
 *
 * No dependencies. Exposes subscribe() for frames and onStatus() for the
 * connection lifecycle. Heartbeats ping every 20s to keep intermediaries
 * from dropping idle connections.
 */
export type RealtimeFrame =
  | { type: "hello"; server_version: string }
  | { type: "pong" }
  | {
      type: "hub.event";
      host_id: string;
      event_type: string;
      ts: number | string;
      summary: Record<string, number>;
    };

export type ConnectionStatus = "connecting" | "open" | "closed";

export class RealtimeClient {
  private ws: WebSocket | null = null;
  private reconnectDelay = 1000;
  private readonly url: string;
  private frameSubs = new Set<(f: RealtimeFrame) => void>();
  private statusSubs = new Set<(s: ConnectionStatus) => void>();
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private manualClose = false;

  constructor(url = `${location.origin.replace(/^http/, "ws")}/ws/ui`) {
    this.url = url;
  }

  start() {
    this.manualClose = false;
    this.connect();
  }

  stop() {
    this.manualClose = true;
    this.emitStatus("closed");
    this.ws?.close();
    this.ws = null;
    if (this.pingTimer) clearInterval(this.pingTimer);
  }

  subscribe(fn: (f: RealtimeFrame) => void) {
    this.frameSubs.add(fn);
    return () => this.frameSubs.delete(fn);
  }

  onStatus(fn: (s: ConnectionStatus) => void) {
    this.statusSubs.add(fn);
    return () => this.statusSubs.delete(fn);
  }

  private emit(frame: RealtimeFrame) {
    this.frameSubs.forEach(fn => fn(frame));
  }
  private emitStatus(s: ConnectionStatus) {
    this.statusSubs.forEach(fn => fn(s));
  }

  private connect() {
    this.emitStatus("connecting");
    try {
      this.ws = new WebSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.ws.addEventListener("open", () => {
      this.emitStatus("open");
      this.reconnectDelay = 1000;
      if (this.pingTimer) clearInterval(this.pingTimer);
      this.pingTimer = setInterval(() => {
        try {
          this.ws?.send(JSON.stringify({ type: "ping" }));
        } catch { /* ignore */ }
      }, 20_000);
    });

    this.ws.addEventListener("message", (ev) => {
      try {
        const frame = JSON.parse(ev.data) as RealtimeFrame;
        this.emit(frame);
      } catch { /* malformed — drop */ }
    });

    const closeOrError = () => {
      this.emitStatus("closed");
      if (this.pingTimer) clearInterval(this.pingTimer);
      this.ws = null;
      if (!this.manualClose) this.scheduleReconnect();
    };
    this.ws.addEventListener("close", closeOrError);
    this.ws.addEventListener("error", closeOrError);
  }

  private scheduleReconnect() {
    setTimeout(() => this.connect(), this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30_000);
  }
}
