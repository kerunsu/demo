import type {
  AnimationFinishedPayload,
  AnimationStartedPayload,
  DomainEvent,
  DomainEventOf,
  DomainEventPayloadMap,
  DomainEventSource,
  DomainEventType,
  TtsFinishedPayload,
  TtsStartedPayload
} from "child-education-training-demo/shared/domain-events";
import type { RobotAnimationId, RobotAnimationIntent } from "child-education-training-demo/shared/animations";
import { realtimeHub } from "./realtimeHub.js";
import { listPersistentDomainEvents, savePersistentDomainEvent } from "./sqlitePersistenceService.js";
import { recordVoiceMetric, recordVoiceTurnTotal } from "./voiceObservabilityService.js";

type PendingFeedbackTurn = {
  sessionId: string;
  commandId: string;
  speechTurnId: string;
  registeredAt: string;
  completed: boolean;
  animationDone: boolean;
  ttsDone: boolean;
  onComplete: () => void;
  timeout: NodeJS.Timeout;
};

const eventsBySession = new Map<string, DomainEvent[]>();
const pendingTurns = new Map<string, PendingFeedbackTurn>();
const processedAckIds = new Set<string>();

function createId(prefix: string) {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function nowIso() {
  return new Date().toISOString();
}

export function getSessionEvents(sessionId: string, afterEventId?: string) {
  const events = eventsBySession.get(sessionId) ?? listPersistentDomainEvents(sessionId);
  if (!eventsBySession.has(sessionId) && events.length > 0) {
    eventsBySession.set(sessionId, events);
  }
  if (!afterEventId) return events;
  const index = events.findIndex((event) => event.eventId === afterEventId);
  return index >= 0 ? events.slice(index + 1) : events;
}

export function publishDomainEvent<TEventType extends DomainEventType>(input: {
  eventType: TEventType;
  sessionId: string;
  source: DomainEventSource;
  payload: DomainEventPayloadMap[TEventType];
  correlationId?: string;
  causationId?: string | null;
  idempotencyKey?: string;
  persist?: boolean;
}) {
  const event = {
    eventId: createId(input.eventType.toLowerCase()),
    eventType: input.eventType,
    sessionId: input.sessionId,
    timestamp: nowIso(),
    source: input.source,
    correlationId: input.correlationId ?? createId("corr"),
    causationId: input.causationId ?? null,
    schemaVersion: "v1",
    idempotencyKey: input.idempotencyKey,
    persist: input.persist ?? true,
    payload: input.payload
  } as DomainEventOf<TEventType>;
  const list = eventsBySession.get(input.sessionId) ?? [];
  list.push(event as DomainEvent);
  eventsBySession.set(input.sessionId, list);
  if (event.persist) {
    savePersistentDomainEvent(event as DomainEvent);
  }
  realtimeHub.broadcast(event as DomainEvent);
  return event;
}

export function registerFeedbackTurn(input: {
  sessionId: string;
  commandId: string;
  speechTurnId: string;
  timeoutMs: number;
  onComplete: () => void;
}) {
  const existing = pendingTurns.get(input.commandId);
  if (existing) return existing;
  const turn: PendingFeedbackTurn = {
    sessionId: input.sessionId,
    commandId: input.commandId,
    speechTurnId: input.speechTurnId,
    registeredAt: nowIso(),
    completed: false,
    animationDone: false,
    ttsDone: false,
    onComplete: input.onComplete,
    timeout: setTimeout(() => completeTurn(input.commandId, "timeout"), input.timeoutMs)
  };
  turn.timeout.unref();
  pendingTurns.set(input.commandId, turn);
  return turn;
}

export function handleClientDomainEvent(event: DomainEvent) {
  if (processedAckIds.has(event.eventId)) return;
  processedAckIds.add(event.eventId);
  const list = eventsBySession.get(event.sessionId) ?? [];
  list.push(event);
  eventsBySession.set(event.sessionId, list);
  if (event.persist) {
    savePersistentDomainEvent(event);
  }
  realtimeHub.broadcast(event);

  if (event.eventType === "ANIMATION_STARTED") return;
  if (event.eventType === "ANIMATION_FINISHED") {
    const payload = event.payload as AnimationFinishedPayload;
    const turn = pendingTurns.get(payload.commandId);
    if (turn) {
      turn.animationDone = true;
      maybeCompleteTurn(turn);
    }
  }
  if (event.eventType === "TTS_STARTED") {
    const payload = event.payload as TtsStartedPayload;
    recordVoiceMetric({
      sessionId: event.sessionId,
      turnId: payload.turnId,
      correlationId: event.correlationId,
      stage: "robot_playback_start",
      startedAt: event.timestamp,
      completedAt: event.timestamp,
      provider: payload.provider,
      model: payload.voice,
      textForHash: payload.textHash,
      metadata: {
        source: event.source
      }
    });
    return;
  }
  if (event.eventType === "TTS_FINISHED") {
    const payload = event.payload as TtsFinishedPayload;
    recordVoiceMetric({
      sessionId: event.sessionId,
      turnId: payload.turnId,
      correlationId: event.correlationId,
      stage: "robot_playback_complete",
      startedAt: event.timestamp,
      completedAt: event.timestamp,
      durationMs: payload.durationMs,
      status: "success",
      audioDurationMs: payload.durationMs,
      metadata: {
        audioRefLength: payload.audioRef.length,
        mimeType: payload.mimeType
      }
    });
    const turn = Array.from(pendingTurns.values()).find((item) => item.speechTurnId === payload.turnId);
    if (turn) {
      turn.ttsDone = true;
      maybeCompleteTurn(turn);
    }
  }
}

export function createAnimationStartedEvent(input: {
  sessionId: string;
  commandId: string;
  animationId: RobotAnimationId;
}) {
  return createClientEvent<"ANIMATION_STARTED">({
    eventType: "ANIMATION_STARTED",
    sessionId: input.sessionId,
    payload: {
      commandId: input.commandId,
      animationId: input.animationId,
      startedAt: nowIso()
    } satisfies AnimationStartedPayload
  });
}

export function createAnimationFinishedEvent(input: {
  sessionId: string;
  commandId: string;
  status: AnimationFinishedPayload["status"];
  durationMs: number;
  errorCode?: string;
}) {
  return createClientEvent<"ANIMATION_FINISHED">({
    eventType: "ANIMATION_FINISHED",
    sessionId: input.sessionId,
    payload: {
      commandId: input.commandId,
      status: input.status,
      durationMs: input.durationMs,
      errorCode: input.errorCode
    }
  });
}

export function createTtsStartedEvent(input: { sessionId: string; turnId: string }) {
  return createClientEvent<"TTS_STARTED">({
    eventType: "TTS_STARTED",
    sessionId: input.sessionId,
    payload: {
      turnId: input.turnId,
      provider: "mock_local",
      textHash: `mock:${input.turnId}`,
      voice: "local-demo"
    } satisfies TtsStartedPayload
  });
}

export function createTtsFinishedEvent(input: {
  sessionId: string;
  turnId: string;
  durationMs: number;
  audioRef: string;
}) {
  return createClientEvent<"TTS_FINISHED">({
    eventType: "TTS_FINISHED",
    sessionId: input.sessionId,
    payload: {
      turnId: input.turnId,
      audioRef: input.audioRef,
      durationMs: input.durationMs,
      mimeType: "audio/mock"
    } satisfies TtsFinishedPayload
  });
}

export function chooseAnimationForAnswer(correct: boolean, courseCompleted: boolean): {
  animationId: RobotAnimationId;
  intent: RobotAnimationIntent;
} {
  if (courseCompleted) return { animationId: "excited", intent: "course_complete" };
  if (correct) return { animationId: "happy", intent: "correct_praise" };
  return { animationId: "curious", intent: "wrong_encourage" };
}

function createClientEvent<TEventType extends DomainEventType>(input: {
  eventType: TEventType;
  sessionId: string;
  payload: DomainEventPayloadMap[TEventType];
}): DomainEventOf<TEventType> {
  return {
    eventId: createId(input.eventType.toLowerCase()),
    eventType: input.eventType,
    sessionId: input.sessionId,
    timestamp: nowIso(),
    source: "robot_screen",
    correlationId: createId("corr"),
    causationId: null,
    schemaVersion: "v1",
    persist: false,
    payload: input.payload
  };
}

function maybeCompleteTurn(turn: PendingFeedbackTurn) {
  if (turn.animationDone && turn.ttsDone) {
    completeTurn(turn.commandId, "success");
  }
}

function completeTurn(commandId: string, status: "success" | "timeout" = "success") {
  const turn = pendingTurns.get(commandId);
  if (!turn || turn.completed) return;
  turn.completed = true;
  clearTimeout(turn.timeout);
  pendingTurns.delete(commandId);
  recordVoiceTurnTotal({
    sessionId: turn.sessionId,
    turnId: turn.speechTurnId,
    correlationId: turn.commandId,
    completedAt: nowIso(),
    status,
    errorCode: status === "timeout" ? "ROBOT_ACK_TIMEOUT" : undefined
  });
  turn.onComplete();
}
