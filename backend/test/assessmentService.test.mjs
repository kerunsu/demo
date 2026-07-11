import assert from "node:assert/strict";
import test from "node:test";
import {
  computeDeterministicAssessment,
  generateAssessmentForSession,
  getAssessment
} from "../dist/services/assessmentService.js";
import { behaviorObservationRepository } from "../dist/services/behaviorFrameIngressService.js";

function buildSession() {
  return {
    sessionId: "session-m6-a",
    childName: "Test Child",
    courseType: "matching",
    startedAt: "2026-06-14T00:00:00.000Z",
    completedAt: "2026-06-14T00:02:00.000Z",
    currentQuestionIndex: 2,
    correctAnswers: 2,
    totalWrongAttempts: 1,
    responseTimes: [1000, 3000],
    questions: [
      {
        id: "q1",
        prompt: "Pick same",
        target: "same",
        options: [],
        correctOptionId: "a",
        hint: "look again",
        errorTypeOnWrong: "mismatch"
      },
      {
        id: "q2",
        prompt: "Pick same",
        target: "same",
        options: [],
        correctOptionId: "b",
        hint: "look again",
        errorTypeOnWrong: "mismatch"
      }
    ],
    questionStats: [
      { questionId: "q1", attempts: 1, correct: true, responseTimeMs: 1000, wrongTypes: [] },
      { questionId: "q2", attempts: 2, correct: true, responseTimeMs: 3000, wrongTypes: ["mismatch"] }
    ],
    chatHistory: [],
    state: "TRAINING_FINISHED"
  };
}

test("deterministic assessment computes evidence-based metrics without formal scores", () => {
  const session = buildSession();
  const assessment = computeDeterministicAssessment({
    session,
    questionBehaviorSummaries: [
      {
        summaryId: "question-summary:session-m6-a:q1",
        sessionId: session.sessionId,
        questionId: "q1",
        windowId: "window-q1",
        correlationId: "corr-q1",
        attention: {
          observedMs: 2000,
          screenOrientedMs: 1500,
          orientationInterruptedMs: 500,
          unavailableMs: 0,
          quality: { status: "complete" }
        },
        language: {
          responsePresent: true,
          responseLatencyMs: 800,
          transcriptLength: 4,
          sentenceCount: 1,
          emptyResponse: false,
          repeatedResponse: false,
          quality: { status: "complete" }
        },
        evidence: [],
        algorithm: { schemaVersion: "m5-behavior-v1", algorithmVersion: "question-behavior-aggregation-v1" },
        dataQuality: { status: "complete" },
        createdAt: "2026-06-14T00:00:03.000Z"
      }
    ],
    sessionBehaviorSummary: {
      summaryId: "session-summary:session-m6-a",
      sessionId: session.sessionId,
      courseType: "matching",
      questionSummaryIds: ["question-summary:session-m6-a:q1"],
      attention: {
        totalObservedMs: 2000,
        screenOrientedRatio: 0.75,
        unavailableRatio: 0,
        quality: { status: "complete" }
      },
      language: {
        responseCount: 1,
        emptyResponseCount: 0,
        repeatedResponseCount: 0,
        medianResponseLatencyMs: 800,
        lowConfidenceTranscriptCount: 0,
        quality: { status: "complete" }
      },
      evidence: [],
      algorithm: { schemaVersion: "m5-behavior-v1", algorithmVersion: "session-behavior-aggregation-v1" },
      dataQuality: { status: "complete" },
      environmentPending: [],
      ownerRequiredBeforeScoring: [],
      createdAt: "2026-06-14T00:00:04.000Z"
    },
    createdAt: "2026-06-14T00:00:05.000Z"
  });

  assert.equal(assessment.metricVersion, "deterministic-assessment-v1");
  assert.equal(assessment.sessionMetrics.firstTryAccuracy, 0.5);
  assert.equal(assessment.sessionMetrics.eventualAccuracy, 1);
  assert.equal(assessment.sessionMetrics.hintDependencyRate, 0.5);
  assert.equal(assessment.questionMetrics[0].attention.screenOrientedRatio, 0.75);
  assert.equal(assessment.questionMetrics[1].dataQuality.status, "partial");
  assert.equal(assessment.scoringStatus, "OWNER_REQUIRED_BEFORE_SCORING");
  assert.ok(assessment.ownerRequiredBeforeScoring.includes("formal_weights"));
  assert.equal(JSON.stringify(assessment).includes("diagnosis"), false);
  assert.equal(JSON.stringify(assessment).includes("percentileRank"), false);
});

test("assessment repository persists generated session assessments", () => {
  behaviorObservationRepository.reset();
  const session = buildSession();
  const generated = generateAssessmentForSession(session);
  const stored = getAssessment(session.sessionId);

  assert.equal(stored.assessmentId, generated.assessmentId);
  assert.equal(stored.dataQuality.status, "partial");
  assert.equal(stored.questionMetrics.length, 2);
});
