import type { RawMediaRuntimeConfig, SessionMediaSummary } from "child-education-training-demo/shared/raw-media";
import { apiRequest } from "./api";

export function getRawMediaConfig() {
  return apiRequest<RawMediaRuntimeConfig>("/media/config");
}

export function recordRawMediaConsent(sessionId: string, consentedBy = "training_start") {
  return apiRequest<{ sessionId: string; consent: { recordedAt: string; scope: string; consentedBy: string } }>(
    `/session/${sessionId}/media/consent`,
    {
      method: "POST",
      body: JSON.stringify({ consentedBy })
    }
  );
}

export function getSessionMediaSummary(sessionId: string) {
  return apiRequest<SessionMediaSummary | null>(`/media/${sessionId}/summary`);
}

export async function ensureRawMediaConsent(sessionId: string) {
  const config = await getRawMediaConfig();
  if (config.persistence !== "enabled") {
    return { enabled: false as const, consented: false };
  }
  if (!config.requireConsent) {
    return { enabled: true as const, consented: true };
  }
  await recordRawMediaConsent(sessionId);
  return { enabled: true as const, consented: true };
}
