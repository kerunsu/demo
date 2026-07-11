import type { TrainingReport } from "../../types";

export function deriveReportMetrics(report: TrainingReport | null) {
  const score = report ? Math.round(report.summary.accuracy * 100) : 0;
  return {
    score,
    starCount: report ? Math.max(1, Math.min(3, Math.round(report.summary.accuracy * 3))) : 1,
    demoReferenceIndex: report ? Math.max(50, Math.min(99, score + 7)) : 50
  };
}

export function formatReportDateTime(isoString: string) {
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return isoString;
  return date.toLocaleString("zh-CN", { hour12: false });
}

export function formatReportDuration(totalSeconds: number) {
  const safeSeconds = Math.max(0, Math.floor(totalSeconds));
  const min = Math.floor(safeSeconds / 60);
  const sec = safeSeconds % 60;
  return `${min}分${sec}秒`;
}
