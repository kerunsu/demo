import {
  VOICE_PARTNER_TURN_SCHEMA,
  type VoicePartnerTurnRequest,
  type VoicePartnerTurnResponse,
  type VoiceTurnPageContextPayload
} from "child-education-training-demo/shared/voice-partner-contract";
import { runtimeConfig } from "../config/runtime.js";
import { getMediaStreamAudioBuffer, getMediaStreamSummary } from "./mediaIngressService.js";
import { buildChatAssistantHistory } from "./chatService.js";
import { getSession as getStoredSession, saveSession } from "./sessionLifecycleService.js";
import { reviewAssistantResult } from "./llmSafetyGatewayService.js";
import { recordPartnerTurnFailure, recordPartnerTurnSuccess } from "./voicePartnerTurnState.js";
import { recordVoiceMetric } from "./voiceObservabilityService.js";

export interface ProcessPartnerVoiceTurnInput {
  sessionId: string;
  streamId: string;
  turnId: string;
  correlationId: string;
  pageContext: VoiceTurnPageContextPayload;
  locale?: string;
  capturedAt?: string;
}

export interface PartnerVoiceTurnResult {
  reply: string;
  strategy: string;
  provider: string;
  timestamp: string;
  audioBase64?: string;
  audioMimeType?: string;
  safetyStatus?: string;
  policyVersion?: string;
  auditId?: string;
}

export async function probeVoicePartnerHealth(): Promise<{
  status: "READY" | "UNAVAILABLE" | "NOT_CONFIGURED";
  latencyMs?: number;
  message?: string;
}> {
  if (!runtimeConfig.voicePartnerBaseUrl) {
    return { status: "NOT_CONFIGURED" };
  }
  const started = Date.now();
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    const response = await fetch(`${runtimeConfig.voicePartnerBaseUrl}/health`, {
      method: "GET",
      signal: controller.signal,
      headers: partnerAuthHeaders()
    });
    clearTimeout(timeout);
    if (!response.ok) {
      return { status: "UNAVAILABLE", latencyMs: Date.now() - started, message: `HTTP ${response.status}` };
    }
    return { status: "READY", latencyMs: Date.now() - started };
  } catch (error) {
    return {
      status: "UNAVAILABLE",
      latencyMs: Date.now() - started,
      message: error instanceof Error ? error.message : "health probe failed"
    };
  }
}

export async function processPartnerVoiceTurn(input: ProcessPartnerVoiceTurnInput): Promise<PartnerVoiceTurnResult> {
  if (runtimeConfig.voiceDialogProvider !== "partner") {
    throw new Error("VOICE_DIALOG_PROVIDER is not partner");
  }
  if (!runtimeConfig.voicePartnerBaseUrl) {
    throw new Error("VOICE_PARTNER_BASE_URL is not configured");
  }

  const session = getStoredSession(input.sessionId);
  if (session.state !== "TRAINING_ACTIVE") {
    throw new Error("Course already completed");
  }

  const summary = getMediaStreamSummary(input.sessionId, input.streamId);
  const audioBuffer = getMediaStreamAudioBuffer(input.sessionId, input.streamId);
  if (!summary || !audioBuffer || audioBuffer.length === 0) {
    recordPartnerTurnFailure(input.sessionId, "AUDIO_NOT_AVAILABLE");
    throw new Error("AUDIO_NOT_AVAILABLE");
  }

  const assistantHistory = buildChatAssistantHistory(session);
  const history = assistantHistory
    .filter((entry): entry is { role: "user" | "assistant"; text: string } => entry.role === "user" || entry.role === "assistant")
    .map((entry) => ({ role: entry.role, text: entry.text }));
  const requestBody: VoicePartnerTurnRequest = {
    schemaVersion: VOICE_PARTNER_TURN_SCHEMA,
    sessionId: input.sessionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    capturedAt: input.capturedAt ?? new Date().toISOString(),
    audio: {
      base64: audioBuffer.toString("base64"),
      mimeType: summary.format.mimeType,
      durationMs: summary.format.chunkDurationMs * Math.max(summary.chunkCount, 1)
    },
    pageContext: input.pageContext,
    history,
    locale: input.locale ?? "zh-CN"
  };

  const started = Date.now();
  recordVoiceMetric({
    sessionId: input.sessionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    stage: "partner_turn_request_start",
    startedAt: new Date(started),
    completedAt: new Date(started),
    status: "success",
    metadata: {
      streamId: input.streamId,
      screenshotPresent: Boolean(input.pageContext.screenshot),
      screenshotUnavailableReason: input.pageContext.screenshotUnavailableReason
    }
  });

  let partnerResponse: VoicePartnerTurnResponse;
  try {
    partnerResponse = await forwardPartnerTurn(requestBody);
  } catch (error) {
    const code = error instanceof Error ? error.message : "PARTNER_REQUEST_FAILED";
    recordPartnerTurnFailure(input.sessionId, code);
    recordVoiceMetric({
      sessionId: input.sessionId,
      turnId: input.turnId,
      correlationId: input.correlationId,
      stage: "partner_turn_failed",
      startedAt: new Date(started),
      completedAt: new Date(),
      status: "failure",
      metadata: { errorCode: code }
    });
    throw error;
  }

  const latencyMs = Date.now() - started;

  if (!partnerResponse.ok) {
    recordPartnerTurnFailure(input.sessionId, partnerResponse.error.code);
    recordVoiceMetric({
      sessionId: input.sessionId,
      turnId: input.turnId,
      correlationId: input.correlationId,
      stage: "partner_turn_failed",
      startedAt: new Date(started),
      completedAt: new Date(),
      status: "failure",
      metadata: { errorCode: partnerResponse.error.code }
    });
    throw new Error(partnerResponse.error.code);
  }

  recordPartnerTurnSuccess(input.sessionId, {
    latencyMs,
    provider: partnerResponse.metadata?.provider
  });

  const childPlaceholder = "[voice-turn]";
  const reviewed = await reviewAssistantResult({
    sessionId: input.sessionId,
    turnId: input.turnId,
    childText: childPlaceholder,
    history: assistantHistory,
    result: {
      reply: partnerResponse.replyText,
      strategy: "partner",
      provider: partnerResponse.metadata?.provider ?? "voice-partner",
      timestamp: new Date().toISOString(),
      audioBase64: partnerResponse.replyAudio?.base64,
      audioMimeType: partnerResponse.replyAudio?.mimeType
    }
  });

  session.chatHistory.push({
    role: "bot",
    text: reviewed.reply,
    strategy: reviewed.strategy,
    timestamp: reviewed.timestamp
  });
  saveSession(session);

  recordVoiceMetric({
    sessionId: input.sessionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    stage: "partner_turn_complete",
    startedAt: new Date(started),
    completedAt: new Date(),
    status: "success",
    durationMs: latencyMs,
    metadata: {
      provider: partnerResponse.metadata?.provider,
      hasReplyAudio: Boolean(reviewed.audioBase64)
    }
  });

  return {
    reply: reviewed.reply,
    strategy: reviewed.strategy,
    provider: reviewed.provider,
    timestamp: reviewed.timestamp,
    audioBase64: reviewed.audioBase64,
    audioMimeType: reviewed.audioMimeType,
    safetyStatus: reviewed.safetyStatus,
    policyVersion: reviewed.policyVersion,
    auditId: reviewed.auditId
  };
}

async function forwardPartnerTurn(body: VoicePartnerTurnRequest): Promise<VoicePartnerTurnResponse> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), runtimeConfig.voicePartnerTimeoutMs);
  try {
    const response = await fetch(`${runtimeConfig.voicePartnerBaseUrl}/v1/voice-turn`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...partnerAuthHeaders()
      },
      body: JSON.stringify(body),
      signal: controller.signal
    });
    const payload = (await response.json()) as VoicePartnerTurnResponse;
    if (!response.ok && payload && "ok" in payload && payload.ok === false) {
      return payload;
    }
    if (!response.ok) {
      return {
        ok: false,
        error: {
          code: "PARTNER_HTTP_ERROR",
          message: `Partner HTTP ${response.status}`
        }
      };
    }
    if (!payload || typeof payload !== "object" || !("ok" in payload)) {
      return {
        ok: false,
        error: { code: "PARTNER_BAD_RESPONSE", message: "Invalid partner JSON" }
      };
    }
    return payload;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("PARTNER_TIMEOUT");
    }
    throw new Error("PARTNER_REQUEST_FAILED");
  } finally {
    clearTimeout(timeout);
  }
}

function partnerAuthHeaders(): Record<string, string> {
  if (!runtimeConfig.voicePartnerApiKey) return {};
  return { "x-voice-partner-key": runtimeConfig.voicePartnerApiKey };
}
