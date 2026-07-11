import type { MonitorPreviewFrameMeta } from "child-education-training-demo/shared/monitor-preview";

type Props = {
  imageUrl: string | null;
  meta: MonitorPreviewFrameMeta | null;
  blur: boolean;
  stale: boolean;
  fallbackTags: Array<[string, string]>;
};

export function MonitorCameraCanvas({ imageUrl, meta, blur, stale, fallbackTags }: Props) {
  const frameWidth = meta?.width ?? 320;
  const frameHeight = meta?.height ?? 240;
  const faceBox = meta?.faceBox;

  return (
    <div className={`server-camera-preview server-camera-canvas-wrap ${blur ? "blurred" : ""} ${stale ? "stale" : "live"}`}>
      {imageUrl ? (
        <>
          <img
            src={imageUrl}
            alt="学员摄像头预览"
            className="server-camera-image"
            width={frameWidth}
            height={frameHeight}
          />
          {faceBox ? (
            <svg
              className="server-camera-overlay"
              viewBox={`0 0 ${frameWidth} ${frameHeight}`}
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <rect
                x={faceBox.x * frameWidth}
                y={faceBox.y * frameHeight}
                width={faceBox.width * frameWidth}
                height={faceBox.height * frameHeight}
                className="server-monitor-face-box"
              />
            </svg>
          ) : null}
          {faceBox ? (
            <div
              className="server-face-box-label"
              style={{
                left: `${faceBox.x * 100}%`,
                top: `${Math.max(0, faceBox.y * 100 - 6)}%`
              }}
            >
              {typeof meta?.attentionScore === "number" ? `专注 ${meta.attentionScore}` : "FACE"}
              {meta?.emotionLabel ? ` · ${meta.emotionLabel}` : ""}
            </div>
          ) : null}
        </>
      ) : (
        <div className="server-camera-placeholder">
          <div className="server-person" />
          <div className="server-face" />
          <p>{stale ? "等待 /child 推送预览帧（LAN 同 backend）…" : "加载预览…"}</p>
        </div>
      )}
      <div className="server-camera-tags">
        {fallbackTags.map(([label, tone]) => (
          <span key={label} className={`server-tag ${tone}`}>
            {label}
          </span>
        ))}
      </div>
      <p className="server-camera-footnote">内存预览 · TTL 3s · 不落盘 · 默认 4fps @ 320×240</p>
    </div>
  );
}
