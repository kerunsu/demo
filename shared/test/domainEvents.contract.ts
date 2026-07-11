import {
  DOMAIN_EVENT_SCHEMA_VERSION,
  DOMAIN_EVENT_SOURCES,
  DOMAIN_EVENT_TYPES,
  type DomainEvent,
  type DomainEventOf,
  type DomainEventPayloadMap,
  type DomainEventSource,
  type DomainEventType
} from "../src/domainEvents.js";

type Assert<T extends true> = T;
type Equals<TLeft, TRight> =
  (<T>() => T extends TLeft ? 1 : 2) extends
  (<T>() => T extends TRight ? 1 : 2)
    ? true
    : false;

type AllEventTypesHavePayloads = Assert<Equals<DomainEventType, keyof DomainEventPayloadMap>>;
type SourceUnionMatchesConstants = Assert<Equals<DomainEventSource, (typeof DOMAIN_EVENT_SOURCES)[number]>>;

const answerSubmitted = {
  eventId: "event-1",
  eventType: "ANSWER_SUBMITTED",
  sessionId: "session-1",
  timestamp: "2026-06-07T00:20:00.000+08:00",
  source: "child_screen",
  correlationId: "corr-1",
  causationId: null,
  schemaVersion: DOMAIN_EVENT_SCHEMA_VERSION,
  idempotencyKey: "answer-click-1",
  persist: true,
  payload: {
    questionId: "question-1",
    selectedOptionId: "option-1",
    responseTimeMs: 1200,
    attemptIndex: 1
  }
} satisfies DomainEventOf<"ANSWER_SUBMITTED">;

const animationFinished = {
  eventId: "event-2",
  eventType: "ANIMATION_FINISHED",
  sessionId: "session-1",
  timestamp: "2026-06-07T00:20:01.000+08:00",
  source: "robot_screen",
  correlationId: "corr-1",
  causationId: "event-1",
  schemaVersion: DOMAIN_EVENT_SCHEMA_VERSION,
  persist: false,
  payload: {
    commandId: "animation-command-1",
    status: "completed",
    durationMs: 1500
  }
} satisfies DomainEventOf<"ANIMATION_FINISHED">;

const eventUnionSamples: DomainEvent[] = [answerSubmitted, animationFinished];

if (DOMAIN_EVENT_TYPES.length !== 24) {
  throw new Error("Domain event type list must stay aligned with docs/DOMAIN_EVENTS.md.");
}

void eventUnionSamples;
