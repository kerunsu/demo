import { useEffect, useMemo, useState } from "react";
import { apiRequest } from "../../services/api";

export type ScreenMirrorRole = "child" | "robot";

export interface ScreenMirrorFrame {
  type: "screen-mirror-frame";
  role: ScreenMirrorRole;
  sessionId: string;
  capturedAt: string;
  sequence: number;
  srcDoc: string;
}

const CHANNEL_NAME = "demo-robot-screen-mirror";
const BROADCAST_INTERVAL_MS = 350;
const STALE_AFTER_MS = 1800;
const BACKEND_UPLOAD_EVERY_N_FRAMES = 2;

function readSessionId() {
  return new URLSearchParams(window.location.search).get("sessionId") || window.localStorage.getItem("m3.activeSessionId") || "";
}

function readHeadAssets() {
  return Array.from(document.head.querySelectorAll('style, link[rel="stylesheet"]'))
    .map((node) => node.outerHTML)
    .join("\n");
}

function buildSrcDoc() {
  const width = Math.max(1, window.innerWidth);
  const height = Math.max(1, window.innerHeight);
  const scrollX = Math.max(0, window.scrollX);
  const scrollY = Math.max(0, window.scrollY);
  const headAssets = readHeadAssets();
  const bodyHtml = document.body.innerHTML;

  return `<!doctype html>
<html>
<head>
  <base href="${window.location.origin}/">
  ${headAssets}
  <style>
    html, body {
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden !important;
      pointer-events: none !important;
      background: #eef6fb;
    }
    #screen-mirror-viewport {
      position: absolute;
      left: 0;
      top: 0;
      width: ${width}px;
      height: ${height}px;
      overflow: hidden;
      transform-origin: top left;
      background: #fff;
    }
    #screen-mirror-viewport #root,
    #screen-mirror-viewport .app,
    #screen-mirror-viewport .robot-screen-shell,
    #screen-mirror-viewport .robot-screen-pure,
    #screen-mirror-viewport .robot-gif-stage,
    #screen-mirror-viewport .robot-gif-fullscreen,
    #screen-mirror-viewport .robot-face-shell-fullscreen {
      width: ${width}px !important;
      height: ${height}px !important;
      min-height: 0 !important;
      max-height: none !important;
    }
    #screen-mirror-viewport .robot-screen-pure {
      position: absolute !important;
      inset: 0 !important;
      padding: 0 !important;
      overflow: hidden !important;
    }
    #screen-mirror-viewport .robot-gif-fullscreen {
      object-fit: fill !important;
    }
    * {
      user-select: none !important;
    }
  </style>
</head>
<body>
  <div id="screen-mirror-viewport">${bodyHtml}</div>
  <script>
    const sourceWidth = ${width};
    const sourceHeight = ${height};
    const sourceScrollX = ${scrollX};
    const sourceScrollY = ${scrollY};
    const viewport = document.getElementById("screen-mirror-viewport");
    function fitMirrorViewport() {
      const scale = Math.min(window.innerWidth / sourceWidth, window.innerHeight / sourceHeight);
      const left = Math.max(0, (window.innerWidth - sourceWidth * scale) / 2);
      const top = Math.max(0, (window.innerHeight - sourceHeight * scale) / 2);
      viewport.style.transform = "translate(" + left + "px, " + top + "px) scale(" + scale + ")";
      window.scrollTo(sourceScrollX, sourceScrollY);
    }
    fitMirrorViewport();
    window.addEventListener("resize", fitMirrorViewport);
  </script>
</body>
</html>`;
}

export function useScreenMirrorSource(role: ScreenMirrorRole) {
  useEffect(() => {
    const channel = "BroadcastChannel" in window ? new BroadcastChannel(CHANNEL_NAME) : null;
    let sequence = 0;
    let disposed = false;
    let uploading = false;

    const publish = () => {
      if (disposed) return;
      const frame: ScreenMirrorFrame = {
        type: "screen-mirror-frame",
        role,
        sessionId: readSessionId(),
        capturedAt: new Date().toISOString(),
        sequence,
        srcDoc: buildSrcDoc()
      };
      sequence += 1;
      channel?.postMessage(frame);
      if (frame.sequence % BACKEND_UPLOAD_EVERY_N_FRAMES === 0 && !uploading) {
        uploading = true;
        uploadScreenMirrorFrame(frame)
          .catch(() => undefined)
          .finally(() => {
            uploading = false;
          });
      }
    };

    publish();
    const timer = window.setInterval(publish, BROADCAST_INTERVAL_MS);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      channel?.close();
    };
  }, [role]);
}

export function useScreenMirrorFrame(role: ScreenMirrorRole) {
  const [frame, setFrame] = useState<ScreenMirrorFrame | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const channel = "BroadcastChannel" in window ? new BroadcastChannel(CHANNEL_NAME) : null;
    const applyFrame = (next: ScreenMirrorFrame | null) => {
      if (next?.type === "screen-mirror-frame" && next.role === role) {
        setFrame((current) => {
          if (!current) return next;
          const currentTime = Date.parse(current.capturedAt);
          const nextTime = Date.parse(next.capturedAt);
          if (nextTime < currentTime) return current;
          if (nextTime === currentTime && next.sequence <= current.sequence) return current;
          return next;
        });
        setNow(Date.now());
      }
    };
    if (channel) {
      channel.onmessage = (event) => applyFrame(event.data as ScreenMirrorFrame);
    }
    const pollBackend = () => {
      void getLatestScreenMirrorFrame(role)
        .then(applyFrame)
        .catch(() => undefined);
    };
    pollBackend();
    const backendTimer = window.setInterval(pollBackend, 700);
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => {
      window.clearInterval(backendTimer);
      window.clearInterval(timer);
      channel?.close();
    };
  }, [role]);

  const stale = useMemo(() => {
    if (!frame) return true;
    return now - Date.parse(frame.capturedAt) > STALE_AFTER_MS;
  }, [frame, now]);

  return { frame, stale, supported: "BroadcastChannel" in window };
}

function uploadScreenMirrorFrame(frame: ScreenMirrorFrame) {
  return apiRequest<{ role: ScreenMirrorRole; sequence: number; receivedAt: string }>("/monitor/screen-frame", {
    method: "POST",
    body: JSON.stringify(frame)
  });
}

function getLatestScreenMirrorFrame(role: ScreenMirrorRole) {
  return apiRequest<(ScreenMirrorFrame & { receivedAt: string }) | null>(`/monitor/screen-frame/${role}/latest`);
}
