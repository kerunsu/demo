export function playMockSpeech(input: {
  turnId: string;
  text: string;
  onStarted: () => void;
  onFinished: (durationMs: number) => void;
  onFailed: () => void;
}) {
  try {
    input.onStarted();
    const durationMs = Math.min(2200, Math.max(700, input.text.length * 90));
    const timer = window.setTimeout(() => input.onFinished(durationMs), durationMs);
    return () => window.clearTimeout(timer);
  } catch {
    input.onFailed();
    return () => undefined;
  }
}
