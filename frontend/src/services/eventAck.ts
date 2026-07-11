import { apiRequest } from "./api";
import type { DomainEvent, DomainEventPayloadMap, DomainEventType } from "child-education-training-demo/shared/domain-events";

export type EventAckPayload =
  | { eventType: "ANIMATION_STARTED"; commandId: string; animationId: string }
  | {
      eventType: "ANIMATION_FINISHED";
      commandId: string;
      status: "completed" | "interrupted" | "failed";
      durationMs: number;
      errorCode?: string;
    }
  | { eventType: "TTS_STARTED"; turnId: string }
  | { eventType: "TTS_FINISHED"; turnId: string; durationMs: number; audioRef: string };

export function sendEventAck(sessionId: string, payload: EventAckPayload) {
  return apiRequest<{ eventId: string }>(`/events/${sessionId}/ack`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function createAckDomainEvent(sessionId: string, payload: EventAckPayload): DomainEvent {
  const eventType = payload.eventType;
  return {
    eventId: `${eventType.toLowerCase()}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
    eventType,
    sessionId,
    timestamp: new Date().toISOString(),
    source: "robot_screen",
    correlationId: `corr_${Date.now().toString(36)}`,
    causationId: null,
    schemaVersion: "v1",
    persist: false,
    payload: toDomainPayload(eventType, payload)
  } as DomainEvent;
}

function toDomainPayload<TEventType extends DomainEventType>(
  eventType: TEventType,
  payload: EventAckPayload
): DomainEventPayloadMap[TEventType] {
  if (eventType === "ANIMATION_STARTED" && payload.eventType === "ANIMATION_STARTED") {
    return {
      commandId: payload.commandId,
      animationId: payload.animationId,
      startedAt: new Date().toISOString()
    } as DomainEventPayloadMap[TEventType];
  }
  if (eventType === "ANIMATION_FINISHED" && payload.eventType === "ANIMATION_FINISHED") {
    return {
      commandId: payload.commandId,
      status: payload.status,
      durationMs: payload.durationMs,
      errorCode: payload.errorCode
    } as DomainEventPayloadMap[TEventType];
  }
  if (eventType === "TTS_STARTED" && payload.eventType === "TTS_STARTED") {
    return {
      turnId: payload.turnId,
      provider: "mock_local",
      textHash: `mock:${payload.turnId}`,
      voice: "local-demo"
    } as DomainEventPayloadMap[TEventType];
  }
  if (eventType === "TTS_FINISHED" && payload.eventType === "TTS_FINISHED") {
    return {
      turnId: payload.turnId,
      audioRef: payload.audioRef,
      durationMs: payload.durationMs,
      mimeType: "audio/mock"
    } as DomainEventPayloadMap[TEventType];
  }
  throw new Error(`Unsupported ACK event: ${eventType}`);
}
