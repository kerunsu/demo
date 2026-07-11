export const VOICE_PARTNER_TURN_SCHEMA = "voice-partner-turn-v1" as const;
export const VOICE_PAGE_CONTEXT_SCHEMA = "voice-page-context-v1" as const;

export type VoiceDialogProviderKind = "rule" | "partner";

export interface VoiceTurnPageContextText {
  schemaVersion: typeof VOICE_PAGE_CONTEXT_SCHEMA;
  courseType: "matching" | "ordering";
  questionIndex: number;
  totalQuestions: number;
  prompt: string;
  target: string;
  targetDescription?: string;
  targetImageUrl?: string;
  options: Array<{ id: string; label: string; imageUrl?: string; description?: string }>;
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
}

export interface VoiceTurnScreenshot {
  mimeType: "image/jpeg" | "image/png";
  base64: string;
  width: number;
  height: number;
}

export interface VoiceTurnPageContextPayload {
  text: VoiceTurnPageContextText;
  screenshot: VoiceTurnScreenshot | null;
  screenshotUnavailableReason?: string;
}

export interface VoicePartnerTurnHistoryMessage {
  role: "user" | "assistant";
  text: string;
}

export interface VoicePartnerTurnRequest {
  schemaVersion: typeof VOICE_PARTNER_TURN_SCHEMA;
  sessionId: string;
  turnId: string;
  correlationId: string;
  capturedAt: string;
  audio: {
    base64: string;
    mimeType: string;
    durationMs: number;
  };
  pageContext: VoiceTurnPageContextPayload;
  history: VoicePartnerTurnHistoryMessage[];
  locale: string;
}

export interface VoicePartnerTurnSuccess {
  ok: true;
  replyText: string;
  replyAudio?: {
    base64: string;
    mimeType: string;
  };
  metadata?: {
    provider?: string;
    latencyMs?: number;
    sttModeUsed?: string;
  };
}

export interface VoicePartnerTurnFailure {
  ok: false;
  error: {
    code: string;
    message: string;
  };
}

export type VoicePartnerTurnResponse = VoicePartnerTurnSuccess | VoicePartnerTurnFailure;

export const VOICE_PARTNER_MAX_SCREENSHOT_BYTES = 500_000;

export type BuildPageContextInput = {
  courseType: "matching" | "ordering";
  questionIndex: number;
  totalQuestions: number;
  prompt: string;
  target: string;
  targetDescription?: string;
  targetImageUrl?: string;
  options: Array<{ id: string; label: string; imageUrl?: string; description?: string }>;
  wrongAttempts: number;
  helpRequestCount?: number;
  questionElapsedMs: number;
  selectedOptionIds: string[];
  correctOptionId?: string;
};

export function buildPageContextText(input: BuildPageContextInput): VoiceTurnPageContextText {
  const narrative = buildPageContextNarrative(input);
  return {
    schemaVersion: VOICE_PAGE_CONTEXT_SCHEMA,
    courseType: input.courseType,
    questionIndex: input.questionIndex,
    totalQuestions: input.totalQuestions,
    prompt: input.prompt,
    target: input.target,
    targetDescription: input.targetDescription,
    targetImageUrl: input.targetImageUrl,
    options: input.options,
    interaction: {
      selectedOptionIds: input.selectedOptionIds,
      wrongAttempts: input.wrongAttempts,
      helpRequestCount: input.helpRequestCount,
      elapsedMs: input.questionElapsedMs
    },
    correctOption: buildCorrectOption(input),
    narrative
  };
}

export function buildPageContextNarrative(input: BuildPageContextInput) {
  const courseLabel = input.courseType === "matching" ? "找一样的图片" : "按规则找图片";
  const targetText = input.targetDescription ? `${input.target}（${input.targetDescription}）` : input.target;
  const optionText =
    input.options
      .map((option, index) => `下面第${index + 1}张：${option.label}${option.description ? `（${option.description}）` : ""}`)
      .join("；") || "下面没有图片";
  const selectionText = input.selectedOptionIds.length > 0 ? `孩子点过：${input.selectedOptionIds.join("、")}。` : "孩子还没点。";
  const attemptText = input.wrongAttempts > 0 ? `已经点错 ${input.wrongAttempts} 次。` : "";
  const helpText = input.helpRequestCount && input.helpRequestCount > 0 ? `孩子说不会 ${input.helpRequestCount} 次。` : "";
  const correct = buildCorrectOption(input);
  const answerText = correct ? `应该点下面第${correct.position}张：${correct.label}。` : "";
  return `现在玩${courseLabel}，第 ${input.questionIndex}/${input.totalQuestions} 题。孩子听到：${input.prompt}。上面的图片：${targetText}。下面的图片：${optionText}。${selectionText}${attemptText}${helpText}${answerText}`;
}

function buildCorrectOption(input: BuildPageContextInput) {
  if (!input.correctOptionId) return undefined;
  const index = input.options.findIndex((option) => option.id === input.correctOptionId);
  if (index < 0) return undefined;
  const option = input.options[index];
  return {
    id: option.id,
    label: option.label,
    position: index + 1,
    description: option.description
  };
}
