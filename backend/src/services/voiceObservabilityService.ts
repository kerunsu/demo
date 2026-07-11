import { createHash } from "node:crypto";
import type { ProviderMetadata } from "child-education-training-demo/shared/providers";

export type VoiceMetricStage =
  | "audio_capture_start"
  | "first_audio_chunk"
  | "vad_speech_start"
  | "vad_speech_end"
  | "stt_request_start"
  | "stt_complete"
  | "transcript_available"
  | "chat_reply_generated"
  | "safety_review"
  | "tts_request_start"
  | "tts_audio_ready"
  | "robot_playback_start"
  | "robot_playback_complete"
  | "voice_turn_total"
  | "partner_turn_request_start"
  | "partner_turn_complete"
  | "partner_turn_failed";

export type VoiceMetricStatus = "success" | "failure" | "degraded" | "cancelled" | "timeout" | "pending";

export interface VoiceMetricRecord {
  sessionId: string;
  turnId: string;
  correlationId: string;
  stage: VoiceMetricStage;
  startedAt: string;
  completedAt: string;
  durationMs: number;
  status: VoiceMetricStatus;
  provider?: string;
  model?: string;
  errorCode?: string;
  externalNetworkCalled: boolean;
  degradedProvider: boolean;
  inputPersisted: boolean;
  rawAudioPersisted: false;
  sensitiveTextLogged: false;
  audioDurationMs?: number;
  textLength?: number;
  textHash?: string;
  metadata?: Record<string, string | number | boolean | null>;
}

export interface VoiceMetricInput {
  sessionId: string;
  turnId: string;
  correlationId: string;
  stage: VoiceMetricStage;
  startedAt?: string | Date;
  completedAt?: string | Date;
  durationMs?: number;
  status?: VoiceMetricStatus;
  provider?: string;
  model?: string;
  errorCode?: string;
  externalNetworkCalled?: boolean;
  degradedProvider?: boolean;
  inputPersisted?: boolean;
  audioDurationMs?: number;
  textForHash?: string;
  metadata?: Record<string, string | number | boolean | null | undefined>;
}

export interface VoiceTurnMetricsSummary {
  sessionId: string;
  turnId: string;
  correlationId: string;
  metricCount: number;
  startedAt?: string;
  completedAt?: string;
  totalDurationMs?: number;
  stages: VoiceMetricRecord[];
}

const MAX_METRICS = 1000;
const records: VoiceMetricRecord[] = [];
const dedupeKeys = new Set<string>();

function toIso(value: string | Date | undefined) {
  if (!value) return new Date().toISOString();
  return value instanceof Date ? value.toISOString() : value;
}

function sanitizeMetadata(metadata: VoiceMetricInput["metadata"]) {
  if (!metadata) return undefined;
  const safeEntries = Object.entries(metadata).filter(([, value]) => value !== undefined);
  if (safeEntries.length === 0) return undefined;
  return Object.fromEntries(safeEntries) as Record<string, string | number | boolean | null>;
}

function createDedupeKey(input: Pick<VoiceMetricInput, "sessionId" | "turnId" | "correlationId" | "stage">) {
  return `${input.sessionId}:${input.turnId}:${input.correlationId}:${input.stage}`;
}

function trimIfNeeded() {
  while (records.length > MAX_METRICS) {
    const removed = records.shift();
    if (removed) dedupeKeys.delete(createDedupeKey(removed));
  }
}

export function hashRedactedText(value: string) {
  return createHash("sha256").update(value, "utf8").digest("hex").slice(0, 16);
}

export function providerMetricDefaults(metadata?: ProviderMetadata) {
  return {
    provider: metadata?.providerId ?? metadata?.providerName,
    model: metadata?.modelId ?? metadata?.vendorModelName,
    externalNetworkCalled: metadata?.dataSafety?.externalNetworkCalled ?? false,
    inputPersisted: metadata?.dataSafety?.inputPersisted ?? false
  };
}

export function recordVoiceMetric(input: VoiceMetricInput): VoiceMetricRecord | null {
  const dedupeKey = createDedupeKey(input);
  if (dedupeKeys.has(dedupeKey)) return null;

  const startedAt = toIso(input.startedAt);
  const completedAt = toIso(input.completedAt ?? input.startedAt);
  const inferredDurationMs = Math.max(0, Date.parse(completedAt) - Date.parse(startedAt));
  const text = input.textForHash;
  const record: VoiceMetricRecord = {
    sessionId: input.sessionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    stage: input.stage,
    startedAt,
    completedAt,
    durationMs: input.durationMs ?? inferredDurationMs,
    status: input.status ?? "success",
    provider: input.provider,
    model: input.model,
    errorCode: input.errorCode,
    externalNetworkCalled: input.externalNetworkCalled ?? false,
    degradedProvider: input.degradedProvider ?? false,
    inputPersisted: input.inputPersisted ?? false,
    rawAudioPersisted: false,
    sensitiveTextLogged: false,
    audioDurationMs: input.audioDurationMs,
    textLength: text ? text.length : undefined,
    textHash: text ? hashRedactedText(text) : undefined,
    metadata: sanitizeMetadata(input.metadata)
  };
  records.push(record);
  dedupeKeys.add(dedupeKey);
  trimIfNeeded();
  return record;
}

export function recordVoiceTurnTotal(input: {
  sessionId: string;
  turnId: string;
  correlationId: string;
  completedAt?: string | Date;
  status?: VoiceMetricStatus;
  errorCode?: string;
}) {
  const relevant = records.filter((record) => record.sessionId === input.sessionId && record.turnId === input.turnId);
  const startedAt = relevant
    .map((record) => record.startedAt)
    .sort((left, right) => Date.parse(left) - Date.parse(right))[0];
  return recordVoiceMetric({
    sessionId: input.sessionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    stage: "voice_turn_total",
    startedAt: startedAt ?? input.completedAt,
    completedAt: input.completedAt,
    status: input.status ?? "success",
    errorCode: input.errorCode
  });
}

export function getVoiceMetricsForSession(sessionId: string) {
  return records.filter((record) => record.sessionId === sessionId);
}

export function getVoiceTurnSummary(sessionId: string, turnId: string): VoiceTurnMetricsSummary {
  const stages = records.filter((record) => record.sessionId === sessionId && record.turnId === turnId);
  const first = stages.map((record) => record.startedAt).sort((left, right) => Date.parse(left) - Date.parse(right))[0];
  const last = stages
    .map((record) => record.completedAt)
    .sort((left, right) => Date.parse(right) - Date.parse(left))[0];
  return {
    sessionId,
    turnId,
    correlationId: stages[0]?.correlationId ?? "",
    metricCount: stages.length,
    startedAt: first,
    completedAt: last,
    totalDurationMs: first && last ? Math.max(0, Date.parse(last) - Date.parse(first)) : undefined,
    stages
  };
}

export function resetVoiceObservabilityForTests() {
  records.length = 0;
  dedupeKeys.clear();
}
