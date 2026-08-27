/**
 * 浏览器 SpeechSynthesis TTS（对齐 DemoRobot audioPlayback.ts）
 * - 仅允许部署约定的 Microsoft Xiaoyi Online (Natural) 音色
 * - unlock 手势
 * - speakText / stop
 * - Chrome/Edge：cancel()+speak() 可能静默失败；canceled 事件会清掉回调 —— 需 watchdog 重试
 * - unlock 不得 cancel 正在播的正式朗读（切课提问常见竞态）
 */
(function (global) {
  const DEFAULT_SPEECH_RATE = 0.88;
  const fixedVoiceConfig = global.FIXED_BROWSER_TTS_VOICE || {};
  const FIXED_VOICE_NAME = String(fixedVoiceConfig.name || "");
  const FIXED_VOICE_MATCH_PREFIX = String(fixedVoiceConfig.matchPrefix || "");
  const FIXED_VOICE_LOCALIZED_TOKEN = String(fixedVoiceConfig.localizedToken || "");
  const FIXED_VOICE_LANG = String(fixedVoiceConfig.lang || "zh-CN");

  let availableVoices = [];
  let preferredVoice = null;
  let speechUnlocked = false;
  let speechWarmState = "cold";
  let warmWatchdog = null;
  let speakGeneration = 0;
  let activeSpeech = null;
  let currentSpeechRate = DEFAULT_SPEECH_RATE;
  const completedSpeechIds = new Map();
  const COMPLETED_SPEECH_TTL_MS = 2 * 60 * 1000;
  const COMPLETED_SPEECH_MAX = 256;
  const SPEECH_ENGINE_STARTUP_COMPENSATION_MS = 350;
  const FIXED_VOICE_LOAD_TIMEOUT_MS = 2500;
  const COLD_START_WATCHDOG_MS = 6500;
  const WARM_START_WATCHDOG_MS = 2200;

  function normalizeSpeechIdentity(options, content) {
    const speechId = String(options.speechId || options.speech_id || "").trim();
    const behaviorId = String(options.behaviorId || options.behavior_id || "").trim();
    const sequenceId = String(options.sequenceId || options.sequence_id || "").trim();
    const requestId = String(options.requestId || options.request_id || "").trim();
    const sessionId = String(options.sessionId || options.session_id || "").trim();
    return {
      speechId,
      behaviorId,
      sequenceId,
      requestId,
      sessionId,
      key: speechId || behaviorId || sequenceId || "",
      content,
    };
  }

  function pruneCompletedSpeechIds(now = Date.now()) {
    for (const [key, finishedAt] of completedSpeechIds) {
      if (now - finishedAt > COMPLETED_SPEECH_TTL_MS) {
        completedSpeechIds.delete(key);
      }
    }
    while (completedSpeechIds.size > COMPLETED_SPEECH_MAX) {
      completedSpeechIds.delete(completedSpeechIds.keys().next().value);
    }
  }

  function rememberCompletedSpeech(identity) {
    if (!identity || !identity.key) return;
    completedSpeechIds.set(identity.key, Date.now());
    pruneCompletedSpeechIds();
  }

  function isCompletedSpeech(identity) {
    if (!identity || !identity.key) return false;
    pruneCompletedSpeechIds();
    return completedSpeechIds.has(identity.key);
  }

  function sameSpeech(left, right) {
    if (!left || !right) return false;
    if (left.key && right.key) return left.key === right.key;
    return left.content === right.content;
  }

  function terminalDetail(identity, status, reason) {
    return {
      status,
      reason: reason || "",
      speechId: identity && identity.speechId,
      behaviorId: identity && (identity.behaviorId || identity.sequenceId),
      sequenceId: identity && identity.sequenceId,
      requestId: identity && identity.requestId,
      sessionId: identity && identity.sessionId,
    };
  }

  function getSpeechSynthesis() {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return null;
    return window.speechSynthesis;
  }

  function isFixedBrowserSpeechVoice(voice) {
    const name = String(voice?.name || "").trim().toLocaleLowerCase();
    const lang = String(voice?.lang || "").trim().toLocaleLowerCase();
    const prefix = FIXED_VOICE_MATCH_PREFIX.toLocaleLowerCase();
    const localized = FIXED_VOICE_LOCALIZED_TOKEN.toLocaleLowerCase();
    return Boolean(
      name && lang === FIXED_VOICE_LANG.toLocaleLowerCase() &&
      ((prefix && name.startsWith(prefix)) || (localized && name.includes(localized)))
    );
  }

  function loadBrowserSpeechVoices() {
    const synth = getSpeechSynthesis();
    if (!synth) {
      availableVoices = [];
      preferredVoice = null;
      return [];
    }
    preferredVoice = (synth.getVoices() || []).find(isFixedBrowserSpeechVoice) || null;
    availableVoices = preferredVoice ? [preferredVoice] : [];
    return availableVoices.map((v) => ({
      name: v.name,
      lang: v.lang,
      label: String(fixedVoiceConfig.label || FIXED_VOICE_NAME),
    }));
  }

  function subscribeBrowserSpeechVoiceChanges(onChange) {
    const synth = getSpeechSynthesis();
    if (!synth) return () => undefined;
    synth.addEventListener("voiceschanged", onChange);
    return () => synth.removeEventListener("voiceschanged", onChange);
  }

  function getPreferredBrowserSpeechVoiceName() {
    loadBrowserSpeechVoices();
    return preferredVoice ? preferredVoice.name : "";
  }

  function isFixedBrowserSpeechVoiceAvailable() {
    loadBrowserSpeechVoices();
    return Boolean(preferredVoice);
  }

  function normalizeSpeechRate(value, fallback = DEFAULT_SPEECH_RATE) {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed >= 0.5 && parsed <= 2
      ? Math.round(parsed * 100) / 100
      : fallback;
  }

  function setBrowserSpeechRate(value) {
    currentSpeechRate = normalizeSpeechRate(value, currentSpeechRate);
    return currentSpeechRate;
  }

  function getBrowserSpeechRate() {
    return currentSpeechRate;
  }

  function isBrowserSpeechSynthesisSupported() {
    return Boolean(getSpeechSynthesis());
  }

  function isBrowserSpeechUnlocked() {
    return speechUnlocked;
  }

  function warmBrowserSpeechOutput() {
    const synth = getSpeechSynthesis();
    if (!synth || speechWarmState === "ready") return;
    if (speechWarmState === "warming") {
      // A later user gesture (for example enabling the microphone) should
      // resume a warm-up that page-load autoplay policy may have suspended.
      if (typeof synth.resume === "function") {
        try { synth.resume(); } catch (_) {}
      }
      return;
    }
    loadBrowserSpeechVoices();
    if (!preferredVoice) return;
    // 正式朗读已经占用引擎时绝不 cancel；它自己的 onstart 会完成预热。
    if (synth.speaking || synth.pending) {
      return;
    }
    speechWarmState = "warming";
    const utterance = new SpeechSynthesisUtterance("。");
    utterance.lang = "zh-CN";
    utterance.volume = 0.01;
    utterance.rate = 10;
    utterance.voice = preferredVoice;
    const finishWarmup = () => {
      if (warmWatchdog != null) {
        clearTimeout(warmWatchdog);
        warmWatchdog = null;
      }
      speechUnlocked = true;
      speechWarmState = "ready";
    };
    utterance.onstart = finishWarmup;
    utterance.onend = finishWarmup;
    // Chrome 偶尔只回 error，但此时语音进程已经被拉起，可视为完成预热。
    utterance.onerror = (event) => {
      if (event && event.error === "not-allowed") {
        if (warmWatchdog != null) clearTimeout(warmWatchdog);
        warmWatchdog = null;
        speechWarmState = "cold";
        return;
      }
      finishWarmup();
    };
    try {
      synth.speak(utterance);
      if (typeof synth.resume === "function") synth.resume();
      warmWatchdog = window.setTimeout(() => {
        warmWatchdog = null;
        if (speechWarmState === "warming") {
          if (!activeSpeech) safeCancel(synth);
          speechWarmState = "cold";
        }
      }, COLD_START_WATCHDOG_MS);
    } catch (_) {
      speechWarmState = "cold";
    }
  }

  function unlockBrowserSpeechOutput() {
    warmBrowserSpeechOutput();
  }

  function stopBrowserSpeech() {
    const stopped = activeSpeech;
    speakGeneration += 1;
    if (stopped && typeof stopped.cancelAttempt === "function") {
      stopped.cancelAttempt();
    }
    if (stopped && stopped.retryTimer != null) {
      clearTimeout(stopped.retryTimer);
      stopped.retryTimer = null;
    }
    getSpeechSynthesis()?.cancel();
    if (stopped && activeSpeech === stopped) {
      activeSpeech = null;
      rememberCompletedSpeech(stopped.identity);
      stopped.options.onEnd?.(
        terminalDetail(stopped.identity, "stopped", "explicit_stop")
      );
    }
  }

  function cancelBrowserSpeechForBehavior(payload = {}) {
    if (!activeSpeech) return false;
    const expected = {
      sessionId: String(payload.sessionId || payload.session_id || "").trim(),
      requestId: String(payload.requestId || payload.request_id || "").trim(),
      behaviorId: String(payload.behaviorId || payload.behavior_id || "").trim(),
    };
    const active = activeSpeech.identity || {};
    if (
      !expected.sessionId || !expected.requestId || !expected.behaviorId ||
      active.sessionId !== expected.sessionId ||
      active.requestId !== expected.requestId ||
      String(active.behaviorId || active.sequenceId || "") !== expected.behaviorId
    ) {
      return false;
    }
    stopBrowserSpeech();
    return true;
  }

  function estimateSpeechMs(content, speechRate = currentSpeechRate) {
    // ~3.5 字/秒 + 缓冲；给对话长句留足时间
    const chars = Math.max(1, String(content || "").length);
    const rateFactor = DEFAULT_SPEECH_RATE / normalizeSpeechRate(speechRate);
    return Math.min(30000, Math.max(3500, Math.round(chars * 320 * rateFactor) + 1200));
  }

  function safeCancel(synth) {
    if (!synth) return;
    try {
      if (synth.speaking || synth.pending) synth.cancel();
    } catch (_) {}
  }

  function speakBrowserText(text, options = {}) {
    const content = String(text || "").trim();
    const identity = normalizeSpeechIdentity(options, content);
    if (!content) {
      options.onError?.("EMPTY_TEXT", terminalDetail(identity, "error", "EMPTY_TEXT"));
      return false;
    }
    const synth0 = getSpeechSynthesis();
    if (!synth0) {
      options.onError?.(
        "BROWSER_SPEECH_OUTPUT_UNSUPPORTED",
        terminalDetail(identity, "error", "BROWSER_SPEECH_OUTPUT_UNSUPPORTED")
      );
      return false;
    }

    if (isCompletedSpeech(identity)) {
      options.onDrop?.("duplicate", terminalDetail(identity, "dropped", "duplicate"));
      return false;
    }
    if (activeSpeech) {
      const reason = sameSpeech(activeSpeech.identity, identity) ? "duplicate" : "busy";
      options.onDrop?.(reason, terminalDetail(identity, "dropped", reason));
      return false;
    }

    const myGen = ++speakGeneration;
    const baseDelay = Math.max(0, Number(options.delayMs) || 0);
    loadBrowserSpeechVoices();
    const operation = {
      generation: myGen,
      identity,
      options,
      acceptedAtMs: Date.now(),
      speakCalledAtMs: null,
      attemptToken: 0,
      retryTimer: null,
      voiceWaitTimer: null,
      removeVoiceWaitListener: null,
      cancelAttempt: null,
    };
    activeSpeech = operation;

    const finishOnce = (() => {
      let done = false;
      return (status, reason) => {
        if (done || myGen !== speakGeneration) return;
        done = true;
        if (typeof operation.cancelAttempt === "function") {
          operation.cancelAttempt();
        }
        if (operation.retryTimer != null) {
          clearTimeout(operation.retryTimer);
          operation.retryTimer = null;
        }
        if (activeSpeech === operation) activeSpeech = null;
        rememberCompletedSpeech(identity);
        const detail = terminalDetail(identity, status, reason);
        if (status === "error") {
          options.onError?.(reason || "BROWSER_SPEECH_OUTPUT_FAILED", detail);
        } else {
          options.onEnd?.(detail);
        }
      };
    })();

    const clearVoiceWait = () => {
      if (operation.voiceWaitTimer != null) {
        clearTimeout(operation.voiceWaitTimer);
        operation.voiceWaitTimer = null;
      }
      if (typeof operation.removeVoiceWaitListener === "function") {
        operation.removeVoiceWaitListener();
        operation.removeVoiceWaitListener = null;
      }
    };

    const attemptSpeak = (attempt) => {
      if (myGen !== speakGeneration || activeSpeech !== operation) return;
      loadBrowserSpeechVoices();
      if (!preferredVoice) {
        finishOnce("error", "FIXED_BROWSER_VOICE_UNAVAILABLE");
        return;
      }
      const attemptToken = ++operation.attemptToken;
      const synth = getSpeechSynthesis();
      if (!synth) {
        finishOnce("error", "BROWSER_SPEECH_OUTPUT_UNSUPPORTED");
        return;
      }

      const utterance = new SpeechSynthesisUtterance(content);
      utterance.lang = FIXED_VOICE_LANG;
      const speechRate = normalizeSpeechRate(options.rate, currentSpeechRate);
      utterance.rate = speechRate;
      utterance.pitch = 1.05;
      utterance.volume = 1;
      utterance.voice = preferredVoice;

      let started = false;
      let startWatchdog = null;
      let endWatchdog = null;
      let kickTimer = null;
      let retrying = false;

      const isCurrentAttempt = () =>
        myGen === speakGeneration &&
        activeSpeech === operation &&
        operation.attemptToken === attemptToken;

      const clearStartWatch = () => {
        if (startWatchdog != null) {
          clearTimeout(startWatchdog);
          startWatchdog = null;
        }
      };
      const clearEndWatch = () => {
        if (endWatchdog != null) {
          clearTimeout(endWatchdog);
          endWatchdog = null;
        }
      };
      const clearKickTimer = () => {
        if (kickTimer != null) {
          clearTimeout(kickTimer);
          kickTimer = null;
        }
      };
      const clearAllWatch = () => {
        clearStartWatch();
        clearEndWatch();
        clearKickTimer();
      };
      operation.cancelAttempt = clearAllWatch;

      const retryOrFail = (reason) => {
        if (retrying || !isCurrentAttempt()) return;
        retrying = true;
        clearAllWatch();
        if (attempt < 3) {
          // Invalidate every callback/timer owned by this attempt before
          // cancel() can synchronously dispatch its canceled/interrupted event.
          const scheduledToken = ++operation.attemptToken;
          safeCancel(synth);
          operation.retryTimer = window.setTimeout(() => {
            operation.retryTimer = null;
            if (
              myGen !== speakGeneration ||
              activeSpeech !== operation ||
              operation.attemptToken !== scheduledToken
            ) {
              return;
            }
            attemptSpeak(attempt + 1);
          }, 180 + attempt * 80);
          return;
        }
        finishOnce("error", reason || "BROWSER_SPEECH_OUTPUT_FAILED");
      };

      utterance.onstart = () => {
        if (!isCurrentAttempt()) return;
        started = true;
        speechUnlocked = true;
        speechWarmState = "ready";
        if (warmWatchdog != null) {
          clearTimeout(warmWatchdog);
          warmWatchdog = null;
        }
        clearStartWatch();
        options.onStart?.({
          acceptedAtClientMs: operation.acceptedAtMs,
          speakCalledAtClientMs: operation.speakCalledAtMs,
          actualAtClientMs: Date.now(),
          attempt,
        });
        // 已开始：只做超长兜底，避免永远不 onend 卡死互动页 / ASR
        endWatchdog = setTimeout(() => {
          if (!isCurrentAttempt()) return;
          safeCancel(synth);
          finishOnce("ended", "end_watchdog");
        }, estimateSpeechMs(content, speechRate) + 4000);
      };
      utterance.onend = () => {
        clearAllWatch();
        if (!isCurrentAttempt()) return;
        finishOnce("ended", "");
      };
      utterance.onerror = (event) => {
        const err = (event && event.error) || "BROWSER_SPEECH_OUTPUT_FAILED";
        // 被更新一代或更新 attempt 打断：本轮丢弃（新一轮自己负责回调）
        if (!isCurrentAttempt()) {
          clearAllWatch();
          return;
        }
        // Chrome：同一次 cancel()+speak() 可能对「本句」立刻抛 canceled，且既无 onstart
        // 也无后续事件。旧逻辑 clearWatch 后直接 return → 对话回复永久无声且 ASR 卡住。
        if (err === "interrupted" || err === "canceled") {
          if (started) {
            // 已开声后被外部打断：按结束处理，确保 resumeAsr / robot_speak_ended
            clearAllWatch();
            finishOnce("ended", err);
            return;
          }
          retryOrFail(err);
          return;
        }
        retryOrFail(err);
      };

      // 打断后多留一点间隙，降低 Chrome cancel 后静默失败（切课连发尤甚）
      const kickDelay = Math.max(
        0,
        baseDelay - SPEECH_ENGINE_STARTUP_COMPENSATION_MS
      ) + (attempt === 0 ? 0 : 200 + attempt * 60);
      kickTimer = window.setTimeout(() => {
        kickTimer = null;
        if (!isCurrentAttempt()) return;
        try {
          operation.speakCalledAtMs = Date.now();
          synth.speak(utterance);
          if (typeof synth.resume === "function") {
            try {
              synth.resume();
            } catch (_) {}
          }
          // delayMs 只决定何时启动；watchdog 必须从真正调用 speak()
          // 之后计时，否则较大的时间轴偏移会在开声前制造多个 retry。
          if (!started && isCurrentAttempt()) {
            const startWatchdogMs = speechWarmState === "ready"
              ? WARM_START_WATCHDOG_MS + attempt * 350
              : COLD_START_WATCHDOG_MS;
            startWatchdog = setTimeout(() => {
              if (!isCurrentAttempt() || started) return;
              retryOrFail("BROWSER_SPEECH_WATCHDOG");
            }, startWatchdogMs);
          }
        } catch (err) {
          retryOrFail((err && err.message) || "BROWSER_SPEECH_OUTPUT_FAILED");
        }
      }, kickDelay);
    };

    if (preferredVoice) {
      attemptSpeak(0);
    } else {
      // Edge may expose online voices shortly after page load. Wait only for
      // the locked Xiaoyi voice; never fall through to another voice.
      const onVoicesChanged = () => {
        if (myGen !== speakGeneration || activeSpeech !== operation) return;
        loadBrowserSpeechVoices();
        if (!preferredVoice) return;
        clearVoiceWait();
        attemptSpeak(0);
      };
      synth0.addEventListener("voiceschanged", onVoicesChanged);
      operation.removeVoiceWaitListener = () =>
        synth0.removeEventListener("voiceschanged", onVoicesChanged);
      operation.voiceWaitTimer = window.setTimeout(() => {
        clearVoiceWait();
        finishOnce("error", "FIXED_BROWSER_VOICE_UNAVAILABLE");
      }, FIXED_VOICE_LOAD_TIMEOUT_MS);
      operation.cancelAttempt = clearVoiceWait;
      onVoicesChanged();
    }
    return true;
  }

  global.BrowserTts = {
    loadBrowserSpeechVoices,
    subscribeBrowserSpeechVoiceChanges,
    getPreferredBrowserSpeechVoiceName,
    isFixedBrowserSpeechVoiceAvailable,
    setBrowserSpeechRate,
    getBrowserSpeechRate,
    isBrowserSpeechSynthesisSupported,
    isBrowserSpeechUnlocked,
    isBrowserSpeechWarm: () => speechWarmState === "ready",
    isBrowserSpeechBusy: () => Boolean(activeSpeech),
    getActiveSpeechIdentity: () => activeSpeech && { ...activeSpeech.identity },
    unlockBrowserSpeechOutput,
    warmBrowserSpeechOutput,
    stopBrowserSpeech,
    cancelBrowserSpeechForBehavior,
    speakBrowserText,
  };
})(window);
