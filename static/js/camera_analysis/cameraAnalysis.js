/**
 * 儿童端摄像头分析：1FPS 采样 → 注意力/情绪描述符 → Socket camera_analysis
 */
import {
  estimateImageQuality,
  scoreAttentionFromFace,
  mapAttentionQualityStatus,
} from './attentionScoring.js';
import {
  scoreEmotionFromBlendshapes,
  mapEmotionQualityStatus,
} from './emotionScoring.js';

const DEFAULTS = {
  enabled: true,
  fps: 1,
  width: 160,
  height: 120,
  mediapipeWasm: 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm',
  faceDetectorModel:
    'https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite',
  faceLandmarkerModel:
    'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task',
};

let cfg = { ...DEFAULTS };
let socketRef = null;
let contextGetter = () => ({});
let running = false;
let timer = null;
let busy = false;
let sequence = 0;
let analysisCanvas = null;
let analysisCtx = null;
let nativeDetector = null;
let mpFaceDetector = null;
let mpLandmarker = null;
let mpReady = false;
let mpFailed = false;

export function configureCameraAnalysis(options = {}) {
  cfg = { ...cfg, ...options };
}

export function bindCameraAnalysisSocket(socket, getContext) {
  socketRef = socket;
  if (typeof getContext === 'function') contextGetter = getContext;
}

async function ensureNativeDetector() {
  if (nativeDetector !== null) return nativeDetector;
  if (typeof window.FaceDetector === 'function') {
    try {
      nativeDetector = new window.FaceDetector({ fastMode: true, maxDetectedFaces: 3 });
      return nativeDetector;
    } catch (e) {
      console.warn('[camera_analysis] FaceDetector 不可用:', e);
      nativeDetector = false;
      return null;
    }
  }
  nativeDetector = false;
  return null;
}

async function ensureMediaPipe() {
  if (mpReady || mpFailed) return mpReady;
  try {
    const vision = await import(
      'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/+esm'
    );
    const { FilesetResolver, FaceDetector, FaceLandmarker } = vision;
    const fileset = await FilesetResolver.forVisionTasks(cfg.mediapipeWasm);
    mpFaceDetector = await FaceDetector.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: cfg.faceDetectorModel, delegate: 'GPU' },
      runningMode: 'IMAGE',
    }).catch(async () =>
      FaceDetector.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: cfg.faceDetectorModel, delegate: 'CPU' },
        runningMode: 'IMAGE',
      })
    );
    mpLandmarker = await FaceLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: cfg.faceLandmarkerModel, delegate: 'GPU' },
      runningMode: 'IMAGE',
      numFaces: 1,
      outputFaceBlendshapes: true,
    }).catch(async () =>
      FaceLandmarker.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: cfg.faceLandmarkerModel, delegate: 'CPU' },
        runningMode: 'IMAGE',
        numFaces: 1,
        outputFaceBlendshapes: true,
      })
    );
    mpReady = true;
    console.log('[camera_analysis] MediaPipe 已就绪');
    return true;
  } catch (e) {
    console.warn('[camera_analysis] MediaPipe 加载失败，将降级:', e);
    mpFailed = true;
    mpReady = false;
    return false;
  }
}

function ensureCanvas() {
  if (!analysisCanvas) {
    analysisCanvas = document.createElement('canvas');
    analysisCanvas.width = cfg.width;
    analysisCanvas.height = cfg.height;
    analysisCtx = analysisCanvas.getContext('2d', { willReadFrequently: true });
  }
  if (analysisCanvas.width !== cfg.width || analysisCanvas.height !== cfg.height) {
    analysisCanvas.width = cfg.width;
    analysisCanvas.height = cfg.height;
  }
}

function pickVideoSource() {
  const el = document.getElementById('childCam');
  if (el && el.readyState >= 2 && el.videoWidth > 0) return el;
  return null;
}

async function detectFaces(bitmapOrCanvas) {
  const native = await ensureNativeDetector();
  if (native) {
    try {
      const faces = await native.detect(bitmapOrCanvas);
      return (faces || []).map((f) => {
        const box = f.boundingBox || f;
        return {
          x: box.x ?? box.left ?? 0,
          y: box.y ?? box.top ?? 0,
          width: box.width ?? 0,
          height: box.height ?? 0,
        };
      });
    } catch (e) {
      console.warn('[camera_analysis] native detect 失败', e);
    }
  }

  if (await ensureMediaPipe()) {
    try {
      const result = mpFaceDetector.detect(bitmapOrCanvas);
      const detections = result?.detections || [];
      return detections.map((d) => {
        const bb = d.boundingBox || {};
        return {
          x: bb.originX || 0,
          y: bb.originY || 0,
          width: bb.width || 0,
          height: bb.height || 0,
        };
      });
    } catch (e) {
      console.warn('[camera_analysis] MP face detect 失败', e);
    }
  }
  return [];
}

async function detectEmotionBlendshapes(bitmapOrCanvas, facePresent) {
  if (!facePresent) return null;
  if (!(await ensureMediaPipe()) || !mpLandmarker) {
    return {
      positiveScore: 0,
      focusedScore: 0,
      frustratedScore: 0,
      confidence: 0,
      degraded: true,
      algorithmVersion: 'browser-emotion-v1',
      unavailable: true,
    };
  }
  try {
    const result = mpLandmarker.detect(bitmapOrCanvas);
    const shapes = result?.faceBlendshapes || [];
    if (!shapes.length) {
      return {
        positiveScore: 0,
        focusedScore: 0,
        frustratedScore: 0,
        confidence: 0,
        degraded: true,
        algorithmVersion: 'browser-emotion-v1',
        unavailable: true,
      };
    }
    return scoreEmotionFromBlendshapes(shapes);
  } catch (e) {
    console.warn('[camera_analysis] landmarker 失败', e);
    return {
      positiveScore: 0,
      focusedScore: 0,
      frustratedScore: 0,
      confidence: 0,
      degraded: true,
      algorithmVersion: 'browser-emotion-v1',
      unavailable: true,
    };
  }
}

async function blobSizeEstimate() {
  return new Promise((resolve) => {
    if (!analysisCanvas) return resolve(0);
    analysisCanvas.toBlob(
      (b) => resolve(b ? b.size : 0),
      'image/jpeg',
      0.7
    );
  });
}

function emitDescriptor(descriptor) {
  if (!socketRef || !socketRef.connected) return;
  socketRef.emit('camera_analysis', descriptor);
}

async function analyzeOnce() {
  if (!running || busy || !cfg.enabled) return;
  const video = pickVideoSource();
  if (!video) {
    const ctx = contextGetter() || {};
    sequence += 1;
    emitDescriptor({
      sessionId: ctx.sessionId || null,
      trainingSessionId: ctx.trainingSessionId || null,
      questionId: ctx.questionId || null,
      frameId: `f_${Date.now()}_${sequence}`,
      sequence,
      capturedAt: new Date().toISOString(),
      width: cfg.width,
      height: cfg.height,
      downsampled: true,
      rawFramePersisted: false,
      provider: 'browser',
      visualFeatures: {
        facePresent: false,
        faceCount: 0,
        facingScore: 0,
        attentionScore100: 0,
        headOrientation: 'unknown',
        imageQuality: 'unavailable',
        confidence: 0,
        algorithmVersion: 'browser-attention-v2',
      },
      dataQuality: { attention: 'missing_device', emotion: 'insufficient' },
    });
    return;
  }

  busy = true;
  try {
    ensureCanvas();
    analysisCtx.drawImage(video, 0, 0, cfg.width, cfg.height);
    const size = await blobSizeEstimate();
    const imageQuality = estimateImageQuality(size, cfg.width, cfg.height);

    const faces = await detectFaces(analysisCanvas);
    let primary = null;
    if (faces.length) {
      primary = faces.reduce((a, b) =>
        a.width * a.height >= b.width * b.height ? a : b
      );
    }

    const visual = scoreAttentionFromFace({
      frameWidth: cfg.width,
      frameHeight: cfg.height,
      faceCount: faces.length,
      primaryFace: primary,
      imageQuality,
    });

    const emotion = await detectEmotionBlendshapes(analysisCanvas, visual.facePresent);
    const ctx = contextGetter() || {};
    sequence += 1;

    emitDescriptor({
      sessionId: ctx.sessionId || null,
      trainingSessionId: ctx.trainingSessionId || null,
      questionId: ctx.questionId || null,
      frameId: `f_${Date.now()}_${sequence}`,
      sequence,
      capturedAt: new Date().toISOString(),
      width: cfg.width,
      height: cfg.height,
      downsampled: true,
      rawFramePersisted: false,
      provider: 'browser',
      visualFeatures: visual,
      emotionFeatures: emotion || undefined,
      dataQuality: {
        attention: mapAttentionQualityStatus(visual),
        emotion: mapEmotionQualityStatus(emotion, visual.facePresent),
      },
    });
  } catch (e) {
    console.warn('[camera_analysis] analyzeOnce 异常', e);
  } finally {
    busy = false;
  }
}

export async function startCameraAnalysis() {
  if (!cfg.enabled) return;
  if (running) return;
  running = true;
  // 预热 MediaPipe（不阻塞循环启动）
  ensureMediaPipe().catch(() => {});
  const interval = Math.max(500, Math.round(1000 / Math.max(0.2, Math.min(2, cfg.fps || 1))));
  await analyzeOnce();
  timer = window.setInterval(() => {
    analyzeOnce();
  }, interval);
  console.log('[camera_analysis] 已启动, interval=', interval);
}

export function stopCameraAnalysis() {
  running = false;
  if (timer) {
    window.clearInterval(timer);
    timer = null;
  }
  busy = false;
}

export function isCameraAnalysisRunning() {
  return running;
}
