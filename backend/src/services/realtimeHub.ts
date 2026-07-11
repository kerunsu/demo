import crypto from "node:crypto";
import type { IncomingMessage, Server } from "node:http";
import type { Duplex } from "node:stream";
import type { DomainEvent } from "child-education-training-demo/shared/domain-events";

type ScreenRole = "child" | "robot" | "operator";

export interface RealtimeClientInfo {
  clientId: string;
  sessionId: string;
  screenRole: ScreenRole;
  lastSeenEventId?: string;
}

export type RealtimeMessage =
  | { type: "hello"; client: RealtimeClientInfo }
  | { type: "heartbeat"; timestamp: string }
  | { type: "event"; event: DomainEvent }
  | { type: "error"; code: string; message: string };

type ClientRecord = RealtimeClientInfo & {
  socket: Duplex;
  alive: boolean;
};

const WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

function encodeFrame(payload: string, opcode = 0x1) {
  const body = Buffer.from(payload);
  const header: number[] = [0x80 | opcode];
  if (body.length < 126) {
    header.push(body.length);
  } else if (body.length < 65536) {
    header.push(126, (body.length >> 8) & 0xff, body.length & 0xff);
  } else {
    throw new Error("WebSocket payload too large for this demo server");
  }
  return Buffer.concat([Buffer.from(header), body]);
}

function decodeFrames(buffer: Buffer): string[] {
  const messages: string[] = [];
  let offset = 0;
  while (offset + 2 <= buffer.length) {
    const first = buffer[offset];
    const second = buffer[offset + 1];
    const opcode = first & 0x0f;
    const masked = (second & 0x80) !== 0;
    let length = second & 0x7f;
    let cursor = offset + 2;
    if (length === 126) {
      if (cursor + 2 > buffer.length) break;
      length = buffer.readUInt16BE(cursor);
      cursor += 2;
    } else if (length === 127) {
      throw new Error("Large WebSocket frames are not supported in this demo server");
    }
    const mask = masked ? buffer.subarray(cursor, cursor + 4) : null;
    if (masked) cursor += 4;
    if (cursor + length > buffer.length) break;
    const payload = Buffer.from(buffer.subarray(cursor, cursor + length));
    if (mask) {
      for (let i = 0; i < payload.length; i += 1) {
        payload[i] ^= mask[i % 4];
      }
    }
    if (opcode === 0x1) messages.push(payload.toString("utf8"));
    offset = cursor + length;
  }
  return messages;
}

function parseRole(value: string | null): ScreenRole {
  if (value === "child" || value === "robot" || value === "operator") return value;
  throw new Error("screenRole must be child, robot, or operator");
}

function parseClientInfo(req: IncomingMessage): RealtimeClientInfo {
  const url = new URL(req.url ?? "", "http://localhost");
  if (url.pathname !== "/ws") {
    throw new Error("Unsupported WebSocket path");
  }
  const sessionId = url.searchParams.get("sessionId");
  if (!sessionId) throw new Error("sessionId is required");
  return {
    sessionId,
    screenRole: parseRole(url.searchParams.get("screenRole")),
    clientId: url.searchParams.get("clientId") || `client_${Math.random().toString(36).slice(2, 10)}`,
    lastSeenEventId: url.searchParams.get("lastSeenEventId") || undefined
  };
}

export class RealtimeHub {
  private clients = new Map<string, ClientRecord>();
  private heartbeatTimer: NodeJS.Timeout | null = null;
  private incomingHandlers = new Set<(event: DomainEvent, client: RealtimeClientInfo) => void>();

  attach(server: Server) {
    server.on("upgrade", (req, socket) => {
      try {
        const key = req.headers["sec-websocket-key"];
        if (!key || Array.isArray(key)) throw new Error("Missing Sec-WebSocket-Key");
        const client = parseClientInfo(req);
        const accept = crypto.createHash("sha1").update(`${key}${WS_GUID}`).digest("base64");
        socket.write(
          [
            "HTTP/1.1 101 Switching Protocols",
            "Upgrade: websocket",
            "Connection: Upgrade",
            `Sec-WebSocket-Accept: ${accept}`,
            "",
            ""
          ].join("\r\n")
        );
        this.register({ ...client, socket, alive: true });
      } catch (error) {
        socket.write("HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n");
        socket.destroy();
      }
    });
    this.ensureHeartbeat();
  }

  onClientEvent(handler: (event: DomainEvent, client: RealtimeClientInfo) => void) {
    this.incomingHandlers.add(handler);
    return () => this.incomingHandlers.delete(handler);
  }

  broadcast(event: DomainEvent) {
    for (const client of this.clients.values()) {
      if (client.sessionId === event.sessionId) {
        this.send(client, { type: "event", event });
      }
    }
  }

  getClientCount(sessionId?: string) {
    if (!sessionId) return this.clients.size;
    return Array.from(this.clients.values()).filter((client) => client.sessionId === sessionId).length;
  }

  closeAll() {
    for (const client of this.clients.values()) {
      client.socket.destroy();
    }
    this.clients.clear();
  }

  private register(client: ClientRecord) {
    this.clients.set(client.clientId, client);
    this.send(client, { type: "hello", client });
    client.socket.on("data", (buffer) => {
      try {
        for (const message of decodeFrames(buffer)) {
          this.handleMessage(client, message);
        }
      } catch {
        this.send(client, { type: "error", code: "BAD_FRAME", message: "Invalid WebSocket frame" });
      }
    });
    client.socket.on("close", () => this.clients.delete(client.clientId));
    client.socket.on("error", () => this.clients.delete(client.clientId));
  }

  private handleMessage(client: ClientRecord, message: string) {
    const payload = JSON.parse(message) as { type?: string; event?: DomainEvent };
    if (payload.type === "heartbeat") {
      client.alive = true;
      this.send(client, { type: "heartbeat", timestamp: new Date().toISOString() });
      return;
    }
    if (payload.type === "event" && payload.event) {
      for (const handler of this.incomingHandlers) {
        handler(payload.event, client);
      }
    }
  }

  private send(client: ClientRecord, message: RealtimeMessage) {
    if (client.socket.destroyed) return;
    client.socket.write(encodeFrame(JSON.stringify(message)));
  }

  private ensureHeartbeat() {
    if (this.heartbeatTimer) return;
    this.heartbeatTimer = setInterval(() => {
      for (const client of this.clients.values()) {
        this.send(client, { type: "heartbeat", timestamp: new Date().toISOString() });
      }
    }, 15000);
    this.heartbeatTimer.unref();
  }
}

export const realtimeHub = new RealtimeHub();
