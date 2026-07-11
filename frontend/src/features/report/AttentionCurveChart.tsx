import type { ProfessionalReportV2 } from "../../types";
import { buildAttentionCurvePoints } from "./reportChartUtils";

type Props = {
  curve: ProfessionalReportV2["attentionCurve"];
};

export function AttentionCurveChart({ curve }: Props) {
  const { line, area, markers } = buildAttentionCurvePoints(curve);

  return (
    <div className="report-detail-chart-card">
      <div className="report-detail-chart-header">
        <div className="report-detail-chart-title">训练期间注意力波动曲线</div>
        <div className="report-detail-chart-meta">X: 题序（每题均值） | Y: 专注度</div>
      </div>
      <svg className="report-detail-chart-svg" viewBox="0 0 760 100" preserveAspectRatio="none" aria-label="注意力波动曲线">
        <line x1="0" y1="20" x2="760" y2="20" stroke="#f1f5f9" strokeWidth="1" />
        <line x1="0" y1="50" x2="760" y2="50" stroke="#f1f5f9" strokeWidth="1" />
        <line x1="0" y1="80" x2="760" y2="80" stroke="#f1f5f9" strokeWidth="1" />
        <defs>
          <linearGradient id="reportAttentionGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#0284c7" stopOpacity="0.2" />
            <stop offset="100%" stopColor="#0284c7" stopOpacity="0" />
          </linearGradient>
        </defs>
        {area ? <polygon points={area} fill="url(#reportAttentionGradient)" /> : null}
        {line ? <polyline points={line} fill="none" stroke="#0284c7" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /> : null}
        {markers.map((marker, index) => (
          <circle
            key={`${marker.x}-${index}`}
            cx={marker.x}
            cy={marker.y}
            r={marker.warn ? 4.5 : 3.5}
            fill="white"
            stroke={marker.warn ? "#d97706" : "#0284c7"}
            strokeWidth={marker.warn ? 2.5 : 2}
          />
        ))}
      </svg>
    </div>
  );
}
