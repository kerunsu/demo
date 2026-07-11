import { apiRequest } from "./api";
import type {
  AnswerResult,
  ChatReply,
  CourseQuestion,
  SessionInfo,
  StartSessionRequest,
  TrainingReport
} from "../types";
import type { VoiceTurnPageContextText } from "child-education-training-demo/shared/voice-partner-contract";

export function startSession(payload: StartSessionRequest) {
  return apiRequest<SessionInfo>("/session/start", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getCurrentQuestion(sessionId: string) {
  return apiRequest<CourseQuestion>(`/course/${sessionId}/current`);
}

export function submitAnswer(
  sessionId: string,
  questionId: string,
  selectedOptionId: string,
  responseTimeMs: number
) {
  return apiRequest<AnswerResult>(`/course/${sessionId}/answer`, {
    method: "POST",
    body: JSON.stringify({
      questionId,
      answer: { selectedOptionId },
      responseTimeMs
    })
  });
}

export function generateReport(sessionId: string) {
  return apiRequest<{ reportId: string; sessionId: string; status: string }>(
    `/report/${sessionId}/generate`,
    { method: "POST" }
  );
}

export function getReport(sessionId: string) {
  return apiRequest<TrainingReport>(`/report/${sessionId}`);
}

export function sendChatMessage(sessionId: string, text: string, pageContext?: VoiceTurnPageContextText) {
  return apiRequest<ChatReply>(`/chat/${sessionId}/message`, {
    method: "POST",
    body: JSON.stringify({ text, pageContext })
  });
}
