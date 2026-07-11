import { gaugeStrokeOffset } from "./monitorChartUtils";

type Props = {
  score?: number;
};

const RADIUS = 42;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export function AttentionGauge({ score }: Props) {
  return (
    <div className="server-gauge-wrap">
      <div className="server-gauge-ring">
        <svg viewBox="0 0 104 104">
          <circle className="server-gauge-track" cx="52" cy="52" r={RADIUS} />
          <circle
            className="server-gauge-value"
            cx="52"
            cy="52"
            r={RADIUS}
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={gaugeStrokeOffset(score, RADIUS)}
          />
        </svg>
        <div className="server-gauge-text">
          <strong>{typeof score === "number" ? score : "--"}</strong>
          <span>注意力分数</span>
        </div>
      </div>
    </div>
  );
}
