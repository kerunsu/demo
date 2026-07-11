import {
  CLOUD_TTS_PROVIDER_METADATA,
  DEFAULT_TTS_PROVIDER_METADATA,
  MockChildSafetyProvider,
  MockTtsProvider,
  type ProviderResult,
  type TtsAudio
} from "child-education-training-demo/shared/providers";
import { runtimeConfig } from "../config/runtime.js";
import { getVoiceDegradationPlan } from "./voiceDegradationService.js";
import { providerMetricDefaults, recordVoiceMetric } from "./voiceObservabilityService.js";

const TTS_TIMEOUT_MS = 6000;
const safetyProvider = new MockChildSafetyProvider();

export interface SpeechSynthesisInput {
  sessionId: string;
  turnId: string;
  correlationId: string;
  text: string;
  voice?: string;
  timeoutMs?: number;
}

export function getSpeechTtsProviderStatus() {
  if (runtimeConfig.voiceTtsProvider === "cloud") {
    return {
      providerId: CLOUD_TTS_PROVIDER_METADATA.providerId ?? "cloud-openai-tts",
      providerType: "cloud",
      status: runtimeConfig.openAiApiKey ? "READY" : "CLOUD_CREDENTIALS_PENDING",
      modelId: CLOUD_TTS_PROVIDER_METADATA.vendorModelName,
      externalNetworkCalled: false,
      inputPersisted: false,
      humanReview: CLOUD_TTS_PROVIDER_METADATA.humanReview,
      licenseReview: CLOUD_TTS_PROVIDER_METADATA.licenseReview
    };
  }
  if (runtimeConfig.voiceTtsProvider === "local") {
    return {
      providerId: DEFAULT_TTS_PROVIDER_METADATA.providerId ?? "local-piper-zh-huayan",
      providerType: "local",
      status: "READY",
      modelId: DEFAULT_TTS_PROVIDER_METADATA.modelId,
      externalNetworkCalled: false,
      inputPersisted: false,
      humanReview: DEFAULT_TTS_PROVIDER_METADATA.humanReview,
      licenseReview: DEFAULT_TTS_PROVIDER_METADATA.licenseReview
    };
  }
  return {
    providerId: "mock-tts",
    providerType: "mock",
    status: "READY",
    modelId: "synthetic-silence-v1",
    externalNetworkCalled: false,
    inputPersisted: false,
    humanReview: "NOT_REQUIRED",
    licenseReview: "NOT_REQUIRED"
  };
}

export async function synthesizeSpeech(input: SpeechSynthesisInput): Promise<ProviderResult<TtsAudio>> {
  const safetyStartedAt = new Date();
  const safety = await safetyProvider.review({
    requestId: `tts-safety:${input.correlationId}`,
    target: "output",
    textRedacted: input.text,
    policyVersion: "m4-rule-safety-v1"
  });
  recordVoiceMetric({
    sessionId: input.sessionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    stage: "safety_review",
    startedAt: safetyStartedAt,
    completedAt: new Date(safetyStartedAt.getTime() + safety.latencyMs),
    durationMs: safety.latencyMs,
    status: safety.ok ? "success" : safety.error.code === "TIMEOUT" ? "timeout" : "failure",
    errorCode: safety.ok ? undefined : safety.error.code,
    degradedProvider: !safety.ok,
    ...providerMetricDefaults(safety.metadata),
    textForHash: input.text,
    metadata: {
      action: safety.ok ? safety.data.action : "error",
      policyVersion: safety.ok ? safety.data.policyVersion : "m4-rule-safety-v1",
      piiTypeCount: safety.ok ? safety.data.piiTypes.length : 0
    }
  });
  if (!safety.ok) {
    const degradation = getVoiceDegradationPlan("TTS_SAFETY_REJECTED");
    return {
      ok: false,
      metadata: DEFAULT_TTS_PROVIDER_METADATA,
      latencyMs: safety.latencyMs,
      error: {
        code: "SAFETY_REJECTED",
        message: safety.error.message
      },
      fallbackText: safety.fallbackText ?? degradation.childSafeText
    };
  }
  const approvedText = safety.data.approvedText ?? safety.data.fallbackText;
  if (!approvedText) {
    const degradation = getVoiceDegradationPlan("TTS_SAFETY_REJECTED");
    return {
      ok: false,
      metadata: DEFAULT_TTS_PROVIDER_METADATA,
      latencyMs: safety.latencyMs,
      error: {
        code: "SAFETY_REJECTED",
        message: "Safety provider did not return approved or fallback text."
      },
      fallbackText: degradation.childSafeText
    };
  }

  const ttsStartedAt = new Date();
  recordVoiceMetric({
    sessionId: input.sessionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    stage: "tts_request_start",
    startedAt: ttsStartedAt,
    completedAt: ttsStartedAt,
    ...providerMetricDefaults(getActiveTtsMetadata()),
    textForHash: approvedText
  });

  if (runtimeConfig.voiceTtsProvider === "cloud" && !runtimeConfig.openAiApiKey) {
    const degradation = getVoiceDegradationPlan("TTS_PROVIDER_UNAVAILABLE");
    const result: ProviderResult<TtsAudio> = {
      ok: false,
      metadata: CLOUD_TTS_PROVIDER_METADATA,
      latencyMs: safety.latencyMs,
      error: {
        code: "CLOUD_CREDENTIALS_PENDING",
        message: "Cloud TTS credentials are not configured.",
        providerStatus: "CLOUD_CREDENTIALS_PENDING"
      },
      fallbackText: approvedText || degradation.childSafeText
    };
    recordTtsReady(input, result, ttsStartedAt, approvedText);
    return result;
  }

  if (runtimeConfig.voiceTtsProvider === "local") {
    const result = await synthesizeWithPythonService(input, approvedText, safety.data);
    recordTtsReady(input, result, ttsStartedAt, approvedText);
    return result;
  }

  const mock = new MockTtsProvider();
  const result = await mock.synthesize({
    turnId: input.turnId,
    text: approvedText,
    safety: safety.data,
    voice: input.voice,
    language: "zh-CN",
    audioFormat: "wav"
  });
  recordTtsReady(input, result, ttsStartedAt, approvedText);
  return result;
}

function getActiveTtsMetadata() {
  if (runtimeConfig.voiceTtsProvider === "cloud") return CLOUD_TTS_PROVIDER_METADATA;
  if (runtimeConfig.voiceTtsProvider === "local") return DEFAULT_TTS_PROVIDER_METADATA;
  return new MockTtsProvider().metadata;
}

function recordTtsReady(input: SpeechSynthesisInput, result: ProviderResult<TtsAudio>, startedAt: Date, approvedText: string) {
  const completedAt = new Date();
  recordVoiceMetric({
    sessionId: input.sessionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    stage: "tts_audio_ready",
    startedAt,
    completedAt,
    durationMs: result.latencyMs || Math.max(0, completedAt.getTime() - startedAt.getTime()),
    status: result.ok ? "success" : result.error.code === "TIMEOUT" ? "timeout" : "degraded",
    errorCode: result.ok ? undefined : result.error.code,
    degradedProvider: !result.ok,
    ...providerMetricDefaults(result.metadata),
    audioDurationMs: result.ok ? result.data.durationMs : result.metrics?.audioDurationMs,
    textForHash: approvedText,
    metadata: {
      mimeType: result.ok ? result.data.mimeType : null
    }
  });
}

async function synthesizeWithPythonService(
  input: SpeechSynthesisInput,
  approvedText: string,
  safety: Awaited<ReturnType<typeof safetyProvider.review>> extends ProviderResult<infer T> ? T : never
): Promise<ProviderResult<TtsAudio>> {
  const started = performance.now();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), input.timeoutMs ?? TTS_TIMEOUT_MS);
  try {
    const pythonVoiceServiceUrl = (runtimeConfig.pythonVoiceServiceUrl ?? "http://127.0.0.1:8765").replace(/\/+$/, "");
    const response = await fetch(`${pythonVoiceServiceUrl}/tts`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        requestId: input.correlationId,
        sessionId: input.sessionId,
        turnId: input.turnId,
        text: approvedText,
        voice: input.voice ?? DEFAULT_TTS_PROVIDER_METADATA.modelId
      })
    });
    const latencyMs = Math.round(performance.now() - started);
    if (!response.ok) {
      const degradation = getVoiceDegradationPlan("TTS_PROVIDER_UNAVAILABLE");
      return {
        ok: false,
        metadata: DEFAULT_TTS_PROVIDER_METADATA,
        latencyMs,
        error: {
          code: "PROVIDER_FAILURE",
          message: `Python TTS service returned ${response.status}.`,
          retryable: response.status >= 500
        },
        fallbackText: approvedText || degradation.childSafeText
      };
    }
    const body = (await response.json()) as { audioBase64: string; mimeType: string; durationMs: number; sampleRateHz?: number };
    return {
      ok: true,
      metadata: DEFAULT_TTS_PROVIDER_METADATA,
      latencyMs,
      data: {
        turnId: input.turnId,
        audioRef: `tts:${input.sessionId}:${input.turnId}`,
        audioBase64: body.audioBase64,
        mimeType: body.mimeType,
        durationMs: body.durationMs,
        sampleRateHz: body.sampleRateHz,
        channels: 1,
        marks: [
          { name: "speech_start", offsetMs: 0 },
          { name: "speech_end", offsetMs: body.durationMs }
        ]
      },
      metrics: {
        processLatencyMs: latencyMs,
        firstByteLatencyMs: latencyMs,
        audioDurationMs: body.durationMs,
        gpuUsed: false,
        hardwareAcceleration: "CPUExecutionProvider"
      }
    };
  } catch (error) {
    const degradation = getVoiceDegradationPlan("TTS_PROVIDER_UNAVAILABLE");
    const latencyMs = Math.round(performance.now() - started);
    return {
      ok: false,
      metadata: DEFAULT_TTS_PROVIDER_METADATA,
      latencyMs,
      error: {
        code: error instanceof DOMException && error.name === "AbortError" ? "TIMEOUT" : "PROVIDER_FAILURE",
        message: error instanceof Error ? error.message : "Python TTS service failed.",
        retryable: true
      },
      fallbackText: approvedText || degradation.childSafeText
    };
  } finally {
    clearTimeout(timeout);
  }
}
