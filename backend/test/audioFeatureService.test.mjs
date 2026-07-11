import assert from "node:assert/strict";
import test from "node:test";
import "./testEnv.mjs";

import { receiveBrowserAudioFeatures } from "../dist/services/audioFeatureService.js";
import { behaviorObservationRepository } from "../dist/services/behaviorFrameIngressService.js";
import { resetBehaviorFrameIngressForTests } from "../dist/services/behaviorFrameIngressService.js";

test("audio feature service persists descriptor-only language observations", () => {
  resetBehaviorFrameIngressForTests();
  const result = receiveBrowserAudioFeatures({
    descriptor: {
      schemaVersion: "m5-audio-features-v1",
      sessionId: "sess_audio",
      turnId: "turn_audio_1",
      correlationId: "corr_audio_1",
      observedAt: "2026-06-15T01:00:00.000Z",
      audioDurationMs: 1800,
      provider: "browser-web-audio",
      features: {
        loudnessRms: 0.18,
        loudnessDb: -14.9,
        speechRatio: 0.82,
        clarityProxy: 0.76,
        sampleCount: 24,
        algorithmVersion: "browser-audio-features-v1",
        degraded: false
      }
    }
  });

  assert.equal(result.accepted, true);
  assert.equal(result.observationCount, 4);
  const observations = behaviorObservationRepository
    .listObservations("sess_audio")
    .filter((item) => item.observationType === "language");
  assert.equal(observations.length, 4);
  assert.ok(observations.some((item) => item.features.kind === "audio_loudness_rms"));
  assert.ok(observations.every((item) => item.provider === "browser-web-audio"));
  const serialized = JSON.stringify(observations);
  assert.equal(serialized.includes("blob"), false);
  assert.equal(serialized.includes("base64"), false);
});
