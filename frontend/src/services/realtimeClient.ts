import type { DomainEvent } from "child-education-training-demo/shared/domain-events";
import { FRONTEND_RUNTIME_CONFIG } from "../config/runtime";

export type RealtimeScreenRole = "child" | "robot" | "operator";

export type RealtimeClientMessage =
  | { type: "hello"; client: { clientId: string; sessionId: string; screenRole: RealtimeScreenRole } }
  | { type: "heartbeat"; timestamp: string }
  | { type: "event"; event: DomainEvent }
  | { type: "error"; code: string; message: string };

export function createRealtimeUrl(input: {
  sessionId: string;
  screenRole: RealtimeScreenRole;
  clientId: string;
  lastSeenEventId?: string;
}) {
  const url = new URL(FRONTEND_RUNTIME_CONFIG.wsUrl);
  url.searchParams.set("sessionId", input.sessionId);
  url.searchParams.set("screenRole", input.screenRole);
  url.searchParams.set("clientId", input.clientId);
  if (input.lastSeenEventId) url.searchParams.set("lastSeenEventId", input.lastSeenEventId);
  return url.toString();
}

export function connectRealtime(input: {
  sessionId: string;
  screenRole: RealtimeScreenRole;
  clientId: string;
  lastSeenEventId?: string;
  onMessage: (message: RealtimeClientMessage) => void;
  onStatus: (status: "connecting" | "connected" | "disconnected" | "error") => void;
}) {
  input.onStatus("connecting");
  const socket = new WebSocket(createRealtimeUrl(input));
  const heartbeat = window.setInterval(() => {
    if (socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "heartbeat" }));
    }
  }, 10000);
  socket.addEventListener("open", () => input.onStatus("connected"));
  socket.addEventListener("close", () => {
    window.clearInterval(heartbeat);
    input.onStatus("disconnected");
  });
  socket.addEventListener("error", () => input.onStatus("error"));
  socket.addEventListener("message", (event) => {
    input.onMessage(JSON.parse(String(event.data)) as RealtimeClientMessage);
  });
  return {
    close: () => {
      window.clearInterval(heartbeat);
      socket.close();
    },
    sendEvent: (domainEvent: DomainEvent) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "event", event: domainEvent }));
      }
    }
  };
}
