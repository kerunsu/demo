import assert from "node:assert/strict";
import test from "node:test";

import {
  collectScoringLimitations,
  computeReportDimensions,
  responseTimeScore,
  RESPONSE_TIME_THRESHOLD_PENDING
} from "../dist/services/reportScoringService.js";
import { computeAcousticExpressiveScore } from "../dist/services/audioFeatureScoringUtils.js";

function baseExpandedReport() {
  return {
    schemaVersion: "m6-expanded-report-v1",
    metricVersion: "m6-expanded-report-metrics-v1",
    answerMetrics: {
      totalQuestions: 2,
      firstTryCorrect: 1,
      firstTryAccuracy: 0.5,
      eventualCorrect: 2,
      eventualAccuracy: 1,
      averageResponseTimeMs: 2000,
      totalWrongAttempts: 1,
      wrongAttemptsByType: { mismatch: 1 },
      questionMetrics: [
        {
          questionId: "matching_q_1",
          firstAttemptCorrect: true,
          eventualCorrect: true,
          attempts: 1,
          wrongAttempts: 0,
          responseTimeMs: 1000,
          hintCount: 0,
          promptDependencyFlag: false,
          dataQualityStatus: "complete"
        },
        {
          questionId: "matching_q_2",
          firstAttemptCorrect: false,
          eventualCorrect: true,
          attempts: 2,
          wrongAttempts: 1,
          responseTimeMs: 3000,
          hintCount: 1,
          promptDependencyFlag: true,
          dataQualityStatus: "partial"
        }
      ]
    },
    attentionMetrics: {
      status: "available",
      observedMs: 2000,
      screenOrientedRatio: 0.8,
      unavailableMs: 0,
      qualityStatus: "complete"
    },
    languageMetrics: {
      status: "available",
      responseCount: 1,
      emptyResponseCount: 0,
      repeatedResponseCount: 0,
      averageTranscriptLength: 6,
      qualityStatus: "complete"
    },
    dataQuality: { status: "partial", limitations: ["PARTIAL_INPUT"], environmentPending: [] },
    evidence: { totalReferences: 1, byType: {}, providerSummary: {}, sample: [] },
    versions: {
      reportVersion: "v1",
      assessmentSchemaVersion: "m6-assessment-v1",
      assessmentMetricVersion: "deterministic-assessment-v1",
      assessmentAlgorithmVersion: "m6-deterministic-assessment-v1",
      reportExplanationPolicyVersion: "m6-report-explanation-rule-v1"
    },
    history: { generatedAt: "2026-06-14T00:00:00.000Z", assessmentCreatedAt: "2026-06-14T00:00:00.000Z", trendBaseline: "single_session_only", previousReportCount: 0 },
    trends: { status: "baseline_only", reasonCode: "NO_PRIOR_REPORT_HISTORY", items: [] },
    safeExplanations: [],
    exportBoundary: {
      jsonReady: true,
      printReady: true,
      containsRawAudio: false,
      containsRawVideo: false,
      containsRawChatText: false,
      allowedFormats: ["json", "browser_print"]
    },
    degradation: { fallbackUsed: true, reasonCodes: ["PARTIAL_INPUT"] }
  };
}

test("report scoring computes matching dimension and marks response thresholds pending", () => {
  const dimensions = computeReportDimensions({
    courseType: "matching",
    totalQuestions: 2,
    accuracy: 0.5,
    averageResponseTimeMs: 2000,
    expandedReport: baseExpandedReport(),
    assessment: {
      questionMetrics: baseExpandedReport().answerMetrics.questionMetrics.map((metric) => ({
        questionId: metric.questionId,
        firstAttemptCorrect: metric.firstAttemptCorrect,
        eventualCorrect: metric.eventualCorrect,
        attempts: metric.attempts,
        wrongAttempts: metric.wrongAttempts,
        responseTimeMs: metric.responseTimeMs,
        hintCount: metric.hintCount,
        promptDependencyFlag: metric.promptDependencyFlag,
        evidence: [],
        dataQuality: { status: metric.dataQualityStatus }
      })),
      sessionMetrics: { totalQuestions: 2, firstTryAccuracy: 0.5 },
      evidence: [],
      dataQuality: { status: "partial" }
    },
    sessionId: "sess_score",
    questionAttention: [
      { questionId: "matching_q_1", score: 90, quality: "complete" },
      { questionId: "matching_q_2", score: 60, quality: "partial" }
    ]
  });

  assert.ok(dimensions.matching > 0);
  assert.equal(dimensions.ordering, 0);
  assert.ok(dimensions.attention > 0);
  assert.ok(responseTimeScore(1200) >= responseTimeScore(5000));
});

test("report scoring includes pending response threshold limitation", () => {
  const limitations = collectScoringLimitations({
    courseType: "matching",
    totalQuestions: 2,
    accuracy: 0.5,
    averageResponseTimeMs: 2000,
    expandedReport: baseExpandedReport(),
    assessment: { questionMetrics: [], sessionMetrics: { totalQuestions: 2 }, evidence: [], dataQuality: { status: "partial" } },
    sessionId: "sess_limit",
    questionAttention: []
  });
  assert.equal(limitations.includes(RESPONSE_TIME_THRESHOLD_PENDING), true);
});

test("expressive language acoustic score differentiates loud clear vs quiet muffled signals", () => {
  const loudClear = computeAcousticExpressiveScore({
    averageLoudnessRms: 0.22,
    averageSpeechRatio: 0.85,
    averageClarityProxy: 0.8
  });
  const quietMuffled = computeAcousticExpressiveScore({
    averageLoudnessRms: 0.01,
    averageSpeechRatio: 0.05,
    averageClarityProxy: 0.2
  });
  assert.ok(loudClear > quietMuffled);

  const report = baseExpandedReport();
  report.languageMetrics.averageLoudnessRms = 0.22;
  report.languageMetrics.averageSpeechRatio = 0.85;
  report.languageMetrics.averageClarityProxy = 0.8;
  report.languageMetrics.audioFeatureTurnCount = 2;
  const withAcoustic = computeReportDimensions({
    courseType: "matching",
    totalQuestions: 2,
    accuracy: 0.5,
    averageResponseTimeMs: 2000,
    expandedReport: report,
    assessment: { questionMetrics: [], sessionMetrics: { totalQuestions: 2 }, evidence: [], dataQuality: { status: "partial" } },
    sessionId: "sess_lang_audio",
    questionAttention: []
  });

  report.languageMetrics.averageLoudnessRms = 0.01;
  report.languageMetrics.averageSpeechRatio = 0.05;
  report.languageMetrics.averageClarityProxy = 0.2;
  const quietReport = computeReportDimensions({
    courseType: "matching",
    totalQuestions: 2,
    accuracy: 0.5,
    averageResponseTimeMs: 2000,
    expandedReport: report,
    assessment: { questionMetrics: [], sessionMetrics: { totalQuestions: 2 }, evidence: [], dataQuality: { status: "partial" } },
    sessionId: "sess_lang_audio_quiet",
    questionAttention: []
  });
  assert.ok(withAcoustic.expressiveLanguage > quietReport.expressiveLanguage);
});
