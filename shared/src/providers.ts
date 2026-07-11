import type {
  AttentionObservation,
  DataQualityStatus,
  LanguageObservation,
  ObservationSource
} from "./behaviorObservations.js";

export type ProviderKind =
  | "stt"
  | "llm"
  | "safety_review"
  | "tts"
  | "attention_observation"
  | "language_observation"
  | "emotion_observation";

export type SpeechProviderType = "local" | "cloud" | "mock";
export type ProviderRuntimeMode = SpeechProviderType | "rule" | "noop" | "external";
export type ProviderHealthStatus =
  | "READY"
  | "INITIALIZING"
  | "UNAVAILABLE"
  | "DEGRADED"
  | "CLOUD_CREDENTIALS_PENDING"
  | "LOCAL_MODEL_PENDING";
export type ReviewStatus = "NOT_REQUIRED" | "HUMAN_REVIEW_PENDING" | "REQUIRED_BEFORE_PRODUCTION" | "COMPLETE";
export type HardwareAcceleration = "CPU" | "CPUExecutionProvider" | "DirectML" | "CUDA" | "unknown" | "none";

export type ProviderErrorCode =
  | "TIMEOUT"
  | "PROVIDER_FAILURE"
  | "EMPTY_RESULT"
  | "LOW_CONFIDENCE"
  | "SAFETY_REJECTED"
  | "UNREVIEWED_TEXT"
  | "CANCELLED"
  | "CLOUD_CREDENTIALS_PENDING"
  | "LOCAL_MODEL_PENDING"
  | "UNSUPPORTED_AUDIO_FORMAT"
  | "AUDIO_TRANSCODE_FAILED"
  | "CAMERA_UNAVAILABLE";

export interface ProviderDataSafetyDeclaration {
  externalNetworkCalled: boolean;
  inputPersisted: boolean;
  rawAudioPersisted: boolean;
  sensitiveTextLogged: boolean;
  credentialsSource: "none" | "environment" | "runtime_secret";
  allowedData: Array<"synthetic" | "developer_authorized" | "authorized_non_child" | "redacted_text">;
  notes: string;
}

export interface ProviderResourceMetrics {
  initLatencyMs?: number;
  modelLoadLatencyMs?: number;
  processLatencyMs?: number;
  firstByteLatencyMs?: number;
  audioDurationMs?: number;
  realTimeFactor?: number;
  peakRssMb?: number;
  cpuPercent?: number;
  gpuUsed: boolean;
  hardwareAcceleration: HardwareAcceleration;
}

export interface ProviderFallbackPolicy {
  fallbackProviderIds: string[];
  fallbackMode: "manual_text" | "mock" | "rule_reply" | "display_text_only" | "none";
  childSafeFallbackText?: string;
}

export interface ProviderMetadata {
  providerKind: ProviderKind;
  providerName: string;
  providerId?: string;
  providerType?: SpeechProviderType;
  mode: ProviderRuntimeMode;
  version: string;
  modelId?: string;
  modelPath?: string;
  configPath?: string;
  vendorModelName?: string;
  defaultEnabled?: boolean;
  humanReview?: ReviewStatus;
  licenseReview?: ReviewStatus;
  dataSafety?: ProviderDataSafetyDeclaration;
  fallback?: ProviderFallbackPolicy;
}

export interface ProviderError {
  code: ProviderErrorCode;
  message: string;
  retryable?: boolean;
  providerStatus?: ProviderHealthStatus;
}

export type ProviderResult<TData> =
  | {
      ok: true;
      metadata: ProviderMetadata;
      latencyMs: number;
      data: TData;
      metrics?: ProviderResourceMetrics;
    }
  | {
      ok: false;
      metadata: ProviderMetadata;
      latencyMs: number;
      error: ProviderError;
      fallbackText?: string;
      metrics?: ProviderResourceMetrics;
    };

export interface ProviderHealth {
  providerId: string;
  providerKind: ProviderKind;
  providerType: SpeechProviderType;
  status: ProviderHealthStatus;
  modelId?: string;
  modelPath?: string;
  configPath?: string;
  initialized: boolean;
  lastCheckedAt: string;
  externalNetworkCalled: boolean;
  inputPersisted: boolean;
  humanReview?: ReviewStatus;
  licenseReview?: ReviewStatus;
  errorCode?: ProviderErrorCode;
  message?: string;
  metrics?: ProviderResourceMetrics;
}

export interface ProviderRequestControl {
  requestId: string;
  sessionId: string;
  correlationId: string;
  turnId: string;
  timeoutMs: number;
  idempotencyKey?: string;
  cancelSignalId?: string;
  createdAt: string;
}

export interface ProviderLifecycle {
  initialize(): Promise<ProviderHealth>;
  healthCheck(): Promise<ProviderHealth>;
  cancel(requestId: string): Promise<ProviderResult<{ requestId: string; cancelled: boolean }>>;
}

export interface SttInput {
  control?: ProviderRequestControl;
  turnId: string;
  audioSegmentId: string;
  audioRef: string;
  languageHint?: string;
  format?: {
    codec: "pcm_s16le" | "wav" | "webm_opus" | "unknown";
    sampleRateHz: number;
    channels: number;
  };
  sequence?: {
    streamId: string;
    sequenceStart: number;
    sequenceEnd: number;
    missingChunks: number[];
  };
}

export interface SttTranscript {
  turnId: string;
  audioSegmentId: string;
  transcriptRedacted: string;
  transcriptHash?: string;
  confidence: number;
  language: string;
  startedAtMs: number;
  endedAtMs: number;
  isFinal: boolean;
  partial?: string;
  normalized?: {
    text: string;
    duplicateOfTurnId?: string;
    lowConfidence: boolean;
    piiTypes: string[];
  };
}

export interface SttProvider extends ProviderLifecycle {
  metadata: ProviderMetadata & { providerKind: "stt" };
  transcribe(input: SttInput): Promise<ProviderResult<SttTranscript>>;
}

export interface SafeConversationContext {
  turnId: string;
  sessionId: string;
  questionId?: string;
  childTextRedacted: string;
  historyRedacted: string[];
  pageContextText?: string;
  policyVersion: string;
}

export interface LlmReplyCandidate {
  turnId: string;
  replyDraft: string;
  contextVersion: string;
}

export interface LlmProvider {
  metadata: ProviderMetadata & { providerKind: "llm" };
  generateReply(input: SafeConversationContext): Promise<ProviderResult<LlmReplyCandidate>>;
}

export type SafetyReviewTarget = "input" | "output" | "report";
export type SafetyReviewAction = "allow" | "redact_then_allow" | "block" | "fallback" | "escalate_to_adult";

export interface SafetyReviewInput {
  requestId: string;
  target: SafetyReviewTarget;
  textRedacted: string;
  policyVersion: string;
}

export interface SafetyReviewDecision {
  requestId: string;
  target: SafetyReviewTarget;
  action: SafetyReviewAction;
  approvedText?: string;
  fallbackText?: string;
  piiTypes: string[];
  reasonCodes: string[];
  policyVersion: string;
}

export interface ChildSafetyProvider {
  metadata: ProviderMetadata & { providerKind: "safety_review" };
  review(input: SafetyReviewInput): Promise<ProviderResult<SafetyReviewDecision>>;
}

export interface TtsInput {
  control?: ProviderRequestControl;
  turnId: string;
  text: string;
  safety: SafetyReviewDecision;
  voice?: string;
  language?: string;
  audioFormat?: "wav" | "mp3" | "ogg" | "pcm";
}

export interface TtsAudio {
  turnId: string;
  audioRef: string;
  audioBase64?: string;
  mimeType: string;
  durationMs: number;
  sampleRateHz?: number;
  channels?: number;
  textHash?: string;
  marks: Array<{ name: string; offsetMs: number }>;
}

export interface TtsProvider extends ProviderLifecycle {
  metadata: ProviderMetadata & { providerKind: "tts" };
  synthesize(input: TtsInput): Promise<ProviderResult<TtsAudio>>;
}

export interface AttentionObservationInput {
  observationId: string;
  sessionId: string;
  questionId?: string;
  turnId?: string;
  eventId?: string;
  correlationId?: string;
  windowId?: string;
  source?: ObservationSource;
  observedAt: string;
}

export interface AttentionObservationProvider {
  metadata: ProviderMetadata & { providerKind: "attention_observation" };
  observe(input: AttentionObservationInput): Promise<ProviderResult<AttentionObservation>>;
}

export interface LanguageObservationInput {
  observationId: string;
  sessionId?: string;
  questionId?: string;
  turnId: string;
  eventId?: string;
  correlationId?: string;
  windowId?: string;
  source?: ObservationSource;
  transcriptRedacted: string;
  confidence?: number;
  observedAt: string;
}

export interface LanguageObservationProvider {
  metadata: ProviderMetadata & { providerKind: "language_observation" };
  observe(input: LanguageObservationInput): Promise<ProviderResult<LanguageObservation>>;
}

export type MockScenario =
  | "success"
  | "timeout"
  | "failure"
  | "empty"
  | "low_confidence"
  | "unsafe"
  | "rewrite";

export type AttentionMockScenario =
  | MockScenario
  | "face_present"
  | "no_face"
  | "multiple_faces"
  | "looking_away"
  | "occluded"
  | "camera_unavailable";

function mockMetadata(providerKind: ProviderKind, providerName: string): ProviderMetadata {
  return {
    providerKind,
    providerName,
    providerId: providerName,
    providerType: "mock",
    mode: "mock",
    version: "mock-v1",
    humanReview: "NOT_REQUIRED",
    licenseReview: "NOT_REQUIRED",
    dataSafety: {
      externalNetworkCalled: false,
      inputPersisted: false,
      rawAudioPersisted: false,
      sensitiveTextLogged: false,
      credentialsSource: "none",
      allowedData: ["synthetic", "developer_authorized", "authorized_non_child", "redacted_text"],
      notes: "Mock provider is deterministic and does not persist raw inputs."
    },
    fallback: {
      fallbackProviderIds: [],
      fallbackMode: "none"
    }
  };
}

function defaultMetrics(): ProviderResourceMetrics {
  return {
    gpuUsed: false,
    hardwareAcceleration: "none"
  };
}

function healthFromMetadata(metadata: ProviderMetadata): ProviderHealth {
  return {
    providerId: metadata.providerId ?? metadata.providerName,
    providerKind: metadata.providerKind,
    providerType: metadata.providerType ?? "mock",
    status: "READY",
    modelId: metadata.modelId,
    modelPath: metadata.modelPath,
    configPath: metadata.configPath,
    initialized: true,
    lastCheckedAt: new Date(0).toISOString(),
    externalNetworkCalled: metadata.dataSafety?.externalNetworkCalled ?? false,
    inputPersisted: metadata.dataSafety?.inputPersisted ?? false,
    humanReview: metadata.humanReview,
    licenseReview: metadata.licenseReview,
    metrics: defaultMetrics()
  };
}

export const DEFAULT_STT_PROVIDER_METADATA: ProviderMetadata & { providerKind: "stt" } = {
  providerKind: "stt",
  providerName: "Vosk small Mandarin local STT",
  providerId: "local-vosk-small-cn",
  providerType: "local",
  mode: "local",
  version: "m4-002b",
  modelId: "vosk-model-small-cn-0.22",
  modelPath: ".runtime/models/vosk/vosk-model-small-cn-0.22",
  defaultEnabled: true,
  humanReview: "NOT_REQUIRED",
  licenseReview: "COMPLETE",
  dataSafety: {
    externalNetworkCalled: false,
    inputPersisted: false,
    rawAudioPersisted: false,
    sensitiveTextLogged: false,
    credentialsSource: "none",
    allowedData: ["synthetic", "developer_authorized", "authorized_non_child"],
    notes: "Development default local STT. Raw audio is processed by the Python service and is not persisted by default."
  },
  fallback: {
    fallbackProviderIds: ["mock-stt"],
    fallbackMode: "manual_text",
    childSafeFallbackText: "我没有听清楚。你可以再说一次，或者用手点答案。"
  }
};

export const DEFAULT_TTS_PROVIDER_METADATA: ProviderMetadata & { providerKind: "tts" } = {
  providerKind: "tts",
  providerName: "Piper Huayan local TTS",
  providerId: "local-piper-zh-huayan",
  providerType: "local",
  mode: "local",
  version: "m4-002b",
  modelId: "zh_CN-huayan-medium",
  modelPath: ".runtime/models/piper/zh_CN-huayan-medium.onnx",
  configPath: ".runtime/models/piper/zh_CN-huayan-medium.onnx.json",
  defaultEnabled: true,
  humanReview: "HUMAN_REVIEW_PENDING",
  licenseReview: "REQUIRED_BEFORE_PRODUCTION",
  dataSafety: {
    externalNetworkCalled: false,
    inputPersisted: false,
    rawAudioPersisted: false,
    sensitiveTextLogged: false,
    credentialsSource: "none",
    allowedData: ["redacted_text"],
    notes: "Development default local TTS. Candidate requires human listening review and production license review."
  },
  fallback: {
    fallbackProviderIds: ["mock-tts"],
    fallbackMode: "display_text_only",
    childSafeFallbackText: "我先把回答显示出来，我们继续做题。"
  }
};

export const CLOUD_STT_PROVIDER_METADATA: ProviderMetadata & { providerKind: "stt" } = {
  providerKind: "stt",
  providerName: "OpenAI cloud STT candidate",
  providerId: "cloud-openai-stt",
  providerType: "cloud",
  mode: "external",
  version: "m4-002",
  vendorModelName: "whisper-1",
  defaultEnabled: false,
  humanReview: "NOT_REQUIRED",
  licenseReview: "REQUIRED_BEFORE_PRODUCTION",
  dataSafety: {
    externalNetworkCalled: false,
    inputPersisted: false,
    rawAudioPersisted: false,
    sensitiveTextLogged: false,
    credentialsSource: "environment",
    allowedData: ["synthetic", "developer_authorized", "authorized_non_child"],
    notes: "Cloud STT remains disabled unless credentials exist and an explicit benchmark switch is enabled."
  },
  fallback: {
    fallbackProviderIds: ["local-vosk-small-cn", "mock-stt"],
    fallbackMode: "manual_text"
  }
};

export const CLOUD_TTS_PROVIDER_METADATA: ProviderMetadata & { providerKind: "tts" } = {
  providerKind: "tts",
  providerName: "OpenAI cloud TTS candidate",
  providerId: "cloud-openai-tts",
  providerType: "cloud",
  mode: "external",
  version: "m4-002",
  vendorModelName: "gpt-4o-mini-tts",
  defaultEnabled: false,
  humanReview: "HUMAN_REVIEW_PENDING",
  licenseReview: "REQUIRED_BEFORE_PRODUCTION",
  dataSafety: {
    externalNetworkCalled: false,
    inputPersisted: false,
    rawAudioPersisted: false,
    sensitiveTextLogged: false,
    credentialsSource: "environment",
    allowedData: ["redacted_text"],
    notes: "Cloud TTS remains disabled unless credentials exist and an explicit benchmark switch is enabled."
  },
  fallback: {
    fallbackProviderIds: ["local-piper-zh-huayan", "mock-tts"],
    fallbackMode: "display_text_only"
  }
};

export const M4_SPEECH_PROVIDER_REGISTRY = {
  defaultSttProviderId: DEFAULT_STT_PROVIDER_METADATA.providerId,
  defaultTtsProviderId: DEFAULT_TTS_PROVIDER_METADATA.providerId,
  stt: [DEFAULT_STT_PROVIDER_METADATA, CLOUD_STT_PROVIDER_METADATA],
  tts: [DEFAULT_TTS_PROVIDER_METADATA, CLOUD_TTS_PROVIDER_METADATA]
} as const;

function success<TData>(metadata: ProviderMetadata, data: TData, latencyMs = 0): ProviderResult<TData> {
  return { ok: true, metadata, latencyMs, data, metrics: defaultMetrics() };
}

function failure<TData>(
  metadata: ProviderMetadata,
  code: ProviderErrorCode,
  message: string,
  fallbackText?: string,
  latencyMs = 0
): ProviderResult<TData> {
  return {
    ok: false,
    metadata,
    latencyMs,
    error: { code, message, retryable: code === "TIMEOUT" || code === "PROVIDER_FAILURE" },
    fallbackText,
    metrics: defaultMetrics()
  };
}

export class MockSttProvider implements SttProvider {
  metadata = mockMetadata("stt", "mock-stt") as ProviderMetadata & { providerKind: "stt" };

  constructor(private scenario: MockScenario = "success") {}

  async initialize(): Promise<ProviderHealth> {
    return healthFromMetadata(this.metadata);
  }

  async healthCheck(): Promise<ProviderHealth> {
    return healthFromMetadata(this.metadata);
  }

  async cancel(requestId: string): Promise<ProviderResult<{ requestId: string; cancelled: boolean }>> {
    return success(this.metadata, { requestId, cancelled: true });
  }

  async transcribe(input: SttInput): Promise<ProviderResult<SttTranscript>> {
    if (this.scenario === "timeout") {
      return failure(this.metadata, "TIMEOUT", "Mock STT timeout.");
    }
    if (this.scenario === "failure") {
      return failure(this.metadata, "PROVIDER_FAILURE", "Mock STT failure.");
    }
    if (this.scenario === "empty") {
      return failure(this.metadata, "EMPTY_RESULT", "Mock STT returned no final transcript.");
    }

    const confidence = this.scenario === "low_confidence" ? 0.35 : 0.96;
    return success(this.metadata, {
      turnId: input.turnId,
      audioSegmentId: input.audioSegmentId,
      transcriptRedacted: "我选择左边的图片",
      confidence,
      language: input.languageHint ?? "zh-CN",
      startedAtMs: 0,
      endedAtMs: 1200,
      isFinal: true,
      normalized: {
        text: "我选择左边的图片",
        lowConfidence: confidence < 0.6,
        piiTypes: []
      }
    });
  }
}

export class MockLlmProvider implements LlmProvider {
  metadata = mockMetadata("llm", "mock-llm") as ProviderMetadata & { providerKind: "llm" };

  constructor(private scenario: MockScenario = "success") {}

  async generateReply(input: SafeConversationContext): Promise<ProviderResult<LlmReplyCandidate>> {
    if (this.scenario === "timeout") {
      return failure(this.metadata, "TIMEOUT", "Mock LLM timeout.", "我们先继续当前题目。");
    }
    if (this.scenario === "failure") {
      return failure(this.metadata, "PROVIDER_FAILURE", "Mock LLM failure.", "我们先继续当前题目。");
    }
    if (this.scenario === "empty") {
      return failure(this.metadata, "EMPTY_RESULT", "Mock LLM returned an empty reply.", "我们先继续当前题目。");
    }

    const replyDraft =
      this.scenario === "unsafe"
        ? "这是不适合儿童的候选回复"
        : `做得好，我们继续看第 ${input.questionId ?? "当前"} 题。`;

    return success(this.metadata, {
      turnId: input.turnId,
      replyDraft,
      contextVersion: "mock-context-v1"
    });
  }
}

export class MockChildSafetyProvider implements ChildSafetyProvider {
  metadata = mockMetadata("safety_review", "mock-safety") as ProviderMetadata & { providerKind: "safety_review" };

  constructor(private scenario: MockScenario = "success") {}

  async review(input: SafetyReviewInput): Promise<ProviderResult<SafetyReviewDecision>> {
    if (this.scenario === "timeout") {
      return failure(this.metadata, "TIMEOUT", "Mock safety review timeout.", "这个内容需要老师或家长帮助。");
    }
    if (this.scenario === "failure") {
      return failure(this.metadata, "PROVIDER_FAILURE", "Mock safety review failure.", "这个内容需要老师或家长帮助。");
    }
    if (this.scenario === "unsafe") {
      return success(this.metadata, {
        requestId: input.requestId,
        target: input.target,
        action: "fallback",
        fallbackText: "这个内容我不能继续聊。我们回到当前题目吧。",
        piiTypes: [],
        reasonCodes: ["unsafe_mock_content"],
        policyVersion: input.policyVersion
      });
    }
    if (this.scenario === "rewrite") {
      return success(this.metadata, {
        requestId: input.requestId,
        target: input.target,
        action: "redact_then_allow",
        approvedText: input.textRedacted.replace(/[0-9]{3,}/g, "[redacted-number]"),
        piiTypes: ["number"],
        reasonCodes: ["pii_redacted"],
        policyVersion: input.policyVersion
      });
    }

    return success(this.metadata, {
      requestId: input.requestId,
      target: input.target,
      action: "allow",
      approvedText: input.textRedacted,
      piiTypes: [],
      reasonCodes: [],
      policyVersion: input.policyVersion
    });
  }
}

export class MockTtsProvider implements TtsProvider {
  metadata = mockMetadata("tts", "mock-tts") as ProviderMetadata & { providerKind: "tts" };

  constructor(private scenario: MockScenario = "success") {}

  async initialize(): Promise<ProviderHealth> {
    return healthFromMetadata(this.metadata);
  }

  async healthCheck(): Promise<ProviderHealth> {
    return healthFromMetadata(this.metadata);
  }

  async cancel(requestId: string): Promise<ProviderResult<{ requestId: string; cancelled: boolean }>> {
    return success(this.metadata, { requestId, cancelled: true });
  }

  async synthesize(input: TtsInput): Promise<ProviderResult<TtsAudio>> {
    const approvedText = input.safety.approvedText ?? input.safety.fallbackText;
    const canSynthesize = input.safety.action === "allow" || input.safety.action === "redact_then_allow" || input.safety.action === "fallback";

    if (!canSynthesize || !approvedText || approvedText !== input.text) {
      return failure(this.metadata, "UNREVIEWED_TEXT", "Mock TTS refuses text that has not passed safety review.");
    }
    if (this.scenario === "timeout") {
      return failure(this.metadata, "TIMEOUT", "Mock TTS timeout.");
    }
    if (this.scenario === "failure") {
      return failure(this.metadata, "PROVIDER_FAILURE", "Mock TTS failure.");
    }

    return success(this.metadata, {
      turnId: input.turnId,
      audioRef: `mock-audio:${input.turnId}`,
      audioBase64: "UklGRiQAAABXQVZFZm10IBAAAAABAAEA",
      mimeType: "audio/wav",
      durationMs: 900,
      sampleRateHz: 16000,
      channels: 1,
      marks: [
        { name: "speech_start", offsetMs: 0 },
        { name: "speech_end", offsetMs: 900 }
      ]
    });
  }
}

export class MockAttentionObservationProvider implements AttentionObservationProvider {
  metadata = mockMetadata("attention_observation", "mock-attention") as ProviderMetadata & {
    providerKind: "attention_observation";
  };

  constructor(private scenario: AttentionMockScenario = "success") {}

  async observe(input: AttentionObservationInput): Promise<ProviderResult<AttentionObservation>> {
    if (this.scenario === "failure") {
      return failure(this.metadata, "PROVIDER_FAILURE", "Mock attention observation failure.");
    }
    const cameraUnavailable = this.scenario === "empty" || this.scenario === "camera_unavailable";
    const lowConfidence = this.scenario === "low_confidence" || this.scenario === "occluded";
    const noFace = this.scenario === "no_face";
    const multipleFaces = this.scenario === "multiple_faces";
    const lookingAway = this.scenario === "looking_away";
    const qualityStatus: DataQualityStatus = cameraUnavailable ? "missing_device" : lowConfidence ? "low_confidence" : "complete";
    const confidence = lowConfidence ? 0.4 : cameraUnavailable ? 0 : 0.9;
    const observedAt = input.observedAt;
    const evidence = [
      {
        type: "provider_result" as const,
        id: `${input.observationId}:provider`,
        sessionId: input.sessionId,
        questionId: input.questionId,
        turnId: input.turnId,
        eventId: input.eventId,
        windowId: input.windowId,
        provider: this.metadata.providerId,
        createdAt: observedAt,
        redacted: true
      }
    ];

    return success(this.metadata, {
      observationId: input.observationId,
      observationType: "attention",
      sessionId: input.sessionId,
      questionId: input.questionId,
      turnId: input.turnId,
      eventId: input.eventId,
      correlationId: input.correlationId ?? input.observationId,
      windowId: input.windowId,
      startedAt: observedAt,
      endedAt: observedAt,
      observedAt,
      source: input.source ?? "mock_provider",
      provider: this.metadata.providerId ?? this.metadata.providerName,
      algorithm: {
        schemaVersion: "m5-behavior-v1",
        algorithmVersion: "mock-attention-v1",
        providerVersion: this.metadata.version
      },
      features: {
        kind: cameraUnavailable ? "camera_unavailable" : multipleFaces ? "face_count" : noFace ? "face_presence" : "screen_orientation",
        facePresent: cameraUnavailable || noFace ? false : true,
        faceCount: cameraUnavailable || noFace ? 0 : multipleFaces ? 2 : 1,
        headOrientation: cameraUnavailable || noFace ? "unknown" : lookingAway ? "away" : "screen",
        roughlyFacingScreen: cameraUnavailable || noFace ? undefined : !lookingAway,
        durationMs: 1000,
        imageQuality: cameraUnavailable ? "unavailable" : this.scenario === "occluded" ? "occluded" : "good",
        cameraAvailable: !cameraUnavailable
      },
      confidence,
      dataQuality: {
        status: qualityStatus,
        providerStatus: cameraUnavailable ? "not_available" : lowConfidence ? "degraded" : "ok",
        confidence
      },
      degraded: qualityStatus !== "complete",
      evidence,
      createdAt: observedAt
    });
  }
}

export class MockLanguageObservationProvider implements LanguageObservationProvider {
  metadata = mockMetadata("language_observation", "mock-language") as ProviderMetadata & {
    providerKind: "language_observation";
  };

  constructor(private scenario: MockScenario = "success") {}

  async observe(input: LanguageObservationInput): Promise<ProviderResult<LanguageObservation>> {
    if (this.scenario === "failure") {
      return failure(this.metadata, "PROVIDER_FAILURE", "Mock language observation failure.");
    }

    const textLength = input.transcriptRedacted.trim().length;
    const empty = textLength === 0;
    const lowConfidence = (input.confidence ?? 1) < 0.6 || this.scenario === "low_confidence";
    const qualityStatus: DataQualityStatus = empty ? "partial" : lowConfidence ? "low_confidence" : "complete";
    const observedAt = input.observedAt;
    const evidence = [
      {
        type: "transcript" as const,
        id: `${input.turnId}:transcript`,
        sessionId: input.sessionId ?? "",
        questionId: input.questionId,
        turnId: input.turnId,
        eventId: input.eventId,
        windowId: input.windowId,
        provider: this.metadata.providerId,
        createdAt: observedAt,
        redacted: true
      }
    ];
    return success(this.metadata, {
      observationId: input.observationId,
      observationType: "language",
      sessionId: input.sessionId ?? "",
      questionId: input.questionId,
      turnId: input.turnId,
      eventId: input.eventId,
      correlationId: input.correlationId ?? input.turnId,
      windowId: input.windowId,
      startedAt: observedAt,
      endedAt: observedAt,
      observedAt,
      source: input.source ?? "mock_provider",
      provider: this.metadata.providerId ?? this.metadata.providerName,
      algorithm: {
        schemaVersion: "m5-behavior-v1",
        algorithmVersion: "mock-language-v1",
        providerVersion: this.metadata.version
      },
      features: {
        kind: empty ? "empty_response" : "transcript_length",
        value: empty ? true : textLength,
        transcriptLength: textLength,
        sttConfidence: input.confidence
      },
      confidence: input.confidence ?? (empty ? 0 : 0.9),
      dataQuality: {
        status: qualityStatus,
        providerStatus: lowConfidence || empty ? "degraded" : "ok",
        confidence: input.confidence
      },
      degraded: qualityStatus !== "complete",
      evidence,
      createdAt: observedAt
    });
  }
}

export interface MockProviderSet {
  stt: SttProvider;
  llm: LlmProvider;
  safety: ChildSafetyProvider;
  tts: TtsProvider;
  attention: AttentionObservationProvider;
  language: LanguageObservationProvider;
}

export function createDefaultMockProviderSet(): MockProviderSet {
  return {
    stt: new MockSttProvider(),
    llm: new MockLlmProvider(),
    safety: new MockChildSafetyProvider(),
    tts: new MockTtsProvider(),
    attention: new MockAttentionObservationProvider(),
    language: new MockLanguageObservationProvider()
  };
}
