import type { CourseQuestion, CourseType, Session } from "../types.js";
import { loadPersistentSession, savePersistentSession } from "./sqlitePersistenceService.js";

const sessions = new Map<string, Session>();

function createSessionId() {
  return `sess_${Math.random().toString(36).slice(2, 10)}`;
}

export function createTrainingSession(input: {
  childName: string;
  courseType: CourseType;
  questions: CourseQuestion[];
}) {
  const sessionId = createSessionId();
  const startedAt = new Date().toISOString();
  const session: Session = {
    sessionId,
    childName: input.childName,
    courseType: input.courseType,
    startedAt,
    completedAt: null,
    currentQuestionIndex: 0,
    correctAnswers: 0,
    totalWrongAttempts: 0,
    responseTimes: [],
    questions: input.questions,
    questionStats: input.questions.map((question) => ({
      questionId: question.id,
      attempts: 0,
      correct: false,
      responseTimeMs: 0,
      wrongTypes: []
    })),
    chatHistory: [],
    state: "TRAINING_ACTIVE",
    lastPresentedQuestionId: undefined
  };
  sessions.set(sessionId, session);
  savePersistentSession(session);
  return session;
}

export function getSession(sessionId: string) {
  const session = sessions.get(sessionId) ?? loadPersistentSession(sessionId);
  if (!session) {
    throw new Error("Session not found");
  }
  sessions.set(sessionId, session);
  return session;
}

export function findSession(sessionId: string) {
  const session = sessions.get(sessionId) ?? loadPersistentSession(sessionId);
  if (!session) return null;
  sessions.set(sessionId, session);
  return session;
}

export function getLatestTrainingSession() {
  const ordered = Array.from(sessions.values()).sort((left, right) => right.startedAt.localeCompare(left.startedAt));
  return ordered.find((session) => session.state === "TRAINING_ACTIVE") ?? ordered[0] ?? null;
}

export function completeSession(session: Session) {
  session.state = "TRAINING_FINISHED";
  session.completedAt = new Date().toISOString();
  savePersistentSession(session);
  return session;
}

export function saveSession(session: Session) {
  sessions.set(session.sessionId, session);
  savePersistentSession(session);
  return session;
}
