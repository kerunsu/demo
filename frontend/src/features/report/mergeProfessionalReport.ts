import type { ProfessionalReportV2, TrainingReport } from "../../types";

function clamp(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function weightedAverage(values: number[], weights: number[]) {
  const totalWeight = weights.reduce((sum, weight) => sum + weight, 0);
  if (totalWeight <= 0) return 0;
  return clamp(values.reduce((sum, value, index) => sum + value * weights[index], 0) / totalWeight);
}

export function mergeProfessionalReportV2(reports: TrainingReport[]): ProfessionalReportV2 | undefined {
  const items = reports.map((report) => report.professionalReportV2).filter((item): item is ProfessionalReportV2 => Boolean(item));
  if (items.length === 0) return undefined;
  if (items.length === 1) return items[0];

  const weights = reports.map((report) => Math.max(1, report.summary.totalQuestions));
  const totalQuestions = weights.reduce((sum, weight) => sum + weight, 0);
  const accuracy = reports.reduce((sum, report) => sum + report.summary.accuracy * report.summary.totalQuestions, 0) / totalQuestions;
  const avgResponse =
    reports.reduce((sum, report) => sum + report.summary.averageResponseTimeMs * report.summary.totalQuestions, 0) / totalQuestions;

  const dimensions = {
    ordering: weightedAverage(
      items.map((item) => item.dimensions.ordering),
      weights
    ),
    matching: weightedAverage(
      items.map((item) => item.dimensions.matching),
      weights
    ),
    receptiveLanguage: weightedAverage(
      items.map((item) => item.dimensions.receptiveLanguage),
      weights
    ),
    attention: weightedAverage(
      items.map((item) => item.dimensions.attention),
      weights
    ),
    expressiveLanguage: weightedAverage(
      items.map((item) => item.dimensions.expressiveLanguage),
      weights
    )
  };

  const overallScore = clamp(
    0.15 * dimensions.ordering +
      0.15 * dimensions.matching +
      0.2 * dimensions.receptiveLanguage +
      0.25 * dimensions.attention +
      0.25 * dimensions.expressiveLanguage
  );

  const availableEmotions = items.filter((item) => item.emotionSummary.status === "AVAILABLE");
  const emotionSummary =
    availableEmotions.length > 0
      ? {
          status: "AVAILABLE" as const,
          positiveRatio: average(availableEmotions.map((item) => item.emotionSummary.positiveRatio ?? 0)),
          focusedRatio: average(availableEmotions.map((item) => item.emotionSummary.focusedRatio ?? 0)),
          frustratedRatio: average(availableEmotions.map((item) => item.emotionSummary.frustratedRatio ?? 0)),
          provider: "mixed-course-emotion-merge-v1",
          algorithmVersion: "mixed-course-emotion-merge-v1"
        }
      : {
          status: "DEGRADED" as const,
          reason: "MANUAL_ACCEPTANCE_REQUIRED" as const
        };

  const attentionCurve = items.flatMap((item) => item.attentionCurve);
  const limitations = Array.from(new Set(items.flatMap((item) => item.dataQuality.limitations).concat(["MIXED_REPORT_MERGED_V2"])));
  const recommendations = Array.from(new Set(items.flatMap((item) => item.narrative.recommendations))).slice(0, 3);
  const analysis = items
    .map((item) => item.narrative.analysis)
    .filter(Boolean)
    .join(" ");
  const narrativePending = items.some((item) => item.narrative.status === "PENDING");

  return {
    schemaVersion: "professional-report-v2",
    formulaVersion: "education-training-index-v1",
    scoreBoundary: "education_training_reference_only",
    overallScore,
    dimensions,
    taskAccuracy: accuracy,
    averageResponseTimeMs: avgResponse,
    emotionSummary,
    attentionCurve,
    narrative: {
      status: narrativePending ? "PENDING" : "READY",
      analysis: narrativePending ? "" : analysis || "多课程训练报告已按题量加权合并，仅供教育训练参考。",
      recommendations: narrativePending ? [] : recommendations.length > 0 ? recommendations : items[0].narrative.recommendations,
      safetyReviewStatus: "PASS",
      generator: narrativePending
        ? "pending"
        : items.every((item) => item.narrative.generator === "mock_llm")
        ? "mock_llm"
        : items.every((item) => item.narrative.generator === "openai")
          ? "openai"
          : items.every((item) => item.narrative.generator === "deepseek")
            ? "deepseek"
            : "rule_fallback",
      provider: "mixed-course-report-merge-v1",
      model: "mixed-course-report-merge-v1",
      promptTemplateVersion: items[0].versions.narrativePromptVersion
    },
    dataQuality: {
      status: items.some((item) => item.dataQuality.degraded) ? "partial" : "complete",
      limitations,
      providerSummary: items.reduce<Record<string, number>>((acc, item) => {
        for (const [provider, count] of Object.entries(item.dataQuality.providerSummary)) {
          acc[provider] = (acc[provider] ?? 0) + count;
        }
        return acc;
      }, {}),
      degraded: limitations.length > 0
    },
    versions: {
      assessmentMetricVersion: "mixed-course-merge-v1",
      reportExplanationPolicyVersion: items[0].versions.reportExplanationPolicyVersion,
      emotionAlgorithmVersion: emotionSummary.algorithmVersion,
      narrativePromptVersion: items[0].versions.narrativePromptVersion
    }
  };
}

function average(values: number[]) {
  if (values.length === 0) return 0;
  return Math.round((values.reduce((sum, value) => sum + value, 0) / values.length) * 1000) / 1000;
}
