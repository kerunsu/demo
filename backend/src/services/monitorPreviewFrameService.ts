import type {
  MonitorPreviewFrameMeta,
  MonitorPreviewLatestResponse,
  MonitorPreviewUploadPayload
} from "child-education-training-demo/shared/monitor-preview";
import { runtimeConfig } from "../config/runtime.js";

type StoredPreviewFrame = {
  mimeType: "image/jpeg" | "image/webp";
  imageBase64: string;
  meta: MonitorPreviewFrameMeta;
  capturedAt: string;
  expiresAt: number;
};

const frames = new Map<string, StoredPreviewFrame>();

export function isMonitorPreviewEnabled() {
  return runtimeConfig.monitorPreviewEnabled;
}

export function storeMonitorPreviewFrame(payload: MonitorPreviewUploadPayload) {
  if (!runtimeConfig.monitorPreviewEnabled) {
    throw new Error("MONITOR_PREVIEW_DISABLED");
  }
  if (payload.sessionId !== payload.meta.sessionId) {
    throw new Error("MONITOR_PREVIEW_SESSION_MISMATCH");
  }
  const buffer = Buffer.from(payload.imageBase64, "base64");
  if (buffer.byteLength <= 0 || buffer.byteLength > runtimeConfig.monitorPreviewMaxBytes) {
    throw new Error("MONITOR_PREVIEW_IMAGE_TOO_LARGE");
  }

  const capturedAt = payload.meta.capturedAt;
  const expiresAt = Date.parse(capturedAt) + runtimeConfig.monitorPreviewTtlMs;
  frames.set(payload.sessionId, {
    mimeType: payload.mimeType,
    imageBase64: payload.imageBase64,
    meta: payload.meta,
    capturedAt,
    expiresAt
  });

  return {
    sessionId: payload.sessionId,
    frameId: payload.meta.frameId,
    accepted: true,
    expiresAt: new Date(expiresAt).toISOString()
  };
}

export function getLatestMonitorPreview(sessionId: string): MonitorPreviewLatestResponse {
  if (!runtimeConfig.monitorPreviewEnabled) {
    return { available: false, stale: true };
  }

  const stored = frames.get(sessionId);
  if (!stored) {
    return { available: false };
  }

  const now = Date.now();
  if (stored.expiresAt <= now) {
    frames.delete(sessionId);
    return { available: false, stale: true };
  }

  return {
    available: true,
    mimeType: stored.mimeType,
    imageBase64: stored.imageBase64,
    meta: stored.meta,
    capturedAt: stored.capturedAt,
    expiresAt: new Date(stored.expiresAt).toISOString()
  };
}

export function resetMonitorPreviewFramesForTests() {
  frames.clear();
}
