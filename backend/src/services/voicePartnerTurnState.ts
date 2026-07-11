const partnerTurnBySession = new Map<
  string,
  {
    partnerLastLatencyMs?: number;
    partnerLastError?: string;
    partnerLastProvider?: string;
    updatedAt: string;
  }
>();

export function recordPartnerTurnSuccess(
  sessionId: string,
  input: { latencyMs: number; provider?: string }
) {
  partnerTurnBySession.set(sessionId, {
    partnerLastLatencyMs: input.latencyMs,
    partnerLastError: undefined,
    partnerLastProvider: input.provider,
    updatedAt: new Date().toISOString()
  });
}

export function recordPartnerTurnFailure(sessionId: string, errorCode: string) {
  const prev = partnerTurnBySession.get(sessionId);
  partnerTurnBySession.set(sessionId, {
    partnerLastLatencyMs: prev?.partnerLastLatencyMs,
    partnerLastError: errorCode,
    partnerLastProvider: prev?.partnerLastProvider,
    updatedAt: new Date().toISOString()
  });
}

export function getPartnerTurnMonitorState(sessionId: string) {
  return partnerTurnBySession.get(sessionId) ?? null;
}

export function resetPartnerTurnStateForTests() {
  partnerTurnBySession.clear();
}
