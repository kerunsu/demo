/**
 * browser-attention-v2：人脸框几何「朝屏」代理分（0–100）
 * 当前评分规则以 docs/REPORT_SCORING.md 和本实现测试为准。
 */

function clamp(v, lo = 0, hi = 1) {
  return Math.max(lo, Math.min(hi, v));
}

export function estimateImageQuality(blobSize, frameWidth, frameHeight) {
  if (!blobSize || blobSize <= 0) return 'unavailable';
  const bpp = blobSize / (frameWidth * frameHeight);
  if (bpp < 0.02) return 'low_light';
  if (bpp < 0.05) return 'blurred';
  return 'good';
}

export function scoreAttentionFromFace({
  frameWidth,
  frameHeight,
  faceCount = 0,
  primaryFace = null,
  imageQuality = 'good',
}) {
  if (!primaryFace || faceCount <= 0 || imageQuality === 'unavailable') {
    return {
      facePresent: false,
      faceCount: faceCount || 0,
      facingScore: 0,
      attentionScore100: 0,
      roughlyFacingScreen: false,
      headOrientation: 'unknown',
      imageQuality,
      confidence: 0,
      algorithmVersion: 'browser-attention-v2',
    };
  }

  const { x, y, width, height } = primaryFace;
  const centerX = (x + width / 2) / frameWidth;
  const centerY = (y + height / 2) / frameHeight;
  const offsetX = clamp((centerX - 0.5) * 2, -1, 1);
  const offsetY = clamp((centerY - 0.5) * 2, -1, 1);
  const faceAreaRatio = clamp((width * height) / (frameWidth * frameHeight), 0, 1);

  const centerScore = clamp(1 - Math.sqrt(offsetX * offsetX + offsetY * offsetY) / 0.95);

  const idealArea = 0.14;
  let areaScore = 0;
  if (faceAreaRatio <= 0) areaScore = 0;
  else if (faceAreaRatio < 0.025 || faceAreaRatio > 0.42) areaScore = 0.25;
  else areaScore = clamp(1 - Math.abs(faceAreaRatio - idealArea) / idealArea);

  const aspectRatio = height > 0 ? width / height : 0;
  let aspectScore = 0.35;
  if (aspectRatio >= 0.55 && aspectRatio <= 1.65) {
    aspectScore = clamp(1 - Math.abs(aspectRatio - 1) / 0.8);
  }

  const geometryScore = 0.55 * centerScore + 0.25 * areaScore + 0.2 * aspectScore;
  const multiFacePenalty = faceCount > 1 ? 0.45 : 1.0;
  const facingScore = clamp(geometryScore * multiFacePenalty);
  const roughlyFacingScreen = faceCount === 1 && facingScore >= 0.55;

  let headOrientation = 'away';
  if (roughlyFacingScreen) headOrientation = 'screen';
  else if (Math.abs(offsetX) > Math.abs(offsetY)) {
    if (offsetX <= -0.12) headOrientation = 'left';
    else if (offsetX >= 0.12) headOrientation = 'right';
  } else if (offsetY <= -0.12) headOrientation = 'up';
  else if (offsetY >= 0.12) headOrientation = 'down';

  const qualityConfidence = {
    good: 0.88,
    low_light: 0.58,
    blurred: 0.48,
    occluded: 0.48,
    unavailable: 0,
  }[imageQuality] ?? 0.5;

  const confidence = clamp(
    qualityConfidence * (0.45 + 0.55 * facingScore) * multiFacePenalty
  );

  return {
    facePresent: true,
    faceCount,
    faceBox: {
      x: x / frameWidth,
      y: y / frameHeight,
      width: width / frameWidth,
      height: height / frameHeight,
    },
    facingScore,
    attentionScore100: Math.round(facingScore * 100),
    roughlyFacingScreen,
    headOrientation,
    imageQuality,
    confidence,
    algorithmVersion: 'browser-attention-v2',
  };
}

export function mapAttentionQualityStatus(visual) {
  if (!visual || visual.imageQuality === 'unavailable') return 'missing_device';
  if (
    ['low_light', 'blurred', 'occluded'].includes(visual.imageQuality) ||
    (visual.confidence ?? 0) < 0.5
  ) {
    return 'low_confidence';
  }
  return 'complete';
}
