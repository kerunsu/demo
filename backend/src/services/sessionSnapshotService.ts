import { getSession } from "./sessionLifecycleService.js";
import { getCurrentQuestionSnapshot } from "./courseService.js";
import { getSessionEvents } from "./domainEventService.js";

export function getSessionSnapshot(sessionId: string, afterEventId?: string) {
  const session = getSession(sessionId);
  const currentQuestion =
    session.state === "TRAINING_ACTIVE" ? getCurrentQuestionSnapshot(session) : null;
  return {
    session: {
      sessionId: session.sessionId,
      childName: session.childName,
      courseType: session.courseType,
      state: session.state,
      startedAt: session.startedAt,
      completedAt: session.completedAt,
      currentQuestionIndex: session.currentQuestionIndex,
      correctAnswers: session.correctAnswers,
      totalWrongAttempts: session.totalWrongAttempts
    },
    currentQuestion,
    events: getSessionEvents(sessionId, afterEventId),
    lastEventId: getSessionEvents(sessionId).at(-1)?.eventId ?? null
  };
}
