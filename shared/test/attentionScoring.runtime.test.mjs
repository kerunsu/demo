import assert from "node:assert/strict";
import test from "node:test";

import {
  ATTENTION_ALGORITHM_V2,
  scoreAttentionFromFaceGeometry,
  scoreAttentionFromLegacyFeatures
} from "../dist/attentionScoring.js";

test("scoreAttentionFromFaceGeometry marks centered frontal face as screen-oriented", () => {
  const result = scoreAttentionFromFaceGeometry({
    frameWidth: 160,
    frameHeight: 120,
    faceCount: 1,
    primaryFace: { x: 52, y: 28, width: 56, height: 64 },
    imageQuality: "good"
  });
  assert.equal(result.algorithmVersion, ATTENTION_ALGORITHM_V2);
  assert.equal(result.facePresent, true);
  assert.equal(result.roughlyFacingScreen, true);
  assert.equal(result.headOrientation, "screen");
  assert.ok((result.facingScore ?? 0) >= 0.55);
});

test("scoreAttentionFromFaceGeometry marks off-center face as away", () => {
  const result = scoreAttentionFromFaceGeometry({
    frameWidth: 160,
    frameHeight: 120,
    faceCount: 1,
    primaryFace: { x: 8, y: 40, width: 36, height: 44 },
    imageQuality: "good"
  });
  assert.equal(result.roughlyFacingScreen, false);
  assert.notEqual(result.headOrientation, "screen");
});

test("scoreAttentionFromFaceGeometry penalizes multiple faces", () => {
  const result = scoreAttentionFromFaceGeometry({
    frameWidth: 160,
    frameHeight: 120,
    faceCount: 2,
    primaryFace: { x: 52, y: 28, width: 56, height: 64 },
    imageQuality: "good"
  });
  assert.equal(result.faceCount, 2);
  assert.equal(result.roughlyFacingScreen, false);
});

test("scoreAttentionFromLegacyFeatures upgrades v1 boolean features", () => {
  const result = scoreAttentionFromLegacyFeatures({
    frameWidth: 160,
    frameHeight: 120,
    facePresent: true,
    faceCount: 1,
    headOrientation: "screen",
    roughlyFacingScreen: true,
    imageQuality: "good",
    confidence: 0.8
  });
  assert.equal(result.algorithmVersion, ATTENTION_ALGORITHM_V2);
  assert.equal(result.roughlyFacingScreen, true);
  assert.ok((result.facingScore ?? 0) > 0);
});
