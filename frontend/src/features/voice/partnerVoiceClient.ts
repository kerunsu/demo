import type { VoiceTurnPageContextPayload } from "child-education-training-demo/shared/voice-partner-contract";
import type { ChatReply } from "../../types";
import { FRONTEND_RUNTIME_CONFIG } from "../../config/runtime";

function apiUrl(path: string) {
  return `${FRONTEND_RUNTIME_CONFIG.apiBaseUrl}${path}`;
}

async function parseApiResponse<T>(response: Response): Promise<T> {
  const body = (await response.json()) as { success: boolean; data: T; error?: { message: string } };
  if (!response.ok || !body.success) {
    throw new Error(body.error?.message ?? `Request failed with ${response.status}`);
  }
  return body.data;
}

export type VoiceDialogConfig = {
  dialogProvider: "rule" | "partner";
  voicePartnerConfigured: boolean;
};

export async function fetchVoiceDialogConfig(): Promise<VoiceDialogConfig> {
  const response = await fetch(apiUrl("/voice/providers"));
  const data = await parseApiResponse<{
    dialogProvider?: "rule" | "partner";
    voicePartnerConfigured?: boolean;
  }>(response);
  return {
    dialogProvider: data.dialogProvider ?? "rule",
    voicePartnerConfigured: Boolean(data.voicePartnerConfigured)
  };
}

export async function persistTranscriptObservations(
  sessionId: string,
  text: string,
  options: { turnId?: string; correlationId?: string } = {}
) {
  const response = await fetch(apiUrl(`/voice-partner/${sessionId}/transcript-observations`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text, ...options })
  });
  return parseApiResponse<{ persisted: boolean }>(response);
}

export async function sendPartnerVoiceTurn(
  sessionId: string,
  input: {
    streamId: string;
    turnId: string;
    correlationId: string;
    pageContext: VoiceTurnPageContextPayload;
    locale?: string;
    capturedAt?: string;
  }
) {
  const response = await fetch(apiUrl(`/voice-partner/${sessionId}/turn`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input)
  });
  return parseApiResponse<ChatReply>(response);
}
