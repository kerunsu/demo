import {
  aggregateTurnAudioFeatures,
  computeZeroCrossingRate,
  rmsFromByteTimeDomain,
  type AudioFrameMetric,
  type BrowserTurnAudioFeatures
} from "child-education-training-demo/shared/browser-audio-features";

export type BrowserAudioCaptureStatus =
  | "idle"
  | "requesting_permission"
  | "recording"
  | "stopping"
  | "stopped"
  | "cancelled"
  | "permission_denied"
  | "no_device"
  | "device_lost"
  | "unsupported"
  | "error";

export interface BrowserAudioDevice {
  deviceId: string;
  label: string;
  groupId?: string;
  kind: "audioinput";
}

export interface BrowserAudioFormat {
  mimeType: string;
  sampleRateHz?: number;
  channels?: number;
  chunkDurationMs: number;
}

export interface BrowserAudioChunk {
  streamId: string;
  sequence: number;
  capturedAt: string;
  durationMs: number;
  format: BrowserAudioFormat;
  blob: Blob;
}

export interface BrowserAudioCaptureState {
  status: BrowserAudioCaptureStatus;
  streamId?: string;
  selectedDeviceId?: string;
  deviceLabel?: string;
  format?: BrowserAudioFormat;
  level: number;
  chunkCount: number;
  startedAt?: string;
  stoppedAt?: string;
  stopReason?: "manual_stop" | "timeout" | "cancelled" | "device_lost" | "error";
  turnFeatures?: BrowserTurnAudioFeatures;
  errorCode?: string;
  errorMessage?: string;
}

export interface BrowserAudioCaptureOptions {
  deviceId?: string;
  streamId?: string;
  chunkDurationMs?: number;
  mimeType?: string;
  maxTurnDurationMs?: number;
  mediaStream?: MediaStream;
}

export interface BrowserAudioCaptureCallbacks {
  onStateChange?: (state: BrowserAudioCaptureState) => void;
  onChunk?: (chunk: BrowserAudioChunk) => void;
  onDeviceChange?: (devices: BrowserAudioDevice[]) => void;
}

type BrowserMediaDevices = Pick<MediaDevices, "enumerateDevices" | "getUserMedia" | "addEventListener" | "removeEventListener">;

const DEFAULT_CHUNK_DURATION_MS = 250;
const DEFAULT_MAX_TURN_DURATION_MS = 10000;
const WAV_SAMPLE_RATE_HZ = 16000;

function createStreamId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `stream-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function isPermissionDenied(error: unknown) {
  return error instanceof DOMException && (error.name === "NotAllowedError" || error.name === "SecurityError");
}

function isNoDevice(error: unknown) {
  return error instanceof DOMException && (error.name === "NotFoundError" || error.name === "DevicesNotFoundError");
}

function pickMimeType(preferred?: string) {
  if (preferred?.toLowerCase().includes("wav")) {
    return "audio/wav";
  }
  const candidates = [
    preferred,
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/wav"
  ].filter(Boolean) as string[];

  if (typeof MediaRecorder === "undefined") return "";
  return candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate)) ?? "";
}

function concatenateFloat32(chunks: Float32Array[]) {
  const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const output = new Float32Array(totalLength);
  let offset = 0;
  for (const chunk of chunks) {
    output.set(chunk, offset);
    offset += chunk.length;
  }
  return output;
}

function downsampleBuffer(input: Float32Array, inputSampleRate: number, outputSampleRate: number) {
  if (inputSampleRate === outputSampleRate) return input;
  if (inputSampleRate < outputSampleRate) return input;

  const ratio = inputSampleRate / outputSampleRate;
  const outputLength = Math.max(1, Math.round(input.length / ratio));
  const output = new Float32Array(outputLength);
  let inputOffset = 0;
  for (let i = 0; i < outputLength; i += 1) {
    const nextOffset = Math.round((i + 1) * ratio);
    let sum = 0;
    let count = 0;
    for (let j = inputOffset; j < nextOffset && j < input.length; j += 1) {
      sum += input[j];
      count += 1;
    }
    output[i] = count > 0 ? sum / count : 0;
    inputOffset = nextOffset;
  }
  return output;
}

function encodePcm16Wav(samples: Float32Array, sampleRateHz: number) {
  const bytesPerSample = 2;
  const wavHeaderBytes = 44;
  const buffer = new ArrayBuffer(wavHeaderBytes + samples.length * bytesPerSample);
  const view = new DataView(buffer);

  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + samples.length * bytesPerSample, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRateHz, true);
  view.setUint32(28, sampleRateHz * bytesPerSample, true);
  view.setUint16(32, bytesPerSample, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, samples.length * bytesPerSample, true);

  let offset = wavHeaderBytes;
  for (const sample of samples) {
    const clamped = Math.max(-1, Math.min(1, sample));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
    offset += bytesPerSample;
  }

  return new Blob([buffer], { type: "audio/wav" });
}

function writeAscii(view: DataView, offset: number, value: string) {
  for (let i = 0; i < value.length; i += 1) {
    view.setUint8(offset + i, value.charCodeAt(i));
  }
}

function toAudioDevices(devices: MediaDeviceInfo[]): BrowserAudioDevice[] {
  return devices
    .filter((device) => device.kind === "audioinput")
    .map((device, index) => ({
      deviceId: device.deviceId,
      label: device.label || `Microphone ${index + 1}`,
      groupId: device.groupId || undefined,
      kind: "audioinput"
    }));
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

async function openAudioStream(mediaDevices: BrowserMediaDevices, deviceId?: string) {
  const attempts: MediaStreamConstraints[] = [
    { audio: buildAudioConstraints(deviceId) },
    { audio: deviceId ? { deviceId: { exact: deviceId } } : true }
  ];

  if (!deviceId && mediaDevices.enumerateDevices) {
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

export class BrowserAudioCaptureController {
  private mediaDevices: BrowserMediaDevices | null;
  private callbacks: BrowserAudioCaptureCallbacks;
  private mediaRecorder: MediaRecorder | null = null;
  private mediaStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private wavProcessor: ScriptProcessorNode | null = null;
  private wavSilenceGain: GainNode | null = null;
  private wavSamples: Float32Array[] = [];
  private levelFrameId: number | null = null;
  private turnFrameMetrics: AudioFrameMetric[] = [];
  private recordingStartedAtMs: number | null = null;
  private maxTurnTimeoutId: number | null = null;
  private sequence = 0;
  private state: BrowserAudioCaptureState = { status: "idle", level: 0, chunkCount: 0 };
  private readonly deviceChangeHandler = () => {
    void this.refreshDevices();
  };

  constructor(
    callbacks: BrowserAudioCaptureCallbacks = {},
    mediaDevices: BrowserMediaDevices | null = typeof navigator === "undefined" ? null : navigator.mediaDevices ?? null
  ) {
    this.callbacks = callbacks;
    this.mediaDevices = mediaDevices;
    this.mediaDevices?.addEventListener?.("devicechange", this.deviceChangeHandler);
  }

  getState() {
    return this.state;
  }

  dispose() {
    this.cancel("controller_disposed");
    this.mediaDevices?.removeEventListener?.("devicechange", this.deviceChangeHandler);
  }

  async refreshDevices() {
    if (!this.mediaDevices?.enumerateDevices) {
      this.updateState({ status: "unsupported", errorCode: "MEDIA_DEVICES_UNSUPPORTED" });
      this.callbacks.onDeviceChange?.([]);
      return [];
    }

    const devices = toAudioDevices(await this.mediaDevices.enumerateDevices());
    this.callbacks.onDeviceChange?.(devices);

    if (this.state.status === "recording" && this.state.selectedDeviceId) {
      const selectedStillExists = devices.some((device) => device.deviceId === this.state.selectedDeviceId);
      if (!selectedStillExists) {
        this.cancel("device_lost");
        this.updateState({ status: "device_lost", errorCode: "DEVICE_LOST", errorMessage: "Selected microphone disconnected." });
      }
    }

    return devices;
  }

  async start(options: BrowserAudioCaptureOptions = {}) {
    if (!this.mediaDevices?.getUserMedia) {
      this.updateState({ status: "unsupported", errorCode: "AUDIO_CAPTURE_UNSUPPORTED" });
      return this.state;
    }
    const prefersWav = options.mimeType?.toLowerCase().includes("wav") ?? false;
    if (!prefersWav && typeof MediaRecorder === "undefined") {
      this.updateState({ status: "unsupported", errorCode: "AUDIO_CAPTURE_UNSUPPORTED" });
      return this.state;
    }

    await this.stop();
    this.updateState({ status: "requesting_permission", errorCode: undefined, errorMessage: undefined, chunkCount: 0, level: 0 });

    try {
      const stream =
        options.mediaStream ??
        (await openAudioStream(this.mediaDevices, options.deviceId));
      this.mediaStream = stream;
      const mimeType = pickMimeType(options.mimeType);
      const recorder = prefersWav ? null : new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const audioContext = new AudioContext();
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 512;
      const source = audioContext.createMediaStreamSource(stream);
      source.connect(analyser);

      const streamId = options.streamId ?? createStreamId();
      const chunkDurationMs = options.chunkDurationMs ?? DEFAULT_CHUNK_DURATION_MS;
      const audioTrack = stream.getAudioTracks()[0];
      const settings = audioTrack?.getSettings();
      const format: BrowserAudioFormat = {
        mimeType: prefersWav ? "audio/wav" : recorder?.mimeType || mimeType || "audio/webm",
        sampleRateHz: prefersWav ? WAV_SAMPLE_RATE_HZ : audioContext.sampleRate,
        channels: settings?.channelCount ?? 1,
        chunkDurationMs
      };

      audioTrack?.addEventListener("ended", () => {
        this.cancel("device_lost");
        this.updateState({ status: "device_lost", errorCode: "DEVICE_LOST", errorMessage: "Microphone stream ended." });
      });

      if (recorder) {
        recorder.ondataavailable = (event) => {
          if (!event.data.size || (this.state.status !== "recording" && this.state.status !== "stopping")) return;
          const sequence = this.sequence;
          this.sequence += 1;
          this.updateState({ chunkCount: this.state.chunkCount + 1 });
          this.callbacks.onChunk?.({
            streamId,
            sequence,
            capturedAt: new Date().toISOString(),
            durationMs: chunkDurationMs,
            format,
            blob: event.data
          });
        };

        recorder.onerror = (event) => {
          const error = event instanceof ErrorEvent ? event.error : undefined;
          this.cancel("recorder_error");
          this.updateState({
            status: "error",
            errorCode: "RECORDER_ERROR",
            errorMessage: error instanceof Error ? error.message : "MediaRecorder failed."
          });
        };
      } else {
        const processor = audioContext.createScriptProcessor(4096, 1, 1);
        const silenceGain = audioContext.createGain();
        silenceGain.gain.value = 0;
        processor.onaudioprocess = (event) => {
          if (this.state.status !== "recording" && this.state.status !== "stopping") return;
          this.wavSamples.push(new Float32Array(event.inputBuffer.getChannelData(0)));
        };
        source.connect(processor);
        processor.connect(silenceGain);
        silenceGain.connect(audioContext.destination);
        this.wavProcessor = processor;
        this.wavSilenceGain = silenceGain;
      }

      this.mediaRecorder = recorder;
      this.audioContext = audioContext;
      this.analyser = analyser;
      this.sequence = 0;
      this.wavSamples = [];
      this.turnFrameMetrics = [];
      this.recordingStartedAtMs = performance.now();
      recorder?.start(chunkDurationMs);
      this.updateState({
        status: "recording",
        streamId,
        selectedDeviceId: settings?.deviceId ?? options.deviceId,
        deviceLabel: audioTrack?.label,
        format,
        startedAt: new Date().toISOString(),
        stoppedAt: undefined,
        chunkCount: 0,
        level: 0
      });
      this.startLevelMeter();
      this.maxTurnTimeoutId = window.setTimeout(() => {
        void this.stop("timeout");
      }, options.maxTurnDurationMs ?? DEFAULT_MAX_TURN_DURATION_MS);
    } catch (error) {
      if (isPermissionDenied(error)) {
        this.updateState({ status: "permission_denied", errorCode: "MIC_PERMISSION_DENIED" });
      } else if (isNoDevice(error)) {
        this.updateState({ status: "no_device", errorCode: "NO_MICROPHONE" });
      } else {
        this.updateState({
          status: "error",
          errorCode: "MIC_CAPTURE_FAILED",
          errorMessage: error instanceof Error ? error.message : "Unable to start microphone capture."
        });
      }
      this.releaseResources();
    }

    return this.state;
  }

  async stop(reason: BrowserAudioCaptureState["stopReason"] = "manual_stop") {
    if (this.state.status !== "recording" && this.state.status !== "requesting_permission") {
      return this.state;
    }

    this.updateState({ status: "stopping", stopReason: reason });
    const recorder = this.mediaRecorder;
    if (recorder && recorder.state !== "inactive") {
      await new Promise<void>((resolve) => {
        const handleData = (event: BlobEvent) => {
          if (!event.data.size || (this.state.status !== "recording" && this.state.status !== "stopping")) return;
          const streamId = this.state.streamId;
          const format = this.state.format;
          if (!streamId || !format) return;
          const sequence = this.sequence;
          this.sequence += 1;
          this.updateState({ chunkCount: this.state.chunkCount + 1 });
          this.callbacks.onChunk?.({
            streamId,
            sequence,
            capturedAt: new Date().toISOString(),
            durationMs: format.chunkDurationMs,
            format,
            blob: event.data
          });
        };
        const handleStop = () => {
          recorder.removeEventListener("dataavailable", handleData);
          resolve();
        };
        recorder.addEventListener("dataavailable", handleData);
        recorder.addEventListener("stop", handleStop, { once: true });
        recorder.requestData();
        recorder.stop();
      });
    } else if (this.wavProcessor && this.audioContext && this.state.streamId && this.state.format && this.wavSamples.length > 0) {
      const samples = downsampleBuffer(concatenateFloat32(this.wavSamples), this.audioContext.sampleRate, WAV_SAMPLE_RATE_HZ);
      const blob = encodePcm16Wav(samples, WAV_SAMPLE_RATE_HZ);
      const durationMs =
        this.recordingStartedAtMs !== null ? Math.max(0, Math.round(performance.now() - this.recordingStartedAtMs)) : this.state.format.chunkDurationMs;
      const sequence = this.sequence;
      this.sequence += 1;
      this.updateState({ chunkCount: this.state.chunkCount + 1 });
      this.callbacks.onChunk?.({
        streamId: this.state.streamId,
        sequence,
        capturedAt: new Date().toISOString(),
        durationMs,
        format: this.state.format,
        blob
      });
    }
    const turnFeatures = this.computeTurnFeatures();
    this.releaseResources();
    this.updateState({
      status: "stopped",
      stoppedAt: new Date().toISOString(),
      level: 0,
      stopReason: reason,
      turnFeatures
    });
    return this.state;
  }

  cancel(reason = "cancelled") {
    if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
      void this.stop(reason === "cancelled" ? "cancelled" : "error");
      return this.state;
    }
    this.releaseResources();
    this.updateState({
      status: "cancelled",
      stoppedAt: new Date().toISOString(),
      level: 0,
      stopReason: "cancelled",
      errorCode: reason === "cancelled" ? undefined : reason.toUpperCase()
    });
    return this.state;
  }

  private startLevelMeter() {
    if (!this.analyser) return;
    const samples = new Uint8Array(this.analyser.fftSize);
    const tick = () => {
      if (!this.analyser || this.state.status !== "recording") return;
      this.analyser.getByteTimeDomainData(samples);
      const rms = rmsFromByteTimeDomain(samples);
      const zcr = computeZeroCrossingRate(samples);
      this.turnFrameMetrics.push({ rms, zcr });
      this.updateState({ level: Math.min(1, Number(rms.toFixed(3))) });
      this.levelFrameId = window.requestAnimationFrame(tick);
    };
    this.levelFrameId = window.requestAnimationFrame(tick);
  }

  private releaseResources() {
    if (this.levelFrameId !== null) {
      window.cancelAnimationFrame(this.levelFrameId);
      this.levelFrameId = null;
    }
    if (this.maxTurnTimeoutId !== null) {
      window.clearTimeout(this.maxTurnTimeoutId);
      this.maxTurnTimeoutId = null;
    }
    this.mediaStream?.getTracks().forEach((track) => track.stop());
    this.mediaStream = null;
    this.mediaRecorder = null;
    if (this.wavProcessor) {
      this.wavProcessor.onaudioprocess = null;
      this.wavProcessor.disconnect();
    }
    this.wavProcessor = null;
    this.wavSilenceGain?.disconnect();
    this.wavSilenceGain = null;
    this.wavSamples = [];
    if (this.audioContext && this.audioContext.state !== "closed") {
      void this.audioContext.close();
    }
    this.audioContext = null;
    this.analyser = null;
    this.turnFrameMetrics = [];
    this.recordingStartedAtMs = null;
  }

  private computeTurnFeatures(): BrowserTurnAudioFeatures | undefined {
    if (this.turnFrameMetrics.length === 0) return undefined;
    const audioDurationMs =
      this.recordingStartedAtMs !== null ? Math.max(0, Math.round(performance.now() - this.recordingStartedAtMs)) : 0;
    return aggregateTurnAudioFeatures(this.turnFrameMetrics, audioDurationMs);
  }

  private updateState(patch: Partial<BrowserAudioCaptureState>) {
    this.state = { ...this.state, ...patch };
    this.callbacks.onStateChange?.(this.state);
  }
}
