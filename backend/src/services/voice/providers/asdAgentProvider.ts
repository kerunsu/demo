import type {
  LlmProvider,
  LlmReplyCandidate,
  ProviderMetadata,
  ProviderResult,
  SafeConversationContext
} from "child-education-training-demo/shared/providers";
import { runtimeConfig } from "../../../config/runtime.js";
import type { ChatMessageContext, ChatProvider, ChatReply } from "../types.js";

const SYSTEM_PROMPT = `你是面向孤独症儿童课程训练的中文对话机器人，名字叫“麦麦”。

你的目标：
1. 像温和、稳定、可预测的玩伴一样陪儿童训练。
2. 把话题固定在当前课程、当前题目、屏幕图片和机器人麦麦身上。
3. 如果儿童跑题，先肯定一句，再自然拉回当前题目。
4. 不做开放闲聊，不回答百科、娱乐、新闻、成人话题。
5. 不替代医生、治疗师或家长，不做诊断。

表达规则：
1. 每次回复 1 到 2 句，适合直接朗读。
2. 每一句都不能超过 12 个汉字。
3. 尽量短，只说重点。
4. 语气要有感情，温柔、鼓励、亲近。
5. 使用短句、具体、正向、可预测的表达。
6. 鼓励语要短，例如“真棒”“很好”。
7. 不使用责备、否定、威胁、讽刺、复杂抽象表达。
8. 不说“你错了”，改说“我们再试一次”。
9. 不使用“但是”“不过”等强转折词。
10. 不使用“你必须”“你应该”等命令式语气。
11. 如出现自伤、伤人、走失、严重痛苦等风险，提示马上找家长或老师。
12. 不使用“目标图”“选项”“页面上下文”“训练目标”“三角体”“立方体”“几何体”等专业词。
13. 面向孩子说话，要说“上面的图片”“下面的图片”“左边这张”“右边这张”。
14. 不说“观察目标图”，改说“看看上面的图片”。
15. 不说“选择正确选项”，改说“点这一张”。
16. 说形状时用孩子能懂的话：尖尖的、方方的、圆圆的、三角形的。
17. 不说“和积木做朋友”“真有趣”“有模有样”“你看见了吗”。
18. 不反问孩子，不说“你找找哪一张呀”。
19. 孩子问“是什么”时，只答“这是X。”。
20. 除非孩子问颜色，不主动描述颜色和细节。

课程约束：
1. 当前页面上下文比普通聊天历史更重要。
2. 回答必须服务于当前课程训练。
3. 儿童问页面相关问题时，必须先直接回答问题。
4. 需要鼓励时，只说“真棒”或“很好”。
5. 不要只说“你在认真尝试”。
6. 儿童问“你是谁”时，可以介绍“我是麦麦”，随后邀请儿童回到当前题目。
7. 儿童问课程无关问题时，不展开回答，只温和拉回屏幕上的图片。
8. 优先引导儿童看上面的图片、看下面的图片、尝试点击或继续表达。

分层辅助规则：
1. 如果上下文里的“辅助层级”是 LEVEL_1_OBSERVE：只提示看颜色、形状、图案，不直接说答案。
2. 如果是 LEVEL_2_DESCRIBE：只说名称和位置，不展开细节。
3. 如果是 LEVEL_3_DIRECT：可以直接告诉正确答案，并邀请儿童点击。
4. 当上下文提供了“正确答案”时，你必须使用它，不要猜。
5. 当上下文提供了选项顺序时，你必须按从左到右的顺序描述。
6. 不要每次重复同一句泛化话术；儿童多次表示不会时，回复要越来越具体。`;

export const ASD_AGENT_METADATA: ProviderMetadata & { providerKind: "llm" } = {
  providerKind: "llm",
  providerName: "ASD child conversation agent",
  providerId: "asd-agent-llm",
  providerType: "cloud",
  mode: "external",
  version: "expert-annotator-asd-main",
  vendorModelName: runtimeConfig.asdLlmModel,
  humanReview: "HUMAN_REVIEW_PENDING",
  licenseReview: "REQUIRED_BEFORE_PRODUCTION",
  dataSafety: {
    externalNetworkCalled: true,
    inputPersisted: false,
    rawAudioPersisted: false,
    sensitiveTextLogged: false,
    credentialsSource: "environment",
    allowedData: ["redacted_text", "developer_authorized"],
    notes: "Uses the ExpertAnnotator ASD prompt and OpenAI-compatible chat completions endpoint."
  },
  fallback: {
    fallbackProviderIds: ["rule"],
    fallbackMode: "rule_reply"
  }
};

type CompletionMessage = {
  role: "system" | "user" | "assistant";
  content: string;
};

async function requestAsdCompletion(messages: CompletionMessage[], maxTokens: number): Promise<string> {
  if (!runtimeConfig.asdLlmApiKey) {
    throw new Error("ASD_LLM_API_KEY/LLM_API_KEY is not configured.");
  }

  const baseUrl = (runtimeConfig.asdLlmBaseUrl ?? "https://api.deepseek.com").replace(/\/+$/, "");
  const response = await fetch(`${baseUrl}/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${runtimeConfig.asdLlmApiKey}`
    },
    body: JSON.stringify({
      model: runtimeConfig.asdLlmModel,
      messages,
      temperature: 0.32,
      max_tokens: maxTokens
    }),
    signal: AbortSignal.timeout(runtimeConfig.asdLlmTimeoutMs)
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`ASD LLM request failed: ${response.status} ${text}`);
  }

  const payload = (await response.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
  };
  const content = payload.choices?.[0]?.message?.content?.trim();
  if (!content) {
    throw new Error("ASD LLM returned an empty reply.");
  }
  return content;
}

function mapHistory(history: ChatMessageContext[]) {
  return history.slice(-runtimeConfig.asdMaxHistoryMessages).map((item) => ({
    role: item.role === "assistant" ? ("assistant" as const) : ("user" as const),
    content: item.text
  }));
}

function contextMessage(pageContextText?: string): CompletionMessage[] {
  if (!pageContextText) {
    return [
      {
        role: "system",
      content: "当前没有可靠课程上下文。只说一句短话，请孩子看屏幕。每句不超过12字。"
      }
    ];
  }
  return [
    {
      role: "system",
      content: `当前课程页面上下文如下，只给你理解页面用。回复孩子时不能照抄字段名。儿童问颜色、图形、位置、第几张、怎么玩时，先直接回答。每次最多2句，每句不超过12字。问“是什么”只答“这是X。”。不要主动描述颜色和细节。不要反问孩子。不要说“目标图”“选项”“训练目标”“页面上下文”“三角体”“立方体”“几何体”“做朋友”“真有趣”：\n${pageContextText}`
       }
  ];
}

export class AsdAgentChatProvider implements ChatProvider {
  name = "asd";

  async generateReply(input: { childText: string; history: ChatMessageContext[]; pageContextText?: string }): Promise<ChatReply> {
    const reply = await requestAsdCompletion(
      [
        { role: "system", content: SYSTEM_PROMPT },
        ...contextMessage(input.pageContextText),
        ...mapHistory(input.history),
        { role: "user", content: input.childText }
      ],
      90
    );

    return {
      reply,
      strategy: "asd_llm",
      provider: "asd-agent-llm",
      timestamp: new Date().toISOString()
    };
  }
}

export class AsdAgentLlmProvider implements LlmProvider {
  metadata = ASD_AGENT_METADATA;

  async generateReply(input: SafeConversationContext): Promise<ProviderResult<LlmReplyCandidate>> {
    const started = Date.now();
    try {
      const history = input.historyRedacted.slice(-runtimeConfig.asdMaxHistoryMessages).map((text, index) => ({
        role: index % 2 === 0 ? ("user" as const) : ("assistant" as const),
        content: text
      }));
      const replyDraft = await requestAsdCompletion(
        [
          { role: "system", content: SYSTEM_PROMPT },
          ...contextMessage(input.pageContextText),
          ...history,
          { role: "user", content: input.childTextRedacted }
        ],
        90
      );

      return {
        ok: true,
        metadata: this.metadata,
        latencyMs: Date.now() - started,
        data: {
          turnId: input.turnId,
          replyDraft,
          contextVersion: input.policyVersion
        },
        metrics: {
          processLatencyMs: Date.now() - started,
          gpuUsed: false,
          hardwareAcceleration: "none"
        }
      };
    } catch (error) {
      return {
        ok: false,
        metadata: this.metadata,
        latencyMs: Date.now() - started,
        error: {
          code: error instanceof DOMException && error.name === "TimeoutError" ? "TIMEOUT" : "PROVIDER_FAILURE",
          message: error instanceof Error ? error.message : "ASD LLM request failed.",
          retryable: true
        },
        fallbackText: "你愿意说真好。我们慢慢来。",
        metrics: {
          processLatencyMs: Date.now() - started,
          gpuUsed: false,
          hardwareAcceleration: "none"
        }
      };
    }
  }
}
