import assert from "node:assert/strict";
import test from "node:test";

import {
  EMOTION_ALGORITHM_V1,
  normalizeEmotionCategoryScores,
  scoreEmotionFromBlendshapes,
  toEmotionDescriptorFeatures
} from "../dist/emotionScoring.js";

test("scoreEmotionFromBlendshapes maps smile blendshapes toward positive", () => {
  const result = scoreEmotionFromBlendshapes(
    {
      mouthSmileLeft: 0.8,
      mouthSmileRight: 0.75,
      cheekSquintLeft: 0.4,
      cheekSquintRight: 0.35
    },
    true
  );
  const normalized = normalizeEmotionCategoryScores(result);
  assert.ok(normalized.positive > normalized.frustrated);
  assert.ok(normalized.positive > 0.3);
});

test("scoreEmotionFromBlendshapes maps frown and brow-down toward frustrated", () => {
  const result = scoreEmotionFromBlendshapes(
    {
      mouthFrownLeft: 0.7,
      mouthFrownRight: 0.65,
      browDownLeft: 0.6,
      browDownRight: 0.55,
      mouthPressLeft: 0.4,
      mouthPressRight: 0.35
    },
    true
  );
  const normalized = normalizeEmotionCategoryScores(result);
  assert.ok(normalized.frustrated > normalized.positive);
});

test("normalizeEmotionCategoryScores returns zero totals for missing face", () => {
  const normalized = normalizeEmotionCategoryScores(scoreEmotionFromBlendshapes({}, false));
  assert.equal(normalized.positive + normalized.focused + normalized.frustrated, 0);
});

test("toEmotionDescriptorFeatures tags browser emotion algorithm version", () => {
  const descriptor = toEmotionDescriptorFeatures(
    {
      mouthSmileLeft: 0.5,
      mouthSmileRight: 0.45,
      eyeSquintLeft: 0.3,
      eyeSquintRight: 0.28
    },
    true
  );
  assert.equal(descriptor.algorithmVersion, EMOTION_ALGORITHM_V1);
  assert.equal(descriptor.provider, "browser-mediapipe-landmarker");
  assert.equal(descriptor.facePresent, true);
});
