import type { DomainEvent } from "child-education-training-demo/shared/domain-events";
import type { QuestionPresentedPayload, AnswerEvaluatedPayload } from "child-education-training-demo/shared/domain-events";
import { aggregateQuestionBehavior, aggregateSessionBehavior } from "./behaviorAggregationService.js";
import { behaviorObservationRepository } from "./behaviorFrameIngressService.js";
import { createQuestionObservationWindow } from "./behaviorTimelineService.js";
import { extractDeterministicLanguageFeatures } from "./languageFeatureService.js";
import { findSession, getSession as getStoredSession } from "./sessionLifecycleService.js";

interface OpenQuestionWindow {
  sessionId: string;
  questionId: string;
  correlationId: string;
  questionPresentedEventId: string;
  startedAt: string;
  additionalEventIds: string[];
}

const openWindowsBySession = new Map<string, OpenQuestionWindow>();

export function resetBehaviorTimelineForTests() {
  openWindowsBySession.clear();
}

export function getOpenQuestionWindow(sessionId: string) {
  return openWindowsBySession.get(sessionId);
}

export function onQuestionPresented(event: DomainEvent) {
  if (event.eventType !== "QUESTION_PRESENTED") return;
  const payload = event.payload as QuestionPresentedPayload;
  const existing = openWindowsBySession.get(event.sessionId);
  if (existing && existing.questionId !== payload.questionId) {
    closeQuestionWindow(existing, event.timestamp);
  }
  if (existing?.questionId === payload.questionId) return;

  openWindowsBySession.set(event.sessionId, {
    sessionId: event.sessionId,
    questionId: payload.questionId,
    correlationId: event.correlationId,
    questionPresentedEventId: event.eventId,
    startedAt: event.timestamp,
    additionalEventIds: []
  });
}

export function onAnswerEvaluated(event: DomainEvent) {
  if (event.eventType !== "ANSWER_EVALUATED") return;
  const payload = event.payload as AnswerEvaluatedPayload;
  const open = openWindowsBySession.get(event.sessionId);
  if (!open || open.questionId !== payload.questionId) return;

  if (payload.hintId) {
    open.additionalEventIds.push(payload.hintId);
    return;
  }

  // Keep the question window open until the next QUESTION_PRESENTED (or session end).
  // Closing on answer cuts off camera frames that still carry this questionId for ~1–2s
  // while the child screen transitions and the camera restarts.
}

export function onSessionEnded(sessionId: string, courseType: string, endedAt: string) {
  const open = openWindowsBySession.get(sessionId);
  if (open) {
    closeQuestionWindow(open, endedAt);
    openWindowsBySession.delete(sessionId);
  }
  persistSessionSummary(sessionId, courseType);
}

export function finalizeSessionBehaviorBeforeReport(sessionId: string, courseType: string) {
  const open = openWindowsBySession.get(sessionId);
  if (open) {
    closeQuestionWindow(open, new Date().toISOString());
    openWindowsBySession.delete(sessionId);
  }
  persistSessionSummary(sessionId, courseType);
}

export function persistLanguageObservationsFromTranscript(input: {
  sessionId: string;
  turnId: string;
  correlationId: string;
  transcriptRedacted: string;
  confidence?: number;
  audioDurationMs?: number;
  duplicateOfTurnId?: string;
  observedAt?: string;
}) {
  const session = findSession(input.sessionId);
  const questionId = session?.questions[session.currentQuestionIndex]?.id;
  const open = openWindowsBySession.get(input.sessionId);
  const observedAt = input.observedAt ?? new Date().toISOString();
  const observations = extractDeterministicLanguageFeatures({
    observationId: `language:${input.sessionId}:${input.turnId}`,
    sessionId: input.sessionId,
    questionId: open?.questionId ?? questionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    windowId: open ? `window:${input.sessionId}:${open.questionId}` : undefined,
    transcriptRedacted: input.transcriptRedacted,
    confidence: input.confidence,
    audioDurationMs: input.audioDurationMs,
    duplicateOfTurnId: input.duplicateOfTurnId,
    observedAt
  });
  for (const observation of observations) {
    behaviorObservationRepository.saveObservation(observation);
  }
  return observations.length;
}

function closeQuestionWindow(open: OpenQuestionWindow, completedAt: string) {
  const observations = behaviorObservationRepository.listObservations(open.sessionId);
  const window = createQuestionObservationWindow({
    sessionId: open.sessionId,
    questionId: open.questionId,
    correlationId: open.correlationId,
    questionPresentedEventId: open.questionPresentedEventId,
    startedAt: open.startedAt,
    completedAt,
    observations,
    additionalEventIds: open.additionalEventIds
  });
  behaviorObservationRepository.saveWindow(window);
  const summary = aggregateQuestionBehavior({
    sessionId: open.sessionId,
    questionId: open.questionId,
    correlationId: open.correlationId,
    window,
    observations
  });
  behaviorObservationRepository.saveQuestionSummary(summary);
}

function persistSessionSummary(sessionId: string, courseType: string) {
  const summaries = behaviorObservationRepository.listQuestionSummaries(sessionId);
  if (summaries.length === 0) return;
  const existing = behaviorObservationRepository.getSessionSummary(sessionId);
  if (existing && existing.questionSummaryIds.length >= summaries.length) return;
  const sessionSummary = aggregateSessionBehavior({
    sessionId,
    courseType,
    questionSummaries: summaries
  });
  behaviorObservationRepository.saveSessionSummary(sessionSummary);
}
