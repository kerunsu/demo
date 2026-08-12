/**
 * Server 监控台：1s Snapshot + 远端预览快通道 + 环境摄像头 + 报告审核
 * 依赖 common.js 的全局 socket
 */
(function () {
  const POLL_MS = 1000;
  const REMOTE_PREVIEW_MS = 250;
  const AMBIENT_PREVIEW_MS = 100;
  const VIEW_KEY = "server.view";

  const els = {
    tabs: document.querySelectorAll(".view-tab"),
    viewConfig: document.getElementById("view-config"),
    viewMonitor: document.getElementById("view-monitor"),
    configActions: document.getElementById("config-header-actions"),
    monitorActions: document.getElementById("monitor-header-actions"),
    grid: document.getElementById("mon-grid"),
    badgeSocket: document.getElementById("mon-badge-socket"),
    badgeRefresh: document.getElementById("mon-badge-refresh"),
    badgeMode: document.getElementById("mon-badge-mode"),
    badgeAnalyzer: document.getElementById("mon-badge-analyzer"),
    badgeAgent: document.getElementById("mon-badge-agent"),
    badgePreview: document.getElementById("mon-badge-preview"),
    stopRobot: document.getElementById("mon-btn-pause"),
    stopAudio: document.getElementById("mon-btn-mute"),
    controlFeedback: document.getElementById("mon-control-feedback"),
    preview: document.getElementById("mon-preview"),
    previewPlaceholder: document.getElementById("mon-preview-placeholder"),
    previewImg: document.getElementById("mon-preview-img"),
    previewStale: document.getElementById("mon-preview-stale"),
    ambientGrid: document.getElementById("mon-ambient-grid"),
    ambientEmpty: document.getElementById("mon-ambient-empty"),
    pendingBtn: document.getElementById("mon-pending-btn"),
    pendingCount: document.getElementById("mon-pending-count"),
    pendingPanel: document.getElementById("mon-pending-panel"),
    pendingList: document.getElementById("mon-pending-list"),
    pendingOpen: document.getElementById("mon-pending-open"),
    reviewModal: document.getElementById("mon-review-modal"),
    reviewMeta: document.getElementById("mon-review-meta"),
    reviewWarn: document.getElementById("mon-review-warn"),
    reviewPublish: document.getElementById("mon-review-publish"),
    reviewEdit: document.getElementById("mon-review-edit"),
    events: document.getElementById("mon-events"),
    attnScore: document.getElementById("mon-attn-score"),
    attnQuality: document.getElementById("mon-attn-quality"),
    attnRatio: document.getElementById("mon-attn-ratio"),
    attnSamples: document.getElementById("mon-attn-samples"),
    attnProvider: document.getElementById("mon-attn-provider"),
    sessionStatus: document.getElementById("mon-session-status"),
    courseTitle: document.getElementById("mon-course-title"),
    courseSub: document.getElementById("mon-course-sub"),
    humanDir: document.getElementById("mon-human-dir"),
    serverOnline: document.getElementById("mon-server-online"),
    teacherOnline: document.getElementById("mon-teacher-online"),
    serverSummary: document.getElementById("mon-server-summary"),
    serverDetail: document.getElementById("mon-server-detail"),
    teacherSummary: document.getElementById("mon-teacher-summary"),
    teacherDetail: document.getElementById("mon-teacher-detail"),
    teacherConnections: document.getElementById("mon-teacher-connections"),
    childSummary: document.getElementById("mon-child-summary"),
    childDetail: document.getElementById("mon-child-detail"),
    runtimeSummary: document.getElementById("mon-runtime-summary"),
    runtimeDetail: document.getElementById("mon-runtime-detail"),
    connectionIssues: document.getElementById("mon-connection-issues"),
    childOnline: document.getElementById("mon-child-online"),
    robotOnline: document.getElementById("mon-robot-online"),
    robotState: document.getElementById("mon-robot-state"),
    robotCommand: document.getElementById("mon-robot-command"),
    robotTargets: document.getElementById("mon-robot-targets"),
    voiceActive: document.getElementById("mon-voice-active"),
    voiceTranscript: document.getElementById("mon-voice-transcript"),
    voiceMatch: document.getElementById("mon-voice-match"),
    voiceExpressive: document.getElementById("mon-voice-expressive"),
    mediaSession: document.getElementById("mon-media-session"),
    chart: document.getElementById("mon-attn-chart"),
    emoPos: document.getElementById("mon-emo-pos"),
    emoNeu: document.getElementById("mon-emo-neu"),
    emoNeg: document.getElementById("mon-emo-neg"),
    emoLabel: document.getElementById("mon-emo-label"),
    limitations: document.getElementById("mon-limitations"),
  };

  const state = {
    view: "config",
    pollTimer: null,
    remotePreviewTimer: null,
    ambientPreviewTimer: null,
    fetching: false,
    lastSource: "—",
    socketOnline: false,
    mediaSessionId: null,
    trainingSessionId: null,
    active: false,
    previewEnabled: true,
    ambientCameras: [],
    pendingReviews: [],
    reviewDismissed: {},
    currentReviewId: null,
  };

  const SOCKET_REFRESH_EVENTS = [
    "play_resource",
    "attention_update",
    "camera_analysis",
    "training_prepare",
    "prepare_training_ack",
    "finalize_training",
    "finalize_training_ack",
    "session_ended",
    "client_presence",
    "readiness_update",
    "readiness_complete",
    "speech_match",
    "analysis_result",
  ];

  function setView(view) {
    if (view === "config") {
      window.location.replace("/server/config/overview");
      return;
    }
    state.view = "monitor";
    try {
      localStorage.setItem(VIEW_KEY, "monitor");
    } catch (_) {}

    if (els.viewMonitor) {
      els.viewMonitor.classList.remove("hidden");
      els.viewMonitor.setAttribute("aria-hidden", "false");
    }
    if (els.monitorActions) els.monitorActions.classList.remove("hidden");

    startPolling();
    fetchSnapshot("poll");
  }

  function startPolling() {
    stopPolling();
    state.pollTimer = setInterval(() => {
      if (document.hidden) return;
      fetchSnapshot("poll");
    }, POLL_MS);
    startRemotePreviewLoop();
  }

  function stopPolling() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
    stopRemotePreviewLoop();
  }

  function startRemotePreviewLoop() {
    stopRemotePreviewLoop();
    state.remotePreviewTimer = setInterval(() => {
      if (document.hidden || state.view !== "monitor") return;
      pollRemotePreview();
    }, REMOTE_PREVIEW_MS);
  }

  function stopRemotePreviewLoop() {
    if (state.remotePreviewTimer) {
      clearInterval(state.remotePreviewTimer);
      state.remotePreviewTimer = null;
    }
  }

  function startAmbientPreviewLoop() {
    if (state.ambientPreviewTimer) return;
    state.ambientPreviewTimer = setInterval(() => {
      if (document.hidden || state.view !== "monitor") return;
      pollAmbientPreview();
    }, AMBIENT_PREVIEW_MS);
  }

  function stopAmbientPreviewLoop() {
    if (state.ambientPreviewTimer) {
      clearInterval(state.ambientPreviewTimer);
      state.ambientPreviewTimer = null;
    }
  }

  async function pollRemotePreview() {
    if (!state.previewEnabled) return;
    const q = state.mediaSessionId
      ? "?mediaSessionId=" + encodeURIComponent(state.mediaSessionId) + "&t=" + Date.now()
      : "?t=" + Date.now();
    try {
      const res = await fetch("/api/monitor/remote-preview.jpg" + q, { cache: "no-store" });
      if (!res.ok || res.status === 204) {
        if (els.badgePreview && !state.active) {
          /* keep last badge from snapshot */
        }
        return;
      }
      const blob = await res.blob();
      if (!blob || !blob.size) return;
      const url = URL.createObjectURL(blob);
      if (els.previewImg) {
        const old = els.previewImg.src;
        els.previewImg.src = url;
        els.previewImg.classList.remove("hidden");
        if (old && old.indexOf("blob:") === 0) {
          try { URL.revokeObjectURL(old); } catch (_) {}
        }
      }
      if (els.previewPlaceholder) els.previewPlaceholder.classList.add("hidden");
      if (els.previewStale) els.previewStale.classList.add("hidden");
      if (els.badgePreview) {
        els.badgePreview.textContent = "预览 · 快通道";
        els.badgePreview.classList.add("ok");
        els.badgePreview.classList.remove("warn");
      }
    } catch (_) {}
  }

  async function pollAmbientPreview() {
    await Promise.all(state.ambientCameras.map(async (camera) => {
      const deviceId = String(camera.deviceId || "");
      if (!deviceId) return;
      try {
        const urlPath = "/api/monitor/ambient/preview.jpg?deviceId=" +
          encodeURIComponent(deviceId) + "&t=" + Date.now();
        const res = await fetch(urlPath, { cache: "no-store" });
        if (!res.ok || res.status === 204) return;
        const blob = await res.blob();
        if (!blob || !blob.size) return;
        const img = els.ambientGrid && els.ambientGrid.querySelector(
          '[data-camera-img="' + CSS.escape(deviceId) + '"]'
        );
        const placeholder = els.ambientGrid && els.ambientGrid.querySelector(
          '[data-camera-placeholder="' + CSS.escape(deviceId) + '"]'
        );
        if (!img) return;
        const objectUrl = URL.createObjectURL(blob);
        const old = img.src;
        img.src = objectUrl;
        img.classList.remove("hidden");
        if (placeholder) placeholder.classList.add("hidden");
        if (old && old.indexOf("blob:") === 0) {
          try { URL.revokeObjectURL(old); } catch (_) {}
        }
      } catch (_) {}
    }));
  }

  async function fetchSnapshot(source) {
    if (state.view !== "monitor" || state.fetching) return;
    state.fetching = true;
    try {
      const res = await fetch("/api/monitor/snapshot", { cache: "no-store" });
      const json = await res.json();
      if (!json || !json.success) {
        renderError(json && json.error ? json.error : "snapshot_failed");
        return;
      }
      state.lastSource = source || "poll";
      renderSnapshot(json.data || {});
    } catch (err) {
      renderError(String(err && err.message ? err.message : err));
    } finally {
      state.fetching = false;
      updateBadges();
    }
  }

  function updateBadges() {
    if (els.badgeSocket) {
      els.badgeSocket.textContent = state.socketOnline ? "Socket · 在线" : "Socket · 离线";
      els.badgeSocket.classList.toggle("ok", state.socketOnline);
      els.badgeSocket.classList.toggle("warn", !state.socketOnline);
    }
    if (els.badgeRefresh) {
      els.badgeRefresh.textContent = "刷新 · " + state.lastSource;
    }
  }

  function qualityClass(q) {
    const u = String(q || "").toUpperCase();
    if (u === "VALID" || u === "COMPLETE") return "good";
    if (u === "DEGRADED" || u === "LOW_CONFIDENCE") return "warn";
    return "bad";
  }

  function fmtRatio(r) {
    if (r == null || Number.isNaN(Number(r))) return "—";
    return (Number(r) * 100).toFixed(0) + "%";
  }

  function renderError(msg) {
    if (els.empty) {
      els.empty.classList.remove("hidden");
      els.empty.querySelector("strong").textContent = "Snapshot 获取失败";
      els.empty.querySelector("p").textContent = msg;
    }
    if (els.grid) els.grid.classList.add("dimmed");
  }

  function renderTeacherConnections(connections) {
    const container = els.teacherConnections;
    if (!container) return;
    container.innerHTML = "";
    const teacherItems = Array.isArray((connections || {}).teacher) ? connections.teacher : [];
    if (!teacherItems.length) return;

    const title = document.createElement("div");
    title.className = "mon-conn-title";
    title.textContent = "连接明细";
    container.appendChild(title);

    teacherItems.forEach((item) => {
      const row = document.createElement("div");
      row.className = "mon-conn-row";

      const label = document.createElement("span");
      label.className = "mon-conn-label";
      label.textContent = `IP ${item.ip || "未知"}`;

      const meta = document.createElement("span");
      meta.className = "mon-conn-meta";
      const ua = String(item.userAgent || "");
      const shortUa = ua.length > 28 ? ua.slice(0, 28) + "…" : ua || "未知浏览器";
      const ageSec = Math.round((item.ageMs || 0) / 1000);
      const connectedAt = item.connectedAtMs ? new Date(item.connectedAtMs).toLocaleTimeString() : "—";
      meta.textContent = `${shortUa} · ${connectedAt} · ${ageSec}s前心跳`;

      const state = document.createElement("span");
      state.className = "mon-conn-state " + (item.isController ? "good" : "warn");
      state.textContent = item.isController ? "控制中" : "只读";

      const button = document.createElement("button");
      button.type = "button";
      button.className = "mon-conn-kill";
      button.textContent = "终止";
      button.disabled = item.isController || false;
      button.title = item.isController ? "当前控制连接不可终止，请在教师端点击「接管」后再操作" : "断开此连接";
      button.addEventListener("click", async () => {
        if (!confirm(`确定终止这条教师连接吗？\nIP: ${item.ip || "未知"}\n${shortUa}`)) return;
        try {
          const response = await fetch("/api/monitor/teacher-connections/disconnect", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sid: item.sid }),
          });
          const result = await response.json();
          if (!response.ok || !result.success) {
            alert("终止失败：" + (result.error || response.status));
            return;
          }
          if (window.MonitorRefresh) window.MonitorRefresh();
        } catch (err) {
          alert("终止失败：" + err.message);
        }
      });

      row.appendChild(label);
      row.appendChild(meta);
      row.appendChild(state);
      row.appendChild(button);
      container.appendChild(row);
    });
  }

  function renderConnectionSummary(summary) {
    const cards = Array.isArray(summary.cards) ? summary.cards : [];
    const byId = Object.fromEntries(cards.map((card) => [card.id, card]));
    const targets = {
      server: [els.serverOnline, els.serverSummary, els.serverDetail],
      teacher: [els.teacherOnline, els.teacherSummary, els.teacherDetail],
      child: [els.childOnline, els.childSummary, els.childDetail],
      runtime: [els.robotOnline, els.runtimeSummary, els.runtimeDetail],
    };
    Object.entries(targets).forEach(([id, nodes]) => {
      const card = byId[id];
      if (!card) return;
      const [tag, summaryEl, detailEl] = nodes;
      if (tag) {
        tag.textContent = card.level === "ok" ? "正常" : card.level === "warn" ? "需注意" : "未连接";
        tag.className = "mon-tag " + (card.level === "ok" ? "good" : card.level === "warn" ? "warn" : "bad");
      }
      if (summaryEl) summaryEl.textContent = card.summary || "状态未知";
      if (detailEl) detailEl.textContent = card.detail || "";
      const root = summaryEl && summaryEl.closest(".mon-screen-card");
      if (root) {
        root.classList.toggle("connection-error", card.level === "error");
        root.classList.toggle("connection-warn", card.level === "warn");
      }
    });
    if (els.connectionIssues) {
      const issues = Array.isArray(summary.issues) ? summary.issues : [];
      els.connectionIssues.innerHTML = "";
      const items = issues.length ? issues : [{ problem: "三端关键连接正常，当前没有需要处理的问题。", action: "" }];
      items.forEach((issue) => {
        const li = document.createElement("li");
        li.textContent = issue.problem + (issue.action ? " 建议：" + issue.action : "");
        els.connectionIssues.appendChild(li);
      });
    }
  }

  function renderSnapshot(data) {
    updateBadges();
    const health = data.health || {};
    if (els.badgeMode) {
      els.badgeMode.textContent = "采集 · " + (
        health.mediaMode === "browser" ? "儿童端浏览器" :
        health.mediaMode === "agent" ? "机器人采集程序" : "未配置"
      );
    }
    if (els.badgeAnalyzer) {
      const a = health.analyzers || {};
      els.badgeAnalyzer.textContent = "分析 · " + (
        String(a.attention || "").toLowerCase() === "mock" ||
        String(a.speech || "").toLowerCase() === "mock"
          ? "含演示数据，不能用于正式报告" : "真实数据"
      );
      const mock =
        String(a.attention || "").toLowerCase() === "mock" ||
        String(a.speech || "").toLowerCase() === "mock";
      els.badgeAnalyzer.classList.toggle("warn", mock);
      els.badgeAnalyzer.classList.toggle("ok", !mock);
    }
    if (els.badgeAgent) {
      const online = !!(health.childAgentOnline || health.mediaAgentOnline);
      els.badgeAgent.textContent = online ? "Agent · 在线" : "Agent · 离线";
      els.badgeAgent.classList.toggle("ok", online);
      els.badgeAgent.classList.toggle("warn", !online);
    }

    // Connection diagnostics and configured camera previews remain useful
    // before a class starts, so the monitor no longer has an inactive overlay.
    if (els.grid) els.grid.classList.remove("dimmed");

    const session = data.session || {};
    const course = data.course || {};
    const attn = data.attention || {};
    const voice = data.voice || {};
    const emotion = data.emotion || {};
    const robot = data.robot || {};
    const clients = health.socketClients || {};
    renderConnectionSummary(health.connectionSummary || {});
    renderTeacherConnections(health.connections);

    if (els.attnScore) {
      const q = String(attn.currentQuality || "").toUpperCase();
      if (attn.currentScore == null || q === "MISSING") {
        els.attnScore.textContent = "—";
        els.attnScore.title = "无有效样本（MISSING 不计为低分）";
      } else {
        els.attnScore.textContent = Math.round(Number(attn.currentScore));
        els.attnScore.title = "";
      }
    }
    if (els.attnQuality) {
      els.attnQuality.textContent = attn.currentQuality || "MISSING";
      els.attnQuality.className = "mon-tag " + qualityClass(attn.currentQuality);
    }
    if (els.attnRatio) els.attnRatio.textContent = fmtRatio(attn.questionAttentionRatio);
    if (els.attnSamples) els.attnSamples.textContent = String(attn.sampleCount ?? "—");
    if (els.attnProvider) els.attnProvider.textContent = attn.provider || "—";
    if (els.sessionStatus) els.sessionStatus.textContent = session.status || "—";

    if (els.courseTitle) els.courseTitle.textContent = course.title || "—";
    if (els.courseSub) {
      const idx = course.questionIndex != null ? course.questionIndex + 1 : "—";
      const total = course.questionTotal != null ? course.questionTotal : "?";
      const elapsed = course.questionElapsedSec != null ? course.questionElapsedSec + "s" : "—";
      els.courseSub.textContent =
        (course.courseType || "—") +
        " · 第 " +
        idx +
        " / " +
        total +
        " 题 · 本题用时 " +
        elapsed;
    }
    if (els.humanDir) {
      els.humanDir.textContent =
        "录像目录：" + (session.humanDirName || "尚未开始录像");
    }
    if (els.mediaSession) {
      els.mediaSession.textContent = "mediaSession · " + (session.mediaSessionId || "—");
    }

    if (els.childOnline && !health.connectionSummary) {
      const n = Number(clients.child || 0);
      els.childOnline.textContent = n > 0 ? "在线 (" + n + ")" : "离线";
      els.childOnline.className = "mon-tag " + (n > 0 ? "good" : "bad");
    }
    if (els.robotOnline && !health.connectionSummary) {
      els.robotOnline.textContent = robot.online ? "在线" : "未知/离线";
      els.robotOnline.className = "mon-tag " + (robot.online ? "good" : "warn");
    }
    if (els.robotState) {
      const command = robot.lastCommand || {};
      els.robotState.textContent =
        (robot.busy && robot.busy.busy ? "机器人正在执行交互。" : "机器人当前空闲。") +
        (robot.audioPlaying ? " 声音正在播放。" : " 当前没有声音播放。") +
        (command.phase === "failed" ? " 最近一次交互执行失败。" : "");
    }
    if (els.stopAudio) {
      els.stopAudio.disabled = !session.mediaSessionId;
      els.stopAudio.title = session.mediaSessionId
        ? "停止会话 " + session.mediaSessionId + " 的当前声音"
        : "当前没有可定位的运行会话";
    }
    if (els.robotCommand) {
      const command = robot.lastCommand || {};
      const actual = [command.motion, command.emotion].filter(Boolean).join(" + ") || "无输出";
      const error = command.error ? " · 错误：" + command.error : "";
      els.robotCommand.textContent = command.commandId
        ? "最近一次交互：" + (command.message || command.phase || "状态未知") + "；执行内容：" + actual + error
        : "还没有执行过机器人交互。";
      els.robotCommand.className = "mon-muted " + (
        command.phase === "failed" ? "bad" : command.phase === "degraded" ? "warn" : command.phase === "completed" ? "good" : ""
      );
    }
    if (els.robotTargets) {
      const targets = robot.targets || {};
      els.robotTargets.textContent = targets.robotDisplayOnline
        ? "机器人表情显示已连接。"
        : "机器人表情显示未连接；动作可能执行但屏幕不会同步。";
    }

    if (els.voiceActive) {
      els.voiceActive.textContent = voice.pipelineActive ? "收声 · 活跃" : "收声 · 空闲";
      els.voiceActive.className = "mon-tag " + (voice.pipelineActive ? "good" : "warn");
    }
    if (els.voiceTranscript) {
      els.voiceTranscript.textContent = voice.lastTranscript || "（无转录）";
    }
    if (els.voiceMatch) {
      if (voice.lastMatchOk == null) els.voiceMatch.textContent = "（无匹配记录）";
      else els.voiceMatch.textContent = voice.lastMatchOk ? "曾匹配成功" : "尚未匹配成功";
    }
    if (els.voiceExpressive) {
      const ex = voice.expressive || {};
      els.voiceExpressive.textContent = ex.speechRatio == null
        ? "暂未收到可用的语音样本。"
        : "已收到语音样本，孩子发声占比约 " + Math.round(Number(ex.speechRatio) * 100) + "% 。";
    }

    renderChart(attn.recentSamples || []);
    renderEmotion(emotion);
    renderPreview(data.preview || {});
    renderAmbient(data.ambient || {});
    renderEvents(data.events || []);
    const limLabels = health.limitationLabels || health.limitations || [];
    renderLimitations(limLabels);

    state.active = !!data.active;
    state.mediaSessionId = (session && session.mediaSessionId) || null;
    state.trainingSessionId = (session && session.trainingSessionId) || null;
    state.previewEnabled = !!(data.preview && data.preview.enabled !== false);

    if (els.badgePreview) {
      const pv = data.preview || {};
      if (!pv.enabled) {
        els.badgePreview.textContent = "预览 · 关闭";
        els.badgePreview.classList.add("warn");
        els.badgePreview.classList.remove("ok");
      } else if (!state.mediaSessionId && !pv.jpegBase64) {
        els.badgePreview.textContent = "预览 · 无帧";
        els.badgePreview.classList.add("warn");
        els.badgePreview.classList.remove("ok");
      }
    }

    refreshPendingReviews();
  }

  function renderPreview(preview) {
    // Snapshot 内嵌帧仅作兜底；正常由 remote-preview 快通道刷新
    const hasFrame = !!(preview && preview.enabled && preview.jpegBase64);
    if (els.previewPlaceholder && !(els.previewImg && els.previewImg.getAttribute('src'))) {
      els.previewPlaceholder.classList.toggle("hidden", hasFrame);
      if (!hasFrame) {
        const strong = els.previewPlaceholder.querySelector("strong");
        const span = els.previewPlaceholder.querySelector("span");
        if (!preview || !preview.enabled) {
          if (strong) strong.textContent = "预览未启用";
          if (span) span.textContent = "设置 MONITOR_PREVIEW_ENABLED=0 可关闭；开启时从 agent 上行帧抽稀展示";
        } else {
          if (strong) strong.textContent = "暂无预览帧";
          if (span) span.textContent = "等待 agent 上行；勿将占位当作真实画面";
        }
      }
    }
    if (hasFrame && els.previewImg && (!els.previewImg.src || els.previewImg.src.indexOf("blob:") !== 0)) {
      els.previewImg.src = "data:image/jpeg;base64," + preview.jpegBase64;
      els.previewImg.classList.remove("hidden");
      if (els.previewPlaceholder) els.previewPlaceholder.classList.add("hidden");
    }
    if (els.previewStale) {
      const showStale = hasFrame && !!preview.stale;
      els.previewStale.classList.toggle("hidden", !showStale);
    }
  }

  function renderAmbient(ambient) {
    const cameras = Array.isArray(ambient.cameras) ? ambient.cameras : [];
    const previousIds = state.ambientCameras.map((item) => String(item.deviceId)).join("|");
    const nextIds = cameras.map((item) => String(item.deviceId)).join("|");
    state.ambientCameras = cameras;
    if (els.ambientEmpty) els.ambientEmpty.classList.toggle("hidden", cameras.length > 0);
    if (els.ambientGrid && previousIds !== nextIds) {
      els.ambientGrid.innerHTML = "";
      cameras.forEach((camera) => {
        const card = document.createElement("div");
        card.className = "mon-camera-card";
        const head = document.createElement("div");
        head.className = "mon-camera-card-head";
        const title = document.createElement("strong");
        title.textContent = camera.name || camera.deviceId;
        const status = document.createElement("span");
        status.className = "mon-tag " + (camera.hasFrame ? "ok" : "warn");
        status.textContent = camera.hasFrame ? "有画面" : "等待首帧";
        status.dataset.cameraStatus = camera.deviceId;
        head.append(title, status);
        const preview = document.createElement("div");
        preview.className = "mon-preview mon-ambient-preview";
        const placeholder = document.createElement("div");
        placeholder.className = "mon-preview-placeholder";
        placeholder.dataset.cameraPlaceholder = camera.deviceId;
        const placeholderTitle = document.createElement("strong");
        placeholderTitle.textContent = camera.error ? "摄像头暂不可用" : "正在读取摄像头…";
        const placeholderHint = document.createElement("span");
        placeholderHint.textContent = camera.error || `设备序号 ${camera.selectorIndex}`;
        placeholder.append(placeholderTitle, placeholderHint);
        const img = document.createElement("img");
        img.className = "mon-preview-img hidden";
        img.alt = (camera.name || camera.deviceId) + "预览";
        img.dataset.cameraImg = camera.deviceId;
        preview.append(placeholder, img);
        card.append(head, preview);
        els.ambientGrid.appendChild(card);
      });
    }
    if (els.ambientGrid) cameras.forEach((camera) => {
      const status = els.ambientGrid.querySelector(
        '[data-camera-status="' + CSS.escape(String(camera.deviceId)) + '"]'
      );
      if (status) {
        status.className = "mon-tag " + (camera.hasFrame ? "ok" : "warn");
        status.textContent = camera.hasFrame ? "有画面" : "等待首帧";
      }
    });
    if (cameras.length) {
      startAmbientPreviewLoop();
      pollAmbientPreview();
    } else {
      stopAmbientPreviewLoop();
      if (els.ambientGrid) els.ambientGrid.innerHTML = "";
    }
  }

  function renderEvents(events) {
    if (!els.events) return;
    els.events.innerHTML = "";
    const list = Array.isArray(events) ? events.slice().reverse() : [];
    if (!list.length) {
      const li = document.createElement("li");
      li.textContent = "暂无事件";
      els.events.appendChild(li);
      return;
    }
    list.slice(0, 20).forEach((ev) => {
      const li = document.createElement("li");
      const t = (ev && ev.t) || "";
      const kind = (ev && ev.kind) || "";
      const msg = (ev && ev.message) || "";
      const level = String((ev && ev.level) || "info").toLowerCase();
      li.className = level === "error" ? "bad" : level === "warn" ? "warn" : "";
      const detail = ev && ev.extra && ev.extra.error ? " · " + ev.extra.error : "";
      li.textContent = (t ? t.slice(11, 19) + " · " : "") + kind + " · " + msg + detail;
      els.events.appendChild(li);
    });
  }

  function renderChart(samples) {
    if (!els.chart) return;
    const w = 600;
    const h = 140;
    const pad = 8;
    const usable = (samples || []).filter(
      (s) => s && s.score != null && String(s.quality || "").toUpperCase() !== "MISSING"
    );
    if (!usable.length) {
      els.chart.innerHTML =
        '<text x="12" y="72" fill="#8a9bad" font-size="12">暂无近 60s 有效样本</text>';
      return;
    }
    const scores = usable.map((s) => Number(s.score) || 0);
    const maxY = 100;
    const n = scores.length;
    const step = n > 1 ? (w - pad * 2) / (n - 1) : 0;
    const pts = scores
      .map((v, i) => {
        const x = pad + i * step;
        const y = h - pad - (v / maxY) * (h - pad * 2);
        return x.toFixed(1) + "," + y.toFixed(1);
      })
      .join(" ");
    const area =
      pts +
      " " +
      (pad + (n - 1) * step).toFixed(1) +
      "," +
      (h - pad) +
      " " +
      pad +
      "," +
      (h - pad);
    els.chart.innerHTML =
      '<polyline fill="none" stroke="#2aa8c8" stroke-width="2.2" points="' +
      pts +
      '"></polyline>' +
      '<polyline fill="rgba(42,168,200,.12)" stroke="none" points="' +
      area +
      '"></polyline>';
  }

  function renderEmotion(emotion) {
    if (!emotion || !emotion.available) {
      if (els.emoPos) els.emoPos.style.width = "0%";
      if (els.emoNeu) els.emoNeu.style.width = "0%";
      if (els.emoNeg) els.emoNeg.style.width = "0%";
      if (els.emoLabel) els.emoLabel.textContent = "不可用";
      return;
    }
    const p = Math.round((emotion.positiveRatio || 0) * 100);
    const n = Math.round((emotion.neutralRatio || 0) * 100);
    const g = Math.round((emotion.negativeRatio || 0) * 100);
    if (els.emoPos) els.emoPos.style.width = p + "%";
    if (els.emoNeu) els.emoNeu.style.width = n + "%";
    if (els.emoNeg) els.emoNeg.style.width = g + "%";
    if (els.emoLabel) {
      els.emoLabel.textContent =
        "正 " + p + "% / 中 " + n + "% / 负 " + g + "% · n=" + (emotion.sampleCount || 0);
    }
  }

  function renderLimitations(list) {
    if (!els.limitations) return;
    els.limitations.innerHTML = "";
    if (!list.length) {
      const li = document.createElement("li");
      li.textContent = "无额外限制说明";
      els.limitations.appendChild(li);
      return;
    }
    list.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      els.limitations.appendChild(li);
    });
  }

  function bindTabs() {
    /* 顶栏已改为链接跳转配置中心 / 监控，无需 Tab 切换 */
  }

  function setControlFeedback(text, kind) {
    if (!els.controlFeedback) return;
    els.controlFeedback.textContent = "控制 · " + text;
    els.controlFeedback.classList.toggle("ok", kind === "ok");
    els.controlFeedback.classList.toggle("warn", kind === "warn");
  }

  async function executeControlAction(button, url, body) {
    if (!button || button.disabled) return;
    const original = button.textContent;
    button.disabled = true;
    button.textContent = "执行中…";
    setControlFeedback("命令提交中", "warn");
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) {
        throw new Error(data.detail || data.message || data.error || ("HTTP " + res.status));
      }
      setControlFeedback(data.message || "命令已下发", "ok");
      fetchSnapshot("control");
    } catch (error) {
      setControlFeedback(error && error.message ? error.message : String(error), "warn");
    } finally {
      button.disabled = false;
      button.textContent = original;
      if (button === els.stopAudio && !state.mediaSessionId) button.disabled = true;
    }
  }

  function bindOperationalControls() {
    if (els.stopRobot) {
      els.stopRobot.addEventListener("click", () => executeControlAction(
        els.stopRobot,
        "/api/v2/control/actions/stop-robot",
        { trainingSessionId: state.trainingSessionId },
      ));
    }
    if (els.stopAudio) {
      els.stopAudio.addEventListener("click", () => executeControlAction(
        els.stopAudio,
        "/api/v2/control/actions/stop-audio",
        { sessionId: state.mediaSessionId, trainingSessionId: state.trainingSessionId },
      ));
    }
  }

  function bindSocket() {
    if (typeof socket === "undefined" || !socket) return;

    const markOnline = () => {
      state.socketOnline = true;
      updateBadges();
    };
    const markOffline = () => {
      state.socketOnline = false;
      updateBadges();
    };

    if (socket.connected) markOnline();
    socket.on("connect", markOnline);
    socket.on("disconnect", markOffline);

    SOCKET_REFRESH_EVENTS.forEach((evt) => {
      socket.on(evt, () => {
        if (state.view !== "monitor") return;
        fetchSnapshot("ws");
      });
    });

    socket.on("report_ready_for_review", (payload) => {
      const id = payload && payload.trainingSessionId;
      if (!id) return;
      openReviewModal(payload);
      refreshPendingReviews();
    });

    socket.on("report_published", () => {
      closeReviewModal();
      refreshPendingReviews();
    });
  }

  function bindVisibility() {
    document.addEventListener("visibilitychange", () => {
      if (state.view !== "monitor") return;
      if (!document.hidden) {
        fetchSnapshot("poll");
        startPolling();
        if (state.ambientCameras.length) startAmbientPreviewLoop();
      }
    });
  }

  function updateReviewBadge() {
    const items = state.pendingReviews || [];
    const n = items.length;
    if (els.pendingBtn) {
      els.pendingBtn.classList.toggle("hidden", n <= 0);
    }
    if (els.pendingCount) {
      els.pendingCount.textContent = String(n);
    }
    if (els.pendingPanel) {
      els.pendingPanel.classList.toggle("hidden", n <= 0);
    }
    if (els.pendingList) {
      els.pendingList.innerHTML = "";
      items.forEach((it) => {
        const li = document.createElement("li");
        const left = document.createElement("span");
        left.textContent =
          String(it.trainingSessionId || "").slice(0, 8) +
          "… · 分 " +
          (it.overall != null ? it.overall : "—") +
          " · " +
          (it.status || "—");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = "处理";
        btn.addEventListener("click", () => {
          delete state.reviewDismissed[it.trainingSessionId];
          openReviewModal(it);
        });
        li.appendChild(left);
        li.appendChild(btn);
        els.pendingList.appendChild(li);
      });
    }
  }

  async function refreshPendingReviews() {
    try {
      const res = await fetch("/api/report/pending-reviews?limit=20", { cache: "no-store" });
      const json = await res.json();
      state.pendingReviews = (json && json.items) || [];
      updateReviewBadge();
      // 稍后处理后不自动弹窗；通过顶栏「待处理报告」或健康区列表继续处理
    } catch (_) {}
  }

  function openReviewModal(item) {
    if (!els.reviewModal || !item || !item.trainingSessionId) return;
    state.currentReviewId = item.trainingSessionId;
    if (els.reviewMeta) {
      els.reviewMeta.textContent =
        "会话 " +
        String(item.trainingSessionId).slice(0, 8) +
        "… · 学生 " +
        (item.studentId != null ? item.studentId : "—") +
        " · 综合分 " +
        (item.overall != null ? item.overall : "—") +
        " · " +
        (item.status || "—");
    }
    if (els.reviewWarn) {
      els.reviewWarn.classList.toggle("hidden", String(item.status || "").toUpperCase() !== "PARTIAL");
    }
    els.reviewModal.classList.remove("hidden");
  }

  function closeReviewModal() {
    if (els.reviewModal) els.reviewModal.classList.add("hidden");
    if (state.currentReviewId) {
      state.reviewDismissed[state.currentReviewId] = true;
    }
    state.currentReviewId = null;
    refreshPendingReviews();
  }

  function openFirstPendingReview() {
    const items = state.pendingReviews || [];
    if (!items.length) {
      refreshPendingReviews().then(() => {
        const next = (state.pendingReviews || [])[0];
        if (next) {
          delete state.reviewDismissed[next.trainingSessionId];
          openReviewModal(next);
        }
      });
      return;
    }
    const first = items[0];
    delete state.reviewDismissed[first.trainingSessionId];
    openReviewModal(first);
  }

  function bindReviewModal() {
    if (els.pendingBtn) {
      els.pendingBtn.addEventListener("click", openFirstPendingReview);
    }
    if (els.pendingOpen) {
      els.pendingOpen.addEventListener("click", openFirstPendingReview);
    }
    document.querySelectorAll("[data-review-dismiss]").forEach((node) => {
      node.addEventListener("click", closeReviewModal);
    });
    if (els.reviewPublish) {
      els.reviewPublish.addEventListener("click", async () => {
        const id = state.currentReviewId;
        if (!id) return;
        els.reviewPublish.disabled = true;
        try {
          const res = await fetch("/api/report/" + encodeURIComponent(id) + "/publish", {
            method: "POST",
          });
          const json = await res.json();
          if (!json.success) throw new Error(json.error || "publish_failed");
          if (els.reviewModal) els.reviewModal.classList.add("hidden");
          state.currentReviewId = null;
          refreshPendingReviews();
        } catch (err) {
          alert("推送失败：" + err);
        } finally {
          els.reviewPublish.disabled = false;
        }
      });
    }
    if (els.reviewEdit) {
      els.reviewEdit.addEventListener("click", () => {
        const id = state.currentReviewId;
        if (!id) return;
        window.location.href = "/server/report-review/" + encodeURIComponent(id);
      });
    }
  }

  function init() {
    bindTabs();
    bindOperationalControls();
    bindSocket();
    bindVisibility();
    bindReviewModal();
    const params = new URLSearchParams(location.search);
    const q = params.get("view");
    const hash = (location.hash || "").replace("#", "");
    if (q === "config" || hash === "config") {
      window.location.replace("/server/config/overview");
      return;
    }
    setView("monitor");
    window.addEventListener("resize", () => {
      /* 触发图表随容器宽度重绘：下次 snapshot 即可；此处轻量空操作占位 */
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
