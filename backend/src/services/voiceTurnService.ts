export type VoiceTurnState =
  | "IDLE"
  | "LISTENING"
  | "TRANSCRIBING"
  | "ROBOT_SPEAKING"
  | "CANCELLED"
  | "COMPLETED"
  | "DEGRADED";

export interface VoiceTurnSnapshot {
  sessionId: string;
  turnId: string | null;
  state: VoiceTurnState;
  listeningAllowed: boolean;
  robotSpeaking: boolean;
  retryCount: number;
  maxRetries: number;
  startedAt?: string;
  updatedAt: string;
  deadlineAt?: string;
  bargeInReserved: boolean;
  lastReason?: string;
}

const DEFAULT_TURN_TIMEOUT_MS = 8000;
const DEFAULT_MAX_RETRIES = 2;
const turns = new Map<string, VoiceTurnSnapshot>();

function nowIso() {
  return new Date().toISOString();
}

function createIdle(sessionId: string): VoiceTurnSnapshot {
  return {
    sessionId,
    turnId: null,
    state: "IDLE",
    listeningAllowed: true,
    robotSpeaking: false,
    retryCount: 0,
    maxRetries: DEFAULT_MAX_RETRIES,
    updatedAt: nowIso(),
    bargeInReserved: true
  };
}

export function getVoiceTurnSnapshot(sessionId: string): VoiceTurnSnapshot {
  return turns.get(sessionId) ?? createIdle(sessionId);
}

export function startListeningTurn(input: {
  sessionId: string;
  turnId: string;
  timeoutMs?: number;
  maxRetries?: number;
}): VoiceTurnSnapshot {
  const current = getVoiceTurnSnapshot(input.sessionId);
  if (current.robotSpeaking) {
    return {
      ...current,
      state: "DEGRADED",
      listeningAllowed: false,
      lastReason: "ROBOT_SPEAKING_LISTENING_PAUSED",
      updatedAt: nowIso()
    };
  }

  const startedAt = nowIso();
  const timeoutMs = input.timeoutMs ?? DEFAULT_TURN_TIMEOUT_MS;
  const snapshot: VoiceTurnSnapshot = {
    sessionId: input.sessionId,
    turnId: input.turnId,
    state: "LISTENING",
    listeningAllowed: true,
    robotSpeaking: false,
    retryCount: current.turnId === input.turnId ? current.retryCount : 0,
    maxRetries: input.maxRetries ?? current.maxRetries ?? DEFAULT_MAX_RETRIES,
    startedAt,
    updatedAt: startedAt,
    deadlineAt: new Date(Date.now() + timeoutMs).toISOString(),
    bargeInReserved: true
  };
  turns.set(input.sessionId, snapshot);
  return snapshot;
}

export function stopListeningForTranscription(sessionId: string, reason = "speech_end"): VoiceTurnSnapshot {
  const current = getVoiceTurnSnapshot(sessionId);
  const snapshot: VoiceTurnSnapshot = {
    ...current,
    state: "TRANSCRIBING",
    listeningAllowed: false,
    updatedAt: nowIso(),
    lastReason: reason
  };
  turns.set(sessionId, snapshot);
  return snapshot;
}

export function markRobotSpeaking(input: { sessionId: string; turnId: string; speaking: boolean; reason?: string }): VoiceTurnSnapshot {
  const current = getVoiceTurnSnapshot(input.sessionId);
  const snapshot: VoiceTurnSnapshot = {
    ...current,
    turnId: input.turnId,
    state: input.speaking ? "ROBOT_SPEAKING" : "IDLE",
    listeningAllowed: !input.speaking,
    robotSpeaking: input.speaking,
    updatedAt: nowIso(),
    lastReason: input.reason
  };
  turns.set(input.sessionId, snapshot);
  return snapshot;
}

export function cancelVoiceTurn(sessionId: string, reason = "cancelled"): VoiceTurnSnapshot {
  const current = getVoiceTurnSnapshot(sessionId);
  const snapshot: VoiceTurnSnapshot = {
    ...current,
    state: "CANCELLED",
    listeningAllowed: !current.robotSpeaking,
    updatedAt: nowIso(),
    lastReason: reason
  };
  turns.set(sessionId, snapshot);
  return snapshot;
}

export function completeVoiceTurn(sessionId: string, reason = "completed"): VoiceTurnSnapshot {
  const current = getVoiceTurnSnapshot(sessionId);
  const snapshot: VoiceTurnSnapshot = {
    ...current,
    state: "COMPLETED",
    listeningAllowed: true,
    robotSpeaking: false,
    updatedAt: nowIso(),
    lastReason: reason
  };
  turns.set(sessionId, snapshot);
  return snapshot;
}

export function retryVoiceTurn(sessionId: string, reason = "retry"): VoiceTurnSnapshot {
  const current = getVoiceTurnSnapshot(sessionId);
  const nextRetryCount = current.retryCount + 1;
  const snapshot: VoiceTurnSnapshot = {
    ...current,
    state: nextRetryCount > current.maxRetries ? "DEGRADED" : "IDLE",
    listeningAllowed: nextRetryCount <= current.maxRetries && !current.robotSpeaking,
    retryCount: nextRetryCount,
    updatedAt: nowIso(),
    lastReason: nextRetryCount > current.maxRetries ? "MAX_RETRIES_EXCEEDED" : reason
  };
  turns.set(sessionId, snapshot);
  return snapshot;
}

export function resetVoiceTurnsForTests() {
  turns.clear();
}
