import type {
  MediaChunkAck,
  MediaStreamFinishRequest,
  MediaStreamStartRequest,
  MediaStreamSummary
} from "child-education-training-demo/shared/media";
import type { ProviderResult, SttTranscript } from "child-education-training-demo/shared/providers";
import { MEDIA_CHUNK_CONTENT_TYPE } from "child-education-training-demo/shared/media";
import { FRONTEND_RUNTIME_CONFIG } from "../../config/runtime";
import type { BrowserAudioChunk } from "./browserAudioCapture";

function mediaUrl(path: string) {
  return `${FRONTEND_RUNTIME_CONFIG.apiBaseUrl}${path}`;
}

async function parseApiResponse<T>(response: Response): Promise<T> {
  const body = (await response.json()) as { success: boolean; data: T; error?: { message: string } };
  if (!response.ok || !body.success) {
    throw new Error(body.error?.message ?? `Media ingress request failed with ${response.status}`);
  }
  return body.data;
}

async function parseProviderResultResponse<T>(response: Response): Promise<T> {
  const body = (await response.json()) as { success: boolean; data: T; error?: { message: string } };
  if (!body.success) {
    throw new Error(body.error?.message ?? `Provider request failed with ${response.status}`);
  }
  if (body.data) {
    return body.data;
  }
  throw new Error(`Provider request failed with ${response.status}`);
}

export async function startMediaStream(input: MediaStreamStartRequest): Promise<MediaStreamSummary> {
  const response = await fetch(mediaUrl(`/media/${input.sessionId}/streams/${input.streamId}/start`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input)
  });
  return parseApiResponse<MediaStreamSummary>(response);
}

export async function sendMediaChunk(input: {
  sessionId: string;
  turnId: string;
  correlationId: string;
  chunk: BrowserAudioChunk;
}): Promise<MediaChunkAck> {
  const response = await fetch(mediaUrl(`/media/${input.sessionId}/streams/${input.chunk.streamId}/chunks/${input.chunk.sequence}`), {
    method: "POST",
    headers: {
      "content-type": MEDIA_CHUNK_CONTENT_TYPE,
      "x-turn-id": input.turnId,
      "x-correlation-id": input.correlationId,
      "x-captured-at": input.chunk.capturedAt,
      "x-duration-ms": String(input.chunk.durationMs),
      "x-audio-codec": normalizeCodec(input.chunk.format.mimeType),
      "x-audio-mime-type": input.chunk.format.mimeType,
      "x-sample-rate-hz": String(input.chunk.format.sampleRateHz ?? 16000),
      "x-audio-channels": String(input.chunk.format.channels ?? 1),
      "x-chunk-duration-ms": String(input.chunk.format.chunkDurationMs)
    },
    body: input.chunk.blob
  });
  return parseApiResponse<MediaChunkAck>(response);
}

export async function finishMediaStream(input: MediaStreamFinishRequest): Promise<MediaStreamSummary> {
  const response = await fetch(mediaUrl(`/media/${input.sessionId}/streams/${input.streamId}/finish`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input)
  });
  return parseApiResponse<MediaStreamSummary>(response);
}

export async function transcribeMediaStream(input: {
  sessionId: string;
  streamId: string;
  turnId: string;
  correlationId: string;
  languageHint?: string;
  timeoutMs?: number;
}): Promise<ProviderResult<SttTranscript>> {
  const response = await fetch(mediaUrl(`/media/${input.sessionId}/streams/${input.streamId}/transcribe`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      turnId: input.turnId,
      correlationId: input.correlationId,
      languageHint: input.languageHint,
      timeoutMs: input.timeoutMs
    })
  });
  return parseProviderResultResponse<ProviderResult<SttTranscript>>(response);
}

function normalizeCodec(mimeType: string) {
  if (mimeType.includes("webm") && mimeType.includes("opus")) return "webm_opus";
  if (mimeType.includes("webm")) return "webm";
  if (mimeType.includes("ogg") && mimeType.includes("opus")) return "ogg_opus";
  if (mimeType.includes("wav")) return "wav";
  return "unknown";
}
