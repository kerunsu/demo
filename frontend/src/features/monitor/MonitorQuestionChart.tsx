import type { MonitorSnapshot } from "../../services/monitorService";
import { buildQuestionPerformanceChart } from "./monitorChartUtils";

type Props = {
  snapshot: MonitorSnapshot | null;
};

export function MonitorQuestionChart({ snapshot }: Props) {
  const chart = buildQuestionPerformanceChart(snapshot);
  const attempted = snapshot?.course.questionStats.filter((item) => item.attempted).length ?? 0;
  return (
    <div className="server-chart-card">
      <div className="server-chart-title">
        <span>逐题正确率与响应时延</span>
        <span>题 {attempted > 0 ? `1–${attempted}` : "—"}</span>
      </div>
      <div className="server-chart-body">
        <svg viewBox="0 0 320 130" preserveAspectRatio="none">
          {[20, 60, 100].map((y) => (
            <line key={y} className="server-chart-grid" x1="26" y1={y} x2="312" y2={y} />
          ))}
          {chart.bars.map((bar) => (
            <rect
              key={bar.index}
              className={bar.correct ? "server-chart-bar" : "server-chart-bar alt"}
              x={bar.x}
              y={bar.y}
              width="20"
              height={bar.height}
              rx="4"
            />
          ))}
          {chart.line ? <polyline className="server-chart-line-yellow" points={chart.line} /> : null}
        </svg>
      </div>
    </div>
  );
}
