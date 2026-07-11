import type {
  AlgorithmVersion,
  DataQuality,
  EvidenceReference
} from "./behaviorObservations.js";

export const DOMAIN_EVENT_SCHEMA_VERSION = "v1" as const;

export const DOMAIN_EVENT_TYPES = [
  "SESSION_STARTED",
  "SESSION_ENDED",
  "QUESTION_PRESENTED",
  "ANSWER_SUBMITTED",
  "ANSWER_EVALUATED",
  "FEEDBACK_REQUESTED",
  "ANIMATION_REQUESTED",
  "ANIMATION_STARTED",
  "ANIMATION_FINISHED",
  "LISTENING_STARTED",
  "LISTENING_FINISHED",
  "TRANSCRIPT_READY",
  "LLM_REPLY_REQUESTED",
  "LLM_REPLY_GENERATED",
  "SAFETY_REVIEW_PASSED",
  "SAFETY_REVIEW_REJECTED",
  "TTS_STARTED",
  "TTS_FINISHED",
  "ATTENTION_OBSERVATION_RECORDED",
  "LANGUAGE_OBSERVATION_RECORDED",
  "ASSESSMENT_UPDATED",
  "REPORT_GENERATED",
  "CLIENT_CONNECTED",
  "CLIENT_DISCONNECTED"
] as const;

export const DOMAIN_EVENT_SOURCES = [
  "child_screen",
  "robot_screen",
  "backend",
  "speech_pipeline",
  "assessment_engine",
  "safety_gateway"
] as const;

export type DomainEventSchemaVersion = typeof DOMAIN_EVENT_SCHEMA_VERSION;
export type DomainEventType = (typeof DOMAIN_EVENT_TYPES)[number];
export type DomainEventSource = (typeof DOMAIN_EVENT_SOURCES)[number];

export interface DomainEventBase<TEventType extends DomainEventType, TPayload> {
  eventId: string;
  eventType: TEventType;
  sessionId: string;
  timestamp: string;
  source: DomainEventSource;
  correlationId: string;
  causationId: string | null;
  schemaVersion: DomainEventSchemaVersion;
  idempotencyKey?: string;
  persist: boolean;
  payload: TPayload;
}

export interface SessionStartedPayload {
  childAlias: string;
  courseQueue: string[];
  startedAt: string;
}

export interface SessionEndedPayload {
  reason: "completed" | "cancelled" | "abandoned" | "error";
  endedAt: string;
}

export interface QuestionPresentedPayload {
  questionId: string;
  courseType: string;
  index: number;
  total: number;
  prompt: string;
}

export interface AnswerSubmittedPayload {
  questionId: string;
  selectedOptionId: string;
  responseTimeMs: number;
  attemptIndex: number;
}

export interface AnswerEvaluatedPayload {
  questionId: string;
  correct: boolean;
  wrongType?: "mismatch" | "wrong_order" | "timeout" | "invalid_input" | "other";
  nextAction: "NEXT_QUESTION" | "RETRY_SAME_QUESTION" | "FINISH_COURSE";
  hintId?: string;
}

export interface FeedbackRequestedPayload {
  feedbackKind: "encouragement" | "praise" | "hint" | "correction" | "safe_fallback";
  text: string;
  requiresSpeech: boolean;
  animationIntent: string;
}

export interface AnimationRequestedPayload {
  commandId: string;
  animationId: string;
  intent: string;
  priority: number;
  interruptPolicy: "interrupt" | "queue" | "ignore_if_playing";
}

export interface AnimationStartedPayload {
  commandId: string;
  animationId: string;
  startedAt: string;
}

export interface AnimationFinishedPayload {
  commandId: string;
  status: "completed" | "interrupted" | "failed";
  durationMs: number;
  errorCode?: string;
}

export interface ListeningStartedPayload {
  turnId: string;
  mode: "single" | "continuous";
  deviceIdHash?: string;
}

export interface ListeningFinishedPayload {
  turnId: string;
  reason: "speech_final" | "timeout" | "cancelled" | "error";
  durationMs: number;
}

export interface TranscriptReadyPayload {
  turnId: string;
  transcriptRedacted: string;
  confidence?: number;
  language: string;
}

export interface LlmReplyRequestedPayload {
  turnId: string;
  provider: string;
  contextVersion: string;
}

export interface LlmReplyGeneratedPayload {
  turnId: string;
  provider: string;
  replyDraft: string;
  latencyMs: number;
}

export interface SafetyReviewPassedPayload {
  targetEventId: string;
  reviewer: string;
  policyVersion: string;
}

export interface SafetyReviewRejectedPayload {
  targetEventId: string;
  reason: string;
  fallbackText: string;
  policyVersion: string;
}

export interface TtsStartedPayload {
  turnId: string;
  provider: string;
  textHash: string;
  voice?: string;
}

export interface TtsFinishedPayload {
  turnId: string;
  audioRef: string;
  durationMs: number;
  mimeType: string;
}

export interface AttentionObservationRecordedPayload {
  observationId: string;
  observationType: "attention";
  questionId?: string;
  turnId?: string;
  windowId?: string;
  kind: string;
  durationMs?: number;
  confidence?: number;
  dataQuality: DataQuality;
  algorithm: AlgorithmVersion;
  evidence: EvidenceReference[];
}

export interface LanguageObservationRecordedPayload {
  observationId: string;
  observationType: "language";
  sourceTurnId?: string;
  questionId?: string;
  windowId?: string;
  feature: string;
  value: string | number | boolean;
  confidence?: number;
  dataQuality: DataQuality;
  algorithm: AlgorithmVersion;
  evidence: EvidenceReference[];
}

export interface AssessmentUpdatedPayload {
  assessmentId: string;
  metricVersion: string;
  metrics: Record<string, number>;
  dataQuality: "ok" | "partial" | "insufficient";
}

export interface ReportGeneratedPayload {
  reportId: string;
  reportVersion: string;
  generatedAt: string;
}

export interface ClientConnectedPayload {
  clientId: string;
  screenRole: "child" | "robot" | "operator";
  lastSeenEventId?: string;
}

export interface ClientDisconnectedPayload {
  clientId: string;
  screenRole: "child" | "robot" | "operator";
  reason: "closed" | "heartbeat_timeout" | "network_error" | "unknown";
}

export type DomainEventPayloadMap = {
  SESSION_STARTED: SessionStartedPayload;
  SESSION_ENDED: SessionEndedPayload;
  QUESTION_PRESENTED: QuestionPresentedPayload;
  ANSWER_SUBMITTED: AnswerSubmittedPayload;
  ANSWER_EVALUATED: AnswerEvaluatedPayload;
  FEEDBACK_REQUESTED: FeedbackRequestedPayload;
  ANIMATION_REQUESTED: AnimationRequestedPayload;
  ANIMATION_STARTED: AnimationStartedPayload;
  ANIMATION_FINISHED: AnimationFinishedPayload;
  LISTENING_STARTED: ListeningStartedPayload;
  LISTENING_FINISHED: ListeningFinishedPayload;
  TRANSCRIPT_READY: TranscriptReadyPayload;
  LLM_REPLY_REQUESTED: LlmReplyRequestedPayload;
  LLM_REPLY_GENERATED: LlmReplyGeneratedPayload;
  SAFETY_REVIEW_PASSED: SafetyReviewPassedPayload;
  SAFETY_REVIEW_REJECTED: SafetyReviewRejectedPayload;
  TTS_STARTED: TtsStartedPayload;
  TTS_FINISHED: TtsFinishedPayload;
  ATTENTION_OBSERVATION_RECORDED: AttentionObservationRecordedPayload;
  LANGUAGE_OBSERVATION_RECORDED: LanguageObservationRecordedPayload;
  ASSESSMENT_UPDATED: AssessmentUpdatedPayload;
  REPORT_GENERATED: ReportGeneratedPayload;
  CLIENT_CONNECTED: ClientConnectedPayload;
  CLIENT_DISCONNECTED: ClientDisconnectedPayload;
};

export type DomainEventOf<TEventType extends DomainEventType> = DomainEventBase<
  TEventType,
  DomainEventPayloadMap[TEventType]
>;

export type DomainEvent = {
  [TEventType in DomainEventType]: DomainEventOf<TEventType>;
}[DomainEventType];

export type PersistedDomainEvent = DomainEvent & { persist: true };
export type OptionalPersistDomainEvent = DomainEvent & { persist: false };
