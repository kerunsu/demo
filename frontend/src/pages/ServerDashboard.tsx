import { useEffect, useMemo, useState } from "react";
import { MonitorCameraPanel } from "../features/monitor/MonitorCameraPanel";
import { MonitorQuestionChart } from "../features/monitor/MonitorQuestionChart";
import { MonitorVoicePipeline } from "../features/monitor/MonitorVoicePipeline";
import { MonitorAudioFeatures } from "../features/monitor/MonitorAudioFeatures";
import { MonitorAttentionChart } from "../features/monitor/MonitorAttentionChart";
import { useMonitorSession } from "../hooks/useMonitorSession";
import { SCREEN_ROUTES } from "../config/runtime";
import { getRawMediaConfig } from "../services/rawMediaService";
import type { RawMediaRuntimeConfig } from "child-education-training-demo/shared/raw-media";
import { useScreenMirrorFrame } from "../features/screenMirror/screenMirror";

function pct(value: number | undefined) {
  return `${Math.round((value ?? 0) * 100)}%`;
}

function ms(value: number | undefined) {
  if (typeof value !== "number") return "N/A";
  return `${Math.round(value)} ms`;
}

function formatDuration(msValue: number | undefined) {
  if (typeof msValue !== "number") return "00:00";
  const totalSeconds = Math.floor(msValue / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function statusClass(value: string | undefined) {
  const lower = (value ?? "").toLowerCase();
  if (lower.includes("fail") || lower.includes("error") || lower.includes("missing")) return "bad";
  if (lower.includes("degraded") || lower.includes("manual") || lower.includes("pending")) return "warn";
  return "good";
}

function formatBytes(value: number | undefined) {
  const bytes = value ?? 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function ServerDashboard() {
  const [sessionId, setSessionId] = useState("");
  const [blurPreview, setBlurPreview] = useState(false);
  const [mediaConfig, setMediaConfig] = useState<RawMediaRuntimeConfig | null>(null);
  const activeSessionId = useMemo(() => sessionId.trim(), [sessionId]);
  const childScreenUrl = useMemo(
    () => `${SCREEN_ROUTES.child}${activeSessionId ? `?sessionId=${activeSessionId}` : ""}`,
    [activeSessionId]
  );
  const robotScreenUrl = useMemo(
    () => `${SCREEN_ROUTES.robot}${activeSessionId ? `?sessionId=${activeSessionId}` : ""}`,
    [activeSessionId]
  );
  const childMirror = useScreenMirrorFrame("child");
  const robotMirror = useScreenMirrorFrame("robot");
  const { snapshot, error, wsStatus, refreshSource } = useMonitorSession(activeSessionId);
  const mediaEnabled = (mediaConfig?.persistence ?? snapshot?.media.rawMediaPersistence) === "enabled";
  const courseProgress = snapshot
    ? ((snapshot.course.currentQuestionIndex + 1) / Math.max(snapshot.course.totalQuestions, 1)) * 100
    : 0;

  useEffect(() => {
    void getRawMediaConfig()
      .then(setMediaConfig)
      .catch(() => setMediaConfig(null));
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const initialSessionId = params.get("sessionId") || window.localStorage.getItem("m3.activeSessionId") || "";
    setSessionId(initialSessionId);
  }, []);

  useEffect(() => {
    if (activeSessionId) return;
    const timer = window.setInterval(() => {
      const storedSessionId = window.localStorage.getItem("m3.activeSessionId") || "";
      if (storedSessionId) setSessionId(storedSessionId);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [activeSessionId]);

  return (
    <main className="server-dashboard">
      <header className="server-topbar">
        <div className="server-brand">
          <div className="server-logo">AI</div>
          <div>
            <h1>实时干预监控与分析控制台</h1>
            <p>
              {activeSessionId
                ? `Session ${activeSessionId} · ${snapshot?.session.childAlias ?? "学员"} · ${snapshot?.session.courseType ?? "训练"}`
                : "教育训练参考视图 · 请输入 sessionId 或从 /child 开始训练"}
            </p>
          </div>
        </div>
        <div className="server-actions">
          <span className={`server-badge ${wsStatus === "connected" ? "good" : "warn"}`}>
            <span className="server-dot" />
            {wsStatus === "connected" ? "WebSocket 在线" : `WebSocket ${wsStatus}`}
          </span>
          <span className="server-badge">刷新 {refreshSource === "ws" ? "事件驱动" : "轮询"}</span>
          <label className="server-session-input">
            Session
            <input value={sessionId} onChange={(event) => setSessionId(event.target.value)} placeholder="sess_..." />
          </label>
          <a className="server-btn" href={childScreenUrl}>
            打开 /child
          </a>
          <a className="server-btn" href={robotScreenUrl}>
            打开 /robot
          </a>
          {activeSessionId ? (
            <a className="server-btn server-btn-primary" href={`/?sessionId=${activeSessionId}#report`}>
              查看报告
            </a>
          ) : null}
        </div>
      </header>

      {error ? <div className="server-alert">Snapshot: {error}</div> : null}
      {!activeSessionId ? <div className="server-alert">请输入 sessionId，或先从 /child 开始训练（sessionId 会自动填入）。</div> : null}

      <section className="server-main-grid">
        <MonitorCameraPanel
          sessionId={activeSessionId}
          snapshot={snapshot}
          blurPreview={blurPreview}
          onBlurPreviewChange={setBlurPreview}
        />

        <article className="server-panel server-screen-panel">
          <div className="server-panel-head">
            <h2><span className="server-accent purple" />双屏实时状态预览</h2>
            <div className="server-panel-tools">
              <span className={`server-pill ${statusClass(snapshot?.session.state)}`}>{snapshot?.session.state ?? "NO_SESSION"}</span>
            </div>
          </div>
          <div className="server-screen-grid">
            <div className="server-screen-preview child">
              <div className="server-preview-bar">
                <span>儿童交互屏</span>
                <span className={`server-tag ${childMirror.frame && !childMirror.stale ? "good" : "warn"}`}>
                  {childMirror.frame ? (childMirror.stale ? "画面延迟" : "实时画面") : "等待画面"}
                </span>
              </div>
              <div className="server-preview-body">
                {childMirror.frame ? (
                  <iframe
                    className="server-screen-frame"
                    srcDoc={childMirror.frame.srcDoc}
                    title="儿童交互屏实时画面"
                    sandbox="allow-scripts"
                  />
                ) : (
                  <div className="server-screen-empty">
                    <div className="server-child-title">等待儿童端画面</div>
                    <div className="server-child-sub">
                      请保持真实 /child 页面打开，server 会接收它发来的实时画面。
                    </div>
                  </div>
                )}
              </div>
            </div>
            <div className="server-screen-preview robot">
              <div className="server-preview-bar">
                <span>机器人表情屏</span>
                <span className={`server-tag ${robotMirror.frame && !robotMirror.stale ? "good" : "warn"}`}>
                  {robotMirror.frame ? (robotMirror.stale ? "画面延迟" : "实时画面") : "等待画面"}
                </span>
              </div>
              <div className="server-preview-body robot-body">
                {robotMirror.frame ? (
                  <iframe
                    className="server-screen-frame"
                    srcDoc={robotMirror.frame.srcDoc}
                    title="机器人表情屏实时画面"
                    sandbox="allow-scripts"
                  />
                ) : (
                  <div className="server-screen-empty">
                    <div className="server-child-title">等待机器人端画面</div>
                    <div className="server-child-sub">
                      请保持真实 /robot 页面打开，server 会接收它发来的实时画面。
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
          {snapshot ? (
            <div className="server-screen-meta">
              <span>当前题目：{snapshot.course.currentQuestionPrompt ?? "等待题目"}</span>
              <span>进度：第 {snapshot.course.currentQuestionIndex + 1} / {snapshot.course.totalQuestions} 题</span>
              <span>当前题用时：{formatDuration(snapshot.course.currentQuestionElapsedMs)}</span>
              <span>课程进度：{Math.round(courseProgress)}%</span>
            </div>
          ) : null}
        </article>

        <article className="server-panel server-voice-panel">
          <div className="server-panel-head">
            <h2><span className="server-accent green" />语音识别与回答流水线</h2>
            <span className="server-pill">{ms(snapshot?.voice.totalTurnLatencyMs)}</span>
          </div>
          <MonitorAudioFeatures snapshot={snapshot} />
          <MonitorVoicePipeline snapshot={snapshot} />
          <div className="server-text-grid">
            <div className="server-text-card">
              <label>识别文本</label>
              <p>{snapshot?.voice.latestTranscriptPreview ?? "无原文记录（仅 hash/长度）"}</p>
            </div>
            <div className="server-text-card">
              <label>脱敏后的模型输入</label>
              <p>{snapshot?.voice.latestModelInputPreview ?? "等待输入"}</p>
            </div>
            <div className="server-text-card answer">
              <label>最终回答</label>
              <p>{snapshot?.voice.latestReplyPreview ?? "等待回复"}</p>
            </div>
          </div>
        </article>

        <article className="server-panel server-analytics-panel">
          <div className="server-panel-head">
            <h2><span className="server-accent yellow" />实时分析趋势</h2>
            <span className="server-pill">逐题窗口</span>
          </div>
          <div className="server-analytics-grid">
            <MonitorAttentionChart snapshot={snapshot} />
            <MonitorQuestionChart snapshot={snapshot} />
            <div className="server-chart-card compact">
              <div className="server-chart-title">
                <span>语音流水线耗时</span>
                <span>{ms(snapshot?.voice.totalTurnLatencyMs)}</span>
              </div>
              <div className="server-kpi-stack">
                <div><label>平均响应</label><strong>{ms(snapshot?.course.averageResponseTimeMs)}</strong></div>
                <div><label>课程正确率</label><strong>{pct(snapshot?.course.accuracy)}</strong></div>
                <div><label>课程时长</label><strong>{formatDuration(snapshot?.course.sessionDurationMs)}</strong></div>
              </div>
            </div>
          </div>
        </article>

        <div className="server-side-lower">
          <article className="server-panel server-metrics-panel">
            <div className="server-panel-head">
              <h2><span className="server-accent" />课程实时指标</h2>
              <span className="server-pill good">{snapshot?.session.courseType ?? "course"}</span>
            </div>
            <div className="server-metrics-grid">
              <div className="server-kpi"><label>正确率</label><strong>{pct(snapshot?.course.accuracy)}</strong></div>
              <div className="server-kpi"><label>题目进度</label><strong>{snapshot ? `${snapshot.course.currentQuestionIndex + 1}/${snapshot.course.totalQuestions}` : "N/A"}</strong></div>
              <div className="server-kpi"><label>平均响应</label><strong>{ms(snapshot?.course.averageResponseTimeMs)}</strong></div>
              <div className="server-kpi"><label>当前题用时</label><strong>{formatDuration(snapshot?.course.currentQuestionElapsedMs)}</strong></div>
            </div>
          </article>

          <article className="server-panel server-media-panel">
            <div className="server-panel-head">
              <h2><span className="server-accent purple" />原始媒体保存</h2>
              <span className={`server-pill ${mediaEnabled ? "good" : "warn"}`}>
                {mediaConfig?.persistence ?? snapshot?.media.rawMediaPersistence ?? "disabled"}
              </span>
            </div>
            <div className="server-metrics-grid media">
              <div className="server-kpi"><label>视频流</label><strong>{snapshot?.media.videoStreamCount ?? 0}</strong></div>
              <div className="server-kpi"><label>音频回合</label><strong>{snapshot?.media.audioTurnCount ?? 0}</strong></div>
              <div className="server-kpi"><label>已保存</label><strong>{formatBytes(snapshot?.media.totalPersistedBytes)}</strong></div>
              <div className="server-kpi"><label>consent</label><strong>{snapshot?.media.consentRecorded ? "已记录" : "未记录"}</strong></div>
            </div>
            {mediaEnabled && activeSessionId && !snapshot?.media.consentRecorded ? (
              <p className="server-media-hint">请从 /child 重新开始训练以写入 consent。</p>
            ) : null}
          </article>

          <article className="server-panel server-events-panel">
            <div className="server-panel-head">
              <h2><span className="server-accent yellow" />事件时间线与告警</h2>
              <span className="server-pill warn">camera stream: MANUAL</span>
            </div>
            <div className="server-events-list">
              {(snapshot?.events ?? []).map((event) => (
                <div key={event.id} className={`server-event ${event.severity}`}>
                  <time>{new Date(event.at).toLocaleTimeString()}</time>
                  <span className="server-event-dot" />
                  <div>
                    <span className="server-event-type">{event.type}</span>
                    <p>{event.detail ?? event.message}</p>
                  </div>
                </div>
              ))}
            </div>
          </article>
        </div>
      </section>

      <footer className="server-footer">
        {snapshot
          ? Object.entries(snapshot.health).map(([key, value]) => (
              <span key={key} className={statusClass(value)}>
                {key}: {value}
              </span>
            ))
          : <span>backend: waiting</span>}
      </footer>
    </main>
  );
}
