type ScreenMirrorRole = "child" | "robot";

export interface ScreenMirrorFramePayload {
  role: ScreenMirrorRole;
  sessionId?: string;
  capturedAt: string;
  sequence: number;
  srcDoc: string;
}

type StoredScreenMirrorFrame = ScreenMirrorFramePayload & {
  receivedAt: string;
};

const latestByRole = new Map<ScreenMirrorRole, StoredScreenMirrorFrame>();

export function storeScreenMirrorFrame(payload: ScreenMirrorFramePayload) {
  const receivedAt = new Date().toISOString();
  const frame = { ...payload, receivedAt };
  latestByRole.set(payload.role, frame);
  return {
    role: payload.role,
    sessionId: payload.sessionId,
    sequence: payload.sequence,
    receivedAt
  };
}

export function getLatestScreenMirrorFrame(role: ScreenMirrorRole) {
  return latestByRole.get(role) ?? null;
}

export function resetScreenMirrorFramesForTests() {
  latestByRole.clear();
}
