import {
  CLOUD_STT_PROVIDER_METADATA,
  DEFAULT_STT_PROVIDER_METADATA,
  MockSttProvider,
  type ProviderErrorCode,
  type ProviderResult,
  type SttTranscript
} from "child-education-training-demo/shared/providers";
import { runtimeConfig } from "../config/runtime.js";
import { getMediaStreamAudioBuffer, getMediaStreamSummary } from "./mediaIngressService.js";
import { transcodeToWav16kMono } from "./audioTranscodeService.js";
import { applyTranscriptNormalization } from "./transcriptService.js";
import { getVoiceDegradationPlan } from "./voiceDegradationService.js";
import { providerMetricDefaults, recordVoiceMetric } from "./voiceObservabilityService.js";
import { persistLanguageObservationsFromTranscript } from "./behaviorTimelineOrchestratorService.js";

const STT_TIMEOUT_MS = 12000;
const FUNASR_STT_PROVIDER_METADATA = {
  ...DEFAULT_STT_PROVIDER_METADATA,
  providerName: "FunASR Mandarin local STT",
  providerId: "local-funasr-zh",
  modelId: "paraformer-zh",
  modelPath: "ModelScope cache",
  version: "expert-annotator-asd-main",
  dataSafety: {
    externalNetworkCalled: false,
    inputPersisted: false,
    rawAudioPersisted: false,
    sensitiveTextLogged: false,
    credentialsSource: "none",
    allowedData: ["synthetic", "developer_authorized", "authorized_non_child"],
    notes: "Local FunASR STT reused from ExpertAnnotator_ASD-main. Raw audio is processed transiently and is not persisted by the voice service."
  }
} satisfies typeof DEFAULT_STT_PROVIDER_METADATA;

export interface MediaStreamTranscriptionInput {
  sessionId: string;
  streamId: string;
  turnId: string;
  correlationId: string;
  languageHint?: string;
  timeoutMs?: number;
}

export interface SttProviderStatus {
  providerId: string;
  providerType: "local" | "cloud" | "mock";
  status: "READY" | "CLOUD_CREDENTIALS_PENDING" | "UNAVAILABLE";
  modelId?: string;
  externalNetworkCalled: boolean;
  inputPersisted: boolean;
}

export function getSttProviderStatus(): SttProviderStatus {
  if (runtimeConfig.sttProvider === "cloud") {
    return {
      providerId: CLOUD_STT_PROVIDER_METADATA.providerId ?? "cloud-openai-stt",
      providerType: "cloud",
      status: runtimeConfig.openAiApiKey ? "READY" : "CLOUD_CREDENTIALS_PENDING",
      modelId: CLOUD_STT_PROVIDER_METADATA.vendorModelName,
      externalNetworkCalled: false,
      inputPersisted: false
    };
  }
  if (runtimeConfig.sttProvider === "local") {
    const metadata = getActiveSttMetadata();
    return {
      providerId: metadata.providerId ?? "local-stt",
      providerType: "local",
      status: "READY",
      modelId: metadata.modelId,
      externalNetworkCalled: false,
      inputPersisted: false
    };
  }
  return {
    providerId: "mock-stt",
    providerType: "mock",
    status: "READY",
    modelId: "fixture-transcript-v1",
    externalNetworkCalled: false,
    inputPersisted: false
  };
}

export async function transcribeMediaStream(input: MediaStreamTranscriptionInput): Promise<ProviderResult<SttTranscript>> {
  const requestStartedAt = new Date();
  const summary = getMediaStreamSummary(input.sessionId, input.streamId);
  if (!summary) {
    const degradation = getVoiceDegradationPlan("MEDIA_TRANSPORT_FAILED");
    const result: ProviderResult<SttTranscript> = {
      ok: false,
      metadata: DEFAULT_STT_PROVIDER_METADATA,
      latencyMs: 0,
      error: {
        code: "EMPTY_RESULT",
        message: "Media stream not found for STT."
      },
      fallbackText: degradation.childSafeText
    };
    recordSttRequest(input, result, requestStartedAt);
    recordSttComplete(input, result, requestStartedAt);
    return result;
  }

  recordVoiceMetric({
    sessionId: input.sessionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    stage: "stt_request_start",
    startedAt: requestStartedAt,
    completedAt: requestStartedAt,
    ...providerMetricDefaults(getActiveSttMetadata()),
    audioDurationMs: summary.format.chunkDurationMs * summary.chunkCount,
    metadata: {
      streamId: input.streamId,
      chunkCount: summary.chunkCount
    }
  });

  if (runtimeConfig.sttProvider === "cloud" && !runtimeConfig.openAiApiKey) {
    const degradation = getVoiceDegradationPlan("STT_PROVIDER_UNAVAILABLE");
    const result: ProviderResult<SttTranscript> = {
      ok: false,
      metadata: CLOUD_STT_PROVIDER_METADATA,
      latencyMs: 0,
      error: {
        code: "CLOUD_CREDENTIALS_PENDING",
        message: "Cloud STT credentials are not configured.",
        providerStatus: "CLOUD_CREDENTIALS_PENDING"
      },
      fallbackText: degradation.childSafeText
    };
    recordSttComplete(input, result, requestStartedAt, summary.format.chunkDurationMs * summary.chunkCount);
    return result;
  }

  if (runtimeConfig.sttProvider === "local") {
    const result = await transcribeWithPythonService(input);
    recordSttComplete(input, result, requestStartedAt, summary.format.chunkDurationMs * summary.chunkCount);
    persistSttLanguageFeatures(input, result, summary.format.chunkDurationMs * summary.chunkCount);
    return result;
  }

  const mock = new MockSttProvider();
  const result = await mock.transcribe({
    turnId: input.turnId,
    audioSegmentId: input.streamId,
    audioRef: `media-stream:${input.sessionId}:${input.streamId}`,
    languageHint: input.languageHint ?? "zh-CN"
  });
  const normalized = applyTranscriptNormalization(input.sessionId, result);
  recordSttComplete(input, normalized, requestStartedAt, summary.format.chunkDurationMs * summary.chunkCount);
  persistSttLanguageFeatures(input, normalized, summary.format.chunkDurationMs * summary.chunkCount);
  return normalized;
}

function getActiveSttMetadata() {
  if (runtimeConfig.sttProvider === "cloud") return CLOUD_STT_PROVIDER_METADATA;
  if (runtimeConfig.sttProvider === "local" && process.env.VOICE_SERVICE_STT_PROVIDER === "local-funasr") {
    return FUNASR_STT_PROVIDER_METADATA;
  }
  if (runtimeConfig.sttProvider === "local") return DEFAULT_STT_PROVIDER_METADATA;
  return new MockSttProvider().metadata;
}

function recordSttRequest(
  input: MediaStreamTranscriptionInput,
  result: ProviderResult<SttTranscript>,
  startedAt: Date
) {
  recordVoiceMetric({
    sessionId: input.sessionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    stage: "stt_request_start",
    startedAt,
    completedAt: startedAt,
    ...providerMetricDefaults(result.metadata),
    status: "failure",
    errorCode: result.ok ? undefined : result.error.code,
    degradedProvider: !result.ok,
    metadata: {
      streamId: input.streamId
    }
  });
}

function recordSttComplete(
  input: MediaStreamTranscriptionInput,
  result: ProviderResult<SttTranscript>,
  startedAt: Date,
  audioDurationMs?: number
) {
  const completedAt = new Date();
  recordVoiceMetric({
    sessionId: input.sessionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    stage: "stt_complete",
    startedAt,
    completedAt,
    durationMs: result.latencyMs || Math.max(0, completedAt.getTime() - startedAt.getTime()),
    status: result.ok ? "success" : result.error.code === "TIMEOUT" ? "timeout" : "degraded",
    errorCode: result.ok ? undefined : result.error.code,
    degradedProvider: !result.ok,
    ...providerMetricDefaults(result.metadata),
    audioDurationMs: result.metrics?.audioDurationMs ?? audioDurationMs,
    metadata: {
      streamId: input.streamId,
      confidence: result.ok ? result.data.confidence : null
    }
  });
}

async function transcribeWithPythonService(input: MediaStreamTranscriptionInput): Promise<ProviderResult<SttTranscript>> {
  const audio = getMediaStreamAudioBuffer(input.sessionId, input.streamId);
  const summary = getMediaStreamSummary(input.sessionId, input.streamId);
  if (!audio || !summary || audio.byteLength === 0) {
    const degradation = getVoiceDegradationPlan("STT_EMPTY_RESULT");
    return {
      ok: false,
      metadata: DEFAULT_STT_PROVIDER_METADATA,
      latencyMs: 0,
      error: {
        code: "EMPTY_RESULT",
        message: "Media stream has no audio chunks."
      },
      fallbackText: degradation.childSafeText
    };
  }

  const started = performance.now();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), input.timeoutMs ?? STT_TIMEOUT_MS);
  const audioDurationMs = summary.format.chunkDurationMs * summary.chunkCount;
  try {
    let audioForStt = audio;
    try {
      audioForStt = await transcodeToWav16kMono(audio, summary.format.mimeType);
    } catch (error) {
      console.warn(
        `[speech-stt] Audio transcode failed for stream ${input.streamId}: mime=${summary.format.mimeType}, bytes=${audio.byteLength}, chunks=${summary.chunkCount}, error=${
          error instanceof Error ? error.message : String(error)
        }`
      );
      const degradation = getVoiceDegradationPlan("STT_PROVIDER_UNAVAILABLE");
      return {
        ok: false,
        metadata: DEFAULT_STT_PROVIDER_METADATA,
        latencyMs: Math.round(performance.now() - started),
        error: {
          code: "AUDIO_TRANSCODE_FAILED",
          message: error instanceof Error ? error.message : "Unable to transcode captured audio for STT.",
          retryable: false
        },
        fallbackText: degradation.childSafeText
      };
    }

    const pythonVoiceServiceUrl = (runtimeConfig.pythonVoiceServiceUrl ?? "http://127.0.0.1:8765").replace(/\/+$/, "");
    const response = await fetch(`${pythonVoiceServiceUrl}/stt`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        requestId: input.correlationId,
        sessionId: input.sessionId,
        turnId: input.turnId,
        streamId: input.streamId,
        languageHint: input.languageHint ?? "zh-CN",
        audioBase64: audioForStt.toString("base64"),
        format: { ...summary.format, mimeType: "audio/wav", codec: "wav" }
      })
    });
    const latencyMs = Math.round(performance.now() - started);
    if (!response.ok) {
      const errorBody = await readResponseJson(response);
      const pythonError = readPythonSttError(errorBody);
      if (shouldFallbackToMockStt(response.status, pythonError.code)) {
        console.warn(
          `[speech-stt] Python voice service unavailable (${response.status}${pythonError.code ? `:${pythonError.code}` : ""})${
            pythonError.message ? `: ${pythonError.message}` : ""
          }.`
        );
      }
      const degradation = getVoiceDegradationPlan("STT_PROVIDER_UNAVAILABLE");
      return {
        ok: false,
        metadata: DEFAULT_STT_PROVIDER_METADATA,
        latencyMs,
        error: {
          code: mapPythonErrorToProviderCode(response.status, pythonError.code),
          message: pythonError.message ?? `Python STT service returned ${response.status}.`,
          retryable: response.status >= 500
        },
        fallbackText: degradation.childSafeText
      };
    }
    const body = (await response.json()) as {
      transcript?: string;
      confidence?: number;
      language?: string;
      durationMs?: number;
      processLatencyMs?: number;
      error?: { code?: string; message?: string };
    };
    if (body.error) {
      const degradation = getVoiceDegradationPlan("STT_EMPTY_RESULT");
      return {
        ok: false,
        metadata: getActiveSttMetadata(),
        latencyMs,
        error: {
          code: mapPythonErrorToProviderCode(response.status, body.error.code),
          message: body.error.message ?? "Python STT service returned an error.",
          retryable: false
        },
        fallbackText: degradation.childSafeText
      };
    }
    return applyTranscriptNormalization(input.sessionId, {
      ok: true,
      metadata: getActiveSttMetadata(),
      latencyMs,
      data: {
        turnId: input.turnId,
        audioSegmentId: input.streamId,
        transcriptRedacted: body.transcript ?? "",
        confidence: body.confidence ?? 0,
        language: body.language ?? input.languageHint ?? "zh-CN",
        startedAtMs: 0,
        endedAtMs: body.durationMs ?? audioDurationMs,
        isFinal: true,
        normalized: {
          text: body.transcript ?? "",
          lowConfidence: (body.confidence ?? 0) < 0.6,
          piiTypes: []
        }
      },
      metrics: {
        processLatencyMs: body.processLatencyMs ?? latencyMs,
        audioDurationMs: body.durationMs ?? audioDurationMs,
        gpuUsed: false,
        hardwareAcceleration: "CPU"
      }
    });
  } catch (error) {
    if (isPythonVoiceServiceUnreachable(error)) {
      console.warn("[speech-stt] Python voice service unreachable.");
    }
    const degradation = getVoiceDegradationPlan("STT_PROVIDER_UNAVAILABLE");
    const latencyMs = Math.round(performance.now() - started);
    return {
      ok: false,
      metadata: DEFAULT_STT_PROVIDER_METADATA,
      latencyMs,
      error: {
        code: error instanceof DOMException && error.name === "AbortError" ? "TIMEOUT" : "PROVIDER_FAILURE",
        message: error instanceof Error ? error.message : "Python STT service failed.",
        retryable: true
      },
      fallbackText: degradation.childSafeText
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function readResponseJson(response: Response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function readPythonSttError(body: unknown) {
  if (!body || typeof body !== "object") {
    return { code: undefined as string | undefined, message: undefined as string | undefined };
  }
  const error = (body as { error?: { code?: string; message?: string } }).error;
  return {
    code: error?.code,
    message: error?.message
  };
}

function shouldFallbackToMockStt(httpStatus: number, errorCode?: string) {
  if (errorCode === "UNSUPPORTED_AUDIO_FORMAT" || errorCode === "AUDIO_TOO_LARGE" || errorCode === "BAD_JSON") {
    return false;
  }
  if (errorCode === "LOCAL_MODEL_PENDING" || errorCode === "PROVIDER_FAILURE") {
    return true;
  }
  return httpStatus === 404 || httpStatus === 503 || httpStatus === 502 || httpStatus >= 500;
}

function mapPythonErrorToProviderCode(httpStatus: number, errorCode?: string): ProviderErrorCode {
  if (errorCode === "LOCAL_MODEL_PENDING") return "LOCAL_MODEL_PENDING";
  if (errorCode === "UNSUPPORTED_AUDIO_FORMAT") return "UNSUPPORTED_AUDIO_FORMAT";
  if (errorCode === "EMPTY_RESULT" || errorCode === "EMPTY_TEXT") return "EMPTY_RESULT";
  if (httpStatus === 408) return "TIMEOUT";
  return "PROVIDER_FAILURE";
}

function isPythonVoiceServiceUnreachable(error: unknown) {
  if (!(error instanceof Error)) return false;
  const message = error.message.toLowerCase();
  if (message.includes("fetch failed") || message.includes("econnrefused") || message.includes("enotfound")) {
    return true;
  }
  const cause = (error as Error & { cause?: unknown }).cause;
  if (cause instanceof Error) {
    const causeMessage = cause.message.toLowerCase();
    return causeMessage.includes("econnrefused") || causeMessage.includes("enotfound");
  }
  return false;
}

function persistSttLanguageFeatures(
  input: MediaStreamTranscriptionInput,
  result: ProviderResult<SttTranscript>,
  audioDurationMs?: number
) {
  if (!result.ok) return;
  persistLanguageObservationsFromTranscript({
    sessionId: input.sessionId,
    turnId: input.turnId,
    correlationId: input.correlationId,
    transcriptRedacted: result.data.transcriptRedacted,
    confidence: result.data.confidence,
    audioDurationMs: result.metrics?.audioDurationMs ?? audioDurationMs,
    duplicateOfTurnId: result.data.normalized?.duplicateOfTurnId,
    observedAt: new Date().toISOString()
  });
}
