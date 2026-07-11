import { createTrainingSession, getLatestTrainingSession, getSession as getStoredSession, saveSession } from "./sessionLifecycleService.js";
import { buildCourseQuestions, getCurrentQuestionSnapshot, submitCourseAnswer } from "./courseService.js";
import {
  chooseAnimationForAnswer,
  publishDomainEvent,
  registerFeedbackTurn
} from "./domainEventService.js";
import { recordVoiceMetric } from "./voiceObservabilityService.js";
import {
  onAnswerEvaluated,
  onQuestionPresented,
  onSessionEnded
} from "./behaviorTimelineOrchestratorService.js";

export function startSession(childName: string, courseType: "matching" | "ordering") {
  const questions = buildCourseQuestions(courseType);
  const session = createTrainingSession({ childName, courseType, questions });
  const sessionEvent = publishDomainEvent({
    eventType: "SESSION_STARTED",
    sessionId: session.sessionId,
    source: "backend",
    payload: {
      childAlias: childName,
      courseQueue: [courseType],
      startedAt: session.startedAt
    }
  });
  const firstQuestionEvent = publishQuestionPresented(session.sessionId, sessionEvent.eventId);
  if (firstQuestionEvent) onQuestionPresented(firstQuestionEvent);
  return {
    sessionId: session.sessionId,
    state: session.state,
    startedAt: session.startedAt,
    courseType: session.courseType
  };
}

export { getSession } from "./sessionLifecycleService.js";

export function getLatestSessionInfo() {
  const session = getLatestTrainingSession();
  if (!session) return null;
  return {
    sessionId: session.sessionId,
    state: session.state,
    startedAt: session.startedAt,
    courseType: session.courseType
  };
}

export function getCurrentQuestion(sessionId: string) {
  const session = getStoredSession(sessionId);
  const snapshot = getCurrentQuestionSnapshot(session);
  if (session.lastPresentedQuestionId !== snapshot.questionId) {
    const event = publishQuestionPresented(sessionId);
    if (event) onQuestionPresented(event);
  }
  return snapshot;
}

export function submitAnswer(
  sessionId: string,
  questionId: string,
  selectedOptionId: string,
  responseTimeMs: number
) {
  const session = getStoredSession(sessionId);
  const questionBeforeAnswer = session.questions[session.currentQuestionIndex];
  const statBefore = session.questionStats[session.currentQuestionIndex];
  const submitted = publishDomainEvent({
    eventType: "ANSWER_SUBMITTED",
    sessionId,
    source: "child_screen",
    idempotencyKey: `${sessionId}:${questionId}:${selectedOptionId}:${statBefore.attempts + 1}`,
    payload: {
      questionId,
      selectedOptionId,
      responseTimeMs,
      attemptIndex: statBefore.attempts + 1
    }
  });
  const result = submitCourseAnswer(session, questionId, selectedOptionId, responseTimeMs);
  const evaluated = publishDomainEvent({
    eventType: "ANSWER_EVALUATED",
    sessionId,
    source: "backend",
    correlationId: submitted.correlationId,
    causationId: submitted.eventId,
    payload: {
      questionId,
      correct: result.correct,
      wrongType: result.correct ? undefined : questionBeforeAnswer.errorTypeOnWrong,
      nextAction: result.courseCompleted
        ? "FINISH_COURSE"
        : result.correct
          ? "NEXT_QUESTION"
          : "RETRY_SAME_QUESTION",
      hintId: result.hint ? `${questionId}:hint` : undefined
    }
  });
  onAnswerEvaluated(evaluated);
  const animation = chooseAnimationForAnswer(result.correct, result.courseCompleted);
  const commandId = `anim_${evaluated.eventId}`;
  const feedback = publishDomainEvent({
    eventType: "FEEDBACK_REQUESTED",
    sessionId,
    source: "backend",
    correlationId: submitted.correlationId,
    causationId: evaluated.eventId,
    payload: {
      feedbackKind: result.correct ? "praise" : result.hint ? "hint" : "encouragement",
      text: result.feedback,
      requiresSpeech: true,
      animationIntent: animation.intent
    }
  });
  const speechTurnId = `tts_${feedback.eventId}`;
  recordVoiceMetric({
    sessionId,
    turnId: speechTurnId,
    correlationId: submitted.correlationId,
    stage: "chat_reply_generated",
    provider: "rule-feedback",
    model: "course-feedback-v1",
    textForHash: result.feedback,
    metadata: {
      feedbackKind: result.correct ? "praise" : result.hint ? "hint" : "encouragement",
      courseCompleted: result.courseCompleted
    }
  });
  publishDomainEvent({
    eventType: "ANIMATION_REQUESTED",
    sessionId,
    source: "backend",
    correlationId: submitted.correlationId,
    causationId: feedback.eventId,
    payload: {
      commandId,
      animationId: animation.animationId,
      intent: animation.intent,
      priority: result.courseCompleted ? 3 : 2,
      interruptPolicy: "interrupt"
    }
  });
  registerFeedbackTurn({
    sessionId,
    commandId,
    speechTurnId,
    timeoutMs: 4000,
    onComplete: () => {
      if (result.courseCompleted) {
        const endedAt = session.completedAt ?? new Date().toISOString();
        publishDomainEvent({
          eventType: "SESSION_ENDED",
          sessionId,
          source: "backend",
          causationId: evaluated.eventId,
          payload: {
            reason: "completed",
            endedAt
          }
        });
        onSessionEnded(sessionId, session.courseType, endedAt);
        return;
      }
      if (result.correct) {
        const nextQuestionEvent = publishQuestionPresented(sessionId, evaluated.eventId);
        if (nextQuestionEvent) onQuestionPresented(nextQuestionEvent);
      }
    }
  });
  return result;
}

export { generateReport, getReport } from "./reportService.js";
export { getAssessment } from "./assessmentService.js";
export { sendChatMessage } from "./chatService.js";

function publishQuestionPresented(sessionId: string, causationId?: string) {
  const session = getStoredSession(sessionId);
  if (session.state !== "TRAINING_ACTIVE") return null;
  const snapshot = getCurrentQuestionSnapshot(session);
  if (session.lastPresentedQuestionId === snapshot.questionId) return null;
  session.lastPresentedQuestionId = snapshot.questionId;
  saveSession(session);
  return publishDomainEvent({
    eventType: "QUESTION_PRESENTED",
    sessionId,
    source: "backend",
    causationId: causationId ?? null,
    payload: {
      questionId: snapshot.questionId,
      courseType: snapshot.courseType,
      index: snapshot.index,
      total: snapshot.total,
      prompt: snapshot.prompt
    }
  });
}
