import { runtimeConfig } from "../config/runtime.js";
import type { ReportNarrativeInput } from "./reportNarrativeService.js";
import type { ReportDimensionScores } from "./reportScoringService.js";

export const REPORT_NARRATIVE_SYSTEM_PROMPT = [
  "你是儿童教育训练报告分析师，仅根据结构化训练指标撰写「深度解读」与「教育干预建议」。",
  "必须只输出合法 JSON，格式为：",
  '{"analysis":"...","recommendations":["...","...","..."]}',
  "要求：",
  "1. analysis 为 80-260 字中文，解读本次训练趋势、相对薄弱维度与注意力/情绪信号，不得改写或质疑定量分数；",
  "2. recommendations 恰好 3 条，每条为可执行的家庭/课堂训练建议；",
  "3. 若 limitations 非空，须在 analysis 中承认数据降级（如注意力 mock、情绪启发式、语音降级），建议中应包含复核环境与设备；",
  "4. 禁止医学诊断、治疗、临床结论、同龄百分位/常模比较；",
  "5. 语气专业但温和，面向教师与家长，强调「教育训练参考」。"
].join("\n");

export interface ReportNarrativeLlmOutput {
  analysis: string;
  recommendations: string[];
}

export interface ReportNarrativeLlmProvider {
  providerId: string;
  modelId: string;
  generate(input: ReportNarrativeInput): Promise<ReportNarrativeLlmOutput>;
}

type MockScenario = "success" | "unsafe" | "failure";

export class MockReportNarrativeLlmProvider implements ReportNarrativeLlmProvider {
  providerId = "mock-report-narrative";
  modelId = "mock-report-narrative-v1";

  constructor(private scenario: MockScenario = "success") {}

  async generate(input: ReportNarrativeInput): Promise<ReportNarrativeLlmOutput> {
    if (this.scenario === "failure") {
      throw new Error("Mock report narrative provider failure");
    }

    const weakest = findWeakestDimension(input.dimensions);
    const accuracyPct = Math.round(input.accuracy * 100);
    const focusPct =
      input.emotionSummary.status === "AVAILABLE"
        ? Math.round((input.emotionSummary.focusedRatio ?? 0) * 100)
        : null;

    if (this.scenario === "unsafe") {
      return {
        analysis: "该儿童存在临床诊断级别的注意力障碍，超过同龄百分位。",
        recommendations: ["建议立即接受治疗。", "需要医学诊断确认。", "应进行临床评估。"]
      };
    }

    const limitationNote =
      input.limitations.length > 0
        ? `部分指标为降级数据（${input.limitations.slice(0, 2).join("、")}），解读时需谨慎。`
        : "各通道数据质量可接受。";

    const attentionNote =
      input.attentionDipQuestions.length > 0
        ? `注意力在 ${input.attentionDipQuestions.slice(0, 2).join("、")} 附近出现波动。`
        : "注意力曲线整体较平稳。";

    const emotionNote =
      focusPct === null
        ? "情绪数据不足，仅保留答题与行为指标。"
        : `情绪通道显示专注占比约 ${focusPct}%。`;

    return {
      analysis: [
        `本次完成 ${input.totalQuestions} 题，首答正确率 ${accuracyPct}%，平均响应约 ${Math.round(input.averageResponseTimeMs)} ms。`,
        attentionNote,
        emotionNote,
        `相对薄弱维度为「${weakest.label}」（${weakest.value} 分）。`,
        limitationNote,
        "以下解读仅供教育训练参考。"
      ].join(""),
      recommendations: [
        `围绕「${weakest.label}」设计 5-10 分钟短时练习块，每周固定 2-3 次并记录首答正确率变化。`,
        input.wrongAttempts > 0
          ? `本次共 ${input.wrongAttempts} 次错误尝试，建议在易错题前增加分解步骤预演，降低挫败感。`
          : "当前答题节奏稳定，可逐步增加题目难度并保持单任务专注。",
        input.limitations.length > 0
          ? "数据存在降级项，建议先复核摄像头、麦克风与网络，再对比下一轮同课程趋势。"
          : "建议固定时段复训，并对比同课程类型的注意力曲线与正确率变化。"
      ]
    };
  }
}

interface OpenAiCompatibleReportConfig {
  providerId: string;
  apiKey: string;
  baseUrl: string;
  modelId: string;
}

class OpenAiCompatibleReportNarrativeLlmProvider implements ReportNarrativeLlmProvider {
  providerId: string;
  modelId: string;

  constructor(private config: OpenAiCompatibleReportConfig) {
    this.providerId = config.providerId;
    this.modelId = config.modelId;
  }

  async generate(input: ReportNarrativeInput): Promise<ReportNarrativeLlmOutput> {
    if (!this.config.apiKey) {
      throw new Error(`${this.config.providerId} API key 未配置`);
    }

    const userPayload = buildStructuredPayload(input);
    const response = await fetch(`${this.config.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.config.apiKey}`
      },
      body: JSON.stringify({
        model: this.config.modelId,
        temperature: 0.4,
        max_tokens: 900,
        response_format: { type: "json_object" },
        messages: [
          { role: "system", content: REPORT_NARRATIVE_SYSTEM_PROMPT },
          { role: "user", content: userPayload }
        ]
      })
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(
        `${this.config.providerId} report narrative 请求失败: ${response.status} ${text.slice(0, 200)}`
      );
    }

    const payload = (await response.json()) as {
      choices?: Array<{ message?: { content?: string } }>;
    };
    const content = payload.choices?.[0]?.message?.content?.trim();
    if (!content) {
      throw new Error(`${this.config.providerId} report narrative 返回为空`);
    }

    return JSON.parse(content) as ReportNarrativeLlmOutput;
  }
}

export class OpenAiReportNarrativeLlmProvider extends OpenAiCompatibleReportNarrativeLlmProvider {
  constructor() {
    super({
      providerId: "openai",
      apiKey: runtimeConfig.openAiApiKey ?? "",
      baseUrl: runtimeConfig.openAiBaseUrl ?? "https://api.openai.com/v1",
      modelId: runtimeConfig.openAiReportModel ?? "gpt-4o-mini"
    });
  }
}

export class DeepSeekReportNarrativeLlmProvider extends OpenAiCompatibleReportNarrativeLlmProvider {
  constructor() {
    super({
      providerId: "deepseek",
      apiKey: runtimeConfig.deepSeekApiKey ?? "",
      baseUrl: runtimeConfig.deepSeekBaseUrl ?? "https://api.deepseek.com/v1",
      modelId: runtimeConfig.deepSeekReportModel ?? "deepseek-chat"
    });
  }
}

export function buildStructuredPayload(input: ReportNarrativeInput) {
  return JSON.stringify({
    totalQuestions: input.totalQuestions,
    accuracy: input.accuracy,
    averageResponseTimeMs: input.averageResponseTimeMs,
    dimensions: input.dimensions,
    emotionSummary: {
      status: input.emotionSummary.status,
      positiveRatio: input.emotionSummary.positiveRatio,
      focusedRatio: input.emotionSummary.focusedRatio,
      frustratedRatio: input.emotionSummary.frustratedRatio
    },
    attentionDipQuestions: input.attentionDipQuestions,
    wrongAttempts: input.wrongAttempts,
    limitations: input.limitations
  });
}

export function resolveReportNarrativeLlmProvider(): ReportNarrativeLlmProvider | null {
  const kind = runtimeConfig.reportNarrativeProvider;
  if (kind === "rule") return null;
  if (kind === "openai") {
    if (!runtimeConfig.openAiApiKey) return null;
    return new OpenAiReportNarrativeLlmProvider();
  }
  if (kind === "deepseek") {
    if (!runtimeConfig.deepSeekApiKey) return null;
    return new DeepSeekReportNarrativeLlmProvider();
  }
  return new MockReportNarrativeLlmProvider();
}

export function usesAsyncReportNarrativeProvider() {
  const kind = runtimeConfig.reportNarrativeProvider;
  if (kind === "openai") return Boolean(runtimeConfig.openAiApiKey);
  if (kind === "deepseek") return Boolean(runtimeConfig.deepSeekApiKey);
  return false;
}

function findWeakestDimension(dimensions: ReportDimensionScores) {
  const entries: Array<{ key: keyof ReportDimensionScores; label: string; value: number }> = [
    { key: "ordering", label: "排序", value: dimensions.ordering },
    { key: "matching", label: "配对", value: dimensions.matching },
    { key: "receptiveLanguage", label: "接受性语言", value: dimensions.receptiveLanguage },
    { key: "attention", label: "注意力", value: dimensions.attention },
    { key: "expressiveLanguage", label: "表达性语言", value: dimensions.expressiveLanguage }
  ];
  const measured = entries.filter((entry) => entry.key !== "overallScore");
  measured.sort((left, right) => left.value - right.value);
  return measured[0] ?? { key: "receptiveLanguage", label: "接受性语言", value: dimensions.receptiveLanguage };
}
