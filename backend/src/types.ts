import type { DeterministicAssessmentResult } from "child-education-training-demo/shared/assessments";

export type CourseType = "matching" | "ordering";

export interface CourseOption {
  id: string;
  label: string;
  imageUrl?: string;
  description?: string;
  level?: number;
}

export interface CourseQuestion {
  id: string;
  prompt: string;
  target: string;
  targetDescription?: string;
  targetImageUrl?: string;
  options: CourseOption[];
  correctOptionId: string;
  hint: string;
  errorTypeOnWrong: "mismatch" | "wrong_order";
}

export interface SessionQuestionStat {
  questionId: string;
  attempts: number;
  correct: boolean;
  responseTimeMs: number;
  wrongTypes: string[];
}

export interface ChatEntry {
  role: "child" | "bot";
  text: string;
  strategy?: string;
  timestamp: string;
}

export interface Session {
  sessionId: string;
  childName: string;
  courseType: CourseType;
  startedAt: string;
  completedAt: string | null;
  currentQuestionIndex: number;
  correctAnswers: number;
  totalWrongAttempts: number;
  responseTimes: number[];
  questions: CourseQuestion[];
  questionStats: SessionQuestionStat[];
  chatHistory: ChatEntry[];
  state: "TRAINING_ACTIVE" | "TRAINING_FINISHED";
  lastPresentedQuestionId?: string;
}

export interface TrainingReport {
  reportId: string;
  sessionId: string;
  childName?: string;
  courseType: "matching" | "ordering" | "mixed";
  startedAt: string;
  completedAt: string;
  durationSec: number;
  summary: {
    totalQuestions: number;
    correctAnswers: number;
    accuracy: number;
    averageResponseTimeMs: number;
  };
  errorStats: {
    totalWrongAttempts: number;
    byType: Array<{
      errorType: "mismatch" | "wrong_order" | "timeout" | "invalid_input" | "other";
      count: number;
    }>;
  };
  questionResults: Array<{
    questionId: string;
    correct: boolean;
    attempts: number;
    responseTimeMs: number;
    errorType?: string;
  }>;
  chatSummary: {
    totalMessages: number;
    childMessageCount: number;
    botMessageCount: number;
    keywords: string[];
    highlights: string[];
  };
  assessment?: DeterministicAssessmentResult;
  expandedReport?: ExpandedAssessmentReport;
  professionalReportV2?: ProfessionalReportV2;
  generatedAt: string;
  version: "v1";
}

export interface ProfessionalReportV2 {
  schemaVersion: "professional-report-v2";
  formulaVersion: "education-training-index-v1";
  scoreBoundary: "education_training_reference_only";
  overallScore: number;
  dimensions: {
    ordering: number;
    matching: number;
    receptiveLanguage: number;
    attention: number;
    expressiveLanguage: number;
  };
  taskAccuracy: number;
  averageResponseTimeMs: number;
  emotionSummary: {
    status: "AVAILABLE" | "DEGRADED";
    positiveRatio?: number;
    focusedRatio?: number;
    frustratedRatio?: number;
    reason?: "MANUAL_ACCEPTANCE_REQUIRED" | "INSUFFICIENT_SIGNALS";
    provider?: string;
    algorithmVersion?: string;
    degraded?: boolean;
    observationCount?: number;
  };
  attentionCurve: Array<{
    questionId: string;
    score?: number;
    quality: string;
  }>;
  attentionSummary?: {
    provider?: string;
    algorithmVersion?: string;
    degraded: boolean;
    observationCount: number;
  };
  languageSummary?: {
    provider?: string;
    algorithmVersion?: string;
    degraded: boolean;
    observationCount: number;
    averageLoudnessRms?: number;
    averageSpeechRatio?: number;
    averageClarityProxy?: number;
  };
  narrative: {
    status: "PENDING" | "READY" | "FAILED";
    analysis: string;
    recommendations: string[];
    safetyReviewStatus: "PASS" | "REJECT";
    generator: "mock_llm" | "rule_fallback" | "openai" | "deepseek" | "pending";
    provider?: string;
    model?: string;
    promptTemplateVersion?: string;
  };
  dataQuality: {
    status: string;
    limitations: string[];
    providerSummary: Record<string, number>;
    degraded: boolean;
  };
  versions: {
    assessmentMetricVersion?: string;
    reportExplanationPolicyVersion: string;
    emotionAlgorithmVersion?: string;
    attentionAlgorithmVersion?: string;
    languageAlgorithmVersion?: string;
    narrativePromptVersion?: string;
  };
}

export interface ExpandedAssessmentReport {
  schemaVersion: "m6-expanded-report-v1";
  metricVersion: "m6-expanded-report-metrics-v1";
  answerMetrics: {
    totalQuestions: number;
    firstTryCorrect: number;
    firstTryAccuracy: number;
    eventualCorrect: number;
    eventualAccuracy: number;
    averageResponseTimeMs?: number;
    medianResponseTimeMs?: number;
    totalWrongAttempts: number;
    wrongAttemptsByType: Record<string, number>;
    questionMetrics: Array<{
      questionId: string;
      firstAttemptCorrect: boolean;
      eventualCorrect: boolean;
      attempts: number;
      wrongAttempts: number;
      responseTimeMs?: number;
      hintCount: number;
      promptDependencyFlag: boolean;
      dataQualityStatus: string;
    }>;
  };
  attentionMetrics: {
    status: "available" | "unavailable";
    observedMs: number;
    screenOrientedRatio?: number;
    unavailableMs: number;
    qualityStatus: string;
  };
  languageMetrics: {
    status: "available" | "unavailable";
    responseCount: number;
    emptyResponseCount: number;
    repeatedResponseCount: number;
    averageTranscriptLength?: number;
    averageLoudnessRms?: number;
    averageSpeechRatio?: number;
    averageClarityProxy?: number;
    audioFeatureTurnCount?: number;
    audioFeatureProvider?: string;
    audioFeatureAlgorithmVersion?: string;
    audioFeatureDegraded?: boolean;
    qualityStatus: string;
  };
  dataQuality: {
    status: string;
    limitations: string[];
    environmentPending: string[];
  };
  evidence: {
    totalReferences: number;
    byType: Record<string, number>;
    providerSummary: Record<string, number>;
    sample: Array<{
      type: string;
      id: string;
      questionId?: string;
      provider?: string;
    }>;
  };
  versions: {
    reportVersion: "v1";
    assessmentSchemaVersion: string;
    assessmentMetricVersion: string;
    assessmentAlgorithmVersion: string;
    reportExplanationPolicyVersion: "m6-report-explanation-rule-v1";
  };
  history: {
    generatedAt: string;
    assessmentCreatedAt: string;
    trendBaseline: "single_session_only";
    previousReportCount: number;
  };
  trends: {
    status: "baseline_only";
    reasonCode: "NO_PRIOR_REPORT_HISTORY";
    items: [];
  };
  safeExplanations: Array<{
    section: "answers" | "attention" | "language" | "data_quality";
    text: string;
    reviewStatus: "PASS";
    policyVersion: "m6-report-explanation-rule-v1";
  }>;
  exportBoundary: {
    jsonReady: boolean;
    printReady: boolean;
    containsRawAudio: false;
    containsRawVideo: false;
    containsRawChatText: false;
    allowedFormats: Array<"json" | "browser_print">;
  };
  degradation: {
    fallbackUsed: boolean;
    reasonCodes: string[];
  };
}
