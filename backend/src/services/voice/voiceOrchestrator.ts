import { runtimeConfig, validateRuntimeConfig } from "../../config/runtime.js";
import type { ChatMessageContext, ChatProvider, TtsProvider } from "./types.js";
import { RuleChatProvider } from "./providers/ruleChatProvider.js";
import { OpenAiChatProvider } from "./providers/openAiChatProvider.js";
import { AsdAgentChatProvider } from "./providers/asdAgentProvider.js";
import { NoopTtsProvider } from "./providers/noopTtsProvider.js";
import { OpenAiTtsProvider } from "./providers/openAiTtsProvider.js";
import { getSttProviderStatus } from "../speechSttService.js";
import { getSpeechTtsProviderStatus } from "../speechTtsService.js";

function createChatProvider(): ChatProvider {
  if (runtimeConfig.chatProvider === "asd") return new AsdAgentChatProvider();
  if (runtimeConfig.chatProvider === "openai") return new OpenAiChatProvider();
  return new RuleChatProvider();
}

function createTtsProvider(): TtsProvider {
  if (runtimeConfig.ttsProvider === "openai") return new OpenAiTtsProvider();
  return new NoopTtsProvider();
}

const chatProvider = createChatProvider();
const ttsProvider = createTtsProvider();

export interface VoiceAssistantResult {
  reply: string;
  strategy: string;
  provider: string;
  timestamp: string;
  audioBase64?: string;
  audioMimeType?: string;
}

export async function runVoiceAssistant(input: {
  childText: string;
  history: ChatMessageContext[];
  pageContextText?: string;
}): Promise<VoiceAssistantResult> {
  const chat = await chatProvider.generateReply(input);
  const tts = await ttsProvider.synthesize({ text: chat.reply });
  return {
    ...chat,
    audioBase64: tts?.audioBase64,
    audioMimeType: tts?.mimeType
  };
}

export function getVoiceProviderStatus() {
  return {
    chatProvider: chatProvider.name,
    dialogProvider: runtimeConfig.voiceDialogProvider,
    voicePartnerConfigured: Boolean(runtimeConfig.voicePartnerBaseUrl),
    voicePartnerFallback: runtimeConfig.voicePartnerFallback,
    sttProvider: getSttProviderStatus(),
    speechTtsProvider: getSpeechTtsProviderStatus(),
    ttsProvider: ttsProvider.name,
    configIssues: validateRuntimeConfig()
  };
}
