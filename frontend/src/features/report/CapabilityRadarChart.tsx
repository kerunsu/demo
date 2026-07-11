import type { ProfessionalReportV2 } from "../../types";
import { buildRadarGridPoints, buildRadarPolygonPoints, getRadarAxisLabels } from "./reportChartUtils";

type Props = {
  dimensions: ProfessionalReportV2["dimensions"];
};

export function CapabilityRadarChart({ dimensions }: Props) {
  const dataPoints = buildRadarPolygonPoints(dimensions);
  const gridOuter = buildRadarGridPoints(75);
  const gridInner = buildRadarGridPoints(45);
  const labels = getRadarAxisLabels();

  return (
    <div className="report-detail-radar-box">
      <p className="report-detail-subtitle">核心能力五维分布图</p>
      <svg className="report-detail-radar-svg" viewBox="0 0 200 200" aria-label="能力维度图">
        <polygon points={gridOuter} fill="none" stroke="#e2e8f0" />
        <polygon points={gridInner} fill="none" stroke="#e2e8f0" />
        {labels.map((axis) => (
          <line key={axis.key} x1="100" y1="100" x2={polar(axis.angleDeg, 75).x} y2={polar(axis.angleDeg, 75).y} stroke="#e2e8f0" />
        ))}
        <polygon points={dataPoints} fill="rgba(2, 132, 199, 0.2)" stroke="#0284c7" strokeWidth="2" />
        {labels.map((axis) => (
          <text key={`${axis.key}-label`} x={axis.x} y={axis.y} fontSize="10" fill="#64748b" textAnchor="middle">
            {axis.label}
          </text>
        ))}
      </svg>
    </div>
  );
}

function polar(angleDeg: number, radius: number) {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: 100 + radius * Math.cos(rad), y: 100 + radius * Math.sin(rad) };
}
