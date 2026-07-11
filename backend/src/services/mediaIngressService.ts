import type {
  MediaChunkAck,
  MediaChunkMetadata,
  MediaStreamFinishRequest,
  MediaStreamStartRequest,
  MediaStreamSummary
} from "child-education-training-demo/shared/media";
import {
  canPersistSessionMedia,
  ensureAudioTurnRecord,
  finalizeAudioTurn,
  persistAudioChunk,
  persistAudioMerged
} from "./rawMediaPersistenceService.js";
import { persistMergedAudioFeaturesIfMissing } from "./mergedAudioFeatureService.js";
import { recordVoiceMetric } from "./voiceObservabilityService.js";

type MediaStreamRecord = MediaStreamSummary & {
  lastUpdatedAt: string;
  chunks: Buffer[];
};

const streams = new Map<string, MediaStreamRecord>();

function streamKey(sessionId: string, streamId: string) {
  return `${sessionId}:${streamId}`;
}

function missingSequences(expectedNextSequence: number, receivedSequence: number) {
  const missing: number[] = [];
  for (let sequence = expectedNextSequence; sequence < receivedSequence; sequence += 1) {
    missing.push(sequence);
  }
  return missing;
}

function toSummary(stream: MediaStreamRecord, rawAudioPersisted = false): MediaStreamSummary {
  return {
    sessionId: stream.sessionId,
    streamId: stream.streamId,
    turnId: stream.turnId,
    correlationId: stream.correlationId,
    status: stream.status,
    startedAt: stream.startedAt,
    endedAt: stream.endedAt,
    format: stream.format,
    chunkCount: stream.chunkCount,
    receivedBytes: stream.receivedBytes,
    expectedNextSequence: stream.expectedNextSequence,
    missingSequences: stream.missingSequences,
    rawAudioPersisted
  };
}

export async function startMediaStream(input: MediaStreamStartRequest): Promise<MediaStreamSummary> {
  const key = streamKey(input.sessionId, input.streamId);
  const existing = streams.get(key);
  if (existing && existing.status !== "failed") {
    return toSummary(existing, existing.rawAudioPersisted);
  }

  const canPersist = await canPersistSessionMedia(input.sessionId);
  if (canPersist) {
    await ensureAudioTurnRecord({
      sessionId: input.sessionId,
      streamId: input.streamId,
      turnId: input.turnId,
      correlationId: input.correlationId,
      startedAt: input.startedAt
    });
  }

  const summary: MediaStreamRecord = {
    sessionId: input.sessionId,
    streamId: input.streamId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    status: "started",
    startedAt: input.startedAt,
    format: input.format,
    chunkCount: 0,
    receivedBytes: 0,
    expectedNextSequence: 0,
    missingSequences: [],
    rawAudioPersisted: canPersist,
    lastUpdatedAt: new Date().toISOString(),
    chunks: []
  };
  streams.set(key, summary);
  recordVoiceMetric({
    sessionId: input.sessionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    stage: "audio_capture_start",
    startedAt: input.startedAt,
    completedAt: input.startedAt,
    metadata: {
      streamId: input.streamId,
      codec: input.format.codec,
      sampleRateHz: input.format.sampleRateHz,
      channels: input.format.channels
    }
  });
  return toSummary(summary, summary.rawAudioPersisted);
}

export async function receiveMediaChunk(metadata: MediaChunkMetadata, chunk: Buffer): Promise<MediaChunkAck> {
  const key = streamKey(metadata.sessionId, metadata.streamId);
  const stream = streams.get(key);
  if (!stream) {
    throw new Error("MEDIA_STREAM_NOT_STARTED");
  }
  if (stream.status === "finished" || stream.status === "cancelled") {
    throw new Error("MEDIA_STREAM_CLOSED");
  }
  if (metadata.byteLength !== chunk.byteLength) {
    throw new Error("MEDIA_CHUNK_SIZE_MISMATCH");
  }

  const newlyMissing = missingSequences(stream.expectedNextSequence, metadata.sequence);
  const accepted = metadata.sequence >= stream.expectedNextSequence;
  let rawAudioPersisted = false;
  if (accepted) {
    const isFirstAcceptedChunk = stream.chunkCount === 0;
    stream.status = "receiving";
    stream.chunkCount += 1;
    stream.receivedBytes += chunk.byteLength;
    stream.chunks.push(Buffer.from(chunk));
    stream.expectedNextSequence = metadata.sequence + 1;
    stream.missingSequences = Array.from(new Set([...stream.missingSequences, ...newlyMissing])).sort((a, b) => a - b);
    stream.lastUpdatedAt = new Date().toISOString();
    if (isFirstAcceptedChunk) {
      recordVoiceMetric({
        sessionId: metadata.sessionId,
        turnId: metadata.turnId,
        correlationId: metadata.correlationId,
        stage: "first_audio_chunk",
        startedAt: metadata.capturedAt,
        completedAt: metadata.capturedAt,
        audioDurationMs: metadata.durationMs,
        metadata: {
          streamId: metadata.streamId,
          sequence: metadata.sequence,
          byteLength: metadata.byteLength
        }
      });
      recordVoiceMetric({
        sessionId: metadata.sessionId,
        turnId: metadata.turnId,
        correlationId: metadata.correlationId,
        stage: "vad_speech_start",
        startedAt: metadata.capturedAt,
        completedAt: metadata.capturedAt,
        audioDurationMs: metadata.durationMs,
        metadata: {
          streamId: metadata.streamId,
          source: "first_audio_chunk_placeholder"
        }
      });
    }
    const persisted = await persistAudioChunk({
      sessionId: metadata.sessionId,
      streamId: metadata.streamId,
      turnId: metadata.turnId,
      correlationId: metadata.correlationId,
      sequence: metadata.sequence,
      capturedAt: metadata.capturedAt,
      chunk,
      mimeType: metadata.format.mimeType,
      missingSequences: stream.missingSequences
    });
    rawAudioPersisted = persisted.persisted;
    stream.rawAudioPersisted = stream.rawAudioPersisted || rawAudioPersisted;
  }

  return {
    sessionId: metadata.sessionId,
    streamId: metadata.streamId,
    sequence: metadata.sequence,
    accepted,
    expectedNextSequence: stream.expectedNextSequence,
    receivedBytes: stream.receivedBytes,
    missingSequences: stream.missingSequences,
    rawAudioPersisted
  };
}

export async function finishMediaStream(input: MediaStreamFinishRequest): Promise<MediaStreamSummary> {
  const key = streamKey(input.sessionId, input.streamId);
  const stream = streams.get(key);
  if (!stream) {
    throw new Error("MEDIA_STREAM_NOT_STARTED");
  }
  stream.status = input.reason === "cancelled" || input.reason === "disconnect" || input.reason === "device_lost" ? "cancelled" : "finished";
  stream.endedAt = input.endedAt;
  stream.lastUpdatedAt = new Date().toISOString();
  recordVoiceMetric({
    sessionId: input.sessionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    stage: "vad_speech_end",
    startedAt: stream.startedAt,
    completedAt: input.endedAt,
    status: stream.status === "cancelled" ? "cancelled" : "success",
    audioDurationMs: stream.format.chunkDurationMs * stream.chunkCount,
    metadata: {
      streamId: input.streamId,
      reason: input.reason,
      chunkCount: stream.chunkCount,
      receivedBytes: stream.receivedBytes
    }
  });
  const merged = await persistAudioMerged({
    sessionId: input.sessionId,
    turnId: input.turnId,
    chunks: stream.chunks
  });
  if (merged.persisted) {
    stream.rawAudioPersisted = true;
  }
  void persistMergedAudioFeaturesIfMissing({
    sessionId: input.sessionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    audioBuffer: Buffer.concat(stream.chunks),
    mimeType: stream.format.mimeType,
    audioDurationMs: stream.format.chunkDurationMs * stream.chunkCount
  }).catch(() => undefined);
  await finalizeAudioTurn({
    sessionId: input.sessionId,
    turnId: input.turnId,
    status: stream.status,
    endedAt: input.endedAt
  });
  return toSummary(stream, stream.rawAudioPersisted);
}

export function getMediaStreamSummary(sessionId: string, streamId: string): MediaStreamSummary | null {
  const stream = streams.get(streamKey(sessionId, streamId));
  return stream ? toSummary(stream, stream.rawAudioPersisted) : null;
}

export function getMediaStreamAudioBuffer(sessionId: string, streamId: string): Buffer | null {
  const stream = streams.get(streamKey(sessionId, streamId));
  if (!stream) return null;
  return Buffer.concat(stream.chunks);
}

export function resetMediaIngressForTests() {
  streams.clear();
}
