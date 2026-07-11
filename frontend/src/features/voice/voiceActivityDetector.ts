import { rmsFromByteTimeDomain } from "child-education-training-demo/shared/browser-audio-features";

export type VoiceActivityDetectorStatus =
  | "idle"
  | "requesting_permission"
  | "listening"
  | "triggered"
  | "permission_denied"
  | "no_device"
  | "unsupported"
  | "error";

export type VoiceActivityDetectorState = {
  status: VoiceActivityDetectorStatus;
  level: number;
  errorCode?: string;
  errorMessage?: string;
};

export type VoiceActivityDetectorOptions = {
  startThreshold?: number;
  minVoiceMs?: number;
};

export type VoiceActivityDetectorCallbacks = {
  onStateChange?: (state: VoiceActivityDetectorState) => void;
  onVoiceStart?: (stream: MediaStream) => void;
};

type BrowserMediaDevices = Pick<MediaDevices, "enumerateDevices" | "getUserMedia">;

const DEFAULT_START_THRESHOLD = 0.03;
const DEFAULT_MIN_VOICE_MS = 40;

function isPermissionDenied(error: unknown) {
  return error instanceof DOMException && (error.name === "NotAllowedError" || error.name === "SecurityError");
}

function isNoDevice(error: unknown) {
  return error instanceof DOMException && (error.name === "NotFoundError" || error.name === "DevicesNotFoundError");
}

function buildAudioConstraints(deviceId?: string): MediaTrackConstraints {
  return {
    deviceId: deviceId ? { exact: deviceId } : undefined,
    echoCancellation: { ideal: true },
    noiseSuppression: { ideal: true },
    autoGainControl: { ideal: true },
    channelCount: { ideal: 1 }
  };
}

async function openAudioStream(mediaDevices: BrowserMediaDevices) {
  const attempts: MediaStreamConstraints[] = [{ audio: buildAudioConstraints() }, { audio: true }];

  try {
    const inputDevices = (await mediaDevices.enumerateDevices()).filter((device) => device.kind === "audioinput" && device.deviceId);
    const preferredDevices = [...inputDevices].sort((a, b) => {
      const aUsb = /usb/i.test(a.label) ? 0 : 1;
      const bUsb = /usb/i.test(b.label) ? 0 : 1;
      return aUsb - bUsb;
    });
    for (const device of preferredDevices) {
      attempts.push({ audio: buildAudioConstraints(device.deviceId) });
      attempts.push({ audio: { deviceId: { exact: device.deviceId } } });
    }
  } catch {
    // Device enumeration can fail before permission is granted; the generic attempts still apply.
  }

  let lastError: unknown;
  for (const constraints of attempts) {
    try {
      return await mediaDevices.getUserMedia(constraints);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}

export class BrowserVoiceActivityDetector {
  private mediaDevices: BrowserMediaDevices | null;
  private callbacks: VoiceActivityDetectorCallbacks;
  private mediaStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private frameId: number | null = null;
  private voiceStartedAtMs: number | null = null;
  private options: Required<VoiceActivityDetectorOptions> = {
    startThreshold: DEFAULT_START_THRESHOLD,
    minVoiceMs: DEFAULT_MIN_VOICE_MS
  };
  private state: VoiceActivityDetectorState = { status: "idle", level: 0 };

  constructor(
    callbacks: VoiceActivityDetectorCallbacks = {},
    mediaDevices: BrowserMediaDevices | null = typeof navigator === "undefined" ? null : navigator.mediaDevices ?? null
  ) {
    this.callbacks = callbacks;
    this.mediaDevices = mediaDevices;
  }

  getState() {
    return this.state;
  }

  async start(options: VoiceActivityDetectorOptions = {}) {
    if (this.state.status === "listening" || this.state.status === "requesting_permission") {
      return this.state;
    }
    if (!this.mediaDevices?.getUserMedia || typeof AudioContext === "undefined") {
      this.updateState({ status: "unsupported", errorCode: "VOICE_ACTIVITY_UNSUPPORTED", level: 0 });
      return this.state;
    }

    this.options = {
      startThreshold: options.startThreshold ?? DEFAULT_START_THRESHOLD,
      minVoiceMs: options.minVoiceMs ?? DEFAULT_MIN_VOICE_MS
    };
    this.updateState({ status: "requesting_permission", level: 0, errorCode: undefined, errorMessage: undefined });

    try {
      const stream = await openAudioStream(this.mediaDevices);
      const audioContext = new AudioContext();
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 512;
      audioContext.createMediaStreamSource(stream).connect(analyser);

      this.mediaStream = stream;
      this.audioContext = audioContext;
      this.analyser = analyser;
      this.voiceStartedAtMs = null;
      this.updateState({ status: "listening", level: 0 });
      this.startMeter();
    } catch (error) {
      if (isPermissionDenied(error)) {
        this.updateState({ status: "permission_denied", errorCode: "MIC_PERMISSION_DENIED", level: 0 });
      } else if (isNoDevice(error)) {
        this.updateState({ status: "no_device", errorCode: "NO_MICROPHONE", level: 0 });
      } else {
        this.updateState({
          status: "error",
          errorCode: "VOICE_ACTIVITY_FAILED",
          errorMessage: error instanceof Error ? error.message : "Unable to monitor microphone level.",
          level: 0
        });
      }
      this.releaseResources();
    }

    return this.state;
  }

  stop(status: VoiceActivityDetectorStatus = "idle") {
    this.releaseResources();
    this.updateState({ status, level: 0 });
    return this.state;
  }

  dispose() {
    this.stop("idle");
  }

  private startMeter() {
    if (!this.analyser) return;
    const samples = new Uint8Array(this.analyser.fftSize);
    const tick = () => {
      if (!this.analyser || this.state.status !== "listening") return;
      this.analyser.getByteTimeDomainData(samples);
      const level = Math.min(1, Number(rmsFromByteTimeDomain(samples).toFixed(3)));
      this.updateState({ level });

      const now = performance.now();
      if (level >= this.options.startThreshold) {
        this.voiceStartedAtMs ??= now;
        if (now - this.voiceStartedAtMs >= this.options.minVoiceMs) {
          const activeStream = this.mediaStream;
          this.releaseResources({ keepStream: true });
          this.updateState({ status: "triggered", level });
          if (activeStream) {
            this.callbacks.onVoiceStart?.(activeStream);
          }
          return;
        }
      } else {
        this.voiceStartedAtMs = null;
      }

      this.frameId = window.requestAnimationFrame(tick);
    };
    this.frameId = window.requestAnimationFrame(tick);
  }

  private releaseResources(options: { keepStream?: boolean } = {}) {
    if (this.frameId !== null) {
      window.cancelAnimationFrame(this.frameId);
      this.frameId = null;
    }
    if (!options.keepStream) {
      this.mediaStream?.getTracks().forEach((track) => track.stop());
    }
    this.mediaStream = null;
    if (this.audioContext && this.audioContext.state !== "closed") {
      void this.audioContext.close();
    }
    this.audioContext = null;
    this.analyser = null;
    this.voiceStartedAtMs = null;
  }

  private updateState(patch: Partial<VoiceActivityDetectorState>) {
    this.state = { ...this.state, ...patch };
    this.callbacks.onStateChange?.(this.state);
  }
}
