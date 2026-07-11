/**
 * Force deterministic mock providers for backend tests regardless of developer .env.
 * Import this module before any backend dist imports in test files.
 */
process.env.VOICE_STT_PROVIDER = "mock";
process.env.VOICE_TTS_PROVIDER = "mock";
process.env.ATTENTION_PROVIDER = "mock";
process.env.EMOTION_PROVIDER = "heuristic";
process.env.RAW_MEDIA_PERSISTENCE = "disabled";
process.env.MONITOR_PREVIEW_ENABLED = "true";
process.env.AI_CHAT_PROVIDER = process.env.AI_CHAT_PROVIDER || "rule";
process.env.AI_TTS_PROVIDER = process.env.AI_TTS_PROVIDER || "none";
process.env.OPENAI_API_KEY = process.env.OPENAI_API_KEY || "";
process.env.REPORT_NARRATIVE_PROVIDER = "mock";
process.env.DEEPSEEK_API_KEY = "";
