import assert from "node:assert/strict";
import test from "node:test";
import "./testEnv.mjs";

import { buildPerQuestionAttentionScores } from "../dist/services/attentionScoreUtils.js";
import { behaviorObservationRepository } from "../dist/services/behaviorFrameIngressService.js";

test("buildPerQuestionAttentionScores groups camera observations by questionId", () => {
  behaviorObservationRepository.reset();
  const sessionId = "sess_attention_grouping";

  for (const [questionId, facingScore] of [
    ["matching_q_1", 0.82],
    ["matching_q_2", 0.78],
    ["matching_q_3", 0.8],
    ["matching_q_4", 0.76]
  ]) {
    behaviorObservationRepository.saveObservation({
      observationId: `attention:${questionId}`,
      observationType: "attention",
      sessionId,
      questionId,
      correlationId: `corr:${questionId}`,
      eventId: `frame:${questionId}`,
      observedAt: "2026-06-15T04:32:17.664Z",
      source: "camera",
      provider: "local-browser-face-attention",
      algorithm: {
        schemaVersion: "m5-behavior-v1",
        algorithmVersion: "browser-attention-v2",
        providerVersion: "final-b-local-attention-v2"
      },
      features: {
        kind: "screen_orientation",
        facePresent: true,
        faceCount: 1,
        headOrientation: "screen",
        roughlyFacingScreen: true,
        facingScore,
        durationMs: 1000,
        imageQuality: "good",
        cameraAvailable: true
      },
      confidence: 0.86,
      dataQuality: { status: "complete", providerStatus: "ok", confidence: 0.86 },
      degraded: false,
      evidence: [],
      createdAt: "2026-06-15T04:32:17.664Z"
    });
  }

  const scores = buildPerQuestionAttentionScores(sessionId, [
    "matching_q_1",
    "matching_q_2",
    "matching_q_3",
    "matching_q_4",
    "matching_q_5"
  ]);

  assert.equal(scores.get("matching_q_1")?.score, 82);
  assert.equal(scores.get("matching_q_2")?.score, 78);
  assert.equal(scores.get("matching_q_3")?.score, 80);
  assert.equal(scores.get("matching_q_4")?.score, 76);
  assert.equal(scores.get("matching_q_5")?.score, undefined);
  assert.equal(scores.get("matching_q_5")?.sampleCount, 0);
});
