import { apiRequest } from "./api";

export interface MonitorSnapshot {
  session: {
    sessionId: string;
    childAlias?: string;
    courseType?: string;
    startedAt?: string;
    state: string;
  };
  course: {
    currentQuestionIndex: number;
    totalQuestions: number;
    accuracy: number;
    averageResponseTimeMs: number;
    currentQuestionElapsedMs?: number;
    currentQuestionPrompt?: string;
    sessionDurationMs?: number;
    questionStats: Array<{
      questionIndex: number;
      questionId: string;
      correct: boolean;
      responseTimeMs: number;
      attempted: boolean;
    }>;
  };
  attention: {
    currentScore?: number;
    currentQuality: "VALID" | "DEGRADED" | "MISSING";
    currentProvider?: string;
    algorithmVersion?: string;
    confidence?: number;
    questionAttentionRatio?: number;
    features?: {
      facePresent?: boolean;
      roughlyFacingScreen?: boolean;
      headOrientation?: string;
      faceCount?: number;
      imageQuality?: string;
      facingScore?: number;
    };
    questionWindows: Array<{
      questionId: string;
      score?: number;
      quality: string;
      startedAt: string;
      endedAt?: string;
    }>;
    attentionSamples: Array<{
      observedAt: string;
      questionId?: string;
      score?: number;
      quality: string;
    }>;
  };
  voice: {
    currentPipeline: Array<{
      stage: string;
      status: "pending" | "running" | "done" | "failed" | "degraded";
      latencyMs?: number;
      provider?: string;
      textPreview?: string;
      safetyStatus?: string;
    }>;
    latestTranscriptPreview?: string;
    latestModelInputPreview?: string;
    latestReplyPreview?: string;
    totalTurnLatencyMs?: number;
    dialogProvider?: "rule" | "partner";
    partnerLastLatencyMs?: number;
    partnerLastError?: string;
    partnerLastProvider?: string;
    audioFeatures?: {
      loudnessRms?: number;
      loudnessDb?: number;
      speechRatio?: number;
      clarityProxy?: number;
      provider?: string;
      algorithmVersion?: string;
      degraded?: boolean;
    };
  };
  emotion: {
    configuredProvider: "local" | "heuristic" | "none";
    provider?: string;
    algorithmVersion?: string;
    degraded: boolean;
    positiveRatio?: number;
    focusedRatio?: number;
    frustratedRatio?: number;
    observationCount: number;
    reason?: "MANUAL_ACCEPTANCE_REQUIRED" | "INSUFFICIENT_SIGNALS";
  };
  robot: {
    currentAnimationId: string;
    isSpeaking: boolean;
    lastAckAt?: string;
  };
  health: Record<string, string>;
  media: {
    rawMediaPersistence: "disabled" | "enabled";
    retentionDays: number;
    requiresConsent: boolean;
    consentRecorded: boolean;
    audioTurnCount: number;
    videoStreamCount: number;
    totalPersistedBytes: number;
    missingChunkCount: number;
    manualAcceptanceRequired: string[];
  };
  events: Array<{
    id: string;
    at: string;
    type: string;
    severity: "info" | "warn" | "error";
    message: string;
    detail?: string;
  }>;
  preview?: {
    enabled: boolean;
    available: boolean;
    stale: boolean;
    capturedAt?: string;
    expiresAt?: string;
    frameId?: string;
  };
}

export function getMonitorSnapshot(sessionId: string) {
  return apiRequest<MonitorSnapshot>(`/monitor/session/${sessionId}/snapshot`);
}
