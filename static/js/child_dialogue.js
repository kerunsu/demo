/**
 * 儿童端自由对话：浏览器 SpeechRecognition → 课程关键词/LLM → browser TTS。
 * 生产儿童端只发送已识别文本，不采集或上传 WAV，也不依赖本地 ASR 模型。
 */
(function (global) {
  const COOLDOWN_MS = 180;

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
  /** 防止浏览器连续识别在重启边界把同一最终句再次提交给 LLM。 */
  let lastSubmittedTranscriptKey = "";
  let lastSubmittedTranscriptAt = 0;
  let lastSubmittedFingerprint = "";
  const SUBMITTED_TRANSCRIPT_DEDUPE_MS = 8000;
  let recognitionMinConfidence = 0.55;
  /** 本地唤醒状态（与服务端 session+题目指纹绑定；题目切换后清除） */
  let dialogueAwake = false;
  let wakeWordEnabled = false;
  let activeCourseSessionId = null;
  // Server 对话台在未开课时分配的精确待机会话。开课后立即让位给正式会话。
  let standbyDialogueSessionId = null;
  let lastPageFingerprint = "";
  let lastFingerprintCheckAt = 0;

  /** 朗读中浏览器已经识别的回答：等 TTS 结束再发送，不打断麦麦。 */
  let pendingTtsTranscript = "";
  let pendingTtsTranscriptReference = "";
  let activeTtsReferenceText = "";

  let speechRec = null;
  let speechRecActive = false;
  let speechRecRestartTimer = null;
  let speechRecGeneration = 0;
  /** 麦克风曾被拒绝/不安全上下文：禁止无点击自动重试 */
  let micBlocked = false;

  function getSocket() {
    return global.socket || null;
  }

  function getSessionId() {
    return activeCourseSessionId || global.currentSessionId || standbyDialogueSessionId || null;
  }

  function makeDialogueRequestId() {
    const random = Math.random().toString(36).slice(2, 10);
    return `dialogue-turn-${Date.now()}-${random}`;
  }

  function emitDialogueLatency(phase, requestId, detail = {}) {
    const socket = getSocket();
    if (!socket || !socket.connected || !requestId) return;
    socket.emit("dialogue_latency_event", {
      sessionId: getSessionId(),
      requestId,
      phase,
      clientTimestamp: Date.now(),
      ...detail,
    });
  }

  function requestDialogueControlState(sessionId) {
    const socket = getSocket();
    if (!socket) return;
    socket.emit("child_dialogue_control_state_request", {
      sessionId: sessionId || getSessionId(),
      pageContext: buildPageContext(),
      clientTimestamp: Date.now(),
    });
  }

  function buildPageContext() {
    const interactive = global.interactivePageContext || null;
    const base = {
      courseType: global.currentCourseType || "",
      courseId: global.currentCourseId || null,
      itemId: global.currentItemId || null,
      questionId: global.currentQuestionId || null,
      prompt: global.currentQuestionPrompt || "",
      target: global.currentSpeechTarget || "",
      speechTarget: global.currentSpeechTarget || "",
      objectName: global.currentItemName || "",
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
    const courseId = String(ctx.courseId || ctx.course_id || "").trim();
    const qid = String(ctx.questionId || ctx.question_id || "").trim();
    const itemId = String(
      ctx.itemId != null ? ctx.itemId : ctx.item_id != null ? ctx.item_id : ""
    ).trim();
    let qIndex = ctx.questionIndex;
    if (qIndex == null) qIndex = ctx.question_index;
    return [courseType, courseId, qid, itemId, qIndex != null ? String(qIndex) : ""].join("|");
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

  function emitDialogueRuntimeState(extra) {
    const socket = getSocket();
    if (!socket || !socket.connected) return;
    const voices = global.BrowserTts?.loadBrowserSpeechVoices?.() || [];
    socket.emit("child_dialogue_runtime_state", {
      sessionId: getSessionId(),
      pageContext: buildPageContext(),
      awake: dialogueAwake,
      listening: autoListenEnabled && !micBlocked,
      recognitionActive: speechRecActive,
      microphoneBlocked: micBlocked,
      voices,
      selectedVoice: global.BrowserTts?.getPreferredBrowserSpeechVoiceName?.() || "",
      voiceAvailable: global.BrowserTts?.isFixedBrowserSpeechVoiceAvailable?.() === true,
      clientTimestamp: Date.now(),
      ...(extra || {}),
    });
  }

  function ensureListeningAfterTeacherWake(requestId) {
    lastPageFingerprint = pageContextFingerprint(buildPageContext());
    if (micBlocked) {
      setStatus("已唤醒，请在儿童端允许麦克风");
      emitDialogueRuntimeState({ requestId, reason: "microphone_blocked" });
      return false;
    }
    if (autoListenEnabled) {
      maybeResumeListening();
      emitDialogueRuntimeState({ requestId, reason: "already_listening" });
      return true;
    }
    const started = startBrowserSpeechRecognition();
    if (!started) {
      setStatus("已唤醒，请点“开始自动聆听”并允许麦克风");
    }
    emitDialogueRuntimeState({
      requestId,
      reason: started ? "teacher_wake_started" : "microphone_start_failed",
    });
    return started;
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
    if (asrPausedForTts) return "朗读中，仍在聆听…";
    if (dialogueBusy) return dialogueAwake ? "思考中…" : (wakeWordEnabled ? "请说唤醒词" : "等待教师唤醒");
    if (dialogueAwake) return "已唤醒，可以说了";
    return wakeWordEnabled ? "请说：麦麦" : "等待教师端点击唤醒智能体";
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

  /** 兼容 child.js 调用；可见对话日志已经迁移到 Server 房间。 */
  function appendDialogueLog(_role, text) {
    return Boolean(String(text || "").trim());
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
      btn.textContent = asrPausedForTts
        ? "朗读中仍在聆听"
        : (dialogueBusy ? "识别中…" : "停止自动聆听");
      btn.classList.add("is-listening");
    } else {
      btn.textContent = "开始自动聆听";
      btn.classList.remove("is-listening");
    }
  }

  function getSpeechRecognitionCtor() {
    return global.SpeechRecognition || global.webkitSpeechRecognition || null;
  }

  function emitDialogueText(text, recognitionProvider = "") {
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
    const transcriptKey = normalizeTranscriptKey(trimmed);
    const fingerprint = pageContextFingerprint(buildPageContext());
    const now = Date.now();
    if (
      recognitionProvider &&
      transcriptKey &&
      transcriptKey === lastSubmittedTranscriptKey &&
      fingerprint === lastSubmittedFingerprint &&
      now - lastSubmittedTranscriptAt < SUBMITTED_TRANSCRIPT_DEDUPE_MS
    ) {
      console.warn("[child_dialogue] 忽略浏览器重复最终识别：", trimmed);
      setStatus("已过滤重复识别，继续聆听…");
      maybeResumeListening();
      return false;
    }
    lastSubmittedTranscriptKey = transcriptKey;
    lastSubmittedTranscriptAt = now;
    lastSubmittedFingerprint = fingerprint;
    dialogueBusy = true;
    childBubbleLoggedForPending = true;
    appendChildTranscript(trimmed);
    setListenButtonState();
    setStatus(dialogueAwake ? "思考中…" : "识别唤醒中…");
    const requestId = makeDialogueRequestId();
    const sentAtClientMs = Date.now();
    socket.emit("child_dialogue_text", {
      sessionId: getSessionId(),
      requestId,
      text: trimmed,
      ...(recognitionProvider ? { recognitionProvider } : {}),
      pageContext: buildPageContext(),
      clientTiming: { sentAtClientMs },
    });
    return true;
  }

  function failMicAndStop(kind, logLabel, detail) {
    console.warn(logLabel || "麦克风不可用", detail || kind);
    micBlocked = kind === "denied" || kind === "insecure";
    autoListenEnabled = false;
    stopBrowserSpeechRecognition();
    setListenButtonState();
    setStatus(micHelpMessage(kind));
    if (dialogueAwake) {
      emitDialogueRuntimeState({ reason: `microphone_${kind || "failed"}` });
    }
  }

  function stopBrowserSpeechRecognition() {
    speechRecGeneration += 1;
    if (speechRecRestartTimer) {
      clearTimeout(speechRecRestartTimer);
      speechRecRestartTimer = null;
    }
    const recognition = speechRec;
    speechRec = null;
    speechRecActive = false;
    if (!recognition) return;
    try {
      recognition.onresult = null;
      recognition.onerror = null;
      recognition.onend = null;
      if (typeof recognition.abort === "function") recognition.abort();
      else recognition.stop();
    } catch (_) {}
  }

  function scheduleSpeechRecognitionRestart(reason, delayMs = 260) {
    if (
      speechRecRestartTimer ||
      !autoListenEnabled ||
      dialogueBusy ||
      asrPausedForTts ||
      micBlocked
    ) return;
    const generation = speechRecGeneration;
    speechRecRestartTimer = setTimeout(() => {
      speechRecRestartTimer = null;
      if (
        generation !== speechRecGeneration ||
        !autoListenEnabled ||
        dialogueBusy ||
        asrPausedForTts ||
        micBlocked ||
        speechRecActive
      ) return;
      console.debug("[child_dialogue] 重启浏览器识别", reason || "ended");
      startBrowserSpeechRecognition();
    }, Math.max(0, Number(delayMs) || 0));
  }

  function startBrowserSpeechRecognition() {
    if (!isMicContextOk()) {
      failMicAndStop("insecure", "浏览器识别跳过：非安全上下文");
      return false;
    }
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) return false;
    if (speechRecActive) return true;
    if (speechRecRestartTimer) {
      clearTimeout(speechRecRestartTimer);
      speechRecRestartTimer = null;
    }
    if (speechRec) {
      const staleRecognition = speechRec;
      speechRec = null;
      try {
        staleRecognition.onresult = null;
        staleRecognition.onerror = null;
        staleRecognition.onend = null;
        if (typeof staleRecognition.abort === "function") staleRecognition.abort();
      } catch (_) {}
    }
    try {
      global.BrowserTts?.unlockBrowserSpeechOutput?.();
      const recognition = new Ctor();
      speechRec = recognition;
      recognition.lang = "zh-CN";
      recognition.interimResults = true;
      recognition.continuous = true;
      let finalText = "";
      let finalConfidenceSum = 0;
      let finalConfidenceCount = 0;
      recognition.onresult = (event) => {
        if (speechRec !== recognition) return;
        if (!autoListenEnabled || dialogueBusy) return;
        const browserSpeechBusy = Boolean(
          global.BrowserTts?.isBrowserSpeechBusy?.(),
        );
        const ttsIsActive = asrPausedForTts || browserSpeechBusy;
        let interim = "";
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const piece = event.results[i][0].transcript || "";
          if (event.results[i].isFinal) {
            finalText += piece;
            const confidence = Number(event.results[i][0].confidence);
            if (Number.isFinite(confidence) && confidence > 0) {
              finalConfidenceSum += confidence;
              finalConfidenceCount += 1;
            }
          } else interim += piece;
        }
        setStatus(ttsIsActive
          ? `朗读中，仍在听：${finalText || interim || "…"}`
          : `正在听：${finalText || interim || "…"}`);
        if (finalText.trim().length >= 2) {
          const text = finalText.trim();
          const confidence = finalConfidenceCount > 0
            ? finalConfidenceSum / finalConfidenceCount
            : null;
          finalText = "";
          finalConfidenceSum = 0;
          finalConfidenceCount = 0;
          if (confidence != null && confidence < recognitionMinConfidence) {
            console.warn("[child_dialogue] 过滤低置信度浏览器识别", confidence, text);
            setStatus("环境声音较杂，没有作为回答提交…");
            emitDialogueRuntimeState({
              reason: "low_confidence_ignored",
              recognitionConfidence: confidence,
            });
            return;
          }
          if (ttsIsActive) {
            if (!pendingTtsTranscript) {
              pendingTtsTranscript = text;
              pendingTtsTranscriptReference = activeTtsReferenceText;
            }
            setStatus("已听到，朗读结束后识别…");
          } else {
            cooldownUntil = Date.now() + COOLDOWN_MS;
            emitDialogueText(text, "browser-speech-recognition");
          }
        }
      };
      recognition.onerror = (ev) => {
        if (speechRec !== recognition) return;
        console.warn("SpeechRecognition error", ev);
        speechRecActive = false;
        const code = (ev && ev.error) || "unknown";
        // Chrome 连续识别遇到静音或内部中止后通常还会结束当前实例；
        // 延迟创建下一实例，避免在 onend 回调内同步 start() 的状态竞争。
        if (code === "aborted" || code === "no-speech") {
          scheduleSpeechRecognitionRestart(code);
          return;
        }
        const kind = classifyMicFailure(code);
        if (kind === "denied" || kind === "insecure") {
          stopBrowserSpeechRecognition();
          failMicAndStop(kind, "浏览器语音识别权限不可用", code);
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
      recognition.onend = () => {
        if (speechRec !== recognition) return;
        speechRecActive = false;
        speechRec = null;
        scheduleSpeechRecognitionRestart("ended");
      };
      recognition.start();
      speechRecActive = true;
      micBlocked = false;
      autoListenEnabled = true;
      setListenButtonState();
      setStatus(listenIdleStatus());
      if (dialogueAwake) emitDialogueRuntimeState({ reason: "recognition_started" });
      return true;
    } catch (err) {
      console.warn("无法启动浏览器语音识别", err);
      if (speechRec) {
        try {
          speechRec.onresult = null;
          speechRec.onerror = null;
          speechRec.onend = null;
        } catch (_) {}
      }
      speechRec = null;
      speechRecActive = false;
      const kind = classifyMicFailure(err);
      if (kind === "denied" || kind === "insecure") {
        failMicAndStop(kind, "无法启动浏览器语音识别", err);
      } else if (autoListenEnabled) {
        scheduleSpeechRecognitionRestart("start_failed", 500);
      }
      return false;
    }
  }

  function startAutoListen(reason = "manual_start") {
    if (autoListenEnabled) {
      maybeResumeListening();
      emitDialogueRuntimeState({ reason: `${reason}_already_listening` });
      return true;
    }
    if (!bindResultHandler()) {
      setStatus("未连接");
      return false;
    }
    // 必须由用户点击「开始自动聆听」触发，才能弹出麦克风权限框
    if (!isMicContextOk()) {
      failMicAndStop("insecure", "非安全上下文，无法请求麦克风");
      return false;
    }
    micBlocked = false;
    if (!getSpeechRecognitionCtor()) {
      failMicAndStop("unavailable", "当前浏览器不支持语音识别");
      return false;
    }
    if (!startBrowserSpeechRecognition()) {
      failMicAndStop("other", "无法启动浏览器语音识别");
      return false;
    }
    emitDialogueRuntimeState({ reason });
    return true;
  }

  function stopAutoListen(reason = "manual_stop") {
    autoListenEnabled = false;
    stopBrowserSpeechRecognition();
    pendingTtsTranscript = "";
    pendingTtsTranscriptReference = "";
    activeTtsReferenceText = "";
    setListenButtonState();
    setStatus("已停止聆听");
    emitDialogueRuntimeState({ reason });
    return true;
  }

  function pauseAsrForTts(spokenText = "") {
    asrPausedForTts = true;
    const reference = String(spokenText || "").trim().slice(0, 500);
    if (reference) activeTtsReferenceText = reference;
    setListenButtonState();
    if (autoListenEnabled) setStatus("朗读中，仍在聆听…");
  }

  function isLikelyTtsEcho(transcript, referenceText) {
    const normalize = (value) => String(value || "")
      .replace(/[\s\u3000，。！？、；：,.!?;:'"“”‘’（）()\[\]【】<>《》…—～~·]/g, "")
      .toLowerCase();
    const heard = normalize(transcript);
    const spoken = normalize(referenceText);
    return heard.length >= 2 && spoken.length >= 2 && (
      spoken.includes(heard) || heard.includes(spoken)
    );
  }

  function resumeAsrAfterTts() {
    asrPausedForTts = false;
    const pendingTranscript = pendingTtsTranscript;
    const pendingTranscriptEchoReference = pendingTtsTranscriptReference;
    pendingTtsTranscript = "";
    pendingTtsTranscriptReference = "";
    activeTtsReferenceText = "";
    if (pendingTranscript) {
      if (isLikelyTtsEcho(pendingTranscript, pendingTranscriptEchoReference)) {
        cooldownUntil = Date.now() + COOLDOWN_MS;
        setStatus("已过滤扬声器回声，继续聆听…");
        setListenButtonState();
        maybeResumeListening();
        return;
      }
      cooldownUntil = 0;
      setListenButtonState();
      setStatus("正在识别刚才的回答…");
      emitDialogueText(pendingTranscript, "browser-speech-recognition");
      return;
    }
    cooldownUntil = Date.now() + COOLDOWN_MS;
    setListenButtonState();
    maybeResumeListening();
  }

  function maybeResumeListening() {
    if (!autoListenEnabled || dialogueBusy || asrPausedForTts || micBlocked) return;
    if (!speechRecActive) scheduleSpeechRecognitionRestart("resume", 0);
    else setStatus(listenIdleStatus());
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
      const dialogueRequestId = data && (data.requestId || data.request_id);
      emitDialogueLatency("result_received", dialogueRequestId, {
        status: data && data.ok ? "ok" : "error",
        provider: data && data.sttProvider,
      });
      dialogueBusy = false;
      cooldownUntil = Date.now() + COOLDOWN_MS;
      setListenButtonState();
      if (!data || !data.ok) {
        const err = String((data && data.error) || "unknown");
        childBubbleLoggedForPending = false;
        if (err === "not_awake") {
          setDialogueAwake(false, { updateStatus: false });
          const transcript = String((data && data.transcript) || "").trim();
          // 未唤醒也展示儿童识别文本（关键词表扬常走此路径之外，仍须可见）
          if (transcript && !childBubbleLoggedForPending) {
            appendChildTranscript(transcript);
          }
          childBubbleLoggedForPending = false;
          setStatus("请说：麦麦");
          maybeResumeListening();
          return;
        }
        if (err === "agent_stopped") {
          setDialogueAwake(false, { updateStatus: false });
          setStatus("智能体已停止，仍在聆听…");
          maybeResumeListening();
          return;
        }
        if (/duplicate_utterance/i.test(err)) {
          setStatus("已过滤重复识别，继续说…");
        } else if (/tts_echo/i.test(err)) {
          setStatus("已过滤扬声器回声，继续说…");
        } else if (/EMPTY|empty|no_speech|audio_too_short|implausible_transcript/i.test(err)) {
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
      // 朗读只接受带 behavior/request 身份的 robot_speak_text。旧的本地
      // 补读会与行为锁释放后的排队命令重复播放，不能保留第二条通路。
      if (!asrPausedForTts) {
        maybeResumeListening();
      }
    });
    socket.on("child_dialogue_wake_state", (data) => {
      const awake = !!(data && data.awake);
      setDialogueAwake(awake, { updateStatus: true });
      if (awake) {
        ensureListeningAfterTeacherWake(data && data.requestId);
      } else {
        // “停止智能体”只关闭回复门，不关闭课程期内的连续识别。
        dialogueBusy = false;
        childBubbleLoggedForPending = false;
        setListenButtonState();
        maybeResumeListening();
        emitDialogueRuntimeState({
          requestId: data && data.requestId,
          reason: (data && data.reason) || "agent_closed",
        });
      }
    });
    socket.on("child_dialogue_control_state", (data) => {
      if (!data) return;
      wakeWordEnabled = data.wakeWordEnabled === true;
      setDialogueAwake(data.awake === true, { updateStatus: false });
      if (data.awake === true) {
        ensureListeningAfterTeacherWake(data.requestId);
      } else {
        setStatus(listenIdleStatus());
      }
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

  function beginCourseListening(payload, reason) {
    const sessionId = String(payload?.sessionId || payload?.session_id || "").trim();
    if (sessionId) {
      activeCourseSessionId = sessionId;
      standbyDialogueSessionId = null;
    }
    requestDialogueControlState(sessionId || getSessionId());
    startAutoListen(reason || "course_started");
    window.setTimeout(() => emitDialogueRuntimeState({ reason: reason || "course_started" }), 0);
  }

  function endCourseListening(payload, reason) {
    const sessionId = String(payload?.sessionId || payload?.session_id || "").trim();
    if (sessionId && activeCourseSessionId && sessionId !== activeCourseSessionId) return;
    stopAutoListen(reason || "course_ended");
    if (dialogueAwake) emitDialogueSleep(reason || "course_ended");
    activeCourseSessionId = null;
    standbyDialogueSessionId = null;
  }

  function bindDialogueRuntime() {
    if (uiBound) return;
    uiBound = true;
    lastPageFingerprint = pageContextFingerprint(buildPageContext());

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
        beginCourseListening(payload, "course_resource_active");
        setTimeout(() => syncAwakeForPageContext(), 50);
      });
      socket.on("training_prepare", (payload) => {
        beginCourseListening(payload, "course_started");
      });
      socket.on("training_prepare_cancel", (payload) => {
        endCourseListening(payload, "course_cancelled");
      });
      socket.on("stop_recording", (payload) => {
        endCourseListening(payload, payload?.reason || "course_ended");
      });
      socket.on("interactive_page_context", () => {
        setTimeout(() => syncAwakeForPageContext(), 0);
      });
      socket.on("child_dialogue_runtime_control", (payload) => {
        const sessionId = String(payload?.sessionId || "").trim();
        const courseSessionId = String(
          activeCourseSessionId || global.currentSessionId || "",
        ).trim();
        if (sessionId && courseSessionId && sessionId !== courseSessionId) return;
        if (sessionId && !courseSessionId) standbyDialogueSessionId = sessionId;
        const action = String(payload?.action || "");
        if (action === "listen_start") startAutoListen("server_listen_start");
        else if (action === "listen_stop") stopAutoListen("server_listen_stop");
        else if (action === "unlock_audio") {
          global.BrowserTts?.unlockBrowserSpeechOutput?.();
          emitDialogueRuntimeState({ requestId: payload?.requestId, reason: "server_audio_unlock" });
        } else if (action === "set_voice") {
          // 一版兼容：旧 Server 可能仍发送该动作。音色已锁定，只回报状态。
          emitDialogueRuntimeState({ requestId: payload?.requestId, reason: "voice_locked" });
        } else if (action === "state_request") {
          emitDialogueRuntimeState({
            requestId: payload?.requestId,
            reason: "server_state_requested",
          });
        }
      });
      // 第一次状态上报可能早于 join_session；房间确认后必须补报一次。
      socket.on("joined_session", (payload) => {
        if (payload?.role && payload.role !== "child") return;
        const sessionId = String(payload?.sessionId || payload?.session_id || "").trim();
        if (sessionId && getSessionId() && sessionId !== String(getSessionId())) return;
        emitDialogueRuntimeState({ reason: "child_session_joined" });
      });
      socket.on("child_session_sync", (payload) => {
        const sessionId = String(payload?.sessionId || payload?.session_id || "").trim();
        if (sessionId && getSessionId() && sessionId !== String(getSessionId())) return;
        emitDialogueRuntimeState({ reason: "child_session_synced" });
      });
      socket.on("connect", () => {
        if (activeCourseSessionId) startAutoListen("socket_reconnected");
        else standbyDialogueSessionId = null;
        emitDialogueRuntimeState({ reason: "socket_connected" });
      });
    }

    global.BrowserTts?.subscribeBrowserSpeechVoiceChanges?.(() => {
      global.BrowserTts?.warmBrowserSpeechOutput?.();
      emitDialogueRuntimeState({ reason: "voices_changed" });
    });

    fetch("/api/child/runtime-config", { cache: "no-store" })
      .then((response) => response.json())
      .then((config) => {
        const value = Number(config?.dialogueAsrMinConfidence);
        if (Number.isFinite(value) && value >= 0 && value <= 1) {
          recognitionMinConfidence = value;
        }
      })
      .catch(() => undefined);

    waitForSocketAndBind(50);
    console.log("[child_dialogue] 运行时已绑定：课程生命周期 → 浏览器语音识别 → 唤醒词/课程关键词 → LLM");
  }

  global.ChildDialogue = {
    startAutoListen,
    stopAutoListen,
    pauseAsrForTts,
    resumeAsrAfterTts,
    bindDialogueRuntime,
    bindDialogueUi: bindDialogueRuntime,
    buildPageContext,
    emitDialogueText,
    emitDialogueLatency,
    appendDialogueLog,
    syncAwakeForPageContext,
    isAwake: () => dialogueAwake,
    sleep: () => emitDialogueSleep("manual_sleep"),
    // 兼容旧名
    startDialogueRecording: startAutoListen,
    stopDialogueRecording: stopAutoListen,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindDialogueRuntime);
  } else {
    setTimeout(bindDialogueRuntime, 0);
  }
})(window);
