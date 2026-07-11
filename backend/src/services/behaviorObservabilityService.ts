export type BehaviorMetricStage =
  | "camera_frame_received"
  | "attention_provider_complete"
  | "language_features_extracted"
  | "question_window_aligned"
  | "question_summary_ready"
  | "session_summary_ready";

export interface BehaviorMetricRecord {
  sessionId: string;
  correlationId: string;
  stage: BehaviorMetricStage;
  startedAt: string;
  completedAt: string;
  durationMs: number;
  status: "success" | "degraded" | "failure" | "timeout";
  provider?: string;
  algorithmVersion?: string;
  errorCode?: string;
  observationCount?: number;
  rawFramePersisted: false;
  rawAudioPersisted: false;
  sensitiveTextLogged: false;
}

export interface BehaviorMetricInput {
  sessionId: string;
  correlationId: string;
  stage: BehaviorMetricStage;
  startedAt?: string;
  completedAt?: string;
  durationMs?: number;
  status?: BehaviorMetricRecord["status"];
  provider?: string;
  algorithmVersion?: string;
  errorCode?: string;
  observationCount?: number;
}

const MAX_BEHAVIOR_METRICS = 1000;
const records: BehaviorMetricRecord[] = [];
const dedupeKeys = new Set<string>();

export function recordBehaviorMetric(input: BehaviorMetricInput): BehaviorMetricRecord | null {
  const key = `${input.sessionId}:${input.correlationId}:${input.stage}`;
  if (dedupeKeys.has(key)) return null;
  const startedAt = input.startedAt ?? new Date().toISOString();
  const completedAt = input.completedAt ?? startedAt;
  const record: BehaviorMetricRecord = {
    sessionId: input.sessionId,
    correlationId: input.correlationId,
    stage: input.stage,
    startedAt,
    completedAt,
    durationMs: input.durationMs ?? Math.max(0, Date.parse(completedAt) - Date.parse(startedAt)),
    status: input.status ?? "success",
    provider: input.provider,
    algorithmVersion: input.algorithmVersion,
    errorCode: input.errorCode,
    observationCount: input.observationCount,
    rawFramePersisted: false,
    rawAudioPersisted: false,
    sensitiveTextLogged: false
  };
  records.push(record);
  dedupeKeys.add(key);
  while (records.length > MAX_BEHAVIOR_METRICS) {
    const removed = records.shift();
    if (removed) dedupeKeys.delete(`${removed.sessionId}:${removed.correlationId}:${removed.stage}`);
  }
  return record;
}

export function getBehaviorMetricsForSession(sessionId: string) {
  return records.filter((record) => record.sessionId === sessionId);
}

export function resetBehaviorObservabilityForTests() {
  records.length = 0;
  dedupeKeys.clear();
}
