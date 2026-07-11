import type { EmotionObservation } from "child-education-training-demo/shared/behavior-observations";
import { normalizeEmotionCategoryScores } from "child-education-training-demo/shared/emotion-scoring";

const MIN_USABLE_EMOTION_OBSERVATIONS = 2;

export function listUsableEmotionScoreObservations(observations: EmotionObservation[]) {
  return observations.filter(
    (observation) =>
      observation.features.kind === "frame_emotion_scores" &&
      observation.features.facePresent === true &&
      observation.dataQuality.status !== "missing_device"
  );
}

export function averageEmotionFeature(
  observations: EmotionObservation[],
  field: "positiveScore" | "focusedScore" | "frustratedScore"
) {
  const values = listUsableEmotionScoreObservations(observations)
    .map((observation) => observation.features[field])
    .filter((value): value is number => typeof value === "number");
  if (values.length === 0) return undefined;
  return round(values.reduce((sum, value) => sum + value, 0) / values.length);
}

export function latestEmotionFeatureProvider(observations: EmotionObservation[]) {
  const usable = listUsableEmotionScoreObservations(observations);
  if (usable.length === 0) return undefined;
  const latest = usable[usable.length - 1]!;
  return {
    provider: latest.provider,
    algorithmVersion: latest.algorithm.algorithmVersion,
    degraded: usable.some((observation) => observation.degraded)
  };
}

export function aggregateEmotionRatiosFromObservations(observations: EmotionObservation[]) {
  const usable = listUsableEmotionScoreObservations(observations);
  if (usable.length < MIN_USABLE_EMOTION_OBSERVATIONS) {
    return {
      ok: false as const,
      reason: "INSUFFICIENT_SIGNALS" as const,
      observationCount: usable.length
    };
  }

  const positive = averageEmotionFeature(usable, "positiveScore") ?? 0;
  const focused = averageEmotionFeature(usable, "focusedScore") ?? 0;
  const frustrated = averageEmotionFeature(usable, "frustratedScore") ?? 0;
  const normalized = normalizeEmotionCategoryScores({
    positive,
    focused,
    frustrated,
    confidence: average(usable.map((observation) => observation.confidence)) ?? 0.5
  });
  const meta = latestEmotionFeatureProvider(usable)!;

  return {
    ok: true as const,
    positiveRatio: normalized.positive,
    focusedRatio: normalized.focused,
    frustratedRatio: normalized.frustrated,
    provider: meta.provider,
    algorithmVersion: meta.algorithmVersion,
    degraded: meta.degraded,
    observationCount: usable.length
  };
}

export function latestSessionEmotionFeatures(observations: EmotionObservation[]) {
  const usable = listUsableEmotionScoreObservations(observations).slice(-12);
  if (usable.length === 0) return undefined;
  const meta = latestEmotionFeatureProvider(usable);
  if (!meta) return undefined;
  const positive = averageEmotionFeature(usable, "positiveScore");
  const focused = averageEmotionFeature(usable, "focusedScore");
  const frustrated = averageEmotionFeature(usable, "frustratedScore");
  return {
    positiveRatio: positive,
    focusedRatio: focused,
    frustratedRatio: frustrated,
    provider: meta.provider,
    algorithmVersion: meta.algorithmVersion,
    degraded: meta.degraded,
    observationCount: usable.length
  };
}

function average(values: number[]) {
  if (values.length === 0) return undefined;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function round(value: number) {
  return Math.round(value * 1000) / 1000;
}
