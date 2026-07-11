import type { MonitorSnapshot } from "../../services/monitorService";

type Props = {
  snapshot: MonitorSnapshot | null;
};

function pct(value?: number) {
  if (typeof value !== "number") return "—";
  return `${Math.round(value * 100)}%`;
}

export function MonitorEmotionFeatures({ snapshot }: Props) {
  const emotion = snapshot?.emotion;
  if (!emotion) {
    return (
      <div className="server-audio-features server-audio-features-empty">
        <span>情绪识别：等待摄像头帧（browser-emotion-v1）</span>
      </div>
    );
  }

  const hasRatios =
    typeof emotion.positiveRatio === "number" ||
    typeof emotion.focusedRatio === "number" ||
    typeof emotion.frustratedRatio === "number";

  return (
    <div className="server-audio-features server-emotion-features">
      <div className="server-audio-features-head">
        <strong>表情情绪（教育训练参考）</strong>
        <span className={emotion.degraded ? "server-pill warn" : "server-pill"}>
          {emotion.provider ?? emotion.configuredProvider ?? "—"} · {emotion.algorithmVersion ?? "—"}
          {emotion.degraded ? " · 降级" : ""}
        </span>
      </div>
      {hasRatios ? (
        <div className="server-emotion-bars" aria-hidden="true">
          <div className="server-emotion-bar happy" style={{ width: pct(emotion.positiveRatio) }} title={`愉悦 ${pct(emotion.positiveRatio)}`} />
          <div className="server-emotion-bar focus" style={{ width: pct(emotion.focusedRatio) }} title={`专注 ${pct(emotion.focusedRatio)}`} />
          <div className="server-emotion-bar frust" style={{ width: pct(emotion.frustratedRatio) }} title={`急躁 ${pct(emotion.frustratedRatio)}`} />
        </div>
      ) : (
        <div className="server-audio-features-empty">
          <span>
            情绪识别：DEGRADED / {emotion.reason ?? "INSUFFICIENT_SIGNALS"}（观测 {emotion.observationCount ?? 0} 帧）
          </span>
        </div>
      )}
      {hasRatios ? (
        <div className="server-emotion-legend">
          <span>愉悦 {pct(emotion.positiveRatio)}</span>
          <span>专注 {pct(emotion.focusedRatio)}</span>
          <span>急躁 {pct(emotion.frustratedRatio)}</span>
          <span>帧数 {emotion.observationCount ?? 0}</span>
        </div>
      ) : null}
    </div>
  );
}
