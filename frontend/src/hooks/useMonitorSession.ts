import { useCallback, useEffect, useState } from "react";
import { connectRealtime } from "../services/realtimeClient";
import { getMonitorSnapshot, type MonitorSnapshot } from "../services/monitorService";

const POLL_CONNECTED_MS = 1000;
const POLL_DISCONNECTED_MS = 1000;

export function useMonitorSession(sessionId: string) {
  const [snapshot, setSnapshot] = useState<MonitorSnapshot | null>(null);
  const [error, setError] = useState("");
  const [wsStatus, setWsStatus] = useState<"connecting" | "connected" | "disconnected" | "error">("disconnected");
  const [refreshSource, setRefreshSource] = useState<"initial" | "poll" | "ws">("initial");

  const refresh = useCallback(
    async (source: "initial" | "poll" | "ws") => {
      if (!sessionId.trim()) return;
      try {
        const next = await getMonitorSnapshot(sessionId.trim());
        setSnapshot(next);
        setError("");
        setRefreshSource(source);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Monitor snapshot unavailable");
      }
    },
    [sessionId]
  );

  useEffect(() => {
    if (!sessionId.trim()) {
      setSnapshot(null);
      setError("");
      return;
    }
    void refresh("initial");
    const pollMs = wsStatus === "connected" ? POLL_CONNECTED_MS : POLL_DISCONNECTED_MS;
    const timer = window.setInterval(() => {
      void refresh("poll");
    }, pollMs);
    return () => window.clearInterval(timer);
  }, [sessionId, wsStatus, refresh]);

  useEffect(() => {
    if (!sessionId.trim()) return;
    const client = connectRealtime({
      sessionId: sessionId.trim(),
      screenRole: "operator",
      clientId: `server-monitor-${crypto.randomUUID().slice(0, 8)}`,
      onStatus: setWsStatus,
      onMessage: (message) => {
        if (message.type === "event") {
          void refresh("ws");
        }
      }
    });
    return () => client.close();
  }, [sessionId, refresh]);

  return {
    snapshot,
    error,
    wsStatus,
    refreshSource,
    refresh: () => refresh("poll")
  };
}
