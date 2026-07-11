export const ATTENTION_ALGORITHM_V2 = "browser-attention-v2" as const;

export type AttentionImageQuality = "good" | "low_light" | "blurred" | "occluded" | "unavailable";
export type AttentionHeadOrientation = "screen" | "left" | "right" | "up" | "down" | "away" | "unknown";

export interface FaceBoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface AttentionScoringInput {
  frameWidth: number;
  frameHeight: number;
  faceCount: number;
  primaryFace?: FaceBoundingBox;
  imageQuality: AttentionImageQuality;
}

export interface AttentionVisualFeatures {
  facePresent: boolean;
  faceCount: number;
  headOrientation: AttentionHeadOrientation;
  roughlyFacingScreen?: boolean;
  facingScore?: number;
  centerOffsetX?: number;
  centerOffsetY?: number;
  faceAreaRatio?: number;
  imageQuality: AttentionImageQuality;
  provider:
    | "browser-face-detector"
    | "browser-mediapipe-face"
    | "browser-frame-quality"
    | "camera-device"
    | "attention-scoring-v2";
  algorithmVersion: string;
  confidence: number;
}

const FACING_THRESHOLD = 0.55;
const IDEAL_FACE_AREA_RATIO = 0.14;
const MIN_FACE_AREA_RATIO = 0.025;
const MAX_FACE_AREA_RATIO = 0.42;

function clamp(value: number, min = 0, max = 1) {
  return Math.min(max, Math.max(min, value));
}

function qualityConfidence(imageQuality: AttentionImageQuality) {
  if (imageQuality === "good") return 0.88;
  if (imageQuality === "low_light") return 0.58;
  if (imageQuality === "blurred" || imageQuality === "occluded") return 0.48;
  return 0;
}

function areaScore(faceAreaRatio: number) {
  if (faceAreaRatio <= 0) return 0;
  if (faceAreaRatio < MIN_FACE_AREA_RATIO || faceAreaRatio > MAX_FACE_AREA_RATIO) return 0.25;
  const delta = Math.abs(faceAreaRatio - IDEAL_FACE_AREA_RATIO);
  return clamp(1 - delta / IDEAL_FACE_AREA_RATIO);
}

function aspectScore(width: number, height: number) {
  if (width <= 0 || height <= 0) return 0;
  const ratio = width / height;
  if (ratio < 0.55 || ratio > 1.65) return 0.35;
  const delta = Math.abs(ratio - 1);
  return clamp(1 - delta / 0.8);
}

function centerScore(offsetX: number, offsetY: number) {
  const distance = Math.sqrt(offsetX * offsetX + offsetY * offsetY);
  return clamp(1 - distance / 0.95);
}

function resolveHeadOrientation(input: {
  roughlyFacingScreen: boolean;
  centerOffsetX: number;
  centerOffsetY: number;
}): AttentionHeadOrientation {
  if (input.roughlyFacingScreen) return "screen";
  const absX = Math.abs(input.centerOffsetX);
  const absY = Math.abs(input.centerOffsetY);
  if (absX > absY) {
    if (input.centerOffsetX <= -0.12) return "left";
    if (input.centerOffsetX >= 0.12) return "right";
  } else {
    if (input.centerOffsetY <= -0.12) return "up";
    if (input.centerOffsetY >= 0.12) return "down";
  }
  return "away";
}

export function scoreAttentionFromFaceGeometry(input: AttentionScoringInput): AttentionVisualFeatures {
  const frameArea = Math.max(1, input.frameWidth * input.frameHeight);
  const imageQuality = input.imageQuality;

  if (imageQuality === "unavailable" || input.faceCount <= 0 || !input.primaryFace) {
    return {
      facePresent: false,
      faceCount: Math.max(0, input.faceCount),
      headOrientation: "unknown",
      roughlyFacingScreen: undefined,
      facingScore: 0,
      centerOffsetX: 0,
      centerOffsetY: 0,
      faceAreaRatio: 0,
      imageQuality,
      provider: imageQuality === "unavailable" ? "browser-frame-quality" : "browser-face-detector",
      algorithmVersion: ATTENTION_ALGORITHM_V2,
      confidence: qualityConfidence(imageQuality) * 0.35
    };
  }

  const face = input.primaryFace;
  const centerX = (face.x + face.width / 2) / Math.max(1, input.frameWidth);
  const centerY = (face.y + face.height / 2) / Math.max(1, input.frameHeight);
  const centerOffsetX = clamp((centerX - 0.5) * 2, -1, 1);
  const centerOffsetY = clamp((centerY - 0.5) * 2, -1, 1);
  const faceAreaRatio = clamp((face.width * face.height) / frameArea, 0, 1);
  const geometryScore =
    centerScore(centerOffsetX, centerOffsetY) * 0.55 +
    areaScore(faceAreaRatio) * 0.25 +
    aspectScore(face.width, face.height) * 0.2;
  const multiFacePenalty = input.faceCount > 1 ? 0.45 : 1;
  const facingScore = clamp(geometryScore * multiFacePenalty);
  const roughlyFacingScreen = input.faceCount === 1 && facingScore >= FACING_THRESHOLD;
  const headOrientation = resolveHeadOrientation({ roughlyFacingScreen, centerOffsetX, centerOffsetY });
  const confidence = clamp(qualityConfidence(imageQuality) * (0.45 + facingScore * 0.55) * multiFacePenalty);

  return {
    facePresent: true,
    faceCount: input.faceCount,
    headOrientation,
    roughlyFacingScreen,
    facingScore: round(facingScore),
    centerOffsetX: round(centerOffsetX),
    centerOffsetY: round(centerOffsetY),
    faceAreaRatio: round(faceAreaRatio),
    imageQuality,
    provider: "browser-face-detector",
    algorithmVersion: ATTENTION_ALGORITHM_V2,
    confidence: round(confidence)
  };
}

export function scoreAttentionFromLegacyFeatures(input: {
  frameWidth: number;
  frameHeight: number;
  facePresent: boolean;
  faceCount: number;
  headOrientation: AttentionHeadOrientation;
  roughlyFacingScreen?: boolean;
  imageQuality: AttentionImageQuality;
  confidence?: number;
}): AttentionVisualFeatures {
  if (!input.facePresent || input.faceCount <= 0) {
    return {
      facePresent: false,
      faceCount: Math.max(0, input.faceCount),
      headOrientation: "unknown",
      roughlyFacingScreen: undefined,
      facingScore: 0,
      imageQuality: input.imageQuality,
      provider: "browser-frame-quality",
      algorithmVersion: ATTENTION_ALGORITHM_V2,
      confidence: input.confidence ?? qualityConfidence(input.imageQuality) * 0.35
    };
  }

  const facingScore =
    input.roughlyFacingScreen === true
      ? clamp((input.confidence ?? 0.75) * 0.95)
      : input.roughlyFacingScreen === false
        ? clamp((input.confidence ?? 0.45) * 0.35)
        : 0;
  return {
    facePresent: true,
    faceCount: input.faceCount,
    headOrientation: input.headOrientation,
    roughlyFacingScreen: input.roughlyFacingScreen,
    facingScore: round(facingScore),
    imageQuality: input.imageQuality,
    provider: "browser-face-detector",
    algorithmVersion: ATTENTION_ALGORITHM_V2,
    confidence: round(input.confidence ?? qualityConfidence(input.imageQuality) * (0.45 + facingScore * 0.55))
  };
}

export function normalizeAttentionVisualFeatures(input: {
  frameWidth: number;
  frameHeight: number;
  visualFeatures?: Partial<AttentionVisualFeatures> & {
    primaryFace?: FaceBoundingBox;
  };
  imageQuality?: AttentionImageQuality;
  byteLength?: number;
}): AttentionVisualFeatures {
  const imageQuality =
    input.visualFeatures?.imageQuality ??
    input.imageQuality ??
    estimateImageQuality(input.byteLength ?? 0, input.frameWidth, input.frameHeight);

  if (input.visualFeatures?.primaryFace) {
    return scoreAttentionFromFaceGeometry({
      frameWidth: input.frameWidth,
      frameHeight: input.frameHeight,
      faceCount: input.visualFeatures.faceCount ?? 1,
      primaryFace: input.visualFeatures.primaryFace,
      imageQuality
    });
  }

  if (input.visualFeatures?.algorithmVersion === ATTENTION_ALGORITHM_V2 && typeof input.visualFeatures.facingScore === "number") {
    return {
      facePresent: Boolean(input.visualFeatures.facePresent),
      faceCount: input.visualFeatures.faceCount ?? 0,
      headOrientation: input.visualFeatures.headOrientation ?? "unknown",
      roughlyFacingScreen: input.visualFeatures.roughlyFacingScreen,
      facingScore: input.visualFeatures.facingScore,
      centerOffsetX: input.visualFeatures.centerOffsetX,
      centerOffsetY: input.visualFeatures.centerOffsetY,
      faceAreaRatio: input.visualFeatures.faceAreaRatio,
      imageQuality,
      provider: input.visualFeatures.provider ?? "browser-face-detector",
      algorithmVersion: ATTENTION_ALGORITHM_V2,
      confidence: input.visualFeatures.confidence ?? qualityConfidence(imageQuality)
    };
  }

  if (input.visualFeatures) {
    return scoreAttentionFromLegacyFeatures({
      frameWidth: input.frameWidth,
      frameHeight: input.frameHeight,
      facePresent: Boolean(input.visualFeatures.facePresent),
      faceCount: input.visualFeatures.faceCount ?? 0,
      headOrientation: input.visualFeatures.headOrientation ?? "unknown",
      roughlyFacingScreen: input.visualFeatures.roughlyFacingScreen,
      imageQuality,
      confidence: input.visualFeatures.confidence
    });
  }

  return {
    facePresent: false,
    faceCount: 0,
    headOrientation: "unknown",
    roughlyFacingScreen: undefined,
    facingScore: 0,
    imageQuality,
    provider: "browser-frame-quality",
    algorithmVersion: ATTENTION_ALGORITHM_V2,
    confidence: qualityConfidence(imageQuality) * 0.35
  };
}

export function estimateImageQuality(byteLength: number, width: number, height: number): AttentionImageQuality {
  const bytesPerPixel = byteLength / Math.max(1, width * height);
  if (byteLength === 0) return "unavailable";
  if (bytesPerPixel < 0.02) return "low_light";
  if (bytesPerPixel < 0.05) return "blurred";
  return "good";
}

function round(value: number) {
  return Math.round(value * 1000) / 1000;
}
