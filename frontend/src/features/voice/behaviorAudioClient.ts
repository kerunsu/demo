import type { BrowserAudioFeatureAck, BrowserTurnAudioFeatureDescriptor } from "child-education-training-demo/shared/behavior-frames";
import { FRONTEND_RUNTIME_CONFIG } from "../../config/runtime";
import type { BrowserTurnAudioFeatures } from "child-education-training-demo/shared/browser-audio-features";

function behaviorUrl(path: string) {
  return `${FRONTEND_RUNTIME_CONFIG.apiBaseUrl}${path}`;
}

async function parseApiResponse<T>(response: Response): Promise<T> {
  const body = (await response.json()) as { success: boolean; data: T; error?: { message: string } };
  if (!response.ok || !body.success) {
    throw new Error(body.error?.message ?? `Audio feature request failed with ${response.status}`);
  }
  return body.data;
}

export async function sendBrowserAudioFeatures(input: {
  sessionId: string;
  turnId: string;
  correlationId: string;
  questionId?: string;
  observedAt: string;
  audioDurationMs: number;
  features: BrowserTurnAudioFeatures;
}): Promise<BrowserAudioFeatureAck> {
  const payload: BrowserTurnAudioFeatureDescriptor = {
    schemaVersion: "m5-audio-features-v1",
    sessionId: input.sessionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    questionId: input.questionId,
    observedAt: input.observedAt,
    audioDurationMs: input.audioDurationMs,
    provider: "browser-web-audio",
    features: {
      loudnessRms: input.features.loudnessRms,
      loudnessDb: input.features.loudnessDb,
      speechRatio: input.features.speechRatio,
      clarityProxy: input.features.clarityProxy,
      sampleCount: input.features.sampleCount,
      algorithmVersion: input.features.algorithmVersion,
      degraded: input.features.degraded
    }
  };
  const response = await fetch(behaviorUrl(`/behavior/${input.sessionId}/voice-turns/${input.turnId}/audio-features`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload)
  });
  return parseApiResponse<BrowserAudioFeatureAck>(response);
}
