import assert from "node:assert/strict";
import test from "node:test";

import { aggregateQuestionBehavior, aggregateSessionBehavior } from "../dist/services/behaviorAggregationService.js";
import {
  createQuestionObservationWindow,
  dedupeObservations
} from "../dist/services/behaviorTimelineService.js";
import {
  getBehaviorMetricsForSession,
  recordBehaviorMetric,
  resetBehaviorObservabilityForTests
} from "../dist/services/behaviorObservabilityService.js";

const startedAt = "2026-06-14T01:20:00.000Z";
const completedAt = "2026-06-14T01:20:05.000Z";

function attentionObservation(id, overrides = {}) {
  return {
    observationId: id,
    observationType: "attention",
    sessionId: "session-agg",
    questionId: "question-1",
    correlationId: "corr-agg",
    startedAt,
    endedAt: completedAt,
    observedAt: "2026-06-14T01:20:01.000Z",
    source: "mock_provider",
    provider: "mock-attention",
    algorithm: {
      schemaVersion: "m5-behavior-v1",
      algorithmVersion: "mock-attention-v1"
    },
    features: {
      kind: "screen_orientation",
      facePresent: true,
      faceCount: 1,
      roughlyFacingScreen: true,
      durationMs: 1000,
      imageQuality: "good",
      cameraAvailable: true
    },
    confidence: 0.9,
    dataQuality: { status: "complete", providerStatus: "ok" },
    degraded: false,
    evidence: [],
    createdAt: startedAt,
    ...overrides
  };
}

function languageObservation(id, kind, value, overrides = {}) {
  return {
    observationId: id,
    observationType: "language",
    sessionId: "session-agg",
    questionId: "question-1",
    turnId: "turn-1",
    correlationId: "corr-agg",
    startedAt,
    endedAt: completedAt,
    observedAt: "2026-06-14T01:20:02.000Z",
    source: "speech_pipeline",
    provider: "deterministic-language-feature-service",
    algorithm: {
      schemaVersion: "m5-behavior-v1",
      algorithmVersion: "deterministic-language-features-v1"
    },
    features: { kind, value },
    confidence: 0.9,
    dataQuality: { status: "complete", providerStatus: "ok" },
    degraded: false,
    evidence: [],
    createdAt: startedAt,
    ...overrides
  };
}

test("question timeline deduplicates repeated observations and aligns a question window", () => {
  const observations = [
    attentionObservation("attention-1"),
    attentionObservation("attention-1"),
    languageObservation("language-present", "speech_presence", true)
  ];
  assert.equal(dedupeObservations(observations).length, 2);

  const window = createQuestionObservationWindow({
    sessionId: "session-agg",
    questionId: "question-1",
    correlationId: "corr-agg",
    questionPresentedEventId: "event-question-1",
    startedAt,
    completedAt,
    observations
  });

  assert.equal(window.windowType, "question");
  assert.deepEqual(window.observationIds, ["attention-1", "language-present"]);
  assert.equal(window.dataQuality.status, "complete");
});

test("question and session aggregation keep quality separate from child behavior", () => {
  const missingCamera = attentionObservation("attention-missing", {
    features: {
      kind: "camera_unavailable",
      facePresent: false,
      faceCount: 0,
      durationMs: 1000,
      imageQuality: "unavailable",
      cameraAvailable: false
    },
    confidence: 0,
    dataQuality: { status: "missing_device", providerStatus: "not_available" },
    degraded: true
  });
  const observations = [
    attentionObservation("attention-on-task"),
    missingCamera,
    languageObservation("language-present", "speech_presence", true),
    languageObservation("language-length", "transcript_length", 8),
    languageObservation("language-empty", "empty_response", false),
    languageObservation("language-repeated", "repeated_response", false)
  ];
  const window = createQuestionObservationWindow({
    sessionId: "session-agg",
    questionId: "question-1",
    correlationId: "corr-agg",
    questionPresentedEventId: "event-question-1",
    startedAt,
    completedAt,
    observations
  });
  const summary = aggregateQuestionBehavior({
    sessionId: "session-agg",
    questionId: "question-1",
    correlationId: "corr-agg",
    window,
    observations
  });

  assert.equal(summary.attention.observedMs, 2000);
  assert.equal(summary.attention.screenOrientedMs, 1000);
  assert.equal(summary.attention.unavailableMs, 1000);
  assert.equal(summary.attention.averageFacingScore, undefined);
  assert.equal(summary.attention.quality.status, "partial");
  assert.equal(summary.language.responsePresent, true);
  assert.equal(summary.language.transcriptLength, 8);
  assert.equal(JSON.stringify(summary).includes("diagnosis"), false);

  const sessionSummary = aggregateSessionBehavior({
    sessionId: "session-agg",
    courseType: "matching",
    questionSummaries: [summary]
  });
  assert.equal(sessionSummary.attention.screenOrientedRatio, 0.5);
  assert.equal(sessionSummary.attention.unavailableRatio, 0.5);
  assert.equal(sessionSummary.ownerRequiredBeforeScoring.includes("formal_attention_thresholds"), true);
  assert.equal(JSON.stringify(sessionSummary).includes("finalScore"), false);
  assert.equal(JSON.stringify(sessionSummary).includes("diagnosis"), false);
});

test("question aggregation averages browser-attention facingScore per question", () => {
  const observations = [
    attentionObservation("attention-a", {
      features: {
        kind: "screen_orientation",
        facePresent: true,
        faceCount: 1,
        roughlyFacingScreen: true,
        facingScore: 0.8,
        durationMs: 1000,
        imageQuality: "good",
        cameraAvailable: true
      }
    }),
    attentionObservation("attention-b", {
      observedAt: "2026-06-14T01:20:02.000Z",
      features: {
        kind: "screen_orientation",
        facePresent: true,
        faceCount: 1,
        roughlyFacingScreen: true,
        facingScore: 0.6,
        durationMs: 1000,
        imageQuality: "good",
        cameraAvailable: true
      }
    })
  ];
  const window = createQuestionObservationWindow({
    sessionId: "session-agg",
    questionId: "question-1",
    correlationId: "corr-agg",
    questionPresentedEventId: "event-question-1",
    startedAt,
    completedAt,
    observations
  });
  const summary = aggregateQuestionBehavior({
    sessionId: "session-agg",
    questionId: "question-1",
    correlationId: "corr-agg",
    window,
    observations
  });
  assert.equal(summary.attention.averageFacingScore, 0.7);
});

test("behavior observability deduplicates and never stores raw media or sensitive text", () => {
  resetBehaviorObservabilityForTests();
  const input = {
    sessionId: "session-agg",
    correlationId: "corr-agg",
    stage: "question_summary_ready",
    observationCount: 3,
    algorithmVersion: "question-behavior-aggregation-v1"
  };
  const first = recordBehaviorMetric(input);
  const duplicate = recordBehaviorMetric(input);
  assert.ok(first);
  assert.equal(duplicate, null);
  const metrics = getBehaviorMetricsForSession("session-agg");
  assert.equal(metrics.length, 1);
  assert.equal(metrics[0].rawFramePersisted, false);
  assert.equal(metrics[0].rawAudioPersisted, false);
  assert.equal(metrics[0].sensitiveTextLogged, false);

  for (let index = 0; index < 1005; index += 1) {
    recordBehaviorMetric({
      sessionId: "session-many",
      correlationId: `corr-${index}`,
      stage: "camera_frame_received"
    });
  }
  assert.equal(getBehaviorMetricsForSession("session-many").length, 1000);
});
