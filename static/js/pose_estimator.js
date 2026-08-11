// static/js/pose_estimator.js
import { FilesetResolver, PoseLandmarker } from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest";
let poseLandmarker;
let currentRunningMode = "IMAGE"; // 跟踪当前运行模式

export async function initPose() {
  const vision = await FilesetResolver.forVisionTasks(
    "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm"
  );
  poseLandmarker = await PoseLandmarker.createFromOptions(vision, {
    baseOptions: {
      modelAssetPath:
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
    },
    numPoses: 1,
    runningMode: "IMAGE"
  });
  console.log("Pose model loaded.");
}

export async function detectImage(imgEl) {
  // 检查poseLandmarker是否已初始化
  if (!poseLandmarker) {
    throw new Error("PoseLandmarker未初始化，请先调用initPose()");
  }
  
  // 检查图像元素是否有效
  if (!imgEl || !imgEl.complete || imgEl.naturalWidth === 0 || imgEl.naturalHeight === 0) {
    throw new Error("图像未准备就绪或尺寸无效");
  }
  
  // 确保运行模式设置为IMAGE
  if (currentRunningMode !== "IMAGE") {
    await poseLandmarker.setOptions({ runningMode: "IMAGE" });
    currentRunningMode = "IMAGE";
  }
  
  const res = poseLandmarker.detect(imgEl);
  return res.landmarks?.[0] || null;
}

export async function detectVideo(videoEl, timestampMs) {
  // 检查poseLandmarker是否已初始化
  if (!poseLandmarker) {
    throw new Error("PoseLandmarker未初始化，请先调用initPose()");
  }
  
  // 检查视频元素是否有效
  if (!videoEl || videoEl.readyState < 2 || videoEl.videoWidth === 0 || videoEl.videoHeight === 0) {
    throw new Error("视频未准备就绪或尺寸无效");
  }
  
  if (currentRunningMode !== "VIDEO") {
    await poseLandmarker.setOptions({ runningMode: "VIDEO" });
    currentRunningMode = "VIDEO";
  }
  const res = poseLandmarker.detectForVideo(videoEl, timestampMs);
  return res.landmarks?.[0] || null;
}
