// 姿态分析相关导入已注释，待迁移到后端
// import { initPose, detectImage, detectVideo } from "./pose_estimator.js";
// import { normalizePose, poseSimilarity } from "./pose_similarity.js";

import {
  configureCameraAnalysis,
  bindCameraAnalysisSocket,
  startCameraAnalysis,
  stopCameraAnalysis,
} from "./camera_analysis/cameraAnalysis.js";

// common.js 创建的全局 socket（挂到 window）；模块内显式引用
const socket = window.socket || (typeof io !== "undefined" ? io() : null);
if (socket && !window.socket) {
  window.socket = socket;
}

// ======================
// 视频/音频录制和传输
// ======================

const CHILD_SESSION_BINDING_KEY = "server_demo_child_session_binding_v1";

function loadChildSessionBinding() {
  try {
    const raw = window.localStorage.getItem(CHILD_SESSION_BINDING_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (error) {
    console.warn("[child.js] 读取儿童端会话绑定失败:", error);
    return {};
  }
}

const restoredChildBinding = loadChildSessionBinding();
const queryStudentId = (() => {
  try {
    return new URLSearchParams(window.location.search).get("studentId");
  } catch (error) {
    return null;
  }
})();
let childStudentId = queryStudentId || restoredChildBinding.studentId || null;

function persistChildSessionBinding(patch = {}) {
  const next = {
    studentId: firstDefined(patch.studentId, childStudentId),
    trainingSessionId: firstDefined(
      patch.trainingSessionId,
      currentTrainingSessionId
    ),
    sessionId: firstDefined(patch.sessionId, announcedSessionId),
    updatedAt: Date.now(),
  };
  childStudentId = next.studentId || null;
  try {
    window.localStorage.setItem(CHILD_SESSION_BINDING_KEY, JSON.stringify(next));
  } catch (error) {
    console.warn("[child.js] 保存儿童端会话绑定失败:", error);
  }
}

function clearChildSessionBinding() {
  announcedSessionId = null;
  currentTrainingSessionId = null;
  currentQuestionId = null;
  try {
    if (childStudentId != null && childStudentId !== "") {
      window.localStorage.setItem(CHILD_SESSION_BINDING_KEY, JSON.stringify({
        studentId: childStudentId,
        trainingSessionId: null,
        sessionId: null,
        updatedAt: Date.now(),
      }));
    } else {
      window.localStorage.removeItem(CHILD_SESSION_BINDING_KEY);
    }
  } catch (error) {}
}

let mediaStream = null;  // 摄像头和麦克风流（仅 browser 模式）
let videoCanvas = null;  // 用于捕获视频帧的Canvas
let videoContext = null;  // Canvas 2D上下文
let audioContext = null;  // 音频上下文
let audioProcessor = null;  // 音频处理器节点
let isRecording = false;  // 是否正在录制
let recordingStartPromise = null;
let recordingStartSessionId = null;
let currentSessionId = null;  // 当前会话ID（整场 media session）
let currentRecordingMode = "continuous";  // continuous | segmented（兼容旧）
let currentHumanDirName = null;  // 与服务端一致的可读目录名
let currentTrainingSessionId = restoredChildBinding.trainingSessionId || null;  // 整次训练会话ID
let currentQuestionId = null;  // 当前题目窗口ID
let announcedSessionId = restoredChildBinding.sessionId || null;  // prepare/play 已公布的会话；重连时立即重新 join
let videoFrameInterval = null;  // 视频帧发送定时器
let videoFrameRate = 30;  // 视频帧率（fps）— browser 模式；agent 模式由 runtime-config 覆盖
let audioSampleRate = 16000;  // 音频采样率（Hz）
let standbyTimer = null;  // 待机图片定时器

// ======================
// 儿童端媒体模式（browser | agent）
// ======================
let childMediaMode = "browser";
// 生产默认显式报告整场录制失败；仅显式调试配置允许静默。
let skipRuntimeRecordingCheck = false;
let childMediaRuntime = null;
let dialogueTtsMode = "browser";
const CHILD_MEDIA_AGENT_BASE = window.CHILD_MEDIA_AGENT_BASE || "http://127.0.0.1:19091";
const CHILD_MEDIA_AGENT_KEY = window.CHILD_MEDIA_AGENT_KEY || "";
let mediaAgentHeartbeatTimer = null;
let mediaAgentOnline = false;

// 供对话模块读取当前课点上下文
window.currentCourseType = window.currentCourseType || "";
window.currentItemId = window.currentItemId || null;
window.currentQuestionPrompt = window.currentQuestionPrompt || "";
window.currentSpeechTarget = window.currentSpeechTarget || "";
window.currentItemName = window.currentItemName || "";
window.interactivePageContext = window.interactivePageContext || null;

const TIMELINE_IGNORED_SOCKET_EVENTS = new Set([
  "video_frame",
  "audio_chunk",
  "camera_analysis_frame",
  "client_presence",
]);

function recordChildTimelineEvent(eventName, payload) {
  if (TIMELINE_IGNORED_SOCKET_EVENTS.has(String(eventName || ""))) return;
  const data = payload && typeof payload === "object" ? payload : {};
  fetch("/api/v2/timeline/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    keepalive: true,
    body: JSON.stringify({
      event: `child_socket_emit.${eventName}`,
      actor: "child",
      source: "child_ui",
      category: "child_operation",
      phase: "observed",
      status: "sent",
      clientTimestamp: Date.now(),
      trainingSessionId: data.trainingSessionId || currentTrainingSessionId,
      sessionId: data.sessionId || data.session_id || currentSessionId || announcedSessionId,
      questionId: data.questionId || currentQuestionId,
      requestId: data.requestId || data.request_id,
      behaviorId: data.behaviorId || data.behavior_id,
      details: { socketEvent: eventName, payload: data },
    }),
  }).catch(() => {});
}

if (socket && typeof socket.onAnyOutgoing === "function") {
  socket.onAnyOutgoing((eventName, ...args) => {
    recordChildTimelineEvent(eventName, args[0]);
  });
}

const SPEECH_COURSE_TYPES = new Set(["naming", "speech", "onomatopoeia", "mimic"]);
const INTERACTIVE_COURSE_TYPES = new Set(["pairing", "ordering", "matching", "sequencing", "interactive"]);
const DEFAULT_SPEECH_PROMPTS = {
  naming: "这是什么呀",
  speech: "这是什么呀",
  onomatopoeia: "听听，这是什么声音呀？",
  mimic: "跟我做一样的动作吧",
};

function naturalizeOnomatopoeiaName(raw) {
  let name = String(raw || "").trim();
  if (!name) return "";
  const suffixes = ["的叫声", "叫声", "叫"];
  for (const suffix of suffixes) {
    if (name.endsWith(suffix) && name.length > suffix.length) {
      name = name.slice(0, -suffix.length).trim();
      break;
    }
  }
  const diminutives = {
    猫: "小猫",
    狗: "小狗",
    鸟: "小鸟",
    鸡: "小鸡",
    鸭: "小鸭",
    鹅: "小鹅",
    羊: "小羊",
    牛: "小牛",
    猪: "小猪",
    兔: "小兔",
    马: "小马",
    熊: "小熊",
    虎: "小老虎",
    狮: "小狮子",
    猴: "小猴",
    鼠: "小老鼠",
    青蛙: "小青蛙",
    老虎: "小老虎",
    狮子: "小狮子",
    老鼠: "小老鼠",
  };
  return diminutives[name] || name;
}

function defaultPromptForCourse(courseType, itemName) {
  const key = String(courseType || "").toLowerCase();
  if (key === "onomatopoeia") {
    const display = naturalizeOnomatopoeiaName(itemName);
    return display ? `${display}是怎么叫的？` : DEFAULT_SPEECH_PROMPTS.onomatopoeia;
  }
  return DEFAULT_SPEECH_PROMPTS[key] || "";
}

function clearInteractiveIframe() {
  try {
    const frame =
      typeof interactiveEl !== "undefined" && interactiveEl
        ? interactiveEl
        : document.getElementById("interactive");
    if (frame) {
      // Keep the committed frame alive until its replacement is ready.
      // Clearing it here made the child screen blank during teacher rating.
      frame.dataset.pageContextActive = "false";
    }
  } catch (e) {
    console.warn("清空互动 iframe 失败:", e);
  }
}

/**
 * play_resource 时同步儿童端对话上下文。
 * 命名/拟声：清掉配对/排序残留，写入当前物品。
 */
function syncDialoguePageContextFromPlay(payload, course, item) {
  const courseType = String(
    (payload && payload.courseType) ||
      window.currentCourseType ||
      (course && course.type) ||
      ""
  ).toLowerCase();
  window.currentCourseType = courseType;

  const itemName =
    (payload && (payload.itemName || payload.item_name)) ||
    (item && item.name) ||
    "";
  const speechTarget =
    (payload && (payload.speechTarget || payload.speech_target)) ||
    (item && (item.speechTarget || item.speech_target || item.name)) ||
    itemName ||
    "";

  window.currentItemName = itemName || speechTarget || "";
  window.currentSpeechTarget = speechTarget || "";
  if (payload && payload.itemId != null) {
    window.currentItemId = payload.itemId;
  } else if (payload && payload.item_id != null) {
    window.currentItemId = payload.item_id;
  } else if (item && item.id != null) {
    window.currentItemId = item.id;
  }

  if (SPEECH_COURSE_TYPES.has(courseType)) {
    clearInteractiveIframe();
    window.interactivePageContext = null;
    window.currentQuestionPrompt = defaultPromptForCourse(
      courseType,
      window.currentItemName || window.currentSpeechTarget
    );
    const pageCtx = {
      courseType,
      courseId: (payload && payload.courseId) || (course && course.id) || null,
      itemId: window.currentItemId,
      questionId: (payload && payload.questionId) || null,
      prompt: window.currentQuestionPrompt,
      target: window.currentSpeechTarget,
      targetText: window.currentSpeechTarget,
      speechTarget: window.currentSpeechTarget,
      name: window.currentItemName || window.currentSpeechTarget,
      label: window.currentSpeechTarget,
    };
    window.interactivePageContext = null;
    console.log("📄 [child.js] 命名/拟声页上下文已重建:", pageCtx);
    return pageCtx;
  }

  if (INTERACTIVE_COURSE_TYPES.has(courseType) || (item && item.type === "interactive") || (course && course.type === "interactive")) {
    // 进入互动课：先丢掉命名残留，等 iframe postMessage 再填题面
    window.interactivePageContext = {
      courseType: courseType || "pairing",
      courseId: (payload && payload.courseId) || (course && course.id) || null,
      itemId: window.currentItemId,
    };
    window.currentSpeechTarget = "";
    window.currentItemName = "";
    window.currentQuestionPrompt = "";
    return window.interactivePageContext;
  }

  // 其它课型：清互动残留
  clearInteractiveIframe();
  window.interactivePageContext = null;
  window.currentQuestionPrompt =
    defaultPromptForCourse(courseType, window.currentItemName || window.currentSpeechTarget) ||
    window.currentQuestionPrompt ||
    "";
  return {
    courseType,
    courseId: (payload && payload.courseId) || (course && course.id) || null,
    itemId: window.currentItemId,
    prompt: window.currentQuestionPrompt,
    target: window.currentSpeechTarget,
    speechTarget: window.currentSpeechTarget,
  };
}

function applyInteractivePageContext(pageContext) {
  if (!pageContext || typeof pageContext !== "object") return false;
  const incomingType = String(
    pageContext.courseType || pageContext.course_type || ""
  ).toLowerCase();
  const currentType = String(window.currentCourseType || "").toLowerCase();
  if (SPEECH_COURSE_TYPES.has(currentType)) {
    console.log("📄 [child.js] 忽略迟到的互动页上下文（当前课型:", currentType, ")");
    return false;
  }
  if (
    incomingType &&
    currentType &&
    INTERACTIVE_COURSE_TYPES.has(currentType) &&
    incomingType !== currentType &&
    !(
      (currentType === "pairing" && incomingType === "matching") ||
      (currentType === "ordering" && incomingType === "sequencing") ||
      (currentType === "matching" && incomingType === "pairing") ||
      (currentType === "sequencing" && incomingType === "ordering")
    )
  ) {
    console.log("📄 [child.js] 忽略课型不符的互动页上下文:", incomingType, "!=", currentType);
    return false;
  }
  window.interactivePageContext = pageContext;
  if (pageContext.courseType) {
    window.currentCourseType = pageContext.courseType;
  }
  if (pageContext.prompt) {
    window.currentQuestionPrompt = pageContext.prompt;
  }
  // 排序会显式传 target:null，必须清掉配对残留，否则 LLM 仍以为有「上面的图片」
  if (Object.prototype.hasOwnProperty.call(pageContext, "target")) {
    window.currentSpeechTarget = pageContext.target || "";
  }
  console.log("📄 [child.js] 互动页上下文已更新:", pageContext);
  if (window.ChildDialogue && typeof window.ChildDialogue.syncAwakeForPageContext === "function") {
    window.ChildDialogue.syncAwakeForPageContext();
  }
  return true;
}

// Only the committed iframe may mutate the live dialogue context. A staging
// iframe may report while preloading; cache that context until atomic commit.
window.addEventListener("message", (event) => {
  const data = event && event.data;
  if (
    !data ||
    typeof data !== "object" ||
    data.type !== "interactive_page_context" ||
    !data.pageContext
  ) {
    return;
  }

  if (
    stagingInteractiveEl &&
    stagingInteractiveEl.contentWindow &&
    event.source === stagingInteractiveEl.contentWindow
  ) {
    stagingInteractiveEl.__pendingPageContext = data.pageContext;
    console.log("📄 [child.js] 暂存预加载互动页上下文");
    return;
  }

  if (
    !currentVisibleCourseMedia ||
    currentVisibleCourseMedia.type !== "interactive" ||
    !interactiveEl ||
    interactiveEl.dataset.pageContextActive !== "true" ||
    event.source !== interactiveEl.contentWindow
  ) {
    console.log("📄 [child.js] 忽略非当前互动页的上下文消息");
    return;
  }
  applyInteractivePageContext(data.pageContext);
});

function behaviorIdentity(payload) {
  const data = payload || {};
  const speechId = String(data.speechId || data.speech_id || "").trim();
  const behaviorId = String(data.behaviorId || data.behavior_id || "").trim();
  const sequenceId = String(data.sequenceId || data.sequence_id || "").trim();
  const requestId = String(data.requestId || data.request_id || "").trim();
  return {
    speechId,
    behaviorId,
    sequenceId,
    requestId,
    key: speechId || behaviorId || sequenceId || "",
  };
}

function matchesExactBehaviorEnvelope(identity, payload, sessionId) {
  const expected = behaviorIdentity(payload || {});
  const expectedSession = String(
    firstDefined(payload && payload.sessionId, payload && payload.session_id, "")
  ).trim();
  return Boolean(
    identity && expectedSession && expected.requestId && expected.behaviorId &&
    String(sessionId || "") === expectedSession &&
    String(identity.requestId || "") === expected.requestId &&
    String(identity.behaviorId || identity.sequenceId || "") === expected.behaviorId
  );
}

function notifyInteractiveSpeakEnded(payload) {
  const identity = behaviorIdentity(payload);
  const msg = {
    type: "robot_speak_ended",
    intent: payload && payload.intent,
    sessionId: (payload && payload.sessionId) || currentSessionId || window.currentSessionId,
    itemId: firstDefined(
      payload && payload.itemId,
      payload && payload.item_id,
      window.currentItemId
    ),
    text: payload && payload.text,
    status: (payload && payload.status) || "ended",
    terminalStatus: (payload && payload.status) || "ended",
    actualAtClientMs: Date.now(),
    protocolVersion: (payload && payload.protocolVersion) || "1",
    modality: "speech",
    reason: (payload && payload.reason) || "",
    speechId: identity.speechId || undefined,
    behaviorId: identity.behaviorId || identity.sequenceId || undefined,
    requestId: identity.requestId || undefined,
    sequenceId: identity.sequenceId || undefined,
  };
  try {
    const frame = document.getElementById("interactive");
    if (frame && frame.contentWindow) {
      frame.contentWindow.postMessage(msg, "*");
    }
  } catch (e) {
    console.warn("postMessage robot_speak_ended 失败:", e);
  }
  if (socket && socket.connected) {
    socket.emit("robot_speak_ended", msg);
  }
}

function getBackendBaseUrl() {
  return `${window.location.protocol}//${window.location.host}`;
}

async function loadChildRuntimeConfig() {
  try {
    const resp = await fetch("/api/child/runtime-config");
    const data = await resp.json();
    if (data && data.success !== false) {
      childMediaRuntime = data;
      childMediaMode = data.mediaMode === "agent" ? "agent" : "browser";
      if (data.dialogueTtsMode) {
        dialogueTtsMode = String(data.dialogueTtsMode).toLowerCase();
      }
      if (typeof data.skipRuntimeRecordingCheck === "boolean") {
        skipRuntimeRecordingCheck = data.skipRuntimeRecordingCheck;
      }
      if (data.videoFps) videoFrameRate = Number(data.videoFps) || videoFrameRate;
      if (data.audioSampleRate) audioSampleRate = Number(data.audioSampleRate) || audioSampleRate;
      if (data.mediaAgentBase) {
        window.CHILD_MEDIA_AGENT_BASE = data.mediaAgentBase;
      }
      if (data.cameraAnalysis) {
        configureCameraAnalysis({
          enabled: data.cameraAnalysis.enabled !== false,
          fps: Number(data.cameraAnalysis.fps) || 1,
          width: Number(data.cameraAnalysis.width) || 160,
          height: Number(data.cameraAnalysis.height) || 120,
        });
      }
      console.log("儿童端运行时配置:", data);
    }
  } catch (err) {
    console.warn("拉取 runtime-config 失败，回退 browser 模式:", err);
    childMediaMode = "browser";
  }
}

function mediaAgentBase() {
  return window.CHILD_MEDIA_AGENT_BASE || CHILD_MEDIA_AGENT_BASE;
}

async function callMediaAgent(path, payload) {
  const headers = { "Content-Type": "application/json" };
  const key = window.CHILD_MEDIA_AGENT_KEY || CHILD_MEDIA_AGENT_KEY;
  if (key) headers["X-Child-Media-Agent-Key"] = key;

  const response = await fetch(`${mediaAgentBase()}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload || {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `Media Agent request failed: ${response.status}`);
  }
  return data;
}

function setChildCamPreviewFromAgent(enable) {
  const childCam = document.getElementById("childCam");
  if (!childCam) return;
  if (enable) {
    // video 元素对 MJPEG 支持不稳定，改用同尺寸的 img 覆盖或直接设 src（部分浏览器可用）
    childCam.removeAttribute("srcObject");
    try { childCam.srcObject = null; } catch (e) {}
    // 用 img 替换预览：若已有 previewImg 则复用
    let previewImg = document.getElementById("childCamPreview");
    if (!previewImg) {
      previewImg = document.createElement("img");
      previewImg.id = "childCamPreview";
      previewImg.alt = "camera preview";
      previewImg.style.cssText = childCam.style.cssText || "position:fixed;right:0;bottom:0;width:240px;height:180px;object-fit:cover;z-index:50;";
      childCam.style.display = "none";
      childCam.parentNode.insertBefore(previewImg, childCam);
    }
    previewImg.style.display = "block";
    previewImg.src = `${mediaAgentBase()}/preview.mjpeg?t=${Date.now()}`;
  } else {
    const previewImg = document.getElementById("childCamPreview");
    if (previewImg) {
      previewImg.removeAttribute("src");
      previewImg.style.display = "none";
    }
    childCam.style.display = "";
  }
}

function emitMediaAgentHeartbeat(online, detail) {
  if (!socket) return;
  socket.emit("child_media_agent_heartbeat", {
    agentOnline: !!online,
    detail: detail || null,
    ts: Date.now(),
  });
}

async function checkMediaAgentHealth() {
  try {
    const response = await fetch(`${mediaAgentBase()}/health`);
    if (!response.ok) throw new Error(`status=${response.status}`);
    const data = await response.json();
    mediaAgentOnline = true;
    emitMediaAgentHeartbeat(true, data);
    console.log("📹 Media Agent 健康检查:", data);
  } catch (error) {
    mediaAgentOnline = false;
    emitMediaAgentHeartbeat(false, { message: error.message });
    console.warn("⚠️ Media Agent 未连接:", error.message);
  }
}

function startMediaAgentHeartbeat() {
  if (mediaAgentHeartbeatTimer) return;
  mediaAgentHeartbeatTimer = setInterval(() => {
    checkMediaAgentHealth();
  }, 5000);
}

// ======================
// 机器人本地 Agent 转发
// ======================
const ROBOT_AGENT_BASE = window.ROBOT_AGENT_BASE || window.CHILD_MEDIA_AGENT_BASE || "http://127.0.0.1:19091";
const ROBOT_AGENT_KEY = window.ROBOT_AGENT_KEY || window.CHILD_MEDIA_AGENT_KEY || "";
let robotAgentHeartbeatTimer = null;
let robotAgentOnline = false;

function updateAgentStatusBadge(online, text) {
  const badge = document.getElementById("agent-status-badge");
  if (!badge) return;
  badge.style.display = "block";
  badge.textContent = text || (online ? "Agent: 在线" : "Agent: 离线");
  badge.style.background = online
    ? "rgba(22, 163, 74, 0.75)"
    : "rgba(220, 38, 38, 0.75)";
}

function emitAgentHeartbeat(online, detail) {
  if (!socket) return;
  socket.emit("child_agent_heartbeat", {
    agentOnline: !!online,
    detail: detail || null,
    ts: Date.now(),
  });
}

async function callRobotAgent(path, payload) {
  const headers = {
    "Content-Type": "application/json"
  };
  if (ROBOT_AGENT_KEY) {
    headers["X-Robot-Agent-Key"] = ROBOT_AGENT_KEY;
    headers["X-Robot-Runtime-Key"] = ROBOT_AGENT_KEY;
    headers["X-Child-Media-Agent-Key"] = ROBOT_AGENT_KEY;
  }

  const response = await fetch(`${ROBOT_AGENT_BASE}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload || {})
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `Agent request failed: ${response.status}`);
  }
  return data;
}

async function checkRobotAgentHealth() {
  try {
    const response = await fetch(`${ROBOT_AGENT_BASE}/health`);
    if (!response.ok) {
      throw new Error(`status=${response.status}`);
    }
    const data = await response.json();
    robotAgentOnline = true;
    updateAgentStatusBadge(true, "Agent: 在线");
    emitAgentHeartbeat(true, data);
    console.log("🤖 Robot Agent 健康检查:", data);
  } catch (error) {
    robotAgentOnline = false;
    updateAgentStatusBadge(false, "Agent: 离线");
    emitAgentHeartbeat(false, { message: error.message });
    console.warn("⚠️ Robot Agent 未连接:", error.message);
  }
}

function startRobotAgentHeartbeat() {
  if (robotAgentHeartbeatTimer) return;
  robotAgentHeartbeatTimer = setInterval(() => {
    checkRobotAgentHealth();
  }, 5000);
}

// 初始化媒体流（摄像头和麦克风）— 仅 browser 模式
async function initMediaStream() {
  if (childMediaMode === "agent") {
    console.log("Media Agent 模式：跳过浏览器 getUserMedia，改用本机 Agent 预览");
    setChildCamPreviewFromAgent(true);
    standbyTimer = setTimeout(() => {
      showStandbyImage();
    }, 3000);
    return true;
  }

  try {
    // 请求摄像头和麦克风权限
    mediaStream = await navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: 640 },
        height: { ideal: 480 },
        frameRate: { ideal: videoFrameRate }
      },
      audio: {
        sampleRate: { ideal: audioSampleRate },
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true
      }
    });
    
    // 显示摄像头画面
    const childCam = document.getElementById("childCam");
    if (childCam) {
      childCam.srcObject = mediaStream;
    }
    
    // 创建Canvas用于捕获视频帧
    videoCanvas = document.createElement('canvas');
    videoCanvas.width = 640;
    videoCanvas.height = 480;
    videoContext = videoCanvas.getContext('2d');
    
    // 初始化音频上下文
    audioContext = new (window.AudioContext || window.webkitAudioContext)({
      sampleRate: audioSampleRate
    });
    
    console.log("媒体流初始化成功");
    
    // 启动待机定时器（3秒后显示待机图片）
    standbyTimer = setTimeout(() => {
      showStandbyImage();
    }, 3000);
    
    return true;
  } catch (error) {
    console.error("初始化媒体流失败:", error);
    alert("无法访问摄像头或麦克风，请检查权限设置");
    // 即使摄像头失败，也启动待机图片定时器
    standbyTimer = setTimeout(() => {
      showStandbyImage();
    }, 3000);
    return false;
  }
}

// 开始录制（browser：本页采集上行；agent：转发本机 Media Agent）
// 方案 B 连续录制：整场同一 mediaSessionId，切题不得 stop/start
async function startRecording(sessionId, options = {}) {
  if (!sessionId) {
    console.error("startRecording 缺少 sessionId");
    return;
  }

  const recordingMode = options.recordingMode || currentRecordingMode || "continuous";
  const humanDirName = options.humanDirName || currentHumanDirName || null;

  if (isRecording) {
    if (sessionId === currentSessionId) {
      console.warn("已经在录制中（同一 session）:", sessionId);
      return;
    }
    // 连续录制：切题只更新标注/房间，保持 agent 录制句柄
    if (recordingMode === "continuous" || currentRecordingMode === "continuous") {
      console.log(
        "📹 连续录制模式：保持录制，不切换 agent session:",
        currentSessionId, "(忽略新 id", sessionId, ")"
      );
      return;
    }
    const previousSessionId = currentSessionId;
    console.log("🔄 切换录制会话:", previousSessionId, "->", sessionId);
    await stopRecording({ notifyServer: false });
  }

  currentSessionId = sessionId;
  window.  currentSessionId = sessionId;
  window.currentSessionId = sessionId;
  currentRecordingMode = recordingMode;
  if (humanDirName) {
    currentHumanDirName = humanDirName;
  }

  if (childMediaMode === "agent") {
    if (recordingStartPromise) {
      if (recordingStartSessionId === sessionId) {
        return recordingStartPromise;
      }
      try {
        await recordingStartPromise;
      } catch (error) {}
    }
    try {
      setChildCamPreviewFromAgent(true);
      let captureDevices = Array.isArray(options.captureDevices) ? options.captureDevices : [];
      if (!Array.isArray(options.captureDevices)) {
        try {
          const response = await fetch('/api/v2/capture/devices');
          const catalog = await response.json();
          if (response.ok && catalog.success) {
            captureDevices = (catalog.devices || []).filter((device) =>
              device.enabled && device.owner === 'runtime'
            );
          }
        } catch (deviceError) {
          console.warn('读取额外采集设备失败，按默认设备继续:', deviceError);
        }
      }
      const startPayload = {
        sessionId,
        backendBaseUrl: getBackendBaseUrl(),
        recordingMode,
        captureDevices,
      };
      if (currentHumanDirName) {
        startPayload.humanDirName = currentHumanDirName;
      }
      isRecording = true;
      recordingStartSessionId = sessionId;
      const startPromise = callMediaAgent("/record/start", startPayload);
      recordingStartPromise = startPromise;
      await startPromise;
      document.getElementById("status").innerText = "正在录制（Media Agent）...";
      console.log(
        "Media Agent 开始录制，sessionId:", sessionId,
        "humanDir:", currentHumanDirName,
        "mode:", recordingMode
      );
      // agent 生产路径：注意力/情绪由服务端对 robot_runtime 上行帧分析，不启浏览器 C2
      console.log("Agent 模式跳过浏览器摄像头分析（C2），由服务端分析上行帧");
    } catch (error) {
      console.error("Media Agent 启动录制失败:", error);
      isRecording = false;
      document.getElementById("status").innerText = "Media Agent 录制失败";
      if (!skipRuntimeRecordingCheck) {
        alert("整场录制未启动，请检查 Runtime");
      } else {
        console.warn(
          "整场录制未启动，请检查 Runtime（alert 已跳过：SKIP_RUNTIME_RECORDING_CHECK）"
        );
      }
    } finally {
      if (recordingStartSessionId === sessionId) {
        recordingStartPromise = null;
        recordingStartSessionId = null;
      }
    }
    return;
  }
  
  if (!mediaStream) {
    console.error("媒体流未初始化");
    return;
  }
  
  isRecording = true;
  
  console.log("开始录制，sessionId:", sessionId);
  
  // 开始发送视频帧
  const videoTrack = mediaStream.getVideoTracks()[0];
  if (videoTrack) {
    const videoEl = document.getElementById("childCam");
    const interval = 1000 / videoFrameRate;  // 每帧间隔（毫秒）
    
    videoFrameInterval = setInterval(() => {
      if (videoEl && videoEl.readyState === 4 && videoEl.videoWidth > 0) {
        captureAndSendVideoFrame();
      }
    }, interval);
  }
  
  // 开始捕获和发送音频
  const audioTrack = mediaStream.getAudioTracks()[0];
  if (audioTrack && audioContext) {
    const source = audioContext.createMediaStreamSource(mediaStream);
    const bufferSize = 4096;  // 音频缓冲区大小
    
    audioProcessor = audioContext.createScriptProcessor(bufferSize, 1, 1);
    
    audioProcessor.onaudioprocess = (event) => {
      if (isRecording) {
        const inputBuffer = event.inputBuffer;
        const inputData = inputBuffer.getChannelData(0);
        
        // 转换为Int16Array（PCM格式）
        const int16Array = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          // 将浮点数(-1.0到1.0)转换为16位整数(-32768到32767)
          int16Array[i] = Math.max(-32768, Math.min(32767, inputData[i] * 32768));
        }
        
        // 转换为base64
        const base64Audio = arrayBufferToBase64(int16Array.buffer);
        sendAudioChunk(base64Audio);
      }
    };
    
    // 创建一个静音的增益节点，避免将麦克风音频播放到扬声器
    // ScriptProcessorNode 需要连接到输出才能触发 onaudioprocess 事件
    const silentGain = audioContext.createGain();
    silentGain.gain.value = 0;  // 设置增益为0，静音
    
    source.connect(audioProcessor);
    audioProcessor.connect(silentGain);
    silentGain.connect(audioContext.destination);
  }
  
  document.getElementById("status").innerText = "正在录制...";

  // 仅 browser 联调：浏览器端注意力/情绪描述符（1FPS），与 video_frame 录制并行
  try {
    bindCameraAnalysisSocket(socket, () => ({
      sessionId: currentSessionId,
      trainingSessionId: currentTrainingSessionId,
      questionId: currentQuestionId,
    }));
    await startCameraAnalysis();
  } catch (e) {
    console.warn("启动摄像头分析失败:", e);
  }
}

// 停止录制
async function stopRecording(options = {}) {
  const notifyServer = options.notifyServer !== false;
  if (recordingStartPromise) {
    try {
      await recordingStartPromise;
    } catch (error) {}
  }
  if (!isRecording) {
    console.warn("未在录制");
    return;
  }
  
  const sessionIdToStop = currentSessionId;
  isRecording = false;
  stopCameraAnalysis();
  
  // 停止视频帧捕获（browser）
  if (videoFrameInterval) {
    clearInterval(videoFrameInterval);
    videoFrameInterval = null;
  }
  
  // 停止音频捕获（browser）
  if (audioProcessor) {
    audioProcessor.disconnect();
    audioProcessor = null;
  }

  if (childMediaMode === "agent") {
    try {
      await callMediaAgent("/record/stop", { sessionId: sessionIdToStop });
      console.log("Media Agent 已停止录制，sessionId:", sessionIdToStop);
    } catch (error) {
      console.error("Media Agent 停止录制失败:", error);
    }
  }
  
  console.log("停止录制，sessionId:", sessionIdToStop);
  
  // 发送停止录制事件（通知后端结束会话/分析）
  // 课点切换时服务端已收尾，避免重复 emit
  if (notifyServer && sessionIdToStop && socket) {
    socket.emit('stop_recording', {
      sessionId: sessionIdToStop
    });
  }
  
  currentSessionId = null;
  currentRecordingMode = "continuous";
  currentHumanDirName = null;
  document.getElementById("status").innerText = "录制已停止";
}

// 捕获并发送视频帧
function captureAndSendVideoFrame() {
  if (!isRecording || !currentSessionId) return;
  
  const videoEl = document.getElementById("childCam");
  if (!videoEl || videoEl.readyState !== 4 || videoEl.videoWidth === 0) {
    return;
  }
  
  try {
    // 将视频帧绘制到Canvas
    videoCanvas.width = videoEl.videoWidth;
    videoCanvas.height = videoEl.videoHeight;
    videoContext.drawImage(videoEl, 0, 0, videoCanvas.width, videoCanvas.height);
    
    // 将Canvas转换为base64（JPEG格式，质量0.8）
    const base64Frame = videoCanvas.toDataURL('image/jpeg', 0.8);
    
    // 移除data:image/jpeg;base64,前缀
    const base64Data = base64Frame.split(',')[1];
    
    // 发送视频帧
    sendVideoFrame(base64Data);
  } catch (error) {
    console.error("捕获视频帧失败:", error);
  }
}

// 发送视频帧到后端
function sendVideoFrame(frameData) {
  if (!socket || !currentSessionId) return;
  
  socket.emit('video_frame', {
    sessionId: currentSessionId,
    frame: frameData,
    timestamp: Date.now()
  });
}

// 发送音频块到后端
function sendAudioChunk(chunkData) {
  if (!socket || !currentSessionId) return;
  
  socket.emit('audio_chunk', {
    sessionId: currentSessionId,
    chunk: chunkData,
    timestamp: Date.now()
  });
}

// 将ArrayBuffer转换为base64
function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

// 生成静态资源完整路径（兼容已有/static前缀，避免 /static/static/...）
function buildStaticUrl(path) {
  if (!path) return null;
  let p = String(path).trim().replace(/\\/g, "/");
  while (p.startsWith("/static/")) {
    p = p.slice("/static/".length);
  }
  while (p.startsWith("static/")) {
    p = p.slice("static/".length);
  }
  if (/^https?:\/\//i.test(String(path).trim())) {
    return String(path).trim();
  }
  return "/static/" + p.replace(/^\/+/, "");
}

let transitionCoverFallbackTimer = null;

function showTransitionCover() {
  const cover = document.getElementById("transitionCover");
  if (cover) {
    cover.style.display = "block";
  }
  // 防止 onload/onplaying 未触发时遮罩永久盖住下一题
  if (transitionCoverFallbackTimer != null) {
    clearTimeout(transitionCoverFallbackTimer);
  }
  transitionCoverFallbackTimer = setTimeout(() => {
    transitionCoverFallbackTimer = null;
    hideTransitionCover();
  }, 2500);
}

function hideTransitionCover() {
  if (transitionCoverFallbackTimer != null) {
    clearTimeout(transitionCoverFallbackTimer);
    transitionCoverFallbackTimer = null;
  }
  const cover = document.getElementById("transitionCover");
  if (cover) {
    cover.style.display = "none";
  }
}

const BEHAVIOR_ANIMATION_FADE_MS = 320;
const BEHAVIOR_ANIMATION_DEDUPE_TTL_MS = 5 * 60 * 1000;
const BEHAVIOR_ANIMATION_DEDUPE_MAX = 256;
let activeBehaviorAnimationPlayback = null;
/** Last praise frame held visible until next content / leave (not snapped back). */
let heldPraiseOverlay = null;
/** prepare_behavior_animation decode-only state; play starts on play_resource. */
let preparedBehaviorAnimation = null;
const completedBehaviorAnimationPlaybacks = new Map();
const preloadedBehaviorAnimationVideos = new Map();

// Warm the browser cache while the child page is idle. This is deliberately
// best-effort: a missing or slow catalog must never prevent course playback.
async function preloadBehaviorAnimations() {
  try {
    const response = await fetch('/api/robot/animations', { credentials: 'include' });
    if (!response.ok) throw new Error(`animation_catalog_http_${response.status}`);
    const data = await response.json();
    const items = Array.isArray(data?.items) ? data.items : [];
    items.forEach((item) => {
      const source = item && (item.url || item.name);
      if (!source || preloadedBehaviorAnimationVideos.has(source)) return;
      const video = document.createElement('video');
      video.preload = 'auto';
      video.muted = true;
      video.defaultMuted = true;
      video.playsInline = true;
      video.setAttribute('aria-hidden', 'true');
      video.style.position = 'fixed';
      video.style.width = '1px';
      video.style.height = '1px';
      video.style.opacity = '0';
      video.style.pointerEvents = 'none';
      video.style.left = '-9999px';
      video.src = buildStaticUrl(source);
      video.addEventListener('error', () => {
        console.warn('[child.js] 行为动画后台预载失败:', source);
      }, { once: true });
      document.body?.appendChild(video);
      try { video.load(); } catch (_) { /* best effort */ }
      preloadedBehaviorAnimationVideos.set(source, video);
    });
    console.log('[child.js] 行为动画后台预载:', items.length);
  } catch (error) {
    console.warn('[child.js] 行为动画目录预载跳过:', error);
  }
}

// 儿童端逻辑
let allCourses = [];
let coursesReady = false;
let coursesReadyPromise = null;
let pendingPlayResource = null;
let currentCourseId = null;
let audioPlayer = null;  // 音频播放器实例

function ensureCoursesLoaded() {
  if (coursesReadyPromise) return coursesReadyPromise;
  coursesReadyPromise = fetch("/courses")
    .then(res => {
      if (!res.ok) throw new Error(`course_catalog_http_${res.status}`);
      return res.json();
    })
    .then(data => {
      allCourses = Array.isArray(data) ? data : [];
      coursesReady = true;
      console.log("📚 课程列表已加载:", allCourses.length);
      if (pendingPlayResource) {
        const queued = pendingPlayResource;
        pendingPlayResource = null;
        handlePlayResource(queued);
      }
      return allCourses;
    })
    .catch(err => {
      coursesReadyPromise = null;
      console.error("加载课程列表失败:", err);
      const failedPayload = pendingPlayResource;
      pendingPlayResource = null;
      if (failedPayload) {
        const transitionId = resourceTransitionIdentity(failedPayload, null, null);
        emitResourceTransitionFailure(
          failedPayload,
          null,
          null,
          transitionId,
          new Error("course_catalog_load_failed")
        );
      }
      throw err;
    });
  return coursesReadyPromise;
}

ensureCoursesLoaded().catch(() => {
  // Status is reported when a queued resource exists; otherwise retry on demand.
});

let imageEl = document.getElementById("image");
let videoEl = document.getElementById("video");
const audioEl = document.getElementById("audio");
let interactiveEl = document.getElementById("interactive");
let stagingImageEl = document.getElementById("image-staging");
let stagingVideoEl = document.getElementById("video-staging");
let stagingInteractiveEl = document.getElementById("interactive-staging");

const RESOURCE_CROSSFADE_MS = 320;
const RESOURCE_LOAD_TIMEOUT_MS = 10000;
const RESOURCE_ACK_TTL_MS = 5 * 60 * 1000;
const RESOURCE_FALLBACK_ACK_TTL_MS = 2000;
const RESOURCE_ACK_MAX = 256;
let resourceTransitionGeneration = 0;
let pendingResourceTransition = null;
let currentVisibleCourseMedia = null;
const completedResourceTransitions = new Map();

function findCourseById(courseId) {
  const target = Number(courseId);
  return allCourses.find(c => Number(c.id) === target) || null;
}

function findCourseItem(course, itemId) {
  if (!course || !Array.isArray(course.items) || itemId == null) return null;
  const target = Number(itemId);
  return course.items.find(it => Number(it.id) === target) || null;
}

function delayMs(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function waitForNextPaint() {
  if (typeof requestAnimationFrame !== "function") {
    return delayMs(16);
  }
  return new Promise(resolve => {
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  });
}

function firstDefined(...values) {
  return values.find(value => value !== undefined && value !== null && value !== "");
}

function resourceTransitionIdentity(payload, course, item) {
  const explicitId = firstDefined(
    payload && payload.transitionId,
    payload && payload.transition_id,
    payload && payload.requestId,
    payload && payload.request_id
  );
  if (explicitId != null) return String(explicitId);
  return [
    "resource",
    firstDefined(payload && payload.sessionId, currentSessionId, "no-session"),
    firstDefined(payload && payload.courseId, course && course.id, "no-course"),
    firstDefined(payload && payload.itemId, item && item.id, "no-item"),
    firstDefined(payload && payload.resolvedFile, item && item.file, course && course.file, "no-file"),
  ].join(":");
}

function hasExplicitResourceTransitionId(payload) {
  return firstDefined(
    payload && payload.transitionId,
    payload && payload.transition_id,
    payload && payload.requestId,
    payload && payload.request_id
  ) != null;
}

function resourceTerminalPayload(payload, course, item, transitionId, extra = {}) {
  const requestId = firstDefined(
    payload && payload.requestId,
    payload && payload.request_id,
    transitionId
  );
  return {
    protocolVersion: firstDefined(payload && payload.protocolVersion, "1"),
    modality: "childAnimation",
    sessionId: firstDefined(payload && payload.sessionId, currentSessionId, ""),
    requestId: requestId == null ? "" : String(requestId),
    transitionId: String(transitionId || ""),
    questionId: firstDefined(payload && payload.questionId, currentQuestionId, ""),
    courseId: firstDefined(payload && payload.courseId, course && course.id, ""),
    itemId: firstDefined(payload && payload.itemId, item && item.id, ""),
    ...extra,
  };
}

function pruneCompletedResourceTransitions(now = Date.now()) {
  for (const [id, record] of completedResourceTransitions.entries()) {
    const ttlMs = record && record.ttlMs || RESOURCE_ACK_TTL_MS;
    if (!record || now - record.completedAt > ttlMs) {
      completedResourceTransitions.delete(id);
    }
  }
  while (completedResourceTransitions.size > RESOURCE_ACK_MAX) {
    completedResourceTransitions.delete(
      completedResourceTransitions.keys().next().value
    );
  }
}

function emitResourceReady(payload, course, item, transitionId) {
  const terminal = resourceTerminalPayload(payload, course, item, transitionId, {
    status: "ready",
  });
  completedResourceTransitions.set(transitionId, {
    completedAt: Date.now(),
    ttlMs: hasExplicitResourceTransitionId(payload)
      ? RESOURCE_ACK_TTL_MS
      : RESOURCE_FALLBACK_ACK_TTL_MS,
    payload: terminal,
  });
  pruneCompletedResourceTransitions();
  socket.emit("resource_ready", terminal);
  console.log("✅ [child.js] resource_ready:", terminal);
}

function emitResourceTransitionFailure(payload, course, item, transitionId, error) {
  const terminal = resourceTerminalPayload(payload, course, item, transitionId, {
    status: "error",
    reason: error && error.message ? error.message : String(error || "resource_load_failed"),
  });
  socket.emit("resource_transition_failed", terminal);
  console.error("❌ [child.js] resource_transition_failed:", terminal);
}

function setElementSource(el, value) {
  if (!el) return;
  if (el.getAttribute("src") === value) {
    el.removeAttribute("src");
  }
  el.src = value;
}

function clearMediaElement(el, type, keepDisplay = false) {
  if (!el) return;
  el.onload = null;
  el.onerror = null;
  el.onloadeddata = null;
  el.oncanplay = null;
  el.onplaying = null;
  el.style.opacity = "0";
  el.style.pointerEvents = "none";
  if (!keepDisplay) el.style.display = "none";

  if (type === "video") {
    try { el.pause(); } catch (e) {}
    try {
      el.removeAttribute("src");
      el.load();
    } catch (e) {}
  } else if (type === "interactive") {
    try {
      el.dataset.pageContextActive = "false";
      if (el.getAttribute("src") !== "about:blank") el.src = "about:blank";
    } catch (e) {}
  } else if (type === "image") {
    try { el.removeAttribute("src"); } catch (e) {}
  }
}

function stagingPairForType(type) {
  if (type === "image") return { active: imageEl, staging: stagingImageEl };
  if (type === "video") return { active: videoEl, staging: stagingVideoEl };
  if (type === "interactive") return { active: interactiveEl, staging: stagingInteractiveEl };
  return null;
}

function resetStagingElement(el, type) {
  if (!el) return;
  clearMediaElement(el, type);
  if (type === "interactive") {
    delete el.__pendingPageContext;
  }
  el.classList.add("course-media-layer--staging");
  el.setAttribute("aria-hidden", "true");
  el.style.zIndex = "1001";
}

function restoreCommittedMedia() {
  if (!currentVisibleCourseMedia || !currentVisibleCourseMedia.el) return;
  currentVisibleCourseMedia.el.style.display = "block";
  currentVisibleCourseMedia.el.style.opacity = "1";
  currentVisibleCourseMedia.el.style.pointerEvents = "auto";
}

function freezeCommittedCourseFrame() {
  if (
    !currentVisibleCourseMedia ||
    currentVisibleCourseMedia.type !== "video" ||
    !currentVisibleCourseMedia.el ||
    typeof currentVisibleCourseMedia.el.pause !== "function"
  ) {
    return;
  }
  try {
    // pause() preserves the browser's currently decoded frame.
    currentVisibleCourseMedia.el.pause();
  } catch (error) {
    console.warn("暂停课程视频以保留评分帧失败:", error);
  }
}

function isCurrentResourceTransition(token) {
  return !!(
    pendingResourceTransition &&
    token &&
    pendingResourceTransition.generation === token.generation &&
    pendingResourceTransition.transitionId === token.transitionId
  );
}

function cancelPendingResourceTransition() {
  const pending = pendingResourceTransition;
  resourceTransitionGeneration += 1;
  pendingResourceTransition = null;
  if (pending && pending.stagingElement) {
    resetStagingElement(pending.stagingElement, pending.type);
  }
  restoreCommittedMedia();
}

function waitForImageReady(image, src) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let timer = null;
    const finish = async (error) => {
      if (settled) return;
      settled = true;
      if (timer != null) clearTimeout(timer);
      if (image.onload === onLoad) image.onload = null;
      if (image.onerror === onError) image.onerror = null;
      if (error) {
        reject(error);
        return;
      }
      if (typeof image.decode === "function") {
        try { await image.decode(); } catch (e) {}
      }
      resolve();
    };
    const onLoad = () => finish();
    const onError = () => finish(new Error(`image_load_failed:${src}`));
    image.onload = onLoad;
    image.onerror = onError;
    timer = setTimeout(
      () => finish(new Error(`image_load_timeout:${src}`)),
      RESOURCE_LOAD_TIMEOUT_MS
    );
    setElementSource(image, src);
    if (image.complete && image.naturalWidth > 0) {
      Promise.resolve().then(onLoad);
    }
  });
}

function waitForVideoReady(video, src) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let timer = null;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      if (timer != null) clearTimeout(timer);
      if (video.onloadeddata === onReady) video.onloadeddata = null;
      if (video.oncanplay === onReady) video.oncanplay = null;
      if (video.onerror === onError) video.onerror = null;
      error ? reject(error) : resolve();
    };
    const onReady = () => finish();
    const onError = () => finish(new Error(`video_load_failed:${src}`));
    video.onloadeddata = onReady;
    video.oncanplay = onReady;
    video.onerror = onError;
    video.preload = "auto";
    timer = setTimeout(
      () => finish(new Error(`video_load_timeout:${src}`)),
      RESOURCE_LOAD_TIMEOUT_MS
    );
    setElementSource(video, src);
    try { video.load(); } catch (e) {}
    if (video.readyState >= 2) Promise.resolve().then(onReady);
  });
}

async function waitForIframeReady(frame, src, token) {
  const parsed = new URL(src, window.location.href);
  if (parsed.origin === window.location.origin) {
    const response = await fetch(parsed.href, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(`interactive_preflight_failed:${response.status}`);
    }
  }
  if (!isCurrentResourceTransition(token)) {
    throw new Error("stale_transition");
  }

  await new Promise((resolve, reject) => {
    let settled = false;
    let timer = null;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      if (timer != null) clearTimeout(timer);
      if (frame.onload === onLoad) frame.onload = null;
      if (frame.onerror === onError) frame.onerror = null;
      error ? reject(error) : resolve();
    };
    const onLoad = () => finish();
    const onError = () => finish(new Error(`interactive_load_failed:${src}`));
    frame.onload = onLoad;
    frame.onerror = onError;
    timer = setTimeout(
      () => finish(new Error(`interactive_load_timeout:${src}`)),
      RESOURCE_LOAD_TIMEOUT_MS
    );
    setElementSource(frame, src);
  });
}

function interactiveResourceUrl(payload, course, item, transitionId) {
  // Interactive item.file may be a question-image directory. The course entry
  // document (matching.html / sequencing.html) is always the preferred shell.
  const source = firstDefined(
    course && course.file,
    course && course.entryFile,
    course && course.entry_file,
    item && item.file
  );
  const base = buildStaticUrl(source);
  if (!base) throw new Error("interactive_resource_missing");

  const params = new URLSearchParams();
  params.set("courseId", firstDefined(payload.courseId, course && course.id, ""));
  params.set("courseType", firstDefined(payload.courseType, course && course.type, "interactive"));
  const itemId = firstDefined(payload.itemId, item && item.id);
  if (itemId != null) params.set("itemId", itemId);
  const sessionId = firstDefined(payload.sessionId, currentSessionId);
  if (sessionId != null) params.set("sessionId", sessionId);
  const trainingSessionId = firstDefined(payload.trainingSessionId, currentTrainingSessionId);
  if (trainingSessionId != null) params.set("trainingSessionId", trainingSessionId);
  const questionId = firstDefined(payload.questionId, currentQuestionId);
  if (questionId != null) params.set("questionId", questionId);

  const configSource = item || course || {};
  if (configSource.difficulty != null) {
    params.set("difficulty", configSource.difficulty);
  }
  if (configSource.config && typeof configSource.config === "object") {
    Object.keys(configSource.config).forEach(key => {
      const value = configSource.config[key];
      params.set(key, typeof value === "object" ? JSON.stringify(value) : value);
    });
  }
  params.set("_transition", transitionId);
  return `${base}${base.includes("?") ? "&" : "?"}${params.toString()}`;
}

function looksLikeAudioPath(path) {
  return /\.(mp3|wav|ogg|m4a|aac)(\?|#|$)/i.test(String(path || ""));
}

function looksLikeImagePath(path) {
  return /\.(png|jpe?g|gif|webp|bmp|svg)(\?|#|$)/i.test(String(path || ""));
}

function looksLikeMediaFolderPath(path) {
  const text = String(path || "").split(/[?#]/)[0];
  if (!text) return false;
  if (/\/$/.test(text)) return true;
  // Folder refs without trailing slash still have no file extension.
  return /\/images\/[^/]+\/\d+$/i.test(text);
}

function resolveImageSource(payload, course, item) {
  // Display slot must be a concrete image URL. Legacy 拟声 courses.json put
  // animal sounds (e.g. dog_bark.mp3) in item.file with type:"image", which
  // trips img.onerror as image_load_failed. Prefer resolved/icon images.
  const candidates = [
    payload && payload.resolvedFile,
    item && item.file,
    item && item.icon,
    course && course.icon,
    course && course.file,
    "resources/images/UI/FG.png",
  ];
  const imageCandidate = candidates.find(
    (value) =>
      value &&
      !looksLikeAudioPath(value) &&
      looksLikeImagePath(value)
  );
  if (imageCandidate) return imageCandidate;
  // Folder paths are resolved server-side into resolvedFile; if only a folder
  // remains, fall through to FG rather than feeding a directory to <img>.
  const nonAudio = candidates.find(
    (value) =>
      value &&
      !looksLikeAudioPath(value) &&
      !looksLikeMediaFolderPath(value)
  );
  if (nonAudio) return nonAudio;
  console.warn(
    "⚠️ [child.js] image slot had audio/folder-only paths; falling back to FG.png",
    candidates.filter(Boolean)
  );
  return "resources/images/UI/FG.png";
}

function buildResourceSpec(payload, course, item, transitionId) {
  const rawType = String(firstDefined(item && item.type, course && course.type, "")).toLowerCase();
  const interactiveTypes = new Set(["interactive", "pairing", "matching", "ordering", "sequencing"]);
  if (rawType === "image") {
    const source = resolveImageSource(payload, course, item);
    return { type: "image", src: buildStaticUrl(source) };
  }
  if (rawType === "video") {
    const source = firstDefined(payload.resolvedFile, item && item.file, course && course.file);
    const src = buildStaticUrl(source);
    if (!src) throw new Error("video_resource_missing");
    return { type: "video", src };
  }
  if (interactiveTypes.has(rawType) || interactiveTypes.has(String(course && course.type).toLowerCase())) {
    return {
      type: "interactive",
      src: interactiveResourceUrl(payload, course, item, transitionId),
    };
  }
  throw new Error(`unsupported_resource_type:${rawType || "missing"}`);
}

async function preloadStagingResource(spec, staging, token) {
  staging.style.display = "block";
  staging.style.opacity = "0";
  staging.style.zIndex = "1001";
  staging.style.pointerEvents = "none";
  staging.classList.add("course-media-layer--staging");
  staging.setAttribute("aria-hidden", "true");

  if (spec.type === "image") {
    await waitForImageReady(staging, spec.src);
  } else if (spec.type === "video") {
    await waitForVideoReady(staging, spec.src);
    if (!isCurrentResourceTransition(token)) throw new Error("stale_transition");
    // Preload/decode only. Starting playback while this layer is transparent
    // leaks sound and advances the hidden video before the atomic commit.
    try { staging.pause(); } catch (e) {}
    staging.currentTime = 0;
  } else if (spec.type === "interactive") {
    await waitForIframeReady(staging, spec.src, token);
  }
}

function promoteStagingResource(type) {
  const pair = stagingPairForType(type);
  if (!pair) throw new Error(`unsupported_staging_type:${type}`);
  const promoted = pair.staging;
  const retired = pair.active;
  const activeId = type === "interactive" ? "interactive" : type;
  const stagingId = `${activeId}-staging`;

  retired.id = `${activeId}-retiring`;
  promoted.id = activeId;
  retired.id = stagingId;

  promoted.classList.remove("course-media-layer--staging");
  promoted.removeAttribute("aria-hidden");
  promoted.style.display = "block";
  promoted.style.opacity = "1";
  promoted.style.zIndex = "1000";
  promoted.style.pointerEvents = "auto";
  if (type === "interactive") promoted.dataset.pageContextActive = "true";

  if (type === "image") {
    imageEl = promoted;
    stagingImageEl = retired;
  } else if (type === "video") {
    videoEl = promoted;
    stagingVideoEl = retired;
  } else {
    interactiveEl = promoted;
    stagingInteractiveEl = retired;
  }
  resetStagingElement(retired, type);
  return promoted;
}

function clearOtherCommittedMedia(promoted) {
  [
    { el: imageEl, type: "image" },
    { el: videoEl, type: "video" },
    { el: interactiveEl, type: "interactive" },
  ].forEach(entry => {
    if (entry.el !== promoted) clearMediaElement(entry.el, entry.type);
  });
}

function commitCourseLogicalContext(payload, course, item, stagedPageContext = null) {
  const courseType = String(
    (payload && payload.courseType) || (course && course.type) || ""
  ).toLowerCase();

  currentCourseId = payload && payload.courseId;
  window.currentCourseId = currentCourseId;
  window.currentItemId = payload && payload.itemId;
  if (payload && payload.questionId) {
    currentQuestionId = payload.questionId;
  }
  if (courseType) {
    window.currentCourseType = courseType;
  }

  if (payload && payload.pageContext && payload.pageContext.courseType) {
    const pageType = String(payload.pageContext.courseType).toLowerCase();
    window.currentCourseType = pageType;
    if (SPEECH_COURSE_TYPES.has(pageType)) {
      clearInteractiveIframe();
      window.interactivePageContext = null;
      window.currentSpeechTarget =
        payload.pageContext.target ||
        payload.pageContext.speechTarget ||
        payload.speechTarget ||
        "";
      window.currentItemName =
        payload.pageContext.name ||
        payload.itemName ||
        window.currentSpeechTarget;
      window.currentQuestionPrompt =
        payload.pageContext.prompt ||
        defaultPromptForCourse(
          pageType,
          window.currentItemName || window.currentSpeechTarget
        );
    } else {
      syncDialoguePageContextFromPlay(payload, course, item);
    }
  } else {
    syncDialoguePageContextFromPlay(payload, course, item);
  }

  if (stagedPageContext) {
    applyInteractivePageContext(stagedPageContext);
  }
  if (
    window.ChildDialogue &&
    typeof window.ChildDialogue.syncAwakeForPageContext === "function"
  ) {
    window.ChildDialogue.syncAwakeForPageContext();
  }
}

async function transitionCourseResource(payload, course, item) {
  const transitionId = resourceTransitionIdentity(payload, course, item);
  pruneCompletedResourceTransitions();
  const completed = completedResourceTransitions.get(transitionId);
  if (completed) {
    socket.emit("resource_ready", completed.payload);
    console.log("↩️ [child.js] duplicate transition acknowledged without replay:", transitionId);
    return true;
  }
  if (
    pendingResourceTransition &&
    pendingResourceTransition.transitionId === transitionId
  ) {
    console.log("⏭️ [child.js] duplicate pending transition ignored:", transitionId);
    return false;
  }

  cancelPendingResourceTransition();
  hideTransitionCover();
  const token = {
    generation: resourceTransitionGeneration,
    transitionId,
    type: "",
    stagingElement: null,
    phase: "preloading",
  };
  pendingResourceTransition = token;

  try {
    const spec = buildResourceSpec(payload, course, item, transitionId);
    const pair = stagingPairForType(spec.type);
    if (!pair || !pair.staging) throw new Error(`staging_element_missing:${spec.type}`);
    token.type = spec.type;
    token.stagingElement = pair.staging;
    resetStagingElement(pair.staging, spec.type);
    await preloadStagingResource(spec, pair.staging, token);
    if (!isCurrentResourceTransition(token)) return false;

    token.phase = "crossfading";
    const previous = currentVisibleCourseMedia && currentVisibleCourseMedia.el;
    await waitForNextPaint();
    if (!isCurrentResourceTransition(token)) return false;
    pair.staging.style.opacity = "1";
    if (previous && previous !== pair.staging) {
      previous.style.pointerEvents = "none";
      previous.style.opacity = "0";
    }
    if (spec.type === "video") {
      try {
        await pair.staging.play();
      } catch (error) {
        if (!error || error.name !== "NotAllowedError") throw error;
        // The decoded first frame remains a valid committed state. A later
        // user gesture may start it without exposing a blank frame.
        pair.staging.pause();
        pair.staging.currentTime = 0;
        console.warn("[child.js] video autoplay blocked; committing decoded first frame");
      }
    }
    await delayMs(RESOURCE_CROSSFADE_MS);
    if (!isCurrentResourceTransition(token)) return false;

    const promoted = promoteStagingResource(spec.type);
    const stagedPageContext =
      spec.type === "interactive" ? promoted.__pendingPageContext || null : null;
    if (spec.type === "interactive") {
      delete promoted.__pendingPageContext;
    }
    clearOtherCommittedMedia(promoted);
    currentVisibleCourseMedia = { el: promoted, type: spec.type, transitionId };
    pendingResourceTransition = null;
    // Keep praise visible throughout preload/crossfade. Clear it only after
    // the next resource is committed, so duplicate or failed transitions do
    // not reveal the previous question again.
    clearHeldPraiseOverlay("content_committed");
    preparedBehaviorAnimation = null;
    try {
      commitCourseLogicalContext(payload, course, item, stagedPageContext);
    } catch (contextError) {
      // The decoded/visible resource is already committed. A dialogue-context
      // bookkeeping error must never roll that frame back to a cleared layer.
      console.error("[child.js] 提交课程逻辑上下文失败:", contextError);
    }
    hideStandbyImage();

    const statusEl = document.getElementById("status");
    if (statusEl) {
      const itemLabel = item && item.name ? ` - ${item.name}` : "";
      statusEl.innerText = `正在播放：${course.title || ""}${itemLabel}`;
    }
    emitResourceReady(payload, course, item, transitionId);
    return true;
  } catch (error) {
    if (!isCurrentResourceTransition(token)) return false;
    if (token.stagingElement) resetStagingElement(token.stagingElement, token.type);
    pendingResourceTransition = null;
    restoreCommittedMedia();
    const statusEl = document.getElementById("status");
    if (statusEl) statusEl.innerText = "新课程加载失败，已保留上一课程画面";
    emitResourceTransitionFailure(payload, course, item, transitionId, error);
    return false;
  }
}

// 统一处理：播放资源 + 可选附加语音
// payload 约定：{ action: "play", courseId, itemId, sessionId, aux?: { question?: true, praise?: true, hint?: true } }
function handlePlayResource(payload) {
  console.log("🎯 [child.js] 收到 play_resource 事件:", payload);
  
  if (!payload || payload.action !== "play") return;
  if (!isEventForActiveChildSession(payload)) {
    console.warn("⏭️ [child.js] 忽略旧会话/旧训练的 play_resource:", payload);
    return;
  }

  if (!coursesReady) {
    pendingPlayResource = payload;
    console.warn("⏳ 课程列表尚未就绪，已排队 play_resource");
    ensureCoursesLoaded().catch(() => {});
    return;
  }

  const { courseId, itemId, sessionId, aux } = payload;
  if (payload.studentId != null || payload.student_id != null) {
    childStudentId = firstDefined(payload.studentId, payload.student_id);
  }
  if (payload.trainingSessionId) {
    currentTrainingSessionId = payload.trainingSessionId;
  }
  
  console.log("📋 [child.js] 解析 payload - courseId:", courseId, "itemId:", itemId, "sessionId:", sessionId, "trainingSessionId:", currentTrainingSessionId, "aux:", aux);
  
  // 判断是否是纯 aux 操作（表扬、提示、问题音频等）
  // 注意：在更新 currentSessionId 之前判断，以便正确识别新会话 vs aux操作
  // 如果收到新的sessionId（与当前不同），说明是初次播放，即使带question也要加载内容
  const hasAuxFlag = aux && (
    aux.question || aux.praise || aux.hint
    || aux.socialGreetingIntro || aux.socialGreetingPlay
    || aux.socialFarewellBye || aux.socialFarewellReply
  );
  const isNewSession = sessionId && sessionId !== currentSessionId;
  const isAuxOperation = hasAuxFlag && !isNewSession && !!currentSessionId;
  
  console.log("🔍 [child.js] aux判断: hasAuxFlag=", hasAuxFlag, "isNewSession=", isNewSession, "currentSessionId=", currentSessionId, "isAuxOperation=", isAuxOperation);
  
  // 如果收到sessionId，开始/附着录制并加入会话房间。
  // 方案 B：整场同一 mediaSessionId，切题不 stop/start。
  if (sessionId) {
    if (payload.mediaMode === "agent" || payload.mediaMode === "browser") {
      childMediaMode = payload.mediaMode;
    }
    const recordingMode = payload.recordingMode || currentRecordingMode || "continuous";
    if (payload.humanDirName) {
      currentHumanDirName = payload.humanDirName;
    }
    console.log(
      "🎬 [child.js] 收到play_resource，准备录制 session:",
      currentSessionId, "->", sessionId,
      "mediaMode:", childMediaMode,
      "recordingMode:", recordingMode,
      "humanDir:", currentHumanDirName,
      "isRecording:", isRecording
    );

    attachChildSession(sessionId);

    startRecording(sessionId, {
      recordingMode,
      humanDirName: currentHumanDirName,
    }).then(() => {
      console.log("✅ [child.js] 录制会话已就绪:", currentSessionId);
    }).catch((err) => {
      console.error("❌ [child.js] 启动/切换录制失败:", err);
    });

  }
  
  const course = findCourseById(courseId);
  if (!course) {
    console.error("❌ 找不到课程:", courseId, "已加载课程数:", allCourses.length);
    const statusEl = document.getElementById("status");
    if (statusEl) statusEl.innerText = "未找到课程配置，请刷新儿童端后重试";
    const transitionId = resourceTransitionIdentity(payload, null, null);
    emitResourceTransitionFailure(
      payload,
      null,
      null,
      transitionId,
      new Error(`course_not_found:${courseId}`)
    );
    return;
  }
  // 找到子项（如果有）
  const item = findCourseItem(course, itemId);
  
  // 如果是纯 aux 操作，只播放音频/视频，不重新加载内容
  if (isAuxOperation) {
    console.log("收到aux操作，只播放音频，不重新加载内容", aux);
    // browser TTS：提问/表扬/提示/社交打招呼再见由 robot_speak_text 朗读，跳过预录直链
    const isBrowserSpokenAux = aux.question || aux.praise || aux.hint
      || aux.socialGreetingIntro || aux.socialGreetingPlay
      || aux.socialFarewellBye || aux.socialFarewellReply;
    if (dialogueTtsMode === "browser" && isBrowserSpokenAux) {
      console.log("⏭️ [child.js] browser TTS 模式，跳过 aux 预录直链:", aux);
      if (aux.praise && payload.behaviorAnimation) {
        playBehaviorAnimation(payload.behaviorAnimation, payload);
      }
      return;
    }
    let auxFile = null;
    if (aux.question) auxFile = course.question;
    if (aux.praise) {
      auxFile = course.praise;
      // 鼓励动画由行为绑定提供；未配置时服务端从默认动画库选择。
      if (payload.behaviorAnimation) {
        playBehaviorAnimation(payload.behaviorAnimation, payload);
      }
    }
    if (aux.hint && item && item.hint) auxFile = item.hint;
    if (auxFile) {
      // 服务端 AudioService 已通过 play_audio 下发；有 AudioPlayer 时不再直链播一遍，
      // 否则表扬/提问会叠播，听感像「一直在表扬」。
      if (audioPlayer && (aux.question || aux.praise || aux.hint)) {
        console.log("⏭️ [child.js] 跳过旧版 aux 直链播放，交由 AudioPlayer:", aux);
      } else {
        const audioUrl = buildStaticUrl(auxFile);
        const tempAudio = new Audio(audioUrl);
        tempAudio.play();
      }
    }
    return; // 早期返回，不执行后续的内容加载逻辑
  }

  // Stage the next course while the committed course remains visible.
  void transitionCourseResource(payload, course, item);
}

socket.on("play_resource", (payload) => {
  handlePlayResource(payload);
});

socket.on("prepare_behavior_animation", (payload) => {
  if (!payload || !isEventForActiveChildSession(payload)) return;
  if (!payload.behaviorAnimation) return;
  // Decode/preload only. Starting full playback here races play_resource:
  // short MP4s finish into completedBehaviorAnimationPlaybacks, then
  // play_resource dedupes and the child never shows praise 画面.
  prepareBehaviorAnimation(payload.behaviorAnimation, payload);
});

// 监听joined_session确认
socket.on("joined_session", (data) => {
  console.log("✅ [child.js] joined_session确认:", data);
});

function isControlEventForCurrentSession(payload) {
  const data = payload && typeof payload === "object" ? payload : {};
  const incomingSessionId = firstDefined(data.sessionId, data.session_id);
  const activeSessionId = firstDefined(announcedSessionId, currentSessionId);
  if (
    incomingSessionId != null &&
    activeSessionId != null &&
    String(incomingSessionId) !== String(activeSessionId)
  ) {
    console.warn("⏭️ [child.js] 忽略其他会话的教师端事件:", incomingSessionId);
    return false;
  }
  const incomingTrainingId = firstDefined(
    data.trainingSessionId,
    data.training_session_id
  );
  if (
    incomingTrainingId != null &&
    currentTrainingSessionId != null &&
    String(incomingTrainingId) !== String(currentTrainingSessionId)
  ) {
    console.warn("⏭️ [child.js] 忽略其他训练的教师端事件:", incomingTrainingId);
    return false;
  }
  return true;
}

function isEventForActiveChildSession(payload) {
  const data = payload && typeof payload === "object" ? payload : {};
  const incomingTrainingId = firstDefined(
    data.trainingSessionId,
    data.training_session_id
  );
  if (
    incomingTrainingId != null &&
    currentTrainingSessionId != null &&
    String(incomingTrainingId) !== String(currentTrainingSessionId)
  ) {
    return false;
  }

  const incomingSessionId = firstDefined(data.sessionId, data.session_id);
  const activeSessionId = firstDefined(announcedSessionId, currentSessionId);
  return !(
    incomingSessionId != null &&
    activeSessionId != null &&
    String(incomingSessionId) !== String(activeSessionId)
  );
}

// 教师端进入/离开控制界面
socket.on("teacher_enter_control", (payload) => {
  if (!isControlEventForCurrentSession(payload)) return;
  console.log("🟢 教师进入控制界面，保留待机/已提交课程直到新资源就绪");
});

socket.on("freeze_course_frame", (payload) => {
  if (!isControlEventForCurrentSession(payload)) return;
  freezeCommittedCourseFrame();
  console.log("⏸️ [child.js] 已冻结当前课程帧，等待评分/下一课");
});

function attachChildSession(sessionId) {
  if (!sessionId) return;
  const previousSessionId = announcedSessionId;
  if (
    previousSessionId &&
    String(previousSessionId) !== String(sessionId) &&
    socket &&
    socket.connected
  ) {
    socket.emit("leave_session", {
      sessionId: previousSessionId,
      role: "child",
    });
    console.log(
      "📡 [child.js] 已离开旧儿童会话房间:",
      previousSessionId,
      "->",
      sessionId
    );
  }
  announcedSessionId = sessionId;
  persistChildSessionBinding({ sessionId });
  ensureAudioPlayer(sessionId);
  if (audioPlayer) audioPlayer.sessionId = sessionId;
  if (socket && socket.connected) {
    socket.emit("join_session", {
      sessionId,
      role: "child",
    });
    console.log("📡 [child.js] 已立即加入儿童会话房间:", sessionId);
  }
}

socket.on("child_session_sync", (payload) => {
  if (!payload || !payload.sessionId) return;
  if (payload.studentId != null || payload.student_id != null) {
    childStudentId = firstDefined(payload.studentId, payload.student_id);
  }
  if (payload.trainingSessionId || payload.training_session_id) {
    currentTrainingSessionId = firstDefined(
      payload.trainingSessionId,
      payload.training_session_id
    );
  }
  attachChildSession(payload.sessionId);
  persistChildSessionBinding();
  console.log("🔄 [child.js] 已恢复儿童端会话绑定:", payload.sessionId);
  if (payload.content && typeof payload.content === "object") {
    handlePlayResource(payload.content);
  }
});

socket.on("training_prepare", async (payload) => {
  console.log("🎬 [child.js] 收到 training_prepare:", payload);
  if (!payload || !payload.sessionId) return;
  if (payload.studentId != null || payload.student_id != null) {
    childStudentId = firstDefined(payload.studentId, payload.student_id);
  }
  if (payload.trainingSessionId) {
    currentTrainingSessionId = payload.trainingSessionId;
  }
  // 后端可能紧接着下发首句音频；录制/Agent 启动前先 join 并绑定播放器。
  attachChildSession(payload.sessionId);
  if (payload.mediaMode === "agent" || payload.mediaMode === "browser") {
    childMediaMode = payload.mediaMode;
  }
  persistChildSessionBinding();
  if (payload.questionId) {
    currentQuestionId = payload.questionId;
  }
  const recordingMode = payload.recordingMode || "continuous";
  currentRecordingMode = recordingMode;
  if (payload.humanDirName) {
    currentHumanDirName = payload.humanDirName;
  }
  setChildCamPreviewFromAgent(childMediaMode === "agent");
  try {
    if (payload.preflightOnly) {
      const statusEl = document.getElementById("status");
      if (statusEl) statusEl.innerText = "设备自检中…";
      console.log("[child.js] strict preflight: 等待 readiness_complete 后正式采集");
      return;
    }
    // 重新 prepare 会 supersede 旧 media session：必须切到新 sessionId，
    // 不能走「连续录制切题不 stop」分支（否则继续往已关闭会话上行）。
    if (isRecording && currentSessionId && currentSessionId !== payload.sessionId) {
      console.log(
        "🔄 [child.js] prepare 新会话，停止旧录制:",
        currentSessionId, "->", payload.sessionId
      );
      await stopRecording({ notifyServer: false });
    }
    await startRecording(payload.sessionId, {
      recordingMode,
      humanDirName: currentHumanDirName,
    });
    const statusEl = document.getElementById("status");
    if (statusEl) {
      statusEl.innerText = childMediaMode === "agent"
        ? "准备录制中（等待选课/开课）…"
        : "准备录制中…";
    }
  } catch (err) {
    console.error("training_prepare 启动录制失败:", err);
  }
});

socket.on("training_prepare_cancel", async (payload) => {
  console.log("🛑 [child.js] 收到 training_prepare_cancel:", payload);
  if (!isControlEventForCurrentSession(payload)) return;
  cancelPendingResourceTransition();
  const endedSessionId = announcedSessionId || currentSessionId;
  await stopRecording({ notifyServer: false });
  if (endedSessionId && socket.connected) {
    socket.emit("leave_session", { sessionId: endedSessionId, role: "child" });
  }
  clearChildSessionBinding();
  showStandbyImage();
});

function ensureAudioPlayer(sessionId) {
  const sid = sessionId || currentSessionId || "readiness";
  if (!audioPlayer && window.AudioPlayer) {
    audioPlayer = new window.AudioPlayer(socket, sid);
    console.log("🔊 [child.js] 音频播放器已初始化 (readiness)");
  } else if (audioPlayer && sessionId) {
    audioPlayer.sessionId = sessionId;
  }
  return audioPlayer;
}

// 模块加载即绑定 play_audio；后续 prepare 只更新真实 sessionId。
ensureAudioPlayer("readiness");

function checkBrowserMediaTracksOk() {
  if (!mediaStream) return false;
  const tracks = mediaStream.getTracks();
  if (!tracks.length) return false;
  return tracks.every((t) => t.readyState === "live");
}

function ensureAudioUnlockOverlay() {
  let el = document.getElementById("audioUnlockOverlay");
  if (el) return el;
  el = document.createElement("div");
  el.id = "audioUnlockOverlay";
  el.style.cssText = [
    "display:none",
    "position:fixed",
    "inset:0",
    "z-index:9999",
    "background:rgba(15,23,42,0.72)",
    "color:#fff",
    "font-size:28px",
    "font-weight:700",
    "align-items:center",
    "justify-content:center",
    "text-align:center",
    "padding:40px",
    "cursor:pointer",
    "user-select:none",
  ].join(";");
  el.innerHTML = "<div>请点击屏幕启用声音<br/><span style='font-size:16px;font-weight:500;opacity:.85'>仅在首次播放课程语音时需要</span></div>";
  // pointerdown 本身就是浏览器认可的用户手势，必须在这个同步回调里重试 play()。
  el.addEventListener("pointerdown", () => {
    if (audioPlayer && typeof audioPlayer.retryBlockedPlayback === "function") {
      const retried = audioPlayer.retryBlockedPlayback();
      if (retried) hideAudioUnlockOverlay();
    }
  });
  document.body.appendChild(el);
  return el;
}

function showAudioUnlockOverlay() {
  const el = ensureAudioUnlockOverlay();
  el.style.display = "flex";
}

function hideAudioUnlockOverlay() {
  const el = document.getElementById("audioUnlockOverlay");
  if (el) el.style.display = "none";
}

window.addEventListener("audio-playback-blocked", (event) => {
  console.warn("🔇 浏览器拦截了有声播放，等待儿童端点击解锁:", event.detail);
  showAudioUnlockOverlay();
});

function waitForAudioUnlockGesture() {
  return new Promise((resolve) => {
    showAudioUnlockOverlay();
    const el = ensureAudioUnlockOverlay();
    const onGesture = () => {
      el.removeEventListener("pointerdown", onGesture);
      el.removeEventListener("click", onGesture);
      resolve();
    };
    el.addEventListener("pointerdown", onGesture, { once: true });
    el.addEventListener("click", onGesture, { once: true });
  });
}

function captureProbeFrameDataUrl() {
  try {
    const canvas = document.createElement("canvas");
    canvas.width = 320;
    canvas.height = 240;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;

    if (childMediaMode === "browser") {
      const cam = document.getElementById("childCam");
      if (cam && cam.videoWidth > 0) {
        ctx.drawImage(cam, 0, 0, canvas.width, canvas.height);
        return canvas.toDataURL("image/jpeg", 0.7);
      }
    }

    const previewImg = document.getElementById("childCamPreview");
    if (previewImg && previewImg.naturalWidth > 0) {
      ctx.drawImage(previewImg, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL("image/jpeg", 0.7);
    }
  } catch (err) {
    console.warn("captureProbeFrame 失败:", err);
  }
  return null;
}

// The only class-start command is the formal recording request below.
// Course and audio resources are loaded on demand by play_resource.
// The server opens the class after it has accepted the first formal video sample.
socket.on("readiness_complete", async (payload) => {
  if (!payload || !payload.captureStart || !payload.sessionId) return;
  if (payload.trainingSessionId) currentTrainingSessionId = payload.trainingSessionId;
  try {
    if (!isRecording || currentSessionId !== payload.sessionId) {
      await startRecording(payload.sessionId, {
        recordingMode: "continuous",
        captureDevices: payload.captureDevices || [],
      });
    }
    // Give the normal upload loop time to deliver at least one formal sample.
    // The server independently verifies its own counters/metadata; this report
    // is only a correlation acknowledgement and cannot make readiness green.
    await new Promise((resolve) => setTimeout(resolve, 1200));
    socket.emit("readiness_child_report", {
      trainingSessionId: payload.trainingSessionId,
      generation: payload.generation,
      sessionId: payload.sessionId,
      recording: !!isRecording,
      mediaTracksOk: childMediaMode === "browser" ? checkBrowserMediaTracksOk() : !!isRecording,
      captureStartConfirmed: true,
    });
    const statusEl = document.getElementById("status");
    if (statusEl) statusEl.innerText = "正式采集中";
  } catch (err) {
    console.error("strict preflight 正式采集启动失败:", err);
    socket.emit("readiness_child_report", {
      trainingSessionId: payload.trainingSessionId,
      generation: payload.generation,
      sessionId: payload.sessionId,
      recording: false,
      mediaTracksOk: false,
      captureStartError: String(err),
    });
  }
});

socket.on("teacher_leave_control", (payload) => {
  if (!isControlEventForCurrentSession(payload)) return;
  console.log("🔴 教师离开控制界面，显示待机图片");
  cancelPendingResourceTransition();
  showTransitionCover();

  // 隐藏当前内容
  imageEl.style.display = "none";
  videoEl.style.display = "none";
  audioEl.style.display = "none";
  interactiveEl.style.display = "none";

  const behaviorAnimationEl = document.getElementById("behaviorAnimationVideo");
  preparedBehaviorAnimation = null;
  if (activeBehaviorAnimationPlayback) {
    finishBehaviorAnimationPlayback(activeBehaviorAnimationPlayback, "stopped", "teacher_leave");
  } else if (heldPraiseOverlay) {
    clearHeldPraiseOverlay("teacher_leave");
  } else if (behaviorAnimationEl) {
    cleanupBehaviorAnimationElement(behaviorAnimationEl);
  }

  showStandbyImage();
  setTimeout(() => hideTransitionCover(), 100);
});

// 监听play_audio事件（新音频系统）
socket.on("play_audio", (data) => {
  console.log("🔊 [child.js] 收到 play_audio 事件:", data);
  // AudioPlayer 会自动处理，这里只做日志
});

socket.on("behavior_cancel", (data) => {
  const sessionId = announcedSessionId || currentSessionId || window.currentSessionId;
  const expected = behaviorIdentity(data || {});
  if (!expected.behaviorId || !expected.requestId || !data || !data.sessionId) return;

  window.BrowserTts?.cancelBrowserSpeechForBehavior?.(data);

  const playback = activeBehaviorAnimationPlayback;
  if (
    playback &&
    matchesExactBehaviorEnvelope(
      behaviorIdentity(playback.payload || {}),
      data,
      firstDefined(playback.payload && playback.payload.sessionId, sessionId, "")
    )
  ) {
    finishBehaviorAnimationPlayback(playback, "stopped", "behavior_cancelled");
  }
});

  // 浏览器 TTS：挂在 aux.question / praise / hint / 社交打招呼再见 与自由对话回复上
  // 服务端可能对 dialogue 连发 room+直达两份，短窗去重避免 cancel 自己
  let lastSpeakDedupeKey = "";
  let lastSpeakDedupeAt = 0;
  socket.on("robot_speak_text", (data) => {
  console.log("🗣️ [child.js] robot_speak_text:", data);
  if (!isEventForActiveChildSession(data)) {
    console.warn("⏭️ [child.js] 忽略旧会话/旧训练的 robot_speak_text:", data);
    return;
  }
  if (!data || !data.text) {
    // 仍通知互动页结束等待，避免 praise wait 卡到 maxMs 才切题
    notifyInteractiveSpeakEnded({
      intent: data && data.intent,
      sessionId: data && data.sessionId,
      text: data && data.text,
      speechId: data && (data.speechId || data.speech_id),
      behaviorId: data && (data.behaviorId || data.behavior_id),
      sequenceId: data && (data.sequenceId || data.sequence_id),
      status: "error",
      reason: "empty_text",
    });
    return;
  }
  const incomingIdentity = behaviorIdentity(data);
  const speakKey = incomingIdentity.key ||
    `${data.intent || ""}|${data.source || ""}|${String(data.text)}`;
  const now = Date.now();
  if (speakKey === lastSpeakDedupeKey && now - lastSpeakDedupeAt < 400) {
    console.log("🗣️ [child.js] 忽略重复 robot_speak_text");
    return;
  }
  lastSpeakDedupeKey = speakKey;
  lastSpeakDedupeAt = now;
  // 自由对话回复已由 child_dialogue_result 记入「麦麦」；此处只记课程/系统朗读
  const src = String(data.source || "").toLowerCase();
  const intent = String(data.intent || "").toLowerCase();
  if (src !== "dialogue" && intent !== "dialogue" && intent !== "wake_ack") {
    window.ChildDialogue?.appendDialogueLog?.("system", data.text);
  }
  if (!window.BrowserTts || !window.BrowserTts.isBrowserSpeechSynthesisSupported()) {
    console.warn("浏览器不支持 SpeechSynthesis");
    const statusEl = document.getElementById("dialogueStatus");
    if (statusEl) statusEl.textContent = "浏览器不支持朗读";
    notifyInteractiveSpeakEnded({
      intent: data.intent,
      sessionId: data.sessionId,
      text: data.text,
      ...incomingIdentity,
      status: "error",
      reason: "unsupported",
    });
    return;
  }
  const activeFileSpeech =
    audioPlayer && typeof audioPlayer.getActivePlaybackIdentity === "function"
      ? audioPlayer.getActivePlaybackIdentity()
      : null;
  if (activeFileSpeech) {
    const activeFileKey =
      activeFileSpeech.speechId ||
      activeFileSpeech.behaviorId ||
      activeFileSpeech.sequenceId ||
      activeFileSpeech.key ||
      "";
    const reason = activeFileKey && activeFileKey === incomingIdentity.key
      ? "duplicate"
      : "audio_busy";
    console.log("🛡️ [child.js] 文件语音活动中，丢弃新 TTS:", reason, incomingIdentity);
    if (reason !== "duplicate") {
      notifyInteractiveSpeakEnded({
        intent: data.intent,
        sessionId: data.sessionId,
        text: data.text,
        ...incomingIdentity,
        status: "dropped",
        reason,
      });
    }
    return;
  }
  // 朗读时暂停连续 ASR，避免喇叭回授进麦克风
  window.ChildDialogue?.pauseAsrForTts?.();
  // Do not enqueue a silent "unlock" utterance in front of formal speech.
  // SpeechSynthesis itself marks the output ready from its real onstart.
  const speechCommandReceivedAtMs = Date.now();
  const browserSpeechAccepted = window.BrowserTts.speakBrowserText(data.text, {
    delayMs: Number(data.delayMs) || 0,
    speechId: incomingIdentity.speechId,
    behaviorId: incomingIdentity.behaviorId,
    sequenceId: incomingIdentity.sequenceId,
    requestId: incomingIdentity.requestId,
    sessionId: data.sessionId || currentSessionId,
    onStart: (timing = {}) => {
      const statusEl = document.getElementById("dialogueStatus");
      if (statusEl) statusEl.textContent = `朗读中：${data.text}`;
      if (socket && socket.connected) {
        socket.emit("behavior_modality_started", {
          protocolVersion: data.protocolVersion || "1",
          sessionId: data.sessionId || currentSessionId,
          requestId: incomingIdentity.requestId || undefined,
          behaviorId: incomingIdentity.behaviorId || incomingIdentity.sequenceId || undefined,
          modality: "speech",
          status: "started",
          actualAtClientMs: Date.now(),
          commandReceivedAtClientMs: speechCommandReceivedAtMs,
          speakCalledAtClientMs: timing.speakCalledAtClientMs || undefined,
          speechAttempt: timing.attempt,
        });
      }
    },
    onEnd: (detail) => {
      const statusEl = document.getElementById("dialogueStatus");
      if (statusEl) statusEl.textContent = "准备就绪";
      window.ChildDialogue?.resumeAsrAfterTts?.();
      notifyInteractiveSpeakEnded({
        intent: data.intent,
        sessionId: data.sessionId,
        text: data.text,
        ...incomingIdentity,
        status: (detail && detail.status) || "ended",
        reason: (detail && detail.reason) || "",
      });
    },
    onError: (reason, detail) => {
      console.warn("browser TTS 失败:", reason);
      const statusEl = document.getElementById("dialogueStatus");
      if (statusEl) statusEl.textContent = `朗读失败：${reason}`;
      window.ChildDialogue?.resumeAsrAfterTts?.();
      notifyInteractiveSpeakEnded({
        intent: data.intent,
        sessionId: data.sessionId,
        text: data.text,
        ...incomingIdentity,
        status: (detail && detail.status) || "error",
        reason: reason || (detail && detail.reason) || "",
      });
    },
    onDrop: (reason) => {
      console.log("🛡️ [child.js] 行为语音活动中，丢弃新 TTS:", reason, incomingIdentity);
      if (!window.BrowserTts.isBrowserSpeechBusy?.()) {
        window.ChildDialogue?.resumeAsrAfterTts?.();
      }
      if (reason !== "duplicate") {
        notifyInteractiveSpeakEnded({
          intent: data.intent,
          sessionId: data.sessionId,
          text: data.text,
          ...incomingIdentity,
          status: "dropped",
          reason,
        });
      }
    },
  });
  if (browserSpeechAccepted && socket && socket.connected) {
    socket.emit("behavior_modality_ready", {
      protocolVersion: data.protocolVersion || "1",
      sessionId: data.sessionId || currentSessionId,
      requestId: incomingIdentity.requestId || undefined,
      behaviorId: incomingIdentity.behaviorId || incomingIdentity.sequenceId || undefined,
      speechId: incomingIdentity.speechId || undefined,
      readinessKey: incomingIdentity.speechId || incomingIdentity.key,
      modality: "speech",
      status: "ready",
      readyAtClientMs: Date.now(),
      commandReceivedAtClientMs: speechCommandReceivedAtMs,
      requestedDelayMs: Number(data.delayMs) || 0,
    });
  }
});

// 监听stop_recording事件
socket.on("stop_recording", async (data) => {
  console.log("收到stop_recording事件:", data);
  const endedSessionId = firstDefined(
    data && data.sessionId,
    data && data.session_id,
    announcedSessionId,
    currentSessionId
  );
  await stopRecording({ notifyServer: false });
  const reason = String((data && data.reason) || "").toLowerCase();
  if (reason === "finalize_training" || reason === "cancel_prepare_training") {
    if (endedSessionId && socket.connected) {
      socket.emit("leave_session", { sessionId: endedSessionId, role: "child" });
    }
    clearChildSessionBinding();
  }
});

// 监听trigger_action事件（自动播放表扬等）
socket.on("trigger_action", (data) => {
  console.log("🎬 收到触发动作:", data);
  
  const { action_type, target, data: actionData } = data;
  
  // 只处理发送给儿童端的动作
  if (target !== 'child' && target !== 'both') {
    return;
  }

  // browser TTS：表扬/提问/提示由 robot_speak_text 朗读，跳过预录 MP3
  if (
    dialogueTtsMode === "browser" &&
    (action_type === "play_audio" || action_type === "play_praise")
  ) {
    console.log("⏭️ [child.js] browser TTS 模式，跳过 trigger_action 预录:", action_type);
    return;
  }
  
  switch (action_type) {
    case 'play_audio':
      // 播放音频
      if (actionData && actionData.audio_file) {
        console.log("🔊 播放音频:", actionData.audio_file);
        const audio = new Audio("/static/" + actionData.audio_file);
        audio.play().catch(err => {
          console.error("播放音频失败:", err);
        });
      }
      break;
      
    case 'play_praise':
      // 播放表扬音频（使用当前课程的表扬音频）
      if (currentCourseId) {
        const course = findCourseById(currentCourseId);
        if (course && course.praise) {
          console.log("🎉 播放表扬:", course.praise);
          const audio = new Audio("/static/" + course.praise);
          audio.play().catch(err => {
            console.error("播放表扬失败:", err);
          });
        }
      }
      break;
      
    case 'show_message':
      // 显示消息（可选）
      if (actionData && actionData.message) {
        document.getElementById("status").innerText = actionData.message;
      }
      break;
      
    default:
      console.log("未知的动作类型:", action_type);
  }
});

socket.on("robot_motion_command", async (command) => {
  if (!command || !command.type) return;

  try {
    if (command.type === "play_motion") {
      const payload = command.payload || {};
      await callRobotAgent("/osc/play", {
        requestId: command.commandId,
        motionName: payload.motionName,
        frames: payload.frames || []
      });
    } else if (command.type === "realtime_pose") {
      const payload = command.payload || {};
      await callRobotAgent("/osc/frame", {
        requestId: command.commandId,
        pose: payload.pose || {},
        moveMs: payload.moveMs || 100
      });
    } else if (command.type === "stop_motion") {
      await callRobotAgent("/osc/stop", {
        requestId: command.commandId
      });
    } else {
      return;
    }

    socket.emit("robot_motion_ack", {
      commandId: command.commandId,
      ok: true
    });
  } catch (error) {
    console.error("❌ Robot Agent 转发失败:", error);
    socket.emit("robot_motion_ack", {
      commandId: command.commandId,
      ok: false,
      error: error.message
    });
  }
});

// 监听match_result事件（可选：在儿童端显示匹配结果）
socket.on("match_result", (data) => {
  //console.log("📊 收到匹配结果:", data);
  // 可以在这里更新UI显示匹配分数
  if (data.passed) {
    document.getElementById("status").innerText = "做得很好！匹配成功！";
  }
});

// 可选：预加载音频，避免延迟（委托 AudioPlayer，保持静默）
function preloadAudio(file) {
  ensureAudioPlayer(currentSessionId);
  if (audioPlayer && typeof audioPlayer.preloadAudio === "function") {
    return audioPlayer.preloadAudio(file);
  }
  const a = new Audio("/static/" + file);
  a.volume = 0;
  a.muted = true;
  a.load();
  return Promise.resolve(file);
}

function emitChildPresenceAndSync(requestSync = true) {
  if (!socket || !socket.connected) return;
  const binding = {
    role: "child",
    ts: Date.now(),
    studentId: childStudentId || undefined,
    trainingSessionId: currentTrainingSessionId || undefined,
    sessionId: announcedSessionId || currentSessionId || undefined,
    capabilities: {
      resourceReady: 1,
      atomicBehavior: 1,
      childSessionSync: 1,
    },
  };
  if (requestSync) {
    socket.emit("child_sync_request", {
      ...binding,
      requestId: `child-sync-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    });
  } else {
    socket.emit("client_presence", binding);
  }
}

// 页面加载时拉取运行时配置并初始化媒体
window.addEventListener("DOMContentLoaded", async () => {
  // 尽早注册 play_audio 监听，避免 training_prepare/play_resource 之前的首句丢失。
  ensureAudioPlayer(announcedSessionId || currentSessionId || "readiness");
  window.BrowserTts?.loadBrowserSpeechVoices?.();

  // Presence also carries the persisted binding/capability handshake so a
  // refreshed child can be rejoined and receive the last committed content.
  if (socket) {
    emitChildPresenceAndSync();
    if (!socket.__childSyncBound) {
      socket.on("connect", emitChildPresenceAndSync);
      socket.__childSyncBound = true;
    }
    setInterval(() => emitChildPresenceAndSync(false), 10000);
  }

  await loadChildRuntimeConfig();
  // Do not await this: media preloading must not delay readiness or the first
  // course transition. The formal playback element still validates canplay.
  void preloadBehaviorAnimations();
  await initMediaStream();
  // browser 联调不依赖本机 19091；避免控制台刷 ERR_CONNECTION_REFUSED
  if (childMediaMode === "agent") {
    await checkRobotAgentHealth();
    startRobotAgentHeartbeat();
    await checkMediaAgentHealth();
    startMediaAgentHeartbeat();
  } else {
    updateAgentStatusBadge(false, "Agent: 未启用(browser)");
    console.log("browser 模式：跳过 Robot/Media Agent 健康检查");
  }
});

if (socket) {
  socket.on("connect", () => {
    ensureAudioPlayer(announcedSessionId || currentSessionId || "readiness");
    const sessionId = announcedSessionId || currentSessionId;
    if (sessionId) {
      attachChildSession(sessionId);
    }
  });
}

// 这一段内容到时候要改一下，就是教师端那边点击"开始评估"后，摄像头就一直开着，包括app.py那里同步更改
// socket.on("show_image", () => {
//     document.getElementById("status").innerText = "展示图片！开始录制！";
//     document.getElementById("image").style.display = "block";
//     document.getElementById("video").style.display = "block";
//     camera.start();
// });

// ======================
// 进度条平滑显示 - 已注释，待迁移到后端
// ======================

// let smoothScore = 0; // 平滑后的分数
// const alpha = 0.2;   // 平滑系数 (0~1)，越小越平滑

// function updateSmoothScore(newScore) {
//   smoothScore = alpha * newScore + (1 - alpha) * smoothScore;
//   return smoothScore;
// }

// ======================
// 进度条更新逻辑
// ======================

// function updateProgressBar(score) {
//   const bar = document.getElementById("poseProgressBar");
//   const smooth = updateSmoothScore(score);

//   // 映射到 0-100% 区间
//   const percent = Math.min(100, Math.max(0, smooth * 100));
//   bar.style.width = percent + "%";
//   bar.innerText = percent.toFixed(1) + "%";
// }




// 姿态分析相关代码已注释，待迁移到后端
// 保存目标图片的姿态
// let targetNorm = null;
// let poseInitialized = false; // 跟踪MediaPipe初始化状态

// 确保MediaPipe已初始化
// async function ensurePoseInitialized() {
//   if (!poseInitialized) {
//     console.log("MediaPipe未初始化，正在初始化...");
//     await initPose();
//     poseInitialized = true;
//     console.log("MediaPipe初始化完成");
//   }
// }

//设置目标姿态的归一化
// async function setupTargetPose(imgEl) {
//   // 检查图像是否已加载且有有效尺寸
//   if (!imgEl.complete || imgEl.naturalWidth === 0 || imgEl.naturalHeight === 0) {
//     console.log("图像未完全加载，等待加载完成...");
//     return new Promise((resolve) => {
//       imgEl.onload = async () => {
//         try {
//           // 确保MediaPipe已初始化
//           await ensurePoseInitialized();
//           const pose = await detectImage(imgEl);
//           if (pose) {
//             targetNorm = normalizePose(pose);
//             console.log("目标图片已归一化:", targetNorm);
//           }
//         } catch (error) {
//           console.error("设置目标姿态失败:", error);
//         }
//         resolve();
//       };
//       imgEl.onerror = () => {
//         console.error("图像加载失败");
//         resolve();
//       };
//     });
//   }
//   
//   try {
//     // 确保MediaPipe已初始化
//     await ensurePoseInitialized();
//     const pose = await detectImage(imgEl);
//     if (pose) {
//       targetNorm = normalizePose(pose);
//       console.log("目标图片已归一化:", targetNorm);
//     }
//   } catch (error) {
//     console.error("设置目标姿态失败:", error);
//   }
// }

// 检查是否应该显示姿态匹配
// function shouldShowPoseMatching() {
//   return currentCourseId === 1;
// }

//检测当前姿态并得到相似度分数
// async function checkLivePose(videoEl) {
//   // 只有在courseId=1时才进行姿态匹配
//   if (!shouldShowPoseMatching()) {
//     return;
//   }
//   
//   // 检查视频元素是否准备就绪
//   if (!videoEl || videoEl.readyState < 2 || videoEl.videoWidth === 0 || videoEl.videoHeight === 0) {
//     return;
//   }
//   
//   try {
//     const ts = performance.now();
//     const pose = await detectVideo(videoEl, ts);
//     if (pose && targetNorm) {
//       const liveNorm = normalizePose(pose);
//       const score = poseSimilarity(targetNorm, liveNorm);
//       console.log("相似度分数:", score.toFixed(3));
//       // 更新进度条 (平滑后的)
//       updateProgressBar(score);
//     }
//   } catch (error) {
//     // 静默处理错误，避免控制台刷屏
//     if (error.message && !error.message.includes("ROI width and height must be > 0")) {
//       console.error("姿态检测错误:", error);
//     }
//   }
// }

//循环检测比较
// function loop(videoEl) {
//   checkLivePose(videoEl);
//   requestAnimationFrame(() => loop(videoEl));
// }

//实际执行流程
// async function testPose() {
//   try {
//     await initPose();
//     poseInitialized = true;
//     console.log("MediaPipe初始化完成");
//   } catch (error) {
//     console.error("MediaPipe初始化失败:", error);
//     poseInitialized = false;
//   }

//   // 2) 摄像头循环检测（一直运行）
//   const video = document.getElementById("childCam");
//   loop(video);
// }
//为 window 对象添加一个事件监听器，当 DOM 内容加载完成时执行 testPose 函数
// window.addEventListener("DOMContentLoaded", testPose);

// ======================
// 待机图片管理
// ======================

// 显示待机图片
function showStandbyImage() {
  const standbyEl = document.getElementById("standbyImage");
  if (standbyEl) {
    standbyEl.style.display = "block";
    console.log("✅ 待机图片已显示");
  }
}

// 隐藏待机图片
function hideStandbyImage() {
  const standbyEl = document.getElementById("standbyImage");
  if (standbyEl) {
    standbyEl.style.display = "none";
  }
  // 清除定时器（如果还未触发）
  if (standbyTimer) {
    clearTimeout(standbyTimer);
    standbyTimer = null;
  }
}

// ======================
// 行为绑定动画播放管理
// ======================

function behaviorAnimationPlaybackIdentity(videoPath, payload) {
  return String(firstDefined(
    payload && payload.behaviorId,
    payload && payload.behavior_id,
    payload && payload.sequenceId,
    payload && payload.sequence_id,
    payload && payload.speechId,
    payload && payload.speech_id,
    payload && payload.requestId,
    payload && payload.request_id,
    [
      "behavior-animation",
      firstDefined(payload && payload.sessionId, currentSessionId, "no-session"),
      firstDefined(payload && payload.questionId, currentQuestionId, "no-question"),
      videoPath,
    ].join(":")
  ));
}

function behaviorAnimationTerminalPayload(payload, playbackId, status, reason = "") {
  const identity = behaviorIdentity(payload || {});
  return {
    protocolVersion: firstDefined(payload && payload.protocolVersion, "1"),
    modality: "childAnimation",
    sessionId: firstDefined(payload && payload.sessionId, currentSessionId, ""),
    requestId: firstDefined(
      payload && payload.requestId,
      payload && payload.request_id,
      ""
    ),
    trainingSessionId: firstDefined(
      payload && payload.trainingSessionId,
      currentTrainingSessionId,
      ""
    ),
    questionId: firstDefined(payload && payload.questionId, currentQuestionId, ""),
    behaviorId: firstDefined(identity.behaviorId, identity.sequenceId, playbackId, ""),
    speechId: identity.speechId || "",
    sequenceId: identity.sequenceId || "",
    status,
    terminalStatus: status,
    actualAtClientMs: Date.now(),
    reason,
  };
}

function pruneCompletedBehaviorAnimationPlaybacks(now = Date.now()) {
  for (const [id, record] of completedBehaviorAnimationPlaybacks.entries()) {
    if (!record || now - record.completedAt > BEHAVIOR_ANIMATION_DEDUPE_TTL_MS) {
      completedBehaviorAnimationPlaybacks.delete(id);
    }
  }
  while (completedBehaviorAnimationPlaybacks.size > BEHAVIOR_ANIMATION_DEDUPE_MAX) {
    completedBehaviorAnimationPlaybacks.delete(
      completedBehaviorAnimationPlaybacks.keys().next().value
    );
  }
}

function cleanupBehaviorAnimationElement(video) {
  if (!video) return;
  video.onloadeddata = null;
  video.oncanplay = null;
  video.onplaying = null;
  video.onended = null;
  video.onerror = null;
  video.style.opacity = "0";
  video.style.pointerEvents = "none";
  video.style.display = "none";
  try {
    video.pause();
    video.removeAttribute("src");
    video.load();
  } catch (e) {}
}

function clearHeldPraiseOverlay(reason = "") {
  if (!heldPraiseOverlay) return;
  const held = heldPraiseOverlay;
  heldPraiseOverlay = null;
  if (activeBehaviorAnimationPlayback && activeBehaviorAnimationPlayback.video === held.video) {
    return;
  }
  cleanupBehaviorAnimationElement(held.video);
  console.log("🧹 [child.js] cleared held praise overlay:", reason || "unspecified");
}

function finishBehaviorAnimationPlayback(playback, status, reason = "") {
  if (!playback || playback.finished) return;
  playback.finished = true;
  if (playback.loadTimer != null) {
    clearTimeout(playback.loadTimer);
    playback.loadTimer = null;
  }
  if (playback.startTimer != null) {
    clearTimeout(playback.startTimer);
    playback.startTimer = null;
  }
  if (playback.watchdogTimer != null) {
    clearTimeout(playback.watchdogTimer);
    playback.watchdogTimer = null;
  }
  const terminal = behaviorAnimationTerminalPayload(
    playback.payload,
    playback.playbackId,
    status,
    reason
  );
  if (status !== "dropped") {
    completedBehaviorAnimationPlaybacks.set(playback.playbackId, {
      completedAt: Date.now(),
      payload: terminal,
    });
    pruneCompletedBehaviorAnimationPlaybacks();
  }

  // Keep the last praise frame until评分/下一题 advances — do not snap back
  // to the previous question image when the MP4 ends.
  if (status === "ended") {
    try {
      playback.video.pause();
    } catch (e) {}
    playback.video.style.opacity = "1";
    playback.video.style.display = "block";
    playback.video.style.pointerEvents = "none";
    if (activeBehaviorAnimationPlayback === playback) {
      activeBehaviorAnimationPlayback = null;
    }
    heldPraiseOverlay = {
      video: playback.video,
      playbackId: playback.playbackId,
      payload: playback.payload,
    };
    socket.emit("behavior_animation_ended", terminal);
    console.log("📡 [child.js] behavior_animation_ended (holding frame):", terminal);
    return;
  }

  playback.video.style.opacity = "0";
  playback.finishTimer = setTimeout(() => {
    if (activeBehaviorAnimationPlayback === playback) {
      activeBehaviorAnimationPlayback = null;
      cleanupBehaviorAnimationElement(playback.video);
    }
    socket.emit("behavior_animation_ended", terminal);
    console.log("📡 [child.js] behavior_animation_ended:", terminal);
  }, BEHAVIOR_ANIMATION_FADE_MS);
}

/**
 * Decode-only warm-up for prepare_behavior_animation.
 * Must not start playback or mark the request completed.
 */
function prepareBehaviorAnimation(videoPath, payload = {}) {
  const behaviorAnimationEl = document.getElementById("behaviorAnimationVideo");
  const playbackId = behaviorAnimationPlaybackIdentity(videoPath, payload);
  if (!behaviorAnimationEl || !videoPath) return false;
  if (activeBehaviorAnimationPlayback) {
    console.log("⏭️ [child.js] prepare skipped; animation already active:", playbackId);
    return false;
  }
  if (
    preparedBehaviorAnimation &&
    preparedBehaviorAnimation.playbackId === playbackId &&
    preparedBehaviorAnimation.video === behaviorAnimationEl
  ) {
    return true;
  }

  preparedBehaviorAnimation = {
    playbackId,
    videoPath,
    payload: { ...payload },
    video: behaviorAnimationEl,
    ready: false,
  };

  behaviorAnimationEl.onloadeddata = null;
  behaviorAnimationEl.oncanplay = null;
  behaviorAnimationEl.onplaying = null;
  behaviorAnimationEl.onended = null;
  behaviorAnimationEl.onerror = null;
  behaviorAnimationEl.style.display = "block";
  behaviorAnimationEl.style.opacity = "0";
  behaviorAnimationEl.style.pointerEvents = "none";
  behaviorAnimationEl.preload = "auto";

  const onReady = () => {
    if (
      !preparedBehaviorAnimation ||
      preparedBehaviorAnimation.playbackId !== playbackId
    ) {
      return;
    }
    if (preparedBehaviorAnimation.ready) return;
    preparedBehaviorAnimation.ready = true;
    const readyPayload = behaviorAnimationTerminalPayload(
      preparedBehaviorAnimation.payload,
      playbackId,
      "ready"
    );
    readyPayload.terminalStatus = null;
    readyPayload.readyAtClientMs = Date.now();
    socket.emit("behavior_modality_ready", readyPayload);
    console.log("🧊 [child.js] praise animation prepared (not started):", videoPath);
  };

  behaviorAnimationEl.onloadeddata = onReady;
  behaviorAnimationEl.oncanplay = onReady;
  setElementSource(behaviorAnimationEl, buildStaticUrl(videoPath));
  try {
    behaviorAnimationEl.load();
  } catch (e) {}
  if (behaviorAnimationEl.readyState >= 2) Promise.resolve().then(onReady);
  return true;
}

// The animation is an overlay; the committed course remains intact underneath.
function playBehaviorAnimation(videoPath, payload = {}) {
  const behaviorAnimationEl = document.getElementById("behaviorAnimationVideo");
  const playbackId = behaviorAnimationPlaybackIdentity(videoPath, payload);
  pruneCompletedBehaviorAnimationPlaybacks();

  const completed = completedBehaviorAnimationPlaybacks.get(playbackId);
  if (completed) {
    socket.emit("behavior_animation_ended", completed.payload);
    console.log("↩️ [child.js] duplicate animation acknowledged without replay:", playbackId);
    return false;
  }
  if (activeBehaviorAnimationPlayback) {
    if (activeBehaviorAnimationPlayback.playbackId !== playbackId) {
      const dropped = behaviorAnimationTerminalPayload(payload, playbackId, "dropped", "animation_busy");
      socket.emit("behavior_animation_ended", dropped);
    }
    console.log("⏭️ [child.js] animation dropped while another animation is active:", playbackId);
    return false;
  }
  if (!behaviorAnimationEl || !videoPath) {
    const failed = behaviorAnimationTerminalPayload(payload, playbackId, "error", "animation_resource_missing");
    socket.emit("behavior_animation_ended", failed);
    console.warn("⚠️ 无法播放行为动画：元素不存在或路径为空", videoPath);
    return false;
  }

  clearHeldPraiseOverlay("new_praise");
  const reusePrepared =
    preparedBehaviorAnimation &&
    preparedBehaviorAnimation.playbackId === playbackId &&
    preparedBehaviorAnimation.video === behaviorAnimationEl;
  preparedBehaviorAnimation = null;

  const playback = {
    playbackId,
    payload: { ...payload },
    video: behaviorAnimationEl,
    finished: false,
    playStarted: false,
    startScheduled: false,
    startTimer: null,
    loadTimer: null,
    finishTimer: null,
    watchdogTimer: null,
    readyEmitted: Boolean(reusePrepared && behaviorAnimationEl.readyState >= 2),
  };
  activeBehaviorAnimationPlayback = playback;
  if (!reusePrepared) {
    cleanupBehaviorAnimationElement(behaviorAnimationEl);
    behaviorAnimationEl.style.display = "block";
    behaviorAnimationEl.style.opacity = "0";
    behaviorAnimationEl.style.pointerEvents = "none";
    behaviorAnimationEl.preload = "auto";
    try {
      behaviorAnimationEl.currentTime = 0;
    } catch (e) {}
  } else {
    behaviorAnimationEl.style.display = "block";
    behaviorAnimationEl.style.opacity = "0";
    behaviorAnimationEl.style.pointerEvents = "none";
    try {
      behaviorAnimationEl.currentTime = 0;
    } catch (e) {}
  }

  const startPlayback = () => {
    if (activeBehaviorAnimationPlayback !== playback || playback.finished) return;
    if (playback.playStarted) return;
    playback.playStarted = true;
    playback.startScheduled = false;
    playback.startTimer = null;
    if (playback.loadTimer != null) {
      clearTimeout(playback.loadTimer);
      playback.loadTimer = null;
    }
    behaviorAnimationEl.onloadeddata = null;
    behaviorAnimationEl.oncanplay = null;
    // Preloading must not pause the course. Freeze only at the shared start
    // anchor when the encouragement overlay actually becomes visible.
    freezeCommittedCourseFrame();
    behaviorAnimationEl.play().then(() => {
      if (activeBehaviorAnimationPlayback !== playback || playback.finished) return;
      behaviorAnimationEl.style.opacity = "1";
      const mediaDurationMs = Number.isFinite(behaviorAnimationEl.duration)
        ? Math.ceil(behaviorAnimationEl.duration * 1000)
        : 0;
      const watchdogMs = Math.max(3000, mediaDurationMs + 2000);
      playback.watchdogTimer = setTimeout(() => {
        finishBehaviorAnimationPlayback(playback, "error", "animation_ended_timeout");
      }, watchdogMs);
      const startedPayload = behaviorAnimationTerminalPayload(
        playback.payload,
        playback.playbackId,
        "started"
      );
      startedPayload.terminalStatus = null;
      startedPayload.actualAtClientMs = Date.now();
      socket.emit("behavior_modality_started", startedPayload);
      console.log("🎬 [child.js] 行为动画叠层开始:", videoPath);
    }).catch(error => {
      finishBehaviorAnimationPlayback(
        playback,
        "error",
        error && error.name ? error.name : "play_failed"
      );
    });
  };
  const onReady = () => {
    if (activeBehaviorAnimationPlayback !== playback || playback.finished) return;
    if (!playback.readyEmitted) {
      playback.readyEmitted = true;
      const readyPayload = behaviorAnimationTerminalPayload(
        playback.payload,
        playback.playbackId,
        "ready"
      );
      readyPayload.terminalStatus = null;
      readyPayload.readyAtClientMs = Date.now();
      socket.emit("behavior_modality_ready", readyPayload);
    }
    if (playback.playStarted || playback.startScheduled) return;
    const relativeDelayMs = Number(payload.behaviorStartDelayMs);
    const startAtMs = Number(payload.behaviorStartAtMs || 0);
    const remainingMs = Number.isFinite(relativeDelayMs)
      ? Math.max(0, relativeDelayMs)
      : Math.max(0, startAtMs - Date.now());
    if (remainingMs > 0) {
      playback.startScheduled = true;
      playback.startTimer = setTimeout(startPlayback, remainingMs);
      return;
    }
    startPlayback();
  };
  behaviorAnimationEl.onloadeddata = onReady;
  behaviorAnimationEl.oncanplay = onReady;
  behaviorAnimationEl.onended = () => finishBehaviorAnimationPlayback(playback, "ended");
  behaviorAnimationEl.onerror = () => finishBehaviorAnimationPlayback(playback, "error", "video_load_failed");
  playback.loadTimer = setTimeout(() => {
    finishBehaviorAnimationPlayback(playback, "error", "video_load_timeout");
  }, RESOURCE_LOAD_TIMEOUT_MS);
  if (!reusePrepared) {
    setElementSource(behaviorAnimationEl, buildStaticUrl(videoPath));
    try { behaviorAnimationEl.load(); } catch (e) {}
  }
  if (behaviorAnimationEl.readyState >= 2) Promise.resolve().then(onReady);
  return true;
}


