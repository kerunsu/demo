import type {
  AttentionObservation,
  BehaviorObservation,
  DataQuality,
  EmotionObservation,
  EvidenceReference,
  LanguageObservation,
  ObservationWindow,
  QuestionBehaviorSummary,
  SessionBehaviorSummary
} from "child-education-training-demo/shared/behavior-observations";
import { createEvidenceReference } from "child-education-training-demo/shared/behavior-observations";
import { averageFacingScoreFromObservations } from "./attentionScoreUtils.js";
import { averageNumericLanguageFeature, latestAudioFeatureProvider } from "./audioFeatureService.js";
import {
  averageEmotionFeature,
  latestEmotionFeatureProvider,
  listUsableEmotionScoreObservations
} from "./emotionFeatureService.js";
import { dedupeObservations } from "./behaviorTimelineService.js";

export function aggregateQuestionBehavior(input: {
  sessionId: string;
  questionId: string;
  correlationId: string;
  window: ObservationWindow;
  observations: BehaviorObservation[];
}): QuestionBehaviorSummary {
  const observations = dedupeObservations(input.observations).filter((observation) =>
    input.window.observationIds.includes(observation.observationId)
  );
  const attention = observations.filter((observation) => observation.observationType === "attention");
  const language = observations.filter((observation) => observation.observationType === "language");
  const emotion = observations.filter((observation) => observation.observationType === "emotion");
  const evidence = buildEvidence(input.sessionId, input.questionId, input.window.windowId, observations);
  const attentionObservedMs = sumFeatureDuration(attention);
  const screenOrientedMs = sumFeatureDuration(attention.filter((observation) => observation.features.roughlyFacingScreen === true));
  const unavailableMs = sumFeatureDuration(attention.filter((observation) => observation.dataQuality.status === "missing_device"));
  const orientationInterruptedMs = Math.max(0, attentionObservedMs - screenOrientedMs - unavailableMs);
  const averageFacingScore = averageFacingScoreFromObservations(attention as AttentionObservation[]);
  const responsePresence = language.find((observation) => observation.features.kind === "speech_presence");
  const transcriptLength = language.find((observation) => observation.features.kind === "transcript_length");
  const sentenceCount = language.find((observation) => observation.features.kind === "sentence_count");
  const emptyResponse = language.find((observation) => observation.features.kind === "empty_response");
  const repeatedResponse = language.find((observation) => observation.features.kind === "repeated_response");
  const languageObservations = language as LanguageObservation[];
  const emotionObservations = emotion as EmotionObservation[];
  const audioMeta = latestAudioFeatureProvider(languageObservations);
  const emotionMeta = latestEmotionFeatureProvider(emotionObservations);
  const usableEmotion = listUsableEmotionScoreObservations(emotionObservations);

  return {
    summaryId: `question-summary:${input.sessionId}:${input.questionId}`,
    sessionId: input.sessionId,
    questionId: input.questionId,
    windowId: input.window.windowId,
    correlationId: input.correlationId,
    attention:
      attention.length > 0
        ? {
            observedMs: attentionObservedMs,
            screenOrientedMs,
            orientationInterruptedMs,
            unavailableMs,
            averageFacingScore,
            quality: combineQuality(attention.map((observation) => observation.dataQuality))
          }
        : undefined,
    language:
      language.length > 0
        ? {
            responsePresent: Boolean(responsePresence?.features.value),
            responseLatencyMs: firstNumericFeature(language, "response_latency_ms"),
            audioDurationMs: firstNumericFeature(language, "audio_duration_ms"),
            transcriptLength: asNumber(transcriptLength?.features.value),
            sentenceCount: asNumber(sentenceCount?.features.value),
            emptyResponse: Boolean(emptyResponse?.features.value),
            repeatedResponse: Boolean(repeatedResponse?.features.value),
            averageLoudnessRms: averageNumericLanguageFeature(languageObservations, "audio_loudness_rms"),
            averageLoudnessDb: averageNumericLanguageFeature(languageObservations, "audio_loudness_db"),
            averageSpeechRatio: averageNumericLanguageFeature(languageObservations, "audio_speech_ratio"),
            averageClarityProxy: averageNumericLanguageFeature(languageObservations, "audio_clarity_proxy"),
            audioFeatureProvider: audioMeta?.provider,
            audioFeatureAlgorithmVersion: audioMeta?.algorithmVersion,
            audioFeatureDegraded: audioMeta?.degraded,
            quality: combineQuality(language.map((observation) => observation.dataQuality))
          }
        : undefined,
    emotion:
      usableEmotion.length > 0
        ? {
            observedMs: sumEmotionDuration(emotionObservations),
            averagePositiveScore: averageEmotionFeature(emotionObservations, "positiveScore"),
            averageFocusedScore: averageEmotionFeature(emotionObservations, "focusedScore"),
            averageFrustratedScore: averageEmotionFeature(emotionObservations, "frustratedScore"),
            emotionFeatureProvider: emotionMeta?.provider,
            emotionFeatureAlgorithmVersion: emotionMeta?.algorithmVersion,
            emotionFeatureDegraded: emotionMeta?.degraded,
            quality: combineQuality(emotion.map((observation) => observation.dataQuality))
          }
        : undefined,
    evidence,
    algorithm: {
      schemaVersion: "m5-behavior-v1",
      algorithmVersion: "question-behavior-aggregation-v1"
    },
    dataQuality: combineQuality(observations.map((observation) => observation.dataQuality)),
    createdAt: new Date().toISOString()
  };
}

export function aggregateSessionBehavior(input: {
  sessionId: string;
  courseType?: string;
  questionSummaries: QuestionBehaviorSummary[];
}): SessionBehaviorSummary {
  const summaries = [...input.questionSummaries];
  const totalObservedMs = sum(summaries.map((summary) => summary.attention?.observedMs ?? 0));
  const screenOrientedMs = sum(summaries.map((summary) => summary.attention?.screenOrientedMs ?? 0));
  const unavailableMs = sum(summaries.map((summary) => summary.attention?.unavailableMs ?? 0));
  const languageSummaries = summaries.map((summary) => summary.language).filter(Boolean);
  const loudnessValues = languageSummaries
    .map((summary) => summary?.averageLoudnessRms)
    .filter((value): value is number => typeof value === "number");
  const speechRatioValues = languageSummaries
    .map((summary) => summary?.averageSpeechRatio)
    .filter((value): value is number => typeof value === "number");
  const clarityValues = languageSummaries
    .map((summary) => summary?.averageClarityProxy)
    .filter((value): value is number => typeof value === "number");
  const audioFeatureTurnCount = languageSummaries.filter(
    (summary) => typeof summary?.averageLoudnessRms === "number"
  ).length;
  const responseLatencies = languageSummaries
    .map((summary) => summary?.responseLatencyMs)
    .filter((value): value is number => typeof value === "number")
    .sort((left, right) => left - right);
  const emotionSummaries = summaries.map((summary) => summary.emotion).filter(Boolean);
  const positiveScores = emotionSummaries
    .map((summary) => summary?.averagePositiveScore)
    .filter((value): value is number => typeof value === "number");
  const focusedScores = emotionSummaries
    .map((summary) => summary?.averageFocusedScore)
    .filter((value): value is number => typeof value === "number");
  const frustratedScores = emotionSummaries
    .map((summary) => summary?.averageFrustratedScore)
    .filter((value): value is number => typeof value === "number");

  return {
    summaryId: `session-summary:${input.sessionId}`,
    sessionId: input.sessionId,
    courseType: input.courseType,
    questionSummaryIds: summaries.map((summary) => summary.summaryId),
    attention:
      summaries.some((summary) => summary.attention)
        ? {
            totalObservedMs,
            screenOrientedRatio: totalObservedMs > 0 ? round(screenOrientedMs / totalObservedMs) : undefined,
            unavailableRatio: totalObservedMs > 0 ? round(unavailableMs / totalObservedMs) : undefined,
            quality: combineQuality(summaries.map((summary) => summary.attention?.quality).filter(Boolean) as DataQuality[])
          }
        : undefined,
    language:
      languageSummaries.length > 0
        ? {
            responseCount: languageSummaries.filter((summary) => summary?.responsePresent).length,
            emptyResponseCount: languageSummaries.filter((summary) => summary?.emptyResponse).length,
            repeatedResponseCount: languageSummaries.filter((summary) => summary?.repeatedResponse).length,
            medianResponseLatencyMs: median(responseLatencies),
            lowConfidenceTranscriptCount: summaries.filter((summary) => summary.language?.quality.status === "low_confidence").length,
            averageLoudnessRms: average(loudnessValues),
            averageSpeechRatio: average(speechRatioValues),
            averageClarityProxy: average(clarityValues),
            audioFeatureTurnCount,
            audioFeatureDegraded: languageSummaries.some((summary) => summary?.audioFeatureDegraded),
            quality: combineQuality(summaries.map((summary) => summary.language?.quality).filter(Boolean) as DataQuality[])
          }
        : undefined,
    emotion:
      emotionSummaries.length > 0
        ? {
            observationCount: emotionSummaries.length,
            averagePositiveScore: average(positiveScores),
            averageFocusedScore: average(focusedScores),
            averageFrustratedScore: average(frustratedScores),
            emotionFeatureProvider: emotionSummaries.find((summary) => summary?.emotionFeatureProvider)?.emotionFeatureProvider,
            emotionFeatureAlgorithmVersion: emotionSummaries.find((summary) => summary?.emotionFeatureAlgorithmVersion)
              ?.emotionFeatureAlgorithmVersion,
            emotionFeatureDegraded: emotionSummaries.some((summary) => summary?.emotionFeatureDegraded),
            quality: combineQuality(emotionSummaries.map((summary) => summary?.quality).filter(Boolean) as DataQuality[])
          }
        : undefined,
    evidence: summaries.flatMap((summary) => summary.evidence),
    algorithm: {
      schemaVersion: "m5-behavior-v1",
      algorithmVersion: "session-behavior-aggregation-v1"
    },
    dataQuality: combineQuality(summaries.map((summary) => summary.dataQuality)),
    environmentPending: ["real_robot_camera", "classroom_lighting", "human_annotation_validation"],
    ownerRequiredBeforeScoring: ["formal_attention_thresholds", "formal_language_weights", "norms_and_percentiles"],
    createdAt: new Date().toISOString()
  };
}

function buildEvidence(sessionId: string, questionId: string, windowId: string, observations: BehaviorObservation[]): EvidenceReference[] {
  const refs = [
    createEvidenceReference({
      type: "observation_window",
      id: windowId,
      sessionId,
      questionId,
      windowId
    }),
    ...observations.map((observation) =>
      createEvidenceReference({
        type: "observation",
        id: observation.observationId,
        sessionId,
        questionId,
        turnId: observation.turnId,
        eventId: observation.eventId,
        windowId,
        provider: observation.provider
      })
    )
  ];
  return refs;
}

function combineQuality(qualities: DataQuality[]): DataQuality {
  if (qualities.length === 0) return { status: "insufficient", reasonCode: "NO_INPUTS" };
  if (qualities.some((quality) => quality.status === "missing_device")) return { status: "partial", reasonCode: "MISSING_DEVICE_INPUT" };
  if (qualities.some((quality) => quality.status === "low_confidence")) return { status: "low_confidence", reasonCode: "LOW_CONFIDENCE_INPUT" };
  if (qualities.some((quality) => quality.status !== "complete")) return { status: "partial", reasonCode: "PARTIAL_INPUT" };
  return { status: "complete" };
}

function sumFeatureDuration(observations: BehaviorObservation[]) {
  return sum(observations.map((observation) => observation.observationType === "attention" ? observation.features.durationMs ?? 0 : 0));
}

function sumEmotionDuration(observations: EmotionObservation[]) {
  return sum(observations.map((observation) => observation.features.durationMs ?? 0));
}

function firstNumericFeature(observations: BehaviorObservation[], kind: string) {
  for (const observation of observations) {
    if (observation.observationType === "language" && observation.features.kind === kind) {
      return asNumber(observation.features.value);
    }
  }
  return undefined;
}

function asNumber(value: unknown) {
  return typeof value === "number" ? value : undefined;
}

function sum(values: number[]) {
  return values.reduce((total, value) => total + value, 0);
}

function median(values: number[]) {
  if (values.length === 0) return undefined;
  return values[Math.floor(values.length / 2)];
}

function average(values: number[]) {
  if (values.length === 0) return undefined;
  return round(values.reduce((total, value) => total + value, 0) / values.length);
}

function round(value: number) {
  return Math.round(value * 1000) / 1000;
}
