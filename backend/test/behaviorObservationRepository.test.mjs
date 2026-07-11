import assert from "node:assert/strict";
import test from "node:test";

import { InMemoryBehaviorObservationRepository } from "../dist/services/behaviorObservationRepository.js";

const now = "2026-06-14T01:00:00.000+08:00";

function makeObservation(index) {
  return {
    observationId: `attention-${index}`,
    observationType: "attention",
    sessionId: "session-behavior",
    questionId: "question-1",
    correlationId: "corr-1",
    startedAt: now,
    endedAt: now,
    observedAt: now,
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
      headOrientation: "screen",
      roughlyFacingScreen: true,
      durationMs: 1000,
      imageQuality: "good",
      cameraAvailable: true
    },
    confidence: 0.9,
    dataQuality: {
      status: "complete",
      providerStatus: "ok",
      confidence: 0.9
    },
    degraded: false,
    evidence: [],
    createdAt: now
  };
}

test("behavior repository deduplicates observations and bounds per-session memory", () => {
  const repository = new InMemoryBehaviorObservationRepository({ maxObservationsPerSession: 2 });

  repository.saveObservation(makeObservation(1));
  repository.saveObservation(makeObservation(2));
  repository.saveObservation(makeObservation(2));
  repository.saveObservation(makeObservation(3));

  const observations = repository.listObservations("session-behavior");
  assert.equal(observations.length, 2);
  assert.deepEqual(
    observations.map((record) => record.observationId),
    ["attention-2", "attention-3"]
  );
  assert.equal(JSON.stringify(observations).includes("rawFrame"), false);
  assert.equal(JSON.stringify(observations).includes("rawAudio"), false);
});

test("behavior repository stores windows and summaries separately from raw media", () => {
  const repository = new InMemoryBehaviorObservationRepository();
  repository.saveWindow({
    windowId: "window-question-1",
    sessionId: "session-behavior",
    questionId: "question-1",
    correlationId: "corr-1",
    windowType: "question",
    startedAt: now,
    endedAt: now,
    inputEventIds: ["event-question-1"],
    observationIds: ["attention-1"],
    algorithm: {
      schemaVersion: "m5-behavior-v1",
      algorithmVersion: "window-baseline-v1"
    },
    dataQuality: { status: "complete" },
    createdAt: now
  });

  repository.saveQuestionSummary({
    summaryId: "question-summary-1",
    sessionId: "session-behavior",
    questionId: "question-1",
    windowId: "window-question-1",
    correlationId: "corr-1",
    evidence: [],
    algorithm: {
      schemaVersion: "m5-behavior-v1",
      algorithmVersion: "question-summary-baseline-v1"
    },
    dataQuality: { status: "complete" },
    createdAt: now
  });

  repository.saveSessionSummary({
    summaryId: "session-summary-1",
    sessionId: "session-behavior",
    questionSummaryIds: ["question-summary-1"],
    evidence: [],
    algorithm: {
      schemaVersion: "m5-behavior-v1",
      algorithmVersion: "session-summary-baseline-v1"
    },
    dataQuality: { status: "complete" },
    environmentPending: [],
    ownerRequiredBeforeScoring: ["formal_scoring_weights"],
    createdAt: now
  });

  assert.equal(repository.listWindows("session-behavior").length, 1);
  assert.equal(repository.listQuestionSummaries("session-behavior").length, 1);
  assert.equal(repository.getSessionSummary("session-behavior").ownerRequiredBeforeScoring.length, 1);
  assert.equal(JSON.stringify(repository.getSessionSummary("session-behavior")).includes("diagnosis"), false);
});
