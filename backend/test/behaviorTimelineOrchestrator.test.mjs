import assert from "node:assert/strict";
import test from "node:test";

import {
  finalizeSessionBehaviorBeforeReport,
  onAnswerEvaluated,
  onQuestionPresented,
  persistLanguageObservationsFromTranscript,
  resetBehaviorTimelineForTests
} from "../dist/services/behaviorTimelineOrchestratorService.js";
import { behaviorObservationRepository } from "../dist/services/behaviorFrameIngressService.js";
import { createTrainingSession } from "../dist/services/sessionLifecycleService.js";
import { buildCourseQuestions } from "../dist/services/courseService.js";

const startedAt = "2026-06-14T02:00:00.000Z";

function questionPresentedEvent(sessionId, questionId, timestamp = startedAt) {
  return {
    eventId: `evt_qp_${questionId}`,
    eventType: "QUESTION_PRESENTED",
    sessionId,
    timestamp,
    source: "backend",
    correlationId: `corr_${questionId}`,
    causationId: null,
    schemaVersion: "v1",
    persist: true,
    payload: {
      questionId,
      courseType: "matching",
      index: 0,
      total: 2,
      prompt: "Pick same"
    }
  };
}

function answerEvaluatedEvent(sessionId, questionId, correct) {
  return {
    eventId: `evt_ae_${questionId}`,
    eventType: "ANSWER_EVALUATED",
    sessionId,
    timestamp: "2026-06-14T02:00:05.000Z",
    source: "backend",
    correlationId: `corr_${questionId}`,
    causationId: "evt_submit",
    schemaVersion: "v1",
    persist: true,
    payload: {
      questionId,
      correct,
      nextAction: correct ? "NEXT_QUESTION" : "RETRY_SAME_QUESTION"
    }
  };
}

function attentionObservation(sessionId, questionId, id) {
  return {
    observationId: id,
    observationType: "attention",
    sessionId,
    questionId,
    correlationId: `corr_${questionId}`,
    startedAt,
    endedAt: "2026-06-14T02:00:05.000Z",
    observedAt: "2026-06-14T02:00:02.000Z",
    source: "camera",
    provider: "local-browser-face-attention",
    algorithm: {
      schemaVersion: "m5-behavior-v1",
      algorithmVersion: "local-browser-attention-v1"
    },
    features: {
      kind: "screen_orientation",
      facePresent: true,
      faceCount: 1,
      roughlyFacingScreen: true,
      durationMs: 1000,
      imageQuality: "good",
      cameraAvailable: true
    },
    confidence: 0.9,
    dataQuality: { status: "complete", providerStatus: "ok" },
    degraded: false,
    evidence: [],
    createdAt: startedAt
  };
}

test("behavior timeline orchestrator opens window, aggregates on answer, and persists language", () => {
  behaviorObservationRepository.reset();
  resetBehaviorTimelineForTests();

  const session = createTrainingSession({
    childName: "Test",
    courseType: "matching",
    questions: buildCourseQuestions("matching").slice(0, 2)
  });
  const questionId = session.questions[0].id;

  onQuestionPresented(questionPresentedEvent(session.sessionId, questionId));
  behaviorObservationRepository.saveObservation(attentionObservation(session.sessionId, questionId, "att-1"));

  persistLanguageObservationsFromTranscript({
    sessionId: session.sessionId,
    turnId: "turn-1",
    correlationId: "corr-turn-1",
    transcriptRedacted: "我想选这个",
    confidence: 0.88,
    observedAt: "2026-06-14T02:00:03.000Z"
  });

  onAnswerEvaluated(answerEvaluatedEvent(session.sessionId, questionId, true));

  let summaries = behaviorObservationRepository.listQuestionSummaries(session.sessionId);
  assert.equal(summaries.length, 0);

  const nextQuestionId = session.questions[1].id;
  onQuestionPresented(questionPresentedEvent(session.sessionId, nextQuestionId, "2026-06-14T02:00:10.000Z"));
  behaviorObservationRepository.saveObservation(attentionObservation(session.sessionId, nextQuestionId, "att-2"));

  summaries = behaviorObservationRepository.listQuestionSummaries(session.sessionId);
  assert.equal(summaries.length, 1);
  assert.equal(summaries[0].questionId, questionId);
  assert.ok(summaries[0].attention);
  assert.ok(summaries[0].language);

  finalizeSessionBehaviorBeforeReport(session.sessionId, session.courseType);
  const sessionSummary = behaviorObservationRepository.getSessionSummary(session.sessionId);
  assert.ok(sessionSummary);
  assert.equal(sessionSummary.questionSummaryIds.length, 2);
});
