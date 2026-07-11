import assert from "node:assert/strict";
import test from "node:test";

import {
  applyTranscriptNormalization,
  normalizeTranscript,
  resetTranscriptNormalizationForTests
} from "../dist/services/transcriptService.js";

test("transcript normalization redacts basic PII and marks low confidence", () => {
  resetTranscriptNormalizationForTests();
  const result = normalizeTranscript({
    sessionId: "session-1",
    turnId: "turn-1",
    audioSegmentId: "audio-1",
    transcript: "我的电话是13812345678 我在阳光小学",
    confidence: 0.42,
    language: "zh-CN",
    startedAtMs: 0,
    endedAtMs: 1200
  });

  assert.equal(result.empty, false);
  assert.equal(result.transcript.normalized.lowConfidence, true);
  assert.deepEqual(result.transcript.normalized.piiTypes, ["phone", "school"]);
  assert.equal(result.transcript.transcriptRedacted.includes("13812345678"), false);
  assert.equal(result.transcript.transcriptRedacted.includes("阳光小学"), false);
});

test("transcript normalization marks duplicate final text by session", () => {
  resetTranscriptNormalizationForTests();
  const first = normalizeTranscript({
    sessionId: "session-dup",
    turnId: "turn-first",
    audioSegmentId: "audio-1",
    transcript: "我选择左边的图片",
    confidence: 0.95,
    language: "zh-CN",
    startedAtMs: 0,
    endedAtMs: 1000
  });
  const second = normalizeTranscript({
    sessionId: "session-dup",
    turnId: "turn-second",
    audioSegmentId: "audio-2",
    transcript: " 我选择左边的图片 ",
    confidence: 0.95,
    language: "zh-CN",
    startedAtMs: 0,
    endedAtMs: 1000
  });

  assert.equal(first.duplicate, false);
  assert.equal(second.duplicate, true);
  assert.equal(second.transcript.normalized.duplicateOfTurnId, "turn-first");
});

test("empty final transcript becomes an EMPTY_RESULT provider response", () => {
  resetTranscriptNormalizationForTests();
  const result = applyTranscriptNormalization("session-empty", {
    ok: true,
    metadata: {
      providerKind: "stt",
      providerName: "mock-stt",
      providerId: "mock-stt",
      providerType: "mock",
      mode: "mock",
      version: "test"
    },
    latencyMs: 1,
    data: {
      turnId: "turn-empty",
      audioSegmentId: "audio-empty",
      transcriptRedacted: "   ",
      confidence: 0,
      language: "zh-CN",
      startedAtMs: 0,
      endedAtMs: 0,
      isFinal: true
    }
  });

  assert.equal(result.ok, false);
  assert.equal(result.error.code, "EMPTY_RESULT");
  assert.equal(typeof result.fallbackText, "string");
});
