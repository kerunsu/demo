import type { CameraDeviceState, CameraFrameSampleDescriptor } from "child-education-training-demo/shared/behavior-frames";
import { BEHAVIOR_FRAME_SCHEMA_VERSION } from "child-education-training-demo/shared/behavior-frames";
import {
  MONITOR_PREVIEW_SCHEMA_VERSION,
  resolveDominantEmotion,
  type MonitorPreviewFrameMeta
} from "child-education-training-demo/shared/monitor-preview";
import {
  ATTENTION_ALGORITHM_V2,
  estimateImageQuality as estimateFrameImageQuality,
  scoreAttentionFromFaceGeometry,
  type AttentionImageQuality,
  type AttentionVisualFeatures
} from "child-education-training-demo/shared/attention-scoring";
import { detectFacesWithMediaPipe, disposeMediaPipeFaceDetector } from "./mediapipeFaceDetector";
import { detectEmotionFeaturesWithMediaPipe, disposeMediaPipeFaceLandmarker } from "./mediapipeFaceLandmarker";

export type BrowserCameraStatus =
  | "idle"
  | "requesting_permission"
  | "sampling"
  | "stopped"
  | "permission_denied"
  | "no_device"
  | "unsupported"
  | "error";

export interface BrowserCameraDevice {
  deviceId: string;
  label: string;
  groupId?: string;
  kind: "videoinput";
}

export interface BrowserCameraCaptureState extends CameraDeviceState {
  status: BrowserCameraStatus;
  streamId?: string;
  frameCount: number;
  startedAt?: string;
  stoppedAt?: string;
}

export interface BrowserCameraCaptureOptions {
  sessionId: string;
  correlationId: string;
  questionId?: string;
  deviceId?: string;
  width?: number;
  height?: number;
  sampleFps?: number;
  /** Frame rate for MediaRecorder; decoupled from low-fps attention sampling. */
  recordingFps?: number;
  mimeType?: "image/jpeg" | "image/webp";
  quality?: number;
  rawVideoPersistence?: {
    enabled: boolean;
    onStreamReady: (input: RawVideoStreamEvent) => void | Promise<void>;
    onSegment: (input: RawVideoSegmentEvent) => void | Promise<void>;
    onThumbnail: (input: RawVideoThumbnailEvent) => void | Promise<void>;
    onStreamFinish: (input: RawVideoStreamFinishEvent) => void | Promise<void>;
  };
  monitorPreview?: {
    enabled: boolean;
    width?: number;
    height?: number;
    fps?: number;
    quality?: number;
    onPreviewFrame?: (input: BrowserMonitorPreviewFrame) => void | Promise<void>;
  };
}

export interface BrowserMonitorPreviewFrame {
  blob: Blob;
  mimeType: "image/jpeg" | "image/webp";
  meta: MonitorPreviewFrameMeta;
}

export interface RawVideoStreamContext {
  sessionId: string;
  questionId?: string;
  correlationId: string;
}

export interface RawVideoStreamEvent extends RawVideoStreamContext {
  streamId: string;
  mimeType: string;
}

export interface RawVideoSegmentEvent extends RawVideoStreamContext {
  streamId: string;
  sequence: number;
  blob: Blob;
  mimeType: string;
  durationMs: number;
  capturedAt: string;
}

export interface RawVideoThumbnailEvent extends RawVideoStreamContext {
  streamId: string;
  blob: Blob;
  mimeType: string;
}

export interface RawVideoStreamFinishEvent extends RawVideoStreamContext {
  streamId: string;
  reason: string;
}

export interface BrowserCameraCaptureCallbacks {
  onStateChange?: (state: BrowserCameraCaptureState) => void;
  onFrame?: (descriptor: CameraFrameSampleDescriptor) => void;
  onDeviceChange?: (devices: BrowserCameraDevice[]) => void;
}

type BrowserMediaDevices = Pick<MediaDevices, "enumerateDevices" | "getUserMedia" | "addEventListener" | "removeEventListener">;
type BrowserFaceDetector = {
  detect: (source: CanvasImageSource) => Promise<Array<{ boundingBox?: DOMRectReadOnly }>>;
};
type BrowserFaceDetectorConstructor = new (options?: { fastMode?: boolean; maxDetectedFaces?: number }) => BrowserFaceDetector;

const DEFAULT_WIDTH = 160;
const DEFAULT_HEIGHT = 120;
const DEFAULT_SAMPLE_FPS = 1;
const DEFAULT_RECORDING_FPS = 15;
const DEFAULT_PREVIEW_WIDTH = 320;
const DEFAULT_PREVIEW_HEIGHT = 240;
const DEFAULT_PREVIEW_FPS = 4;
const VIDEO_SEGMENT_MS = 1000; // upload chunk size; each question opens its own camera-stream / merged.webm
/** Wait before finishing a per-question stream so MediaRecorder can emit at least one chunk. */
const MIN_RECORDING_MS_BEFORE_SWITCH = 1200;

function createId(prefix: string) {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function toCameraDevices(devices: MediaDeviceInfo[]): BrowserCameraDevice[] {
  return devices
    .filter((device) => device.kind === "videoinput")
    .map((device, index) => ({
      deviceId: device.deviceId,
      label: device.label || `Camera ${index + 1}`,
      groupId: device.groupId || undefined,
      kind: "videoinput"
    }));
}

function isPermissionDenied(error: unknown) {
  return error instanceof DOMException && (error.name === "NotAllowedError" || error.name === "SecurityError");
}

function isNoDevice(error: unknown) {
  return error instanceof DOMException && (error.name === "NotFoundError" || error.name === "DevicesNotFoundError");
}

async function hashBlob(blob: Blob) {
  const buffer = await blob.arrayBuffer();
  if (typeof crypto !== "undefined" && crypto.subtle) {
    const digest = await crypto.subtle.digest("SHA-256", buffer);
    return Array.from(new Uint8Array(digest))
      .slice(0, 8)
      .map((value) => value.toString(16).padStart(2, "0"))
      .join("");
  }
  return `bytes-${buffer.byteLength}`;
}

function getFaceDetectorConstructor() {
  return (window as unknown as { FaceDetector?: BrowserFaceDetectorConstructor }).FaceDetector;
}

type FaceBox = { x: number; y: number; width: number; height: number };

function clamp01(value: number) {
  return Math.min(1, Math.max(0, value));
}

function normalizeFaceBox(box: FaceBox, frameWidth: number, frameHeight: number) {
  if (frameWidth <= 0 || frameHeight <= 0) return undefined;
  return {
    x: clamp01(box.x / frameWidth),
    y: clamp01(box.y / frameHeight),
    width: clamp01(box.width / frameWidth),
    height: clamp01(box.height / frameHeight)
  };
}

function toDescriptorVisualFeatures(
  features: AttentionVisualFeatures,
  faceBox?: FaceBox,
  frameWidth?: number,
  frameHeight?: number
) {
  return {
    facePresent: features.facePresent,
    faceCount: features.faceCount,
    headOrientation: features.headOrientation,
    roughlyFacingScreen: features.roughlyFacingScreen,
    facingScore: features.facingScore,
    centerOffsetX: features.centerOffsetX,
    centerOffsetY: features.centerOffsetY,
    faceAreaRatio: features.faceAreaRatio,
    faceBox: faceBox && frameWidth && frameHeight ? normalizeFaceBox(faceBox, frameWidth, frameHeight) : undefined,
    imageQuality: features.imageQuality,
    provider: features.provider,
    algorithmVersion: features.algorithmVersion,
    confidence: features.confidence
  };
}

function pickPrimaryFace(faces: FaceBox[]) {
  return [...faces].sort((left, right) => right.width * right.height - left.width * left.height)[0];
}

function scoreDetectedFaces(
  faces: FaceBox[],
  width: number,
  height: number,
  imageQuality: AttentionImageQuality,
  provider: AttentionVisualFeatures["provider"]
) {
  const primaryFace = pickPrimaryFace(faces);
  if (!primaryFace) {
    return toDescriptorVisualFeatures({
      facePresent: false,
      faceCount: 0,
      headOrientation: "unknown",
      roughlyFacingScreen: undefined,
      facingScore: 0,
      imageQuality,
      provider,
      algorithmVersion: ATTENTION_ALGORITHM_V2,
      confidence: imageQuality === "good" ? 0.3 : 0.18
    });
  }

  const scored = scoreAttentionFromFaceGeometry({
    frameWidth: width,
    frameHeight: height,
    faceCount: faces.length,
    primaryFace,
    imageQuality
  });
  return toDescriptorVisualFeatures({ ...scored, provider }, primaryFace, width, height);
}

async function detectWithNativeFaceDetector(canvas: HTMLCanvasElement): Promise<FaceBox[] | null> {
  const FaceDetectorCtor = getFaceDetectorConstructor();
  if (!FaceDetectorCtor) return null;

  try {
    const detector = new FaceDetectorCtor({ fastMode: true, maxDetectedFaces: 4 });
    const faces = await detector.detect(canvas);
    return faces
      .map((face) => face.boundingBox)
      .filter((box): box is DOMRectReadOnly => Boolean(box))
      .map((box) => ({ x: box.x, y: box.y, width: box.width, height: box.height }));
  } catch {
    return null;
  }
}

function noDetectorFallback(imageQuality: AttentionImageQuality) {
  return toDescriptorVisualFeatures({
    facePresent: false,
    faceCount: 0,
    headOrientation: "unknown",
    roughlyFacingScreen: undefined,
    facingScore: 0,
    imageQuality,
    provider: "browser-frame-quality",
    algorithmVersion: ATTENTION_ALGORITHM_V2,
    confidence: imageQuality === "good" ? 0.35 : 0.2
  });
}

async function extractVisualFeatures(canvas: HTMLCanvasElement, blob: Blob, width: number, height: number) {
  const imageQuality = estimateFrameImageQuality(blob.size, width, height);

  const nativeFaces = await detectWithNativeFaceDetector(canvas);
  if (nativeFaces !== null) {
    return scoreDetectedFaces(nativeFaces, width, height, imageQuality, "browser-face-detector");
  }

  const mediapipeFaces = await detectFacesWithMediaPipe(canvas);
  if (mediapipeFaces !== null) {
    return scoreDetectedFaces(mediapipeFaces, width, height, imageQuality, "browser-mediapipe-face");
  }

  return noDetectorFallback(imageQuality);
}

function pickVideoMimeType() {
  const candidates = ["video/webm;codecs=vp8", "video/webm", "video/mp4"];
  if (typeof MediaRecorder === "undefined") return "";
  return candidates.find((item) => MediaRecorder.isTypeSupported(item)) ?? "";
}

class BrowserCameraVideoRecorder {
  private recorder: MediaRecorder | null = null;
  private sequence = 0;
  private mimeType = "video/webm";
  private segmentHandler:
    | ((input: { sequence: number; blob: Blob; mimeType: string; durationMs: number; capturedAt: string }) => void | Promise<void>)
    | null = null;
  private pendingUploads: Promise<void>[] = [];

  start(
    stream: MediaStream,
    onSegment: (input: { sequence: number; blob: Blob; mimeType: string; durationMs: number; capturedAt: string }) => void | Promise<void>
  ) {
    if (typeof MediaRecorder === "undefined") return;
    this.sequence = 0;
    this.mimeType = pickVideoMimeType();
    this.segmentHandler = onSegment;
    this.pendingUploads = [];
    this.recorder = new MediaRecorder(stream, this.mimeType ? { mimeType: this.mimeType } : undefined);
    this.recorder.ondataavailable = (event) => {
      if (event.data.size === 0) return;
      void this.emitSegment(event.data, VIDEO_SEGMENT_MS);
    };
    this.recorder.start(VIDEO_SEGMENT_MS);
  }

  private trackUpload(promise: Promise<void>) {
    const tracked = promise.catch(() => undefined);
    this.pendingUploads.push(tracked);
    void tracked.finally(() => {
      const index = this.pendingUploads.indexOf(tracked);
      if (index >= 0) this.pendingUploads.splice(index, 1);
    });
    return tracked;
  }

  private emitSegment(blob: Blob, durationMs: number) {
    if (!this.segmentHandler) return;
    const capturedAt = new Date().toISOString();
    const handler = this.segmentHandler;
    void this.trackUpload(
      Promise.resolve(
        handler({
          sequence: this.sequence,
          blob,
          mimeType: this.mimeType || blob.type || "video/webm",
          durationMs,
          capturedAt
        })
      )
    );
    this.sequence += 1;
  }

  async stopAndFlush() {
    const recorder = this.recorder;
    const handler = this.segmentHandler;
    const mimeType = this.mimeType;
    const sequenceAtStop = this.sequence;
    this.recorder = null;
    this.segmentHandler = null;
    if (!recorder || recorder.state === "inactive") {
      await Promise.all(this.pendingUploads);
      this.pendingUploads = [];
      return;
    }

    let flushSequence = sequenceAtStop;
    await new Promise<void>((resolve) => {
      const handleData = (event: BlobEvent) => {
        if (event.data.size === 0 || !handler) return;
        const capturedAt = new Date().toISOString();
        const sequence = flushSequence;
        flushSequence += 1;
        void this.trackUpload(
          Promise.resolve(
            handler({
              sequence,
              blob: event.data,
              mimeType: mimeType || event.data.type || "video/webm",
              durationMs: 0,
              capturedAt
            })
          )
        );
      };
      const handleStop = () => {
        recorder.removeEventListener("dataavailable", handleData);
        resolve();
      };
      recorder.addEventListener("dataavailable", handleData);
      recorder.addEventListener("stop", handleStop, { once: true });
      if (recorder.state === "recording") {
        recorder.requestData();
        recorder.stop();
        return;
      }
      handleStop();
    });

    await Promise.all(this.pendingUploads);
    this.pendingUploads = [];
  }

  getMimeType() {
    return this.mimeType;
  }
}

export class BrowserCameraCaptureController {
  private mediaDevices: BrowserMediaDevices | null;
  private callbacks: BrowserCameraCaptureCallbacks;
  private mediaStream: MediaStream | null = null;
  private video: HTMLVideoElement | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private sampleTimerId: number | null = null;
  private previewTimerId: number | null = null;
  private previewSequence = 0;
  private sequence = 0;
  private videoRecorder = new BrowserCameraVideoRecorder();
  private activeStreamId: string | null = null;
  private activeCaptureOptions: BrowserCameraCaptureOptions | null = null;
  private previewCanvas: HTMLCanvasElement | null = null;
  private lastAnalysisContext: {
    visualFeatures?: NonNullable<CameraFrameSampleDescriptor["visualFeatures"]>;
    emotionFeatures?: NonNullable<CameraFrameSampleDescriptor["emotionFeatures"]>;
  } = {};
  private stopPromise: Promise<void> | null = null;
  private switchQuestionPromise: Promise<BrowserCameraCaptureState> | null = null;
  private recordingStartedAt = 0;
  private state: BrowserCameraCaptureState = {
    status: "idle",
    permission: "unknown",
    deviceAvailable: false,
    maxFps: DEFAULT_SAMPLE_FPS,
    stopped: true,
    frameCount: 0
  };

  private readonly deviceChangeHandler = () => {
    void this.refreshDevices();
  };

  constructor(
    callbacks: BrowserCameraCaptureCallbacks = {},
    mediaDevices: BrowserMediaDevices | null = typeof navigator === "undefined" ? null : navigator.mediaDevices ?? null
  ) {
    this.callbacks = callbacks;
    this.mediaDevices = mediaDevices;
    this.mediaDevices?.addEventListener?.("devicechange", this.deviceChangeHandler);
  }

  getState() {
    return this.state;
  }

  private streamContext(): RawVideoStreamContext | null {
    if (!this.activeCaptureOptions) return null;
    return {
      sessionId: this.activeCaptureOptions.sessionId,
      questionId: this.activeCaptureOptions.questionId,
      correlationId: this.activeCaptureOptions.correlationId
    };
  }

  private markRecordingStarted() {
    this.recordingStartedAt = Date.now();
  }

  private async ensureMinimumRecordingBeforeSwitch() {
    if (!this.recordingStartedAt) return;
    const elapsed = Date.now() - this.recordingStartedAt;
    if (elapsed >= MIN_RECORDING_MS_BEFORE_SWITCH) return;
    await new Promise<void>((resolve) => {
      window.setTimeout(resolve, MIN_RECORDING_MS_BEFORE_SWITCH - elapsed);
    });
  }

  /** Keep the camera open; finish the current per-question video and open a new stream. */
  async switchQuestion(patch: Pick<BrowserCameraCaptureOptions, "questionId" | "correlationId">) {
    if (this.switchQuestionPromise) {
      await this.switchQuestionPromise;
    }
    const run = this.switchQuestionInternal(patch);
    this.switchQuestionPromise = run;
    try {
      return await run;
    } finally {
      if (this.switchQuestionPromise === run) {
        this.switchQuestionPromise = null;
      }
    }
  }

  private async switchQuestionInternal(patch: Pick<BrowserCameraCaptureOptions, "questionId" | "correlationId">) {
    if (this.state.status !== "sampling" || !this.mediaStream || !this.activeCaptureOptions) {
      return this.state;
    }
    if (
      this.activeCaptureOptions.questionId === patch.questionId &&
      this.activeCaptureOptions.correlationId === patch.correlationId
    ) {
      return this.state;
    }

    const persistence = this.activeCaptureOptions.rawVideoPersistence;
    const previousContext = this.streamContext();
    if (persistence?.enabled && this.activeStreamId && previousContext) {
      const previousStreamId = this.activeStreamId;
      await this.ensureMinimumRecordingBeforeSwitch();
      await this.videoRecorder.stopAndFlush();
      await persistence.onStreamFinish({
        streamId: previousStreamId,
        reason: "question_end",
        ...previousContext
      });

      const newStreamId = createId("camera-stream");
      const mimeType = pickVideoMimeType() || "video/webm";
      this.activeStreamId = newStreamId;
      this.sequence = 0;
      this.activeCaptureOptions = {
        ...this.activeCaptureOptions,
        questionId: patch.questionId,
        correlationId: patch.correlationId
      };
      const nextContext = this.streamContext()!;
      await persistence.onStreamReady({ streamId: newStreamId, mimeType, ...nextContext });
      this.videoRecorder.start(this.mediaStream, (segment) => {
        void persistence.onSegment({
          streamId: newStreamId,
          ...segment,
          ...this.streamContext()!
        });
      });
      this.markRecordingStarted();
      this.updateState({ streamId: newStreamId, frameCount: 0 });
      return this.state;
    }

    this.activeCaptureOptions = {
      ...this.activeCaptureOptions,
      questionId: patch.questionId,
      correlationId: patch.correlationId
    };
    return this.state;
  }

  dispose() {
    this.stop();
    disposeMediaPipeFaceDetector();
    disposeMediaPipeFaceLandmarker();
    this.mediaDevices?.removeEventListener?.("devicechange", this.deviceChangeHandler);
  }

  async refreshDevices() {
    if (!this.mediaDevices?.enumerateDevices) {
      this.updateState({ status: "unsupported", permission: "unsupported", deviceAvailable: false, errorCode: "CAMERA_UNSUPPORTED" });
      this.callbacks.onDeviceChange?.([]);
      return [];
    }

    const devices = toCameraDevices(await this.mediaDevices.enumerateDevices());
    this.callbacks.onDeviceChange?.(devices);
    this.updateState({ deviceAvailable: devices.length > 0 });
    return devices;
  }

  async start(options: BrowserCameraCaptureOptions) {
    await this.stopInternal();
    if (!this.mediaDevices?.getUserMedia || typeof document === "undefined") {
      this.updateState({ status: "unsupported", permission: "unsupported", errorCode: "CAMERA_UNSUPPORTED" });
      return this.state;
    }

    this.updateState({ status: "requesting_permission", permission: "prompt", errorCode: undefined, frameCount: 0 });

    try {
      const width = options.width ?? DEFAULT_WIDTH;
      const height = options.height ?? DEFAULT_HEIGHT;
      const sampleFps = Math.min(2, Math.max(0.2, options.sampleFps ?? DEFAULT_SAMPLE_FPS));
      const recordingFps = Math.min(30, Math.max(5, options.recordingFps ?? DEFAULT_RECORDING_FPS));
      const stream = await this.mediaDevices.getUserMedia({
        video: {
          deviceId: options.deviceId ? { exact: options.deviceId } : undefined,
          width: { ideal: width },
          height: { ideal: height },
          frameRate: { ideal: recordingFps, max: 30 }
        },
        audio: false
      });
      const video = document.createElement("video");
      video.muted = true;
      video.playsInline = true;
      video.srcObject = stream;
      await video.play();

      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const streamId = createId("camera-stream");
      const track = stream.getVideoTracks()[0];
      const settings = track?.getSettings();
      track?.addEventListener("ended", () => {
        this.stop("DEVICE_LOST");
      });

      this.mediaStream = stream;
      this.video = video;
      this.canvas = canvas;
      this.sequence = 0;
      this.activeStreamId = streamId;
      this.activeCaptureOptions = options;
      this.updateState({
        status: "sampling",
        permission: "granted",
        stopped: false,
        streamId,
        width,
        height,
        maxFps: sampleFps,
        selectedDeviceIdHash: settings?.deviceId ? `device-${settings.deviceId.slice(0, 8)}` : undefined,
        labelRedacted: track?.label ? "[camera-label-redacted]" : undefined,
        startedAt: new Date().toISOString(),
        stoppedAt: undefined
      });

      const intervalMs = Math.round(1000 / sampleFps);
      const capture = () => {
        void this.captureFrame(width, height);
      };
      capture();
      this.sampleTimerId = window.setInterval(capture, intervalMs);

      if (options.rawVideoPersistence?.enabled) {
        const mimeType = pickVideoMimeType() || "video/webm";
        const context = this.streamContext()!;
        void options.rawVideoPersistence.onStreamReady({ streamId, mimeType, ...context });
        this.videoRecorder.start(stream, (segment) => {
          void options.rawVideoPersistence?.onSegment({
            streamId,
            ...segment,
            ...this.streamContext()!
          });
        });
        this.markRecordingStarted();
      }

      const preview = options.monitorPreview;
      if (preview?.enabled && preview.onPreviewFrame) {
        const previewWidth = preview.width ?? DEFAULT_PREVIEW_WIDTH;
        const previewHeight = preview.height ?? DEFAULT_PREVIEW_HEIGHT;
        const previewFps = Math.min(10, Math.max(1, preview.fps ?? DEFAULT_PREVIEW_FPS));
        this.previewCanvas = document.createElement("canvas");
        this.previewCanvas.width = previewWidth;
        this.previewCanvas.height = previewHeight;
        this.previewSequence = 0;
        const previewIntervalMs = Math.round(1000 / previewFps);
        const capturePreview = () => {
          void this.capturePreviewFrame(previewWidth, previewHeight);
        };
        capturePreview();
        this.previewTimerId = window.setInterval(capturePreview, previewIntervalMs);
      }
    } catch (error) {
      if (isPermissionDenied(error)) {
        this.updateState({ status: "permission_denied", permission: "denied", errorCode: "CAMERA_PERMISSION_DENIED" });
      } else if (isNoDevice(error)) {
        this.updateState({ status: "no_device", deviceAvailable: false, errorCode: "NO_CAMERA" });
      } else {
        this.updateState({ status: "error", errorCode: "CAMERA_CAPTURE_FAILED" });
      }
      this.releaseResources();
    }

    return this.state;
  }

  stop(errorCode?: string) {
    void this.stopInternal(errorCode);
    return this.state;
  }

  async stopAndWait(errorCode?: string) {
    await this.stopInternal(errorCode);
    return this.state;
  }

  private async stopInternal(errorCode?: string) {
    if (this.stopPromise) {
      await this.stopPromise;
      return;
    }

    this.stopPromise = this.finalizeCapture(errorCode);
    try {
      await this.stopPromise;
    } finally {
      this.stopPromise = null;
    }
  }

  private async finalizeCapture(errorCode?: string) {
    const streamId = this.activeStreamId;
    const persistence = this.activeCaptureOptions?.rawVideoPersistence;

    if (this.sampleTimerId !== null) {
      window.clearInterval(this.sampleTimerId);
      this.sampleTimerId = null;
    }

    if (this.previewTimerId !== null) {
      window.clearInterval(this.previewTimerId);
      this.previewTimerId = null;
    }

    if (persistence?.enabled && streamId) {
      const context = this.streamContext();
      await this.videoRecorder.stopAndFlush();
      if (context) {
        await persistence.onStreamFinish({
          streamId,
          reason: errorCode ? "device_lost" : "question_end",
          ...context
        });
      }
    } else {
      await this.videoRecorder.stopAndFlush();
    }

    this.releaseResources();
    this.activeStreamId = null;
    this.activeCaptureOptions = null;
    this.updateState({ status: "stopped", stopped: true, stoppedAt: new Date().toISOString(), errorCode });
  }

  private async captureFrame(width: number, height: number) {
    const options = this.activeCaptureOptions;
    const streamId = this.activeStreamId;
    if (!options || !streamId || !this.video || !this.canvas || this.state.status !== "sampling") return;
    const context = this.canvas.getContext("2d");
    if (!context) return;
    context.drawImage(this.video, 0, 0, width, height);
    const mimeType = options.mimeType ?? "image/jpeg";
    const blob = await new Promise<Blob | null>((resolve) => {
      this.canvas?.toBlob(resolve, mimeType, options.quality ?? 0.6);
    });
    if (!blob) return;
    const sequence = this.sequence;
    if (sequence === 0 && options.rawVideoPersistence?.enabled) {
      const context = this.streamContext();
      if (context) {
        void options.rawVideoPersistence.onThumbnail({
          streamId,
          blob,
          mimeType,
          ...context
        });
      }
    }
    this.sequence += 1;
    const capturedAt = new Date().toISOString();
    const visualFeatures = await extractVisualFeatures(this.canvas, blob, width, height);
    const emotionFeatures =
      visualFeatures.facePresent ? await detectEmotionFeaturesWithMediaPipe(this.canvas, true) : undefined;
    const descriptor: CameraFrameSampleDescriptor = {
      schemaVersion: BEHAVIOR_FRAME_SCHEMA_VERSION,
      sessionId: options.sessionId,
      streamId,
      frameId: `${streamId}:frame-${sequence}`,
      sequence,
      capturedAt,
      correlationId: options.correlationId,
      questionId: options.questionId,
      width,
      height,
      downsampled: true,
      frameHash: await hashBlob(blob),
      byteLength: blob.size,
      mimeType,
      rawFramePersisted: false,
      visualFeatures,
      emotionFeatures: emotionFeatures ?? undefined
    };
    this.updateState({ frameCount: this.state.frameCount + 1 });
    this.lastAnalysisContext = { visualFeatures, emotionFeatures: emotionFeatures ?? undefined };
    this.callbacks.onFrame?.(descriptor);
  }

  private async capturePreviewFrame(width: number, height: number) {
    const options = this.activeCaptureOptions;
    const streamId = this.activeStreamId;
    const onPreviewFrame = options?.monitorPreview?.onPreviewFrame;
    if (!options?.monitorPreview?.enabled || !onPreviewFrame || !streamId || !this.video || !this.previewCanvas || this.state.status !== "sampling") {
      return;
    }

    const context = this.previewCanvas.getContext("2d");
    if (!context) return;
    context.drawImage(this.video, 0, 0, width, height);

    const mimeType = options.mimeType ?? "image/jpeg";
    const quality = options.monitorPreview.quality ?? options.quality ?? 0.6;
    const blob = await new Promise<Blob | null>((resolve) => {
      this.previewCanvas?.toBlob(resolve, mimeType, quality);
    });
    if (!blob) return;

    const sequence = this.previewSequence;
    this.previewSequence += 1;
    const capturedAt = new Date().toISOString();
    const visual = this.lastAnalysisContext.visualFeatures;
    const emotion = this.lastAnalysisContext.emotionFeatures;
    const dominant = resolveDominantEmotion({
      positiveScore: emotion?.positiveScore,
      focusedScore: emotion?.focusedScore,
      frustratedScore: emotion?.frustratedScore
    });

    const meta: MonitorPreviewFrameMeta = {
      schemaVersion: MONITOR_PREVIEW_SCHEMA_VERSION,
      sessionId: options.sessionId,
      streamId,
      frameId: `${streamId}:preview-${sequence}`,
      sequence,
      capturedAt,
      width,
      height,
      faceBox: visual?.faceBox,
      facePresent: visual?.facePresent,
      attentionScore: typeof visual?.facingScore === "number" ? Math.round(visual.facingScore * 100) : undefined,
      emotionDominant: dominant.dominant,
      emotionLabel: dominant.label,
      attentionProvider: visual?.provider,
      emotionProvider: emotion?.provider,
      attentionAlgorithmVersion: visual?.algorithmVersion,
      emotionAlgorithmVersion: emotion?.algorithmVersion
    };

    void onPreviewFrame({ blob, mimeType: mimeType as "image/jpeg" | "image/webp", meta });
  }

  private releaseResources() {
    this.mediaStream?.getTracks().forEach((track) => track.stop());
    this.mediaStream = null;
    this.video = null;
    this.canvas = null;
    this.previewCanvas = null;
    this.previewSequence = 0;
    this.lastAnalysisContext = {};
  }

  private updateState(patch: Partial<BrowserCameraCaptureState>) {
    this.state = { ...this.state, ...patch };
    this.callbacks.onStateChange?.(this.state);
  }
}
