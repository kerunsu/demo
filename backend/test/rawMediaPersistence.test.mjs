import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import path from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(fileURLToPath(new URL("../..", import.meta.url)));
const mediaRoot = path.join(projectRoot, ".runtime", "media-test");

let previousEnv = { ...process.env };

before(() => {
  process.env.RAW_MEDIA_PERSISTENCE = "enabled";
  process.env.RAW_MEDIA_ROOT = mediaRoot;
  process.env.RAW_MEDIA_REQUIRE_CONSENT = "true";
});

after(async () => {
  process.env = previousEnv;
  const { resetRawMediaPersistenceForTests } = await import("../dist/services/rawMediaPersistenceService.js");
  const { resetVideoIngressForTests } = await import("../dist/services/videoIngressService.js");
  const { resetMediaIngressForTests } = await import("../dist/services/mediaIngressService.js");
  await resetRawMediaPersistenceForTests();
  resetVideoIngressForTests();
  resetMediaIngressForTests();
});

test("raw media persistence saves video segments and audio chunks when enabled with consent", async () => {
  const {
    recordSessionMediaConsent,
    resetRawMediaPersistenceForTests,
    getSessionMediaManifest,
    getSessionMediaSummary
  } = await import("../dist/services/rawMediaPersistenceService.js");
  const { startVideoStream, receiveVideoSegment, finishVideoStream, resetVideoIngressForTests } = await import(
    "../dist/services/videoIngressService.js"
  );
  const { startMediaStream, receiveMediaChunk, finishMediaStream, resetMediaIngressForTests } = await import(
    "../dist/services/mediaIngressService.js"
  );

  await resetRawMediaPersistenceForTests();
  resetVideoIngressForTests();
  resetMediaIngressForTests();

  const sessionId = "sess_rawmedia01";
  await recordSessionMediaConsent(sessionId, {
    recordedAt: new Date().toISOString(),
    consentedBy: "test",
    scope: "raw_audio_video"
  });

  await startVideoStream({
    sessionId,
    streamId: "camera-stream-1",
    correlationId: "corr-video",
    questionId: "q1",
    startedAt: new Date().toISOString(),
    mimeType: "video/webm"
  });
  const videoAck = await receiveVideoSegment(
    {
      sessionId,
      streamId: "camera-stream-1",
      correlationId: "corr-video",
      sequence: 0,
      capturedAt: new Date().toISOString(),
      durationMs: 2000,
      byteLength: 5,
      mimeType: "video/webm"
    },
    Buffer.from([1, 2, 3, 4, 5])
  );
  assert.equal(videoAck.rawVideoPersisted, true);
  await finishVideoStream({
    sessionId,
    streamId: "camera-stream-1",
    correlationId: "corr-video",
    reason: "question_end",
    endedAt: new Date().toISOString()
  });

  await startMediaStream({
    sessionId,
    streamId: "audio-stream-1",
    turnId: "turn-1",
    correlationId: "corr-audio",
    startedAt: new Date().toISOString(),
    format: {
      codec: "webm_opus",
      mimeType: "audio/webm;codecs=opus",
      sampleRateHz: 48000,
      channels: 1,
      chunkDurationMs: 250
    },
    maxTurnDurationMs: 5000
  });
  const audioAck = await receiveMediaChunk(
    {
      sessionId,
      streamId: "audio-stream-1",
      turnId: "turn-1",
      correlationId: "corr-audio",
      sequence: 0,
      capturedAt: new Date().toISOString(),
      durationMs: 250,
      byteLength: 4,
      format: {
        codec: "webm_opus",
        mimeType: "audio/webm;codecs=opus",
        sampleRateHz: 48000,
        channels: 1,
        chunkDurationMs: 250
      }
    },
    Buffer.from([9, 8, 7, 6])
  );
  assert.equal(audioAck.rawAudioPersisted, true);
  const finished = await finishMediaStream({
    sessionId,
    streamId: "audio-stream-1",
    turnId: "turn-1",
    correlationId: "corr-audio",
    reason: "speech_end",
    endedAt: new Date().toISOString()
  });
  assert.equal(finished.rawAudioPersisted, true);

  const manifest = await getSessionMediaManifest(sessionId);
  assert.ok(manifest);
  assert.equal(manifest.consent?.consentedBy, "test");
  assert.equal(manifest.video["camera-stream-1"]?.segments.length, 1);
  assert.ok(manifest.video["camera-stream-1"]?.mergedRelativePath);
  assert.equal(manifest.audio["turn-1"]?.chunks.length, 1);
  assert.ok(manifest.audio["turn-1"]?.mergedRelativePath);

  const summary = await getSessionMediaSummary(sessionId);
  assert.equal(summary?.videoStreamCount, 1);
  assert.equal(summary?.audioTurnCount, 1);
  assert.ok((summary?.totalPersistedBytes ?? 0) >= 9);

  const videoSegmentPath = path.join(mediaRoot, sessionId, manifest.video["camera-stream-1"].segments[0].relativePath);
  const audioChunkPath = path.join(mediaRoot, sessionId, manifest.audio["turn-1"].chunks[0].relativePath);
  await access(videoSegmentPath);
  await access(path.join(mediaRoot, sessionId, manifest.video["camera-stream-1"].mergedRelativePath ?? ""));
  await access(audioChunkPath);
  await access(path.join(mediaRoot, sessionId, manifest.audio["turn-1"].mergedRelativePath ?? ""));

  const manifestOnDisk = JSON.parse(await readFile(path.join(mediaRoot, sessionId, "manifest.json"), "utf8"));
  assert.equal(manifestOnDisk.schemaVersion, "raw-media-manifest-v1");
});

test("raw media persistence stays disabled without enabled config", async () => {
  process.env.RAW_MEDIA_PERSISTENCE = "disabled";
  const { canPersistSessionMedia, resetRawMediaPersistenceForTests } = await import("../dist/services/rawMediaPersistenceService.js");
  await resetRawMediaPersistenceForTests();
  assert.equal(await canPersistSessionMedia("sess_disabled01"), false);
  process.env.RAW_MEDIA_PERSISTENCE = "enabled";
});

test("corrupt manifest with trailing JSON garbage is repaired on read", async () => {
  const { mkdir, writeFile, readFile } = await import("node:fs/promises");
  const {
    getSessionMediaManifest,
    getSessionMediaSummary,
    resetRawMediaPersistenceForTests
  } = await import("../dist/services/rawMediaPersistenceService.js");

  await resetRawMediaPersistenceForTests();

  const sessionId = "sess_corrupt01";
  const sessionDir = path.join(mediaRoot, sessionId);
  await mkdir(sessionDir, { recursive: true });

  const validManifest = {
    schemaVersion: "raw-media-manifest-v1",
    sessionId,
    createdAt: "2026-06-14T00:00:00.000Z",
    updatedAt: "2026-06-14T00:00:00.000Z",
    consent: {
      recordedAt: "2026-06-14T00:00:00.000Z",
      scope: "raw_audio_video",
      consentedBy: "test"
    },
    audio: {},
    video: {}
  };
  const trailingGarbage = `\n  "consent": {\n    "recordedAt": "2026-06-14T00:00:00.000Z",\n    "scope": "raw_audio_video",\n    "consentedBy": "test"\n  }\n}`;
  await writeFile(
    path.join(sessionDir, "manifest.json"),
    `${JSON.stringify(validManifest, null, 2)}${trailingGarbage}`,
    "utf8"
  );

  const manifest = await getSessionMediaManifest(sessionId);
  assert.ok(manifest);
  assert.equal(manifest.sessionId, sessionId);
  assert.equal(manifest.consent?.consentedBy, "test");

  const summary = await getSessionMediaSummary(sessionId);
  assert.equal(summary?.consentRecorded, true);

  const repairedOnDisk = await readFile(path.join(sessionDir, "manifest.json"), "utf8");
  const parsedOnDisk = JSON.parse(repairedOnDisk);
  assert.equal(parsedOnDisk.sessionId, sessionId);
  assert.equal(repairedOnDisk.trim(), `${JSON.stringify(parsedOnDisk, null, 2)}\n`.trim());
});
