import type { MonitorSnapshot } from "../../services/monitorService";
import { buildAttentionChart } from "./monitorChartUtils";

type Props = {
  snapshot: MonitorSnapshot | null;
};

export function MonitorAttentionChart({ snapshot }: Props) {
  const chart = buildAttentionChart(snapshot);
  return (
    <div className="server-chart-card">
      <div className="server-chart-title">
        <span>实时注意力波动</span>
        <span>
          均值 {chart.average}
          {chart.sampleCount > 0 ? ` · ${chart.sampleCount} 采样` : ""}
        </span>
      </div>
      <div className="server-chart-body">
        <svg viewBox="0 0 320 130" preserveAspectRatio="none">
          <defs>
            <linearGradient id="monitorFadeCyan" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#2aa8c8" stopOpacity="0.22" />
              <stop offset="100%" stopColor="#2aa8c8" stopOpacity="0" />
            </linearGradient>
          </defs>
          {[18, 53, 88, 122].map((y) => (
            <line key={y} className="server-chart-grid" x1="30" y1={y} x2="310" y2={y} />
          ))}
          {chart.area ? <path className="server-chart-area" d={chart.area} fill="url(#monitorFadeCyan)" /> : null}
          {chart.line ? <polyline className="server-chart-line-cyan" points={chart.line} /> : null}
          <text className="server-chart-label" x="4" y="23">
            100
          </text>
          <text className="server-chart-label" x="10" y="57">
            75
          </text>
          <text className="server-chart-label" x="10" y="92">
            50
          </text>
          <text className="server-chart-label" x="17" y="126">
            0
          </text>
        </svg>
      </div>
    </div>
  );
}
