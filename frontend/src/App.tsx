import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./styles.css";
import type { AppPage, ChatReply, CourseOption, CourseQuestion } from "./types";
import { getApiOrigin, getScreenRoleFromPathname } from "./config/runtime";
import { sendChatMessage } from "./services/trainingService";
import { useCourseFlow } from "./hooks/useCourseFlow";
import { useVoiceCapture, type VoiceMode } from "./hooks/useVoiceCapture";
import { ReportBackgroundBubbles } from "./features/report/ReportBackgroundBubbles";
import { deriveReportMetrics, formatReportDateTime } from "./features/report/reportMetrics";
import { ProfessionalReportV2Content } from "./features/report/ProfessionalReportV2Content";
import { isNarrativePending } from "./features/report/reportNarrativeStatus";
import {
  getPreferredBrowserSpeechVoiceName,
  isBrowserSpeechSynthesisSupported,
  loadBrowserSpeechVoices,
  playChatReplyAudio,
  setPreferredBrowserSpeechVoice,
  stopChatReplyAudio,
  subscribeBrowserSpeechVoiceChanges,
  unlockBrowserSpeechOutput,
  type BrowserSpeechVoiceOption
} from "./features/voice/audioPlayback";
import { buildPageContextPayload, buildPageContextText, toBuildPageContextInput } from "./features/voice/buildPageContext";
import { fetchVoiceDialogConfig, persistTranscriptObservations } from "./features/voice/partnerVoiceClient";
import type { VoiceDialogProviderKind } from "./hooks/useVoiceCapture";
import { BrowserCameraCaptureController, type BrowserCameraCaptureState } from "./features/camera/browserCameraCapture";
import { isAnswerTransitionLocked } from "./features/training/questionTransition";
import { isStaleVideoIngressError, VideoPersistenceQueue } from "./features/camera/videoPersistenceQueue";
import { uploadMonitorPreviewFrame } from "./services/monitorPreviewClient";
import { sendCameraFrameDescriptor } from "./features/camera/cameraFrameClient";
import {
  finishVideoStream,
  sendVideoSegment,
  startVideoStream,
  uploadVideoThumbnail
} from "./features/camera/videoMediaIngressClient";
import { getRawMediaConfig } from "./services/rawMediaService";
import {
  CourseSelectPageShell,
  ReportDetailPageShell,
  ReportPageShell,
  TrainingPageShell,
  WelcomePageShell
} from "./pages/PageShells";
import { RobotScreen } from "./pages/RobotScreen";
import { ServerDashboard } from "./pages/ServerDashboard";
import { useScreenMirrorSource } from "./features/screenMirror/screenMirror";

const COURSE_OPTIONS: CourseOption[] = [
  {
    type: "matching",
    title: "配对训练",
    description: "看上面的图片，点一样的图片",
    iconUrl: "/matching/icon/matching-icon.png",
    enabled: true
  },
  {
    type: "ordering",
    title: "数学课",
    description: "在有趣的图形里练习大小、长短和多少",
    iconUrl: "/paixu/icon/Math-icon.png",
    enabled: true
  }
];

const BACKEND_ORIGIN = getApiOrigin();

type ReportLayout = "landscape" | "portrait";
type HomeParticle = {
  id: number;
  left: number;
  top: number;
  size: number;
  color: string;
  isStar: boolean;
  tx: number;
  ty: number;
  duration: number;
  rotate: number;
};

const HOME_PARTICLE_COLORS = ["#FF4081", "#00E5FF", "#76FF03", "#FFD600", "#FF9100", "#D500F9"];
/** Brief delay only for the first camera cold start so option animations can settle. */
const CAMERA_FIRST_START_DELAY_MS = 300;

function formatVoiceStatus(reason: string) {
  const labels: Record<string, string> = {
    MIC_PERMISSION_DENIED: "浏览器没有麦克风权限，请在地址栏允许麦克风后刷新页面。",
    NO_MICROPHONE: "没有检测到可用麦克风，请检查设备连接。",
    MIC_CAPTURE_FAILED: "麦克风启动失败，请确认没有被其他软件占用。",
    AUDIO_CAPTURE_UNSUPPORTED: "当前浏览器不支持录音采集，请使用 Chrome 或 Edge。",
    MEDIA_RECORDER_UNSUPPORTED: "当前浏览器不支持本地录音采集，请使用 Chrome 或 Edge。",
    MEDIA_STREAM_START_FAILED: "后端录音流启动失败，请确认本地服务正在运行。",
    MEDIA_STREAM_FINISH_FAILED: "录音结束请求失败，请稍后再试。",
    MEDIA_TRANSPORT_FAILED: "音频上传失败，请稍后再试。",
    STT_PROVIDER_UNAVAILABLE: "语音识别服务暂时不可用。",
    STT_EMPTY_RESULT: "没有识别到语音，请靠近麦克风再说一次。",
    AUDIO_FEATURE_UPLOAD_FAILED: "语音特征上传失败，但可以继续录音。",
    DEVICE_LOST: "麦克风连接中断，请检查设备。",
    BROWSER_SPEECH_COMPAT_UNAVAILABLE: "浏览器语音兼容模式不可用，本地录音模式仍可使用。",
    VOICE_ACTIVITY_UNSUPPORTED: "当前浏览器不支持声控检测，请使用麦克风按钮。",
    VOICE_ACTIVITY_FAILED: "声控检测启动失败，请检查麦克风是否被占用。"
  };
  return labels[reason] ?? reason;
}

function formatAutoVoiceStatus(status: string, active: boolean) {
  if (!active) return "声控：已暂停";
  if (status === "requesting_permission") return "声控：等待麦克风权限";
  if (status === "listening") return "声控：等待声音";
  if (status === "triggered") return "声控：检测到声音";
  if (status === "permission_denied") return "声控：没有麦克风权限";
  if (status === "no_device") return "声控：未检测到麦克风";
  if (status === "unsupported") return "声控：浏览器不支持";
  if (status === "error") return "声控：启动失败";
  return "声控：准备中";
}

function resolveAsset(src?: string) {
  if (!src) return "";
  if (src.startsWith("http://") || src.startsWith("https://")) return src;
  return `${BACKEND_ORIGIN}${src.startsWith("/") ? src : `/${src}`}`;
}

type VoiceLog = {
  id: number;
  role: "child" | "assistant" | "system";
  text: string;
};

function isHelpRequestSpeech(text: string) {
  return /(不会|不知道|不知|不懂|怎么选|选哪个|哪一个|帮帮|帮我|提示|答案)/.test(text);
}

const MATCHING_CORRECT_FEEDBACK_LINES = [
  "回答正确，真棒！",
  "做对了，真棒！",
  "找对了，很好！",
  "答对了，继续加油！",
  "选对了，真不错！",
  "回答正确，做得好！",
  "这题答对了，真棒！"
];

const ORDERING_CORRECT_FEEDBACK_LINES = [
  "回答正确，真棒！",
  "做对了，真棒！",
  "答对了，很好！",
  "选对了，真不错！",
  "这题做对了！",
  "回答正确，继续加油！",
  "你答对了，真棒！",
];

const COURSE_COMPLETE_FEEDBACK_LINES = [
  "这一节完成了，真棒！",
  "这一关做完了，很好！",
  "完成这一节了，继续加油！",
  "这一关完成了，真不错！"
];

const ALL_TRAINING_COMPLETE_FEEDBACK_LINES = [
  "训练完成了，真棒！",
  "今天全部做完了，很好！",
  "所有题都完成了，真棒！",
  "今天做完了，继续加油！",
  "训练结束了，真不错！",
];

const MATCHING_WRONG_FEEDBACK_LINES = [
  "没关系，再试一次",
  "我们慢慢来，先看颜色，再看形状。",
  "这次还可以再试试，麦麦陪你一起看。",
  "一步一步来，先看上面的图片。",
  "我们再看一遍上面那张，慢慢找。",
  "眼睛慢慢看，找颜色和形状都一样的图片。",
  "麦麦陪你，再找一张更像的。",
  "先找和上面最像的那一张。",
  "换个小方法，先看上面那张哪里特别。"
];

const ORDERING_WRONG_FEEDBACK_LINES = [
  "没关系，再试一次",
  "我们慢慢来，先比较，再选择。",
  "慢慢来，我们再看一遍。",
  "这次还可以再试试，麦麦陪你一起比较。",
  "我们慢慢来，再比较一次吧。",
  "不着急，把大小、长短或多少看清楚。",
  "麦麦在这里陪你，再试一次。",
  "这一步需要多想一会儿，我们慢慢比较。",
];

const MATCHING_WRONG_FEEDBACK_WITH_HINT_LINES = [
  "你一直在努力。麦麦给你一个小提示，看亮起来的那一张。",
  "跟着提示看一看，再点一下。",
  "麦麦来帮你一点点，看提示的位置。",
  "这次用提示来帮忙，看亮起来的图片。",
  "你已经试了好几次。现在看麦麦提示的那一张。",
  "我们轻轻看提示，那一张更像。",
  "麦麦把范围变小一点，看提示出来的位置。"
];

const ORDERING_WRONG_FEEDBACK_WITH_HINT_LINES = [
  "你一直在努力。麦麦给你一个小提示，看亮起来的那一个。",
  "我们慢慢来。现在看亮起来的那个。",
  "跟着提示看一看，再点一下。",
  "麦麦来帮你一点点，看提示的位置。",
  "这次看提示，点亮起来的那个。",
  "你已经试了好几次。现在看麦麦提示的那一个。",
  "麦麦把范围变小一点，看提示出来的位置。"
];

function pickLine(lines: string[], recent: string[] = []) {
  const available = lines.filter((line) => !recent.includes(line));
  const pool = available.length > 0 ? available : lines;
  return pool[Math.floor(Math.random() * pool.length)] ?? pool[0] ?? "";
}

function ChildApp() {
  useScreenMirrorSource("child");
  const [page, setPage] = useState<AppPage>("welcome");
  const [visiblePage, setVisiblePage] = useState<AppPage>("welcome");
  const [pageTransition, setPageTransition] = useState<"active" | "hidden">("active");
  const [childName, setChildName] = useState("小朋友");
  const [homeParticles, setHomeParticles] = useState<HomeParticle[]>([]);
  const [voiceMode, setVoiceMode] = useState<VoiceMode>("single");
  const [voicePanelOpen, setVoicePanelOpen] = useState(false);
  const [voiceLogs, setVoiceLogs] = useState<VoiceLog[]>([]);
  const [autoVoiceTriggerEnabled, setAutoVoiceTriggerEnabled] = useState(true);
  const [autoSpeakEnabled, setAutoSpeakEnabled] = useState(true);
  const [speechVoiceOptions, setSpeechVoiceOptions] = useState<BrowserSpeechVoiceOption[]>([]);
  const [selectedSpeechVoiceName, setSelectedSpeechVoiceName] = useState("");
  const [speechStatus, setSpeechStatus] = useState<"idle" | "speaking" | "unsupported" | "error">(
    isBrowserSpeechSynthesisSupported() ? "idle" : "unsupported"
  );
  const [speechError, setSpeechError] = useState("");
  const [reportLayout, setReportLayout] = useState<ReportLayout>("landscape");
  const [narrativeLoading, setNarrativeLoading] = useState(false);
  const cameraCaptureRef = useRef<BrowserCameraCaptureController | null>(null);
  const cameraQuestionRef = useRef<string | null>(null);
  const cameraSessionRef = useRef<string | null>(null);
  const cameraFailureSentRef = useRef<string | null>(null);
  const rawMediaEnabledRef = useRef(false);
  const videoPersistenceQueueRef = useRef<VideoPersistenceQueue | null>(null);
  const voiceContextRootRef = useRef<HTMLDivElement | null>(null);
  const maimaiGreetingPlayedRef = useRef(false);
  const voiceHelpRequestCountRef = useRef<Record<string, number>>({});
  const recentAnswerFeedbackRef = useRef<string[]>([]);
  const [voiceDialogProvider, setVoiceDialogProvider] = useState<VoiceDialogProviderKind>("rule");
  const {
    activeCourseIndex,
    courseQuestionTotals,
    courseStars,
    error,
    feedback,
    flashBg,
    handleSelectAnswer,
    handleStartTraining,
    handleToggleCourse,  
    hint,
    loading,
    optionStates,
    currentQuestionWrongAttempts,
    questionStartAt,
    question,
    queuedCourses,
    report,
    refreshMergedReport,
    resetToSelect,
    resetToWelcome,
    selectedCourses,
    session,
    setError
  } = useCourseFlow({
    childName,
    courseOptions: COURSE_OPTIONS,
    onPageChange: setPage,
    onCourseStarted: () => undefined,
    onAnswerFeedback: handleAnswerFeedback,
    onVoiceReset: () => {
      setVoiceLogs([]);
      recentAnswerFeedbackRef.current = [];
      void stopVoiceCapture();
    }
  });

  function handleAnswerFeedback(input: {
    question: CourseQuestion;
    selectedOptionId: string;
    correct: boolean;
    courseCompleted: boolean;
    correctOptionId?: string;
    wrongAttemptsAfter: number;
  }) {
    const correctOption = input.correctOptionId
      ? input.question.payload.options.find((option) => option.id === input.correctOptionId)
      : undefined;
    const isMatching = input.question.courseType === "matching";
    const recentFeedback = recentAnswerFeedbackRef.current;
    let text = "";
    if (input.correct && input.courseCompleted) {
      const hasNextCourse = activeCourseIndex + 1 < queuedCourses.length;
      text = pickLine(hasNextCourse ? COURSE_COMPLETE_FEEDBACK_LINES : ALL_TRAINING_COMPLETE_FEEDBACK_LINES, recentFeedback);
    } else if (input.correct) {
      text = pickLine(isMatching ? MATCHING_CORRECT_FEEDBACK_LINES : ORDERING_CORRECT_FEEDBACK_LINES, recentFeedback);
    } else if (input.wrongAttemptsAfter >= 2 && correctOption?.label) {
      const hintLine = pickLine(
        isMatching ? MATCHING_WRONG_FEEDBACK_WITH_HINT_LINES : ORDERING_WRONG_FEEDBACK_WITH_HINT_LINES,
        recentFeedback
      );
      text = isMatching ? `${hintLine} 我们再找${correctOption.label}。` : hintLine;
    } else {
      text = pickLine(isMatching ? MATCHING_WRONG_FEEDBACK_LINES : ORDERING_WRONG_FEEDBACK_LINES, recentFeedback);
    }
    recentAnswerFeedbackRef.current = [...recentFeedback, text].slice(-6);

    const reply: ChatReply = {
      reply: text,
      strategy: input.correct ? "local_answer_praise" : "local_answer_encourage",
      provider: "local-maimai",
      timestamp: new Date().toISOString()
    };
    setVoicePanelOpen(true);
    setVoiceLogs((prev) => [...prev.slice(-11), { id: Date.now(), role: "assistant", text }]);
    playAssistantReply(reply);
  }

  const getVoicePageContext = useCallback(async () => {
    if (!question) {
      throw new Error("QUESTION_NOT_READY");
    }
    const selectedOptionIds = Object.entries(optionStates)
      .filter(([, state]) => state === "correct" || state === "wrong")
      .map(([id]) => id);
    return buildPageContextPayload(
      {
        question,
        wrongAttempts: currentQuestionWrongAttempts,
        helpRequestCount: voiceHelpRequestCountRef.current[question.questionId] ?? 0,
        questionElapsedMs: questionStartAt ? Math.max(0, Date.now() - questionStartAt) : 0,
        selectedOptionIds
      },
      voiceContextRootRef.current
    );
  }, [currentQuestionWrongAttempts, optionStates, question, questionStartAt]);

  const getVoiceChatPageContext = useCallback(() => {
    if (!question) return undefined;
    const selectedOptionIds = Object.entries(optionStates)
      .filter(([, state]) => state === "correct" || state === "wrong")
      .map(([id]) => id);
    return buildPageContextText(
      toBuildPageContextInput({
        question,
        wrongAttempts: currentQuestionWrongAttempts,
        helpRequestCount: voiceHelpRequestCountRef.current[question.questionId] ?? 0,
        questionElapsedMs: questionStartAt ? Math.max(0, Date.now() - questionStartAt) : 0,
        selectedOptionIds
      })
    );
  }, [currentQuestionWrongAttempts, optionStates, question, questionStartAt]);

  async function handlePartnerTurnComplete(reply: ChatReply) {
    const logId = Date.now();
    setVoicePanelOpen(true);
    setVoiceLogs((prev) => [...prev.slice(-11), { id: logId, role: "assistant", text: reply.reply }]);
    playAssistantReply(reply);
  }

  const autoVoiceTriggerActive =
    autoVoiceTriggerEnabled && page === "training" && speechStatus !== "speaking" && voiceMode === "single";
  const {
    autoVoiceTriggerState,
    interimText,
    startVoiceCapture,
    stopVoiceCapture,
    voiceFallbackReason,
    voiceListening,
    voiceSupported
  } = useVoiceCapture({
    voiceMode,
    sessionId: session?.sessionId,
    dialogProvider: voiceDialogProvider,
    getPageContext: voiceDialogProvider === "partner" ? getVoicePageContext : undefined,
    onPartnerTurnComplete: voiceDialogProvider === "partner" ? handlePartnerTurnComplete : undefined,
    autoVoiceTriggerEnabled: autoVoiceTriggerActive,
    onFinalTranscript: handleVoiceFinal
  });

  const pageTitle = useMemo(() => {
    if (visiblePage === "welcome") return "欢迎来到互动训练";
    if (visiblePage === "select") return "请选择课程";
    if (visiblePage === "training") return "开始训练";
    if (visiblePage === "reportDetail") return "训练观察报告";
    return "训练报告";
  }, [visiblePage]);

  const reportMetrics = useMemo(() => deriveReportMetrics(report), [report]);

  useEffect(() => {
    if (page === visiblePage) {
      setPageTransition("active");
      return;
    }

    setPageTransition("hidden");
    const swapTimer = window.setTimeout(() => {
      setVisiblePage(page);
      setPageTransition("active");
    }, 300);

    return () => {
      window.clearTimeout(swapTimer);
    };
  }, [page, visiblePage]);

  useEffect(() => {
    void fetchVoiceDialogConfig()
      .then((config) => setVoiceDialogProvider(config.dialogProvider))
      .catch(() => setVoiceDialogProvider("rule"));
  }, []);

  useEffect(() => {
    void getRawMediaConfig()
      .then((config) => {
        rawMediaEnabledRef.current = config.persistence === "enabled";
      })
      .catch(() => {
        rawMediaEnabledRef.current = false;
      });
  }, []);

  useEffect(() => {
    const refreshVoices = () => {
      const options = loadBrowserSpeechVoices();
      setSpeechVoiceOptions(options);
      setSelectedSpeechVoiceName(getPreferredBrowserSpeechVoiceName());
      setSpeechStatus(isBrowserSpeechSynthesisSupported() ? "idle" : "unsupported");
    };
    refreshVoices();
    return subscribeBrowserSpeechVoiceChanges(refreshVoices);
  }, []);

  useEffect(() => {
    return () => {
      stopChatReplyAudio();
    };
  }, []);

  function playMaimaiGreeting() {
    if (maimaiGreetingPlayedRef.current) return;
    maimaiGreetingPlayedRef.current = true;

    const greeting = "你好呀，我叫麦麦。快来和我一起玩吧。";
    const reply: ChatReply = {
      reply: greeting,
      strategy: "proactive_greeting",
      provider: "local-maimai",
      timestamp: new Date().toISOString()
    };
    setVoicePanelOpen(true);
    setVoiceLogs((prev) => [...prev.slice(-11), { id: Date.now(), role: "assistant", text: greeting }]);
    playAssistantReply(reply);
  }

  function playAssistantReply(reply: ChatReply) {
    if (!autoSpeakEnabled) return;
    playChatReplyAudio(reply, {
      browserSpeechFallback: true,
      onStart: () => {
        setSpeechError("");
        setSpeechStatus("speaking");
      },
      onEnd: () => setSpeechStatus(isBrowserSpeechSynthesisSupported() ? "idle" : "unsupported"),
      onError: (reason) => {
        setSpeechError(reason);
        setSpeechStatus("error");
      }
    });
  }

  function handleSpeechVoiceChange(name: string) {
    setPreferredBrowserSpeechVoice(name);
    setSelectedSpeechVoiceName(getPreferredBrowserSpeechVoiceName());
  }

  function handleStopSpeaking() {
    stopChatReplyAudio();
    setSpeechStatus(isBrowserSpeechSynthesisSupported() ? "idle" : "unsupported");
    setSpeechError("");
  }

  function formatSpeechStatus() {
    if (speechStatus === "speaking") return "正在朗读";
    if (speechStatus === "unsupported") return "当前浏览器不支持语音输出";
    if (speechStatus === "error") return `朗读失败：${speechError || "请先点击麦克风或测试朗读"}`;
    return "准备朗读";
  }

  useEffect(() => {
    const controller = new BrowserCameraCaptureController({
      onFrame: (descriptor) => {
        void sendCameraFrameDescriptor(descriptor).catch(() => undefined);
      },
      onStateChange: (state) => {
        if (state.status === "permission_denied" || state.status === "no_device" || state.status === "unsupported" || state.status === "error") {
          void sendCameraUnavailableDescriptor(state);
        }
      }
    });
    cameraCaptureRef.current = controller;
    return () => {
      controller.dispose();
      cameraCaptureRef.current = null;
    };
  }, []);

  function getVideoPersistenceQueue() {
    if (!videoPersistenceQueueRef.current) {
      videoPersistenceQueueRef.current = new VideoPersistenceQueue();
    }
    return videoPersistenceQueueRef.current;
  }

  function buildCameraRawVideoPersistence() {
    const queue = getVideoPersistenceQueue();
    return rawMediaEnabledRef.current
      ? {
          enabled: true as const,
          onStreamReady: ({
            streamId,
            mimeType,
            sessionId: sid,
            questionId: qid,
            correlationId: cid
          }: {
            streamId: string;
            mimeType: string;
            sessionId: string;
            questionId?: string;
            correlationId: string;
          }) =>
            queue.enqueue(async () => {
              await startVideoStream({
                sessionId: sid,
                streamId,
                correlationId: cid,
                questionId: qid,
                startedAt: new Date().toISOString(),
                mimeType
              });
            }),
          onSegment: ({
            streamId,
            sequence,
            blob,
            mimeType,
            durationMs,
            capturedAt,
            sessionId: sid,
            correlationId: cid
          }: {
            streamId: string;
            sequence: number;
            blob: Blob;
            mimeType: string;
            durationMs: number;
            capturedAt: string;
            sessionId: string;
            correlationId: string;
          }) =>
            queue.enqueueSegment(streamId, async () => {
              try {
                await sendVideoSegment({
                  sessionId: sid,
                  streamId,
                  correlationId: cid,
                  sequence,
                  capturedAt,
                  durationMs,
                  mimeType,
                  blob
                });
              } catch (error) {
                if (!isStaleVideoIngressError(error)) throw error;
              }
            }),
          onThumbnail: ({
            streamId,
            blob,
            mimeType,
            sessionId: sid,
            correlationId: cid
          }: {
            streamId: string;
            blob: Blob;
            mimeType: string;
            sessionId: string;
            correlationId: string;
          }) =>
            queue.enqueue(async () => {
              await uploadVideoThumbnail({
                sessionId: sid,
                streamId,
                correlationId: cid,
                mimeType,
                blob
              });
            }),
          onStreamFinish: ({
            streamId,
            reason,
            sessionId: sid,
            correlationId: cid
          }: {
            streamId: string;
            reason: string;
            sessionId: string;
            correlationId: string;
          }) =>
            queue.finishStream(streamId, async () => {
              try {
                await finishVideoStream({
                  sessionId: sid,
                  streamId,
                  correlationId: cid,
                  reason: reason === "device_lost" ? "device_lost" : "question_end",
                  endedAt: new Date().toISOString()
                });
              } catch (error) {
                if (!isStaleVideoIngressError(error)) throw error;
              }
            })
        }
      : undefined;
  }

  useEffect(() => {
    const controller = cameraCaptureRef.current;
    if (!controller) return;

    let cancelled = false;
    const questionId = question?.questionId ?? null;
    if (page !== "training" || !session || !questionId) {
      cameraQuestionRef.current = null;
      cameraSessionRef.current = null;
      controller.stop();
      return;
    }

    // Per-question video stream boundary follows `question.questionId` — updated only after
    // the correct-answer transition animation completes (see questionTransition.ts).

    const correlationId = `camera:${session.sessionId}:${questionId}`;
    const startOptions = {
      sessionId: session.sessionId,
      questionId,
      correlationId,
      width: 160,
      height: 120,
      sampleFps: 1,
      recordingFps: 15,
      mimeType: "image/jpeg" as const,
      quality: 0.6,
      rawVideoPersistence: buildCameraRawVideoPersistence(),
      monitorPreview: {
        enabled: true,
        width: 320,
        height: 240,
        fps: 4,
        quality: 0.6,
        onPreviewFrame: async (input: Parameters<typeof uploadMonitorPreviewFrame>[0]) => {
          void uploadMonitorPreviewFrame(input).catch(() => undefined);
        }
      }
    };

    void (async () => {
      let state = controller.getState();
      if (state.status === "sampling") {
        if (cameraSessionRef.current === session.sessionId) {
          if (cameraQuestionRef.current !== questionId) {
            cameraFailureSentRef.current = null;
            if (!cancelled) {
              await controller.switchQuestion({ questionId, correlationId });
              if (!cancelled) cameraQuestionRef.current = questionId;
            }
          }
          return;
        }
        await controller.stopAndWait();
        if (cancelled) return;
        state = controller.getState();
      }

      if (state.status === "requesting_permission") return;

      cameraQuestionRef.current = questionId;
      cameraSessionRef.current = session.sessionId;
      cameraFailureSentRef.current = null;
      await new Promise<void>((resolve) => {
        window.setTimeout(resolve, CAMERA_FIRST_START_DELAY_MS);
      });
      if (cancelled || controller.getState().status === "sampling") return;
      await controller.start(startOptions);
    })();

    return () => {
      cancelled = true;
    };
  }, [page, question?.questionId, session?.sessionId]);
  function openReportDetail() {
    setReportLayout("landscape");
    setPage("reportDetail");
  }

  useEffect(() => {
    if (visiblePage !== "reportDetail" || !report || !isNarrativePending(report)) {
      setNarrativeLoading(false);
      return;
    }

    let cancelled = false;
    setNarrativeLoading(true);

    const poll = async () => {
      while (!cancelled) {
        const fresh = await refreshMergedReport();
        if (!fresh || !isNarrativePending(fresh)) {
          if (!cancelled) setNarrativeLoading(false);
          return;
        }
        await new Promise<void>((resolve) => {
          window.setTimeout(resolve, 1500);
        });
      }
    };

    void poll();
    return () => {
      cancelled = true;
    };
  }, [visiblePage, report, refreshMergedReport]);

  async function sendCameraUnavailableDescriptor(state: BrowserCameraCaptureState) {
    if (!session || !question) return;
    const key = `${session.sessionId}:${question.questionId}:${state.errorCode ?? state.status}`;
    if (cameraFailureSentRef.current === key) return;
    cameraFailureSentRef.current = key;
    await sendCameraFrameDescriptor({
      schemaVersion: "m5-frame-v1",
      sessionId: session.sessionId,
      streamId: `camera-unavailable:${session.sessionId}`,
      frameId: `camera-unavailable:${session.sessionId}:${question.questionId}`,
      sequence: 0,
      capturedAt: new Date().toISOString(),
      correlationId: `camera:${session.sessionId}:${question.questionId}`,
      questionId: question.questionId,
      width: 1,
      height: 1,
      downsampled: true,
      frameHash: state.errorCode ?? state.status,
      byteLength: 0,
      mimeType: "mock/frame-descriptor",
      rawFramePersisted: false,
      visualFeatures: {
        facePresent: false,
        faceCount: 0,
        headOrientation: "unknown",
        imageQuality: "unavailable",
        provider: "camera-device",
        algorithmVersion: "camera-device-availability-v1",
        confidence: 0
      }
    });
  }

  async function handleVoiceFinal(transcript: string) {
    const childText = transcript.trim();
    if (!childText) return;
    const logIdBase = Date.now();
    const preTrainingHint = "已识别语音，开始训练后可进行实时对话。";
    if (question && isHelpRequestSpeech(childText)) {
      voiceHelpRequestCountRef.current[question.questionId] = (voiceHelpRequestCountRef.current[question.questionId] ?? 0) + 1;
    }
    setVoicePanelOpen(true);

    if (!session || page !== "training") {
      setVoiceLogs((prev) => {
        const next: VoiceLog[] = [...prev.slice(-10), { id: logIdBase, role: "child", text: childText }];
        if (!prev.some((log) => log.role === "system" && log.text === preTrainingHint)) {
          next.push({ id: logIdBase + 1, role: "system", text: preTrainingHint });
        }
        return next.slice(-12);
      });
      return;
    }

    setVoiceLogs((prev) => [...prev.slice(-11), { id: logIdBase, role: "child", text: childText }]);
    setError("");
    if (voiceDialogProvider === "partner") {
      try {
        await persistTranscriptObservations(session.sessionId, childText);
      } catch {
        // Expressive-language observations are best-effort in partner mode.
      }
      return;
    }

    try {
      const result = await sendChatMessage(session.sessionId, childText, getVoiceChatPageContext());
      setVoiceLogs((prev) => [...prev.slice(-11), { id: logIdBase + 1, role: "assistant", text: result.reply }]);
      playAssistantReply(result);
    } catch (voiceErr) {
      setVoiceLogs((prev) => [
        ...prev.slice(-11),
        { id: logIdBase + 1, role: "system", text: "语音已识别，但本次对话发送失败。" }
      ]);
      setError(voiceErr instanceof Error ? voiceErr.message : "语音对话失败");
    }
  }

  function handleMainMicClick() {
    if (!voiceSupported) return;
    unlockBrowserSpeechOutput();
    if (voiceMode === "continuous") {
      handleSwitchVoiceMode("single");
      return;
    }
    if (voiceListening) {
      void stopVoiceCapture();
      return;
    }
    stopChatReplyAudio();
    void startVoiceCapture("single");
  }

  async function handleSwitchVoiceMode(mode: VoiceMode) {
    setVoiceMode(mode);
    await stopVoiceCapture();
    setVoicePanelOpen(false);
    if (mode === "continuous") {
      await startVoiceCapture(mode);
    }
  }

  function handleHomeStartClick(event: React.MouseEvent<HTMLButtonElement>) {
    unlockBrowserSpeechOutput();
    playMaimaiGreeting();
    const rect = event.currentTarget.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const particles: HomeParticle[] = Array.from({ length: 25 }, (_, index) => {
      const angle = Math.random() * Math.PI * 2;
      const velocity = 150 + Math.random() * 200;
      return {
        id: Date.now() + index,
        left: centerX,
        top: centerY,
        size: Math.random() * 15 + 10,
        color: HOME_PARTICLE_COLORS[Math.floor(Math.random() * HOME_PARTICLE_COLORS.length)],
        isStar: Math.random() > 0.5,
        tx: Math.cos(angle) * velocity,
        ty: Math.sin(angle) * velocity + 100,
        duration: 600 + Math.random() * 400,
        rotate: Math.random() * 360
      };
    });
    setHomeParticles(particles);
    setTimeout(() => setHomeParticles([]), 1100);
    setTimeout(() => setPage("select"), 350);
  }

  return (
    <main className="app">
      <div className="app-background" aria-hidden="true" />

      {visiblePage !== "welcome" ? (
        <header className="header">
          <h1>{pageTitle}</h1>
        </header>
      ) : null}

      {error ? <div className="error">{error}</div> : null}

      {visiblePage === "welcome" ? (
        <WelcomePageShell transition={pageTransition}>
          <div className="home-main-action">
            <button className="home-btn-start" onClick={handleHomeStartClick}>
              开始训练
            </button>
          </div>

          <div className="home-particles-container">
            {homeParticles.map((particle) => (
              <span
                key={particle.id}
                className={`home-particle ${particle.isStar ? "home-particle-star" : ""}`}
                style={
                  {
                    left: `${particle.left}px`,
                    top: `${particle.top}px`,
                    width: `${particle.size}px`,
                    height: `${particle.size}px`,
                    background: particle.color,
                    "--tx": `${particle.tx}px`,
                    "--ty": `${particle.ty}px`,
                    "--rot": `${particle.rotate}deg`,
                    "--duration": `${particle.duration}ms`
                  } as React.CSSProperties
                }
              />
            ))}
          </div>
        </WelcomePageShell>
      ) : null}

      {visiblePage === "select" ? (
        <CourseSelectPageShell transition={pageTransition}>
          <h2 className="title-fun">请选择你想挑战的课程</h2>
          <div className="courses-grid">
            {COURSE_OPTIONS.map((course) => (
              <button
                key={course.type}
                className={`course-card-fun ${selectedCourses.includes(course.type) ? "selected" : ""}`}
                onClick={() => course.enabled && handleToggleCourse(course.type)}
                disabled={!course.enabled}
              >
                <div className="badge-star">★</div>
                {course.iconUrl ? (
                  <div className="course-card-icon-wrap-fun">
                    <img className="course-card-icon-fun" src={resolveAsset(course.iconUrl)} alt={`${course.title}图标`} />
                  </div>
                ) : null}
                <strong className="course-title-fun">{course.title}</strong>
                <span className="course-desc-fun">{course.description}</span>
              </button>
            ))}
          </div>
          <button
            className="btn-3d course-start-btn"
            onClick={handleStartTraining}
            disabled={loading || selectedCourses.length === 0}
          >
            {loading ? "准备中..." : "开始所选课程"}
          </button>
        </CourseSelectPageShell>
      ) : null}

      {visiblePage === "training" && question ? (
        <TrainingPageShell transition={pageTransition} courseType={question.courseType} flashBg={flashBg}>
          <div ref={voiceContextRootRef} data-voice-context-root className="voice-context-root">
          <div className="course-route-bar">
            <div className={`course-route-nodes ${queuedCourses.length === 1 ? "single" : ""}`}>
              {queuedCourses.map((courseType, index) => {
                const courseInfo = COURSE_OPTIONS.find((course) => course.type === courseType);
                const nodeState = index < activeCourseIndex ? "done" : index === activeCourseIndex ? "active" : "pending";
                const totalStars = Math.max(0, courseQuestionTotals[courseType] || (index === activeCourseIndex ? question.total : 0));
                const stars = courseStars[courseType] ?? [];
                return (
                  <div key={`${courseType}-${index}`} className={`course-route-node ${nodeState}`}>
                    <div className="course-route-badge">{courseInfo?.type === "matching" ? "🧩" : "🔢"}</div>
                    <div className="course-route-text">
                      <strong>{courseInfo?.title ?? courseType}</strong>
                      <span>{index + 1} / {queuedCourses.length}</span>
                    </div>
                    <div className="course-route-stars" aria-label={`${courseInfo?.title ?? courseType}题目进度`}>
                      {Array.from({ length: totalStars }).map((_, starIndex) => (
                        <span key={`${courseType}-star-${starIndex}`} className={`route-star ${stars[starIndex] ?? "off"}`}>
                          ★
                        </span>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {question.courseType === "matching" ? (
            <>
              <div className="target-stage">
                <p className="speech-bubble">{question.prompt}</p>
                <div className="target-item-wrapper">
                  <img className="target-image" src={resolveAsset(question.payload.targetImageUrl)} alt="目标图片" />
                </div>
              </div>
            </>
          ) : (
            <div className="target-stage">
              <p className="speech-bubble">{question.prompt}</p>
              <div className="target-item-wrapper target-rule-wrapper">
                <p className="rule-text">{question.payload.target}</p>
              </div>
            </div>
          )}
          <div className="options-grid-fun">
            {question.payload.options.map((option) => (
              <button
                key={option.id}
                className={`option-card-fun ${optionStates[option.id] ?? "normal"}`}
                onClick={() => void handleSelectAnswer(option.id)}
                disabled={loading || isAnswerTransitionLocked(optionStates) || optionStates[option.id] === "wrong"}
              >
                {option.imageUrl ? (
                  <img src={resolveAsset(option.imageUrl)} alt={option.label} />
                ) : (
                  <span className="option-label-fun">{option.label}</span>
                )}
              </button>
            ))}
          </div>
          {feedback ? <p className="feedback-fun">{feedback}</p> : null}
          {hint ? <p className="hint-fun">提示：{hint}</p> : null}
          </div>
        </TrainingPageShell>
      ) : null}

      {visiblePage === "report" && report ? (
        <ReportPageShell transition={pageTransition}>
          <ReportBackgroundBubbles />

          <div className="result-panel">
            <div className="result-left">
              <h1 className="result-title">训练完成啦！</h1>
              <div className="huge-stars">
                {[0, 1, 2].map((idx) => (
                  <span
                    key={idx}
                    className={`huge-star ${idx < reportMetrics.starCount ? "active" : ""}`}
                    style={{ animationDelay: `${0.15 + idx * 0.18}s` }}
                  >
                    ★
                  </span>
                ))}
              </div>
              <p className="congrats-text">
                太棒了！
                <br />
                你第一次就答对了 <span>{report.summary.correctAnswers}</span> 道题！
              </p>
            </div>

            <div className="result-right">
              <div className="stats-grid-2x2">
                <div className="stat-card">
                  <div className="stat-icon">⚡</div>
                  <div className="stat-label">平均速度</div>
                  <div className="stat-value">{(report.summary.averageResponseTimeMs / 1000).toFixed(1)} 秒</div>
                </div>
                <div className="stat-card">
                  <div className="stat-icon">📊</div>
                  <div className="stat-label">错误尝试</div>
                  <div className="stat-value red">{report.errorStats.totalWrongAttempts} 次</div>
                </div>
                <div className="stat-card">
                  <div className="stat-icon">🎯</div>
                  <div className="stat-label">正确率</div>
                  <div className="stat-value">{(report.summary.accuracy * 100).toFixed(0)}%</div>
                </div>
                <div className="stat-card">
                  <div className="stat-icon">🧩</div>
                  <div className="stat-label">训练题数</div>
                  <div className="stat-value">{report.summary.totalQuestions} 题</div>
                </div>
              </div>

              <p className="result-chat-highlight">
                {report.chatSummary.highlights.length > 0 ? report.chatSummary.highlights.join("；") : "本次训练未触发对话交流。"}
              </p>

              <div className="action-buttons">
                <button className="btn-3d btn-blue" onClick={openReportDetail}>
                  {isNarrativePending(report) ? "查看训练报告（AI 分析中…）" : "查看训练报告"}
                </button>
                <div className="action-buttons-row">
                  <button className="btn-3d btn-orange" onClick={resetToSelect}>
                    再玩一次！
                  </button>
                  <button className="btn-3d btn-gray" onClick={resetToWelcome}>
                    回首页
                  </button>
                </div>
              </div>
            </div>
          </div>
        </ReportPageShell>
      ) : null}

      {visiblePage === "reportDetail" && report ? (
        <ReportDetailPageShell transition={pageTransition} layout={reportLayout}>
          <div className="report-detail-toolbar">
            <div className="report-detail-toolbar-title">训练观察报告预览模式</div>
            <div className="report-detail-toolbar-actions">
              <button className="report-detail-action" onClick={() => setReportLayout((prev) => (prev === "landscape" ? "portrait" : "landscape"))}>
                {reportLayout === "landscape" ? "切换竖版" : "切换横版"}
              </button>
              <button className="report-detail-action" onClick={() => setPage("report")}>
                返回结果页
              </button>
              <button className="report-detail-action report-detail-action-print" onClick={() => window.print()}>
                打印训练报告
              </button>
              <button className="report-detail-action" onClick={resetToSelect}>
                再玩一次
              </button>
              <button className="report-detail-action" onClick={resetToWelcome}>
                返回首页
              </button>
            </div>
          </div>

          <article className={`report-detail-container ${reportLayout === "landscape" ? "report-detail-container-landscape" : ""}`}>
            <div className="report-detail-watermark">FUN ACADEMY</div>
            <ProfessionalReportV2Content
              report={report}
              childName={childName}
              narrativeLoading={narrativeLoading || isNarrativePending(report)}
            />
          </article>
        </ReportDetailPageShell>
      ) : null}

      {visiblePage !== "welcome" && visiblePage !== "reportDetail" ? (
        <div className={`voice-fab-wrap ${voicePanelOpen ? "open" : ""}`}>
          <button className="voice-toggle-btn" onClick={() => setVoicePanelOpen((prev) => !prev)} title="语音面板">
            {voicePanelOpen ? "−" : "+"}
          </button>

          <button
            className={`voice-main-btn ${voiceListening ? "listening" : ""}`}
            onClick={handleMainMicClick}
            disabled={!voiceSupported}
            title={voiceListening ? "停止录音并发送" : voiceMode === "continuous" ? "切换到单次录音" : "开始录音"}
          >
            🎤
          </button>

          {voicePanelOpen ? (
            <div className="voice-panel">
              <div className="voice-panel-head">
                <span>语音模式</span>
                <span className={`voice-status-dot ${voiceListening || autoVoiceTriggerState.status === "listening" ? "on" : ""}`}>
                  {voiceListening ? "录音中" : formatAutoVoiceStatus(autoVoiceTriggerState.status, autoVoiceTriggerActive)}
                </span>
              </div>

              <div className="voice-mode-switch">
                <button
                  className={`voice-mode-btn ${voiceMode === "continuous" ? "active" : ""}`}
                  onClick={() => handleSwitchVoiceMode("continuous")}
                >
                  持续捕捉
                </button>
                <button
                  className={`voice-mode-btn ${voiceMode === "single" ? "active" : ""}`}
                  onClick={() => handleSwitchVoiceMode("single")}
                >
                  单次录音
                </button>
              </div>

              <p className="voice-tip">
                {autoVoiceTriggerEnabled && voiceMode === "single"
                  ? voiceListening
                    ? "检测到声音后正在录音，安静一小会儿会自动发送。"
                    : "训练页会等待外接麦克风声音，听到说话后自动发送给麦麦。"
                  : voiceMode === "continuous"
                  ? "会持续捕捉环境语音并自动分段识别。"
                  : voiceListening
                    ? "正在录音，再点一次麦克风停止并发送。"
                    : "点击麦克风开始录音，再点一次停止并发送。"}
              </p>

              <div className="voice-speech-controls">
                <label className="voice-speech-toggle">
                  <input
                    type="checkbox"
                    checked={autoVoiceTriggerEnabled}
                    onChange={(event) => setAutoVoiceTriggerEnabled(event.currentTarget.checked)}
                  />
                  <span>声控自动对话</span>
                </label>
                <label className="voice-speech-toggle">
                  <input
                    type="checkbox"
                    checked={autoSpeakEnabled}
                    onChange={(event) => setAutoSpeakEnabled(event.currentTarget.checked)}
                  />
                  <span>自动朗读回复</span>
                </label>
                <button className="voice-speech-stop-btn" type="button" onClick={handleStopSpeaking}>
                  停止朗读
                </button>
              </div>

              <label className="voice-select-field">
                <span>朗读音色</span>
                <select
                  value={selectedSpeechVoiceName}
                  disabled={speechVoiceOptions.length === 0}
                  onChange={(event) => handleSpeechVoiceChange(event.currentTarget.value)}
                >
                  {speechVoiceOptions.length === 0 ? (
                    <option value="">无可用音色</option>
                  ) : (
                    speechVoiceOptions.map((voice) => (
                      <option key={`${voice.name}:${voice.lang}`} value={voice.name}>
                        {voice.label}
                      </option>
                    ))
                  )}
                </select>
              </label>

              <p className={`voice-speech-status ${speechStatus === "error" ? "error" : ""}`}>{formatSpeechStatus()}</p>

              {!voiceSupported ? <p className="voice-warning">当前浏览器不支持录音采集，请更换 Chrome 或 Edge。</p> : null}
              {voiceFallbackReason ? <p className="voice-warning">语音状态：{formatVoiceStatus(voiceFallbackReason)}</p> : null}

              {interimText ? <p className="voice-interim">识别中：{interimText}</p> : null}

              <div className="voice-log-list">
                {voiceLogs.length === 0 ? (
                  <p className="voice-empty">还没有语音记录，试着说一句话吧。</p>
                ) : (
                  voiceLogs.slice(-6).map((log) => (
                    <p key={log.id} className={`voice-log-item ${log.role}`}>
                      <strong>{log.role === "child" ? "你" : log.role === "assistant" ? "助手" : "系统"}：</strong>
                      {log.text}
                    </p>
                  ))
                )}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </main>
  );
}

function App() {
  const screenRole = useMemo(() => getScreenRoleFromPathname(window.location.pathname), []);
  if (screenRole === "robot") {
    return <RobotScreen />;
  }
  if (screenRole === "server") {
    return <ServerDashboard />;
  }
  return <ChildApp />;
}

export default App;
