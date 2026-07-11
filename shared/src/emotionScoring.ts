export const EMOTION_ALGORITHM_V1 = "browser-emotion-v1" as const;

export type EmotionBlendshapeMap = Record<string, number>;

export interface EmotionDescriptorFeatures {
  positiveScore: number;
  focusedScore: number;
  frustratedScore: number;
  facePresent: boolean;
  provider: "browser-mediapipe-landmarker";
  algorithmVersion: typeof EMOTION_ALGORITHM_V1 | string;
  confidence: number;
  degraded: boolean;
}

export interface EmotionCategoryScores {
  positive: number;
  focused: number;
  frustrated: number;
  confidence: number;
}

function clamp(value: number, min = 0, max = 1) {
  return Math.min(max, Math.max(min, value));
}

function blendValue(blendshapes: EmotionBlendshapeMap, name: string) {
  return clamp(blendshapes[name] ?? 0);
}

function average(...values: number[]) {
  if (values.length === 0) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

export function scoreEmotionFromBlendshapes(
  blendshapes: EmotionBlendshapeMap,
  facePresent: boolean
): EmotionCategoryScores {
  if (!facePresent) {
    return { positive: 0, focused: 0, frustrated: 0, confidence: 0 };
  }

  const smile = average(
    blendValue(blendshapes, "mouthSmileLeft"),
    blendValue(blendshapes, "mouthSmileRight")
  );
  const cheekRaise = average(
    blendValue(blendshapes, "cheekSquintLeft"),
    blendValue(blendshapes, "cheekSquintRight")
  );
  const frown = average(
    blendValue(blendshapes, "mouthFrownLeft"),
    blendValue(blendshapes, "mouthFrownRight")
  );
  const browDown = average(
    blendValue(blendshapes, "browDownLeft"),
    blendValue(blendshapes, "browDownRight")
  );
  const browInnerUp = average(
    blendValue(blendshapes, "browInnerUpLeft"),
    blendValue(blendshapes, "browInnerUpRight")
  );
  const eyeSquint = average(
    blendValue(blendshapes, "eyeSquintLeft"),
    blendValue(blendshapes, "eyeSquintRight")
  );
  const jawOpen = blendValue(blendshapes, "jawOpen");
  const mouthPress = average(
    blendValue(blendshapes, "mouthPressLeft"),
    blendValue(blendshapes, "mouthPressRight")
  );

  const positive = clamp(smile * 0.72 + cheekRaise * 0.18 + (1 - frown) * 0.1);
  const frustrated = clamp(frown * 0.42 + browDown * 0.34 + mouthPress * 0.14 + browInnerUp * 0.1);
  const neutralFocus = clamp(1 - jawOpen * 0.35 - frustrated * 0.25);
  const focused = clamp(neutralFocus * 0.55 + eyeSquint * 0.25 + (1 - positive) * 0.2);

  const signalStrength = Math.max(positive, focused, frustrated);
  const confidence = clamp(0.35 + signalStrength * 0.45 + (smile + eyeSquint) * 0.1);

  return { positive, focused, frustrated, confidence };
}

export function normalizeEmotionCategoryScores(scores: EmotionCategoryScores): EmotionCategoryScores {
  const total = scores.positive + scores.focused + scores.frustrated;
  if (total <= 0.05) {
    return { positive: 0, focused: 0, frustrated: 0, confidence: scores.confidence };
  }
  return {
    positive: round(scores.positive / total),
    focused: round(scores.focused / total),
    frustrated: round(scores.frustrated / total),
    confidence: scores.confidence
  };
}

export function toEmotionDescriptorFeatures(
  blendshapes: EmotionBlendshapeMap,
  facePresent: boolean,
  degraded = false
): EmotionDescriptorFeatures {
  const raw = scoreEmotionFromBlendshapes(blendshapes, facePresent);
  const normalized = normalizeEmotionCategoryScores(raw);
  const lowSignal = normalized.positive + normalized.focused + normalized.frustrated < 0.15;
  return {
    positiveScore: normalized.positive,
    focusedScore: normalized.focused,
    frustratedScore: normalized.frustrated,
    facePresent,
    provider: "browser-mediapipe-landmarker",
    algorithmVersion: EMOTION_ALGORITHM_V1,
    confidence: round(raw.confidence),
    degraded: degraded || lowSignal || !facePresent
  };
}

export function normalizeEmotionDescriptorFeatures(
  input?: Partial<EmotionDescriptorFeatures> | null
): EmotionDescriptorFeatures | undefined {
  if (!input || input.facePresent === false) return undefined;
  if (
    typeof input.positiveScore !== "number" ||
    typeof input.focusedScore !== "number" ||
    typeof input.frustratedScore !== "number"
  ) {
    return undefined;
  }

  const normalized = normalizeEmotionCategoryScores({
    positive: input.positiveScore,
    focused: input.focusedScore,
    frustrated: input.frustratedScore,
    confidence: typeof input.confidence === "number" ? input.confidence : 0.5
  });

  return {
    positiveScore: normalized.positive,
    focusedScore: normalized.focused,
    frustratedScore: normalized.frustrated,
    facePresent: true,
    provider: "browser-mediapipe-landmarker",
    algorithmVersion: EMOTION_ALGORITHM_V1,
    confidence: normalized.confidence,
    degraded: Boolean(input.degraded) || normalized.positive + normalized.focused + normalized.frustrated < 0.15
  };
}

function round(value: number) {
  return Math.round(value * 1000) / 1000;
}
