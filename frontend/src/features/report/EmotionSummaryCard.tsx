import type { ProfessionalReportV2 } from "../../types";
import { dominantEmotionLabel } from "./reportChartUtils";

type Props = {
  emotionSummary: ProfessionalReportV2["emotionSummary"];
};

export function EmotionSummaryCard({ emotionSummary }: Props) {
  if (emotionSummary.status !== "AVAILABLE") {
    return (
      <div className="report-detail-kpi-card">
        <div className="kpi-label">主要情绪状态</div>
        <div className="kpi-value report-detail-emotion-title">数据不足</div>
        <div className="kpi-status kpi-status-warn">
          情绪识别：DEGRADED / {emotionSummary.reason ?? "MANUAL_ACCEPTANCE_REQUIRED"}
        </div>
      </div>
    );
  }

  const positive = Math.round((emotionSummary.positiveRatio ?? 0) * 100);
  const focused = Math.round((emotionSummary.focusedRatio ?? 0) * 100);
  const frustrated = Math.round((emotionSummary.frustratedRatio ?? 0) * 100);
  const isHeuristic = emotionSummary.provider?.includes("heuristic");
  const statusLabel = isHeuristic
    ? `启发式情绪参考（非独立模型） · ${emotionSummary.algorithmVersion ?? "emotion-heuristic-v1"}`
    : `表情情绪分析 · ${emotionSummary.provider ?? "local-browser-face-emotion"} · ${emotionSummary.algorithmVersion ?? "browser-emotion-v1"}${emotionSummary.degraded ? " · 部分降级" : ""}`;

  return (
    <div className="report-detail-kpi-card">
      <div className="kpi-label">主要情绪状态</div>
      <div className="kpi-value report-detail-emotion-title">{dominantEmotionLabel(emotionSummary)}</div>
      <div className="report-detail-emotion-bars" aria-hidden="true">
        <div className="report-detail-emo-happy" style={{ width: `${positive}%` }} />
        <div className="report-detail-emo-focus" style={{ width: `${focused}%` }} />
        <div className="report-detail-emo-frust" style={{ width: `${frustrated}%` }} />
      </div>
      <div className="report-detail-emotion-legend">
        <span>愉悦 {positive}%</span>
        <span>专注 {focused}%</span>
        <span>急躁 {frustrated}%</span>
      </div>
      <div className="kpi-status kpi-status-blue">{statusLabel}</div>
    </div>
  );
}
