export const BEHAVIOR_FRAME_SCHEMA_VERSION = "m5-frame-v1" as const;
export const BEHAVIOR_FRAME_CONTENT_TYPE = "application/json" as const;
export const BEHAVIOR_FRAME_MAX_DESCRIPTOR_BYTES = 16 * 1024;

export interface CameraDeviceState {
  permission: "unknown" | "prompt" | "granted" | "denied" | "unsupported";
  deviceAvailable: boolean;
  selectedDeviceIdHash?: string;
  labelRedacted?: string;
  width?: number;
  height?: number;
  maxFps: number;
  stopped: boolean;
  errorCode?: string;
}

export interface CameraFrameSampleDescriptor {
  schemaVersion: typeof BEHAVIOR_FRAME_SCHEMA_VERSION;
  sessionId: string;
  streamId: string;
  frameId: string;
  sequence: number;
  capturedAt: string;
  correlationId: string;
  questionId?: string;
  width: number;
  height: number;
  downsampled: true;
  frameHash: string;
  byteLength: number;
  mimeType: "image/jpeg" | "image/webp" | "mock/frame-descriptor";
  rawFramePersisted: false;
  visualFeatures?: {
    facePresent: boolean;
    faceCount: number;
    headOrientation: "screen" | "left" | "right" | "up" | "down" | "away" | "unknown";
    roughlyFacingScreen?: boolean;
    facingScore?: number;
    centerOffsetX?: number;
    centerOffsetY?: number;
    faceAreaRatio?: number;
    faceBox?: {
      x: number;
      y: number;
      width: number;
      height: number;
    };
    imageQuality: "good" | "low_light" | "blurred" | "occluded" | "unavailable";
    provider:
      | "browser-face-detector"
      | "browser-mediapipe-face"
      | "browser-frame-quality"
      | "camera-device"
      | "attention-scoring-v2";
    algorithmVersion: string;
    confidence: number;
  };
  emotionFeatures?: {
    positiveScore: number;
    focusedScore: number;
    frustratedScore: number;
    facePresent: boolean;
    provider: "browser-mediapipe-landmarker";
    algorithmVersion: string;
    confidence: number;
    degraded: boolean;
  };
}

export interface CameraFrameAck {
  sessionId: string;
  streamId: string;
  frameId: string;
  sequence: number;
  accepted: boolean;
  expectedNextSequence: number;
  receivedFrameCount: number;
  droppedSequences: number[];
  rawFramePersisted: false;
}

export const BEHAVIOR_AUDIO_FEATURE_SCHEMA_VERSION = "m5-audio-features-v1" as const;

export interface BrowserTurnAudioFeatureDescriptor {
  schemaVersion: typeof BEHAVIOR_AUDIO_FEATURE_SCHEMA_VERSION;
  sessionId: string;
  turnId: string;
  correlationId: string;
  questionId?: string;
  observedAt: string;
  audioDurationMs: number;
  provider: "browser-web-audio" | "server-merged-audio";
  features: {
    loudnessRms: number;
    loudnessDb: number;
    speechRatio: number;
    clarityProxy: number;
    sampleCount: number;
    algorithmVersion: string;
    degraded: boolean;
  };
}

export interface BrowserAudioFeatureAck {
  sessionId: string;
  turnId: string;
  accepted: boolean;
  observationCount: number;
}
