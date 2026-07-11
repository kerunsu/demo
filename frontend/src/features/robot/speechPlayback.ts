export interface SpeechPlaybackInput {
  turnId: string;
  text: string;
  audioBase64?: string;
  mimeType?: string;
  durationMs?: number;
  onStarted: () => void;
  onFinished: (durationMs: number) => void;
  onFailed: () => void;
}

export function playSpeechAudio(input: SpeechPlaybackInput) {
  if (!input.audioBase64 || !input.mimeType) {
    return playTimedFallback(input);
  }

  try {
    const audio = new Audio(`data:${input.mimeType};base64,${input.audioBase64}`);
    let finished = false;
    const startedAt = performance.now();
    const fallbackDurationMs = input.durationMs ?? Math.min(2200, Math.max(700, input.text.length * 90));
    const fallbackTimer = window.setTimeout(() => {
      if (finished) return;
      finished = true;
      cleanup();
      input.onFinished(fallbackDurationMs);
    }, fallbackDurationMs + 1500);

    const cleanup = () => {
      window.clearTimeout(fallbackTimer);
      audio.onended = null;
      audio.onerror = null;
    };

    audio.onended = () => {
      if (finished) return;
      finished = true;
      const durationMs = Math.round(performance.now() - startedAt);
      cleanup();
      input.onFinished(durationMs || fallbackDurationMs);
    };
    audio.onerror = () => {
      if (finished) return;
      finished = true;
      cleanup();
      input.onFailed();
    };

    input.onStarted();
    void audio.play().catch(() => {
      if (finished) return;
      finished = true;
      cleanup();
      input.onFailed();
    });
    return () => {
      finished = true;
      cleanup();
      audio.pause();
    };
  } catch {
    input.onFailed();
    return () => undefined;
  }
}

function playTimedFallback(input: SpeechPlaybackInput) {
  try {
    input.onStarted();
    const durationMs = input.durationMs ?? Math.min(2200, Math.max(700, input.text.length * 90));
    const timer = window.setTimeout(() => input.onFinished(durationMs), durationMs);
    return () => window.clearTimeout(timer);
  } catch {
    input.onFailed();
    return () => undefined;
  }
}
