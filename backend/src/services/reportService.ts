import { getSession as getStoredSession } from "./sessionLifecycleService.js";
import { generateAssessmentForSession } from "./assessmentService.js";
import { buildPerQuestionAttentionScores } from "./attentionScoreUtils.js";
import { finalizeSessionBehaviorBeforeReport } from "./behaviorTimelineOrchestratorService.js";
import { behaviorObservationRepository } from "./behaviorFrameIngressService.js";
import { aggregateSessionEmotion } from "./emotionAggregationService.js";
import { buildPerQuestionVideoCaptureStatus } from "./questionVideoCaptureUtils.js";
import { getSessionMediaManifest } from "./rawMediaPersistenceService.js";
import {
  buildQuestionAttentionCurve,
  collectScoringLimitations,
  computeReportDimensions,
  FORMULA_VERSION
} from "./reportScoringService.js";
import {
  buildPendingReportNarrative,
  buildRuleFallbackNarrative,
  generateReportNarrative,
  type ReportNarrativeInput,
  type ReportNarrativeResult
} from "./reportNarrativeService.js";
import { usesAsyncReportNarrativeProvider } from "./reportNarrativeLlmProvider.js";
import { loadPersistentReport, savePersistentReport } from "./sqlitePersistenceService.js";
import type { ExpandedAssessmentReport, TrainingReport } from "../types.js";
import type { DeterministicAssessmentResult } from "child-education-training-demo/shared/assessments";

const reports = new Map<string, TrainingReport>();
const narrativeJobs = new Map<string, Promise<void>>();

export function isReportNarrativePending(report: TrainingReport) {
  return report.professionalReportV2?.narrative?.status === "PENDING";
}

function createReportId() {
  return `rep_${Math.random().toString(36).slice(2, 10)}`;
}

export async function generateReport(sessionId: string) {
  const session = getStoredSession(sessionId);
  if (session.state !== "TRAINING_FINISHED" || !session.completedAt) {
    throw new Error("Course not completed yet");
  }

  const totalQuestions = session.questions.length;
  const firstTryCorrectCount = session.questionStats.filter((item) => item.attempts === 1).length;
  const avgResponseTime =
    session.responseTimes.length === 0
      ? 0
      : session.responseTimes.reduce((acc, value) => acc + value, 0) / session.responseTimes.length;

  const errorTypeCounter = new Map<string, number>();
  for (const stat of session.questionStats) {
    for (const errorType of stat.wrongTypes) {
      errorTypeCounter.set(errorType, (errorTypeCounter.get(errorType) ?? 0) + 1);
    }
  }

  const uniqueChildMessages = session.chatHistory
    .filter((entry) => entry.role === "child")
    .map((entry) => entry.text.trim())
    .filter((text) => text.length > 0);

  const keywords = Array.from(
    new Set(
      uniqueChildMessages
        .flatMap((message) => message.split(/\s+|，|。|！|？|,|\.|!|\?/g))
        .filter((token) => token.length >= 2)
    )
  ).slice(0, 5);

  finalizeSessionBehaviorBeforeReport(session.sessionId, session.courseType);
  const assessment = generateAssessmentForSession(session);
  const expandedReport = buildExpandedAssessmentReport(assessment, new Date().toISOString());
  const observationAttention = buildPerQuestionAttentionScores(
    sessionId,
    assessment.questionMetrics.map((metric) => metric.questionId)
  );
  const mediaManifest = await getSessionMediaManifest(sessionId);
  const questionVideoCapture = buildPerQuestionVideoCaptureStatus(
    mediaManifest,
    assessment.questionMetrics.map((metric) => metric.questionId)
  );
  const questionAttention = assessment.questionMetrics.map((metric) => {
    const observed = observationAttention.get(metric.questionId);
    const video = questionVideoCapture.get(metric.questionId);
    if (mediaManifest && video && !video.captured) {
      return {
        questionId: metric.questionId,
        score: undefined,
        quality: "excluded_no_video"
      };
    }
    const score =
      typeof observed?.score === "number"
        ? clamp(observed.score)
        : typeof metric.attention?.averageFacingScore === "number"
          ? clamp(metric.attention.averageFacingScore * 100)
          : typeof metric.attention?.screenOrientedRatio === "number"
            ? clamp(metric.attention.screenOrientedRatio * 100)
            : undefined;
    return {
      questionId: metric.questionId,
      score,
      quality: observed?.sampleCount ? observed.quality : metric.dataQuality.status
    };
  });
  const scoringInput = {
    courseType: session.courseType,
    totalQuestions,
    accuracy: totalQuestions === 0 ? 0 : firstTryCorrectCount / totalQuestions,
    averageResponseTimeMs: avgResponseTime,
    expandedReport,
    assessment,
    sessionId,
    questionAttention,
    questionVideoCapture,
    rawMediaManifestAvailable: Boolean(mediaManifest)
  };
  const dimensions = computeReportDimensions(scoringInput);
  const emotionSummary = aggregateSessionEmotion({
    assessment,
    sessionBehaviorSummary: behaviorObservationRepository.getSessionSummary(sessionId),
    emotionObservations: behaviorObservationRepository
      .listObservations(sessionId)
      .filter((observation) => observation.observationType === "emotion"),
    totalWrongAttempts: session.totalWrongAttempts,
    totalQuestions
  });
  const attentionCurve = buildQuestionAttentionCurve(scoringInput);
  const attentionDipQuestions = attentionCurve
    .filter((point) => typeof point.score === "number" && point.score < 50)
    .map((point) => point.questionId);
  const limitations = collectScoringLimitations(scoringInput);
  if (emotionSummary.status === "DEGRADED") {
    limitations.push("EMOTION_PROVIDER_DEGRADED_OR_MANUAL_ACCEPTANCE_REQUIRED");
  }
  const attentionMeta = deriveAttentionReportMeta(sessionId);
  if (attentionMeta.degraded) {
    limitations.push("ATTENTION_PROVIDER_DEGRADED_OR_MOCK");
  }
  const languageMeta = deriveLanguageReportMeta(sessionId);
  if (languageMeta.degraded) {
    limitations.push("LANGUAGE_AUDIO_FEATURES_DEGRADED_OR_MOCK");
  }
  const narrativeInput: ReportNarrativeInput = {
    sessionId,
    totalQuestions,
    accuracy: scoringInput.accuracy,
    averageResponseTimeMs: avgResponseTime,
    dimensions,
    emotionSummary,
    attentionDipQuestions,
    wrongAttempts: session.totalWrongAttempts,
    limitations
  };
  const narrative = usesAsyncReportNarrativeProvider()
    ? buildPendingReportNarrative()
    : await generateReportNarrative(narrativeInput);
  const report: TrainingReport = {
    reportId: createReportId(),
    sessionId: session.sessionId,
    childName: session.childName,
    courseType: session.courseType,
    startedAt: session.startedAt,
    completedAt: session.completedAt,
    durationSec: Math.max(
      0,
      Math.round((new Date(session.completedAt).getTime() - new Date(session.startedAt).getTime()) / 1000)
    ),
    summary: {
      totalQuestions,
      // 准确率口径：每题第一次作答是否正确
      correctAnswers: firstTryCorrectCount,
      accuracy: totalQuestions === 0 ? 0 : firstTryCorrectCount / totalQuestions,
      averageResponseTimeMs: avgResponseTime
    },
    errorStats: {
      totalWrongAttempts: session.totalWrongAttempts,
      byType: Array.from(errorTypeCounter.entries()).map(([errorType, count]) => ({
        errorType: errorType as "mismatch" | "wrong_order" | "timeout" | "invalid_input" | "other",
        count
      }))
    },
    questionResults: session.questionStats.map((item) => ({
      questionId: item.questionId,
      // 对外按“首答是否正确”记录
      correct: item.attempts === 1,
      attempts: item.attempts,
      responseTimeMs: item.responseTimeMs,
      errorType: item.wrongTypes[0]
    })),
    chatSummary: {
      totalMessages: session.chatHistory.length,
      childMessageCount: session.chatHistory.filter((entry) => entry.role === "child").length,
      botMessageCount: session.chatHistory.filter((entry) => entry.role === "bot").length,
      keywords,
      highlights:
        session.chatHistory.length > 0
          ? ["训练中孩子有主动交流，系统给出了鼓励或提示回应。"]
          : ["本次训练未触发对话交流。"]
    },
    assessment,
    expandedReport,
    professionalReportV2: {
      schemaVersion: "professional-report-v2",
      formulaVersion: FORMULA_VERSION,
      scoreBoundary: "education_training_reference_only",
      overallScore: dimensions.overallScore,
      dimensions: {
        ordering: dimensions.ordering,
        matching: dimensions.matching,
        receptiveLanguage: dimensions.receptiveLanguage,
        attention: dimensions.attention,
        expressiveLanguage: dimensions.expressiveLanguage
      },
      taskAccuracy: scoringInput.accuracy,
      averageResponseTimeMs: avgResponseTime,
      emotionSummary,
      attentionCurve,
      attentionSummary: attentionMeta,
      languageSummary: languageMeta,
      narrative,
      dataQuality: {
        status: expandedReport.dataQuality.status,
        limitations,
        providerSummary: expandedReport.evidence.providerSummary,
        degraded: limitations.length > 0
      },
      versions: {
        assessmentMetricVersion: expandedReport.versions.assessmentMetricVersion,
        reportExplanationPolicyVersion: expandedReport.versions.reportExplanationPolicyVersion,
        emotionAlgorithmVersion: emotionSummary.algorithmVersion,
        attentionAlgorithmVersion: attentionMeta.algorithmVersion,
        languageAlgorithmVersion: languageMeta.algorithmVersion,
        narrativePromptVersion: narrative.promptTemplateVersion
      }
    },
    generatedAt: new Date().toISOString(),
    version: "v1"
  };

  reports.set(sessionId, report);
  savePersistentReport(report);
  if (usesAsyncReportNarrativeProvider()) {
    scheduleReportNarrativeGeneration(sessionId, narrativeInput);
    return {
      reportId: report.reportId,
      sessionId: report.sessionId,
      status: "NARRATIVE_PENDING"
    };
  }
  return {
    reportId: report.reportId,
    sessionId: report.sessionId,
    status: "READY"
  };
}

function scheduleReportNarrativeGeneration(sessionId: string, input: ReportNarrativeInput) {
  if (narrativeJobs.has(sessionId)) return;
  const job = completeReportNarrative(sessionId, input).finally(() => {
    narrativeJobs.delete(sessionId);
  });
  narrativeJobs.set(sessionId, job);
}

async function completeReportNarrative(sessionId: string, input: ReportNarrativeInput) {
  let narrative: ReportNarrativeResult;
  try {
    narrative = await generateReportNarrative(input);
  } catch {
    narrative = buildRuleFallbackNarrative(input);
  }

  const report = reports.get(sessionId) ?? loadPersistentReport(sessionId);
  if (!report?.professionalReportV2) return;
  report.professionalReportV2.narrative = narrative;
  report.professionalReportV2.versions.narrativePromptVersion = narrative.promptTemplateVersion;
  reports.set(sessionId, report);
  savePersistentReport(report);
}

function clamp(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}

export function getReport(sessionId: string) {
  const report = reports.get(sessionId) ?? loadPersistentReport(sessionId);
  if (!report) {
    throw new Error("Report not generated");
  }
  reports.set(sessionId, report);
  return report;
}

function buildExpandedAssessmentReport(
  assessment: DeterministicAssessmentResult,
  generatedAt: string
): ExpandedAssessmentReport {
  const firstTryCorrect = assessment.questionMetrics.filter((metric) => metric.firstAttemptCorrect).length;
  const eventualCorrect = assessment.questionMetrics.filter((metric) => metric.eventualCorrect).length;
  const attentionMetrics = assessment.questionMetrics
    .map((metric) => metric.attention)
    .filter((metric): metric is NonNullable<typeof metric> => Boolean(metric));
  const languageMetrics = assessment.questionMetrics
    .map((metric) => metric.language)
    .filter((metric): metric is NonNullable<typeof metric> => Boolean(metric));
  const limitations = collectQualityLimitations(assessment);
  const evidenceByType: Record<string, number> = {};
  const providerSummary: Record<string, number> = {};
  for (const item of assessment.evidence) {
    evidenceByType[item.type] = (evidenceByType[item.type] ?? 0) + 1;
    const provider = item.provider ?? "missing_provider";
    providerSummary[provider] = (providerSummary[provider] ?? 0) + 1;
  }

  return {
    schemaVersion: "m6-expanded-report-v1",
    metricVersion: "m6-expanded-report-metrics-v1",
    answerMetrics: {
      totalQuestions: assessment.sessionMetrics.totalQuestions,
      firstTryCorrect,
      firstTryAccuracy: assessment.sessionMetrics.firstTryAccuracy,
      eventualCorrect,
      eventualAccuracy: assessment.sessionMetrics.eventualAccuracy,
      averageResponseTimeMs: assessment.sessionMetrics.averageResponseTimeMs,
      medianResponseTimeMs: assessment.sessionMetrics.medianResponseTimeMs,
      totalWrongAttempts: assessment.sessionMetrics.totalWrongAttempts,
      wrongAttemptsByType: assessment.sessionMetrics.wrongAttemptsByType,
      questionMetrics: assessment.questionMetrics.map((metric) => ({
        questionId: metric.questionId,
        firstAttemptCorrect: metric.firstAttemptCorrect,
        eventualCorrect: metric.eventualCorrect,
        attempts: metric.attempts,
        wrongAttempts: metric.wrongAttempts,
        responseTimeMs: metric.responseTimeMs,
        hintCount: metric.hintCount,
        promptDependencyFlag: metric.promptDependencyFlag,
        dataQualityStatus: metric.dataQuality.status
      }))
    },
    attentionMetrics: {
      status: attentionMetrics.length > 0 ? "available" : "unavailable",
      observedMs: sum(attentionMetrics.map((metric) => metric.observedMs)),
      screenOrientedRatio: weightedRatio(
        attentionMetrics.map((metric) => ({
          value: metric.screenOrientedRatio,
          weight: metric.observedMs
        }))
      ),
      unavailableMs: sum(attentionMetrics.map((metric) => metric.unavailableMs)),
      qualityStatus: assessment.sessionMetrics.attention?.quality.status ?? "insufficient"
    },
    languageMetrics: {
      status: languageMetrics.length > 0 ? "available" : "unavailable",
      responseCount: languageMetrics.filter((metric) => metric.responsePresent).length,
      emptyResponseCount: languageMetrics.filter((metric) => metric.emptyResponse).length,
      repeatedResponseCount: languageMetrics.filter((metric) => metric.repeatedResponse).length,
      averageTranscriptLength: average(
        languageMetrics
          .map((metric) => metric.transcriptLength)
          .filter((value): value is number => typeof value === "number")
      ),
      averageLoudnessRms: average(
        languageMetrics
          .map((metric) => metric.averageLoudnessRms)
          .filter((value): value is number => typeof value === "number")
      ),
      averageSpeechRatio: average(
        languageMetrics
          .map((metric) => metric.averageSpeechRatio)
          .filter((value): value is number => typeof value === "number")
      ),
      averageClarityProxy: average(
        languageMetrics
          .map((metric) => metric.averageClarityProxy)
          .filter((value): value is number => typeof value === "number")
      ),
      audioFeatureTurnCount: languageMetrics.filter((metric) => typeof metric.averageLoudnessRms === "number").length,
      audioFeatureProvider: languageMetrics.find((metric) => metric.audioFeatureProvider)?.audioFeatureProvider,
      audioFeatureAlgorithmVersion: languageMetrics.find((metric) => metric.audioFeatureAlgorithmVersion)
        ?.audioFeatureAlgorithmVersion,
      audioFeatureDegraded: languageMetrics.some((metric) => metric.audioFeatureDegraded),
      qualityStatus: assessment.sessionMetrics.language?.quality.status ?? "insufficient"
    },
    dataQuality: {
      status: assessment.dataQuality.status,
      limitations,
      environmentPending: assessment.environmentPending
    },
    evidence: {
      totalReferences: assessment.evidence.length,
      byType: evidenceByType,
      providerSummary,
      sample: assessment.evidence.slice(0, 8).map((item) => ({
        type: item.type,
        id: item.id,
        questionId: item.questionId,
        provider: item.provider
      }))
    },
    versions: {
      reportVersion: "v1",
      assessmentSchemaVersion: assessment.schemaVersion,
      assessmentMetricVersion: assessment.metricVersion,
      assessmentAlgorithmVersion: assessment.algorithm.algorithmVersion,
      reportExplanationPolicyVersion: "m6-report-explanation-rule-v1"
    },
    history: {
      generatedAt,
      assessmentCreatedAt: assessment.createdAt,
      trendBaseline: "single_session_only",
      previousReportCount: 0
    },
    trends: {
      status: "baseline_only",
      reasonCode: "NO_PRIOR_REPORT_HISTORY",
      items: []
    },
    safeExplanations: buildSafeReportExplanations(assessment, limitations),
    exportBoundary: {
      jsonReady: true,
      printReady: true,
      containsRawAudio: false,
      containsRawVideo: false,
      containsRawChatText: false,
      allowedFormats: ["json", "browser_print"]
    },
    degradation: {
      fallbackUsed: limitations.length > 0,
      reasonCodes: limitations
    }
  };
}

function buildSafeReportExplanations(
  assessment: DeterministicAssessmentResult,
  limitations: string[]
): ExpandedAssessmentReport["safeExplanations"] {
  const policyVersion = "m6-report-explanation-rule-v1";
  return [
    {
      section: "answers",
      text: `First-try accuracy is ${(assessment.sessionMetrics.firstTryAccuracy * 100).toFixed(0)}%. This is a training-performance metric, not a professional score.`,
      reviewStatus: "PASS",
      policyVersion
    },
    {
      section: "attention",
      text: assessment.sessionMetrics.attention
        ? "Attention observations summarize screen-oriented intervals from camera descriptors (browser-attention-v2). This is task engagement, not clinical attention."
        : "Attention observations are unavailable; the report records this as a data-quality limitation.",
      reviewStatus: "PASS",
      policyVersion
    },
    {
      section: "language",
      text: assessment.sessionMetrics.language
        ? "Language observations use derived transcript features only and do not include raw child text."
        : "Language observations are unavailable or incomplete; no language score is produced.",
      reviewStatus: "PASS",
      policyVersion
    },
    {
      section: "data_quality",
      text: limitations.length > 0
        ? "Some inputs are incomplete, so the report preserves limitations and avoids unsupported interpretation."
        : "Structured inputs were sufficient for deterministic educational-reference metrics.",
      reviewStatus: "PASS",
      policyVersion
    }
  ];
}

function deriveAttentionReportMeta(sessionId: string) {
  const observations = behaviorObservationRepository
    .listObservations(sessionId)
    .filter((item) => item.observationType === "attention");
  if (observations.length === 0) {
    return {
      provider: undefined,
      algorithmVersion: undefined,
      degraded: true,
      observationCount: 0
    };
  }
  const latest = observations[observations.length - 1]!;
  const mockCount = observations.filter((item) => (item.provider ?? "").includes("mock")).length;
  return {
    provider: latest.provider,
    algorithmVersion: latest.algorithm.algorithmVersion,
    degraded: observations.some((item) => item.degraded) || mockCount > 0,
    observationCount: observations.length
  };
}

function deriveLanguageReportMeta(sessionId: string) {
  const observations = behaviorObservationRepository
    .listObservations(sessionId)
    .filter((item) => item.observationType === "language");
  const audioObservations = observations.filter((item) =>
    ["audio_loudness_rms", "audio_loudness_db", "audio_speech_ratio", "audio_clarity_proxy"].includes(item.features.kind)
  );
  if (audioObservations.length === 0) {
    return {
      provider: undefined,
      algorithmVersion: undefined,
      degraded: true,
      observationCount: 0,
      averageLoudnessRms: undefined,
      averageSpeechRatio: undefined,
      averageClarityProxy: undefined
    };
  }
  const latest = audioObservations[audioObservations.length - 1]!;
  const turnIds = new Set(audioObservations.map((item) => item.turnId).filter(Boolean));
  const loudness = average(
    audioObservations
      .filter((item) => item.features.kind === "audio_loudness_rms")
      .map((item) => item.features.value)
      .filter((value): value is number => typeof value === "number")
  );
  const speechRatio = average(
    audioObservations
      .filter((item) => item.features.kind === "audio_speech_ratio")
      .map((item) => item.features.value)
      .filter((value): value is number => typeof value === "number")
  );
  const clarity = average(
    audioObservations
      .filter((item) => item.features.kind === "audio_clarity_proxy")
      .map((item) => item.features.value)
      .filter((value): value is number => typeof value === "number")
  );
  return {
    provider: latest.provider,
    algorithmVersion: latest.algorithm.algorithmVersion,
    degraded: audioObservations.some((item) => item.degraded) || (latest.provider ?? "").includes("mock"),
    observationCount: turnIds.size,
    averageLoudnessRms: loudness,
    averageSpeechRatio: speechRatio,
    averageClarityProxy: clarity
  };
}

function collectQualityLimitations(assessment: DeterministicAssessmentResult) {
  const limitations = new Set<string>();
  if (assessment.dataQuality.reasonCode) limitations.add(assessment.dataQuality.reasonCode);
  for (const metric of assessment.questionMetrics) {
    if (metric.dataQuality.reasonCode) limitations.add(metric.dataQuality.reasonCode);
    if (metric.attention?.quality.reasonCode) limitations.add(metric.attention.quality.reasonCode);
    if (metric.language?.quality.reasonCode) limitations.add(metric.language.quality.reasonCode);
  }
  return [...limitations];
}

function sum(values: number[]) {
  return values.reduce((total, value) => total + value, 0);
}

function average(values: number[]) {
  if (values.length === 0) return undefined;
  return round(sum(values) / values.length);
}

function weightedRatio(items: Array<{ value?: number; weight: number }>) {
  const usable = items.filter((item): item is { value: number; weight: number } => typeof item.value === "number" && item.weight > 0);
  const denominator = sum(usable.map((item) => item.weight));
  if (denominator <= 0) return undefined;
  return round(usable.reduce((total, item) => total + item.value * item.weight, 0) / denominator);
}

function round(value: number) {
  return Math.round(value * 1000) / 1000;
}
