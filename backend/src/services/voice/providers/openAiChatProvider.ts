                                                import { runtimeConfig } from "../../../config/runtime.js";
import type { ChatProvider, ChatReply } from "../types.js";

export class OpenAiChatProvider implements ChatProvider {
  name = "openai";

  async generateReply(input: { childText: string; history: Array<{ role: string; text: string }> }): Promise<ChatReply> {
    if (!runtimeConfig.openAiApiKey) {
      throw new Error("OPENAI_API_KEY 未配置");
    }

    const systemPrompt =
      "你是儿童互动训练助手。页面相关问题要先回答。每次最多2句，每句不超过12字。问是什么只答这是X。不要反问孩子。不要说目标图、选项、训练目标、三角体、立方体、几何体、做朋友、真有趣。";
    const messages = [
      { role: "system", content: systemPrompt },
      ...input.history.slice(-8).map((item) => ({
        role: item.role === "assistant" ? "assistant" : "user",
        content: item.text
      })),
      { role: "user", content: input.childText }
    ];

    const response = await fetch(`${runtimeConfig.openAiBaseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${runtimeConfig.openAiApiKey}`
      },
      body: JSON.stringify({
        model: runtimeConfig.openAiChatModel,
        temperature: 0.6,
        max_tokens: 80,
        messages
      })
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`OpenAI Chat 请求失败: ${response.status} ${text}`);
    }

    const payload = (await response.json()) as {
      choices?: Array<{ message?: { content?: string } }>;
    };
    const content = payload.choices?.[0]?.message?.content?.trim();
    if (!content) {
      throw new Error("OpenAI Chat 返回为空");
    }

    return {
      reply: content,
      strategy: "llm",
      provider: "openai",
      timestamp: new Date().toISOString()
    };
  }
}
