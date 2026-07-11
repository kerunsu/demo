import { runtimeConfig } from "../config/runtime.js";
import { deriveObservationAttentionScore } from "./attentionScoreUtils.js";
import { latestTurnAudioFeatures } from "./audioFeatureService.js";
import { latestSessionEmotionFeatures } from "./emotionFeatureService.js";
import { getLatestMonitorPreview, isMonitorPreviewEnabled } from "./monitorPreviewFrameService.js";
import { getSessionMediaSummary } from "./rawMediaPersistenceService.js";
import { getSessionSnapshot } from "./sessionSnapshotService.js";
import { getSession } from "./sessionLifecycleService.js";
import { behaviorObservationRepository } from "./behaviorFrameIngressService.js";
import { getSessionEvents } from "./domainEventService.js";
import { probePythonVoiceServiceHealth } from "./pythonVoiceHealthService.js";
import { getVoiceMetricsForSession } from "./voiceObservabilityService.js";
import { getPartnerTurnMonitorState } from "./voicePartnerTurnState.js";

type MonitorStageStatus = "pending" | "running" | "done" | "failed" | "degraded";

export async function getMonitorSnapshot(sessionId: string) {
  const snapshot = getSessionSnapshot(sessionId);
  const session = getSession(sessionId);
  const mediaSummary = await getSessionMediaSummary(sessionId);
  const events = getSessionEvents(sessionId);
  const observations = behaviorObservationRepository.listObservations(sessionId);
  const windows = behaviorObservationRepository.listWindows(sessionId);
  const summaries = behaviorObservationRepository.listQuestionSummaries(sessionId);
  const sessionSummary = behaviorObservationRepository.getSessionSummary(sessionId);
  const voiceMetrics = getVoiceMetricsForSession(sessionId);
  const partnerTurnState = getPartnerTurnMonitorState(sessionId);
  const pythonVoiceHealth = await probePythonVoiceServiceHealth();
  const currentQuestion = snapshot.currentQuestion;
  const latestAttention = [...observations].reverse().find((observation) => observation.observationType === "attention");
  const languageObservations = observations.filter((observation) => observation.observationType === "language");
  const emotionObservations = observations.filter((observation) => observation.observationType === "emotion");
  const latestAudioFeatures = latestTurnAudioFeatures(languageObservations as never);
  const latestEmotionFeatures = latestSessionEmotionFeatures(emotionObservations as never);
  const previewLatest = getLatestMonitorPreview(sessionId);
  const currentQuestionSummary = currentQuestion
    ? summaries.find((summary) => summary.questionId === currentQuestion.questionId)
    : undefined;
  const currentQuestionStartedAt = currentQuestion
    ? events.find((event) => event.eventType === "QUESTION_PRESENTED" && event.payload.questionId === currentQuestion.questionId)?.timestamp
    : undefined;
  const latestRobotAck = [...events].reverse().find((event) => event.eventType === "ANIMATION_STARTED" || event.eventType === "ANIMATION_FINISHED");
  const latestAnimationRequest = [...events].reverse().find((event) => event.eventType === "ANIMATION_REQUESTED");
  const questionStats = session.questionStats.map((stat, index) => ({
    questionIndex: index + 1,
    questionId: stat.questionId,
    correct: stat.correct,
    responseTimeMs: stat.responseTimeMs,
    attempted: stat.attempts > 0
  }));
  const attentionWindows = summaries.length > 0
    ? summaries.map((summary) => ({
        questionId: summary.questionId,
        score: deriveQuestionAttentionScore(summary),
        quality: summary.dataQuality.status,
        startedAt: summary.createdAt,
        endedAt: summary.createdAt
      }))
    : windows.map((window) => ({
        questionId: window.questionId,
        quality: "pending_summary",
        startedAt: window.startedAt,
        endedAt: window.endedAt
      }));
  const attentionSamples = observations
    .filter((observation) => observation.observationType === "attention")
    .slice(-120)
    .map((observation) => ({
      observedAt: observation.observedAt,
      questionId: observation.questionId,
      score: deriveObservationAttentionScore(observation),
      quality: observation.dataQuality.status
    }))
    .filter((sample) => typeof sample.score === "number");

  return {
    session: {
      sessionId: snapshot.session.sessionId,
      childAlias: snapshot.session.childName,
      courseType: snapshot.session.courseType,
      startedAt: snapshot.session.startedAt,
      state: snapshot.session.state
    },
    course: {
      currentQuestionIndex: snapshot.session.currentQuestionIndex,
      totalQuestions: currentQuestion?.total ?? Math.max(snapshot.session.currentQuestionIndex + 1, 1),
      accuracy: ratio(snapshot.session.correctAnswers, Math.max(currentQuestion?.total ?? 0, snapshot.session.currentQuestionIndex + 1)),
      averageResponseTimeMs: average(getResponseTimes(sessionId)),
      currentQuestionElapsedMs: currentQuestionStartedAt ? Math.max(0, Date.now() - Date.parse(currentQuestionStartedAt)) : undefined,
      currentQuestionPrompt: currentQuestion?.prompt,
      sessionDurationMs: snapshot.session.startedAt ? Math.max(0, Date.now() - Date.parse(snapshot.session.startedAt)) : undefined,
      questionStats
    },
    attention: {
      currentScore: deriveCurrentAttentionScore(observations, latestAttention),
      currentQuality: mapAttentionQuality(latestAttention?.dataQuality.status ?? sessionSummary?.dataQuality.status),
      currentProvider: latestAttention?.provider ?? runtimeConfig.attentionProvider,
      algorithmVersion:
        latestAttention && latestAttention.observationType === "attention"
          ? latestAttention.algorithm.algorithmVersion
          : undefined,
      confidence: latestAttention?.confidence,
      questionAttentionRatio: currentQuestionSummary
        ? deriveQuestionAttentionScore(currentQuestionSummary)
        : undefined,
      features: latestAttention && latestAttention.observationType === "attention"
        ? {
            facePresent: latestAttention.features.facePresent,
            roughlyFacingScreen: latestAttention.features.roughlyFacingScreen,
            headOrientation: latestAttention.features.headOrientation,
            faceCount: latestAttention.features.faceCount,
            imageQuality: latestAttention.features.imageQuality,
            facingScore: latestAttention.features.facingScore ?? deriveFacingScoreFromObservation(latestAttention)
          }
        : undefined,
      questionWindows: attentionWindows,
      attentionSamples
    },
    voice: {
      currentPipeline: buildVoicePipeline(voiceMetrics),
      latestTranscriptPreview: latestTextPreview(voiceMetrics, "transcript_available"),
      latestModelInputPreview: latestTextPreview(voiceMetrics, "chat_reply_generated"),
      latestReplyPreview: latestTextPreview(voiceMetrics, "tts_audio_ready"),
      totalTurnLatencyMs: deriveTotalTurnLatency(voiceMetrics),
      audioFeatures: latestAudioFeatures,
      dialogProvider: runtimeConfig.voiceDialogProvider,
      partnerLastLatencyMs: partnerTurnState?.partnerLastLatencyMs,
      partnerLastError: partnerTurnState?.partnerLastError,
      partnerLastProvider: partnerTurnState?.partnerLastProvider
    },
    emotion: {
      configuredProvider: runtimeConfig.emotionProvider,
      provider: latestEmotionFeatures?.provider ?? (runtimeConfig.emotionProvider === "local" ? "local-browser-face-emotion" : runtimeConfig.emotionProvider),
      algorithmVersion: latestEmotionFeatures?.algorithmVersion,
      degraded:
        runtimeConfig.emotionProvider === "none" ||
        runtimeConfig.emotionProvider === "heuristic" ||
        Boolean(latestEmotionFeatures?.degraded) ||
        !latestEmotionFeatures,
      positiveRatio: latestEmotionFeatures?.positiveRatio,
      focusedRatio: latestEmotionFeatures?.focusedRatio,
      frustratedRatio: latestEmotionFeatures?.frustratedRatio,
      observationCount: latestEmotionFeatures?.observationCount ?? 0,
      reason:
        runtimeConfig.emotionProvider === "none"
          ? "MANUAL_ACCEPTANCE_REQUIRED"
          : latestEmotionFeatures
            ? undefined
            : "INSUFFICIENT_SIGNALS"
    },
    preview: {
      enabled: isMonitorPreviewEnabled(),
      available: previewLatest.available,
      stale: Boolean(previewLatest.stale),
      capturedAt: previewLatest.capturedAt,
      expiresAt: previewLatest.expiresAt,
      frameId: previewLatest.meta?.frameId
    },
    robot: {
      currentAnimationId: latestAnimationRequest?.eventType === "ANIMATION_REQUESTED" ? latestAnimationRequest.payload.animationId : "eye",
      isSpeaking: hasStage(voiceMetrics, "robot_playback_start") && !hasStage(voiceMetrics, "robot_playback_complete"),
      lastAckAt: latestRobotAck?.timestamp
    },
    health: {
      backend: "ok",
      pythonVoiceService: pythonVoiceHealth.status,
      sqlite: "ok",
      websocket: events.some((event) => event.eventType === "CLIENT_CONNECTED") ? "ok" : "degraded:no_client_connection_event",
      vosk: runtimeConfig.sttProvider === "local" ? "configured_local" : "degraded:mock_or_unverified",
      piper: runtimeConfig.voiceTtsProvider === "local" ? "configured_local" : "degraded:mock_or_unverified",
      attentionProvider: runtimeConfig.attentionProvider,
      emotionProvider: runtimeConfig.emotionProvider
    },
    media: {
      rawMediaPersistence: runtimeConfig.rawMediaPersistence,
      retentionDays: runtimeConfig.rawMediaRetentionDays,
      requiresConsent: runtimeConfig.rawMediaRequireConsent,
      consentRecorded: mediaSummary?.consentRecorded ?? false,
      audioTurnCount: mediaSummary?.audioTurnCount ?? 0,
      videoStreamCount: mediaSummary?.videoStreamCount ?? 0,
      totalPersistedBytes: mediaSummary?.totalPersistedBytes ?? 0,
      missingChunkCount: mediaSummary?.missingChunkCount ?? 0,
      manualAcceptanceRequired: [
        "MANUAL_ACCEPTANCE_REQUIRED: real robot camera stream to server",
        mediaSummary?.missingChunkCount ? "MANUAL_ACCEPTANCE_REQUIRED: review missing media chunks in manifest" : "",
        "MANUAL_ACCEPTANCE_REQUIRED: raw media deletion and retention drill"
      ].filter(Boolean)
    },
    events: [...events].reverse().slice(0, 20).map((event) => ({
      id: event.eventId,
      at: event.timestamp,
      type: event.eventType,
      severity: eventSeverity(event.eventType),
      message: event.eventType,
      detail: JSON.stringify(event.payload).slice(0, 180)
    }))
  };
}

function getResponseTimes(sessionId: string) {
  return getSessionEvents(sessionId)
    .filter((event) => event.eventType === "ANSWER_SUBMITTED")
    .map((event) => event.payload.responseTimeMs)
    .filter((value): value is number => typeof value === "number");
}

function buildVoicePipeline(metrics: ReturnType<typeof getVoiceMetricsForSession>) {
  const latestByStage = new Map<string, (typeof metrics)[number]>();
  for (const metric of metrics) latestByStage.set(metric.stage, metric);
  return [
    "audio_capture_start",
    "first_audio_chunk",
    "vad_speech_start",
    "vad_speech_end",
    "stt_request_start",
    "stt_complete",
    "transcript_available",
    "chat_reply_generated",
    "safety_review",
    "tts_request_start",
    "tts_audio_ready",
    "robot_playback_start",
    "robot_playback_complete"
  ].map((stage) => {
    const metric = latestByStage.get(stage);
    return {
      stage,
      status: mapMetricStatus(metric?.status),
      latencyMs: metric?.durationMs,
      provider: metric?.provider,
      textPreview: metric?.textHash ? `hash:${metric.textHash}` : undefined,
      safetyStatus: stage === "safety_review" ? metric?.status ?? "pending" : undefined
    };
  });
}

function latestTextPreview(metrics: ReturnType<typeof getVoiceMetricsForSession>, stage: string) {
  const metric = [...metrics].reverse().find((item) => item.stage === stage);
  if (!metric) return undefined;
  if (metric.textHash) return `hash:${metric.textHash}; length:${metric.textLength ?? 0}`;
  return metric.provider ? `${metric.provider}; ${metric.status}` : metric.status;
}

function deriveFacingScoreFromObservation(
  observation: NonNullable<ReturnType<typeof behaviorObservationRepository.listObservations>[number]>
) {
  if (observation.observationType !== "attention") return undefined;
  if (typeof observation.features.facingScore === "number") return observation.features.facingScore;
  if (observation.features.roughlyFacingScreen === true) {
    return Math.round((observation.confidence ?? 0.75) * 100) / 100;
  }
  if (observation.features.roughlyFacingScreen === false) {
    return Math.round((observation.confidence ?? 0.35) * 0.45 * 100) / 100;
  }
  return undefined;
}

function deriveQuestionAttentionScore(
  summary: NonNullable<ReturnType<typeof behaviorObservationRepository.listQuestionSummaries>[number]>
) {
  if (typeof summary.attention?.averageFacingScore === "number") {
    return Math.round(summary.attention.averageFacingScore * 100);
  }
  return deriveSummaryAttentionScore(summary.attention?.screenOrientedMs, summary.attention?.observedMs);
}

function deriveCurrentAttentionScore(
  observations: ReturnType<typeof behaviorObservationRepository.listObservations>,
  latest = [...observations].reverse().find((observation) => observation.observationType === "attention")
) {
  if (!latest || latest.observationType !== "attention") return undefined;
  return deriveObservationAttentionScore(latest);
}

function deriveSummaryAttentionScore(screenOrientedMs?: number, observedMs?: number) {
  if (!screenOrientedMs || !observedMs) return undefined;
  return Math.round((screenOrientedMs / observedMs) * 100);
}

function mapAttentionQuality(status?: string): "VALID" | "DEGRADED" | "MISSING" {
  if (!status) return "MISSING";
  if (status === "complete") return "VALID";
  if (status === "missing_device" || status === "insufficient") return "MISSING";
  return "DEGRADED";
}

function mapMetricStatus(status?: string): MonitorStageStatus {
  if (!status) return "pending";
  if (status === "success") return "done";
  if (status === "failure" || status === "timeout" || status === "cancelled") return "failed";
  if (status === "degraded") return "degraded";
  return "running";
}

function eventSeverity(eventType: string): "info" | "warn" | "error" {
  if (eventType.includes("FAILED") || eventType.includes("REJECTED") || eventType.includes("DISCONNECTED")) return "error";
  if (eventType.includes("DEGRADED") || eventType.includes("FINISHED")) return "warn";
  return "info";
}

function hasStage(metrics: ReturnType<typeof getVoiceMetricsForSession>, stage: string) {
  return metrics.some((metric) => metric.stage === stage);
}

function ratio(numerator: number, denominator: number) {
  return denominator <= 0 ? 0 : Math.round((numerator / denominator) * 1000) / 1000;
}

function deriveTotalTurnLatency(metrics: ReturnType<typeof getVoiceMetricsForSession>) {
  const totalMetric = [...metrics].reverse().find((metric) => metric.stage === "voice_turn_total");
  if (totalMetric?.durationMs) return totalMetric.durationMs;
  const completedStages = metrics.filter((metric) => typeof metric.durationMs === "number");
  if (completedStages.length === 0) return undefined;
  return completedStages.reduce((sum, metric) => sum + (metric.durationMs ?? 0), 0);
}

function average(values: number[]) {
  if (values.length === 0) return 0;
  return Math.round(values.reduce((total, value) => total + value, 0) / values.length);
}
