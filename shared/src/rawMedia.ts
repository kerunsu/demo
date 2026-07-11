export type RawMediaPersistenceMode = "disabled" | "enabled";

export type SessionMediaConsentScope = "raw_audio_video";

export interface RawMediaRuntimeConfig {
  persistence: RawMediaPersistenceMode;
  root: string;
  retentionDays: number;
  requireConsent: boolean;
  encryption: string;
}

export interface SessionMediaConsentRecord {
  recordedAt: string;
  scope: SessionMediaConsentScope;
  consentedBy: string;
}

export interface SessionMediaChunkRecord {
  sequence: number;
  relativePath: string;
  byteLength: number;
  capturedAt?: string;
}

export interface SessionMediaAudioTurnRecord {
  streamId: string;
  turnId: string;
  correlationId: string;
  status: "started" | "receiving" | "finished" | "cancelled" | "failed";
  startedAt: string;
  endedAt?: string;
  chunks: SessionMediaChunkRecord[];
  mergedRelativePath?: string;
  missingSequences: number[];
  receivedBytes: number;
}

export interface SessionMediaVideoStreamRecord {
  streamId: string;
  correlationId: string;
  questionId?: string;
  status: "started" | "receiving" | "finished" | "cancelled" | "failed";
  startedAt: string;
  endedAt?: string;
  segments: SessionMediaChunkRecord[];
  mergedRelativePath?: string;
  thumbnailRelativePath?: string;
  missingSequences: number[];
  receivedBytes: number;
}

export interface SessionMediaManifest {
  schemaVersion: "raw-media-manifest-v1";
  sessionId: string;
  createdAt: string;
  updatedAt: string;
  consent?: SessionMediaConsentRecord;
  audio: Record<string, SessionMediaAudioTurnRecord>;
  video: Record<string, SessionMediaVideoStreamRecord>;
}

export interface SessionMediaSummary {
  sessionId: string;
  consentRecorded: boolean;
  audioTurnCount: number;
  videoStreamCount: number;
  totalPersistedBytes: number;
  missingChunkCount: number;
  updatedAt?: string;
}

export interface RawMediaDiagnostics {
  persistence: RawMediaPersistenceMode;
  rootPath: string;
  rootExists: boolean;
  rootWritable: boolean;
  retentionDays: number;
  requireConsent: boolean;
  sessionCount: number;
  totalPersistedBytes: number;
}

export interface VideoStreamStartRequest {
  sessionId: string;
  streamId: string;
  correlationId: string;
  questionId?: string;
  startedAt: string;
  mimeType: string;
}

export interface VideoSegmentMetadata {
  sessionId: string;
  streamId: string;
  correlationId: string;
  sequence: number;
  capturedAt: string;
  durationMs: number;
  byteLength: number;
  mimeType: string;
}

export interface VideoSegmentAck {
  sessionId: string;
  streamId: string;
  sequence: number;
  accepted: boolean;
  expectedNextSequence: number;
  receivedBytes: number;
  missingSequences: number[];
  rawVideoPersisted: boolean;
}

export interface VideoStreamFinishRequest {
  sessionId: string;
  streamId: string;
  correlationId: string;
  reason: "question_end" | "manual_stop" | "cancelled" | "timeout" | "disconnect" | "device_lost";
  endedAt: string;
}

export interface VideoStreamSummary {
  sessionId: string;
  streamId: string;
  correlationId: string;
  questionId?: string;
  status: "started" | "receiving" | "finished" | "cancelled" | "failed";
  startedAt: string;
  endedAt?: string;
  segmentCount: number;
  receivedBytes: number;
  expectedNextSequence: number;
  missingSequences: number[];
  rawVideoPersisted: boolean;
  thumbnailRelativePath?: string;
}

export const RAW_MEDIA_MANIFEST_SCHEMA_VERSION = "raw-media-manifest-v1" as const;
export const VIDEO_MAX_SEGMENT_BYTES = 2 * 1024 * 1024;
