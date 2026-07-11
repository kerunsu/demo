import { useEffect, useRef, useState } from "react";
import type { VoiceTurnPageContextPayload } from "child-education-training-demo/shared/voice-partner-contract";
import { BrowserAudioCaptureController, type BrowserAudioCaptureState } from "../features/voice/browserAudioCapture";
import { sendBrowserAudioFeatures } from "../features/voice/behaviorAudioClient";
import { sendPartnerVoiceTurn } from "../features/voice/partnerVoiceClient";
import { finishMediaStream, sendMediaChunk, startMediaStream, transcribeMediaStream } from "../features/voice/mediaIngressClient";
import {
  BrowserVoiceActivityDetector,
  type VoiceActivityDetectorState
} from "../features/voice/voiceActivityDetector";
import type { ChatReply } from "../types";

export type VoiceMode = "continuous" | "single";
export type VoiceDialogProviderKind = "rule" | "partner";

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: unknown) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

type UseVoiceCaptureArgs = {
  voiceMode: VoiceMode;
  sessionId?: string;
  dialogProvider?: VoiceDialogProviderKind;
  onFinalTranscript: (transcript: string) => void | Promise<void>;
  getPageContext?: () => Promise<VoiceTurnPageContextPayload>;
  onPartnerTurnComplete?: (reply: ChatReply) => void | Promise<void>;
  autoVoiceTriggerEnabled?: boolean;
};

type MediaFinishReason = "manual_stop" | "timeout" | "cancelled" | "disconnect" | "device_lost";
const MIN_SINGLE_TURN_RECORDING_MS = 1200;
const AUTO_TURN_MIN_RECORDING_MS = 900;
const AUTO_TURN_SILENCE_MS = 1200;
const AUTO_TURN_SILENCE_LEVEL = 0.018;
const AUTO_TURN_RESET_LEVEL = 0.024;
const AUTO_TRIGGER_COOLDOWN_MS = 900;

function createId(prefix: string) {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function mapFinishReason(state: BrowserAudioCaptureState): MediaFinishReason {
  if (state.stopReason === "timeout") return "timeout";
  if (state.stopReason === "cancelled") return "cancelled";
  if (state.stopReason === "device_lost" || state.status === "device_lost") return "device_lost";
  if (state.stopReason === "error") return "cancelled";
  return "manual_stop";
}

export function useVoiceCapture({
  voiceMode,
  sessionId,
  dialogProvider = "rule",
  onFinalTranscript,
  getPageContext,
  onPartnerTurnComplete,
  autoVoiceTriggerEnabled = false
}: UseVoiceCaptureArgs) {
  const [voiceSupported, setVoiceSupported] = useState(true);
  const [voiceListening, setVoiceListening] = useState(false);
  const [voiceFallbackReason, setVoiceFallbackReason] = useState<string | null>(null);
  const [interimText, setInterimText] = useState("");
  const [autoVoiceTriggerState, setAutoVoiceTriggerState] = useState<VoiceActivityDetectorState>({
    status: "idle",
    level: 0
  });
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const mediaCaptureRef = useRef<BrowserAudioCaptureController | null>(null);
  const voiceActivityDetectorRef = useRef<BrowserVoiceActivityDetector | null>(null);
  const mediaTurnRef = useRef<{
    sessionId: string;
    streamId: string;
    turnId: string;
    correlationId: string;
    formatStarted: boolean;
    startedAtMs: number;
  } | null>(null);
  const pendingChunkUploadsRef = useRef<Set<Promise<unknown>>>(new Set());
  const shouldKeepListeningRef = useRef(false);
  const voiceModeRef = useRef(voiceMode);
  const dialogProviderRef = useRef(dialogProvider);
  const autoVoiceTriggerEnabledRef = useRef(autoVoiceTriggerEnabled);
  const autoTurnActiveRef = useRef(false);
  const autoSilenceStartedAtRef = useRef<number | null>(null);
  const autoSilenceFrameRef = useRef<number | null>(null);
  const autoTriggerCooldownUntilRef = useRef(0);
  const finalizeInFlightRef = useRef(false);
  const finalizePromiseRef = useRef<Promise<void> | null>(null);
  const onFinalTranscriptRef = useRef(onFinalTranscript);
  const getPageContextRef = useRef(getPageContext);
  const onPartnerTurnCompleteRef = useRef(onPartnerTurnComplete);
  const parallelBrowserSpeechRef = useRef(false);

  useEffect(() => {
    voiceModeRef.current = voiceMode;
  }, [voiceMode]);

  useEffect(() => {
    dialogProviderRef.current = dialogProvider;
  }, [dialogProvider]);

  useEffect(() => {
    autoVoiceTriggerEnabledRef.current = autoVoiceTriggerEnabled;
    if (autoVoiceTriggerEnabled) {
      void startAutoVoiceDetection();
    } else {
      stopAutoVoiceDetection();
    }
  }, [autoVoiceTriggerEnabled]);

  useEffect(() => {
    onFinalTranscriptRef.current = onFinalTranscript;
  }, [onFinalTranscript]);

  useEffect(() => {
    getPageContextRef.current = getPageContext;
  }, [getPageContext]);

  useEffect(() => {
    onPartnerTurnCompleteRef.current = onPartnerTurnComplete;
  }, [onPartnerTurnComplete]);

  async function runPartnerTurn(turn: {
    sessionId: string;
    streamId: string;
    turnId: string;
    correlationId: string;
  }) {
    const buildContext = getPageContextRef.current;
    const onComplete = onPartnerTurnCompleteRef.current;
    if (!buildContext || !onComplete) {
      setVoiceFallbackReason("PARTNER_CONTEXT_UNAVAILABLE");
      return;
    }
    try {
      const pageContext = await buildContext();
      const reply = await sendPartnerVoiceTurn(turn.sessionId, {
        streamId: turn.streamId,
        turnId: turn.turnId,
        correlationId: turn.correlationId,
        pageContext,
        locale: "zh-CN",
        capturedAt: new Date().toISOString()
      });
      await onComplete(reply);
      setVoiceFallbackReason(null);
    } catch {
      setVoiceFallbackReason("PARTNER_TURN_FAILED");
    }
  }

  async function finalizeActiveMediaTurn(
    reason: MediaFinishReason,
    options: {
      transcribe?: boolean;
      partnerTurn?: boolean;
      turnFeatures?: BrowserAudioCaptureState["turnFeatures"];
      turn?: {
        sessionId: string;
        streamId: string;
        turnId: string;
        correlationId: string;
        formatStarted: boolean;
        startedAtMs: number;
      } | null;
    } = {}
  ) {
    const turn = options.turn ?? mediaTurnRef.current;
    if (!turn?.formatStarted || finalizeInFlightRef.current) return;
    finalizeInFlightRef.current = true;
    if (!options.turn && mediaTurnRef.current?.turnId === turn.turnId) {
      mediaTurnRef.current = null;
    } else if (options.turn && mediaTurnRef.current?.turnId === turn.turnId) {
      mediaTurnRef.current = null;
    }
    let resolveFinalize: (() => void) | undefined;
    const finalizePromise = new Promise<void>((resolve) => {
      resolveFinalize = resolve;
    });
    finalizePromiseRef.current = finalizePromise;
    try {
      if (options.turnFeatures) {
        try {
          await sendBrowserAudioFeatures({
            sessionId: turn.sessionId,
            turnId: turn.turnId,
            correlationId: turn.correlationId,
            observedAt: new Date().toISOString(),
            audioDurationMs: options.turnFeatures.audioDurationMs,
            features: options.turnFeatures
          });
        } catch {
          setVoiceFallbackReason("AUDIO_FEATURE_UPLOAD_FAILED");
        }
      }
      if (pendingChunkUploadsRef.current.size > 0) {
        await Promise.allSettled([...pendingChunkUploadsRef.current]);
      }
      try {
        await finishMediaStream({
          sessionId: turn.sessionId,
          streamId: turn.streamId,
          turnId: turn.turnId,
          correlationId: turn.correlationId,
          reason,
          endedAt: new Date().toISOString()
        });
      } catch {
        setVoiceFallbackReason("MEDIA_STREAM_FINISH_FAILED");
        return;
      }
      if (options.partnerTurn) {
        await runPartnerTurn(turn);
      } else if (options.transcribe) {
        try {
          const durationMs = options.turnFeatures?.audioDurationMs ?? 8000;
          const result = await transcribeMediaStream({
            sessionId: turn.sessionId,
            streamId: turn.streamId,
            turnId: turn.turnId,
            correlationId: turn.correlationId,
            languageHint: "zh-CN",
            timeoutMs: Math.min(15000, Math.max(8000, durationMs + 4000))
          });
          if (result.ok) {
            const transcript = result.data.normalized?.text ?? result.data.transcriptRedacted;
            if (transcript.trim()) {
              await onFinalTranscriptRef.current(transcript);
              setVoiceFallbackReason(null);
            } else {
              setVoiceFallbackReason("STT_EMPTY_RESULT");
            }
          } else {
            setVoiceFallbackReason(result.error.code);
          }
        } catch {
          setVoiceFallbackReason("STT_PROVIDER_UNAVAILABLE");
        }
      }
    } catch {
      setVoiceFallbackReason("MEDIA_TRANSPORT_FAILED");
    } finally {
      parallelBrowserSpeechRef.current = false;
      finalizeInFlightRef.current = false;
      resolveFinalize?.();
      if (finalizePromiseRef.current === finalizePromise) {
        finalizePromiseRef.current = null;
      }
    }
  }

  async function waitForPendingFinalize() {
    if (finalizePromiseRef.current) {
      await finalizePromiseRef.current;
    }
  }

  function getVoiceActivityDetector() {
    if (!voiceActivityDetectorRef.current) {
      voiceActivityDetectorRef.current = new BrowserVoiceActivityDetector({
        onStateChange: (state) => {
          setAutoVoiceTriggerState(state);
          if (state.errorCode) {
            setVoiceFallbackReason(state.errorCode);
          }
        },
        onVoiceStart: (stream) => {
          void handleAutoVoiceStart(stream);
        }
      });
    }
    return voiceActivityDetectorRef.current;
  }

  function stopAutoSilenceWatcher() {
    if (autoSilenceFrameRef.current !== null) {
      window.cancelAnimationFrame(autoSilenceFrameRef.current);
      autoSilenceFrameRef.current = null;
    }
    autoSilenceStartedAtRef.current = null;
  }

  function startAutoSilenceWatcher() {
    stopAutoSilenceWatcher();
    const tick = () => {
      const turn = mediaTurnRef.current;
      const controller = mediaCaptureRef.current;
      if (!autoTurnActiveRef.current || !turn || !controller) {
        stopAutoSilenceWatcher();
        return;
      }

      const state = controller.getState();
      if (state.status !== "recording") {
        autoSilenceFrameRef.current = window.requestAnimationFrame(tick);
        return;
      }

      const now = performance.now();
      const elapsedMs = now - turn.startedAtMs;
      if (elapsedMs >= AUTO_TURN_MIN_RECORDING_MS && state.level <= AUTO_TURN_SILENCE_LEVEL) {
        autoSilenceStartedAtRef.current ??= now;
        if (now - autoSilenceStartedAtRef.current >= AUTO_TURN_SILENCE_MS) {
          stopAutoSilenceWatcher();
          void controller.stop("manual_stop");
          return;
        }
      } else if (state.level >= AUTO_TURN_RESET_LEVEL) {
        autoSilenceStartedAtRef.current = null;
      }

      autoSilenceFrameRef.current = window.requestAnimationFrame(tick);
    };
    autoSilenceFrameRef.current = window.requestAnimationFrame(tick);
  }

  async function handleAutoVoiceStart(mediaStream?: MediaStream) {
    if (!autoVoiceTriggerEnabledRef.current || mediaTurnRef.current || finalizeInFlightRef.current) return;
    if (performance.now() < autoTriggerCooldownUntilRef.current) {
      mediaStream?.getTracks().forEach((track) => track.stop());
      void startAutoVoiceDetection();
      return;
    }

    autoTurnActiveRef.current = true;
    await startVoiceCapture("single", { autoTriggered: true, mediaStream });
    if (mediaTurnRef.current) {
      startAutoSilenceWatcher();
    } else {
      autoTurnActiveRef.current = false;
      stopAutoSilenceWatcher();
      void startAutoVoiceDetection();
    }
  }

  async function startAutoVoiceDetection() {
    if (!autoVoiceTriggerEnabledRef.current || mediaTurnRef.current || finalizeInFlightRef.current) return;
    if (performance.now() < autoTriggerCooldownUntilRef.current) {
      window.setTimeout(() => {
        void startAutoVoiceDetection();
      }, Math.max(120, autoTriggerCooldownUntilRef.current - performance.now()));
      return;
    }
    const detector = getVoiceActivityDetector();
    await detector.start();
    if (!autoVoiceTriggerEnabledRef.current || mediaTurnRef.current || finalizeInFlightRef.current) {
      detector.stop("idle");
    }
  }

  function stopAutoVoiceDetection() {
    voiceActivityDetectorRef.current?.stop("idle");
  }

  function startParallelBrowserRecognition() {
    // The active product path uses MediaRecorder + backend local STT. Browser SpeechRecognition
    // is only useful for partner-mode captions and can produce misleading microphone errors.
    if (dialogProviderRef.current !== "partner" || !recognitionRef.current || parallelBrowserSpeechRef.current) {
      return;
    }
    const recognition = recognitionRef.current;
    try {
      recognition.continuous = false;
      recognition.interimResults = true;
      parallelBrowserSpeechRef.current = true;
      recognition.start();
    } catch {
      parallelBrowserSpeechRef.current = false;
    }
  }

  async function handleMediaStateChange(state: BrowserAudioCaptureState) {
    setVoiceListening(state.status === "recording" || state.status === "requesting_permission" || state.status === "stopping");
    if (state.status === "unsupported") {
      setVoiceFallbackReason("MEDIA_RECORDER_UNSUPPORTED");
      setVoiceSupported(Boolean(recognitionRef.current));
    }
    if (state.status === "permission_denied" || state.status === "no_device" || state.status === "device_lost" || state.status === "error") {
      setVoiceFallbackReason(state.errorCode ?? state.status.toUpperCase());
    }

    if (state.status !== "stopped" && state.status !== "cancelled" && state.status !== "device_lost") {
      return;
    }

    const keepListening = shouldKeepListeningRef.current;
    const mode = voiceModeRef.current;
    const reason = mapFinishReason(state);
    const isPartner = dialogProviderRef.current === "partner";
    const wasAutoTurn = autoTurnActiveRef.current;
    const finishedByVoiceTurn = reason === "manual_stop" || (wasAutoTurn && reason === "timeout");
    const shouldPartnerTurn = isPartner && finishedByVoiceTurn;
    const shouldTranscribe = !isPartner && finishedByVoiceTurn;
    const turnSnapshot = mediaTurnRef.current;
    autoTurnActiveRef.current = false;
    stopAutoSilenceWatcher();

    await finalizeActiveMediaTurn(reason, {
      partnerTurn: shouldPartnerTurn,
      transcribe: shouldTranscribe,
      turnFeatures: state.turnFeatures,
      turn: turnSnapshot
    });
    setVoiceListening(false);
    setInterimText("");
    if (wasAutoTurn) {
      autoTriggerCooldownUntilRef.current = performance.now() + AUTO_TRIGGER_COOLDOWN_MS;
    }

    if (keepListening && mode === "continuous" && reason !== "manual_stop") {
      void startVoiceCapture("continuous");
    } else if (autoVoiceTriggerEnabledRef.current) {
      window.setTimeout(() => {
        void startAutoVoiceDetection();
      }, wasAutoTurn ? AUTO_TRIGGER_COOLDOWN_MS : 0);
    }
  }

  const handleMediaStateChangeRef = useRef(handleMediaStateChange);
  handleMediaStateChangeRef.current = handleMediaStateChange;

  useEffect(() => {
    const controller = new BrowserAudioCaptureController({
      onStateChange: (state) => {
        void handleMediaStateChangeRef.current(state);
      },
      onChunk: (chunk) => {
        const turn = mediaTurnRef.current;
        if (!turn || !turn.formatStarted) return;
        const activeTurn = turn;
        const upload = sendMediaChunk({
          sessionId: activeTurn.sessionId,
          turnId: activeTurn.turnId,
          correlationId: activeTurn.correlationId,
          chunk
        }).catch(() => {
          if (mediaTurnRef.current?.turnId === activeTurn.turnId) {
            setVoiceFallbackReason("MEDIA_TRANSPORT_FAILED");
          }
        });
        pendingChunkUploadsRef.current.add(upload);
        void upload.finally(() => {
          pendingChunkUploadsRef.current.delete(upload);
        });
      }
    });
    mediaCaptureRef.current = controller;
    setVoiceSupported(controller.getState().status !== "unsupported");
    return () => {
      shouldKeepListeningRef.current = false;
      autoVoiceTriggerEnabledRef.current = false;
      autoTurnActiveRef.current = false;
      stopAutoSilenceWatcher();
      voiceActivityDetectorRef.current?.dispose();
      voiceActivityDetectorRef.current = null;
      void (async () => {
        const turn = mediaTurnRef.current;
        const active = controller.getState();
        if (turn?.formatStarted && (active.status === "recording" || active.status === "requesting_permission")) {
          await controller.stop("manual_stop");
        } else if (turn?.formatStarted) {
          await finalizeActiveMediaTurn("disconnect");
        }
        controller.dispose();
      })();
      mediaCaptureRef.current = null;
    };
  }, []);

  useEffect(() => {
    const SpeechRecognitionCtor =
      (window as unknown as { SpeechRecognition?: new () => SpeechRecognitionLike }).SpeechRecognition ??
      (window as unknown as { webkitSpeechRecognition?: new () => SpeechRecognitionLike }).webkitSpeechRecognition;

    if (!SpeechRecognitionCtor) {
      setVoiceFallbackReason("BROWSER_SPEECH_COMPAT_UNAVAILABLE");
      return;
    }

    const recognition = new SpeechRecognitionCtor();
    recognition.lang = "zh-CN";
    recognition.interimResults = true;
    recognition.continuous = false;

    recognition.onresult = (rawEvent) => {
      const event = rawEvent as {
        resultIndex: number;
        results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal?: boolean }>;
      };
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const piece = event.results[i][0]?.transcript?.trim() ?? "";
        if (!piece) continue;
        if (event.results[i].isFinal) {
          void onFinalTranscriptRef.current(piece);
        } else {
          interim += piece;
        }
      }
      setInterimText(interim);
    };

    recognition.onerror = () => {
      setVoiceListening(false);
      setInterimText("");
      if (parallelBrowserSpeechRef.current) {
        parallelBrowserSpeechRef.current = false;
      }
    };

    recognition.onend = () => {
      if (parallelBrowserSpeechRef.current) {
        parallelBrowserSpeechRef.current = false;
        return;
      }
      setVoiceListening(false);
      setInterimText("");
      if (shouldKeepListeningRef.current && voiceModeRef.current === "continuous") {
        try {
          recognition.continuous = true;
          recognition.start();
          setVoiceListening(true);
        } catch {
          // Browser APIs can reject duplicate start calls during onend.
        }
      }
    };

    recognitionRef.current = recognition;
    return () => {
      shouldKeepListeningRef.current = false;
      try {
        recognition.stop();
      } catch {
        // ignore
      }
      recognitionRef.current = null;
    };
  }, []);

  async function startVoiceCapture(targetMode?: VoiceMode, options: { autoTriggered?: boolean; mediaStream?: MediaStream } = {}) {
    await waitForPendingFinalize();
    stopAutoVoiceDetection();
    if (!options.autoTriggered) {
      autoTurnActiveRef.current = false;
      stopAutoSilenceWatcher();
    }
    const activeSessionId = sessionId || "pre-session-local-voice";
    const controller = mediaCaptureRef.current;
    if (!controller) {
      setVoiceFallbackReason("MEDIA_RECORDER_UNSUPPORTED");
      options.mediaStream?.getTracks().forEach((track) => track.stop());
      if (options.autoTriggered) {
        autoTurnActiveRef.current = false;
        void startAutoVoiceDetection();
      }
      return;
    }

    const activeState = controller.getState();
    if (activeState.status === "recording" || activeState.status === "stopping" || activeState.status === "requesting_permission") {
      await controller.stop("cancelled");
      await waitForPendingFinalize();
    }

    const turnId = createId("voice-turn");
    const correlationId = createId("voice-corr");
    const streamId = createId("stream");
    const mode = targetMode ?? voiceModeRef.current;
    const chunkDurationMs = mode === "continuous" ? 500 : 250;
    const maxTurnDurationMs = options.autoTriggered ? 10000 : mode === "continuous" ? 10000 : 8000;
    const startedAt = new Date().toISOString();

    try {
      await startMediaStream({
        sessionId: activeSessionId,
        streamId,
        turnId,
        correlationId,
        startedAt,
        format: {
          codec: "wav",
          mimeType: "audio/wav",
          sampleRateHz: 16000,
          channels: 1,
          chunkDurationMs
        },
        maxTurnDurationMs
      });
    } catch {
      setVoiceFallbackReason("MEDIA_STREAM_START_FAILED");
      options.mediaStream?.getTracks().forEach((track) => track.stop());
      if (options.autoTriggered) {
        autoTurnActiveRef.current = false;
        void startAutoVoiceDetection();
      }
      return;
    }

    mediaTurnRef.current = {
      sessionId: activeSessionId,
      streamId,
      turnId,
      correlationId,
      formatStarted: true,
      startedAtMs: performance.now()
    };

    const state = await controller.start({
      streamId,
      chunkDurationMs,
      maxTurnDurationMs,
      mimeType: "audio/wav",
      mediaStream: options.mediaStream
    });

    if (state.status !== "recording" || state.streamId !== streamId) {
      mediaTurnRef.current = null;
      try {
        await finishMediaStream({
          sessionId: activeSessionId,
          streamId,
          turnId,
          correlationId,
          reason: "cancelled",
          endedAt: new Date().toISOString()
        });
      } catch {
        setVoiceFallbackReason("MEDIA_STREAM_START_FAILED");
      }
      setVoiceFallbackReason(state.errorCode ?? state.status.toUpperCase());
      if (options.autoTriggered) {
        autoTurnActiveRef.current = false;
        void startAutoVoiceDetection();
      }
      return;
    }

    shouldKeepListeningRef.current = mode === "continuous";
    setVoiceFallbackReason(null);
    if (dialogProviderRef.current === "partner") {
      startParallelBrowserRecognition();
    }
  }

  function startBrowserSpeechCompatibilityCapture(targetMode?: VoiceMode) {
    if (dialogProviderRef.current !== "partner" || !recognitionRef.current) {
      setVoiceFallbackReason("MEDIA_RECORDER_UNSUPPORTED");
      return;
    }
    const recognition = recognitionRef.current;
    const mode = targetMode ?? voiceModeRef.current;
    try {
      recognition.continuous = mode === "continuous";
      recognition.interimResults = true;
      shouldKeepListeningRef.current = mode === "continuous";
      recognition.start();
      setVoiceListening(true);
      setVoiceFallbackReason("BROWSER_SPEECH_COMPAT_FALLBACK");
    } catch {
      setVoiceFallbackReason("MICROPHONE_UNAVAILABLE");
    }
  }

  async function stopVoiceCapture() {
    shouldKeepListeningRef.current = false;
    if (mediaCaptureRef.current && mediaTurnRef.current) {
      const remainingMs = Math.max(0, MIN_SINGLE_TURN_RECORDING_MS - (performance.now() - mediaTurnRef.current.startedAtMs));
      if (remainingMs > 0) {
        await new Promise<void>((resolve) => window.setTimeout(resolve, remainingMs));
      }
      await mediaCaptureRef.current.stop("manual_stop");
      await waitForPendingFinalize();
      return;
    }

    if (!recognitionRef.current) return;
    try {
      recognitionRef.current.stop();
    } catch {
      // ignore
    }
    setVoiceListening(false);
    setInterimText("");
  }

  return {
    autoVoiceTriggerState,
    interimText,
    startVoiceCapture,
    stopVoiceCapture,
    voiceFallbackReason,
    voiceListening,
    voiceSupported
  };
}
