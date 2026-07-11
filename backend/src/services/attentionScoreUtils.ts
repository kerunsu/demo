import type { AttentionObservation } from "child-education-training-demo/shared/behavior-observations";
import { behaviorObservationRepository } from "./behaviorFrameIngressService.js";

export function deriveObservationAttentionScore(observation: AttentionObservation) {
  if (observation.observationType !== "attention") return undefined;
  const features = observation.features;
  if (typeof features.facingScore === "number") {
    return Math.round(features.facingScore * 100);
  }
  if (features.roughlyFacingScreen === true) {
    return Math.round((observation.confidence ?? 0.75) * 100);
  }
  if (features.roughlyFacingScreen === false) {
    return Math.round((observation.confidence ?? 0.35) * 0.45 * 100);
  }
  if (features.facePresent === false) return 0;
  return Math.round((observation.confidence ?? 0.45) * 100);
}

export function averageFacingScoreFromObservations(observations: AttentionObservation[]) {
  const scores = observations
    .map((observation) => observation.features.facingScore)
    .filter((value): value is number => typeof value === "number");
  if (scores.length === 0) return undefined;
  return round(scores.reduce((sum, value) => sum + value, 0) / scores.length);
}

function round(value: number) {
  return Math.round(value * 1000) / 1000;
}

function averageObservationScores(observations: AttentionObservation[]) {
  const scores = observations
    .map((observation) => deriveObservationAttentionScore(observation))
    .filter((value): value is number => typeof value === "number");
  if (scores.length === 0) return undefined;
  return Math.round(scores.reduce((sum, value) => sum + value, 0) / scores.length);
}

export function buildPerQuestionAttentionScores(sessionId: string, questionIds: string[]) {
  const observations = behaviorObservationRepository
    .listObservations(sessionId)
    .filter((observation): observation is AttentionObservation => observation.observationType === "attention");

  const byQuestion = new Map<string, AttentionObservation[]>();
  for (const observation of observations) {
    if (!observation.questionId) continue;
    const records = byQuestion.get(observation.questionId) ?? [];
    records.push(observation);
    byQuestion.set(observation.questionId, records);
  }

  return new Map(
    questionIds.map((questionId) => {
      const records = byQuestion.get(questionId) ?? [];
      const averageFacingScore = averageFacingScoreFromObservations(records);
      const score =
        typeof averageFacingScore === "number"
          ? Math.round(averageFacingScore * 100)
          : averageObservationScores(records);
      const quality =
        records.length === 0
          ? "insufficient"
          : records.some((observation) => observation.degraded || observation.dataQuality.status !== "complete")
            ? "partial"
            : "complete";
      return [questionId, { score, sampleCount: records.length, quality }] as const;
    })
  );
}
