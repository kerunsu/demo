import dotenv from "dotenv";
import path from "node:path";

dotenv.config();
dotenv.config({
  path:
    process.env.ASD_AGENT_ENV_FILE ||
    path.resolve(process.cwd(), "..", "..", "ExpertAnnotator_ASD-main", "asd_llm_agent", ".env")
});

type ChatProviderKind = "rule" | "openai" | "asd";
type ReportNarrativeProviderKind = "rule" | "mock" | "openai" | "deepseek";
type TtsProviderKind = "none" | "openai";
type SttProviderKind = "mock" | "local" | "cloud";
type VoiceTtsProviderKind = "mock" | "local" | "cloud";
type AttentionProviderKind = "mock" | "local";
type EmotionProviderKind = "local" | "heuristic" | "none";
type RawMediaPersistence = "disabled" | "enabled";
type VoiceDialogProviderKind = "rule" | "partner";
type VoicePartnerFallbackKind = "none" | "rule";

function getEnv(name: string, fallback?: string) {
  const value = process.env[name];
  if (value === undefined || value === "") return fallback;
  return value;
}

function asChatProvider(value: string | undefined): ChatProviderKind {
  if (value === "asd") return "asd";
  return value === "openai" ? "openai" : "rule";
}

function asReportNarrativeProvider(value: string | undefined): ReportNarrativeProviderKind {
  if (value === "openai") return "openai";
  if (value === "deepseek") return "deepseek";
  if (value === "rule") return "rule";
  return "mock";
}

function asTtsProvider(value: string | undefined): TtsProviderKind {
  return value === "openai" ? "openai" : "none";
}

function asSttProvider(value: string | undefined): SttProviderKind {
  if (value === "local" || value === "cloud") return value;
  return "mock";
}

function asVoiceTtsProvider(value: string | undefined): VoiceTtsProviderKind {
  if (value === "local" || value === "cloud") return value;
  return "mock";
}

function asAttentionProvider(value: string | undefined): AttentionProviderKind {
  return value === "local" ? "local" : "mock";
}

function asEmotionProvider(value: string | undefined): EmotionProviderKind {
  if (value === "none") return "none";
  if (value === "heuristic") return "heuristic";
  return "local";
}

function asRawMediaPersistence(value: string | undefined): RawMediaPersistence {
  return value === "enabled" ? "enabled" : "disabled";
}

function asVoiceDialogProvider(value: string | undefined): VoiceDialogProviderKind {
  return value === "partner" ? "partner" : "rule";
}

function asVoicePartnerFallback(value: string | undefined): VoicePartnerFallbackKind {
  return value === "rule" ? "rule" : "none";
}

export function getEmotionProviderKind(): EmotionProviderKind {
  return asEmotionProvider(getEnv("EMOTION_PROVIDER"));
}

function asPort(value: string | undefined, fallback: number) {
  if (!value) return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0 || parsed > 65535) {
    throw new Error(`Invalid backend port: ${value}`);
  }
  return parsed;
}

function asPositiveInteger(value: string | undefined, fallback: number) {
  if (!value) return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`Invalid positive integer: ${value}`);
  }
  return parsed;
}

function asBoolean(value: string | undefined, fallback: boolean) {
  if (!value) return fallback;
  return value.toLowerCase() === "true";
}

function trimTrailingSlash(value: string) {
  return value.replace(/\/+$/, "");
}

function asOrigin(value: string | undefined, fallback: string) {
  const raw = value || fallback;
  try {
    const parsed = new URL(raw);
    return trimTrailingSlash(parsed.origin);
  } catch {
    throw new Error(`Invalid origin URL: ${raw}`);
  }
}

function parseCorsOrigins(value: string | undefined) {
  if (!value || value.trim() === "" || value.trim() === "*") return true as const;
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => asOrigin(item, item));
}

export const runtimeConfig = {
  backendHost: getEnv("BACKEND_HOST", "127.0.0.1") ?? "127.0.0.1",
  backendPort: asPort(getEnv("BACKEND_PORT", getEnv("PORT")), 3001),
  publicBackendOrigin: asOrigin(getEnv("PUBLIC_BACKEND_ORIGIN"), "http://127.0.0.1:3001"),
  corsOrigins: parseCorsOrigins(getEnv("CORS_ORIGIN")),
  chatProvider: asChatProvider(getEnv("AI_CHAT_PROVIDER")),
  reportNarrativeProvider: asReportNarrativeProvider(getEnv("REPORT_NARRATIVE_PROVIDER")),
  ttsProvider: asTtsProvider(getEnv("AI_TTS_PROVIDER")),
  sttProvider: asSttProvider(getEnv("VOICE_STT_PROVIDER")),
  voiceTtsProvider: asVoiceTtsProvider(getEnv("VOICE_TTS_PROVIDER")),
  attentionProvider: asAttentionProvider(getEnv("ATTENTION_PROVIDER")),
  get emotionProvider() {
    return getEmotionProviderKind();
  },
  rawMediaPersistence: asRawMediaPersistence(getEnv("RAW_MEDIA_PERSISTENCE")),
  rawMediaRoot: getEnv("RAW_MEDIA_ROOT", ".runtime/media") ?? ".runtime/media",
  rawMediaRetentionDays: asPositiveInteger(getEnv("RAW_MEDIA_RETENTION_DAYS"), 7),
  rawMediaRequireConsent: asBoolean(getEnv("RAW_MEDIA_REQUIRE_CONSENT"), true),
  rawMediaEncryption: getEnv("RAW_MEDIA_ENCRYPTION", "optional") ?? "optional",
  monitorPreviewEnabled: asBoolean(getEnv("MONITOR_PREVIEW_ENABLED"), true),
  monitorPreviewMaxFps: asPositiveInteger(getEnv("MONITOR_PREVIEW_MAX_FPS"), 4),
  monitorPreviewWidth: asPositiveInteger(getEnv("MONITOR_PREVIEW_WIDTH"), 320),
  monitorPreviewHeight: asPositiveInteger(getEnv("MONITOR_PREVIEW_HEIGHT"), 240),
  monitorPreviewTtlMs: asPositiveInteger(getEnv("MONITOR_PREVIEW_TTL_MS"), 3000),
  monitorPreviewMaxBytes: asPositiveInteger(getEnv("MONITOR_PREVIEW_MAX_BYTES"), 256 * 1024),
  monitorPreviewJpegQuality: Math.min(1, Math.max(0.3, Number(getEnv("MONITOR_PREVIEW_JPEG_QUALITY", "0.6")) || 0.6)),
  pythonVoiceServiceUrl: getEnv("VOICE_PYTHON_SERVICE_URL", "http://127.0.0.1:8765"),
  openAiApiKey: getEnv("OPENAI_API_KEY", ""),
  openAiBaseUrl: getEnv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
  openAiChatModel: getEnv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
  openAiReportModel: getEnv("OPENAI_REPORT_MODEL", getEnv("OPENAI_CHAT_MODEL", "gpt-4o-mini") ?? "gpt-4o-mini"),
  deepSeekApiKey: getEnv("DEEPSEEK_API_KEY", ""),
  deepSeekBaseUrl: getEnv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
  deepSeekReportModel: getEnv("DEEPSEEK_REPORT_MODEL", "deepseek-chat"),
  openAiTtsModel: getEnv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
  openAiTtsVoice: getEnv("OPENAI_TTS_VOICE", "alloy"),
  asdLlmApiKey: getEnv("ASD_LLM_API_KEY", getEnv("LLM_API_KEY", "")),
  asdLlmBaseUrl: getEnv("ASD_LLM_BASE_URL", getEnv("LLM_BASE_URL", "https://api.deepseek.com")),
  asdLlmModel: getEnv("ASD_LLM_MODEL", getEnv("LLM_MODEL", "deepseek-chat")),
  asdLlmTimeoutMs: asPositiveInteger(getEnv("ASD_LLM_TIMEOUT_SECONDS", getEnv("REQUEST_TIMEOUT_SECONDS")), 90) * 1000,
  asdMaxHistoryMessages: asPositiveInteger(getEnv("ASD_MAX_HISTORY_MESSAGES", getEnv("MAX_HISTORY_MESSAGES")), 12),
  get voiceDialogProvider() {
    return asVoiceDialogProvider(getEnv("VOICE_DIALOG_PROVIDER"));
  },
  get voicePartnerBaseUrl() {
    return trimTrailingSlash(getEnv("VOICE_PARTNER_BASE_URL", "") ?? "");
  },
  get voicePartnerApiKey() {
    return getEnv("VOICE_PARTNER_API_KEY", "");
  },
  get voicePartnerTimeoutMs() {
    return asPositiveInteger(getEnv("VOICE_PARTNER_TIMEOUT_MS"), 30000);
  },
  get voicePartnerFallback() {
    return asVoicePartnerFallback(getEnv("VOICE_PARTNER_FALLBACK"));
  }
} as const;

export function validateRuntimeConfig() {
  const issues: string[] = [];
  if (!runtimeConfig.backendHost) {
    issues.push("BACKEND_HOST 不能为空");
  }
  if (runtimeConfig.chatProvider === "openai" && !runtimeConfig.openAiApiKey) {
    issues.push("AI_CHAT_PROVIDER=openai 但未配置 OPENAI_API_KEY");
  }
  if (runtimeConfig.reportNarrativeProvider === "openai" && !runtimeConfig.openAiApiKey) {
    issues.push("REPORT_NARRATIVE_PROVIDER=openai 但未配置 OPENAI_API_KEY（将降级为 rule_fallback）");
  }
  if (runtimeConfig.reportNarrativeProvider === "deepseek" && !runtimeConfig.deepSeekApiKey) {
    issues.push("REPORT_NARRATIVE_PROVIDER=deepseek 但未配置 DEEPSEEK_API_KEY（将降级为 rule_fallback）");
  }
  if (runtimeConfig.ttsProvider === "openai" && !runtimeConfig.openAiApiKey) {
    issues.push("AI_TTS_PROVIDER=openai 但未配置 OPENAI_API_KEY");
  }
  if (runtimeConfig.sttProvider === "cloud" && !runtimeConfig.openAiApiKey) {
    issues.push("VOICE_STT_PROVIDER=cloud 但未配置 OPENAI_API_KEY");
  }
  if (runtimeConfig.voiceTtsProvider === "cloud" && !runtimeConfig.openAiApiKey) {
    issues.push("VOICE_TTS_PROVIDER=cloud 但未配置 OPENAI_API_KEY");
  }
  if (runtimeConfig.voiceDialogProvider === "partner" && !runtimeConfig.voicePartnerBaseUrl) {
    issues.push("VOICE_DIALOG_PROVIDER=partner 但未配置 VOICE_PARTNER_BASE_URL");
  }
  return issues;
}
