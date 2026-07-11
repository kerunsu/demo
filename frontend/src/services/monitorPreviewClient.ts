import type {
  MonitorPreviewLatestResponse,
  MonitorPreviewUploadPayload
} from "child-education-training-demo/shared/monitor-preview";
import { MONITOR_PREVIEW_SCHEMA_VERSION } from "child-education-training-demo/shared/monitor-preview";
import type { BrowserMonitorPreviewFrame } from "../features/camera/browserCameraCapture";
import { apiRequest } from "./api";

export interface MonitorPreviewConfig {
  enabled: boolean;
  maxFps: number;
  width: number;
  height: number;
  ttlMs: number;
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result ?? "");
      const base64 = result.includes(",") ? result.split(",")[1] : result;
      resolve(base64);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

export async function uploadMonitorPreviewFrame(input: BrowserMonitorPreviewFrame) {
  const imageBase64 = await blobToBase64(input.blob);
  const payload: MonitorPreviewUploadPayload = {
    schemaVersion: MONITOR_PREVIEW_SCHEMA_VERSION,
    sessionId: input.meta.sessionId,
    mimeType: input.mimeType,
    imageBase64,
    meta: input.meta
  };
  return apiRequest<{ sessionId: string; frameId: string; accepted: boolean; expiresAt: string }>(
    `/monitor/session/${input.meta.sessionId}/preview-frame`,
    {
      method: "POST",
      body: JSON.stringify(payload)
    }
  );
}

export function getMonitorPreviewConfig() {
  return apiRequest<MonitorPreviewConfig>("/monitor/preview/config");
}

export function getLatestMonitorPreview(sessionId: string) {
  return apiRequest<MonitorPreviewLatestResponse>(`/monitor/session/${sessionId}/preview/latest`);
}
