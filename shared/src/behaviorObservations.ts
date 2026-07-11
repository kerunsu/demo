export const BEHAVIOR_SCHEMA_VERSION = "m5-behavior-v1" as const;

export const DATA_QUALITY_STATUSES = [
  "complete",
  "partial",
  "missing_device",
  "low_confidence",
  "timeout",
  "manual_override",
  "insufficient"
] as const;

export const EVIDENCE_REFERENCE_TYPES = [
  "domain_event",
  "voice_turn",
  "transcript",
  "animation_event",
  "feedback_event",
  "provider_result",
  "observation",
  "observation_window"
] as const;

export const OBSERVATION_SOURCES = [
  "camera",
  "microphone",
  "speech_pipeline",
  "training_event",
  "mock_provider",
  "manual_test"
] as const;

export const ATTENTION_FEATURE_KINDS = [
  "face_presence",
  "face_count",
  "head_orientation",
  "screen_orientation",
  "screen_oriented_interval",
  "orientation_interruption",
  "image_quality",
  "camera_unavailable"
] as const;

export const EMOTION_FEATURE_KINDS = [
  "frame_emotion_scores",
  "face_absent",
  "emotion_unavailable"
] as const;

export const LANGUAGE_FEATURE_KINDS = [
  "speech_presence",
  "response_latency_ms",
  "audio_duration_ms",
  "transcript_length",
  "word_count",
  "sentence_count",
  "empty_response",
  "repeated_response",
  "stt_confidence",
  "prompt_count",
  "prompt_delta",
  "relevance",
  "completeness",
  "information_richness",
  "audio_loudness_rms",
  "audio_loudness_db",
  "audio_speech_ratio",
  "audio_clarity_proxy"
] as const;

export type BehaviorSchemaVersion = typeof BEHAVIOR_SCHEMA_VERSION;
export type DataQualityStatus = (typeof DATA_QUALITY_STATUSES)[number];
export type EvidenceReferenceType = (typeof EVIDENCE_REFERENCE_TYPES)[number];
export type ObservationSource = (typeof OBSERVATION_SOURCES)[number];
export type AttentionFeatureKind = (typeof ATTENTION_FEATURE_KINDS)[number];
export type EmotionFeatureKind = (typeof EMOTION_FEATURE_KINDS)[number];
export type LanguageFeatureKind = (typeof LANGUAGE_FEATURE_KINDS)[number];

export interface AlgorithmVersion {
  schemaVersion: BehaviorSchemaVersion;
  algorithmVersion: string;
  providerVersion?: string;
  modelVersion?: string;
  ruleVersion?: string;
}

export interface DataQuality {
  status: DataQualityStatus;
  reasonCode?: string;
  providerStatus?: "ok" | "degraded" | "failed" | "not_available";
  confidence?: number;
  notes?: string;
}

export interface EvidenceReference {
  type: EvidenceReferenceType;
  id: string;
  sessionId: string;
  questionId?: string;
  turnId?: string;
  eventId?: string;
  windowId?: string;
  provider?: string;
  createdAt: string;
  redacted: boolean;
}

export interface BehaviorObservationBase<TKind extends string, TFeature> {
  observationId: string;
  observationType: TKind;
  sessionId: string;
  questionId?: string;
  turnId?: string;
  eventId?: string;
  correlationId: string;
  windowId?: string;
  startedAt: string;
  endedAt: string;
  observedAt: string;
  source: ObservationSource;
  provider: string;
  algorithm: AlgorithmVersion;
  features: TFeature;
  confidence: number;
  dataQuality: DataQuality;
  degraded: boolean;
  error?: {
    code: string;
    message: string;
    retryable?: boolean;
  };
  evidence: EvidenceReference[];
  createdAt: string;
}

export type HeadOrientation = "screen" | "away" | "left" | "right" | "up" | "down" | "unknown";
export type ImageQuality = "good" | "low_light" | "blurred" | "occluded" | "unavailable" | "unknown";

export interface AttentionFeatures {
  kind: AttentionFeatureKind;
  facePresent?: boolean;
  faceCount?: number;
  headOrientation?: HeadOrientation;
  roughlyFacingScreen?: boolean;
  facingScore?: number;
  durationMs?: number;
  imageQuality?: ImageQuality;
  cameraAvailable?: boolean;
}

export interface LanguageFeatures {
  kind: LanguageFeatureKind;
  value: string | number | boolean;
  responseStartedAt?: string;
  audioDurationMs?: number;
  transcriptLength?: number;
  wordCount?: number;
  sentenceCount?: number;
  sttConfidence?: number;
  promptCount?: number;
  providerFeature?: {
    provider: string;
    modelOrRuleVersion: string;
    inputEvidence: EvidenceReference[];
  };
}

export interface EmotionFeatures {
  kind: EmotionFeatureKind;
  positiveScore?: number;
  focusedScore?: number;
  frustratedScore?: number;
  facePresent?: boolean;
  durationMs?: number;
}

export type AttentionObservation = BehaviorObservationBase<"attention", AttentionFeatures>;
export type LanguageObservation = BehaviorObservationBase<"language", LanguageFeatures>;
export type EmotionObservation = BehaviorObservationBase<"emotion", EmotionFeatures>;
export type BehaviorObservation = AttentionObservation | LanguageObservation | EmotionObservation;

export interface ObservationWindow {
  windowId: string;
  sessionId: string;
  questionId?: string;
  turnId?: string;
  correlationId: string;
  windowType: "question" | "attempt" | "voice_turn" | "prompt_delta" | "session";
  startedAt: string;
  endedAt: string;
  inputEventIds: string[];
  observationIds: string[];
  algorithm: AlgorithmVersion;
  dataQuality: DataQuality;
  createdAt: string;
}

export interface QuestionBehaviorSummary {
  summaryId: string;
  sessionId: string;
  questionId: string;
  windowId: string;
  correlationId: string;
  attention?: {
    observedMs: number;
    screenOrientedMs: number;
    orientationInterruptedMs: number;
    unavailableMs: number;
    /** Mean browser-attention-v2 facingScore (0–1) across question observations. */
    averageFacingScore?: number;
    quality: DataQuality;
  };
  language?: {
    responsePresent: boolean;
    responseLatencyMs?: number;
    audioDurationMs?: number;
    transcriptLength?: number;
    sentenceCount?: number;
    emptyResponse: boolean;
    repeatedResponse: boolean;
    averageLoudnessRms?: number;
    averageLoudnessDb?: number;
    averageSpeechRatio?: number;
    averageClarityProxy?: number;
    audioFeatureProvider?: string;
    audioFeatureAlgorithmVersion?: string;
    audioFeatureDegraded?: boolean;
    quality: DataQuality;
  };
  emotion?: {
    observedMs: number;
    averagePositiveScore?: number;
    averageFocusedScore?: number;
    averageFrustratedScore?: number;
    emotionFeatureProvider?: string;
    emotionFeatureAlgorithmVersion?: string;
    emotionFeatureDegraded?: boolean;
    quality: DataQuality;
  };
  evidence: EvidenceReference[];
  algorithm: AlgorithmVersion;
  dataQuality: DataQuality;
  createdAt: string;
}

export interface SessionBehaviorSummary {
  summaryId: string;
  sessionId: string;
  courseType?: string;
  questionSummaryIds: string[];
  attention?: {
    totalObservedMs: number;
    screenOrientedRatio?: number;
    unavailableRatio?: number;
    quality: DataQuality;
  };
  language?: {
    responseCount: number;
    emptyResponseCount: number;
    repeatedResponseCount: number;
    medianResponseLatencyMs?: number;
    lowConfidenceTranscriptCount: number;
    averageLoudnessRms?: number;
    averageSpeechRatio?: number;
    averageClarityProxy?: number;
    audioFeatureTurnCount?: number;
    audioFeatureDegraded?: boolean;
    quality: DataQuality;
  };
  emotion?: {
    observationCount: number;
    averagePositiveScore?: number;
    averageFocusedScore?: number;
    averageFrustratedScore?: number;
    emotionFeatureProvider?: string;
    emotionFeatureAlgorithmVersion?: string;
    emotionFeatureDegraded?: boolean;
    quality: DataQuality;
  };
  evidence: EvidenceReference[];
  algorithm: AlgorithmVersion;
  dataQuality: DataQuality;
  environmentPending: string[];
  ownerRequiredBeforeScoring: string[];
  createdAt: string;
}

export const DEFAULT_BEHAVIOR_ALGORITHM_VERSION: AlgorithmVersion = {
  schemaVersion: BEHAVIOR_SCHEMA_VERSION,
  algorithmVersion: "m5-behavior-baseline-v1"
};

export function createEvidenceReference(input: Omit<EvidenceReference, "createdAt" | "redacted"> & {
  createdAt?: string;
  redacted?: boolean;
}): EvidenceReference {
  return {
    ...input,
    createdAt: input.createdAt ?? new Date(0).toISOString(),
    redacted: input.redacted ?? true
  };
}
