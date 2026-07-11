import { getSession as getStoredSession, saveSession } from "./sessionLifecycleService.js";
import { runVoiceAssistant, type VoiceAssistantResult } from "./voice/voiceOrchestrator.js";
import {
  minimizeAndRedact,
  reviewAssistantResult,
  runChildSafeLlmTurn
} from "./llmSafetyGatewayService.js";
import { persistLanguageObservationsFromTranscript } from "./behaviorTimelineOrchestratorService.js";
import type { ChatMessageContext } from "./voice/types.js";
import type { Session } from "../types.js";

type VoiceAssistantRunner = (input: {
  childText: string;
  history: ChatMessageContext[];
  pageContextText?: string;
}) => Promise<VoiceAssistantResult>;

type ChatPageContext = {
  courseType: "matching" | "ordering";
  questionIndex: number;
  totalQuestions: number;
  prompt: string;
  target: string;
  targetDescription?: string;
  options: Array<{ id: string; label: string; description?: string }>;
  interaction: {
    selectedOptionIds: string[];
    wrongAttempts: number;
    helpRequestCount?: number;
    elapsedMs: number;
  };
  correctOption?: {
    id: string;
    label: string;
    position: number;
    description?: string;
  };
  narrative: string;
};

const FALLBACK_REPLY = "这个内容我不能继续聊。我们回到当前题目吧。";

function buildCountingReply(childText: string, pageContext?: ChatPageContext): VoiceAssistantResult | null {
  if (!pageContext || pageContext.courseType !== "ordering") return null;
  if (!/(多少|几个|数一数|数一下|左边|右边)/.test(childText)) return null;

  const counts = pageContext.options
    .map((option, index) => {
      const side = index === 0 ? "左边" : index === 1 ? "右边" : `第${index + 1}张`;
      const match = option.description?.match(/有(\d+)个(.+)$/);
      if (!match) return null;
      return `${side}有${match[1]}个${match[2]}`;
    })
    .filter((item): item is string => Boolean(item));

  if (counts.length < 2) return null;
  return {
    reply: `${counts.join("，")}。你数得很认真！`,
    strategy: "rule_counting",
    provider: "rule",
    timestamp: new Date().toISOString()
  };
}

export function buildChatAssistantHistory(session: Session): ChatMessageContext[] {
  return session.chatHistory.slice(-8).map((entry) => ({
    role: entry.role === "bot" ? "assistant" : "user",
    text: entry.text
  }));
}

export async function persistChildTranscriptObservations(
  sessionId: string,
  text: string,
  options: { turnId?: string; correlationId?: string; confidence?: number } = {}
) {
  const session = getStoredSession(sessionId);
  if (session.state !== "TRAINING_ACTIVE") {
    throw new Error("Course already completed");
  }
  const childText = text.trim();
  if (!childText) return { persisted: false as const };

  const turnId = options.turnId ?? `voice_obs_${Date.now().toString(36)}_${session.chatHistory.length}`;
  const correlationId = options.correlationId ?? `voice-obs:${sessionId}:${turnId}`;
  const preMessageHistory = buildChatAssistantHistory(session);
  const minimized = minimizeAndRedact(childText, preMessageHistory);

  persistLanguageObservationsFromTranscript({
    sessionId,
    turnId,
    correlationId,
    transcriptRedacted: minimized.childTextRedacted,
    confidence: options.confidence ?? (minimized.childTextRedacted.length > 0 ? 0.85 : 0),
    observedAt: new Date().toISOString()
  });

  return { persisted: true as const, turnId, transcriptRedacted: minimized.childTextRedacted };
}

function createChatFallback(): VoiceAssistantResult {
  return {
    reply: FALLBACK_REPLY,
    strategy: "fallback",
    provider: "rule",
    timestamp: new Date().toISOString()
  };
}

function buildPageContextForPrompt(pageContext?: ChatPageContext) {
  if (!pageContext) return undefined;
  const selected =
    pageContext.interaction.selectedOptionIds.length > 0 ? pageContext.interaction.selectedOptionIds.join("、") : "尚未选择";
  const options = pageContext.options
    .map((option, index) => `下面第${index + 1}张（${option.id}）：${option.label}${option.description ? `，${option.description}` : ""}`)
    .join("；");
  const helpCount = pageContext.interaction.helpRequestCount ?? 0;
  const supportLevel =
    helpCount <= 1 && pageContext.interaction.wrongAttempts <= 0
      ? "LEVEL_1_OBSERVE：第一次不会或刚开始困难，只提示看哪里，不直接说答案。"
      : helpCount <= 2 && pageContext.interaction.wrongAttempts <= 1
        ? "LEVEL_2_DESCRIBE：已经多次求助或答错一次，请说清上面图片和下面图片哪里像。"
        : "LEVEL_3_DIRECT：儿童持续困难，请直接告诉应该点下面第几张。";
  return [
    pageContext.narrative,
    `给AI看的内部信息：不要把字段名说给孩子听。`,
    `玩法：${pageContext.courseType === "matching" ? "找一样的图片" : "按规则找图片"}`,
    `现在是第 ${pageContext.questionIndex}/${pageContext.totalQuestions} 题`,
    `孩子听到的问题：${pageContext.prompt}`,
    `上面的图片：${pageContext.target}${pageContext.targetDescription ? `，${pageContext.targetDescription}` : ""}`,
    `下面从左到右的图片：${options || "无"}`,
    `孩子已经点过：${selected}`,
    `点错次数：${pageContext.interaction.wrongAttempts}`,
    `孩子求助次数：${helpCount}`,
    `辅助层级：${supportLevel}`,
    pageContext.correctOption
      ? `应该点：下面第${pageContext.correctOption.position}张，${pageContext.correctOption.label}${pageContext.correctOption.description ? `，${pageContext.correctOption.description}` : ""}`
      : "应该点：未知"
  ].join("\n");
}

export async function sendChatMessage(
  sessionId: string,
  text: string,
  options: { runAssistant?: VoiceAssistantRunner; pageContext?: ChatPageContext } = {}
) {
  const session = getStoredSession(sessionId);
  if (session.state !== "TRAINING_ACTIVE") {
    throw new Error("Course already completed");
  }

  const childText = text.trim();
  const preMessageHistory = buildChatAssistantHistory(session);
  const minimized = minimizeAndRedact(childText, preMessageHistory);
  const turnId = `chat_${Date.now().toString(36)}_${session.chatHistory.length}`;
  session.chatHistory.push({
    role: "child",
    text: minimized.childTextRedacted,
    timestamp: new Date().toISOString()
  });
  const questionId = session.questions[session.currentQuestionIndex]?.id;
  persistLanguageObservationsFromTranscript({
    sessionId,
    turnId,
    correlationId: `chat:${sessionId}:${turnId}`,
    transcriptRedacted: minimized.childTextRedacted,
    confidence: minimized.childTextRedacted.length > 0 ? 0.85 : 0,
    observedAt: new Date().toISOString()
  });

  const history = buildChatAssistantHistory(session);
  const pageContextText = buildPageContextForPrompt(options.pageContext);
  const countingReply = buildCountingReply(minimized.childTextRedacted, options.pageContext);
  const reply = countingReply
    ? countingReply
    : options.runAssistant
    ? await options
        .runAssistant({ childText: minimized.childTextRedacted, history, pageContextText })
        .catch(() => createChatFallback())
        .then((result) =>
          reviewAssistantResult({
            sessionId,
            turnId,
            childText,
            result,
            history
          })
        )
    : await runChildSafeLlmTurn({
        sessionId,
        turnId,
        questionId,
        childText,
        history,
        pageContextText
      });

  session.chatHistory.push({
    role: "bot",
    text: reply.reply,
    strategy: reply.strategy,
    timestamp: reply.timestamp
  });
  saveSession(session);

  return reply;
}

export { runVoiceAssistant };
