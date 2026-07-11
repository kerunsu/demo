import { runtimeConfig } from "../../../config/runtime.js";
import type { TtsProvider, TtsSynthesis } from "../types.js";

export class OpenAiTtsProvider implements TtsProvider {
  name = "openai";

  async synthesize(input: { text: string }): Promise<TtsSynthesis | null> {
    if (!runtimeConfig.openAiApiKey) {
      throw new Error("OPENAI_API_KEY 未配置");
    }
    if (!input.text.trim()) return null;

    const response = await fetch(`${runtimeConfig.openAiBaseUrl}/audio/speech`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${runtimeConfig.openAiApiKey}`
      },
      body: JSON.stringify({
        model: runtimeConfig.openAiTtsModel,
        voice: runtimeConfig.openAiTtsVoice,
        input: input.text,
        format: "mp3"
      })
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`OpenAI TTS 请求失败: ${response.status} ${text}`);
    }

    const arrayBuffer = await response.arrayBuffer();
    const base64 = Buffer.from(arrayBuffer).toString("base64");
    return {
      audioBase64: base64,
      mimeType: "audio/mpeg"
    };
  }
}
