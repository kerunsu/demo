import type { VideoSegmentAck, VideoStreamFinishRequest, VideoStreamStartRequest, VideoStreamSummary } from "child-education-training-demo/shared/raw-media";
import { MEDIA_CHUNK_CONTENT_TYPE } from "child-education-training-demo/shared/media";
import { FRONTEND_RUNTIME_CONFIG } from "../../config/runtime";

function mediaUrl(path: string) {
  return `${FRONTEND_RUNTIME_CONFIG.apiBaseUrl}${path}`;
}

async function parseApiResponse<T>(response: Response): Promise<T> {
  const body = (await response.json()) as { success: boolean; data: T; error?: { message: string } };
  if (!response.ok || !body.success) {
    throw new Error(body.error?.message ?? `Video ingress request failed with ${response.status}`);
  }
  return body.data;
}

export async function startVideoStream(input: VideoStreamStartRequest): Promise<VideoStreamSummary> {
  const response = await fetch(mediaUrl(`/media/${input.sessionId}/video/${input.streamId}/start`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input)
  });
  return parseApiResponse<VideoStreamSummary>(response);
}

export async function sendVideoSegment(input: {
  sessionId: string;
  streamId: string;
  correlationId: string;
  sequence: number;
  capturedAt: string;
  durationMs: number;
  mimeType: string;
  blob: Blob;
}): Promise<VideoSegmentAck> {
  const response = await fetch(mediaUrl(`/media/${input.sessionId}/video/${input.streamId}/segments/${input.sequence}`), {
    method: "POST",
    headers: {
      "content-type": MEDIA_CHUNK_CONTENT_TYPE,
      "x-correlation-id": input.correlationId,
      "x-captured-at": input.capturedAt,
      "x-duration-ms": String(input.durationMs),
      "x-video-mime-type": input.mimeType
    },
    body: input.blob
  });
  return parseApiResponse<VideoSegmentAck>(response);
}

export async function uploadVideoThumbnail(input: {
  sessionId: string;
  streamId: string;
  correlationId: string;
  mimeType: string;
  blob: Blob;
}) {
  const response = await fetch(mediaUrl(`/media/${input.sessionId}/video/${input.streamId}/thumbnail`), {
    method: "POST",
    headers: {
      "content-type": MEDIA_CHUNK_CONTENT_TYPE,
      "x-correlation-id": input.correlationId,
      "x-thumbnail-mime-type": input.mimeType
    },
    body: input.blob
  });
  return parseApiResponse<{ persisted: boolean; relativePath?: string }>(response);
}

export async function finishVideoStream(input: VideoStreamFinishRequest): Promise<VideoStreamSummary> {
  const response = await fetch(mediaUrl(`/media/${input.sessionId}/video/${input.streamId}/finish`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input)
  });
  return parseApiResponse<VideoStreamSummary>(response);
}
