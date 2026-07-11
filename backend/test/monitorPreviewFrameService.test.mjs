import assert from "node:assert/strict";
import test from "node:test";
import "./testEnv.mjs";

import {
  getLatestMonitorPreview,
  resetMonitorPreviewFramesForTests,
  storeMonitorPreviewFrame
} from "../dist/services/monitorPreviewFrameService.js";

const samplePayload = {
  schemaVersion: "monitor-preview-v1",
  sessionId: "sess_preview",
  mimeType: "image/jpeg",
  imageBase64: Buffer.from("preview-jpeg").toString("base64"),
  meta: {
    schemaVersion: "monitor-preview-v1",
    sessionId: "sess_preview",
    streamId: "camera-stream-1",
    frameId: "camera-stream-1:preview-0",
    sequence: 0,
    capturedAt: new Date().toISOString(),
    width: 320,
    height: 240,
    facePresent: true,
    attentionScore: 72
  }
};

test("monitor preview frame service stores and returns latest frame", () => {
  resetMonitorPreviewFramesForTests();
  const stored = storeMonitorPreviewFrame(samplePayload);
  assert.equal(stored.accepted, true);
  const latest = getLatestMonitorPreview("sess_preview");
  assert.equal(latest.available, true);
  assert.equal(latest.mimeType, "image/jpeg");
  assert.equal(latest.meta?.frameId, "camera-stream-1:preview-0");
});

test("monitor preview frame service expires stale frames by ttl", () => {
  resetMonitorPreviewFramesForTests();
  storeMonitorPreviewFrame({
    ...samplePayload,
    meta: {
      ...samplePayload.meta,
      capturedAt: "2020-01-01T00:00:00.000Z"
    }
  });
  const latest = getLatestMonitorPreview("sess_preview");
  assert.equal(latest.available, false);
  assert.equal(latest.stale, true);
});

test("monitor preview frame service rejects session mismatch", () => {
  resetMonitorPreviewFramesForTests();
  assert.throws(
    () =>
      storeMonitorPreviewFrame({
        ...samplePayload,
        sessionId: "sess_a",
        meta: { ...samplePayload.meta, sessionId: "sess_b" }
      }),
    /MONITOR_PREVIEW_SESSION_MISMATCH/
  );
});
