import { runtimeConfig } from "../config/runtime.js";

const PROBE_TIMEOUT_MS = 2000;

export type PythonVoiceHealthStatus =
  | "ok"
  | "unreachable"
  | "degraded:mock_providers"
  | "degraded:local_model_pending"
  | "degraded:provider_error"
  | "skipped:not_configured";

export interface PythonVoiceHealthBody {
  status?: string;
  sttProvider?: string;
  ttsProvider?: string;
  sttProviderStatus?: string;
  ttsProviderStatus?: string;
}

export interface PythonVoiceHealthProbe {
  status: PythonVoiceHealthStatus;
  sttProvider?: string;
  ttsProvider?: string;
  latencyMs?: number;
}

export function interpretPythonVoiceHealthBody(
  body: PythonVoiceHealthBody,
  options: { expectLocalStt: boolean; expectLocalTts: boolean }
): PythonVoiceHealthStatus {
  if (body.status !== "ok") return "degraded:provider_error";
  const mockStt = body.sttProvider === "mock";
  const mockTts = body.ttsProvider === "mock";
  if ((options.expectLocalStt && mockStt) || (options.expectLocalTts && mockTts)) {
    return "degraded:mock_providers";
  }
  if (body.sttProviderStatus === "LOCAL_MODEL_PENDING" || body.ttsProviderStatus === "LOCAL_MODEL_PENDING") {
    return "degraded:local_model_pending";
  }
  return "ok";
}

export function usesPythonVoiceService() {
  return runtimeConfig.sttProvider === "local" || runtimeConfig.voiceTtsProvider === "local";
}

export async function probePythonVoiceServiceHealth(): Promise<PythonVoiceHealthProbe> {
  const expectLocalStt = runtimeConfig.sttProvider === "local";
  const expectLocalTts = runtimeConfig.voiceTtsProvider === "local";
  if (!expectLocalStt && !expectLocalTts) {
    return { status: "skipped:not_configured" };
  }

  const baseUrl = (runtimeConfig.pythonVoiceServiceUrl ?? "http://127.0.0.1:8765").replace(/\/+$/, "");
  const started = performance.now();
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
    const response = await fetch(`${baseUrl}/health`, { signal: controller.signal });
    clearTimeout(timeout);
    const latencyMs = Math.round(performance.now() - started);
    if (!response.ok) {
      return { status: "degraded:provider_error", latencyMs };
    }
    const body = (await response.json()) as PythonVoiceHealthBody;
    const status = interpretPythonVoiceHealthBody(body, { expectLocalStt, expectLocalTts });
    return {
      status,
      latencyMs,
      sttProvider: body.sttProvider,
      ttsProvider: body.ttsProvider
    };
  } catch {
    return {
      status: "unreachable",
      latencyMs: Math.round(performance.now() - started)
    };
  }
}
