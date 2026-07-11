type ReplyStrategy = "encourage" | "hint" | "praise" | "fallback";

export interface DialogueReply {
  reply: string;
  strategy: ReplyStrategy;
  timestamp: string;
}

const encourageKeywords = ["不会", "不懂", "难", "help", "怕"];
const praiseKeywords = ["我会了", "完成", "太简单", "好玩"];

function containsAny(text: string, keywords: string[]) {
  return keywords.some((keyword) => text.includes(keyword));
}

export function generateDialogueReply(text: string): DialogueReply {
  const normalized = text.trim().toLowerCase();

  if (!normalized) {
    return {
      reply: "你可以告诉我你现在想做什么，我会陪你一起完成。",
      strategy: "fallback",
      timestamp: new Date().toISOString()
    };
  }

  if (containsAny(normalized, encourageKeywords)) {
    return {
      reply: "没关系，我们一步一步来，你先试试最容易的那个选项。",
      strategy: "hint",
      timestamp: new Date().toISOString()
    };
  }

  if (containsAny(normalized, praiseKeywords)) {
    return {
      reply: "太棒了，你学得很快！继续保持！",
      strategy: "praise",
      timestamp: new Date().toISOString()
    };
  }

  return {
    reply: "我看到你很认真，继续加油，完成这一题就更厉害了！",
    strategy: "encourage",
    timestamp: new Date().toISOString()
  };
}
