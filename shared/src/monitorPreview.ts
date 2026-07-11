export const MONITOR_PREVIEW_SCHEMA_VERSION = "monitor-preview-v1" as const;

export type MonitorPreviewEmotionDominant = "positive" | "focused" | "frustrated";

export interface MonitorPreviewFaceBox {
  /** Normalized 0–1 relative to frame width/height */
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface MonitorPreviewFrameMeta {
  schemaVersion: typeof MONITOR_PREVIEW_SCHEMA_VERSION;
  sessionId: string;
  streamId: string;
  frameId: string;
  sequence: number;
  capturedAt: string;
  width: number;
  height: number;
  faceBox?: MonitorPreviewFaceBox;
  facePresent?: boolean;
  attentionScore?: number;
  emotionDominant?: MonitorPreviewEmotionDominant;
  emotionLabel?: string;
  attentionProvider?: string;
  emotionProvider?: string;
  attentionAlgorithmVersion?: string;
  emotionAlgorithmVersion?: string;
}

export interface MonitorPreviewUploadPayload {
  schemaVersion: typeof MONITOR_PREVIEW_SCHEMA_VERSION;
  sessionId: string;
  mimeType: "image/jpeg" | "image/webp";
  imageBase64: string;
  meta: MonitorPreviewFrameMeta;
}

export interface MonitorPreviewLatestResponse {
  available: boolean;
  stale?: boolean;
  mimeType?: "image/jpeg" | "image/webp";
  imageBase64?: string;
  meta?: MonitorPreviewFrameMeta;
  capturedAt?: string;
  expiresAt?: string;
}

export const MONITOR_PREVIEW_EMOTION_LABELS: Record<MonitorPreviewEmotionDominant, string> = {
  positive: "愉悦",
  focused: "专注",
  frustrated: "急躁"
};

export function resolveDominantEmotion(input: {
  positiveScore?: number;
  focusedScore?: number;
  frustratedScore?: number;
}): { dominant?: MonitorPreviewEmotionDominant; label?: string } {
  const entries: Array<[MonitorPreviewEmotionDominant, number]> = [
    ["positive", input.positiveScore ?? 0],
    ["focused", input.focusedScore ?? 0],
    ["frustrated", input.frustratedScore ?? 0]
  ];
  const top = entries.sort((left, right) => right[1] - left[1])[0];
  if (!top || top[1] <= 0) return {};
  return { dominant: top[0], label: MONITOR_PREVIEW_EMOTION_LABELS[top[0]] };
}
