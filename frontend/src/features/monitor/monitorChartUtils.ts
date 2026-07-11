import type { MonitorSnapshot } from "../../services/monitorService";

export function buildAttentionChart(snapshot: MonitorSnapshot | null) {
  const samples = snapshot?.attention.attentionSamples ?? [];
  const values = samples.length
    ? samples.map((item) => item.score ?? 0)
    : (snapshot?.attention.questionWindows ?? []).map((item) => item.score ?? 0);
  const fallback = values.length ? values : [0, 0, 0, 0, 0];
  const points = fallback.slice(-60).map((value, index, list) => {
    const x = list.length <= 1 ? 30 : 30 + (index / (list.length - 1)) * 280;
    const y = 122 - Math.max(0, Math.min(100, value)) * 1.04;
    return { x, y, value };
  });
  const line = points.map((point) => `${point.x},${point.y}`).join(" ");
  const area = points.length
    ? `M${points[0].x},${points[0].y} ${points.slice(1).map((point) => `L${point.x},${point.y}`).join(" ")} L${points[points.length - 1].x},122 L${points[0].x},122 Z`
    : "";
  const average =
    fallback.length > 0 ? Math.round(fallback.reduce((sum, value) => sum + value, 0) / fallback.length) : 0;
  return { line, area, average, points, sampleCount: samples.length };
}

export function buildQuestionPerformanceChart(snapshot: MonitorSnapshot | null) {
  const stats = (snapshot?.course.questionStats ?? []).filter((item) => item.attempted).slice(-8);
  if (stats.length === 0) {
    return { bars: [], line: "", maxResponseMs: 1 };
  }
  const maxResponseMs = Math.max(...stats.map((item) => item.responseTimeMs), 1);
  const barWidth = 20;
  const gap = 38;
  const startX = 40;
  const bars = stats.map((item, index) => {
    const x = startX + index * gap;
    const height = item.correct ? 61 : 30;
    const y = 100 - height;
    const responseY = 100 - Math.round((item.responseTimeMs / maxResponseMs) * 55);
    return { x, y, height, correct: item.correct, responseY, index: item.questionIndex };
  });
  const line = bars.map((bar) => `${bar.x + barWidth / 2},${bar.responseY}`).join(" ");
  return { bars, line, maxResponseMs };
}

export function gaugeStrokeOffset(score: number | undefined, radius = 42) {
  const circumference = 2 * Math.PI * radius;
  const normalized = Math.max(0, Math.min(100, score ?? 0));
  return circumference - (normalized / 100) * circumference;
}
