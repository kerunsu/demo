import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import "./testEnv.mjs";

import {
  MockChildSafetyProvider,
  MockSttProvider,
  MockTtsProvider
} from "child-education-training-demo/shared/providers";
import {
  finishMediaStream,
  receiveMediaChunk,
  resetMediaIngressForTests,
  startMediaStream
} from "../dist/services/mediaIngressService.js";
import { transcribeMediaStream } from "../dist/services/speechSttService.js";
import { synthesizeSpeech } from "../dist/services/speechTtsService.js";
import { resetTranscriptNormalizationForTests } from "../dist/services/transcriptService.js";
import {
  cancelVoiceTurn,
  completeVoiceTurn,
  markRobotSpeaking,
  resetVoiceTurnsForTests,
  retryVoiceTurn,
  startListeningTurn,
  stopListeningForTranscription
} from "../dist/services/voiceTurnService.js";
import {
  getVoiceDegradationPlan,
  mapProviderErrorToVoiceDegradation
} from "../dist/services/voiceDegradationService.js";
import {
  getVoiceMetricsForSession,
  recordVoiceTurnTotal,
  resetVoiceObservabilityForTests
} from "../dist/services/voiceObservabilityService.js";

const projectRoot = path.resolve(fileURLToPath(new URL("../..", import.meta.url)));
const manifestPath = path.join(projectRoot, "tools", "voice-fixtures", "voice-fixture-manifest.json");

async function loadManifest() {
  return JSON.parse(await readFile(manifestPath, "utf8"));
}

test("M4-013 fixture manifest covers non-child voice, silence, noise, network, playback, and safety cases", async () => {
  const manifest = await loadManifest();
  assert.equal(manifest.schemaVersion, "m4-013-fixture-v1");
  assert.equal(manifest.dataPolicy.realChildVoiceAllowed, false);
  assert.equal(manifest.dataPolicy.cloudCallsAllowedByDefault, false);
  assert.equal(manifest.dataPolicy.committedAudioFilesAllowed, false);

  const ids = new Set(manifest.fixtures.map((fixture) => fixture.id));
  for (const id of [
    "synthetic-short-zh",
    "synthetic-long-zh",
    "synthetic-silence",
    "synthetic-noise",
    "synthetic-no-speech-timeout",
    "mock-duplicate-transcript",
    "mock-safety-reject",
    "mock-tts-playback-failure",
    "mock-websocket-disconnect"
  ]) {
    assert.equal(ids.has(id), true, `missing fixture ${id}`);
  }
});

test("M4-013 mock providers cover STT, Safety, and TTS success, failure, timeout, and degradation paths", async () => {
  const success = await new MockSttProvider("success").transcribe({
    turnId: "turn-fixture-stt",
    audioSegmentId: "audio-short",
    audioRef: "fixture:synthetic-short-zh",
    languageHint: "zh-CN"
  });
  assert.equal(success.ok, true);
  assert.equal(success.metadata.dataSafety.externalNetworkCalled, false);

  const empty = await new MockSttProvider("empty").transcribe({
    turnId: "turn-fixture-empty",
    audioSegmentId: "audio-silence",
    audioRef: "fixture:synthetic-silence"
  });
  assert.equal(empty.ok, false);
  assert.equal(mapProviderErrorToVoiceDegradation(empty.error.code).reason, "STT_EMPTY_RESULT");

  const timeout = await new MockSttProvider("timeout").transcribe({
    turnId: "turn-fixture-timeout",
    audioSegmentId: "audio-timeout",
    audioRef: "fixture:synthetic-no-speech-timeout"
  });
  assert.equal(timeout.ok, false);
  assert.equal(timeout.error.code, "TIMEOUT");

  const safetyReject = await new MockChildSafetyProvider("unsafe").review({
    requestId: "safety-fixture",
    target: "output",
    textRedacted: "unsafe fixture text",
    policyVersion: "m4-rule-safety-v1"
  });
  assert.equal(safetyReject.ok, true);
  assert.equal(safetyReject.data.action, "fallback");

  const ttsSuccess = await new MockTtsProvider("success").synthesize({
    turnId: "turn-fixture-tts",
    text: safetyReject.data.fallbackText,
    safety: safetyReject.data,
    audioFormat: "wav"
  });
  assert.equal(ttsSuccess.ok, true);
  assert.equal(ttsSuccess.metadata.dataSafety.externalNetworkCalled, false);

  const ttsFailure = await new MockTtsProvider("failure").synthesize({
    turnId: "turn-fixture-tts-fail",
    text: safetyReject.data.fallbackText,
    safety: safetyReject.data,
    audioFormat: "wav"
  });
  assert.equal(ttsFailure.ok, false);
  assert.equal(mapProviderErrorToVoiceDegradation(ttsFailure.error.code).reason, "STT_PROVIDER_UNAVAILABLE");
});

test("M4-013 voice fixture chain runs without cloud, raw audio persistence, duplicate metrics, or stuck turns", async () => {
  resetMediaIngressForTests();
  resetTranscriptNormalizationForTests();
  resetVoiceObservabilityForTests();
  resetVoiceTurnsForTests();

  const sessionId = "sess_fixture_chain";
  const streamId = "stream_fixture_chain";
  const turnId = "turn_fixture_chain";
  const correlationId = "corr_fixture_chain";
  const format = {
    codec: "webm_opus",
    mimeType: "audio/webm;codecs=opus",
    sampleRateHz: 48000,
    channels: 1,
    chunkDurationMs: 250
  };

  const listening = startListeningTurn({ sessionId, turnId, timeoutMs: 5000, maxRetries: 1 });
  assert.equal(listening.state, "LISTENING");

  const started = await startMediaStream({
    sessionId,
    streamId,
    turnId,
    correlationId,
    startedAt: "2026-06-13T09:00:00.000Z",
    format,
    maxTurnDurationMs: 5000
  });
  assert.equal(started.rawAudioPersisted, false);

  const ack = await receiveMediaChunk(
    {
      sessionId,
      streamId,
      turnId,
      correlationId,
      sequence: 0,
      capturedAt: "2026-06-13T09:00:00.250Z",
      durationMs: 250,
      byteLength: 4,
      format
    },
    Buffer.from([1, 2, 3, 4])
  );
  assert.equal(ack.accepted, true);
  assert.equal(ack.rawAudioPersisted, false);

  const finished = await finishMediaStream({
    sessionId,
    streamId,
    turnId,
    correlationId,
    reason: "speech_end",
    endedAt: "2026-06-13T09:00:00.500Z"
  });
  assert.equal(finished.status, "finished");

  const transcribing = stopListeningForTranscription(sessionId);
  assert.equal(transcribing.state, "TRANSCRIBING");

  const stt = await transcribeMediaStream({ sessionId, streamId, turnId, correlationId, languageHint: "zh-CN" });
  assert.equal(stt.ok, true);
  assert.equal(stt.metadata.dataSafety.externalNetworkCalled, false);
  assert.equal(stt.metadata.dataSafety.rawAudioPersisted, false);

  const tts = await synthesizeSpeech({
    sessionId,
    turnId,
    correlationId,
    text: "我们继续做题吧。"
  });
  assert.equal(tts.ok, true);
  assert.equal(tts.metadata.dataSafety.externalNetworkCalled, false);

  const speaking = markRobotSpeaking({ sessionId, turnId, speaking: true, reason: "tts_started" });
  assert.equal(speaking.state, "ROBOT_SPEAKING");
  assert.equal(startListeningTurn({ sessionId, turnId: "blocked-turn" }).lastReason, "ROBOT_SPEAKING_LISTENING_PAUSED");

  const completed = completeVoiceTurn(sessionId, "tts_finished");
  assert.equal(completed.state, "COMPLETED");
  assert.equal(completed.listeningAllowed, true);

  const retry = retryVoiceTurn(sessionId, "empty_transcript");
  assert.equal(retry.state, "IDLE");
  const degradedRetry = retryVoiceTurn(sessionId, "empty_transcript");
  assert.equal(degradedRetry.state, "DEGRADED");

  const cancelled = cancelVoiceTurn(sessionId, "playback_failure");
  assert.equal(cancelled.state, "CANCELLED");
  assert.equal(getVoiceDegradationPlan("ROBOT_AUDIO_PLAYBACK_FAILED").fallbackMode, "display_text_only");
  assert.equal(getVoiceDegradationPlan("WEBSOCKET_DISCONNECTED").fallbackMode, "resume_when_reconnected");

  recordVoiceTurnTotal({
    sessionId,
    turnId,
    correlationId,
    completedAt: "2026-06-13T09:00:01.000Z"
  });
  recordVoiceTurnTotal({
    sessionId,
    turnId,
    correlationId,
    completedAt: "2026-06-13T09:00:02.000Z"
  });

  const metrics = getVoiceMetricsForSession(sessionId);
  assert.equal(metrics.every((metric) => metric.externalNetworkCalled === false), true);
  assert.equal(metrics.every((metric) => metric.rawAudioPersisted === false), true);
  assert.equal(metrics.every((metric) => metric.sensitiveTextLogged === false), true);
  assert.equal(metrics.filter((metric) => metric.stage === "voice_turn_total").length, 1);
  assert.equal(metrics.some((metric) => metric.stage === "stt_complete"), true);
  assert.equal(metrics.some((metric) => metric.stage === "tts_audio_ready"), true);
});
