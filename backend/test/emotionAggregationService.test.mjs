import assert from "node:assert/strict";
import test from "node:test";
import "./testEnv.mjs";

import { aggregateSessionEmotion, EMOTION_HEURISTIC_VERSION } from "../dist/services/emotionAggregationService.js";

const assessment = {
  sessionMetrics: {
    firstTryAccuracy: 0.8,
    totalQuestions: 5
  }
};

function emotionObservation(sequence, scores) {
  const observedAt = `2026-06-15T10:00:0${sequence}.000Z`;
  return {
    observationId: `emotion:frame-${sequence}`,
    observationType: "emotion",
    sessionId: "session-emotion",
    questionId: "q1",
    correlationId: "corr-emotion",
    eventId: `frame-${sequence}`,
    startedAt: observedAt,
    endedAt: observedAt,
    observedAt,
    source: "camera",
    provider: "local-browser-face-emotion",
    algorithm: {
      schemaVersion: "m5-behavior-v1",
      algorithmVersion: "browser-emotion-v1"
    },
    features: {
      kind: "frame_emotion_scores",
      positiveScore: scores.positive,
      focusedScore: scores.focused,
      frustratedScore: scores.frustrated,
      facePresent: true,
      durationMs: 1000
    },
    confidence: 0.82,
    dataQuality: { status: "complete", providerStatus: "ok", confidence: 0.82 },
    degraded: false,
    evidence: [],
    createdAt: observedAt
  };
}

test("aggregateSessionEmotion returns DEGRADED when provider is none", () => {
  const previous = process.env.EMOTION_PROVIDER;
  process.env.EMOTION_PROVIDER = "none";
  const result = aggregateSessionEmotion({
    assessment,
    totalWrongAttempts: 1,
    totalQuestions: 5,
    emotionObservations: [emotionObservation(0, { positive: 0.5, focused: 0.3, frustrated: 0.2 })]
  });
  process.env.EMOTION_PROVIDER = previous;
  assert.equal(result.status, "DEGRADED");
  assert.equal(result.reason, "MANUAL_ACCEPTANCE_REQUIRED");
});

test("aggregateSessionEmotion normalizes frame observations for local provider", () => {
  const previous = process.env.EMOTION_PROVIDER;
  process.env.EMOTION_PROVIDER = "local";
  const result = aggregateSessionEmotion({
    assessment,
    totalWrongAttempts: 1,
    totalQuestions: 5,
    emotionObservations: [
      emotionObservation(0, { positive: 0.6, focused: 0.3, frustrated: 0.1 }),
      emotionObservation(1, { positive: 0.4, focused: 0.45, frustrated: 0.15 })
    ]
  });
  process.env.EMOTION_PROVIDER = previous;
  assert.equal(result.status, "AVAILABLE");
  assert.equal(result.provider, "local-browser-face-emotion");
  assert.equal(result.algorithmVersion, "browser-emotion-v1");
  assert.ok(typeof result.positiveRatio === "number");
  assert.ok(Math.abs((result.positiveRatio ?? 0) + (result.focusedRatio ?? 0) + (result.frustratedRatio ?? 0) - 1) < 0.01);
});

test("aggregateSessionEmotion degrades local provider when signals are insufficient", () => {
  const previous = process.env.EMOTION_PROVIDER;
  process.env.EMOTION_PROVIDER = "local";
  const result = aggregateSessionEmotion({
    assessment,
    totalWrongAttempts: 1,
    totalQuestions: 5,
    emotionObservations: [emotionObservation(0, { positive: 0.6, focused: 0.3, frustrated: 0.1 })]
  });
  process.env.EMOTION_PROVIDER = previous;
  assert.equal(result.status, "DEGRADED");
  assert.equal(result.reason, "INSUFFICIENT_SIGNALS");
});

test("aggregateSessionEmotion keeps heuristic path labeled as degraded", () => {
  const previous = process.env.EMOTION_PROVIDER;
  process.env.EMOTION_PROVIDER = "heuristic";
  const result = aggregateSessionEmotion({
    assessment,
    sessionBehaviorSummary: {
      attention: { screenOrientedRatio: 0.7 },
      language: { responseCount: 2, emptyResponseCount: 0, repeatedResponseCount: 0 }
    },
    totalWrongAttempts: 1,
    totalQuestions: 5
  });
  process.env.EMOTION_PROVIDER = previous;
  assert.equal(result.status, "AVAILABLE");
  assert.equal(result.algorithmVersion, EMOTION_HEURISTIC_VERSION);
  assert.equal(result.degraded, true);
});
