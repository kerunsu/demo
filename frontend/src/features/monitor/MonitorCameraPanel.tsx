import { useState } from "react";
import { AttentionGauge } from "./AttentionGauge";
import { MonitorCameraCanvas } from "./MonitorCameraCanvas";
import { useMonitorPreview } from "../../hooks/useMonitorPreview";
import type { MonitorSnapshot } from "../../services/monitorService";

type Props = {
  sessionId: string;
  snapshot: MonitorSnapshot | null;
  blurPreview: boolean;
  onBlurPreviewChange: (value: boolean) => void;
};

function pct(value: number | undefined) {
  return `${Math.round((value ?? 0) * 100)}%`;
}

function statusClass(value: string | undefined) {
  const lower = (value ?? "").toLowerCase();
  if (lower.includes("fail") || lower.includes("error") || lower.includes("missing")) return "bad";
  if (lower.includes("degraded") || lower.includes("manual") || lower.includes("pending")) return "warn";
  return "good";
}

function attentionStatusLabel(features: {
  facePresent?: boolean;
  roughlyFacingScreen?: boolean;
  headOrientation?: string;
  faceCount?: number;
  imageQuality?: string;
  facingScore?: number;
} | undefined): Array<[string, string]> {
  if (!features) return [["等待摄像头 descriptor", "warn"]];
  const tags: Array<[string, string]> = [];
  tags.push([features.facePresent ? "人脸存在" : "未检测到人脸", features.facePresent ? "good" : "bad"]);
  if (typeof features.facingScore === "number") {
    tags.push([`朝向得分 ${(features.facingScore * 100).toFixed(0)}`, features.facingScore >= 0.55 ? "good" : "warn"]);
  } else if (typeof features.roughlyFacingScreen === "boolean") {
    tags.push([features.roughlyFacingScreen ? "朝向屏幕" : "视线偏离", features.roughlyFacingScreen ? "good" : "warn"]);
  }
  if (features.headOrientation && features.headOrientation !== "unknown") {
    tags.push([`头部 ${features.headOrientation}`, features.headOrientation === "screen" ? "good" : "warn"]);
  }
  if (typeof features.faceCount === "number") {
    tags.push([`${features.faceCount} 人`, features.faceCount === 1 ? "good" : "warn"]);
  }
  if (features.imageQuality) {
    const good = features.imageQuality === "good";
    tags.push([good ? "画面质量良好" : `画面：${features.imageQuality}`, good ? "good" : "warn"]);
  }
  return tags;
}

function dominantEmotionLabel(snapshot: MonitorSnapshot | null) {
  const emotion = snapshot?.emotion;
  if (!emotion) return "等待情绪";
  const entries: Array<[string, number]> = [
    ["愉悦", emotion.positiveRatio ?? 0],
    ["专注", emotion.focusedRatio ?? 0],
    ["急躁", emotion.frustratedRatio ?? 0]
  ];
  const top = entries.sort((left, right) => right[1] - left[1])[0];
  if (!top || top[1] <= 0) return emotion.degraded ? "情绪降级" : "无信号";
  return `主导：${top[0]} ${pct(top[1])}`;
}

export function MonitorCameraPanel({ sessionId, snapshot, blurPreview, onBlurPreviewChange }: Props) {
  const [engineeringOpen, setEngineeringOpen] = useState(false);
  const { imageUrl, meta, stale, previewEnabled } = useMonitorPreview(sessionId, Boolean(sessionId.trim()));
  const attentionTags = attentionStatusLabel(snapshot?.attention.features);
  const attentionProviderLive =
    snapshot?.attention.currentProvider === "local-browser-face-attention" &&
    snapshot?.attention.algorithmVersion === "browser-attention-v2";

  return (
    <article className="server-panel server-camera-panel">
      <div className="server-panel-head">
        <h2>
          <span className="server-accent" />
          实时摄像头与注意力
        </h2>
        <div className="server-panel-tools">
          <label className="server-switch">
            <input type="checkbox" checked={blurPreview} onChange={(event) => onBlurPreviewChange(event.target.checked)} />
            画面模糊
          </label>
          <span className={`server-pill ${previewEnabled ? (stale ? "warn" : "good") : "warn"}`}>
            {previewEnabled ? (stale ? "预览等待" : "预览在线") : "预览关闭"}
          </span>
        </div>
      </div>

      <MonitorCameraCanvas
        imageUrl={imageUrl}
        meta={meta}
        blur={blurPreview}
        stale={stale}
        fallbackTags={attentionTags}
      />

      <div className="server-gauge-row">
        <AttentionGauge score={snapshot?.attention.currentScore} />
        <div className="server-camera-side">
          <div className="server-emotion-strip">
            <span className="server-emotion-strip-label">情绪</span>
            <span className="server-emotion-strip-value">{dominantEmotionLabel(snapshot)}</span>
            {snapshot?.emotion?.degraded ? <span className="server-pill warn">降级</span> : null}
          </div>
          <dl className="server-meta-grid server-meta-grid-compact">
            <div>
              <dt>本题关注比例</dt>
              <dd>
                {typeof snapshot?.attention.questionAttentionRatio === "number"
                  ? `${snapshot.attention.questionAttentionRatio}%`
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>数据质量</dt>
              <dd className={statusClass(snapshot?.attention.currentQuality)}>{snapshot?.attention.currentQuality ?? "MISSING"}</dd>
            </div>
          </dl>
        </div>
      </div>

      <details
        className="server-engineering-details"
        open={engineeringOpen}
        onToggle={(event) => setEngineeringOpen(event.currentTarget.open)}
      >
        <summary>工程信息</summary>
        <dl className="server-meta-grid server-meta-grid-engineering">
          <div>
            <dt>注意力 Provider</dt>
            <dd className="server-truncate" title={snapshot?.attention.currentProvider ?? "—"}>
              {snapshot?.attention.currentProvider ?? "—"}
            </dd>
          </div>
          <div>
            <dt>算法版本</dt>
            <dd className="server-truncate" title={snapshot?.attention.algorithmVersion ?? "—"}>
              {snapshot?.attention.algorithmVersion ?? "—"}
            </dd>
          </div>
          <div>
            <dt>情绪 Provider</dt>
            <dd className="server-truncate" title={snapshot?.emotion?.provider ?? snapshot?.emotion?.configuredProvider ?? "—"}>
              {snapshot?.emotion?.provider ?? snapshot?.emotion?.configuredProvider ?? "—"}
            </dd>
          </div>
          <div>
            <dt>预览通道</dt>
            <dd>{attentionProviderLive ? "browser-attention-v2 + preview" : "descriptor / mock"}</dd>
          </div>
        </dl>
      </details>
    </article>
  );
}
