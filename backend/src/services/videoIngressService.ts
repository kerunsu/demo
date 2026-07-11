import type {
  VideoSegmentAck,
  VideoSegmentMetadata,
  VideoStreamFinishRequest,
  VideoStreamStartRequest,
  VideoStreamSummary
} from "child-education-training-demo/shared/raw-media";
import {
  canPersistSessionMedia,
  ensureVideoStreamRecord,
  finalizeVideoStream,
  persistVideoSegment,
  persistVideoMerged,
  persistVideoThumbnail
} from "./rawMediaPersistenceService.js";

type VideoStreamRecord = VideoStreamSummary & {
  lastUpdatedAt: string;
  segments: Buffer[];
};

const streams = new Map<string, VideoStreamRecord>();

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

function toSummary(stream: VideoStreamRecord): VideoStreamSummary {
  return {
    sessionId: stream.sessionId,
    streamId: stream.streamId,
    correlationId: stream.correlationId,
    questionId: stream.questionId,
    status: stream.status,
    startedAt: stream.startedAt,
    endedAt: stream.endedAt,
    segmentCount: stream.segmentCount,
    receivedBytes: stream.receivedBytes,
    expectedNextSequence: stream.expectedNextSequence,
    missingSequences: stream.missingSequences,
    rawVideoPersisted: stream.rawVideoPersisted,
    thumbnailRelativePath: stream.thumbnailRelativePath
  };
}

export async function startVideoStream(input: VideoStreamStartRequest): Promise<VideoStreamSummary> {
  const key = streamKey(input.sessionId, input.streamId);
  const existing = streams.get(key);
  if (existing && existing.status !== "failed") {
    return toSummary(existing);
  }

  const canPersist = await canPersistSessionMedia(input.sessionId);
  if (canPersist) {
    await ensureVideoStreamRecord({
      sessionId: input.sessionId,
      streamId: input.streamId,
      correlationId: input.correlationId,
      questionId: input.questionId,
      startedAt: input.startedAt
    });
  }

  const summary: VideoStreamRecord = {
    sessionId: input.sessionId,
    streamId: input.streamId,
    correlationId: input.correlationId,
    questionId: input.questionId,
    status: "started",
    startedAt: input.startedAt,
    segmentCount: 0,
    receivedBytes: 0,
    expectedNextSequence: 0,
    missingSequences: [],
    rawVideoPersisted: canPersist,
    lastUpdatedAt: new Date().toISOString(),
    segments: []
  };
  streams.set(key, summary);
  return toSummary(summary);
}

export async function receiveVideoSegment(metadata: VideoSegmentMetadata, segment: Buffer): Promise<VideoSegmentAck> {
  const key = streamKey(metadata.sessionId, metadata.streamId);
  const stream = streams.get(key);
  if (!stream) {
    return {
      sessionId: metadata.sessionId,
      streamId: metadata.streamId,
      sequence: metadata.sequence,
      accepted: false,
      expectedNextSequence: metadata.sequence,
      receivedBytes: 0,
      missingSequences: [],
      rawVideoPersisted: false
    };
  }
  if (stream.status === "finished" || stream.status === "cancelled") {
    return {
      sessionId: metadata.sessionId,
      streamId: metadata.streamId,
      sequence: metadata.sequence,
      accepted: false,
      expectedNextSequence: stream.expectedNextSequence,
      receivedBytes: stream.receivedBytes,
      missingSequences: stream.missingSequences,
      rawVideoPersisted: stream.rawVideoPersisted ?? false
    };
  }
  if (metadata.byteLength !== segment.byteLength) {
    throw new Error("VIDEO_SEGMENT_SIZE_MISMATCH");
  }

  const newlyMissing = missingSequences(stream.expectedNextSequence, metadata.sequence);
  const accepted = metadata.sequence >= stream.expectedNextSequence;
  let rawVideoPersisted = false;
  if (accepted) {
    stream.status = "receiving";
    stream.segmentCount += 1;
    stream.receivedBytes += segment.byteLength;
    stream.segments.push(Buffer.from(segment));
    stream.expectedNextSequence = metadata.sequence + 1;
    stream.missingSequences = Array.from(new Set([...stream.missingSequences, ...newlyMissing])).sort((a, b) => a - b);
    stream.lastUpdatedAt = new Date().toISOString();
    const persisted = await persistVideoSegment({
      sessionId: metadata.sessionId,
      streamId: metadata.streamId,
      correlationId: metadata.correlationId,
      questionId: stream.questionId,
      sequence: metadata.sequence,
      capturedAt: metadata.capturedAt,
      segment,
      mimeType: metadata.mimeType,
      missingSequences: stream.missingSequences
    });
    rawVideoPersisted = persisted.persisted;
    stream.rawVideoPersisted = stream.rawVideoPersisted || rawVideoPersisted;
  }

  return {
    sessionId: metadata.sessionId,
    streamId: metadata.streamId,
    sequence: metadata.sequence,
    accepted,
    expectedNextSequence: stream.expectedNextSequence,
    receivedBytes: stream.receivedBytes,
    missingSequences: stream.missingSequences,
    rawVideoPersisted
  };
}

export async function finishVideoStream(input: VideoStreamFinishRequest): Promise<VideoStreamSummary> {
  const key = streamKey(input.sessionId, input.streamId);
  const stream = streams.get(key);
  if (!stream) {
    return {
      sessionId: input.sessionId,
      streamId: input.streamId,
      correlationId: input.correlationId,
      status: input.reason === "cancelled" || input.reason === "disconnect" || input.reason === "device_lost" ? "cancelled" : "finished",
      startedAt: input.endedAt,
      endedAt: input.endedAt,
      segmentCount: 0,
      receivedBytes: 0,
      expectedNextSequence: 0,
      missingSequences: [],
      rawVideoPersisted: false
    };
  }
  stream.status =
    input.reason === "cancelled" || input.reason === "disconnect" || input.reason === "device_lost" ? "cancelled" : "finished";
  stream.endedAt = input.endedAt;
  stream.lastUpdatedAt = input.endedAt;
  const merged = await persistVideoMerged({
    sessionId: input.sessionId,
    streamId: input.streamId,
    segments: stream.segments
  });
  if (merged.persisted) {
    stream.rawVideoPersisted = true;
  }
  await finalizeVideoStream({
    sessionId: input.sessionId,
    streamId: input.streamId,
    status: stream.status,
    endedAt: input.endedAt
  });
  return toSummary(stream);
}

export async function uploadVideoThumbnail(input: {
  sessionId: string;
  streamId: string;
  correlationId: string;
  thumbnail: Buffer;
  mimeType: string;
}) {
  const key = streamKey(input.sessionId, input.streamId);
  const stream = streams.get(key);
  const persisted = await persistVideoThumbnail({
    sessionId: input.sessionId,
    streamId: input.streamId,
    thumbnail: input.thumbnail,
    mimeType: input.mimeType
  });
  if (stream && persisted.relativePath) {
    stream.thumbnailRelativePath = persisted.relativePath;
  }
  return persisted;
}

export function getVideoStreamSummary(sessionId: string, streamId: string): VideoStreamSummary | null {
  const stream = streams.get(streamKey(sessionId, streamId));
  return stream ? toSummary(stream) : null;
}

export function resetVideoIngressForTests() {
  streams.clear();
}
