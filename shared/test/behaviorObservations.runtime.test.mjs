import assert from "node:assert/strict";
import test from "node:test";

import {
  BEHAVIOR_SCHEMA_VERSION,
  DATA_QUALITY_STATUSES,
  DEFAULT_BEHAVIOR_ALGORITHM_VERSION,
  createEvidenceReference
} from "../dist/behaviorObservations.js";
import { MockAttentionObservationProvider, MockLanguageObservationProvider } from "../dist/providers.js";

const now = "2026-06-14T01:00:00.000+08:00";

test("M5 behavior fixture constructs attention and language observations without raw media", async () => {
  const attention = await new MockAttentionObservationProvider().observe({
    observationId: "attention-obs-1",
    sessionId: "session-1",
    questionId: "question-1",
    eventId: "event-question-presented-1",
    correlationId: "corr-question-1",
    windowId: "window-question-1",
    observedAt: now
  });
  assert.equal(attention.ok, true);
  assert.equal(attention.data.observationType, "attention");
  assert.equal(attention.data.algorithm.schemaVersion, BEHAVIOR_SCHEMA_VERSION);
  assert.equal(attention.data.features.roughlyFacingScreen, true);
  assert.equal(attention.data.dataQuality.status, "complete");

  const serializedAttention = JSON.stringify(attention.data);
  assert.equal(serializedAttention.includes("rawFrame"), false);
  assert.equal(serializedAttention.includes("base64"), false);
  assert.equal(serializedAttention.includes("video"), false);

  const language = await new MockLanguageObservationProvider().observe({
    observationId: "language-obs-1",
    sessionId: "session-1",
    questionId: "question-1",
    turnId: "turn-1",
    eventId: "event-transcript-ready-1",
    correlationId: "corr-question-1",
    windowId: "window-question-1",
    transcriptRedacted: "我选择左边的图片",
    confidence: 0.93,
    observedAt: now
  });
  assert.equal(language.ok, true);
  assert.equal(language.data.observationType, "language");
  assert.equal(language.data.features.kind, "transcript_length");
  assert.equal(language.data.features.transcriptLength, 8);
  assert.equal(language.data.dataQuality.status, "complete");

  const serializedLanguage = JSON.stringify(language.data);
  assert.equal(serializedLanguage.includes("rawAudio"), false);
  assert.equal(serializedLanguage.includes("transcriptRaw"), false);
});

test("M5 data quality expresses missing camera, low confidence transcript, and empty speech", async () => {
  const missingCamera = await new MockAttentionObservationProvider("empty").observe({
    observationId: "attention-missing-camera",
    sessionId: "session-1",
    questionId: "question-1",
    correlationId: "corr-question-1",
    observedAt: now
  });
  assert.equal(missingCamera.ok, true);
  assert.equal(missingCamera.data.dataQuality.status, "missing_device");
  assert.equal(missingCamera.data.features.cameraAvailable, false);
  assert.equal(missingCamera.data.degraded, true);

  const lowConfidence = await new MockLanguageObservationProvider().observe({
    observationId: "language-low-confidence",
    sessionId: "session-1",
    questionId: "question-1",
    turnId: "turn-low-confidence",
    transcriptRedacted: "我选择",
    confidence: 0.35,
    observedAt: now
  });
  assert.equal(lowConfidence.ok, true);
  assert.equal(lowConfidence.data.dataQuality.status, "low_confidence");
  assert.equal(lowConfidence.data.degraded, true);

  const emptySpeech = await new MockLanguageObservationProvider().observe({
    observationId: "language-empty",
    sessionId: "session-1",
    questionId: "question-1",
    turnId: "turn-empty",
    transcriptRedacted: "",
    confidence: 0,
    observedAt: now
  });
  assert.equal(emptySpeech.ok, true);
  assert.equal(emptySpeech.data.features.kind, "empty_response");
  assert.equal(emptySpeech.data.dataQuality.status, "partial");
});

test("M5 summaries remain inputs for M6 and do not contain scores or diagnosis", () => {
  const evidence = createEvidenceReference({
    type: "observation_window",
    id: "window-question-1",
    sessionId: "session-1",
    questionId: "question-1",
    windowId: "window-question-1",
    createdAt: now
  });

  const questionSummary = {
    summaryId: "question-summary-1",
    sessionId: "session-1",
    questionId: "question-1",
    windowId: "window-question-1",
    correlationId: "corr-question-1",
    attention: {
      observedMs: 3000,
      screenOrientedMs: 2400,
      orientationInterruptedMs: 600,
      unavailableMs: 0,
      quality: { status: "complete" }
    },
    language: {
      responsePresent: true,
      responseLatencyMs: 900,
      audioDurationMs: 1500,
      transcriptLength: 8,
      sentenceCount: 1,
      emptyResponse: false,
      repeatedResponse: false,
      quality: { status: "complete" }
    },
    evidence: [evidence],
    algorithm: DEFAULT_BEHAVIOR_ALGORITHM_VERSION,
    dataQuality: { status: "complete" },
    createdAt: now
  };

  const sessionSummary = {
    summaryId: "session-summary-1",
    sessionId: "session-1",
    courseType: "matching",
    questionSummaryIds: [questionSummary.summaryId],
    attention: {
      totalObservedMs: 3000,
      screenOrientedRatio: 0.8,
      unavailableRatio: 0,
      quality: { status: "complete" }
    },
    language: {
      responseCount: 1,
      emptyResponseCount: 0,
      repeatedResponseCount: 0,
      medianResponseLatencyMs: 900,
      lowConfidenceTranscriptCount: 0,
      quality: { status: "complete" }
    },
    evidence: [evidence],
    algorithm: DEFAULT_BEHAVIOR_ALGORITHM_VERSION,
    dataQuality: { status: "complete" },
    environmentPending: [],
    ownerRequiredBeforeScoring: ["formal_attention_thresholds", "formal_language_scoring_weights"],
    createdAt: now
  };

  const serialized = JSON.stringify({ questionSummary, sessionSummary });
  assert.equal(serialized.includes("diagnosis"), false);
  assert.equal(serialized.includes("percentile"), false);
  assert.equal(serialized.includes("clinical"), false);
  assert.equal(serialized.includes("finalScore"), false);
  assert.ok(DATA_QUALITY_STATUSES.includes(questionSummary.dataQuality.status));
  assert.ok(sessionSummary.ownerRequiredBeforeScoring.length > 0);
});
