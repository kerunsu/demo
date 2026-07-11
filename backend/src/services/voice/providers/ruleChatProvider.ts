import type { ChatProvider, ChatReply } from "../types.js";

const encourageKeywords = ["不会", "不懂", "难", "help", "怕"];
const praiseKeywords = ["我会了", "完成", "太简单", "好玩"];

function containsAny(text: string, keywords: string[]) {
  return keywords.some((keyword) => text.includes(keyword));
}

function buildRuleReply(text: string): ChatReply {
  const normalized = text.trim().toLowerCase();
  const timestamp = new Date().toISOString();

  if (!normalized) {
    return {
      reply: "我陪你。先看屏幕吧。",
      strategy: "fallback",
      provider: "rule",
      timestamp
    };
  }

  if (containsAny(normalized, encourageKeywords)) {
    return {
      reply: "没关系。我陪你慢慢来。",
      strategy: "hint",
      provider: "rule",
      timestamp
    };
  }

  if (containsAny(normalized, praiseKeywords)) {
    return {
      reply: "回答正确，真棒！",
      strategy: "praise",
      provider: "rule",
      timestamp
    };
  }

  return {
    reply: "你很认真。我们继续吧。",
    strategy: "encourage",
    provider: "rule",
    timestamp
  };
}

export class RuleChatProvider implements ChatProvider {
  name = "rule";

  async generateReply(input: { childText: string }) {
    return buildRuleReply(input.childText);
  }
}
