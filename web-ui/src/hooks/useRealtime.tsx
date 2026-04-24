import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { RealtimeClient, type RealtimeFrame, type ConnectionStatus } from "../api/ws";

type RealtimeCtx = {
  status: ConnectionStatus;
  subscribe: (fn: (f: RealtimeFrame) => void) => () => void;
};

const Ctx = createContext<RealtimeCtx | null>(null);

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const clientRef = useRef<RealtimeClient | null>(null);
  const qc = useQueryClient();

  if (clientRef.current === null) {
    clientRef.current = new RealtimeClient();
  }

  useEffect(() => {
    const client = clientRef.current!;
    const unStatus = client.onStatus(setStatus);
    const unFrame = client.subscribe((frame) => {
      if (frame.type === "hub.event" && frame.event_type === "event.metrics") {
        qc.invalidateQueries({ queryKey: ["metrics"] });
        qc.invalidateQueries({ queryKey: ["hosts"] });
      }
    });
    client.start();
    return () => {
      unFrame();
      unStatus();
      client.stop();
    };
  }, [qc]);

  const value: RealtimeCtx = {
    status,
    subscribe: (fn) => clientRef.current!.subscribe(fn),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useRealtime() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useRealtime must be used inside <RealtimeProvider>");
  return ctx;
}

/**
 * Subscribe to the N most recent frames (ring buffer). Re-renders on each
 * new frame, so keep `limit` small when feeding lists.
 */
export function useRecentFrames(limit = 10) {
  const { subscribe } = useRealtime();
  const [frames, setFrames] = useState<RealtimeFrame[]>([]);
  useEffect(() => {
    return subscribe((f) => {
      setFrames((prev) => {
        const next = [f, ...prev];
        return next.length > limit ? next.slice(0, limit) : next;
      });
    });
  }, [subscribe, limit]);
  return frames;
}
