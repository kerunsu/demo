import type { ExpandedAssessmentReport, TrainingReport } from "../types.js";
import type { DeterministicAssessmentResult } from "child-education-training-demo/shared/assessments";
import {
  computeAcousticExpressiveScore,
  EXPRESSIVE_ACOUSTIC_WEIGHT,
  EXPRESSIVE_TEXT_WEIGHT,
  hasAcousticLanguageSignals
} from "./audioFeatureScoringUtils.js";
import { isQuestionVideoCaptured, type QuestionVideoCaptureStatus } from "./questionVideoCaptureUtils.js";
import { getVoiceMetricsForSession } from "./voiceObservabilityService.js";

export const FORMULA_VERSION = "education-training-index-v1";
export const RESPONSE_TIME_LOWER_BETTER_MS = 1200;
export const RESPONSE_TIME_UPPER_PENALTY_MS = 8000;
export const RESPONSE_TIME_THRESHOLD_PENDING = "PENDING_CONFIRMATION:RESPONSE_TIME_THRESHOLDS";

export interface ReportScoringInput {
  courseType: TrainingReport["courseType"];
  totalQuestions: number;
  accuracy: number;
  averageResponseTimeMs: number;
  expandedReport: ExpandedAssessmentReport;
  assessment: DeterministicAssessmentResult;
  sessionId: string;
  questionAttention: Array<{
    questionId: string;
    score?: number;
    quality: string;
  }>;
  questionVideoCapture?: Map<string, QuestionVideoCaptureStatus>;
  rawMediaManifestAvailable?: boolean;
}

export interface ReportDimensionScores {
  ordering: number;
  matching: number;
  receptiveLanguage: number;
  attention: number;
  expressiveLanguage: number;
  overallScore: number;
}

export function computeReportDimensions(input: ReportScoringInput): ReportDimensionScores {
  const accuracyScore = clamp(input.accuracy * 100);
  const responseScore = responseTimeScore(input.averageResponseTimeMs);
  const attentionQualityCoefficient = input.expandedReport.attentionMetrics.qualityStatus === "complete" ? 1 : 0.7;

  const attentionItems = input.questionAttention.filter(
    (item) =>
      typeof item.score === "number" &&
      isAttentionPointEligibleForScoring(item.questionId, item.quality, input)
  );
  const attentionScore =
    attentionItems.length > 0
      ? clamp(
          (attentionItems.reduce((sum, item) => sum + (item.score ?? 0), 0) / attentionItems.length) *
            attentionQualityCoefficient
        )
      : input.expandedReport.attentionMetrics.status === "available" &&
          typeof input.expandedReport.attentionMetrics.screenOrientedRatio === "number"
        ? clamp(input.expandedReport.attentionMetrics.screenOrientedRatio * 100 * attentionQualityCoefficient)
        : 0;

  const expressiveLanguage = computeExpressiveLanguageScore(input);
  const ordering = computeCourseDimensionScore(input, "ordering", accuracyScore, responseScore);
  const matching = computeCourseDimensionScore(input, "matching", accuracyScore, responseScore);
  const receptiveLanguage = weightedScore(accuracyScore, responseScore, 0.45);
  const overallScore = clamp(
    0.15 * ordering + 0.15 * matching + 0.2 * receptiveLanguage + 0.25 * attentionScore + 0.25 * expressiveLanguage
  );

  return { ordering, matching, receptiveLanguage, attention: attentionScore, expressiveLanguage, overallScore };
}

export function buildQuestionAttentionCurve(input: ReportScoringInput) {
  return input.expandedReport.answerMetrics.questionMetrics.flatMap((metric) => {
    const attention = input.questionAttention.find((item) => item.questionId === metric.questionId);
    const quality = attention?.quality ?? metric.dataQualityStatus;
    if (!isAttentionPointEligibleForScoring(metric.questionId, quality, input)) {
      return [];
    }
    return [
      {
        questionId: metric.questionId,
        score: attention?.score,
        quality
      }
    ];
  });
}

function isAttentionPointEligibleForScoring(
  questionId: string,
  quality: string,
  input: ReportScoringInput
) {
  if (quality === "excluded_no_video") return false;
  const video = input.questionVideoCapture?.get(questionId);
  return isQuestionVideoCaptured(video, input.rawMediaManifestAvailable ?? false);
}

export function collectScoringLimitations(input: ReportScoringInput): string[] {
  const limitations = new Set<string>([
    ...input.expandedReport.dataQuality.limitations,
    RESPONSE_TIME_THRESHOLD_PENDING
  ]);
  if (input.expandedReport.attentionMetrics.status === "unavailable") {
    limitations.add("ATTENTION_PROVIDER_DEGRADED_OR_MISSING");
  }
  if (input.expandedReport.languageMetrics.status === "unavailable") {
    limitations.add("LANGUAGE_FEATURES_DEGRADED_OR_MISSING");
  }
  if (input.expandedReport.languageMetrics.audioFeatureDegraded) {
    limitations.add("AUDIO_FEATURES_DEGRADED_OR_PARTIAL");
  }
  if (input.rawMediaManifestAvailable) {
    const excluded = input.expandedReport.answerMetrics.questionMetrics.filter(
      (metric) => !isAttentionPointEligibleForScoring(
        metric.questionId,
        input.questionAttention.find((item) => item.questionId === metric.questionId)?.quality ??
          metric.dataQualityStatus,
        input
      )
    );
    if (excluded.length > 0) {
      limitations.add("ATTENTION_CURVE_EXCLUDED_QUESTIONS_WITHOUT_VIDEO");
    }
  }
  return [...limitations];
}

function computeCourseDimensionScore(
  input: ReportScoringInput,
  target: "ordering" | "matching",
  fallbackAccuracy: number,
  fallbackResponse: number
) {
  const stats = input.assessment.questionMetrics.filter((metric) => inferQuestionCourseType(metric.questionId) === target);
  if (stats.length === 0) {
    if (input.courseType === target) return weightedScore(fallbackAccuracy, fallbackResponse, 0.65);
    if (input.courseType === "mixed") return 0;
    return 0;
  }
  const accuracy = ratio(stats.filter((metric) => metric.firstAttemptCorrect).length, stats.length) * 100;
  const responseTimes = stats
    .map((metric) => metric.responseTimeMs)
    .filter((value): value is number => typeof value === "number");
  const avgResponse = responseTimes.length > 0 ? responseTimes.reduce((a, b) => a + b, 0) / responseTimes.length : input.averageResponseTimeMs;
  return weightedScore(clamp(accuracy), responseTimeScore(avgResponse), 0.65);
}

function computeExpressiveLanguageScore(input: ReportScoringInput) {
  if (input.expandedReport.languageMetrics.status !== "available") return 0;
  const textScore = computeTextExpressiveLanguageScore(input);
  const lang = input.expandedReport.languageMetrics;
  if (!hasAcousticLanguageSignals(lang)) {
    return textScore;
  }
  const acousticScore = computeAcousticExpressiveScore(lang);
  return clamp(EXPRESSIVE_TEXT_WEIGHT * textScore + EXPRESSIVE_ACOUSTIC_WEIGHT * acousticScore);
}

function computeTextExpressiveLanguageScore(input: ReportScoringInput) {
  const lang = input.expandedReport.languageMetrics;
  const voiceMetrics = getVoiceMetricsForSession(input.sessionId);
  const sttSuccess = voiceMetrics.filter((metric) => metric.stage === "stt_complete" && metric.status === "success").length;
  const sttTotal = voiceMetrics.filter((metric) => metric.stage === "stt_complete").length;
  const sttPassRate = sttTotal > 0 ? sttSuccess / sttTotal : 0.5;
  const responseRate = ratio(lang.responseCount, Math.max(lang.responseCount + lang.emptyResponseCount, 1));
  const repeatPenalty = lang.repeatedResponseCount * 8;
  const emptyPenalty = lang.emptyResponseCount * 15;
  const transcriptBonus = typeof lang.averageTranscriptLength === "number" ? Math.min(20, lang.averageTranscriptLength * 2) : 0;
  return clamp(30 + responseRate * 25 + sttPassRate * 25 + transcriptBonus - repeatPenalty - emptyPenalty);
}

function inferQuestionCourseType(questionId: string): "matching" | "ordering" | "unknown" {
  if (questionId.startsWith("matching_")) return "matching";
  if (questionId.startsWith("ordering_")) return "ordering";
  return "unknown";
}

export function responseTimeScore(valueMs?: number) {
  if (!valueMs || valueMs <= 0) return 0;
  return clamp(100 - ((valueMs - RESPONSE_TIME_LOWER_BETTER_MS) / (RESPONSE_TIME_UPPER_PENALTY_MS - RESPONSE_TIME_LOWER_BETTER_MS)) * 100);
}

function weightedScore(left: number, right: number, leftWeight: number) {
  return clamp(leftWeight * left + (1 - leftWeight) * right);
}

function ratio(numerator: number, denominator: number) {
  return denominator <= 0 ? 0 : numerator / denominator;
}

function clamp(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}
