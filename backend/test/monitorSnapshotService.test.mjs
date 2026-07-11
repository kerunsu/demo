import assert from "node:assert/strict";
import test from "node:test";
import "./testEnv.mjs";

import { createTrainingSession } from "../dist/services/sessionLifecycleService.js";
import { getMonitorSnapshot } from "../dist/services/monitorSnapshotService.js";
import { behaviorObservationRepository } from "../dist/services/behaviorFrameIngressService.js";
import { resetBehaviorFrameIngressForTests } from "../dist/services/behaviorFrameIngressService.js";

test("monitor snapshot exposes course stats, attention features, and voice pipeline", async () => {
  resetBehaviorFrameIngressForTests();
  const session = createTrainingSession({
    childName: "测试学员",
    courseType: "matching",
    questions: [
      {
        id: "q1",
        prompt: "找出打招呼的人",
        target: "wave",
        targetImageUrl: "/matching/wave.png",
        options: [
          { id: "a", label: "A", imageUrl: "/matching/a.png" },
          { id: "b", label: "B", imageUrl: "/matching/b.png" }
        ]
      }
    ]
  });
  session.questionStats[0].attempts = 1;
  session.questionStats[0].correct = true;
  session.questionStats[0].responseTimeMs = 1800;

  behaviorObservationRepository.saveObservation({
    observationId: "attention:test",
    observationType: "attention",
    sessionId: session.sessionId,
    questionId: "q1",
    correlationId: "corr-1",
    eventId: "frame-1",
    observedAt: new Date().toISOString(),
    source: "camera",
    provider: "mock-attention",
    algorithm: {
      schemaVersion: "m5-behavior-v1",
      algorithmVersion: "mock-v1",
      providerVersion: "mock-v1"
    },
    features: {
      kind: "screen_orientation",
      facePresent: true,
      faceCount: 1,
      headOrientation: "screen",
      roughlyFacingScreen: true,
      facingScore: 0.82,
      durationMs: 1000,
      imageQuality: "good"
    },
    dataQuality: { status: "complete", observedMs: 1000, missingMs: 0 },
    confidence: 0.91,
    degraded: false
  });

  for (const [kind, value] of [
    ["audio_loudness_rms", 0.21],
    ["audio_loudness_db", -13.5],
    ["audio_speech_ratio", 0.78],
    ["audio_clarity_proxy", 0.74]
  ]) {
    behaviorObservationRepository.saveObservation({
      observationId: `language-audio:${kind}`,
      observationType: "language",
      sessionId: session.sessionId,
      questionId: "q1",
      turnId: "turn-1",
      correlationId: "corr-1",
      observedAt: new Date().toISOString(),
      source: "microphone",
      provider: "browser-web-audio",
      algorithm: {
        schemaVersion: "m5-behavior-v1",
        algorithmVersion: "browser-audio-features-v1"
      },
      features: { kind, value },
      dataQuality: { status: "complete" },
      confidence: 0.9,
      degraded: false,
      evidence: [],
      createdAt: new Date().toISOString()
    });
  }

  const snapshot = await getMonitorSnapshot(session.sessionId);

  assert.equal(snapshot.session.childAlias, "测试学员");
  assert.equal(snapshot.course.currentQuestionPrompt, "找出打招呼的人");
  assert.equal(snapshot.course.questionStats.length, 1);
  assert.equal(snapshot.course.questionStats[0].correct, true);
  assert.equal(snapshot.attention.features?.facePresent, true);
  assert.equal(snapshot.attention.confidence, 0.91);
  assert.equal(snapshot.attention.currentScore, 82);
  assert.equal(snapshot.attention.attentionSamples.length, 1);
  assert.equal(snapshot.attention.attentionSamples[0].score, 82);
  assert.ok(Array.isArray(snapshot.voice.currentPipeline));
  assert.ok(snapshot.voice.currentPipeline.length >= 5);
  assert.equal(snapshot.voice.audioFeatures?.loudnessRms, 0.21);
  assert.equal(snapshot.voice.audioFeatures?.clarityProxy, 0.74);
  assert.equal(snapshot.health.backend, "ok");
  assert.notEqual(snapshot.health.pythonVoiceService, "MANUAL_ACCEPTANCE_REQUIRED");
  assert.equal(snapshot.media.rawMediaPersistence, "disabled");
});
