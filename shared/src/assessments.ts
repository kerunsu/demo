import type {
  AlgorithmVersion,
  DataQuality,
  EvidenceReference,
  SessionBehaviorSummary
} from "./behaviorObservations.js";

export const ASSESSMENT_SCHEMA_VERSION = "m6-assessment-v1" as const;
export const ASSESSMENT_METRIC_VERSION = "deterministic-assessment-v1" as const;
export const OWNER_REQUIRED_BEFORE_SCORING = "OWNER_REQUIRED_BEFORE_SCORING" as const;

export type AssessmentSchemaVersion = typeof ASSESSMENT_SCHEMA_VERSION;
export type AssessmentMetricVersion = typeof ASSESSMENT_METRIC_VERSION;

export interface QuestionAssessmentMetrics {
  questionId: string;
  attempts: number;
  firstAttemptCorrect: boolean;
  eventualCorrect: boolean;
  wrongAttempts: number;
  responseTimeMs?: number;
  hintCount: number;
  promptDependencyFlag: boolean;
  attention?: {
    observedMs: number;
    screenOrientedRatio?: number;
    averageFacingScore?: number;
    unavailableMs: number;
    quality: DataQuality;
  };
  language?: {
    responsePresent: boolean;
    responseLatencyMs?: number;
    transcriptLength?: number;
    sentenceCount?: number;
    emptyResponse: boolean;
    repeatedResponse: boolean;
    averageLoudnessRms?: number;
    averageLoudnessDb?: number;
    averageSpeechRatio?: number;
    averageClarityProxy?: number;
    audioFeatureProvider?: string;
    audioFeatureAlgorithmVersion?: string;
    audioFeatureDegraded?: boolean;
    quality: DataQuality;
  };
  evidence: EvidenceReference[];
  dataQuality: DataQuality;
}

export interface SessionAssessmentMetrics {
  totalQuestions: number;
  completedQuestions: number;
  firstTryAccuracy: number;
  eventualAccuracy: number;
  totalWrongAttempts: number;
  averageResponseTimeMs?: number;
  medianResponseTimeMs?: number;
  hintDependencyRate: number;
  wrongAttemptsByType: Record<string, number>;
  attention?: SessionBehaviorSummary["attention"];
  language?: SessionBehaviorSummary["language"];
  dataQuality: DataQuality;
}

export interface DeterministicAssessmentResult {
  assessmentId: string;
  sessionId: string;
  schemaVersion: AssessmentSchemaVersion;
  metricVersion: AssessmentMetricVersion;
  algorithm: AlgorithmVersion;
  questionMetrics: QuestionAssessmentMetrics[];
  sessionMetrics: SessionAssessmentMetrics;
  evidence: EvidenceReference[];
  dataQuality: DataQuality;
  scoringStatus: typeof OWNER_REQUIRED_BEFORE_SCORING;
  ownerRequiredBeforeScoring: string[];
  environmentPending: string[];
  createdAt: string;
}
