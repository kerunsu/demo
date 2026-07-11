import { useCallback, useEffect, useRef, useState } from "react";
import type { MonitorPreviewFrameMeta } from "child-education-training-demo/shared/monitor-preview";
import { getLatestMonitorPreview, getMonitorPreviewConfig } from "../services/monitorPreviewClient";

export function useMonitorPreview(sessionId: string, enabled = true) {
  const [config, setConfig] = useState<{ enabled: boolean; pollMs: number }>({ enabled: false, pollMs: 250 });
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [meta, setMeta] = useState<MonitorPreviewFrameMeta | null>(null);
  const [stale, setStale] = useState(true);
  const objectUrlRef = useRef<string | null>(null);

  const revokeUrl = useCallback(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void getMonitorPreviewConfig()
      .then((previewConfig) => {
        const pollMs = Math.max(200, Math.round(1000 / Math.max(1, previewConfig.maxFps)));
        setConfig({ enabled: previewConfig.enabled, pollMs });
      })
      .catch(() => setConfig({ enabled: false, pollMs: 250 }));
  }, [enabled]);

  useEffect(() => {
    if (!enabled || !sessionId.trim() || !config.enabled) {
      revokeUrl();
      setImageUrl(null);
      setMeta(null);
      setStale(true);
      return;
    }

    let cancelled = false;
    const poll = async () => {
      try {
        const latest = await getLatestMonitorPreview(sessionId.trim());
        if (cancelled) return;
        if (!latest.available || !latest.imageBase64 || !latest.mimeType) {
          revokeUrl();
          setImageUrl(null);
          setMeta(latest.meta ?? null);
          setStale(Boolean(latest.stale));
          return;
        }
        const binary = atob(latest.imageBase64);
        const bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index += 1) {
          bytes[index] = binary.charCodeAt(index);
        }
        const blob = new Blob([bytes], { type: latest.mimeType });
        revokeUrl();
        const url = URL.createObjectURL(blob);
        objectUrlRef.current = url;
        setImageUrl(url);
        setMeta(latest.meta ?? null);
        setStale(Boolean(latest.stale));
      } catch {
        if (!cancelled) setStale(true);
      }
    };

    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, config.pollMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      revokeUrl();
    };
  }, [sessionId, enabled, config.enabled, config.pollMs, revokeUrl]);

  return {
    imageUrl,
    meta,
    stale,
    previewEnabled: config.enabled
  };
}
