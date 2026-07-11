import assert from "node:assert/strict";
import test from "node:test";
import "./testEnv.mjs";

import {
  behaviorObservationRepository,
  receiveCameraFrameDescriptor,
  resetBehaviorFrameIngressForTests
} from "../dist/services/behaviorFrameIngressService.js";
import { LocalAttentionObservationProvider } from "../dist/services/localAttentionObservationProvider.js";
import { LocalEmotionObservationProvider } from "../dist/services/localEmotionObservationProvider.js";
import { MockAttentionObservationProvider } from "../../shared/dist/providers.js";

const now = "2026-06-14T01:10:00.000Z";

function descriptor(sequence) {
  return {
    schemaVersion: "m5-frame-v1",
    sessionId: "session-camera",
    streamId: "camera-stream-1",
    frameId: `camera-stream-1:frame-${sequence}`,
    sequence,
    capturedAt: now,
    correlationId: "corr-camera",
    questionId: "question-1",
    width: 160,
    height: 120,
    downsampled: true,
    frameHash: `hash-${sequence}`,
    byteLength: 2048,
    mimeType: "mock/frame-descriptor",
    rawFramePersisted: false
  };
}

test("camera frame ingress accepts descriptor metadata and stores attention observation without raw frames", async () => {
  resetBehaviorFrameIngressForTests();
  const result = await receiveCameraFrameDescriptor(descriptor(0));

  assert.equal(result.ack.accepted, true);
  assert.equal(result.ack.rawFramePersisted, false);
  assert.equal(result.observation.observationType, "attention");
  assert.equal(result.observation.features.facePresent, true);
  assert.equal(result.observation.dataQuality.status, "complete");

  const saved = behaviorObservationRepository.listObservations("session-camera");
  assert.equal(saved.length, 1);
  assert.equal(JSON.stringify(saved).includes("rawFrame"), false);
  assert.equal(JSON.stringify(saved).includes("base64"), false);
});

test("camera frame ingress reports dropped sequences and rejects raw persistence", async () => {
  resetBehaviorFrameIngressForTests();
  const skipped = await receiveCameraFrameDescriptor(descriptor(2));
  assert.deepEqual(skipped.ack.droppedSequences, [0, 1]);
  assert.equal(skipped.ack.expectedNextSequence, 3);

  await assert.rejects(
    () => receiveCameraFrameDescriptor({ ...descriptor(3), rawFramePersisted: true }),
    /RAW_FRAME_PERSISTENCE_NOT_ALLOWED/
  );
});

test("attention mock scenarios cover no face, multiple faces, looking away, occluded, and camera unavailable", async () => {
  const cases = [
    ["no_face", 0, false, "complete"],
    ["multiple_faces", 2, true, "complete"],
    ["looking_away", 1, false, "complete"],
    ["occluded", 1, true, "low_confidence"],
    ["camera_unavailable", 0, false, "missing_device"]
  ];

  for (const [scenario, faceCount, roughlyFacingScreen, quality] of cases) {
    const result = await receiveCameraFrameDescriptor(
      { ...descriptor(0), frameId: `frame-${scenario}`, sequence: 0 },
      new MockAttentionObservationProvider(scenario)
    );
    assert.equal(result.observation.features.faceCount, faceCount);
    assert.equal(result.observation.features.roughlyFacingScreen ?? false, roughlyFacingScreen);
    assert.equal(result.observation.dataQuality.status, quality);
    resetBehaviorFrameIngressForTests();
  }
});

test("local attention provider consumes browser descriptors and keeps data quality separate from attention", async () => {
  resetBehaviorFrameIngressForTests();
  const localProvider = new LocalAttentionObservationProvider();
  const result = await receiveCameraFrameDescriptor({
    ...descriptor(0),
    visualFeatures: {
      facePresent: true,
      faceCount: 2,
      headOrientation: "away",
      roughlyFacingScreen: false,
      facingScore: 0.32,
      imageQuality: "good",
      provider: "browser-face-detector",
      algorithmVersion: "browser-attention-v2",
      confidence: 0.74
    }
  }, localProvider);

  assert.equal(result.observation.provider, "local-browser-face-attention");
  assert.equal(result.observation.features.facePresent, true);
  assert.equal(result.observation.features.faceCount, 2);
  assert.equal(result.observation.features.headOrientation, "away");
  assert.equal(result.observation.features.roughlyFacingScreen, false);
  assert.equal(result.observation.features.imageQuality, "good");
  assert.equal(result.observation.dataQuality.status, "complete");
  assert.equal(result.observation.confidence, 0.74);

  const unavailable = await receiveCameraFrameDescriptor({
    ...descriptor(1),
    frameId: "camera-unavailable-local",
    sequence: 1,
    mimeType: "mock/frame-descriptor",
    byteLength: 0,
    visualFeatures: {
      facePresent: false,
      faceCount: 0,
      headOrientation: "unknown",
      imageQuality: "unavailable",
      provider: "camera-device",
      algorithmVersion: "camera-device-availability-v1",
      confidence: 0
    }
  }, localProvider);
  assert.equal(unavailable.observation.features.kind, "camera_unavailable");
  assert.equal(unavailable.observation.dataQuality.status, "missing_device");
  assert.equal(unavailable.observation.degraded, true);
});

test("local attention provider scores centered face geometry as screen-oriented", async () => {
  resetBehaviorFrameIngressForTests();
  const localProvider = new LocalAttentionObservationProvider();
  const result = await receiveCameraFrameDescriptor(
    {
      ...descriptor(0),
      visualFeatures: {
        facePresent: true,
        faceCount: 1,
        headOrientation: "screen",
        roughlyFacingScreen: true,
        facingScore: 0.82,
        centerOffsetX: 0.04,
        centerOffsetY: -0.03,
        faceAreaRatio: 0.16,
        imageQuality: "good",
        provider: "browser-mediapipe-face",
        algorithmVersion: "browser-attention-v2",
        confidence: 0.86
      }
    },
    localProvider
  );

  assert.equal(result.observation.algorithm.algorithmVersion, "browser-attention-v2");
  assert.equal(result.observation.features.roughlyFacingScreen, true);
  assert.equal(result.observation.features.facingScore, 0.82);
  assert.equal(result.observation.degraded, false);
});

test("local emotion provider consumes browser blendshape descriptors", async () => {
  resetBehaviorFrameIngressForTests();
  const previous = process.env.EMOTION_PROVIDER;
  process.env.EMOTION_PROVIDER = "local";
  const result = await receiveCameraFrameDescriptor({
    ...descriptor(0),
    visualFeatures: {
      facePresent: true,
      faceCount: 1,
      headOrientation: "screen",
      roughlyFacingScreen: true,
      facingScore: 0.82,
      imageQuality: "good",
      provider: "browser-mediapipe-face",
      algorithmVersion: "browser-attention-v2",
      confidence: 0.86
    },
    emotionFeatures: {
      positiveScore: 0.52,
      focusedScore: 0.33,
      frustratedScore: 0.15,
      facePresent: true,
      provider: "browser-mediapipe-landmarker",
      algorithmVersion: "browser-emotion-v1",
      confidence: 0.8,
      degraded: false
    }
  });

  assert.equal(result.emotionObservation?.observationType, "emotion");
  assert.equal(result.emotionObservation?.features.kind, "frame_emotion_scores");
  assert.equal(result.emotionObservation?.provider, "local-browser-face-emotion");
  assert.equal(result.emotionObservation?.algorithm.algorithmVersion, "browser-emotion-v1");

  const saved = behaviorObservationRepository.listObservations("session-camera");
  assert.equal(saved.filter((item) => item.observationType === "emotion").length, 1);
  process.env.EMOTION_PROVIDER = previous;
});

test("local emotion provider can be invoked directly for absent blendshapes", async () => {
  const provider = new LocalEmotionObservationProvider();
  const result = await provider.observe({
    observationId: "emotion:missing",
    sessionId: "session-camera",
    observedAt: now,
    frameDescriptor: descriptor(0)
  });
  assert.equal(result.ok, true);
  assert.equal(result.data.features.kind, "face_absent");
  assert.equal(result.data.degraded, true);
});
