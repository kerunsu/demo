/**
 * 儿童端自由对话：连续自动聆听（能量 VAD）→ FunASR → LLM → browser TTS
 * - 默认走本机麦克风 PCM→WAV → child_dialogue_audio（FunASR / voice-service）
 * - 浏览器 SpeechRecognition 仅作无 FunASR 时的兜底，不再依赖按住说话
 * - 机器人朗读时暂停 ASR，避免回授
 */
(function (global) {
  const TARGET_SAMPLE_RATE = 16000;
  const START_LEVEL = 0.03;
  const SILENCE_LEVEL = 0.018;
  const RESET_LEVEL = 0.024;
  const MIN_VOICE_MS = 180;
  const MIN_TURN_MS = 700;
  const SILENCE_END_MS = 900;
  const COOLDOWN_MS = 180;
  const MAX_TURN_MS = 12000;
  /** 开说前环形缓冲：覆盖 MIN_VOICE_MS 确认窗 + 提问结束后的句首 */
  const PREROLL_MS = 700;

  const MAX_LOG_MESSAGES = 8;
  const PANEL_COLLAPSED_KEY = "eiart.child.dialogue.collapsed";
  const ROLE_LABELS = {
    child: "儿童",
    maimai: "麦麦",
    system: "系统",
  };

  let dialogueBusy = false;
  let uiBound = false;
  let resultHandlerBound = false;
  let autoListenEnabled = false;
  let asrPausedForTts = false;
  let cooldownUntil = 0;
  /** 打字发送时已写入儿童气泡，结果回调里勿再记一遍 transcript */
  let childBubbleLoggedForPending = false;
  /** 连续 ASR 关键词命中与对话 STT 可能同句双发，短窗去重 */
  let lastChildTranscriptKey = "";
  let lastChildTranscriptAt = 0;
  /** 本地唤醒状态（与服务端 session+题目指纹绑定；题目切换后清除） */
  let dialogueAwake = false;
  let dialoguePanelVisible = true;
  let dialoguePanelCollapsed = false;
  let wakeWordEnabled = false;
  let lastPageFingerprint = "";
  let lastFingerprintCheckAt = 0;

  let mediaStream = null;
  let audioContext = null;
  let analyser = null;
  let meterFrame = null;
  let captureNode = null;
  let silenceGain = null;

  let capturingTurn = false;
  let voiceStartedAt = null;
  let silenceStartedAt = null;
  let turnStartedAt = null;
  let pcmChunks = [];
  /** 最近 PREROLL_MS 的 PCM，在 VAD 确认开说前也持续写入 */
  let prerollChunks = [];
  let prerollSamples = 0;
  let captureSampleRate = TARGET_SAMPLE_RATE;

  let speechRec = null;
  let speechRecActive = false;
  let usingBrowserSpeechFallback = false;
  /** 麦克风曾被拒绝/不安全上下文：禁止无点击自动重试 */
  let micBlocked = false;

  function getSocket() {
    return global.socket || null;
  }

  function getSessionId() {
    return global.currentSessionId || null;
  }

  function applyDialoguePanelVisibility(visible) {
    dialoguePanelVisible = visible !== false;
    const panel = document.getElementById("dialoguePanel");
    if (!panel) return;
    panel.style.display = dialoguePanelVisible ? "block" : "none";
    panel.style.visibility = dialoguePanelVisible ? "visible" : "hidden";
    panel.setAttribute("aria-hidden", dialoguePanelVisible ? "false" : "true");
  }

  function applyDialoguePanelCollapsed(collapsed, persist) {
    dialoguePanelCollapsed = collapsed === true;
    const panel = document.getElementById("dialoguePanel");
    const body = document.getElementById("dialoguePanelBody");
    const button = document.getElementById("dialogueCollapseBtn");
    if (!panel || !body || !button) return;
    panel.classList.toggle("is-collapsed", dialoguePanelCollapsed);
    body.setAttribute("aria-hidden", dialoguePanelCollapsed ? "true" : "false");
    button.setAttribute("aria-expanded", dialoguePanelCollapsed ? "false" : "true");
    button.textContent = dialoguePanelCollapsed ? "+" : "−";
    button.title = dialoguePanelCollapsed ? "展开语音窗口" : "收起语音窗口";
    button.setAttribute("aria-label", button.title);
    if (persist) {
      try {
        localStorage.setItem(PANEL_COLLAPSED_KEY, dialoguePanelCollapsed ? "1" : "0");
      } catch (_) { /* storage may be disabled */ }
    }
  }

  function requestDialogueControlState(sessionId) {
    const socket = getSocket();
    if (!socket) return;
    socket.emit("child_dialogue_control_state_request", {
      sessionId: sessionId || getSessionId(),
      clientTimestamp: Date.now(),
    });
  }

  function buildPageContext() {
    const interactive = global.interactivePageContext || null;
    const base = {
      courseType: global.currentCourseType || "",
      courseId: global.currentCourseId || null,
      itemId: global.currentItemId || null,
      prompt: global.currentQuestionPrompt || "",
      target: global.currentSpeechTarget || "",
      speechTarget: global.currentSpeechTarget || "",
      name: global.currentItemName || global.currentSpeechTarget || "",
      label: global.currentSpeechTarget || "",
    };
    const speechTypes = new Set(["naming", "speech", "onomatopoeia", "mimic"]);
    const baseType = String(base.courseType || "").toLowerCase();
    // 命名/拟声等非 iframe 课：禁止合并旧配对/排序 interactive 上下文
    if (speechTypes.has(baseType)) {
      return base;
    }
    if (!interactive || typeof interactive !== "object") {
      return base;
    }
    const interactiveType = String(
      interactive.courseType || interactive.course_type || ""
    ).toLowerCase();
    // 课型不一致时丢弃 interactive，避免串课
    if (interactiveType && baseType && interactiveType !== baseType) {
      return base;
    }
    const merged = {
      ...base,
      ...interactive,
      courseType: interactive.courseType || base.courseType,
      prompt: interactive.prompt || base.prompt,
    };
    // interactive.target 为 null/"" 时不要回落到旧的 currentSpeechTarget
    if (Object.prototype.hasOwnProperty.call(interactive, "target")) {
      merged.target = interactive.target || "";
    } else {
      merged.target = interactive.target || base.target;
    }
    return merged;
  }

  /** 与服务端 `_page_context_fingerprint` 对齐的题目指纹 */
  function pageContextFingerprint(pageContext) {
    const ctx = pageContext || {};
    const courseType = String(ctx.courseType || ctx.course_type || "")
      .trim()
      .toLowerCase();
    const qid = String(ctx.questionId || ctx.question_id || "").trim();
    const itemId = String(
      ctx.itemId != null ? ctx.itemId : ctx.item_id != null ? ctx.item_id : ""
    ).trim();
    let qIndex = ctx.questionIndex;
    if (qIndex == null) qIndex = ctx.question_index;
    const target = String(
      ctx.target ||
        ctx.targetText ||
        ctx.speechTarget ||
        ctx.itemLabel ||
        ctx.label ||
        ctx.name ||
        ""
    )
      .trim()
      .slice(0, 40);
    const options = ctx.options || ctx.optionsLeftToRight || [];
    const optParts = [];
    if (Array.isArray(options)) {
      options.forEach((opt) => {
        if (opt && typeof opt === "object") {
          optParts.push(
            String(opt.id || opt.label || opt.name || opt.src || "")
          );
        } else {
          optParts.push(String(opt));
        }
      });
    } else if (typeof options === "string") {
      optParts.push(options.trim());
    }
    return [courseType, qid, itemId, qIndex != null ? String(qIndex) : "", target, optParts.join(",")].join("|");
  }

  function setDialogueAwake(awake, opts) {
    const next = !!awake;
    const prev = dialogueAwake;
    dialogueAwake = next;
    if (opts && opts.updateStatus !== false && prev !== next) {
      setStatus(listenIdleStatus());
    }
    updateSleepButton();
  }

  function emitDialogueSleep(reason) {
    const socket = getSocket();
    if (socket) {
      socket.emit("child_dialogue_sleep", {
        sessionId: getSessionId(),
        reason: reason || "manual_sleep",
      });
    }
    setDialogueAwake(false, { updateStatus: true });
  }

  /**
   * 题目指纹变化时退出本地唤醒，并通知服务端。
   * @returns {boolean} 是否发生了切换
   */
  function syncAwakeForPageContext() {
    const fp = pageContextFingerprint(buildPageContext());
    const switched = !!(lastPageFingerprint && lastPageFingerprint !== fp);
    if (switched && dialogueAwake) {
      console.log("[child_dialogue] 题目指纹变化，退出唤醒", lastPageFingerprint, "→", fp);
      emitDialogueSleep("context_switch");
    }
    lastPageFingerprint = fp;
    return switched;
  }

  function listenIdleStatus() {
    if (!autoListenEnabled) return "准备就绪";
    if (asrPausedForTts) return "朗读中，暂停聆听…";
    if (dialogueBusy) return dialogueAwake ? "思考中…" : (wakeWordEnabled ? "请说唤醒词" : "等待教师唤醒");
    if (dialogueAwake) return "已唤醒，可以说了";
    return wakeWordEnabled ? "请说：麦麦，麦麦" : "等待教师端点击唤醒智能体";
  }

  function updateSleepButton() {
    const btn = document.getElementById("dialogueSleepBtn");
    if (!btn) return;
    btn.disabled = !dialogueAwake;
    btn.textContent = dialogueAwake ? "退出唤醒" : "未唤醒";
  }

  function setStatus(text) {
    const el = document.getElementById("dialogueStatus");
    if (el) el.textContent = text;
  }

  async function checkVoiceHealth() {
    try {
      const response = await fetch("/api/v2/voice/health", { cache: "no-store" });
      const data = await response.json();
      if (data && data.ready) return true;
      const deps = (data && data.dependencies) || {};
      const missing = Object.keys(deps).filter((key) => deps[key] === false);
      const detail = (data && data.error) || "语音识别模型未就绪";
      const suffix = missing.length ? `（缺少 ${missing.join("、")}）` : "";
      setStatus(`语音识别不可用：${detail}${suffix}`);
      appendDialogueLog("system", `语音识别状态：${detail}${suffix}`);
      return false;
    } catch (error) {
      setStatus("语音识别服务不可达，请检查 Server");
      appendDialogueLog("system", "语音识别服务不可达，请检查 Server 的 voice-service");
      return false;
    }
  }

  /**
   * 调试用对话气泡：保留约当前 + 前 3 轮（最多 8 条）。
   * role: "child" | "maimai" | "system"
   */
  function appendDialogueLog(role, text) {
    const trimmed = String(text || "").trim();
    if (!trimmed) return;
    const log = document.getElementById("dialogueLog");
    if (!log) return;
    const key = ROLE_LABELS[role] ? role : "system";
    const row = document.createElement("div");
    row.className = `dialogue-panel__msg dialogue-panel__msg--${key}`;
    const roleEl = document.createElement("span");
    roleEl.className = "dialogue-panel__msg-role";
    roleEl.textContent = ROLE_LABELS[key] || "系统";
    const body = document.createElement("div");
    body.className = "dialogue-panel__msg-body";
    body.textContent = trimmed;
    row.appendChild(roleEl);
    row.appendChild(body);
    log.appendChild(row);
    while (log.children.length > MAX_LOG_MESSAGES) {
      log.removeChild(log.firstChild);
    }
    log.scrollTop = log.scrollHeight;
  }

  /** 儿童识别文本入对话气泡（短窗去重，避免双通路重复）。 */
  function normalizeTranscriptKey(text) {
    return String(text || "")
      .trim()
      .replace(/[\s\u3000，。！？、；：,.!?;:'"“”‘’（）()\[\]【】<>《》…—～~·]+/g, "");
  }

  function appendChildTranscript(text) {
    const trimmed = String(text || "").trim();
    if (!trimmed) return false;
    const now = Date.now();
    const norm = normalizeTranscriptKey(trimmed);
    if (!norm) return false;
    if (lastChildTranscriptKey && now - lastChildTranscriptAt < 8000) {
      if (
        norm === lastChildTranscriptKey ||
        lastChildTranscriptKey.includes(norm) ||
        norm.includes(lastChildTranscriptKey)
      ) {
        if (norm.length <= lastChildTranscriptKey.length) return false;
      }
    }
    lastChildTranscriptKey = norm;
    lastChildTranscriptAt = now;
    appendDialogueLog("child", trimmed);
    return true;
  }

  function isLocalhostHost() {
    const host = String(location.hostname || "").toLowerCase();
    return (
      host === "localhost" ||
      host === "127.0.0.1" ||
      host === "[::1]" ||
      host === "::1"
    );
  }

  /** http://局域网IP 等非安全上下文会直接 NotAllowedError */
  function isMicContextOk() {
    return !!window.isSecureContext || isLocalhostHost();
  }

  function localhostChildUrl() {
    const port = location.port || (location.protocol === "https:" ? "443" : "8080");
    const proto = location.protocol === "https:" ? "https" : "http";
    return `${proto}://127.0.0.1:${port}/child`;
  }

  function lanHttpsChildHint() {
    const host = String(location.hostname || "");
    const port = location.port || "8080";
    if (host && !isLocalhostHost()) {
      return `https://${host}:${port}/child`;
    }
    return `https://<本机LAN-IP>:${port}/child`;
  }

  /**
   * 将 getUserMedia / SpeechRecognition 错误归类，避免露出 not-allowed 原文。
   * @returns {"insecure"|"denied"|"unavailable"|"other"}
   */
  function classifyMicFailure(errOrCode) {
    if (!isMicContextOk()) return "insecure";
    const name = String(
      (errOrCode && errOrCode.name) || errOrCode || ""
    ).toLowerCase();
    const msg = String((errOrCode && errOrCode.message) || "").toLowerCase();
    if (
      name === "notallowederror" ||
      name === "not-allowed" ||
      name === "service-not-allowed" ||
      name === "permissiondeniederror" ||
      msg.includes("not-allowed") ||
      msg.includes("permission")
    ) {
      return "denied";
    }
    if (
      name === "notfounderror" ||
      name === "devices-not-found" ||
      name === "audio-capture" ||
      name === "no_getusermedia"
    ) {
      return "unavailable";
    }
    if (name === "securityerror" || msg.includes("secure")) {
      return "insecure";
    }
    return "other";
  }

  function micHelpMessage(kind) {
    if (kind === "insecure") {
      // 跨机机器人：127.0.0.1 会打到本机而非后端，禁止作为首选提示
      if (isLocalhostHost()) {
        return (
          `当前地址无法使用麦克风。请改用 ${localhostChildUrl()}，` +
          `或启用后端 HTTPS 后打开 ${lanHttpsChildHint()}。`
        );
      }
      const host = String(location.hostname || "<后端IP>");
      const port = location.port || "8080";
      return (
        "当前为局域网 HTTP，浏览器未把它当作安全上下文，对话麦克风不可用" +
        "（即使地址栏显示已允许麦克风）。请在机器人运维页点「打开 /child」，" +
        `或在机器人上运行同目录 Open-ChildLanMic.ps1 -LanHost ${host} -Port ${port}；` +
        "勿用普通浏览器直接打开局域网 http://IP/child。" +
        `（仅当后端与浏览器同机时可用 ${localhostChildUrl()}）`
      );
    }
    if (kind === "denied") {
      return (
        "麦克风权限被拒绝。请点地址栏左侧锁图标 → 网站设置 → 麦克风选「允许」，然后刷新再点「开始自动聆听」。" +
        "若曾点「禁止」：Chrome 设置 → 隐私和安全 → 网站设置 → 麦克风，删除本站后刷新重试。"
      );
    }
    if (kind === "unavailable") {
      return "未检测到可用麦克风，请检查系统录音设备后重试。";
    }
    return "麦克风不可用，请检查权限与设备后，再点「开始自动聆听」。";
  }

  function setListenButtonState() {
    const btn = document.getElementById("dialogueHoldBtn");
    if (!btn) return;
    if (autoListenEnabled) {
      btn.textContent = asrPausedForTts || dialogueBusy ? "聆听暂停中…" : "停止自动聆听";
      btn.classList.add("is-listening");
    } else {
      btn.textContent = "开始自动聆听";
      btn.classList.remove("is-listening");
    }
  }

  function getSpeechRecognitionCtor() {
    return global.SpeechRecognition || global.webkitSpeechRecognition || null;
  }

  function rmsFromTimeDomain(samples) {
    let sum = 0;
    for (let i = 0; i < samples.length; i += 1) {
      const v = (samples[i] - 128) / 128;
      sum += v * v;
    }
    return Math.sqrt(sum / Math.max(1, samples.length));
  }

  function concatenateFloat32(chunks) {
    const total = chunks.reduce((n, c) => n + c.length, 0);
    const out = new Float32Array(total);
    let offset = 0;
    chunks.forEach((c) => {
      out.set(c, offset);
      offset += c.length;
    });
    return out;
  }

  function downsampleBuffer(input, inputRate, outputRate) {
    if (inputRate === outputRate) return input;
    if (inputRate < outputRate) return input;
    const ratio = inputRate / outputRate;
    const outLen = Math.max(1, Math.round(input.length / ratio));
    const output = new Float32Array(outLen);
    let inputOffset = 0;
    for (let i = 0; i < outLen; i += 1) {
      const next = Math.round((i + 1) * ratio);
      let sum = 0;
      let count = 0;
      for (let j = inputOffset; j < next && j < input.length; j += 1) {
        sum += input[j];
        count += 1;
      }
      output[i] = count > 0 ? sum / count : 0;
      inputOffset = next;
    }
    return output;
  }

  function encodePcm16Wav(samples, sampleRateHz) {
    const bytesPerSample = 2;
    const header = 44;
    const buffer = new ArrayBuffer(header + samples.length * bytesPerSample);
    const view = new DataView(buffer);
    const writeAscii = (offset, text) => {
      for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
    };
    writeAscii(0, "RIFF");
    view.setUint32(4, 36 + samples.length * bytesPerSample, true);
    writeAscii(8, "WAVE");
    writeAscii(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRateHz, true);
    view.setUint32(28, sampleRateHz * bytesPerSample, true);
    view.setUint16(32, bytesPerSample, true);
    view.setUint16(34, 16, true);
    writeAscii(36, "data");
    view.setUint32(40, samples.length * bytesPerSample, true);
    let offset = header;
    for (let i = 0; i < samples.length; i += 1) {
      const clamped = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
      offset += 2;
    }
    return new Blob([buffer], { type: "audio/wav" });
  }

  async function blobToBase64(blob) {
    const buffer = await blob.arrayBuffer();
    let binary = "";
    const bytes = new Uint8Array(buffer);
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return btoa(binary);
  }

  function emitDialogueText(text) {
    const socket = getSocket();
    if (!socket) {
      setStatus("未连接");
      return false;
    }
    const trimmed = String(text || "").trim();
    if (!trimmed) {
      setStatus("请先说点什么或打字");
      return false;
    }
    syncAwakeForPageContext();
    dialogueBusy = true;
    childBubbleLoggedForPending = true;
    appendChildTranscript(trimmed);
    setListenButtonState();
    setStatus(dialogueAwake ? "思考中…" : "识别唤醒中…");
    socket.emit("child_dialogue_text", {
      sessionId: getSessionId(),
      text: trimmed,
      pageContext: buildPageContext(),
    });
    return true;
  }

  async function emitDialogueAudioWav(blob) {
    const socket = getSocket();
    if (!socket) {
      setStatus("未连接");
      return;
    }
    if (!blob || blob.size < 320) {
      setStatus("太短了，继续说…");
      return;
    }
    syncAwakeForPageContext();
    dialogueBusy = true;
    childBubbleLoggedForPending = false;
    setListenButtonState();
    setStatus(dialogueAwake ? "识别中（FunASR）…" : "识别唤醒中…");
    try {
      const audioBase64 = await blobToBase64(blob);
      socket.emit("child_dialogue_audio", {
        sessionId: getSessionId(),
        audioBase64,
        mimeType: "audio/wav",
        pageContext: buildPageContext(),
      });
    } catch (err) {
      console.error("上传对话音频失败", err);
      setStatus("发送失败");
      dialogueBusy = false;
      childBubbleLoggedForPending = false;
      setListenButtonState();
      maybeResumeListening();
    }
  }

  function canCapture() {
    return (
      autoListenEnabled &&
      !dialogueBusy &&
      !asrPausedForTts &&
      Date.now() >= cooldownUntil &&
      !!mediaStream &&
      !!analyser
    );
  }

  function clearPreroll() {
    prerollChunks = [];
    prerollSamples = 0;
  }

  function pushPreroll(input) {
    const copy = new Float32Array(input);
    prerollChunks.push(copy);
    prerollSamples += copy.length;
    const maxSamples = Math.max(
      1,
      Math.floor(captureSampleRate * (PREROLL_MS / 1000))
    );
    while (prerollSamples > maxSamples && prerollChunks.length > 0) {
      const dropped = prerollChunks.shift();
      prerollSamples -= dropped.length;
    }
  }

  function seedPcmFromPreroll() {
    pcmChunks = prerollChunks.map((c) => new Float32Array(c));
  }

  function prerollHasVoice() {
    if (!prerollChunks.length) return false;
    const merged = concatenateFloat32(prerollChunks);
    if (!merged.length) return false;
    let sum = 0;
    for (let i = 0; i < merged.length; i += 1) {
      const v = merged[i];
      sum += v * v;
    }
    return Math.sqrt(sum / merged.length) >= START_LEVEL * 0.7;
  }

  function finalizeCapturedTurn() {
    if (!capturingTurn) return;
    capturingTurn = false;
    const chunks = pcmChunks;
    pcmChunks = [];
    voiceStartedAt = null;
    silenceStartedAt = null;
    turnStartedAt = null;
    if (!chunks.length) return;
    const merged = concatenateFloat32(chunks);
    const down = downsampleBuffer(merged, captureSampleRate, TARGET_SAMPLE_RATE);
    const wav = encodePcm16Wav(down, TARGET_SAMPLE_RATE);
    void emitDialogueAudioWav(wav);
  }

  function onPcmFrame(input) {
    if (!capturingTurn) return;
    pcmChunks.push(new Float32Array(input));
    const now = performance.now();
    const elapsed = now - (turnStartedAt || now);
    if (elapsed >= MAX_TURN_MS) {
      finalizeCapturedTurn();
    }
  }

  function meterTick() {
    if (!analyser || !autoListenEnabled) return;
    const nowWall = Date.now();
    if (nowWall - lastFingerprintCheckAt >= 400) {
      lastFingerprintCheckAt = nowWall;
      syncAwakeForPageContext();
    }
    const samples = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(samples);
    const level = Math.min(1, rmsFromTimeDomain(samples));
    const now = performance.now();

    if (!canCapture()) {
      if (capturingTurn) {
        // 朗读/忙时丢弃半截，避免回授进 FunASR
        capturingTurn = false;
        pcmChunks = [];
        voiceStartedAt = null;
        silenceStartedAt = null;
        turnStartedAt = null;
      }
      // Only wipe preroll while the robot is actually speaking. During the
      // post-TTS cooldown the child may already have started answering.
      if (asrPausedForTts) {
        clearPreroll();
      }
      meterFrame = window.requestAnimationFrame(meterTick);
      return;
    }

    if (!capturingTurn) {
      const prerollReady = prerollHasVoice();
      if (prerollReady || level >= START_LEVEL) {
        voiceStartedAt = voiceStartedAt || now;
        if (prerollReady || now - voiceStartedAt >= MIN_VOICE_MS) {
          capturingTurn = true;
          turnStartedAt = now;
          silenceStartedAt = null;
          seedPcmFromPreroll();
          setStatus("正在听…");
        }
      } else {
        voiceStartedAt = null;
        setStatus(listenIdleStatus());
      }
    } else {
      if (level <= SILENCE_LEVEL) {
        silenceStartedAt = silenceStartedAt || now;
        const spoken = now - (turnStartedAt || now);
        if (spoken >= MIN_TURN_MS && now - silenceStartedAt >= SILENCE_END_MS) {
          finalizeCapturedTurn();
        }
      } else if (level >= RESET_LEVEL) {
        silenceStartedAt = null;
      }
    }

    meterFrame = window.requestAnimationFrame(meterTick);
  }

  function releaseAudioGraph(keepStream) {
    if (meterFrame != null) {
      window.cancelAnimationFrame(meterFrame);
      meterFrame = null;
    }
    if (captureNode) {
      captureNode.onaudioprocess = null;
      try {
        captureNode.disconnect();
      } catch (_) {}
      captureNode = null;
    }
    if (silenceGain) {
      try {
        silenceGain.disconnect();
      } catch (_) {}
      silenceGain = null;
    }
    analyser = null;
    if (audioContext && audioContext.state !== "closed") {
      void audioContext.close();
    }
    audioContext = null;
    if (!keepStream && mediaStream) {
      mediaStream.getTracks().forEach((t) => t.stop());
      mediaStream = null;
    }
    capturingTurn = false;
    pcmChunks = [];
    clearPreroll();
    voiceStartedAt = null;
    silenceStartedAt = null;
    turnStartedAt = null;
  }

  async function openMicStream() {
    const attempts = [
      {
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      },
      { audio: true },
    ];
    let lastErr = null;
    for (const constraints of attempts) {
      try {
        return await navigator.mediaDevices.getUserMedia(constraints);
      } catch (err) {
        lastErr = err;
      }
    }
    throw lastErr || new Error("getUserMedia failed");
  }

  async function startFunasrAutoListen() {
    if (!isMicContextOk()) {
      const err = new Error("insecure_context");
      err.name = "SecurityError";
      throw err;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      const err = new Error("no_getUserMedia");
      err.name = "no_getUserMedia";
      throw err;
    }
    global.BrowserTts?.unlockBrowserSpeechOutput?.();
    mediaStream = await openMicStream();
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    if (audioContext.state === "suspended") {
      await audioContext.resume();
    }
    captureSampleRate = audioContext.sampleRate || TARGET_SAMPLE_RATE;
    const source = audioContext.createMediaStreamSource(mediaStream);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);

    // ScriptProcessor：采集 PCM 供 WAV/FunASR（兼容性优先）
    const bufferSize = 4096;
    captureNode = audioContext.createScriptProcessor(bufferSize, 1, 1);
    silenceGain = audioContext.createGain();
    silenceGain.gain.value = 0;
    captureNode.onaudioprocess = (ev) => {
      const input = ev.inputBuffer.getChannelData(0);
      // 聆听开启且未因 TTS 暂停时持续写入 pre-roll（与是否已开 turn 无关）
      if (autoListenEnabled && !asrPausedForTts) {
        pushPreroll(input);
      }
      if (!capturingTurn) return;
      onPcmFrame(input);
    };
    source.connect(captureNode);
    captureNode.connect(silenceGain);
    silenceGain.connect(audioContext.destination);

    micBlocked = false;
    autoListenEnabled = true;
    usingBrowserSpeechFallback = false;
    setListenButtonState();
    setStatus(listenIdleStatus());
    meterFrame = window.requestAnimationFrame(meterTick);
  }

  function failMicAndStop(kind, logLabel, detail) {
    console.warn(logLabel || "麦克风不可用", detail || kind);
    micBlocked = kind === "denied" || kind === "insecure";
    autoListenEnabled = false;
    stopBrowserSpeechFallback();
    releaseAudioGraph(false);
    usingBrowserSpeechFallback = false;
    setListenButtonState();
    setStatus(micHelpMessage(kind));
  }

  function stopBrowserSpeechFallback() {
    if (!speechRec) return;
    try {
      speechRec.onend = null;
      speechRec.stop();
    } catch (_) {}
    speechRecActive = false;
    speechRec = null;
  }

  function startBrowserSpeechFallback() {
    if (!isMicContextOk()) {
      failMicAndStop("insecure", "浏览器识别跳过：非安全上下文");
      return false;
    }
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) return false;
    try {
      global.BrowserTts?.unlockBrowserSpeechOutput?.();
      speechRec = new Ctor();
      speechRec.lang = "zh-CN";
      speechRec.interimResults = true;
      speechRec.continuous = true;
      let finalText = "";
      speechRec.onresult = (event) => {
        if (!autoListenEnabled || dialogueBusy || asrPausedForTts) return;
        let interim = "";
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const piece = event.results[i][0].transcript || "";
          if (event.results[i].isFinal) finalText += piece;
          else interim += piece;
        }
        setStatus(`正在听：${finalText || interim || "…"}`);
        if (finalText.trim().length >= 2) {
          const text = finalText.trim();
          finalText = "";
          cooldownUntil = Date.now() + COOLDOWN_MS;
          emitDialogueText(text);
        }
      };
      speechRec.onerror = (ev) => {
        console.warn("SpeechRecognition error", ev);
        speechRecActive = false;
        const code = (ev && ev.error) || "unknown";
        // aborted / no-speech：连续模式下可忽略
        if (code === "aborted" || code === "no-speech") return;
        const kind = classifyMicFailure(code);
        if (kind === "denied" || kind === "insecure") {
          // 优先改走 FunASR（getUserMedia→VAD→WAV），不再展示英文 not-allowed
          stopBrowserSpeechFallback();
          usingBrowserSpeechFallback = false;
          void (async () => {
            try {
              await startFunasrAutoListen();
            } catch (err) {
              failMicAndStop(
                classifyMicFailure(err) === "other" ? kind : classifyMicFailure(err),
                "SpeechRecognition not-allowed 后 FunASR 仍失败",
                err
              );
            }
          })();
          return;
        }
        if (autoListenEnabled && !dialogueBusy) {
          if (kind === "unavailable") {
            setStatus(micHelpMessage("unavailable"));
          } else {
            setStatus("识别暂时失败，请再说一次或改用打字。");
          }
        }
      };
      speechRec.onend = () => {
        speechRecActive = false;
        if (
          autoListenEnabled &&
          usingBrowserSpeechFallback &&
          !dialogueBusy &&
          !asrPausedForTts &&
          !micBlocked
        ) {
          try {
            speechRec.start();
            speechRecActive = true;
          } catch (err) {
            console.warn("重启浏览器识别失败", err);
          }
        }
      };
      speechRec.start();
      speechRecActive = true;
      micBlocked = false;
      autoListenEnabled = true;
      usingBrowserSpeechFallback = true;
      setListenButtonState();
      setStatus(listenIdleStatus());
      return true;
    } catch (err) {
      console.warn("无法启动浏览器语音识别", err);
      const kind = classifyMicFailure(err);
      if (kind === "denied" || kind === "insecure") {
        failMicAndStop(kind, "无法启动浏览器语音识别", err);
      }
      return false;
    }
  }

  function fallbackAfterLocalSttFailure(errorText) {
    if (usingBrowserSpeechFallback) return false;
    if (!/(voice_service|funasr|LOCAL_MODEL|model.*(?:error|unavailable|pending))/i.test(errorText)) {
      return false;
    }
    console.warn("本地语音模型不可用，切换浏览器语音识别", errorText);
    releaseAudioGraph(false);
    autoListenEnabled = true;
    if (startBrowserSpeechFallback()) {
      setStatus("本地语音模型不可用，已切换浏览器识别，请继续说");
      return true;
    }
    autoListenEnabled = false;
    setListenButtonState();
    setStatus("本地语音模型未安装；请安装 FunASR，或改用支持语音识别的 Chrome");
    return true;
  }

  async function startAutoListen() {
    if (autoListenEnabled) return;
    if (!bindResultHandler()) {
      setStatus("未连接");
      return;
    }
    // 必须由用户点击「开始自动聆听」触发，才能弹出麦克风权限框
    if (!isMicContextOk()) {
      failMicAndStop("insecure", "非安全上下文，无法请求麦克风");
      return;
    }
    micBlocked = false;
    try {
      await startFunasrAutoListen();
    } catch (err) {
      console.warn("FunASR 自动聆听启动失败", err);
      releaseAudioGraph(false);
      const kind = classifyMicFailure(err);
      // 权限/安全上下文失败时不要再走 SpeechRecognition（同样会 not-allowed）
      if (kind === "denied" || kind === "insecure" || kind === "unavailable") {
        failMicAndStop(kind, "FunASR 麦克风启动失败", err);
        return;
      }
      console.warn("尝试浏览器 SpeechRecognition 兜底", err);
      if (!startBrowserSpeechFallback()) {
        failMicAndStop("other", "麦克风不可用", err);
      }
    }
  }

  function stopAutoListen() {
    autoListenEnabled = false;
    stopBrowserSpeechFallback();
    releaseAudioGraph(false);
    usingBrowserSpeechFallback = false;
    setListenButtonState();
    setStatus("已停止聆听");
  }

  function pauseAsrForTts() {
    asrPausedForTts = true;
    if (capturingTurn) {
      capturingTurn = false;
      pcmChunks = [];
    }
    clearPreroll();
    if (usingBrowserSpeechFallback) {
      stopBrowserSpeechFallback();
    }
    setListenButtonState();
    if (autoListenEnabled) setStatus("朗读中，暂停聆听…");
  }

  function resumeAsrAfterTts() {
    asrPausedForTts = false;
    cooldownUntil = Date.now() + COOLDOWN_MS;
    setListenButtonState();
    maybeResumeListening();
  }

  function maybeResumeListening() {
    if (!autoListenEnabled || dialogueBusy || asrPausedForTts || micBlocked) return;
    if (usingBrowserSpeechFallback) {
      if (!speechRecActive) startBrowserSpeechFallback();
      else setStatus(listenIdleStatus());
      return;
    }
    if (mediaStream && analyser) {
      setStatus(listenIdleStatus());
      if (meterFrame == null) meterFrame = window.requestAnimationFrame(meterTick);
      return;
    }
    // 无流时不自动重新 getUserMedia（需用户再次点击，才能弹出权限）
    setStatus("请点击「开始自动聆听」以启用麦克风");
    autoListenEnabled = false;
    setListenButtonState();
  }

  function sendTextFromInput() {
    const input = document.getElementById("dialogueTextInput");
    if (!input) return;
    const text = input.value;
    if (emitDialogueText(text)) {
      input.value = "";
    }
  }

  function bindResultHandler() {
    if (resultHandlerBound) return true;
    const socket = getSocket();
    if (!socket) return false;
    socket.on("child_dialogue_result", (data) => {
      dialogueBusy = false;
      cooldownUntil = Date.now() + COOLDOWN_MS;
      setListenButtonState();
      if (!data || !data.ok) {
        const err = String((data && data.error) || "unknown");
        childBubbleLoggedForPending = false;
        if (fallbackAfterLocalSttFailure(err)) {
          return;
        }
        if (err === "not_awake") {
          setDialogueAwake(false, { updateStatus: false });
          const transcript = String((data && data.transcript) || "").trim();
          // 未唤醒也展示儿童识别文本（关键词表扬常走此路径之外，仍须可见）
          if (transcript && !childBubbleLoggedForPending) {
            appendChildTranscript(transcript);
          }
          childBubbleLoggedForPending = false;
          setStatus("请说：麦麦，麦麦");
          maybeResumeListening();
          return;
        }
        if (/EMPTY|empty|no_speech|audio_too_short/i.test(err)) {
          setStatus("没听清，继续说…");
        } else {
          setStatus(`对话失败: ${err}`);
        }
        maybeResumeListening();
        return;
      }
      if (Object.prototype.hasOwnProperty.call(data, "awake")) {
        setDialogueAwake(!!data.awake, { updateStatus: false });
      } else if (data.wake) {
        setDialogueAwake(true, { updateStatus: false });
      }
      const transcript = String(data.transcript || "").trim();
      const replyText = String(
        (data.reply && (data.reply.reply || data.reply.text)) || ""
      ).trim();
      // 语音识别：结果里才有 transcript；打字发送已记过儿童气泡
      if (transcript && !childBubbleLoggedForPending) {
        appendChildTranscript(transcript);
      }
      if (replyText) {
        appendDialogueLog("maimai", replyText);
      }
      childBubbleLoggedForPending = false;
      const provider = data.sttProvider ? ` [${data.sttProvider}]` : "";
      if (data.wake && data.reply && data.reply.strategy === "wake_ack") {
        setStatus("已唤醒，可以说了");
      } else if (replyText) {
        setStatus(`你说：${transcript}${provider} → ${replyText}`);
      } else {
        setStatus(`你说：${transcript}${provider}`);
      }
      // 兜底：若 robot_speak_text 未到（未 pauseAsr），本地补读，避免「有字无声」
      if (replyText) {
        const speakFallback = replyText;
        window.setTimeout(() => {
          if (asrPausedForTts) return;
          if (global.BrowserTts?.isBrowserSpeechBusy?.()) return;
          if (!global.BrowserTts?.isBrowserSpeechSynthesisSupported?.()) return;
          console.warn("[child_dialogue] robot_speak_text 未触发，本地补读");
          pauseAsrForTts();
          global.BrowserTts.unlockBrowserSpeechOutput?.();
          global.BrowserTts.speakBrowserText(speakFallback, {
            onEnd: () => resumeAsrAfterTts(),
            onError: () => resumeAsrAfterTts(),
          });
        }, 1800);
      }
      // 若即将朗读，由 pauseAsrForTts 接管；否则恢复聆听
      if (!asrPausedForTts) {
        maybeResumeListening();
      }
    });
    socket.on("child_dialogue_wake_state", (data) => {
      setDialogueAwake(!!(data && data.awake), { updateStatus: true });
    });
    socket.on("child_dialogue_visibility", (data) => {
      applyDialoguePanelVisibility(!data || data.visible !== false);
    });
    socket.on("child_dialogue_control_state", (data) => {
      if (!data) return;
      wakeWordEnabled = data.wakeWordEnabled === true;
      applyDialoguePanelVisibility(data.visible !== false);
      setStatus(listenIdleStatus());
    });
    // 连续 ASR 识别文本（含错答/未命中）；与 child_dialogue_result 短窗去重
    socket.on("child_speech_recognized", (data) => {
      if (!data) return;
      const sid = String(data.sessionId || data.session_id || "").trim();
      const mine = String(getSessionId() || "").trim();
      if (sid && mine && sid !== mine) return;
      const transcript = String(data.transcript || "").trim();
      if (!transcript) return;
      appendChildTranscript(transcript);
    });
    requestDialogueControlState();
    resultHandlerBound = true;
    setStatus(listenIdleStatus());
    updateSleepButton();
    return true;
  }

  function waitForSocketAndBind(retries) {
    if (bindResultHandler()) return;
    if (retries <= 0) {
      setStatus("未连接，请刷新页面");
      return;
    }
    setTimeout(() => waitForSocketAndBind(retries - 1), 200);
  }

  function bindDialogueUi() {
    if (uiBound) return;
    const panel = document.getElementById("dialoguePanel");
    const btn = document.getElementById("dialogueHoldBtn");
    const unlockBtn = document.getElementById("dialogueUnlockBtn");
    const collapseBtn = document.getElementById("dialogueCollapseBtn");
    const sleepBtn = document.getElementById("dialogueSleepBtn");
    const voiceSelect = document.getElementById("dialogueVoiceSelect");
    const sendBtn = document.getElementById("dialogueSendBtn");
    const textInput = document.getElementById("dialogueTextInput");
    if (!panel || !btn) {
      console.warn("[child_dialogue] dialoguePanel 未找到");
      return;
    }
    uiBound = true;
    applyDialoguePanelVisibility(dialoguePanelVisible);
    try {
      dialoguePanelCollapsed = localStorage.getItem(PANEL_COLLAPSED_KEY) === "1";
    } catch (_) { /* storage may be disabled */ }
    applyDialoguePanelCollapsed(dialoguePanelCollapsed, false);
    panel.style.zIndex = "5000";
    setListenButtonState();
    updateSleepButton();
    lastPageFingerprint = pageContextFingerprint(buildPageContext());

    if (unlockBtn) {
      unlockBtn.addEventListener("click", () => {
        global.BrowserTts?.unlockBrowserSpeechOutput?.();
        setStatus("声音已启用");
      });
    }
    if (collapseBtn) {
      collapseBtn.addEventListener("click", () => {
        applyDialoguePanelCollapsed(!dialoguePanelCollapsed, true);
      });
    }
    if (sleepBtn) {
      sleepBtn.addEventListener("click", () => {
        emitDialogueSleep("manual_sleep");
        setStatus("请说：麦麦，麦麦");
      });
    }
    btn.addEventListener("click", async (ev) => {
      ev.preventDefault();
      if (!bindResultHandler()) {
        setStatus("未连接");
        return;
      }
      global.BrowserTts?.unlockBrowserSpeechOutput?.();
      if (autoListenEnabled) {
        stopAutoListen();
        return;
      }
      // 用户手势内请求麦克风（Chrome 权限弹窗要求）
      setStatus("正在请求麦克风权限…");
      await startAutoListen();
    });
    if (sendBtn) {
      sendBtn.addEventListener("click", () => {
        if (!bindResultHandler()) {
          setStatus("未连接");
          return;
        }
        global.BrowserTts?.unlockBrowserSpeechOutput?.();
        sendTextFromInput();
      });
    }
    if (textInput) {
      textInput.addEventListener("keydown", (ev) => {
        if (ev.key !== "Enter") return;
        ev.preventDefault();
        if (!bindResultHandler()) {
          setStatus("未连接");
          return;
        }
        global.BrowserTts?.unlockBrowserSpeechOutput?.();
        sendTextFromInput();
      });
    }
    if (voiceSelect && global.BrowserTts) {
      const fill = () => {
        const options = global.BrowserTts.loadBrowserSpeechVoices();
        voiceSelect.innerHTML = "";
        options.forEach((opt) => {
          const el = document.createElement("option");
          el.value = opt.name;
          el.textContent = opt.label;
          voiceSelect.appendChild(el);
        });
        const preferred = global.BrowserTts.getPreferredBrowserSpeechVoiceName();
        if (preferred) voiceSelect.value = preferred;
      };
      fill();
      global.BrowserTts.subscribeBrowserSpeechVoiceChanges(fill);
      voiceSelect.addEventListener("change", () => {
        global.BrowserTts.setPreferredBrowserSpeechVoice(voiceSelect.value);
      });
    }

    // 课点 / 互动页切换时同步退出唤醒
    window.addEventListener("message", (event) => {
      const data = event && event.data;
      if (!data || typeof data !== "object") return;
      if (data.type === "interactive_page_context") {
        setTimeout(() => syncAwakeForPageContext(), 0);
      }
    });
    const socket = getSocket();
    if (socket) {
      socket.on("play_resource", (payload) => {
        requestDialogueControlState(payload && (payload.sessionId || payload.session_id));
        setTimeout(() => syncAwakeForPageContext(), 50);
      });
      socket.on("training_prepare", (payload) => {
        requestDialogueControlState(payload && (payload.sessionId || payload.session_id));
      });
      socket.on("interactive_page_context", () => {
        setTimeout(() => syncAwakeForPageContext(), 0);
      });
    }

    waitForSocketAndBind(50);
    checkVoiceHealth();
    console.log("[child_dialogue] UI 已绑定：唤醒词「麦麦，麦麦」→ FunASR → LLM");
  }

  global.ChildDialogue = {
    startAutoListen,
    stopAutoListen,
    pauseAsrForTts,
    resumeAsrAfterTts,
    bindDialogueUi,
    buildPageContext,
    emitDialogueText,
    appendDialogueLog,
    syncAwakeForPageContext,
    isAwake: () => dialogueAwake,
    sleep: () => emitDialogueSleep("manual_sleep"),
    // 兼容旧名
    startDialogueRecording: startAutoListen,
    stopDialogueRecording: stopAutoListen,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindDialogueUi);
  } else {
    setTimeout(bindDialogueUi, 0);
  }
})(window);
