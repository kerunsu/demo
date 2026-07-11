import type { MonitorSnapshot } from "../../services/monitorService";

type Props = {
  snapshot: MonitorSnapshot | null;
};

function barWidth(value?: number) {
  if (typeof value !== "number") return 0;
  return Math.max(0, Math.min(100, Math.round(value * 100)));
}

function formatDb(value?: number) {
  if (typeof value !== "number") return "—";
  return `${value.toFixed(1)} dB`;
}

export function MonitorAudioFeatures({ snapshot }: Props) {
  const features = snapshot?.voice.audioFeatures;
  if (!features) {
    return (
      <div className="server-audio-features server-audio-features-empty">
        <span>声学特征：等待语音回合（browser-web-audio）</span>
      </div>
    );
  }

  return (
    <div className="server-audio-features">
      <div className="server-audio-features-head">
        <strong>声学特征（工程代理指标）</strong>
        <span className={features.degraded ? "server-pill warn" : "server-pill"}>
          {features.provider ?? "browser-web-audio"} · {features.algorithmVersion ?? "—"}
          {features.degraded ? " · 降级" : ""}
        </span>
      </div>
      <div className="server-audio-feature-bars">
        <div className="server-audio-feature-row">
          <label>响度 RMS</label>
          <div className="server-progress" aria-hidden="true">
            <i style={{ width: `${barWidth(features.loudnessRms)}%` }} />
          </div>
          <span>{typeof features.loudnessRms === "number" ? features.loudnessRms.toFixed(3) : "—"}</span>
        </div>
        <div className="server-audio-feature-row">
          <label>响度 dB</label>
          <div className="server-progress alt" aria-hidden="true">
            <i style={{ width: `${barWidth(features.loudnessRms)}%` }} />
          </div>
          <span>{formatDb(features.loudnessDb)}</span>
        </div>
        <div className="server-audio-feature-row">
          <label>语音活动占比</label>
          <div className="server-progress" aria-hidden="true">
            <i style={{ width: `${barWidth(features.speechRatio)}%` }} />
          </div>
          <span>{typeof features.speechRatio === "number" ? `${Math.round(features.speechRatio * 100)}%` : "—"}</span>
        </div>
        <div className="server-audio-feature-row">
          <label>清晰度代理</label>
          <div className="server-progress alt" aria-hidden="true">
            <i style={{ width: `${barWidth(features.clarityProxy)}%` }} />
          </div>
          <span>{typeof features.clarityProxy === "number" ? features.clarityProxy.toFixed(2) : "—"}</span>
        </div>
      </div>
    </div>
  );
}
