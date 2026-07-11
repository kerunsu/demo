import type { BrowserTurnAudioFeatureDescriptor } from "child-education-training-demo/shared/behavior-frames";
import type { LanguageObservation } from "child-education-training-demo/shared/behavior-observations";
import { createEvidenceReference } from "child-education-training-demo/shared/behavior-observations";
import { behaviorObservationRepository } from "./behaviorFrameIngressService.js";
import { getOpenQuestionWindow } from "./behaviorTimelineOrchestratorService.js";
import { findSession } from "./sessionLifecycleService.js";

export interface PersistBrowserAudioFeaturesInput {
  descriptor: BrowserTurnAudioFeatureDescriptor;
}

export function receiveBrowserAudioFeatures(input: PersistBrowserAudioFeaturesInput) {
  const observations = extractBrowserAudioFeatureObservations(input.descriptor);
  for (const observation of observations) {
    behaviorObservationRepository.saveObservation(observation);
  }
  return {
    sessionId: input.descriptor.sessionId,
    turnId: input.descriptor.turnId,
    accepted: true,
    observationCount: observations.length
  };
}

export function extractBrowserAudioFeatureObservations(descriptor: BrowserTurnAudioFeatureDescriptor): LanguageObservation[] {
  const session = findSession(descriptor.sessionId);
  const open = getOpenQuestionWindow(descriptor.sessionId);
  const questionId = descriptor.questionId ?? open?.questionId ?? session?.questions[session.currentQuestionIndex]?.id;
  const observedAt = descriptor.observedAt;
  const dataQuality = descriptor.features.degraded
    ? { status: "partial" as const, providerStatus: "degraded" as const, reasonCode: "LOW_AUDIO_SIGNAL" }
    : { status: "complete" as const, providerStatus: "ok" as const };

  const base = {
    sessionId: descriptor.sessionId,
    questionId,
    turnId: descriptor.turnId,
    correlationId: descriptor.correlationId,
    windowId: open ? `window:${descriptor.sessionId}:${open.questionId}` : undefined,
    observedAt,
    audioDurationMs: descriptor.audioDurationMs,
    degraded: descriptor.features.degraded,
    dataQuality,
    provider: descriptor.provider,
    algorithmVersion: descriptor.features.algorithmVersion
  };

  return [
    createAudioFeatureObservation(base, "audio_loudness_rms", descriptor.features.loudnessRms),
    createAudioFeatureObservation(base, "audio_loudness_db", descriptor.features.loudnessDb),
    createAudioFeatureObservation(base, "audio_speech_ratio", descriptor.features.speechRatio),
    createAudioFeatureObservation(base, "audio_clarity_proxy", descriptor.features.clarityProxy)
  ];
}

function createAudioFeatureObservation(
  input: {
    sessionId: string;
    questionId?: string;
    turnId: string;
    correlationId: string;
    windowId?: string;
    observedAt: string;
    audioDurationMs: number;
    degraded: boolean;
    dataQuality: LanguageObservation["dataQuality"];
    provider: string;
    algorithmVersion: string;
  },
  kind: LanguageObservation["features"]["kind"],
  value: number
): LanguageObservation {
  const evidence = [
    createEvidenceReference({
      type: "voice_turn",
      id: `${input.turnId}:audio-features`,
      sessionId: input.sessionId,
      questionId: input.questionId,
      turnId: input.turnId,
      windowId: input.windowId,
      provider: input.provider
    })
  ];

  return {
    observationId: `language:${input.sessionId}:${input.turnId}:${kind}`,
    observationType: "language",
    sessionId: input.sessionId,
    questionId: input.questionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    windowId: input.windowId,
    startedAt: input.observedAt,
    endedAt: input.observedAt,
    observedAt: input.observedAt,
    source: "microphone",
    provider: input.provider,
    algorithm: {
      schemaVersion: "m5-behavior-v1",
      algorithmVersion: input.algorithmVersion,
      ruleVersion: input.algorithmVersion
    },
    features: {
      kind,
      value,
      audioDurationMs: input.audioDurationMs
    },
    confidence: input.degraded ? 0.5 : 0.9,
    dataQuality: input.dataQuality,
    degraded: input.degraded,
    evidence,
    createdAt: input.observedAt
  };
}

export function averageNumericLanguageFeature(
  observations: LanguageObservation[],
  kind: LanguageObservation["features"]["kind"]
) {
  const values = observations
    .filter((observation) => observation.features.kind === kind)
    .map((observation) => observation.features.value)
    .filter((value): value is number => typeof value === "number");
  if (values.length === 0) return undefined;
  return round(values.reduce((sum, value) => sum + value, 0) / values.length);
}

export function latestAudioFeatureProvider(observations: LanguageObservation[]) {
  const audioKinds = new Set(["audio_loudness_rms", "audio_loudness_db", "audio_speech_ratio", "audio_clarity_proxy"]);
  const audioObservations = observations.filter((observation) => audioKinds.has(observation.features.kind));
  if (audioObservations.length === 0) return undefined;
  const latest = audioObservations[audioObservations.length - 1]!;
  return {
    provider: latest.provider,
    algorithmVersion: latest.algorithm.algorithmVersion,
    degraded: audioObservations.some((observation) => observation.degraded)
  };
}

export function latestTurnAudioFeatures(observations: LanguageObservation[]) {
  const audioKinds = new Set(["audio_loudness_rms", "audio_loudness_db", "audio_speech_ratio", "audio_clarity_proxy"]);
  const audioObservations = observations.filter((observation) => audioKinds.has(observation.features.kind));
  if (audioObservations.length === 0) return undefined;
  const latestTurnId = audioObservations[audioObservations.length - 1]!.turnId;
  const turnObservations = audioObservations.filter((observation) => observation.turnId === latestTurnId);
  const meta = latestAudioFeatureProvider(turnObservations);
  if (!meta) return undefined;
  return {
    loudnessRms: averageNumericLanguageFeature(turnObservations, "audio_loudness_rms"),
    loudnessDb: averageNumericLanguageFeature(turnObservations, "audio_loudness_db"),
    speechRatio: averageNumericLanguageFeature(turnObservations, "audio_speech_ratio"),
    clarityProxy: averageNumericLanguageFeature(turnObservations, "audio_clarity_proxy"),
    provider: meta.provider,
    algorithmVersion: meta.algorithmVersion,
    degraded: meta.degraded
  };
}

function round(value: number) {
  return Math.round(value * 1000) / 1000;
}
