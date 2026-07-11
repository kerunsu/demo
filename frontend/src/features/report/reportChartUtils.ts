import type { ProfessionalReportV2 } from "../../types";

const RADAR_CENTER = 100;
const RADAR_RADIUS = 75;

const RADAR_AXES = [
  { key: "attention" as const, label: "注意力", angleDeg: -90 },
  { key: "expressiveLanguage" as const, label: "表达语言", angleDeg: -18 },
  { key: "receptiveLanguage" as const, label: "接受语言", angleDeg: 54 },
  { key: "matching" as const, label: "配对", angleDeg: 126 },
  { key: "ordering" as const, label: "排序", angleDeg: 198 }
];

function polarPoint(angleDeg: number, radius: number) {
  const rad = (angleDeg * Math.PI) / 180;
  return {
    x: RADAR_CENTER + radius * Math.cos(rad),
    y: RADAR_CENTER + radius * Math.sin(rad)
  };
}

export function buildRadarPolygonPoints(dimensions: ProfessionalReportV2["dimensions"]) {
  return RADAR_AXES.map((axis) => {
    const score = Math.max(0, Math.min(100, dimensions[axis.key] ?? 0));
    const point = polarPoint(axis.angleDeg, (score / 100) * RADAR_RADIUS);
    return `${point.x.toFixed(1)},${point.y.toFixed(1)}`;
  }).join(" ");
}

export function buildRadarGridPoints(radius: number) {
  return RADAR_AXES.map((axis) => {
    const point = polarPoint(axis.angleDeg, radius);
    return `${point.x.toFixed(1)},${point.y.toFixed(1)}`;
  }).join(" ");
}

export function getRadarAxisLabels() {
  return RADAR_AXES.map((axis) => {
    const point = polarPoint(axis.angleDeg, RADAR_RADIUS + 14);
    return { ...axis, x: point.x, y: point.y };
  });
}

export function buildAttentionCurvePoints(
  curve: ProfessionalReportV2["attentionCurve"],
  width = 760,
  height = 100
) {
  const plottable = curve.filter((point) => typeof point.score === "number");
  if (plottable.length === 0) return { line: "", area: "", markers: [] as Array<{ x: number; y: number; warn: boolean }> };
  const step = plottable.length <= 1 ? 0 : width / (plottable.length - 1);
  const markers = plottable.map((point, index) => {
    const x = step * index;
    const score = point.score as number;
    const y = height - (score / 100) * (height - 10) - 5;
    const warn = point.quality !== "complete" || score < 50;
    return { x, y, warn };
  });
  const line = markers.map((marker) => `${marker.x.toFixed(1)},${marker.y.toFixed(1)}`).join(" ");
  const area = `0,${height} ${line} ${width},${height}`;
  return { line, area, markers };
}

export function dominantEmotionLabel(emotion: ProfessionalReportV2["emotionSummary"]) {
  if (emotion.status !== "AVAILABLE") return "数据不足";
  const positive = emotion.positiveRatio ?? 0;
  const focused = emotion.focusedRatio ?? 0;
  const frustrated = emotion.frustratedRatio ?? 0;
  if (positive >= focused && positive >= frustrated) return "愉悦为主";
  if (focused >= frustrated) return "专注为主";
  return "急躁/挫败偏多";
}
