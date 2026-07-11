import { FaceLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";
import {
  EMOTION_ALGORITHM_V1,
  toEmotionDescriptorFeatures,
  type EmotionBlendshapeMap,
  type EmotionDescriptorFeatures
} from "child-education-training-demo/shared/emotion-scoring";

const MEDIAPIPE_VISION_VERSION = "0.10.14";
const WASM_BASE = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MEDIAPIPE_VISION_VERSION}/wasm`;
const MODEL_PATH =
  "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";

let landmarkerInstance: FaceLandmarker | null = null;
let landmarkerPromise: Promise<FaceLandmarker | null> | null = null;

async function createLandmarker() {
  if (typeof window === "undefined") return null;
  try {
    const vision = await FilesetResolver.forVisionTasks(WASM_BASE);
    return await FaceLandmarker.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: MODEL_PATH,
        delegate: "GPU"
      },
      runningMode: "IMAGE",
      numFaces: 1,
      outputFaceBlendshapes: true
    });
  } catch {
    try {
      const vision = await FilesetResolver.forVisionTasks(WASM_BASE);
      return await FaceLandmarker.createFromOptions(vision, {
        baseOptions: {
          modelAssetPath: MODEL_PATH,
          delegate: "CPU"
        },
        runningMode: "IMAGE",
        numFaces: 1,
        outputFaceBlendshapes: true
      });
    } catch {
      return null;
    }
  }
}

async function getLandmarker() {
  if (landmarkerInstance) return landmarkerInstance;
  if (!landmarkerPromise) {
    landmarkerPromise = createLandmarker().then((landmarker) => {
      landmarkerInstance = landmarker;
      if (!landmarker) landmarkerPromise = null;
      return landmarker;
    });
  }
  return landmarkerPromise;
}

function toBlendshapeMap(
  categories: Array<{ categoryName?: string; score?: number }> | undefined
): EmotionBlendshapeMap | null {
  if (!categories || categories.length === 0) return null;
  const map: EmotionBlendshapeMap = {};
  for (const category of categories) {
    if (!category.categoryName) continue;
    map[category.categoryName] = category.score ?? 0;
  }
  return Object.keys(map).length > 0 ? map : null;
}

export async function detectEmotionFeaturesWithMediaPipe(
  canvas: HTMLCanvasElement,
  facePresent: boolean
): Promise<EmotionDescriptorFeatures | null> {
  if (!facePresent) return null;
  try {
    const landmarker = await getLandmarker();
    if (!landmarker) return null;
    const result = landmarker.detect(canvas);
    const blendshapes = toBlendshapeMap(result.faceBlendshapes?.[0]?.categories);
    if (!blendshapes) return null;
    return toEmotionDescriptorFeatures(blendshapes, true);
  } catch {
    return null;
  }
}

export function disposeMediaPipeFaceLandmarker() {
  landmarkerInstance?.close();
  landmarkerInstance = null;
  landmarkerPromise = null;
}

export { EMOTION_ALGORITHM_V1 };
