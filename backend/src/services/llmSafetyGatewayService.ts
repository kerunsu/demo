import {
  MockChildSafetyProvider,
  MockLlmProvider,
  type ChildSafetyProvider,
  type LlmProvider,
  type SafetyReviewAction
} from "child-education-training-demo/shared/providers";
import { runtimeConfig } from "../config/runtime.js";
import type { VoiceAssistantResult } from "./voice/voiceOrchestrator.js";
import type { ChatMessageContext } from "./voice/types.js";
import { AsdAgentLlmProvider } from "./voice/providers/asdAgentProvider.js";

export const CHILD_SAFETY_POLICY_VERSION = "m6-child-safety-v1";
const FALLBACK_REPLY = "这个内容我不能继续聊。我们回到当前题目吧。";
const ADULT_HELP_REPLY = "这个问题需要老师或家长帮忙。我们先暂停一下，请老师或家长来看一看。";

export interface LlmGatewayAuditRecord {
  requestId: string;
  sessionId: string;
  turnId: string;
  provider: string;
  status: "PASS" | "REJECT" | "TIMEOUT" | "ERROR" | "CREDENTIALS_PENDING";
  inputAction: SafetyReviewAction | "error";
  outputAction: SafetyReviewAction | "error";
  piiTypes: string[];
  reasonCodes: string[];
  inputLength: number;
  minimizedHistoryCount: number;
  latencyMs: number;
  externalNetworkCalled: boolean;
  tokenUsage?: {
    inputTokensApprox: number;
    outputTokensApprox: number;
  };
  createdAt: string;
}

export interface LlmGatewayResult extends VoiceAssistantResult {
  safetyStatus: LlmGatewayAuditRecord["status"];
  policyVersion: string;
  auditId: string;
}

const auditRecords = new Map<string, LlmGatewayAuditRecord[]>();
const defaultSafetyProvider = new MockChildSafetyProvider();
const defaultMockLlmProvider = new MockLlmProvider();
const defaultAsdLlmProvider = new AsdAgentLlmProvider();

export async function runChildSafeLlmTurn(input: {
  sessionId: string;
  turnId: string;
  childText: string;
  history: ChatMessageContext[];
  questionId?: string;
  pageContextText?: string;
  llmProvider?: LlmProvider;
  safetyProvider?: ChildSafetyProvider;
}): Promise<LlmGatewayResult> {
  const started = Date.now();
  const requestId = `llm:${input.sessionId}:${input.turnId}`;
  const minimized = minimizeAndRedact(input.childText, input.history);
  const safetyProvider = input.safetyProvider ?? defaultSafetyProvider;
  const inputDecision = reviewText("input", requestId, minimized.childTextRedacted);
  if (inputDecision.action === "fallback" || inputDecision.action === "block" || inputDecision.action === "escalate_to_adult") {
    return recordAndReturn({
      requestId,
      sessionId: input.sessionId,
      turnId: input.turnId,
      provider: "rule-safety",
      status: "REJECT",
      inputAction: inputDecision.action,
      outputAction: "fallback",
      piiTypes: [...minimized.piiTypes, ...inputDecision.piiTypes],
      reasonCodes: inputDecision.reasonCodes,
      inputLength: input.childText.length,
      minimizedHistoryCount: minimized.historyRedacted.length,
      latencyMs: Date.now() - started,
      externalNetworkCalled: false,
      reply: inputDecision.action === "escalate_to_adult" ? ADULT_HELP_REPLY : FALLBACK_REPLY,
      strategy: "safety_fallback",
      providerName: "rule-safety"
    });
  }

  const inputReview = await safetyProvider.review({
    requestId: `${requestId}:input`,
    target: "input",
    textRedacted: minimized.childTextRedacted,
    policyVersion: CHILD_SAFETY_POLICY_VERSION
  }).catch((error) => ({ ok: false as const, error }));

  if (!inputReview.ok || inputReview.data.action === "fallback" || inputReview.data.action === "block") {
    return recordAndReturn({
      requestId,
      sessionId: input.sessionId,
      turnId: input.turnId,
      provider: inputReview.ok ? inputReview.metadata.providerName : "mock-safety",
      status: inputReview.ok ? "REJECT" : inputReview.error?.code === "TIMEOUT" ? "TIMEOUT" : "ERROR",
      inputAction: inputReview.ok ? inputReview.data.action : "error",
      outputAction: "fallback",
      piiTypes: inputReview.ok ? [...minimized.piiTypes, ...inputReview.data.piiTypes] : minimized.piiTypes,
      reasonCodes: inputReview.ok ? inputReview.data.reasonCodes : ["input_safety_provider_failed"],
      inputLength: input.childText.length,
      minimizedHistoryCount: minimized.historyRedacted.length,
      latencyMs: Date.now() - started,
      externalNetworkCalled: inputReview.ok ? inputReview.metadata.dataSafety?.externalNetworkCalled ?? false : false,
      reply: inputReview.ok ? inputReview.data.fallbackText ?? FALLBACK_REPLY : FALLBACK_REPLY,
      strategy: "safety_fallback",
      providerName: "rule-safety"
    });
  }

  if (!input.llmProvider && runtimeConfig.chatProvider === "rule") {
    return reviewOutputAndRecord({
      requestId,
      sessionId: input.sessionId,
      turnId: input.turnId,
      replyDraft: buildRuleReply(minimized.childTextRedacted, input.pageContextText),
      strategy: "rule",
      provider: "rule",
      started,
      inputLength: input.childText.length,
      minimizedHistoryCount: minimized.historyRedacted.length,
      piiTypes: [...minimized.piiTypes, ...inputReview.data.piiTypes],
      reasonCodes: [],
      status: "PASS",
      safetyProvider
    });
  }

  const llmProvider = input.llmProvider ?? (runtimeConfig.chatProvider === "asd" ? defaultAsdLlmProvider : defaultMockLlmProvider);
  if (runtimeConfig.chatProvider === "asd" && !runtimeConfig.asdLlmApiKey) {
    return reviewOutputAndRecord({
      requestId,
      sessionId: input.sessionId,
      turnId: input.turnId,
      replyDraft: buildRuleReply(minimized.childTextRedacted, input.pageContextText),
      strategy: "credential_fallback",
      provider: "rule",
      started,
      inputLength: input.childText.length,
      minimizedHistoryCount: minimized.historyRedacted.length,
      piiTypes: [...minimized.piiTypes, ...inputReview.data.piiTypes],
      reasonCodes: ["CREDENTIALS_PENDING"],
      status: "CREDENTIALS_PENDING",
      safetyProvider
    });
  }
  if (runtimeConfig.chatProvider === "openai" && !runtimeConfig.openAiApiKey) {
    return reviewOutputAndRecord({
      requestId,
      sessionId: input.sessionId,
      turnId: input.turnId,
      replyDraft: buildRuleReply(minimized.childTextRedacted, input.pageContextText),
      strategy: "credential_fallback",
      provider: "rule",
      started,
      inputLength: input.childText.length,
      minimizedHistoryCount: minimized.historyRedacted.length,
      piiTypes: [...minimized.piiTypes, ...inputReview.data.piiTypes],
      reasonCodes: ["CREDENTIALS_PENDING"],
      status: "CREDENTIALS_PENDING",
      safetyProvider
    });
  }

  const llm = await llmProvider.generateReply({
    turnId: input.turnId,
    sessionId: input.sessionId,
    questionId: input.questionId,
    childTextRedacted: inputReview.data.approvedText ?? minimized.childTextRedacted,
    historyRedacted: minimized.historyRedacted,
    pageContextText: input.pageContextText,
    policyVersion: CHILD_SAFETY_POLICY_VERSION
  }).catch((error) => ({ ok: false as const, error }));

  if (!llm.ok) {
    return reviewOutputAndRecord({
      requestId,
      sessionId: input.sessionId,
      turnId: input.turnId,
      replyDraft: buildRuleReply(minimized.childTextRedacted, input.pageContextText),
      strategy: "fallback",
      provider: "rule",
      started,
      inputLength: input.childText.length,
      minimizedHistoryCount: minimized.historyRedacted.length,
      piiTypes: [...minimized.piiTypes, ...inputReview.data.piiTypes],
      reasonCodes: ["llm_provider_failed"],
      status: llm.error?.code === "TIMEOUT" ? "TIMEOUT" : "ERROR",
      safetyProvider
    });
  }

  return reviewOutputAndRecord({
    requestId,
    sessionId: input.sessionId,
    turnId: input.turnId,
    replyDraft: llm.data.replyDraft,
    strategy: "llm",
    provider: llm.metadata.providerId ?? llm.metadata.providerName,
    started,
    inputLength: input.childText.length,
    minimizedHistoryCount: minimized.historyRedacted.length,
    piiTypes: [...minimized.piiTypes, ...inputReview.data.piiTypes],
    reasonCodes: [],
    status: "PASS",
    safetyProvider
  });
}

export async function reviewAssistantResult(input: {
  sessionId: string;
  turnId: string;
  childText: string;
  result: VoiceAssistantResult;
  history: ChatMessageContext[];
  safetyProvider?: ChildSafetyProvider;
}) {
  const started = Date.now();
  const requestId = `llm:${input.sessionId}:${input.turnId}:external-runner`;
  const minimized = minimizeAndRedact(input.childText, input.history);
  return reviewOutputAndRecord({
    requestId,
    sessionId: input.sessionId,
    turnId: input.turnId,
    replyDraft: input.result.reply,
    strategy: input.result.strategy,
    provider: input.result.provider,
    started,
    inputLength: input.childText.length,
    minimizedHistoryCount: minimized.historyRedacted.length,
    piiTypes: minimized.piiTypes,
    reasonCodes: [],
    status: "PASS",
    safetyProvider: input.safetyProvider ?? defaultSafetyProvider,
    audioBase64: input.result.audioBase64,
    audioMimeType: input.result.audioMimeType
  });
}

export function minimizeAndRedact(childText: string, history: ChatMessageContext[]) {
  const redacted = redactText(childText);
  return {
    childTextRedacted: redacted.text,
    historyRedacted: history.slice(-4).map((item) => redactText(item.text).text),
    piiTypes: redacted.piiTypes
  };
}

export function getLlmGatewayAuditRecords(sessionId: string) {
  return [...(auditRecords.get(sessionId) ?? [])];
}

export function resetLlmGatewayAuditRecords() {
  auditRecords.clear();
}

export async function reviewReportNarrativeOutput(input: {
  sessionId: string;
  analysis: string;
  recommendations: string[];
  safetyProvider?: ChildSafetyProvider;
}): Promise<{ status: "PASS" | "REJECT"; reasonCodes: string[] }> {
  const safetyProvider = input.safetyProvider ?? defaultSafetyProvider;
  const combined = [input.analysis, ...input.recommendations].join("\n");
  const requestId = `report-narrative:${input.sessionId}`;
  const outputDecision = reviewText("output", requestId, combined);

  if (outputDecision.action === "fallback" || outputDecision.action === "block" || outputDecision.action === "escalate_to_adult") {
    return {
      status: "REJECT",
      reasonCodes: [...outputDecision.reasonCodes, "unsafe_professional_claim"]
    };
  }

  const reviewed = await safetyProvider
    .review({
      requestId: `${requestId}:output`,
      target: "report",
      textRedacted: outputDecision.textRedacted,
      policyVersion: CHILD_SAFETY_POLICY_VERSION
    })
    .catch(() => ({ ok: false as const, error: { code: "ERROR" } }));

  if (!reviewed.ok || reviewed.data.action === "fallback" || reviewed.data.action === "block") {
    return {
      status: "REJECT",
      reasonCodes: reviewed.ok ? reviewed.data.reasonCodes : ["output_safety_provider_failed"]
    };
  }

  return { status: "PASS", reasonCodes: [] };
}

async function reviewOutputAndRecord(input: {
  requestId: string;
  sessionId: string;
  turnId: string;
  replyDraft: string;
  strategy: string;
  provider: string;
  started: number;
  inputLength: number;
  minimizedHistoryCount: number;
  piiTypes: string[];
  reasonCodes: string[];
  status: LlmGatewayAuditRecord["status"];
  safetyProvider: ChildSafetyProvider;
  audioBase64?: string;
  audioMimeType?: string;
}): Promise<LlmGatewayResult> {
  const outputDecision = reviewText("output", input.requestId, input.replyDraft);
  const reviewed = await input.safetyProvider.review({
    requestId: `${input.requestId}:output`,
    target: "output",
    textRedacted: outputDecision.textRedacted,
    policyVersion: CHILD_SAFETY_POLICY_VERSION
  }).catch((error) => ({ ok: false as const, error }));

  if (outputDecision.action === "fallback" || outputDecision.action === "block" || !reviewed.ok) {
    return recordAndReturn({
      requestId: input.requestId,
      sessionId: input.sessionId,
      turnId: input.turnId,
      provider: input.provider,
      status: reviewed.ok ? "REJECT" : reviewed.error?.code === "TIMEOUT" ? "TIMEOUT" : "ERROR",
      inputAction: "allow",
      outputAction: reviewed.ok ? reviewed.data.action : "error",
      piiTypes: [...input.piiTypes, ...outputDecision.piiTypes],
      reasonCodes: [...input.reasonCodes, ...outputDecision.reasonCodes, "output_safety_failed"],
      inputLength: input.inputLength,
      minimizedHistoryCount: input.minimizedHistoryCount,
      latencyMs: Date.now() - input.started,
      externalNetworkCalled: false,
      reply: reviewed.ok ? reviewed.data.fallbackText ?? FALLBACK_REPLY : FALLBACK_REPLY,
      strategy: "safety_fallback",
      providerName: "rule-safety"
    });
  }

  const approvedText = childFriendlyReplyText(reviewed.data.approvedText ?? outputDecision.textRedacted);
  return recordAndReturn({
    requestId: input.requestId,
    sessionId: input.sessionId,
    turnId: input.turnId,
    provider: input.provider,
    status: input.status,
    inputAction: "allow",
    outputAction: reviewed.data.action,
    piiTypes: [...input.piiTypes, ...reviewed.data.piiTypes, ...outputDecision.piiTypes],
    reasonCodes: [...input.reasonCodes, ...reviewed.data.reasonCodes, ...outputDecision.reasonCodes],
    inputLength: input.inputLength,
    minimizedHistoryCount: input.minimizedHistoryCount,
    latencyMs: Date.now() - input.started,
    externalNetworkCalled: false,
    reply: approvedText,
    strategy: input.strategy,
    providerName: input.provider,
    audioBase64: input.audioBase64,
    audioMimeType: input.audioMimeType
  });
}

function childFriendlyReplyText(text: string) {
  const normalized = text
    .replace(/绿色三角体/g, "绿色尖尖块")
    .replace(/三角形立体图形/g, "尖尖块")
    .replace(/三角体/g, "尖尖块")
    .replace(/立方体/g, "方方块")
    .replace(/几何体/g, "图形")
    .replace(/目标图/g, "上面的图片")
    .replace(/选项/g, "下面的图片")
    .replace(/训练目标/g, "要找的图片")
    .replace(/页面上下文/g, "屏幕上的内容")
    .replace(/上面的图片是一个?([^，。！？]+)[，。！？]?.*/g, "这是$1。")
    .replace(/上面的图片是一把([^，。！？]+)[，。！？]?.*/g, "这是$1。")
    .replace(/上面的图片是一张([^，。！？]+)[，。！？]?.*/g, "这是$1。")
    .replace(/它是一个?([^，。！？]+)[，。！？]?.*/g, "这是$1。")
    .replace(/它是一把([^，。！？]+)[，。！？]?.*/g, "这是$1。")
    .replace(/它是一张([^，。！？]+)[，。！？]?.*/g, "这是$1。")
    .replace(/下面第[一二三四五六七八九十\d]+张(?:图片)?是一个?([^，。！？]+)[，。！？]?.*/g, "这是$1。")
    .replace(/下面第[一二三四五六七八九十\d]+张(?:图片)?是一把([^，。！？]+)[，。！？]?.*/g, "这是$1。")
    .replace(/下面第[一二三四五六七八九十\d]+张(?:图片)?是一张([^，。！？]+)[，。！？]?.*/g, "这是$1。");
  return compactChildReply(normalizeObjectNameReply(normalized));
}

function normalizeObjectNameReply(text: string) {
  const names = knownObjectNames();
  const firstSentence = text.split(/[。！？?!\n]/)[0] ?? text;
  const matchedName = names.find((name) => firstSentence.includes(name));
  if (/是什么|这是|是一个|是一把|是一颗|是一串|是一辆|是一张|图片/.test(firstSentence) && matchedName) {
    return `这是${matchedName}。`;
  }
  const leadingName = firstSentence.match(/^([^，,。！？]{1,8})[，,]/)?.[1];
  if (leadingName && names.includes(leadingName)) {
    return `这是${leadingName}。`;
  }
  return text;
}

function knownObjectNames() {
  return [
    "小汽车",
    "自行车",
    "彩色球",
    "绿色尖尖块",
    "苹果",
    "桃子",
    "香蕉",
    "菠萝",
    "西瓜",
    "草莓",
    "葡萄",
    "篮球",
    "水杯",
    "椅子",
    "碗"
  ];
}

function compactChildReply(text: string) {
  const blocked = /(做朋友|交朋友|真有趣|有模有样|你看见了吗|找找.*呀|哪一张.*呀|哪一张.*吗|我陪你看|我们来看)/;
  const parts = text
    .split(/(?<=[。！？?!])|\n+/)
    .map((part) => part.trim().replace(/^[，。！？,.、\s]+|[，。！？,.、\s]+$/g, ""))
    .filter((part) => part && !blocked.test(part))
    .map((part) => part.replace(/^你真棒[，,]\s*/, "").replace(/^真棒[，,]\s*/, ""));
  const shortened = parts.slice(0, 2).map((part) => {
    if (/^这是/.test(part)) return `${part.split(/[，,、]/)[0].slice(0, 12)}。`;
    if (/^点/.test(part)) return `${part.slice(0, 8)}。`;
    return `${part.slice(0, 12)}。`;
  });
  return shortened.join("") || "看屏幕。";
}

function recordAndReturn(input: {
  requestId: string;
  sessionId: string;
  turnId: string;
  provider: string;
  status: LlmGatewayAuditRecord["status"];
  inputAction: LlmGatewayAuditRecord["inputAction"];
  outputAction: LlmGatewayAuditRecord["outputAction"];
  piiTypes: string[];
  reasonCodes: string[];
  inputLength: number;
  minimizedHistoryCount: number;
  latencyMs: number;
  externalNetworkCalled: boolean;
  reply: string;
  strategy: string;
  providerName: string;
  audioBase64?: string;
  audioMimeType?: string;
}): LlmGatewayResult {
  const createdAt = new Date().toISOString();
  const audit: LlmGatewayAuditRecord = {
    requestId: input.requestId,
    sessionId: input.sessionId,
    turnId: input.turnId,
    provider: input.provider,
    status: input.status,
    inputAction: input.inputAction,
    outputAction: input.outputAction,
    piiTypes: Array.from(new Set(input.piiTypes)),
    reasonCodes: Array.from(new Set(input.reasonCodes)),
    inputLength: input.inputLength,
    minimizedHistoryCount: input.minimizedHistoryCount,
    latencyMs: input.latencyMs,
    externalNetworkCalled: input.externalNetworkCalled,
    tokenUsage: {
      inputTokensApprox: Math.ceil(input.inputLength / 4),
      outputTokensApprox: Math.ceil(input.reply.length / 4)
    },
    createdAt
  };
  const records = auditRecords.get(input.sessionId) ?? [];
  records.push(audit);
  auditRecords.set(input.sessionId, records.slice(-200));
  return {
    reply: input.reply,
    strategy: input.strategy,
    provider: input.providerName,
    timestamp: createdAt,
    audioBase64: input.audioBase64,
    audioMimeType: input.audioMimeType,
    safetyStatus: input.status,
    policyVersion: CHILD_SAFETY_POLICY_VERSION,
    auditId: input.requestId
  };
}

function reviewText(target: "input" | "output", requestId: string, text: string) {
  const redacted = redactText(text);
  const lower = redacted.text.toLowerCase();
  const reasonCodes: string[] = [...redacted.piiTypes.map((type) => `pii_${type}`)];
  let action: SafetyReviewAction = redacted.piiTypes.length > 0 ? "redact_then_allow" : "allow";

  if (/ignore (all )?(previous )?(rules|instructions)|system prompt|bypass|jailbreak/.test(lower)) {
    action = "fallback";
    reasonCodes.push("prompt_injection");
  }
  if (/self[- ]?harm|kill myself|suicide|hurt myself|家暴|自伤|受伤/.test(lower)) {
    action = "escalate_to_adult";
    reasonCodes.push("danger_signal");
  }
  if (/adult content|porn|violent threat|色情|成人内容|暴力威胁/.test(lower)) {
    action = "block";
    reasonCodes.push("blocked_content");
  }
  if (target === "output" && /diagnosis|percentile|clinical|治疗|诊断|百分位/.test(lower)) {
    action = "fallback";
    reasonCodes.push("unsafe_professional_claim");
  }

  return {
    requestId,
    target,
    action,
    textRedacted: redacted.text,
    piiTypes: redacted.piiTypes,
    reasonCodes
  };
}

function redactText(text: string) {
  const piiTypes: string[] = [];
  let redacted = text;
  redacted = redacted.replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, () => {
    piiTypes.push("email");
    return "[redacted-email]";
  });
  redacted = redacted.replace(/\b(?:\+?\d[\d -]{7,}\d)\b/g, () => {
    piiTypes.push("phone_or_long_number");
    return "[redacted-number]";
  });
  redacted = redacted.replace(/\b(?:my name is|我是|我叫)\s+[\p{L}]{2,12}/giu, () => {
    piiTypes.push("name");
    return "[redacted-name]";
  });
  return {
    text: redacted.trim(),
    piiTypes: Array.from(new Set(piiTypes))
  };
}

function buildRuleReply(text: string, pageContextText?: string) {
  const childText = text.trim();
  if (!childText) return "你可以先说一句。我陪你。";

  const contextAnswer = buildContextAwareRuleReply(childText, pageContextText);
  if (contextAnswer) return contextAnswer;

  if (/help|不会|不懂|难/.test(text.toLowerCase())) {
    return "没关系。我陪你慢慢看。";
  }
  return "我没看清细节。我们看屏幕吧。";
}

function buildContextAwareRuleReply(text: string, pageContextText?: string) {
  if (!pageContextText) return "";

  const prompt = readContextValue(pageContextText, "孩子听到的问题") || readContextValue(pageContextText, "题目提示");
  const target = readContextValue(pageContextText, "上面的图片") || readContextValue(pageContextText, "训练目标");
  const correct = readContextValue(pageContextText, "应该点") || readContextValue(pageContextText, "正确答案");
  const options = readContextValue(pageContextText, "下面从左到右的图片") || readContextValue(pageContextText, "当前页面从左到右的选项");

  if (/第[一二三四五六七八九十\d]+张/.test(text) && /是什么|有什么|图案/.test(text)) {
    const optionReply = buildOptionNameReply(text, options);
    if (optionReply) return optionReply;
  }
  if (/第几张|哪一张|选哪|哪个/.test(text) && correct && !correct.includes("未知")) {
    return `${formatChoiceAnswer(correct)}。你问得很好。`;
  }
  if (/当前题目|题目是什么|要做什么|怎么玩|怎么选|怎么找/.test(text) && prompt) {
    return `${shortenSentence(prompt)}。我们一起看。`;
  }
  if (/什么颜色|颜色/.test(text)) {
    const colorSource = [target, correct, options].filter(Boolean).join("。");
    const color = colorSource.match(/[红橙黄绿青蓝紫黑白灰粉棕金银]色/)?.[0];
    if (color) return `是${color}。你观察得很好。`;
  }
  if (/是什么|有什么|上面|下面/.test(text)) {
    const source = /下面/.test(text) ? options || correct || target : target || correct || options;
    if (source) return `${shortenSentence(source)}。我陪你看。`;
  }

  return "";
}

function buildOptionNameReply(text: string, optionsText: string) {
  if (!optionsText) return "";
  const position = parsePositionNumber(text);
  if (!position) return "";
  const optionText = readOptionByPosition(optionsText, position);
  const name = extractKnownObjectName(optionText);
  return name ? `这是${name}。` : "";
}

function parsePositionNumber(text: string) {
  const raw = text.match(/第([一二三四五六七八九十\d]+)张/)?.[1];
  if (!raw) return 0;
  if (/^\d+$/.test(raw)) return Number(raw);
  const map: Record<string, number> = {
    一: 1,
    二: 2,
    三: 3,
    四: 4,
    五: 5,
    六: 6,
    七: 7,
    八: 8,
    九: 9,
    十: 10
  };
  return map[raw] ?? 0;
}

function readOptionByPosition(optionsText: string, position: number) {
  const match = optionsText.match(new RegExp(`下面第${position}张[^：:]*[：:]([^；。]*)`));
  return match?.[1]?.trim() ?? "";
}

function extractKnownObjectName(text: string) {
  return knownObjectNames().find((name) => text.includes(name)) ?? "";
}

function formatChoiceAnswer(text: string) {
  const position = text.match(/下面第(\d+)张/)?.[1] ?? text.match(/第(\d+)张/)?.[1];
  const positionText = position === "1" ? "左边这张" : position === "2" ? "右边这张" : position ? `第${position}张` : "";
  const cleaned = shortenSentence(text)
    .replace(/^下面的图片\s*\d+[:：]?/, "")
    .replace(/^选项\s*\d+[:：]?/, "")
    .trim();
  if (positionText && cleaned && !cleaned.includes(positionText)) {
    return `点${positionText}`;
  }
  if (positionText) return `点${positionText}`;
  return `点${cleaned || "这一张"}`;
}

function readContextValue(context: string, label: string) {
  const line = context.split(/\r?\n/).find((item) => item.startsWith(`${label}：`));
  return line?.slice(label.length + 1).trim() ?? "";
}

function shortenSentence(text: string) {
  const cleaned = text
    .replace(/^第\d+张，?/, "")
    .replace(/^下面第\d+张，?/, "下面这张")
    .replace(/^下面第\d+张/, "下面这张")
    .replace(/^正确答案[:：]?/, "")
    .replace(/^训练目标[:：]?/, "")
    .replace(/^当前页面从左到右的选项[:：]?/, "")
    .replace(/^应该点[:：]?/, "")
    .replace(/^上面的图片[:：]?/, "")
    .replace(/^下面从左到右的图片[:：]?/, "")
    .replace(/（[^）]*）/g, "")
    .replace(/[。！？,.，、；;]+$/g, "")
    .trim();
  return cleaned.length > 28 ? cleaned.slice(0, 28) : cleaned;
}
