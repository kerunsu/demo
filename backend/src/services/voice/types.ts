export interface ChatMessageContext {
  role: "system" | "user" | "assistant";
  text: string;
}

export interface ChatReply {
  reply: string;
  strategy: string;
  provider: string;
  timestamp: string;
}

export interface ChatProvider {
  name: string;
  generateReply(input: { childText: string; history: ChatMessageContext[]; pageContextText?: string }): Promise<ChatReply>;
}

export interface TtsSynthesis {
  audioBase64: string;
  mimeType: string;
}

export interface TtsProvider {
  name: string;
  synthesize(input: { text: string }): Promise<TtsSynthesis | null>;
}
