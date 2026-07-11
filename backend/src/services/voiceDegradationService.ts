export type VoiceDegradationReason =
  | "MICROPHONE_UNAVAILABLE"
  | "MEDIA_TRANSPORT_FAILED"
  | "STT_PROVIDER_UNAVAILABLE"
  | "STT_EMPTY_RESULT"
  | "STT_LOW_CONFIDENCE"
  | "TTS_PROVIDER_UNAVAILABLE"
  | "TTS_SAFETY_REJECTED"
  | "WEBSOCKET_DISCONNECTED"
  | "ROBOT_AUDIO_PLAYBACK_FAILED";

export type VoiceFallbackMode = "retry_voice" | "manual_text" | "fixed_audio" | "display_text_only" | "resume_when_reconnected";

export interface VoiceDegradationPlan {
  reason: VoiceDegradationReason;
  fallbackMode: VoiceFallbackMode;
  childSafeText: string;
  retryable: boolean;
  fixedAudioAllowed: boolean;
  rawAudioPersisted: false;
  externalNetworkRequired: false;
}

const PLANS: Record<VoiceDegradationReason, VoiceDegradationPlan> = {
  MICROPHONE_UNAVAILABLE: {
    reason: "MICROPHONE_UNAVAILABLE",
    fallbackMode: "manual_text",
    childSafeText: "麦克风现在不能用，你可以先用手点答案。",
    retryable: true,
    fixedAudioAllowed: false,
    rawAudioPersisted: false,
    externalNetworkRequired: false
  },
  MEDIA_TRANSPORT_FAILED: {
    reason: "MEDIA_TRANSPORT_FAILED",
    fallbackMode: "retry_voice",
    childSafeText: "刚才的声音没有传过去，我们再试一次。",
    retryable: true,
    fixedAudioAllowed: false,
    rawAudioPersisted: false,
    externalNetworkRequired: false
  },
  STT_PROVIDER_UNAVAILABLE: {
    reason: "STT_PROVIDER_UNAVAILABLE",
    fallbackMode: "manual_text",
    childSafeText: "我暂时没有听清楚，你可以再说一次，或者用手点答案。",
    retryable: true,
    fixedAudioAllowed: false,
    rawAudioPersisted: false,
    externalNetworkRequired: false
  },
  STT_EMPTY_RESULT: {
    reason: "STT_EMPTY_RESULT",
    fallbackMode: "retry_voice",
    childSafeText: "我没有听清楚，请你再说一次。",
    retryable: true,
    fixedAudioAllowed: false,
    rawAudioPersisted: false,
    externalNetworkRequired: false
  },
  STT_LOW_CONFIDENCE: {
    reason: "STT_LOW_CONFIDENCE",
    fallbackMode: "retry_voice",
    childSafeText: "我不太确定听对了没有，请你再说一遍。",
    retryable: true,
    fixedAudioAllowed: false,
    rawAudioPersisted: false,
    externalNetworkRequired: false
  },
  TTS_PROVIDER_UNAVAILABLE: {
    reason: "TTS_PROVIDER_UNAVAILABLE",
    fallbackMode: "fixed_audio",
    childSafeText: "我们继续做题吧。",
    retryable: true,
    fixedAudioAllowed: true,
    rawAudioPersisted: false,
    externalNetworkRequired: false
  },
  TTS_SAFETY_REJECTED: {
    reason: "TTS_SAFETY_REJECTED",
    fallbackMode: "fixed_audio",
    childSafeText: "我们继续做题吧。",
    retryable: false,
    fixedAudioAllowed: true,
    rawAudioPersisted: false,
    externalNetworkRequired: false
  },
  WEBSOCKET_DISCONNECTED: {
    reason: "WEBSOCKET_DISCONNECTED",
    fallbackMode: "resume_when_reconnected",
    childSafeText: "连接正在恢复，请稍等一下。",
    retryable: true,
    fixedAudioAllowed: false,
    rawAudioPersisted: false,
    externalNetworkRequired: false
  },
  ROBOT_AUDIO_PLAYBACK_FAILED: {
    reason: "ROBOT_AUDIO_PLAYBACK_FAILED",
    fallbackMode: "display_text_only",
    childSafeText: "请看屏幕上的提示，我们继续。",
    retryable: true,
    fixedAudioAllowed: true,
    rawAudioPersisted: false,
    externalNetworkRequired: false
  }
};

export function getVoiceDegradationPlan(reason: VoiceDegradationReason): VoiceDegradationPlan {
  return PLANS[reason];
}

export function mapProviderErrorToVoiceDegradation(code?: string): VoiceDegradationPlan {
  if (code === "EMPTY_RESULT") return getVoiceDegradationPlan("STT_EMPTY_RESULT");
  if (code === "LOW_CONFIDENCE") return getVoiceDegradationPlan("STT_LOW_CONFIDENCE");
  if (code === "SAFETY_REJECTED" || code === "UNREVIEWED_TEXT") return getVoiceDegradationPlan("TTS_SAFETY_REJECTED");
  if (code === "CLOUD_CREDENTIALS_PENDING" || code === "LOCAL_MODEL_PENDING" || code === "TIMEOUT" || code === "PROVIDER_FAILURE") {
    return getVoiceDegradationPlan("STT_PROVIDER_UNAVAILABLE");
  }
  return getVoiceDegradationPlan("MEDIA_TRANSPORT_FAILED");
}
