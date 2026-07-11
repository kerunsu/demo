import type { ChatReply } from "../../types";

const VOICE_STORAGE_KEY = "asd-agent-voice-name";

export type BrowserSpeechVoiceOption = {
  name: string;
  lang: string;
  label: string;
};

type PlaybackOptions = {
  browserSpeechFallback?: boolean;
  onStart?: () => void;
  onEnd?: () => void;
  onError?: (reason: string) => void;
};

let availableVoices: SpeechSynthesisVoice[] = [];
let preferredVoice: SpeechSynthesisVoice | null = null;
let speechUnlocked = false;
let activeAudio: HTMLAudioElement | null = null;

function getSpeechSynthesis() {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return null;
  return window.speechSynthesis;
}

function getSavedVoiceName() {
  try {
    return window.localStorage.getItem(VOICE_STORAGE_KEY);
  } catch {
    return null;
  }
}

function saveVoiceName(name: string) {
  try {
    window.localStorage.setItem(VOICE_STORAGE_KEY, name);
  } catch {
    // Voice preference is convenience-only.
  }
}

export function loadBrowserSpeechVoices() {
  const synth = getSpeechSynthesis();
  if (!synth) {
    availableVoices = [];
    preferredVoice = null;
    return [];
  }

  const voices = synth.getVoices();
  const chineseVoices = voices.filter((voice) => voice.lang.toLowerCase().startsWith("zh"));
  const otherVoices = voices.filter((voice) => !voice.lang.toLowerCase().startsWith("zh"));
  availableVoices = [...chineseVoices, ...otherVoices];
  const savedVoiceName = getSavedVoiceName();

  preferredVoice =
    availableVoices.find((voice) => voice.name === savedVoiceName) ??
    availableVoices.find((voice) => voice.lang === "zh-CN") ??
    availableVoices.find((voice) => voice.lang.toLowerCase().startsWith("zh")) ??
    availableVoices[0] ??
    null;

  return availableVoices.map((voice) => ({
    name: voice.name,
    lang: voice.lang,
    label: `${voice.name} (${voice.lang})`
  }));
}

export function subscribeBrowserSpeechVoiceChanges(onChange: () => void) {
  const synth = getSpeechSynthesis();
  if (!synth) return () => undefined;
  synth.addEventListener("voiceschanged", onChange);
  return () => synth.removeEventListener("voiceschanged", onChange);
}

export function getPreferredBrowserSpeechVoiceName() {
  loadBrowserSpeechVoices();
  return preferredVoice?.name ?? "";
}

export function setPreferredBrowserSpeechVoice(name: string) {
  loadBrowserSpeechVoices();
  preferredVoice = availableVoices.find((voice) => voice.name === name) ?? preferredVoice;
  if (preferredVoice) {
    saveVoiceName(preferredVoice.name);
  }
}

export function isBrowserSpeechSynthesisSupported() {
  return Boolean(getSpeechSynthesis());
}

export function unlockBrowserSpeechOutput() {
  const synth = getSpeechSynthesis();
  if (!synth || speechUnlocked) return;
  loadBrowserSpeechVoices();
  const utterance = new SpeechSynthesisUtterance("。");
  utterance.lang = "zh-CN";
  utterance.volume = 0.01;
  utterance.rate = 1;
  if (preferredVoice) {
    utterance.voice = preferredVoice;
  }
  utterance.onend = () => {
    speechUnlocked = true;
  };
  utterance.onerror = () => {
    speechUnlocked = true;
  };
  synth.cancel();
  synth.speak(utterance);
}

export function stopChatReplyAudio() {
  if (activeAudio) {
    activeAudio.pause();
    activeAudio.src = "";
    activeAudio = null;
  }
  getSpeechSynthesis()?.cancel();
}

export function playChatReplyAudio(reply: ChatReply, options: PlaybackOptions = {}) {
  stopChatReplyAudio();
  if (reply.audioBase64 && reply.audioMimeType) {
    const audio = new Audio(`data:${reply.audioMimeType};base64,${reply.audioBase64}`);
    activeAudio = audio;
    audio.onplay = () => options.onStart?.();
    audio.onended = () => {
      if (activeAudio === audio) activeAudio = null;
      options.onEnd?.();
    };
    audio.onerror = () => {
      if (activeAudio === audio) activeAudio = null;
      options.onError?.("AUDIO_PLAYBACK_FAILED");
    };
    void audio.play().catch(() => {
      if (activeAudio === audio) activeAudio = null;
      options.onError?.("AUDIO_PLAYBACK_BLOCKED");
    });
    return;
  }

  if (options.browserSpeechFallback === false) return;
  speakBrowserText(reply.reply, options);
}

function speakBrowserText(text: string, options: PlaybackOptions) {
  const synth = getSpeechSynthesis();
  if (!synth) {
    options.onError?.("BROWSER_SPEECH_OUTPUT_UNSUPPORTED");
    return;
  }

  loadBrowserSpeechVoices();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = preferredVoice?.lang || "zh-CN";
  utterance.rate = 0.88;
  utterance.pitch = 1.05;
  utterance.volume = 1;
  if (preferredVoice) {
    utterance.voice = preferredVoice;
  }

  utterance.onstart = () => {
    speechUnlocked = true;
    options.onStart?.();
  };
  utterance.onend = () => options.onEnd?.();
  utterance.onerror = (event) => options.onError?.(event.error || "BROWSER_SPEECH_OUTPUT_FAILED");

  window.setTimeout(() => {
    synth.cancel();
    synth.speak(utterance);
  }, 80);
}
