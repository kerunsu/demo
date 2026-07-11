import type { ProviderResult, TtsAudio } from "child-education-training-demo/shared/providers";
import { apiRequest } from "../../services/api";

export function requestRobotSpeech(input: {
  sessionId: string;
  turnId: string;
  correlationId: string;
  text: string;
  voice?: string;
}) {
  return apiRequest<ProviderResult<TtsAudio>>(`/voice-turns/${input.sessionId}/tts`, {
    method: "POST",
    body: JSON.stringify({
      turnId: input.turnId,
      correlationId: input.correlationId,
      text: input.text,
      voice: input.voice
    })
  });
}
