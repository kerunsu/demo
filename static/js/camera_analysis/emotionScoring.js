/**
 * browser-emotion-v1：MediaPipe blendshape → positive / focused / frustrated
 * 当前评分规则以 docs/REPORT_SCORING.md 和本实现测试为准。
 */

function clamp(v, lo = 0, hi = 1) {
  return Math.max(lo, Math.min(hi, v));
}

function avg(a, b) {
  const xa = Number.isFinite(a) ? a : 0;
  const xb = Number.isFinite(b) ? b : 0;
  return (xa + xb) / 2;
}

function readBlend(map, name) {
  const v = map[name];
  return clamp(Number.isFinite(v) ? v : 0);
}

/**
 * @param {Record<string, number>|Array<{categories?: Array<{categoryName:string,score:number}>}>} blendshapes
 */
export function scoreEmotionFromBlendshapes(blendshapes) {
  const map = {};
  if (Array.isArray(blendshapes)) {
    // FaceLandmarker categories format
    const cats = blendshapes[0]?.categories || blendshapes;
    if (Array.isArray(cats)) {
      for (const c of cats) {
        if (c && c.categoryName) map[c.categoryName] = c.score;
      }
    }
  } else if (blendshapes && typeof blendshapes === 'object') {
    Object.assign(map, blendshapes);
  }

  if (!Object.keys(map).length) {
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

  const smile = avg(readBlend(map, 'mouthSmileLeft'), readBlend(map, 'mouthSmileRight'));
  const cheekRaise = avg(readBlend(map, 'cheekSquintLeft'), readBlend(map, 'cheekSquintRight'));
  const frown = avg(readBlend(map, 'mouthFrownLeft'), readBlend(map, 'mouthFrownRight'));
  const browDown = avg(readBlend(map, 'browDownLeft'), readBlend(map, 'browDownRight'));
  const browInnerUp = avg(readBlend(map, 'browInnerUpLeft'), readBlend(map, 'browInnerUpRight'));
  const eyeSquint = avg(readBlend(map, 'eyeSquintLeft'), readBlend(map, 'eyeSquintRight'));
  const mouthPress = avg(readBlend(map, 'mouthPressLeft'), readBlend(map, 'mouthPressRight'));
  const jawOpen = readBlend(map, 'jawOpen');

  let positive = clamp(0.72 * smile + 0.18 * cheekRaise + 0.1 * (1 - frown));
  let frustrated = clamp(
    0.42 * frown + 0.34 * browDown + 0.14 * mouthPress + 0.1 * browInnerUp
  );
  const neutralFocus = clamp(1 - 0.35 * jawOpen - 0.25 * frustrated);
  let focused = clamp(0.55 * neutralFocus + 0.25 * eyeSquint + 0.2 * (1 - positive));

  const signalStrength = Math.max(positive, focused, frustrated);
  let confidence = clamp(0.35 + 0.45 * signalStrength + 0.1 * (smile + eyeSquint));

  const total = positive + focused + frustrated;
  if (total <= 0.05) {
    positive = 0;
    focused = 0;
    frustrated = 0;
  } else {
    positive /= total;
    focused /= total;
    frustrated /= total;
  }

  return {
    positiveScore: Number(positive.toFixed(3)),
    focusedScore: Number(focused.toFixed(3)),
    frustratedScore: Number(frustrated.toFixed(3)),
    confidence: Number(confidence.toFixed(3)),
    degraded: false,
    algorithmVersion: 'browser-emotion-v1',
    unavailable: false,
  };
}

export function mapEmotionQualityStatus(emotion, facePresent) {
  if (!facePresent || !emotion || emotion.unavailable) return 'insufficient';
  if (emotion.degraded || (emotion.confidence ?? 0) < 0.45) return 'low_confidence';
  return 'complete';
}

export function dominantEmotionLabel(emotion) {
  if (!emotion || emotion.unavailable) return null;
  const entries = [
    ['愉悦', emotion.positiveScore || 0],
    ['专注', emotion.focusedScore || 0],
    ['急躁', emotion.frustratedScore || 0],
  ];
  entries.sort((a, b) => b[1] - a[1]);
  if (entries[0][1] <= 0) return null;
  return `${entries[0][0]}为主`;
}
