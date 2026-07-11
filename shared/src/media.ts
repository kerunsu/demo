export type MediaStreamStatus = "started" | "receiving" | "finished" | "cancelled" | "failed";
export type MediaCodec = "pcm_s16le" | "wav" | "webm_opus" | "webm" | "ogg_opus" | "unknown";

export interface MediaAudioFormat {
  codec: MediaCodec;
  mimeType: string;
  sampleRateHz: number;
  channels: number;
  chunkDurationMs: number;
}

export interface MediaStreamStartRequest {
  sessionId: string;
  streamId: string;
  turnId: string;
  correlationId: string;
  deviceIdHash?: string;
  startedAt: string;
  format: MediaAudioFormat;
  maxTurnDurationMs: number;
}

export interface MediaChunkMetadata {
  sessionId: string;
  streamId: string;
  turnId: string;
  correlationId: string;
  sequence: number;
  capturedAt: string;
  durationMs: number;
  byteLength: number;
  format: MediaAudioFormat;
}

export interface MediaChunkAck {
  sessionId: string;
  streamId: string;
  sequence: number;
  accepted: boolean;
  expectedNextSequence: number;
  receivedBytes: number;
  missingSequences: number[];
  rawAudioPersisted: boolean;
}

export interface MediaStreamFinishRequest {
  sessionId: string;
  streamId: string;
  turnId: string;
  correlationId: string;
  reason: "speech_end" | "manual_stop" | "cancelled" | "timeout" | "disconnect" | "device_lost";
  endedAt: string;
}

export interface MediaStreamSummary {
  sessionId: string;
  streamId: string;
  turnId: string;
  correlationId: string;
  status: MediaStreamStatus;
  startedAt: string;
  endedAt?: string;
  format: MediaAudioFormat;
  chunkCount: number;
  receivedBytes: number;
  expectedNextSequence: number;
  missingSequences: number[];
  rawAudioPersisted: boolean;
}

export const MEDIA_CHUNK_CONTENT_TYPE = "application/octet-stream";
export const MEDIA_MAX_CHUNK_BYTES = 512 * 1024;
export const MEDIA_MAX_TURN_DURATION_MS = 10000;
