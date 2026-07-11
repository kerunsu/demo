import type { DeterministicAssessmentResult } from "child-education-training-demo/shared/assessments";
import type { EmotionObservation, SessionBehaviorSummary } from "child-education-training-demo/shared/behavior-observations";
import { runtimeConfig } from "../config/runtime.js";
import { aggregateEmotionRatiosFromObservations } from "./emotionFeatureService.js";

export const EMOTION_HEURISTIC_VERSION = "emotion-heuristic-v1";
export const EMOTION_BROWSER_PROVIDER = "local-browser-face-emotion";

export interface EmotionSummaryResult {
  status: "AVAILABLE" | "DEGRADED";
  positiveRatio?: number;
  focusedRatio?: number;
  frustratedRatio?: number;
  reason?: "MANUAL_ACCEPTANCE_REQUIRED" | "INSUFFICIENT_SIGNALS";
  provider?: string;
  algorithmVersion?: string;
  degraded?: boolean;
  observationCount?: number;
}

export function aggregateSessionEmotion(input: {
  assessment: DeterministicAssessmentResult;
  sessionBehaviorSummary?: SessionBehaviorSummary;
  emotionObservations?: EmotionObservation[];
  totalWrongAttempts: number;
  totalQuestions: number;
}): EmotionSummaryResult {
  if (runtimeConfig.emotionProvider === "none") {
    return {
      status: "DEGRADED",
      reason: "MANUAL_ACCEPTANCE_REQUIRED",
      provider: "none",
      degraded: true
    };
  }

  if (runtimeConfig.emotionProvider === "heuristic") {
    return aggregateHeuristicEmotion(input);
  }

  const aggregated = aggregateEmotionRatiosFromObservations(input.emotionObservations ?? []);
  if (!aggregated.ok) {
    return {
      status: "DEGRADED",
      reason: aggregated.reason,
      provider: EMOTION_BROWSER_PROVIDER,
      algorithmVersion: "browser-emotion-v1",
      degraded: true,
      observationCount: aggregated.observationCount
    };
  }

  return {
    status: "AVAILABLE",
    positiveRatio: aggregated.positiveRatio,
    focusedRatio: aggregated.focusedRatio,
    frustratedRatio: aggregated.frustratedRatio,
    provider: aggregated.provider ?? EMOTION_BROWSER_PROVIDER,
    algorithmVersion: aggregated.algorithmVersion ?? "browser-emotion-v1",
    degraded: aggregated.degraded,
    observationCount: aggregated.observationCount
  };
}

function aggregateHeuristicEmotion(input: {
  assessment: DeterministicAssessmentResult;
  sessionBehaviorSummary?: SessionBehaviorSummary;
  totalWrongAttempts: number;
  totalQuestions: number;
}): EmotionSummaryResult {
  const firstTryAccuracy = input.assessment.sessionMetrics.firstTryAccuracy;
  const wrongRate = ratio(input.totalWrongAttempts, Math.max(input.totalQuestions, 1));
  const attentionRatio = input.sessionBehaviorSummary?.attention?.screenOrientedRatio ?? 0;
  const language = input.sessionBehaviorSummary?.language;
  const emptyResponses = language?.emptyResponseCount ?? 0;
  const repeatedResponses = language?.repeatedResponseCount ?? 0;
  const responseCount = language?.responseCount ?? 0;

  let positive = 0.35 + firstTryAccuracy * 0.35 + (responseCount > 0 ? 0.1 : 0);
  let focused = 0.25 + attentionRatio * 0.45;
  let frustrated = wrongRate * 0.35 + emptyResponses * 0.05 + repeatedResponses * 0.08;

  if (positive + focused + frustrated < 0.15) {
    return {
      status: "DEGRADED",
      reason: "INSUFFICIENT_SIGNALS",
      provider: "local-emotion-heuristic",
      algorithmVersion: EMOTION_HEURISTIC_VERSION,
      degraded: true
    };
  }

  const normalized = normalizeRatios(positive, focused, frustrated);
  return {
    status: "AVAILABLE",
    positiveRatio: normalized.positive,
    focusedRatio: normalized.focused,
    frustratedRatio: normalized.frustrated,
    provider: "local-emotion-heuristic",
    algorithmVersion: EMOTION_HEURISTIC_VERSION,
    degraded: true
  };
}

function normalizeRatios(positive: number, focused: number, frustrated: number) {
  const total = positive + focused + frustrated;
  if (total <= 0) return { positive: 0.34, focused: 0.33, frustrated: 0.33 };
  return {
    positive: round(positive / total),
    focused: round(focused / total),
    frustrated: round(frustrated / total)
  };
}

function ratio(numerator: number, denominator: number) {
  return denominator <= 0 ? 0 : numerator / denominator;
}

function round(value: number) {
  return Math.round(value * 1000) / 1000;
}
