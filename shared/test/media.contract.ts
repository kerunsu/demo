import {
  MEDIA_CHUNK_CONTENT_TYPE,
  MEDIA_MAX_CHUNK_BYTES,
  MEDIA_MAX_TURN_DURATION_MS,
  type MediaChunkAck,
  type MediaChunkMetadata,
  type MediaStreamStartRequest,
  type MediaStreamSummary
} from "../src/media.js";

const startRequest = {
  sessionId: "session-1",
  streamId: "stream-1",
  turnId: "turn-1",
  correlationId: "corr-1",
  startedAt: "2026-06-13T08:00:00.000Z",
  format: {
    codec: "webm_opus",
    mimeType: "audio/webm;codecs=opus",
    sampleRateHz: 48000,
    channels: 1,
    chunkDurationMs: 250
  },
  maxTurnDurationMs: MEDIA_MAX_TURN_DURATION_MS
} satisfies MediaStreamStartRequest;

const chunkMetadata = {
  ...startRequest,
  sequence: 0,
  capturedAt: "2026-06-13T08:00:00.250Z",
  durationMs: 250,
  byteLength: 1024
} satisfies MediaChunkMetadata;

const ack = {
  sessionId: "session-1",
  streamId: "stream-1",
  sequence: 0,
  accepted: true,
  expectedNextSequence: 1,
  receivedBytes: 1024,
  missingSequences: [],
  rawAudioPersisted: false
} satisfies MediaChunkAck;

const summary = {
  ...startRequest,
  status: "finished",
  endedAt: "2026-06-13T08:00:01.000Z",
  chunkCount: 1,
  receivedBytes: 1024,
  expectedNextSequence: 1,
  missingSequences: [],
  rawAudioPersisted: false
} satisfies MediaStreamSummary;

const contentType = MEDIA_CHUNK_CONTENT_TYPE satisfies "application/octet-stream";
const maxBytes = MEDIA_MAX_CHUNK_BYTES satisfies number;

void chunkMetadata;
void ack;
void summary;
void contentType;
void maxBytes;
