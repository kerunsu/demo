import assert from "node:assert/strict";
import test from "node:test";

import {
  countWordsOrCharacters,
  extractDeterministicLanguageFeatures
} from "../dist/services/languageFeatureService.js";

const now = "2026-06-14T01:00:00.000+08:00";

test("deterministic language features extract redacted transcript facts without scoring", () => {
  const observations = extractDeterministicLanguageFeatures({
    observationId: "language-feature",
    sessionId: "session-1",
    questionId: "question-1",
    turnId: "turn-1",
    eventId: "event-transcript-1",
    correlationId: "corr-1",
    windowId: "window-question-1",
    transcriptRedacted: "我选择左边的图片。",
    confidence: 0.92,
    audioDurationMs: 1500,
    promptCount: 1,
    observedAt: now
  });

  const byKind = new Map(observations.map((observation) => [observation.features.kind, observation]));
  assert.equal(byKind.get("speech_presence").features.value, true);
  assert.equal(byKind.get("transcript_length").features.value, 9);
  assert.equal(byKind.get("sentence_count").features.value, 1);
  assert.equal(byKind.get("stt_confidence").features.value, 0.92);
  assert.equal(byKind.get("audio_duration_ms").features.value, 1500);
  assert.equal(byKind.get("prompt_count").features.value, 1);
  assert.equal(observations.every((observation) => observation.dataQuality.status === "complete"), true);

  const serialized = JSON.stringify(observations);
  assert.equal(serialized.includes("finalScore"), false);
  assert.equal(serialized.includes("abilityScore"), false);
  assert.equal(serialized.includes("diagnosis"), false);
});

test("deterministic language features preserve STT failure and low quality as data quality", () => {
  const lowConfidence = extractDeterministicLanguageFeatures({
    observationId: "language-low",
    sessionId: "session-1",
    questionId: "question-1",
    turnId: "turn-low",
    correlationId: "corr-1",
    transcriptRedacted: "我选",
    confidence: 0.31,
    observedAt: now
  });
  assert.equal(
    lowConfidence.find((observation) => observation.features.kind === "stt_confidence").dataQuality.status,
    "low_confidence"
  );

  const emptySpeech = extractDeterministicLanguageFeatures({
    observationId: "language-empty",
    sessionId: "session-1",
    questionId: "question-1",
    turnId: "turn-empty",
    correlationId: "corr-1",
    transcriptRedacted: "",
    confidence: 0,
    observedAt: now
  });
  assert.equal(emptySpeech.find((observation) => observation.features.kind === "speech_presence").features.value, false);
  assert.equal(emptySpeech.find((observation) => observation.features.kind === "empty_response").dataQuality.status, "partial");
});

test("word counter handles space-delimited text and Chinese text deterministically", () => {
  assert.equal(countWordsOrCharacters("I choose left"), 3);
  assert.equal(countWordsOrCharacters("我选择左边"), 5);
  assert.equal(countWordsOrCharacters("   "), 0);
});
