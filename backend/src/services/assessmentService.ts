import type {
  DeterministicAssessmentResult,
  QuestionAssessmentMetrics
} from "child-education-training-demo/shared/assessments";
import type {
  DataQuality,
  EvidenceReference,
  QuestionBehaviorSummary,
  SessionBehaviorSummary
} from "child-education-training-demo/shared/behavior-observations";
import { createEvidenceReference } from "child-education-training-demo/shared/behavior-observations";
import type { Session } from "../types.js";
import { assessmentRepository } from "./assessmentRepository.js";
import { behaviorObservationRepository } from "./behaviorFrameIngressService.js";

const REQUIRED_SCORING_DECISIONS = [
  "formal_weights",
  "formal_thresholds",
  "professional_norms",
  "percentiles",
  "clinical_or_professional_interpretation"
];
const ASSESSMENT_SCHEMA_VERSION = "m6-assessment-v1";
const ASSESSMENT_METRIC_VERSION = "deterministic-assessment-v1";
const OWNER_REQUIRED_BEFORE_SCORING = "OWNER_REQUIRED_BEFORE_SCORING";

export function computeDeterministicAssessment(input: {
  session: Session;
  questionBehaviorSummaries?: QuestionBehaviorSummary[];
  sessionBehaviorSummary?: SessionBehaviorSummary;
  createdAt?: string;
}): DeterministicAssessmentResult {
  const questionBehaviorSummaries = input.questionBehaviorSummaries ?? [];
  const behaviorByQuestion = new Map(questionBehaviorSummaries.map((summary) => [summary.questionId, summary]));
  const createdAt = input.createdAt ?? new Date().toISOString();
  const questionMetrics = input.session.questionStats.map((stat) => {
    const behavior = behaviorByQuestion.get(stat.questionId);
    return buildQuestionMetrics(input.session.sessionId, stat, behavior, createdAt);
  });
  const completedQuestions = input.session.questionStats.filter((stat) => stat.correct).length;
  const firstTryCorrect = questionMetrics.filter((metric) => metric.firstAttemptCorrect).length;
  const eventualCorrect = questionMetrics.filter((metric) => metric.eventualCorrect).length;
  const responseTimes = questionMetrics
    .map((metric) => metric.responseTimeMs)
    .filter((value): value is number => typeof value === "number")
    .sort((left, right) => left - right);
  const evidence = [
    createEvidenceReference({
      type: "domain_event",
      id: `session:${input.session.sessionId}:question-stats`,
      sessionId: input.session.sessionId,
      createdAt
    }),
    ...questionMetrics.flatMap((metric) => metric.evidence),
    ...(input.sessionBehaviorSummary?.evidence ?? [])
  ];
  const dataQuality = combineQuality([
    ...questionMetrics.map((metric) => metric.dataQuality),
    input.sessionBehaviorSummary?.dataQuality ?? { status: "insufficient", reasonCode: "BEHAVIOR_SUMMARY_MISSING" }
  ]);

  return {
    assessmentId: `assessment:${input.session.sessionId}`,
    sessionId: input.session.sessionId,
    schemaVersion: ASSESSMENT_SCHEMA_VERSION,
    metricVersion: ASSESSMENT_METRIC_VERSION,
    algorithm: {
      schemaVersion: "m5-behavior-v1",
      algorithmVersion: "m6-deterministic-assessment-v1",
      ruleVersion: OWNER_REQUIRED_BEFORE_SCORING
    },
    questionMetrics,
    sessionMetrics: {
      totalQuestions: input.session.questions.length,
      completedQuestions,
      firstTryAccuracy: ratio(firstTryCorrect, input.session.questions.length),
      eventualAccuracy: ratio(eventualCorrect, input.session.questions.length),
      totalWrongAttempts: input.session.totalWrongAttempts,
      averageResponseTimeMs: average(responseTimes),
      medianResponseTimeMs: median(responseTimes),
      hintDependencyRate: ratio(questionMetrics.filter((metric) => metric.promptDependencyFlag).length, input.session.questions.length),
      wrongAttemptsByType: countWrongTypes(input.session.questionStats),
      attention: input.sessionBehaviorSummary?.attention,
      language: input.sessionBehaviorSummary?.language,
      dataQuality
    },
    evidence,
    dataQuality,
    scoringStatus: OWNER_REQUIRED_BEFORE_SCORING,
    ownerRequiredBeforeScoring: REQUIRED_SCORING_DECISIONS,
    environmentPending: [
      "real_robot_field_validation",
      "human_annotation_comparison",
      "approved_scoring_rules"
    ],
    createdAt
  };
}

export function generateAssessmentForSession(session: Session) {
  const questionBehaviorSummaries = behaviorObservationRepository.listQuestionSummaries(session.sessionId);
  const sessionBehaviorSummary = behaviorObservationRepository.getSessionSummary(session.sessionId);
  const assessment = computeDeterministicAssessment({
    session,
    questionBehaviorSummaries,
    sessionBehaviorSummary
  });
  return assessmentRepository.saveAssessment(assessment);
}

export function getAssessment(sessionId: string) {
  const assessment = assessmentRepository.getAssessment(sessionId);
  if (!assessment) {
    throw new Error("Assessment not generated");
  }
  return assessment;
}

function buildQuestionMetrics(
  sessionId: string,
  stat: Session["questionStats"][number],
  behavior: QuestionBehaviorSummary | undefined,
  createdAt: string
): QuestionAssessmentMetrics {
  const evidence: EvidenceReference[] = [
    createEvidenceReference({
      type: "domain_event",
      id: `question-stat:${sessionId}:${stat.questionId}`,
      sessionId,
      questionId: stat.questionId,
      createdAt
    }),
    ...(behavior?.evidence ?? [])
  ];
  const dataQuality = combineQuality([
    { status: "complete" },
    behavior?.dataQuality ?? { status: "insufficient", reasonCode: "BEHAVIOR_QUESTION_SUMMARY_MISSING" }
  ]);

  return {
    questionId: stat.questionId,
    attempts: stat.attempts,
    firstAttemptCorrect: stat.correct && stat.attempts === 1,
    eventualCorrect: stat.correct,
    wrongAttempts: stat.wrongTypes.length,
    responseTimeMs: stat.responseTimeMs > 0 ? stat.responseTimeMs : undefined,
    hintCount: Math.max(0, stat.attempts - 1),
    promptDependencyFlag: stat.attempts > 1,
    attention: behavior?.attention
      ? {
          observedMs: behavior.attention.observedMs,
          screenOrientedRatio: ratio(behavior.attention.screenOrientedMs, behavior.attention.observedMs),
          averageFacingScore: behavior.attention.averageFacingScore,
          unavailableMs: behavior.attention.unavailableMs,
          quality: behavior.attention.quality
        }
      : undefined,
    language: behavior?.language,
    evidence,
    dataQuality
  };
}

function countWrongTypes(stats: Session["questionStats"]) {
  const counts: Record<string, number> = {};
  for (const stat of stats) {
    for (const wrongType of stat.wrongTypes) {
      counts[wrongType] = (counts[wrongType] ?? 0) + 1;
    }
  }
  return counts;
}

function combineQuality(qualities: DataQuality[]): DataQuality {
  if (qualities.length === 0) return { status: "insufficient", reasonCode: "NO_INPUTS" };
  if (qualities.some((quality) => quality.status === "missing_device")) {
    return { status: "partial", reasonCode: "MISSING_DEVICE_INPUT" };
  }
  if (qualities.some((quality) => quality.status === "low_confidence")) {
    return { status: "low_confidence", reasonCode: "LOW_CONFIDENCE_INPUT" };
  }
  if (qualities.some((quality) => quality.status !== "complete")) {
    return { status: "partial", reasonCode: "PARTIAL_INPUT" };
  }
  return { status: "complete" };
}

function ratio(numerator: number, denominator: number) {
  return denominator <= 0 ? 0 : round(numerator / denominator);
}

function average(values: number[]) {
  if (values.length === 0) return undefined;
  return round(values.reduce((total, value) => total + value, 0) / values.length);
}

function median(values: number[]) {
  if (values.length === 0) return undefined;
  return values[Math.floor(values.length / 2)];
}

function round(value: number) {
  return Math.round(value * 1000) / 1000;
}
