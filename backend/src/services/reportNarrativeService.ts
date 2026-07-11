import { z } from "zod";
import { reviewReportNarrativeOutput } from "./llmSafetyGatewayService.js";
import type { EmotionSummaryResult } from "./emotionAggregationService.js";
import type { ReportDimensionScores } from "./reportScoringService.js";
import {
  type ReportNarrativeLlmProvider,
  resolveReportNarrativeLlmProvider
} from "./reportNarrativeLlmProvider.js";

export const REPORT_NARRATIVE_PROMPT_VERSION = "report-narrative-prompt-v2";

export interface ReportNarrativeInput {
  sessionId: string;
  totalQuestions: number;
  accuracy: number;
  averageResponseTimeMs: number;
  dimensions: ReportDimensionScores;
  emotionSummary: EmotionSummaryResult;
  attentionDipQuestions: string[];
  wrongAttempts: number;
  limitations: string[];
}

export type ReportNarrativeGenerator = "mock_llm" | "rule_fallback" | "openai" | "deepseek" | "pending";
export type ReportNarrativeStatus = "PENDING" | "READY" | "FAILED";

export interface ReportNarrativeResult {
  status: ReportNarrativeStatus;
  analysis: string;
  recommendations: string[];
  safetyReviewStatus: "PASS" | "REJECT";
  generator: ReportNarrativeGenerator;
  provider?: string;
  model?: string;
  promptTemplateVersion: string;
}

export function buildPendingReportNarrative(): ReportNarrativeResult {
  return {
    status: "PENDING",
    analysis: "",
    recommendations: [],
    safetyReviewStatus: "PASS",
    generator: "pending",
    provider: "report-narrative-queue",
    model: "pending",
    promptTemplateVersion: REPORT_NARRATIVE_PROMPT_VERSION
  };
}

const narrativeLlmOutputSchema = z.object({
  analysis: z.string().min(20).max(2000),
  recommendations: z.array(z.string().min(8).max(500)).min(3).max(5)
});

export interface GenerateReportNarrativeOptions {
  providerOverride?: ReportNarrativeLlmProvider | null;
}

export async function generateReportNarrative(
  input: ReportNarrativeInput,
  options?: GenerateReportNarrativeOptions
): Promise<ReportNarrativeResult> {
  const provider =
    options && "providerOverride" in options ? options.providerOverride : resolveReportNarrativeLlmProvider();

  if (!provider) {
    return buildRuleFallbackNarrative(input);
  }

  try {
    const llmOutput = await provider.generate(input);
    const parsed = narrativeLlmOutputSchema.safeParse(llmOutput);
    if (!parsed.success) {
      return buildRuleFallbackNarrative(input);
    }

    const safety = await reviewReportNarrativeOutput({
      sessionId: input.sessionId,
      analysis: parsed.data.analysis,
      recommendations: parsed.data.recommendations.slice(0, 3)
    });

    if (safety.status !== "PASS") {
      return buildRuleFallbackNarrative(input);
    }

    const analysis = sanitizeNarrativeText(parsed.data.analysis);
    const recommendations = parsed.data.recommendations.slice(0, 3).map(sanitizeNarrativeText);

    return {
      analysis: finalizeAnalysisText(analysis, input),
      recommendations,
      safetyReviewStatus: "PASS",
      status: "READY",
      generator: mapProviderToGenerator(provider.providerId),
      provider: provider.providerId,
      model: provider.modelId,
      promptTemplateVersion: REPORT_NARRATIVE_PROMPT_VERSION
    };
  } catch {
    return buildRuleFallbackNarrative(input);
  }
}

export function buildRuleFallbackNarrative(input: ReportNarrativeInput): ReportNarrativeResult {
  const weakest = findWeakestDimension(input.dimensions);
  const attentionNote =
    input.attentionDipQuestions.length > 0
      ? `注意力曲线在 ${input.attentionDipQuestions.slice(0, 3).join("、")} 附近出现波动。`
      : "注意力曲线整体较平稳。";
  const emotionNote =
    input.emotionSummary.status === "AVAILABLE"
      ? input.emotionSummary.provider?.includes("heuristic")
        ? `情绪启发式显示专注占比约 ${Math.round((input.emotionSummary.focusedRatio ?? 0) * 100)}%（非独立模型）。`
        : `表情情绪分析显示专注占比约 ${Math.round((input.emotionSummary.focusedRatio ?? 0) * 100)}%。`
      : "情绪识别数据不足，报告仅保留教育训练参考指标。";

  return {
    analysis: sanitizeNarrativeText(
      `本次报告基于结构化训练结果生成。首答正确率 ${(input.accuracy * 100).toFixed(0)}%，共出现 ${input.wrongAttempts} 次错误尝试。${attentionNote}${emotionNote} 当前相对薄弱维度为「${weakest.label}」。该结论仅供教育训练参考，不代表医学诊断。`
    ),
    recommendations: buildRecommendations(input),
    safetyReviewStatus: "PASS",
    status: "READY",
    generator: "rule_fallback",
    provider: "rule-narrative",
    model: "education-training-narrative-v1",
    promptTemplateVersion: REPORT_NARRATIVE_PROMPT_VERSION
  };
}

function finalizeAnalysisText(analysis: string, input: ReportNarrativeInput) {
  const disclaimer = "该分析仅作教育训练参考，不代表医学诊断或常模结论。";
  if (analysis.includes("教育训练参考")) {
    return sanitizeNarrativeText(analysis);
  }
  return sanitizeNarrativeText(
    `根据本次 ${input.totalQuestions} 道题的结构化训练数据，首答正确率为 ${(input.accuracy * 100).toFixed(0)}%。${analysis} ${disclaimer}`
  );
}

function buildRecommendations(input: ReportNarrativeInput): string[] {
  const weakest = findWeakestDimension(input.dimensions);
  const recommendations = [
    weakest.key === "ordering"
      ? "日常可增加多指令排序小游戏，通过生活化指令提升序列记忆和执行能力。"
      : weakest.key === "matching"
        ? "可通过配对找相同/找不同的小练习，逐步提升视觉辨别稳定性。"
        : weakest.key === "attention"
          ? "建议采用短时、单任务训练块，并在噪杂环境中逐步延长专注时长。"
          : weakest.key === "expressiveLanguage"
            ? "鼓励孩子用简短完整句描述选择理由，并在语音识别质量不足时优先复核设备与环境。"
            : "可结合图片指令与口头复述，巩固接受性语言理解。",
    input.wrongAttempts > 0
      ? "在错题高发题目前增加预演与分解步骤，减少挫败感并提升连贯执行。"
      : "保持当前节奏，继续观察多轮训练后的稳定性变化。",
    input.limitations.length > 0
      ? "当注意力、语音或情绪数据为降级状态时，先复核摄像头、麦克风与现场网络，再解释趋势。"
      : "建议每周固定时段复训，并对比同课程类型的趋势变化。"
  ];
  return recommendations.slice(0, 3);
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

function mapProviderToGenerator(providerId: string): ReportNarrativeGenerator {
  if (providerId.startsWith("mock")) return "mock_llm";
  if (providerId === "deepseek") return "deepseek";
  return "openai";
}

function sanitizeNarrativeText(text: string) {
  return text.replace(/diagnosis|percentile|clinical|治疗|诊断|百分位|医学诊断/giu, "教育训练参考");
}
