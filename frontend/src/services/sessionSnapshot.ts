import { apiRequest } from "./api";
import type { CourseQuestion, CourseType } from "../types";
import type { DomainEvent } from "child-education-training-demo/shared/domain-events";

export interface SessionSnapshot {
  session: {
    sessionId: string;
    childName: string;
    courseType: CourseType;
    state: "TRAINING_ACTIVE" | "TRAINING_FINISHED";
    startedAt: string;
    completedAt: string | null;
    currentQuestionIndex: number;
    correctAnswers: number;
    totalWrongAttempts: number;
  };
  currentQuestion: CourseQuestion | null;
  events: DomainEvent[];
  lastEventId: string | null;
}

export interface LatestSessionInfo {
  sessionId: string;
  state: "TRAINING_ACTIVE" | "TRAINING_FINISHED";
  startedAt: string;
  courseType: CourseType;
}

export function getSessionSnapshot(sessionId: string, afterEventId?: string) {
  const query = afterEventId ? `?afterEventId=${encodeURIComponent(afterEventId)}` : "";
  return apiRequest<SessionSnapshot>(`/session/${sessionId}/snapshot${query}`);
}

export function getLatestSessionInfo() {
  return apiRequest<LatestSessionInfo | null>("/session/active/latest");
}

export async function resolveRobotScreenSessionId(pinnedSessionId: string | null, storedSessionId: string) {
  if (pinnedSessionId) return pinnedSessionId;

  const latestSession = await getLatestSessionInfo().catch(() => null);
  if (latestSession?.state === "TRAINING_ACTIVE") {
    return latestSession.sessionId;
  }
  if (storedSessionId) return storedSessionId;
  return latestSession?.sessionId ?? "";
}
