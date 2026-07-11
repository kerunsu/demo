import { FaceDetector, FilesetResolver } from "@mediapipe/tasks-vision";

export type DetectedFaceBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

const MEDIAPIPE_VISION_VERSION = "0.10.14";
const WASM_BASE = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MEDIAPIPE_VISION_VERSION}/wasm`;
const MODEL_PATH =
  "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite";

let detectorInstance: FaceDetector | null = null;
let detectorPromise: Promise<FaceDetector | null> | null = null;

async function createDetector() {
  if (typeof window === "undefined") return null;
  try {
    const vision = await FilesetResolver.forVisionTasks(WASM_BASE);
    return await FaceDetector.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: MODEL_PATH,
        delegate: "GPU"
      },
      runningMode: "IMAGE",
      minDetectionConfidence: 0.5
    });
  } catch {
    return null;
  }
}

async function getDetector() {
  if (detectorInstance) return detectorInstance;
  if (!detectorPromise) {
    detectorPromise = createDetector().then((detector) => {
      detectorInstance = detector;
      if (!detector) detectorPromise = null;
      return detector;
    });
  }
  return detectorPromise;
}

function toFaceBoxes(detections: ReturnType<FaceDetector["detect"]>["detections"]): DetectedFaceBox[] {
  return detections
    .map((detection) => detection.boundingBox)
    .filter((box): box is NonNullable<typeof box> => Boolean(box))
    .map((box) => ({
      x: box.originX,
      y: box.originY,
      width: box.width,
      height: box.height
    }));
}

export async function detectFacesWithMediaPipe(canvas: HTMLCanvasElement): Promise<DetectedFaceBox[] | null> {
  try {
    const detector = await getDetector();
    if (!detector) return null;
    return toFaceBoxes(detector.detect(canvas).detections);
  } catch {
    return null;
  }
}

export function disposeMediaPipeFaceDetector() {
  detectorInstance?.close();
  detectorInstance = null;
  detectorPromise = null;
}
