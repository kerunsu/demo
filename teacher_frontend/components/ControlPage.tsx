import { useState, useEffect, useRef, useCallback } from 'react';
import { Lightbulb, Award, ArrowRight, ArrowLeft, ChevronDown, ChevronRight, Eye, Target, BarChart3, X, HelpCircle } from 'lucide-react';
import { Puzzle, Blocks, Brain, Users } from 'lucide-react';
import { io, Socket } from 'socket.io-client';
import { TeacherRatingDialog } from './TeacherRatingDialog';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

// 分析结果接口
interface MatchResult {
  session_id: string;
  matcher_type: string;
  score: number;
  passed: boolean;
  threshold: number;
  timestamp: number;
  details?: Record<string, any>;
}

function normalizeMatchScorePercent(score: unknown, threshold: unknown): number | null {
  const raw = Number(score);
  if (!Number.isFinite(raw)) return null;
  const rawThreshold = Number(threshold);
  const usesPercentScale = Number.isFinite(rawThreshold)
    ? rawThreshold > 1.0001
    : raw > 1.0001;
  const percent = usesPercentScale ? raw : raw * 100;
  return Math.min(100, Math.max(0, percent));
}

interface AttentionUpdate {
  session_id: string;
  score: number;
  state: 'high' | 'medium' | 'low' | 'unknown';
  trend: 'increasing' | 'stable' | 'decreasing';
  timestamp: number;
  score_scale?: string;
  provider?: string;
  face_present?: boolean;
}

interface SessionSummary {
  session_id: string;
  summary: {
    duration: number;
    total_frames: number;
    total_chunks: number;
    vision_summary: any[];
    audio_summary: any[];
    statistics: {
      total_frames: number;
      total_audio_chunks: number;
      word_count: number;
      average_attention: number;
    };
  };
  timestamp: number;
}

interface ControlPageProps {
  onBack: () => void;
  onFinish: () => void;
  onViewReport?: (trainingSessionId: string) => void;
  selectedCourses: Array<{categoryId: string, courseId: string}>;
  selectedStudent: string | null;
  /** prepare_training 已创建的训练 ID，进控制页时直接复用 */
  initialTrainingSessionId?: string | null;
  /** 开课录制门已通过（服务器已收到视频） */
  readinessPassed?: boolean;
  /** 评估一次作答即定结果；训练答错后继续正向引导。 */
  mode: 'assessment' | 'training';
  /** Read-only ControlPage preview, available only under Vite development. */
  previewMode?: boolean;
  /** In-memory course fixtures used by the read-only preview. */
  previewCourses?: Course[];
}

// 课程类型映射（与CourseSelectionPage保持一致）
const courseTypeMap: Record<string, { name: string; icon: typeof Brain }> = {
  'pairing': { name: '配对', icon: Puzzle },
  'ordering': { name: '排序', icon: Blocks },
};

const DefaultIcon = Brain;
const DEFAULT_ITEM_IMAGE = 'https://images.unsplash.com/photo-1759159482847-78aadfcbeb85?w=300&h=200&fit=crop';
const EMPTY_PREVIEW_COURSES: Course[] = [];

type SocialAuxKey =
  | 'socialGreetingIntro'
  | 'socialGreetingPlay'
  | 'socialFarewellBye'
  | 'socialFarewellReply';

type PlayAux = {
  attention?: boolean;
  reward?: boolean;
  behaviorAnimationOverride?: string;
  question?: boolean;
  praise?: boolean;
  hint?: boolean;
  socialGreetingIntro?: boolean;
  socialGreetingPlay?: boolean;
  socialFarewellBye?: boolean;
  socialFarewellReply?: boolean;
};

type PlaybackPhase = 'idle' | 'pending' | 'busy';
type PlayIntent = 'content' | 'attention' | 'reward' | 'question' | 'praise' | 'hint' | 'social';

interface PendingPlayRequest {
  requestId: string;
  intent: PlayIntent;
  aux: PlayAux;
  isContent: boolean;
  contentKey: string | null;
  courseIndex: number;
  itemIndex: number;
  studentId: string;
  trainingSessionId: string | null;
  requestedAtMs: number;
  payload: Record<string, any>;
  timeoutId: number | null;
  retryCount: number;
  advanceAfterPlayback?: AdvanceSource;
}

interface KnownPlayRequest extends PendingPlayRequest {
  sessionId: string | null;
  questionId: string | null;
  behaviorId: string | null;
}

function createClientRequestId(prefix: string): string {
  const randomId =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${randomId}`;
}

function normalizeId(value: unknown): string | null {
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return null;
}

function getPlayIntent(aux: PlayAux): PlayIntent {
  if (aux.attention) return 'attention';
  if (aux.reward) return 'reward';
  if (aux.question) return 'question';
  if (aux.praise) return 'praise';
  if (aux.hint) return 'hint';
  if (isSocialAux(aux)) return 'social';
  return 'content';
}

function getSocialRole(item: CourseItem | null | undefined): 'greeting' | 'farewell' | null {
  if (!item) return null;
  const role = item.config?.socialRole;
  if (role === 'greeting' || role === 'farewell') return role;
  if (item.name === '打招呼') return 'greeting';
  if (item.name === '再见') return 'farewell';
  return null;
}

function isSocialAux(aux: PlayAux | Record<string, any> | null | undefined): boolean {
  if (!aux) return false;
  return Boolean(
    aux.socialGreetingIntro ||
    aux.socialGreetingPlay ||
    aux.socialFarewellBye ||
    aux.socialFarewellReply
  );
}

/** 打招呼置顶、再见置尾；每个社交角色拆成独立序列条目 */
function normalizeSocialOrder(selectedItems: SelectedCourseItem[]): SelectedCourseItem[] {
  const greetings: SelectedCourseItem[] = [];
  const farewells: SelectedCourseItem[] = [];
  const middle: SelectedCourseItem[] = [];

  for (const sel of selectedItems) {
    if (sel.course.type !== 'social') {
      middle.push(sel);
      continue;
    }
    const greetingItems = sel.items.filter((i) => getSocialRole(i) === 'greeting');
    const farewellItems = sel.items.filter((i) => getSocialRole(i) === 'farewell');
    const otherItems = sel.items.filter(
      (i) => getSocialRole(i) !== 'greeting' && getSocialRole(i) !== 'farewell'
    );

    for (const item of greetingItems) {
      greetings.push({
        courseId: sel.courseId,
        itemIds: [item.id],
        course: sel.course,
        items: [item],
      });
    }
    if (otherItems.length > 0) {
      middle.push({
        courseId: sel.courseId,
        itemIds: otherItems.map((i) => i.id),
        course: sel.course,
        items: otherItems,
      });
    }
    for (const item of farewellItems) {
      farewells.push({
        courseId: sel.courseId,
        itemIds: [item.id],
        course: sel.course,
        items: [item],
      });
    }
  }

  return [...greetings, ...middle, ...farewells];
}

export interface CourseItem {
  id: number;
  name: string;
  type: string;
  file?: string;
  icon?: string;
  hint?: string;
  difficulty?: string;
  config?: any;
  /** ASR 比对文本；空则回退 name */
  speechTarget?: string | null;
}

export interface Course {
  id: number;
  title: string;
  type: string;
  question?: string;
  praise?: string;
  file?: string;
  icon?: string;
  items: CourseItem[];
}

interface CourseCategory {
  id: string;
  name: string;
  icon: typeof Brain;
  courses: Course[];
}

// 选中的课程项结构
interface SelectedCourseItem {
  courseId: number;
  itemIds: number[];
  course: Course;
  items: CourseItem[];
}

type AdvanceSource = 'manual' | 'matching_end' | 'ordering_end' | 'praise_end' | 'social_end';

interface AdvanceSnapshot {
  source: AdvanceSource;
  trainingSessionId: string;
  questionId: string;
  runtimeSessionId: string | null;
  courseIndex: number;
  itemIndex: number;
  courseId: number;
  courseItemId: number | null;
  courseType: string;
  courseName: string;
  itemName: string;
  responseMs: number | null;
  responseSource: 'teacher_advance' | 'game_metrics';
  clientRecordedAt: string;
}

export function ControlPage({
  onBack,
  onFinish,
  onViewReport,
  selectedCourses,
  selectedStudent,
  initialTrainingSessionId = null,
  readinessPassed = false,
  mode,
  previewMode = false,
  previewCourses = EMPTY_PREVIEW_COURSES,
}: ControlPageProps) {
  const isPreviewMode = import.meta.env.DEV && previewMode;
  const [allCourses, setAllCourses] = useState<Course[]>([]);
  const [selectedCourseItems, setSelectedCourseItems] = useState<SelectedCourseItem[]>([]);
  const [currentCourseIndex, setCurrentCourseIndex] = useState(0);
  const [currentItemIndex, setCurrentItemIndex] = useState(0);
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set());
  const [showBackConfirm, setShowBackConfirm] = useState(false);
  const [showFinishConfirm, setShowFinishConfirm] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [socketConnected, setSocketConnected] = useState(false);
  const [teacherLatencyMs, setTeacherLatencyMs] = useState<number | null>(null);
  const [behaviorSyncDeltaMs, setBehaviorSyncDeltaMs] = useState<number | null>(null);
  const [controlRole, setControlRole] = useState<'unknown' | 'controller' | 'observer'>('unknown');
  const [claimingControl, setClaimingControl] = useState(false);
  const [claimingControlNotice, setClaimingControlNotice] = useState<string | null>(null);
  const claimControlTimerRef = useRef<number | null>(null);
  const [forcedStopInfo, setForcedStopInfo] = useState<{
    sessionId?: string | null;
    trainingSessionId?: string | null;
    studentId?: number | null;
    humanDirName?: string | null;
  } | null>(null);
  const socketRef = useRef<Socket | null>(null);
  const latencyProbeTimerRef = useRef<number | null>(null);
  const teacherLatencyRef = useRef<number | null>(null);
  
  // 分析结果状态
  const [matchScore, setMatchScore] = useState<number | null>(null);
  const [matchPassed, setMatchPassed] = useState<boolean>(false);
  const [matchType, setMatchType] = useState<string>('');
  const [attentionScore, setAttentionScore] = useState<number | null>(null);
  const [attentionState, setAttentionState] = useState<string>('unknown');
  const [attentionTrend, setAttentionTrend] = useState<string>('stable');
  const [sessionSummary, setSessionSummary] = useState<SessionSummary | null>(null);
  const [showSummaryModal, setShowSummaryModal] = useState(false);

  // 配对游戏状态
  const [matchingDifficulty, setMatchingDifficulty] = useState<number>(3); // 默认3选1
  const [matchingStatus, setMatchingStatus] = useState<{
    currentDifficulty: number;      // 当前难度
    currentQuestion: number;        // 当前题目索引
    totalQuestions: number;         // 总题目数
    correctCount: number;           // 正确数
    wrongCount: number;             // 错误数
    accuracy: number;               // 正确率百分比
    isCorrect: boolean;             // 本题是否正确
    consecutiveCorrect: number;     // 连续正确数
    isSimplifiedMode: boolean;      // 是否简化模式
  } | null>(null);
  const [matchingGameStarted, setMatchingGameStarted] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [trainingSessionId, setTrainingSessionId] = useState<string | null>(initialTrainingSessionId);
  const [currentQuestionId, setCurrentQuestionId] = useState<string | null>(null);
  const [pendingAdvance, setPendingAdvance] = useState<AdvanceSnapshot | null>(null);
  const [selectedRating, setSelectedRating] = useState<number | null>(null);
  const [ratingSaving, setRatingSaving] = useState(false);
  const [ratingError, setRatingError] = useState<string | null>(null);
  const [finalizing, setFinalizing] = useState(false);
  const [reportModulesLoading, setReportModulesLoading] = useState(true);
  const [reportPublished, setReportPublished] = useState(false);
  const [playbackPhase, setPlaybackPhase] = useState<PlaybackPhase>('idle');
  const [playbackNotice, setPlaybackNotice] = useState<string | null>(null);
  const [hasFailedPlayback, setHasFailedPlayback] = useState(false);
  const [dialogueAwake, setDialogueAwake] = useState(false);
  const [dialogueControlBusy, setDialogueControlBusy] = useState(false);
  const [dialogueControlNotice, setDialogueControlNotice] = useState<string | null>(null);
  const [engagementAnimations, setEngagementAnimations] = useState<Array<{ name: string }>>([]);
  const [rewardAnimation, setRewardAnimation] = useState('');
  const [engagementSettingsOpen, setEngagementSettingsOpen] = useState(false);
  const [awaitingResourceReady, setAwaitingResourceReady] = useState(false);
  const [interactiveNextPending, setInteractiveNextPending] = useState(false);
  const lastGameEndRef = useRef<number>(0);
  const matchingGameStartedRef = useRef(false);
  const sequencingGameStartedRef = useRef(false);
  const [currentResolvedFile, setCurrentResolvedFile] = useState<string | null>(null); // 服务端随机选择的真实图片路径

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/api/robot/animations`, { cache: 'no-store', credentials: 'include' })
      .then((response) => response.json())
      .then((payload) => {
        if (cancelled || !payload?.success) return;
        const playable = (Array.isArray(payload.items) ? payload.items : [])
          .filter((item: any) => item?.validationStatus === 'compatible' || item?.validationStatus === 'degraded')
          .map((item: any) => ({ name: String(item.name) }));
        setEngagementAnimations(playable);
      })
      .catch((error) => console.warn('加载夸奖下屏素材失败:', error));
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!selectedStudent) {
      setRewardAnimation('');
      return;
    }
    try {
      setRewardAnimation(localStorage.getItem(`maimai.reward-animation.${selectedStudent}`) || '');
    } catch (_) {
      setRewardAnimation('');
    }
  }, [selectedStudent]);

  // 音频播放状态
  const [audioStatus, setAudioStatus] = useState<{
    isPlaying: boolean;
    entryId: string | null;
    progress: number;
  }>({
    isPlaying: false,
    entryId: null,
    progress: 0
  });

  // 排序游戏状态
  const [sequencingConfig, setSequencingConfig] = useState({
    autoMode: true,           // 默认开启自动
    category: 'size',         // 大小/长短/高矮/多少
    difficulty: 2,            // 两者（目前禁用三者、四者）
    rule: 'bigger'            // 选大的/选小的 等
  });
  
  // 使用ref保存最新的配置值（解决闭包问题）
  const sequencingConfigRef = useRef(sequencingConfig);
  // 儿童端已经展示的题目。教师选择的 sequencingConfig 只代表下一题，
  // 当前题的再次提问/提示必须使用这个快照，不能提前使用待生效配置。
  const sequencingActiveQuestionRef = useRef<{
    category: string;
    rule: string;
    questionIndex: number | null;
  } | null>(null);
  const matchingDifficultyRef = useRef(matchingDifficulty);
  const handleNextRef = useRef<(source?: AdvanceSource) => void>(() => {});
  const playCurrentItemRef = useRef<(
    aux?: PlayAux,
    options?: {
      retryCount?: number;
      expectedCourseIndex?: number;
      expectedItemIndex?: number;
      requestId?: string;
      advanceAfterPlayback?: AdvanceSource;
    },
  ) => void>(() => {});
  const currentCourseIndexRef = useRef(currentCourseIndex);
  const currentItemIndexRef = useRef(currentItemIndex);
  const selectedCourseItemsRef = useRef(selectedCourseItems);
  const selectedStudentRef = useRef(selectedStudent);
  const lastContentRequestKeyRef = useRef<string | null>(null);
  const contentRequestRef = useRef<{
    key: string;
    requestId: string;
    status: 'pending' | 'accepted';
  } | null>(null);
  const autoQuestionSentForRef = useRef<string | null>(null);
  const pendingPlayRequestsRef = useRef<Map<string, PendingPlayRequest>>(new Map());
  const knownPlayRequestsRef = useRef<Map<string, KnownPlayRequest>>(new Map());
  const handledPlayBroadcastIdsRef = useRef<Set<string>>(new Set());
  const playbackPhaseRef = useRef<PlaybackPhase>('idle');
  const audioPlayingRef = useRef(false);
  const awaitingResourceReadyRef = useRef(false);
  const activePlaybackRequestIdRef = useRef<string | null>(null);
  const activeBehaviorIdRef = useRef<string | null>(null);
  const behaviorUnlockTimerRef = useRef<number | null>(null);
  const deferredAutoQuestionRef = useRef<{
    requestId?: string;
    questionId: string;
    courseIndex: number;
    itemIndex: number;
    retryCount: number;
  } | null>(null);
  const deferredContentRetryRef = useRef<{
    requestId: string;
    courseIndex: number;
    itemIndex: number;
    retryCount: number;
  } | null>(null);
  const deferredManualPlayRef = useRef<{
    aux: PlayAux;
    intent: PlayIntent;
    courseIndex: number;
    itemIndex: number;
    advanceAfterPlayback?: AdvanceSource;
  } | null>(null);
  const failedPlayRetryRef = useRef<{
    requestId: string;
    aux: PlayAux;
    courseIndex: number;
    itemIndex: number;
    retryCount: number;
    advanceAfterPlayback?: AdvanceSource;
  } | null>(null);
  const autoQuestionWaitRef = useRef<{
    contentRequestId: string;
    questionId: string;
    courseIndex: number;
    itemIndex: number;
    fallbackTimerId: number | null;
  } | null>(null);
  const contentResourceWaitRef = useRef<{
    requestId: string;
    courseIndex: number;
    itemIndex: number;
    retryCount: number;
    timeoutId: number | null;
  } | null>(null);
  const readyContentRequestIdsRef = useRef<Set<string>>(new Set());
  const failedTransitionRequestIdsRef = useRef<Set<string>>(new Set());
  const cancelPendingGameStartsRef = useRef<() => void>(() => {});
  const praiseRequestContextRef = useRef<{
    requestId: string;
    courseIndex: number;
    itemIndex: number;
    sessionId: string | null;
    behaviorId: string | null;
    animationExpected: boolean | null;
    fallbackTimerId: number | null;
  } | null>(null);
  /** Dedup keyword_auto_praise before play_resource_ack sets praiseRequestContextRef. */
  const keywordAutoPraiseInFlightRef = useRef<{
    requestId: string | null;
    itemId: string | null;
    atMs: number;
  } | null>(null);
  const pendingPraiseAdvanceRef = useRef<{
    requestId: string;
    courseIndex: number;
    itemIndex: number;
    sessionId: string | null;
  } | null>(null);
  const praiseRatingTimerRef = useRef<number | null>(null);
  const completionRatingContextRef = useRef<{
    requestId: string;
    behaviorId: string | null;
    courseIndex: number;
    itemIndex: number;
    sessionId: string | null;
    source: AdvanceSource;
    fallbackTimerId: number | null;
  } | null>(null);
  const socialAutomationIdsRef = useRef<Set<string>>(new Set());
  /**
   * A social prompt is a course-entry lifecycle action, not a simulated button
   * click.  Keep the committed content request as its idempotency key so React
   * re-renders, resource-ready retries and Socket re-delivery cannot greet or
   * say goodbye twice.
   */
  const socialEntryRequestIdsRef = useRef<Set<string>>(new Set());
  const deferredSocialEntryRef = useRef<{
    contentRequestId: string;
    auxKey: 'socialGreetingIntro' | 'socialFarewellBye';
    courseIndex: number;
    itemIndex: number;
  } | null>(null);
  const delayedTimersRef = useRef<Set<number>>(new Set());
  const finalizePromiseRef = useRef<Promise<string | null> | null>(null);
  const finalizeOperationIdRef = useRef<string | null>(null);
  const trainingSessionIdRef = useRef<string | null>(initialTrainingSessionId);
  const currentSessionIdRef = useRef<string | null>(null);
  const currentQuestionIdRef = useRef<string | null>(null);
  const dialogueControlRequestRef = useRef<string | null>(null);
  const dialogueControlTimerRef = useRef<number | null>(null);
  const interactiveQuestionIdRef = useRef<string | null>(null);
  const interactiveNextPendingRef = useRef<{
    courseType: 'pairing' | 'ordering';
    previousQuestionId: string | null;
    requestId: string;
    timeoutId: number | null;
  } | null>(null);
  const questionStartedAtRef = useRef<number | null>(null);
  const completionAtRef = useRef<number | null>(null);
  const advanceLockRef = useRef(false);

  const scheduleTimeout = useCallback((callback: () => void, delayMs: number): number => {
    const timerId = window.setTimeout(() => {
      delayedTimersRef.current.delete(timerId);
      callback();
    }, Math.max(0, delayMs));
    delayedTimersRef.current.add(timerId);
    return timerId;
  }, []);

  const clearScheduledTimeout = useCallback((timerId: number | null | undefined) => {
    if (timerId == null) return;
    window.clearTimeout(timerId);
    delayedTimersRef.current.delete(timerId);
  }, []);

  const clearAllScheduledTimeouts = useCallback(() => {
    delayedTimersRef.current.forEach((timerId) => window.clearTimeout(timerId));
    delayedTimersRef.current.clear();
    behaviorUnlockTimerRef.current = null;
  }, []);

  const completeInteractiveNext = useCallback((
    courseType: 'pairing' | 'ordering',
    nextQuestionId?: string | null,
  ) => {
    const pending = interactiveNextPendingRef.current;
    if (!pending || pending.courseType !== courseType) return false;
    const normalizedNextQuestionId = normalizeId(nextQuestionId);
    if (
      pending.previousQuestionId &&
      normalizedNextQuestionId &&
      pending.previousQuestionId === normalizedNextQuestionId
    ) {
      return false;
    }
    clearScheduledTimeout(pending.timeoutId);
    interactiveNextPendingRef.current = null;
    setInteractiveNextPending(false);
    setPlaybackNotice(null);
    return true;
  }, [clearScheduledTimeout]);

  const clearContentResourceWait = useCallback((expectedRequestId?: string | null) => {
    const wait = contentResourceWaitRef.current;
    if (
      expectedRequestId &&
      wait &&
      wait.requestId !== expectedRequestId
    ) {
      return false;
    }
    if (wait?.timeoutId != null) {
      clearScheduledTimeout(wait.timeoutId);
    }
    contentResourceWaitRef.current = null;
    awaitingResourceReadyRef.current = false;
    setAwaitingResourceReady(false);
    return true;
  }, [clearScheduledTimeout]);

  const armContentResourceWait = useCallback((
    requestId: string,
    courseIndex: number,
    itemIndex: number,
    retryCount: number,
  ) => {
    clearContentResourceWait();
    awaitingResourceReadyRef.current = true;
    setAwaitingResourceReady(true);

    const timeoutId = scheduleTimeout(() => {
      const wait = contentResourceWaitRef.current;
      if (!wait || wait.requestId !== requestId) return;

      contentResourceWaitRef.current = null;
      awaitingResourceReadyRef.current = false;
      setAwaitingResourceReady(false);
      readyContentRequestIdsRef.current.delete(requestId);

      const autoWait = autoQuestionWaitRef.current;
      if (autoWait?.contentRequestId === requestId) {
        clearScheduledTimeout(autoWait.fallbackTimerId);
        autoQuestionWaitRef.current = null;
      }
      deferredAutoQuestionRef.current = null;

      if (contentRequestRef.current?.requestId === requestId) {
        contentRequestRef.current = null;
      }
      lastContentRequestKeyRef.current = null;

      if (
        currentCourseIndexRef.current === courseIndex &&
        currentItemIndexRef.current === itemIndex
      ) {
        failedPlayRetryRef.current = {
          requestId: createClientRequestId('play-content-retry'),
          aux: {},
          courseIndex,
          itemIndex,
          retryCount,
        };
        setHasFailedPlayback(true);
        setPlaybackNotice('等待儿童端新课点画面超时；已保留上一帧，可重试本课点');
      }
    }, 15000);

    contentResourceWaitRef.current = {
      requestId,
      courseIndex,
      itemIndex,
      retryCount,
      timeoutId,
    };
  }, [clearContentResourceWait, clearScheduledTimeout, scheduleTimeout]);

  const setPlaybackGate = useCallback((
    phase: PlaybackPhase,
    requestId: string | null = null,
    behaviorId: string | null = null,
    notice: string | null = null,
  ) => {
    playbackPhaseRef.current = phase;
    activePlaybackRequestIdRef.current = requestId;
    activeBehaviorIdRef.current = behaviorId;
    setPlaybackPhase(phase);
    setPlaybackNotice(notice);
  }, []);

  const flushDeferredAutoQuestion = useCallback(() => {
    if (
      !socketRef.current?.connected ||
      playbackPhaseRef.current !== 'idle' ||
      audioPlayingRef.current ||
      awaitingResourceReadyRef.current
    ) {
      return;
    }

    // Teacher-issued commands have priority over automatic question playback.
    // Only one latest command is retained so a burst of clicks cannot create a
    // second behavior transaction or silently disappear.
    const deferredManual = deferredManualPlayRef.current;
    if (deferredManual) {
      if (
        currentCourseIndexRef.current !== deferredManual.courseIndex ||
        currentItemIndexRef.current !== deferredManual.itemIndex
      ) {
        deferredManualPlayRef.current = null;
      } else {
        deferredManualPlayRef.current = null;
        playCurrentItemRef.current(deferredManual.aux, {
          expectedCourseIndex: deferredManual.courseIndex,
          expectedItemIndex: deferredManual.itemIndex,
          advanceAfterPlayback: deferredManual.advanceAfterPlayback,
        });
        return;
      }
    }

    const socialEntry = deferredSocialEntryRef.current;
    if (socialEntry) {
      if (
        currentCourseIndexRef.current !== socialEntry.courseIndex ||
        currentItemIndexRef.current !== socialEntry.itemIndex
      ) {
        deferredSocialEntryRef.current = null;
      } else {
        deferredSocialEntryRef.current = null;
        playCurrentItemRef.current(
          { [socialEntry.auxKey]: true } as PlayAux,
          {
            expectedCourseIndex: socialEntry.courseIndex,
            expectedItemIndex: socialEntry.itemIndex,
          },
        );
        return;
      }
    }

    const contentRetry = deferredContentRetryRef.current;
    if (contentRetry) {
      if (
        currentCourseIndexRef.current !== contentRetry.courseIndex ||
        currentItemIndexRef.current !== contentRetry.itemIndex
      ) {
        deferredContentRetryRef.current = null;
      } else {
        deferredContentRetryRef.current = null;
        playCurrentItemRef.current(
          {},
          {
            requestId: contentRetry.requestId,
            retryCount: contentRetry.retryCount,
            expectedCourseIndex: contentRetry.courseIndex,
            expectedItemIndex: contentRetry.itemIndex,
          },
        );
        return;
      }
    }

    const deferred = deferredAutoQuestionRef.current;
    if (deferred) {
      if (
        currentQuestionIdRef.current !== deferred.questionId ||
        currentCourseIndexRef.current !== deferred.courseIndex ||
        currentItemIndexRef.current !== deferred.itemIndex
      ) {
        deferredAutoQuestionRef.current = null;
      } else {
        deferredAutoQuestionRef.current = null;
        playCurrentItemRef.current(
          { question: true },
          {
            requestId: deferred.requestId,
            retryCount: deferred.retryCount,
            expectedCourseIndex: deferred.courseIndex,
            expectedItemIndex: deferred.itemIndex,
          },
        );
        return;
      }
    }

  }, []);

  const clearPraiseRequestContext = useCallback((requestId?: string | null) => {
    const context = praiseRequestContextRef.current;
    if (!context || (requestId && context.requestId !== requestId)) return;
    clearScheduledTimeout(context.fallbackTimerId);
    context.fallbackTimerId = null;
    praiseRequestContextRef.current = null;
  }, [clearScheduledTimeout]);

  const clearCompletionRatingContext = useCallback((requestId?: string | null) => {
    const context = completionRatingContextRef.current;
    if (!context || (requestId && context.requestId !== requestId)) return;
    clearScheduledTimeout(context.fallbackTimerId);
    completionRatingContextRef.current = null;
  }, [clearScheduledTimeout]);

  const queueCompletionRating = useCallback((
    context: NonNullable<typeof completionRatingContextRef.current>,
    notice?: string,
    delayMs = 0,
  ) => {
    if (
      completionRatingContextRef.current?.requestId !== context.requestId ||
      currentCourseIndexRef.current !== context.courseIndex ||
      currentItemIndexRef.current !== context.itemIndex ||
      (context.sessionId && currentSessionIdRef.current !== context.sessionId)
    ) {
      clearCompletionRatingContext(context.requestId);
      return;
    }
    clearScheduledTimeout(context.fallbackTimerId);
    context.fallbackTimerId = null;
    if (notice) setPlaybackNotice(notice);
    scheduleTimeout(() => {
      if (completionRatingContextRef.current?.requestId !== context.requestId) return;
      completionRatingContextRef.current = null;
      completionAtRef.current = Date.now();
      handleNextRef.current(context.source);
    }, Math.max(0, delayMs));
  }, [clearCompletionRatingContext, clearScheduledTimeout, scheduleTimeout]);

  const armCompletionRatingFallback = useCallback((
    context: NonNullable<typeof completionRatingContextRef.current>,
    delayMs: number,
  ) => {
    clearScheduledTimeout(context.fallbackTimerId);
    context.fallbackTimerId = scheduleTimeout(() => {
      if (completionRatingContextRef.current?.requestId !== context.requestId) return;
      queueCompletionRating(
        context,
        '课程回应已完成，但结束回执超时，现进入评分',
      );
    }, Math.max(3000, delayMs));
  }, [clearScheduledTimeout, queueCompletionRating, scheduleTimeout]);

  const queuePraiseRating = useCallback((
    context: NonNullable<typeof praiseRequestContextRef.current>,
    notice?: string,
    delayMs = 0,
  ) => {
    if (
      currentCourseIndexRef.current !== context.courseIndex ||
      currentItemIndexRef.current !== context.itemIndex ||
      (context.sessionId && currentSessionIdRef.current !== context.sessionId)
    ) {
      clearPraiseRequestContext(context.requestId);
      return;
    }
    clearScheduledTimeout(context.fallbackTimerId);
    context.fallbackTimerId = null;
    if (praiseRequestContextRef.current?.requestId === context.requestId) {
      praiseRequestContextRef.current = null;
    }
    if (pendingPraiseAdvanceRef.current?.requestId !== context.requestId) {
      pendingPraiseAdvanceRef.current = {
        requestId: context.requestId,
        courseIndex: context.courseIndex,
        itemIndex: context.itemIndex,
        sessionId: context.sessionId,
      };
    }
    if (notice) setPlaybackNotice(notice);
    clearScheduledTimeout(praiseRatingTimerRef.current);
    praiseRatingTimerRef.current = scheduleTimeout(() => {
      praiseRatingTimerRef.current = null;
      const scheduled = pendingPraiseAdvanceRef.current;
      if (!scheduled || scheduled.requestId !== context.requestId) return;
      pendingPraiseAdvanceRef.current = null;
      if (
        currentCourseIndexRef.current === scheduled.courseIndex &&
        currentItemIndexRef.current === scheduled.itemIndex &&
        (!scheduled.sessionId || currentSessionIdRef.current === scheduled.sessionId)
      ) {
        handleNextRef.current('praise_end');
      }
    }, Math.max(0, delayMs));
  }, [
    clearPraiseRequestContext,
    clearScheduledTimeout,
    scheduleTimeout,
  ]);

  const armPraiseRatingFallback = useCallback((
    context: NonNullable<typeof praiseRequestContextRef.current>,
    delayMs: number,
  ) => {
    clearScheduledTimeout(context.fallbackTimerId);
    context.fallbackTimerId = scheduleTimeout(() => {
      if (praiseRequestContextRef.current?.requestId !== context.requestId) return;
      queuePraiseRating(context, '表扬已完成，动画结束回执超时，现可评分');
    }, Math.max(1000, delayMs));
  }, [clearScheduledTimeout, queuePraiseRating, scheduleTimeout]);

  const releasePlaybackGate = useCallback((
    expectedRequestId?: string | null,
    expectedBehaviorId?: string | null,
  ) => {
    if (
      expectedRequestId &&
      activePlaybackRequestIdRef.current &&
      expectedRequestId !== activePlaybackRequestIdRef.current
    ) {
      return;
    }
    if (
      expectedBehaviorId &&
      activeBehaviorIdRef.current &&
      expectedBehaviorId !== activeBehaviorIdRef.current
    ) {
      return;
    }
    clearScheduledTimeout(behaviorUnlockTimerRef.current);
    behaviorUnlockTimerRef.current = null;
    setPlaybackGate('idle');
    scheduleTimeout(flushDeferredAutoQuestion, 0);
  }, [clearScheduledTimeout, flushDeferredAutoQuestion, scheduleTimeout, setPlaybackGate]);

  const holdPlaybackGate = useCallback((
    requestId: string | null,
    behaviorId: string | null,
    remainingMs: number,
    notice: string | null = null,
  ) => {
    clearScheduledTimeout(behaviorUnlockTimerRef.current);
    setPlaybackGate('busy', requestId, behaviorId, notice);
    behaviorUnlockTimerRef.current = scheduleTimeout(() => {
      releasePlaybackGate(requestId, behaviorId);
    }, Math.max(250, remainingMs + 100));
  }, [clearScheduledTimeout, releasePlaybackGate, scheduleTimeout, setPlaybackGate]);

  const armPlayRequestTimeout = useCallback((
    pending: PendingPlayRequest,
    timeoutMs = 12000,
  ) => {
    clearScheduledTimeout(pending.timeoutId);
    pending.timeoutId = scheduleTimeout(() => {
      const currentPending = pendingPlayRequestsRef.current.get(pending.requestId);
      if (currentPending !== pending) return;
      pendingPlayRequestsRef.current.delete(pending.requestId);
      if (contentRequestRef.current?.requestId === pending.requestId) {
        contentRequestRef.current = null;
        lastContentRequestKeyRef.current = null;
      }
      if (pending.isContent) {
        clearContentResourceWait(pending.requestId);
      }
      clearCompletionRatingContext(pending.requestId);
      failedPlayRetryRef.current = {
        // Reuse the same idempotency key: the server may have executed the
        // request while only its ACK was lost.
        requestId: pending.requestId,
        aux: pending.aux,
        courseIndex: pending.courseIndex,
        itemIndex: pending.itemIndex,
        retryCount: pending.retryCount,
        advanceAfterPlayback: pending.advanceAfterPlayback,
      };
      setHasFailedPlayback(true);
      setPlaybackGate(
        'idle',
        null,
        null,
        pending.isContent
          ? '服务端确认超时；儿童端继续保留上一帧，请重试本课点'
          : '服务端确认播放超时，请重试本次交互',
      );
    }, timeoutMs);
  }, [
    clearContentResourceWait,
    clearScheduledTimeout,
    scheduleTimeout,
    setPlaybackGate,
  ]);

  const cancelAutoQuestionWait = useCallback(() => {
    const wait = autoQuestionWaitRef.current;
    if (wait?.fallbackTimerId != null) {
      clearScheduledTimeout(wait.fallbackTimerId);
    }
    if (wait) {
      readyContentRequestIdsRef.current.delete(wait.contentRequestId);
    }
    autoQuestionWaitRef.current = null;
    deferredAutoQuestionRef.current = null;
  }, [clearScheduledTimeout]);

  const queueAutoQuestion = useCallback((
    contentRequestId: string,
    questionId: string,
    courseIndex: number,
    itemIndex: number,
  ) => {
    const wait = autoQuestionWaitRef.current;
    if (!wait || wait.contentRequestId !== contentRequestId) return;
    clearScheduledTimeout(wait.fallbackTimerId);
    autoQuestionWaitRef.current = null;
    readyContentRequestIdsRef.current.delete(contentRequestId);

    if (
      currentQuestionIdRef.current !== questionId ||
      currentCourseIndexRef.current !== courseIndex ||
      currentItemIndexRef.current !== itemIndex
    ) {
      return;
    }

    autoQuestionSentForRef.current = questionId;
    deferredAutoQuestionRef.current = {
      questionId,
      courseIndex,
      itemIndex,
      retryCount: 0,
    };
    scheduleTimeout(flushDeferredAutoQuestion, 0);
  }, [clearScheduledTimeout, flushDeferredAutoQuestion, scheduleTimeout]);

  const armAutoQuestionWait = useCallback((
    contentRequestId: string,
    questionId: string,
    courseIndex: number,
    itemIndex: number,
  ) => {
    cancelAutoQuestionWait();
    const fallbackTimerId = scheduleTimeout(() => {
      queueAutoQuestion(contentRequestId, questionId, courseIndex, itemIndex);
    }, 3000);
    autoQuestionWaitRef.current = {
      contentRequestId,
      questionId,
      courseIndex,
      itemIndex,
      fallbackTimerId,
    };
    if (readyContentRequestIdsRef.current.has(contentRequestId)) {
      scheduleTimeout(
        () => queueAutoQuestion(contentRequestId, questionId, courseIndex, itemIndex),
        0,
      );
    }
  }, [cancelAutoQuestionWait, queueAutoQuestion, scheduleTimeout]);

  const markResourceReady = useCallback((requestId: string) => {
    readyContentRequestIdsRef.current.add(requestId);
    while (readyContentRequestIdsRef.current.size > 100) {
      const oldest = readyContentRequestIdsRef.current.values().next().value;
      if (!oldest) break;
      readyContentRequestIdsRef.current.delete(oldest);
    }
    clearContentResourceWait(requestId);
    const wait = autoQuestionWaitRef.current;
    if (!wait || wait.contentRequestId !== requestId) {
      scheduleTimeout(flushDeferredAutoQuestion, 0);
      return;
    }
    queueAutoQuestion(
      wait.contentRequestId,
      wait.questionId,
      wait.courseIndex,
      wait.itemIndex,
    );
  }, [
    clearContentResourceWait,
    flushDeferredAutoQuestion,
    queueAutoQuestion,
    scheduleTimeout,
  ]);
  
  // 同步ref
  useEffect(() => {
    sequencingConfigRef.current = sequencingConfig;
  }, [sequencingConfig]);
  
  useEffect(() => {
    matchingDifficultyRef.current = matchingDifficulty;
  }, [matchingDifficulty]);

  useEffect(() => {
    currentCourseIndexRef.current = currentCourseIndex;
    currentItemIndexRef.current = currentItemIndex;
    selectedCourseItemsRef.current = selectedCourseItems;
    cancelAutoQuestionWait();
    clearContentResourceWait();
    clearPraiseRequestContext();
    cancelPendingGameStartsRef.current();
    sequencingActiveQuestionRef.current = null;
    contentRequestRef.current = null;
    deferredContentRetryRef.current = null;
    clearScheduledTimeout(praiseRatingTimerRef.current);
    praiseRatingTimerRef.current = null;
    praiseRequestContextRef.current = null;
    pendingPraiseAdvanceRef.current = null;
    failedPlayRetryRef.current = null;
    deferredSocialEntryRef.current = null;
    setHasFailedPlayback(false);
  }, [
    cancelAutoQuestionWait,
    clearContentResourceWait,
    clearPraiseRequestContext,
    currentCourseIndex,
    currentItemIndex,
    selectedCourseItems,
  ]);

  useEffect(() => {
    selectedStudentRef.current = selectedStudent;
  }, [selectedStudent]);

  useEffect(() => {
    trainingSessionIdRef.current = trainingSessionId;
    currentSessionIdRef.current = currentSessionId;
    currentQuestionIdRef.current = currentQuestionId;
  }, [trainingSessionId, currentSessionId, currentQuestionId]);

  useEffect(() => {
    audioPlayingRef.current = audioStatus.isPlaying;
  }, [audioStatus.isPlaying]);

  const [sequencingStats, setSequencingStats] = useState<{
    size: { correct: number; wrong: number };
    length: { correct: number; wrong: number };
    height: { correct: number; wrong: number };
    count: { correct: number; wrong: number };
  }>({
    size: { correct: 0, wrong: 0 },
    length: { correct: 0, wrong: 0 },
    height: { correct: 0, wrong: 0 },
    count: { correct: 0, wrong: 0 }
  });

  const [sequencingGameStarted, setSequencingGameStarted] = useState(false);
  const [sequencingStatus, setSequencingStatus] = useState<{
    currentQuestion: number;
    totalQuestions: number;
    category: string;
    rule: string;
  } | null>(null);

  // 从后端获取课程数据
  useEffect(() => {
    if (isPreviewMode) {
      const selectedItems = previewCourses
        .filter((course) => course.items.length > 0)
        .map((course) => ({
          courseId: course.id,
          itemIds: course.items.map((item) => item.id),
          course,
          items: course.items,
        }));

      setAllCourses(previewCourses);
      setSelectedCourseItems(normalizeSocialOrder(selectedItems));
      setExpandedCategories(new Set(previewCourses.map((course) => course.type)));
      setCurrentCourseIndex(0);
      setCurrentItemIndex(0);
      setSocketConnected(true);
      setTeacherLatencyMs(24);
      setBehaviorSyncDeltaMs(12);
      setControlRole('controller');
      setMatchScore(92);
      setMatchPassed(true);
      setAttentionScore(86);
      setAttentionState('high');
      setMatchingStatus({
        currentDifficulty: 3,
        currentQuestion: 3,
        totalQuestions: 8,
        correctCount: 2,
        wrongCount: 1,
        accuracy: 67,
        isCorrect: true,
        consecutiveCorrect: 1,
        isSimplifiedMode: false,
      });
      setSequencingStats({
        size: { correct: 3, wrong: 0 },
        length: { correct: 2, wrong: 1 },
        height: { correct: 1, wrong: 1 },
        count: { correct: 2, wrong: 0 },
      });
      setSequencingStatus({
        currentQuestion: 3,
        totalQuestions: 8,
        category: 'size',
        rule: 'bigger',
      });
      setError(selectedItems.length > 0 ? null : 'Preview course data is empty');
      setLoading(false);
      return;
    }

    let disposed = false;
    const coursesAbortController = new AbortController();
    const fetchCourses = async () => {
      try {
        setLoading(true);
        const response = await fetch('/courses', {
          signal: coursesAbortController.signal,
        });
        
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
          const text = await response.text();
          console.error('收到非 JSON 响应:', text.substring(0, 200));
          throw new Error(`服务器返回了非 JSON 响应。请检查后端服务是否正常运行。状态码: ${response.status}`);
        }
        
        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.error || `获取课程数据失败 (${response.status})`);
        }
        
        const data: Course[] = await response.json();
        if (!Array.isArray(data)) {
          throw new Error('课程数据格式无效');
        }
        if (disposed) return;
        setAllCourses(data);

        // 从 localStorage 获取选中的课程项
        const selectedItemsDataStr = localStorage.getItem('selectedCourseItems');
        if (!selectedItemsDataStr) {
          throw new Error('未找到选中的课程项数据');
        }

        const parsedSelectedItems: unknown = JSON.parse(selectedItemsDataStr);
        if (
          !parsedSelectedItems ||
          typeof parsedSelectedItems !== 'object' ||
          Array.isArray(parsedSelectedItems)
        ) {
          throw new Error('已选课程数据格式无效，请返回重新选课');
        }
        const selectedItemsData = parsedSelectedItems as Record<string, unknown>;
        
        // 构建选中的课程项列表
        const selectedItems: SelectedCourseItem[] = [];
        Object.entries(selectedItemsData).forEach(([courseIdStr, rawItemIds]) => {
          const courseId = parseInt(courseIdStr, 10);
          const itemIds = Array.isArray(rawItemIds)
            ? rawItemIds
                .map((itemId) => Number(itemId))
                .filter((itemId) => Number.isInteger(itemId))
            : [];
          const course = data.find(c => c.id === courseId);
          if (course && itemIds.length > 0) {
            const items = course.items.filter(item => itemIds.includes(item.id));
            if (items.length > 0) {
              selectedItems.push({
                courseId,
                itemIds,
                course,
                items
              });
            }
          }
        });

        if (selectedItems.length === 0) {
          throw new Error('未找到有效的选中课程项');
        }

        // 社交：打招呼置顶、再见置尾
        setSelectedCourseItems(normalizeSocialOrder(selectedItems));
        
        // 默认展开第一个课程所在的类别
        if (selectedItems.length > 0) {
          const firstCourse = selectedItems[0].course;
          const categoryId = firstCourse.type;
          setExpandedCategories(new Set([categoryId]));
        }
      } catch (err) {
        if (coursesAbortController.signal.aborted || disposed) return;
        setError(err instanceof Error ? err.message : '未知错误');
        console.error('获取课程数据失败:', err);
      } finally {
        if (!disposed) setLoading(false);
      }
    };

    fetchCourses();

    // 初始化 Socket.IO 连接
    // 在开发环境中，如果前端运行在不同的端口，需要指定完整的 URL
    // 生产环境中，如果前后端同源，可以直接使用 io()
    
    // 判断是否为开发环境（Vite 开发服务器通常运行在 5173 或其他端口）
    const isDevelopment = import.meta.env.DEV;
    const isViteDevServer = window.location.port && window.location.port !== '8080';
    
    // 如果是在 Vite 开发服务器中运行，使用代理（相对路径）
    // 否则使用当前 origin（生产环境或直接访问后端）
    let socketUrl: string;
    if (isDevelopment && isViteDevServer) {
      // Vite 开发环境：使用相对路径，通过代理连接
      socketUrl = window.location.origin;
      console.log('🔧 开发环境：使用 Vite 代理连接到 Socket.IO');
    } else {
      // 生产环境或直接访问：优先使用环境变量，其次使用当前页面同源地址
      socketUrl = import.meta.env.VITE_SOCKET_URL || window.location.origin;
      console.log('🔧 生产环境：直接连接到后端 Socket.IO');
    }
    
    console.log('正在连接到 Socket.IO 服务器:', socketUrl);
    console.log('当前页面 URL:', window.location.href);
    console.log('当前端口:', window.location.port);

    const eventMatchesCurrentStudent = (data: any): boolean => {
      const eventStudentId = normalizeId(data?.studentId ?? data?.student_id);
      const currentStudentId = normalizeId(selectedStudentRef.current);
      return !eventStudentId || !currentStudentId || eventStudentId === currentStudentId;
    };

    const eventMatchesCurrentTraining = (data: any): boolean => {
      const eventTrainingId = normalizeId(
        data?.trainingSessionId ?? data?.training_session_id,
      );
      const activeTrainingId = normalizeId(trainingSessionIdRef.current);
      return !eventTrainingId || !activeTrainingId || eventTrainingId === activeTrainingId;
    };

    const eventMatchesCurrentSession = (data: any): boolean => {
      const eventSessionId = normalizeId(data?.sessionId ?? data?.session_id);
      const activeSessionId = normalizeId(currentSessionIdRef.current);
      return Boolean(eventSessionId && activeSessionId && eventSessionId === activeSessionId);
    };

    const pendingGameStarts = new Map<string, {
      socket: Socket;
      sessionId: string;
      courseType: 'pairing' | 'ordering';
      courseIndex: number;
      itemIndex: number;
      fallbackTimerId: number | null;
    }>();
    cancelPendingGameStartsRef.current = () => {
      pendingGameStarts.forEach((pendingGame) => {
        clearScheduledTimeout(pendingGame.fallbackTimerId);
      });
      pendingGameStarts.clear();
    };

    const startPendingGame = (requestId: string) => {
      const pendingGame = pendingGameStarts.get(requestId);
      if (!pendingGame) return;
      clearScheduledTimeout(pendingGame.fallbackTimerId);
      pendingGameStarts.delete(requestId);
      readyContentRequestIdsRef.current.delete(requestId);
      const {
        socket,
        sessionId,
        courseType,
        courseIndex,
        itemIndex,
      } = pendingGame;
      if (
        socketRef.current !== socket ||
        !socket.connected ||
        currentSessionIdRef.current !== sessionId ||
        currentCourseIndexRef.current !== courseIndex ||
        currentItemIndexRef.current !== itemIndex
      ) {
        return;
      }

      if (courseType === 'pairing') {
        socket.emit('matching_set_difficulty', {
          sessionId,
          difficulty: matchingDifficultyRef.current,
        });
        socket.emit('matching_start', { sessionId });
        setMatchingStatus({
          currentDifficulty: matchingDifficultyRef.current,
          currentQuestion: 0,
          totalQuestions: 15,
          correctCount: 0,
          wrongCount: 0,
          accuracy: 0,
          isCorrect: false,
          consecutiveCorrect: 0,
          isSimplifiedMode: false,
        });
        setMatchingGameStarted(true);
        matchingGameStartedRef.current = true;
        return;
      }

      const config = sequencingConfigRef.current;
      socket.emit('sequencing_set_config', {
        sessionId,
        autoMode: config.autoMode,
        category: config.category,
        difficulty: config.difficulty,
        rule: config.rule,
      });
      socket.emit('sequencing_start', { sessionId });
      setSequencingStatus({
        currentQuestion: 0,
        totalQuestions: 16,
        category: config.category,
        rule: config.rule,
      });
      setSequencingStats({
        size: { correct: 0, wrong: 0 },
        length: { correct: 0, wrong: 0 },
        height: { correct: 0, wrong: 0 },
        count: { correct: 0, wrong: 0 },
      });
      setSequencingGameStarted(true);
      sequencingGameStartedRef.current = true;
    };
    
    let fallbackStarted = false;

    // 创建 Socket 连接函数
    const createSocket = (url: string, isRetry = false) => {
      const socket = io(url, {
        transports: ['polling', 'websocket'],
        tryAllTransports: true,
        reconnection: true,
        reconnectionDelay: 1000,
        reconnectionAttempts: Infinity,
        path: '/socket.io/',
        timeout: 20000,
        withCredentials: true,
      });
      socketRef.current = socket;

      // Persist every teacher-originated control command on the server clock.
      // Raw media is never sent by the teacher UI; the server still sanitizes
      // payloads and credentials before writing the audit timeline.
      (socket as any).onAnyOutgoing?.((eventName: string, ...args: any[]) => {
        if (eventName === 'client_presence') return;
        const first = args[0] && typeof args[0] === 'object' ? args[0] : {};
        fetch(`${API_BASE}/api/v2/timeline/events`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          keepalive: true,
          body: JSON.stringify({
            event: `teacher_socket_emit.${eventName}`,
            actor: 'teacher',
            source: 'teacher_ui',
            category: 'teacher_operation',
            phase: 'requested',
            status: 'sent',
            clientTimestamp: Date.now(),
            trainingSessionId: first.trainingSessionId || trainingSessionIdRef.current,
            sessionId: first.sessionId || currentSessionIdRef.current,
            questionId: first.questionId || currentQuestionIdRef.current,
            requestId: first.requestId,
            behaviorId: first.behaviorId,
            details: { socketEvent: eventName, payload: first },
          }),
        }).catch(() => {});
      });
      
      socket.on('connect', () => {
        console.log(`✅ Socket.IO 连接成功! Socket ID: ${socket.id}`);
        if (isRetry) {
          console.log('✅ 备用连接方式成功！');
        }
        setSocketConnected(true);
        socket.emit('teacher_enter_control', {
          status: 'enter',
          studentId: selectedStudentRef.current
            ? parseInt(selectedStudentRef.current, 10)
            : undefined,
          sessionId: currentSessionIdRef.current || undefined,
          trainingSessionId: trainingSessionIdRef.current || undefined,
        });
        if (currentSessionIdRef.current) {
          socket.emit('join_session', {
            sessionId: currentSessionIdRef.current,
            role: 'teacher',
          });
        }

        // A reconnect may lose the original emit or only its ACK. Re-send the
        // same idempotency key; the server will either execute once or replay
        // the cached ACK. Content requests are also re-forwarded to the child
        // so its dedupe path can repeat resource_ready without replaying media.
        const replayedRequestIds = new Set<string>();
        pendingPlayRequestsRef.current.forEach((pending) => {
          const stillCurrent =
            pending.courseIndex === currentCourseIndexRef.current &&
            pending.itemIndex === currentItemIndexRef.current &&
            pending.studentId === normalizeId(selectedStudentRef.current);
          if (!stillCurrent) {
            clearScheduledTimeout(pending.timeoutId);
            pendingPlayRequestsRef.current.delete(pending.requestId);
            return;
          }
          armPlayRequestTimeout(pending);
          socket.emit('play_resource', pending.payload);
          replayedRequestIds.add(pending.requestId);
        });

        const resourceWait = contentResourceWaitRef.current;
        if (resourceWait && !replayedRequestIds.has(resourceWait.requestId)) {
          const known = knownPlayRequestsRef.current.get(resourceWait.requestId);
          if (
            known?.isContent &&
            known.courseIndex === currentCourseIndexRef.current &&
            known.itemIndex === currentItemIndexRef.current
          ) {
            socket.emit('play_resource', known.payload);
          }
        }

        socket.emit('client_presence', { role: 'teacher', ts: Date.now() });
        const probe = () => {
          if (!socket.connected) return;
          const clientAtMs = Date.now();
          socket.emit('teacher_latency_probe', { probeId: String(clientAtMs), clientAtMs });
        };
        probe();
        if (latencyProbeTimerRef.current) window.clearInterval(latencyProbeTimerRef.current);
        latencyProbeTimerRef.current = window.setInterval(probe, 2000);
        scheduleTimeout(flushDeferredAutoQuestion, 0);
        if (!(socket as any).__presenceTimer) {
          (socket as any).__presenceTimer = window.setInterval(() => {
            if (socket.connected) {
              socket.emit('client_presence', { role: 'teacher', ts: Date.now() });
            }
          }, 10000);
        }
      });

      socket.on('teacher_control_state', (data: any) => {
        const isController = data?.controlRole === 'controller';
        setControlRole(isController ? 'controller' : 'observer');
        if (isController) {
          if (claimControlTimerRef.current) {
            clearTimeout(claimControlTimerRef.current);
            claimControlTimerRef.current = null;
          }
          setClaimingControl(false);
          setClaimingControlNotice(null);
        }
      });

      // 控制台强制关闭了本场录制：弹窗提示，确认后回到角色/课程选择重新开始
      socket.on('recording_forced_stop', (data: any) => {
        setForcedStopInfo({
          sessionId: data?.sessionId || null,
          trainingSessionId: data?.trainingSessionId || null,
          studentId: data?.studentId ?? null,
          humanDirName: data?.humanDirName || null,
        });
      });
      socket.on('teacher_dialogue_control_ack', (data: any) => {
        const activeRequestId = dialogueControlRequestRef.current;
        if (data?.requestId && activeRequestId && data.requestId !== activeRequestId) return;
        if (dialogueControlTimerRef.current) {
          window.clearTimeout(dialogueControlTimerRef.current);
          dialogueControlTimerRef.current = null;
        }
        dialogueControlRequestRef.current = null;
        setDialogueControlBusy(false);
        if (!data?.success) {
          const friendlyError: Record<string, string> = {
            child_not_connected: '儿童端尚未连接，请先打开当前儿童端页面',
            session_id_missing: '当前没有有效课程，请先进入课程',
            session_not_found: '当前课程已结束，请重新进入课程',
            active_course_missing: '当前没有有效课程，请先进入课程',
            session_mismatch: '课程状态刚刚发生变化，请再点击一次',
          };
          setDialogueControlNotice(
            friendlyError[String(data?.error || '')] || '操作未完成，请确认儿童端在线后重试',
          );
          return;
        }
        if (data.action === 'wake') {
          setDialogueAwake(data.awake === true);
          setDialogueControlNotice('智能体已静默唤醒，正在确认儿童端聆听状态…');
        } else if (data.action === 'sleep') {
          setDialogueAwake(false);
          setDialogueControlNotice('智能体回复已停止；儿童端仍在持续聆听');
        }
      });
      socket.on('teacher_dialogue_control_state', (data: any) => {
        const sessionId = normalizeId(data?.sessionId);
        if (!data?.success || (sessionId && sessionId !== currentSessionIdRef.current)) return;
        setDialogueAwake(data.awake === true);
      });
      socket.on('teacher_dialogue_runtime_state', (data: any) => {
        const sessionId = normalizeId(data?.sessionId);
        if (!data?.success || (sessionId && sessionId !== currentSessionIdRef.current)) return;
        const awake = data.awake === true;
        setDialogueAwake(awake);
        if (!awake) {
          setDialogueControlNotice(
            data.reason === 'context_switch'
              ? '题目已切换，智能体已自动停止；需要时可再次唤醒'
              : '智能体已停止，儿童端仍在聆听',
          );
        } else if (data.listening === true) {
          setDialogueControlNotice('智能体已唤醒，儿童端正在聆听');
        } else if (data.microphoneBlocked === true) {
          setDialogueControlNotice('智能体已唤醒；请在儿童端允许麦克风，或点击“开始自动聆听”');
        } else {
          setDialogueControlNotice('智能体已唤醒，儿童端正在恢复聆听…');
        }
      });

      socket.on('joined_session', (data: any) => {
        if (data?.role !== 'teacher') return;
        if (data?.status === 'ok' && data?.controlRole === 'controller') {
          setControlRole('controller');
        } else if (data?.controlRole === 'observer' || data?.error) {
          setControlRole('observer');
        }
      });

      socket.on('disconnect', (reason) => {
        console.log('❌ Socket.IO 连接断开，原因:', reason);
        // A terminal audio_status_update can be lost while offline. Keep the
        // socket/behavior gates authoritative and discard the stale UI flag;
        // a still-busy server will reject/re-gate the next idempotent request.
        audioPlayingRef.current = false;
        setAudioStatus({
          isPlaying: false,
          entryId: null,
          progress: 0,
        });
        setSocketConnected(false);
        setTeacherLatencyMs(null);
        setControlRole('unknown');
        if (dialogueControlTimerRef.current) {
          window.clearTimeout(dialogueControlTimerRef.current);
          dialogueControlTimerRef.current = null;
        }
        dialogueControlRequestRef.current = null;
        setDialogueControlBusy(false);
        setDialogueControlNotice('连接暂时中断，恢复后可重新操作');
        if (claimControlTimerRef.current) {
          clearTimeout(claimControlTimerRef.current);
          claimControlTimerRef.current = null;
        }
        setClaimingControl(false);
      });

      socket.on('teacher_latency_probe_ack', (data: any) => {
        const sent = Number(data?.clientAtMs || 0);
        if (sent > 0) {
          const measured = Math.max(0, Date.now() - sent);
          teacherLatencyRef.current = measured;
          setTeacherLatencyMs(measured);
        }
      });

      socket.on('connect_error', (error) => {
        console.error('❌ Socket.IO 连接错误:', error);
        console.error('错误详情:', error.message);
        console.error('尝试连接的 URL:', url);
        
        // 如果使用代理连接失败，且是开发环境，尝试直接连接后端
        if (
          !fallbackStarted &&
          !isRetry &&
          isDevelopment &&
          isViteDevServer &&
          url === window.location.origin
        ) {
          console.log('🔄 代理连接失败，尝试直接连接到后端...');
          const directUrl = import.meta.env.VITE_SOCKET_URL;
          if (directUrl) {
            fallbackStarted = true;
            const presenceTimer = (socket as any).__presenceTimer;
            if (presenceTimer) window.clearInterval(presenceTimer);
            socket.disconnect();
            socket.removeAllListeners();
            const fallbackSocket = createSocket(directUrl, true);
            socketRef.current = fallbackSocket;
          } else {
            setSocketConnected(false);
          }
        } else {
          setSocketConnected(false);
        }
      });

      socket.io.on('reconnect', (attemptNumber) => {
        console.log('🔄 Socket.IO 重连成功，尝试次数:', attemptNumber);
        setSocketConnected(true);
      });

      socket.io.on('reconnect_attempt', (attemptNumber) => {
        console.log('🔄 正在尝试重连 Socket.IO，第', attemptNumber, '次');
      });

      socket.io.on('reconnect_failed', () => {
        console.error('❌ Socket.IO 重连失败');
        setSocketConnected(false);
      });
      
      // 监听分析结果事件
      socket.on('match_result', (data: MatchResult) => {
        if (!eventMatchesCurrentSession(data)) return;
        console.log('📊 收到匹配结果:', data);
        const normalizedScore = normalizeMatchScorePercent(data.score, data.threshold);
        if (normalizedScore == null) return;
        setMatchScore(normalizedScore);
        setMatchPassed(data.passed);
        setMatchType(data.matcher_type);
      });
      
      socket.on('attention_update', (data: AttentionUpdate) => {
        if (!eventMatchesCurrentSession(data)) return;
        console.log('👁️ 收到注意力更新:', data);
        // 统一按 0–100 存储展示；旧服务端 Mock 可能仍发 0–1
        const raw = Number(data.score);
        const scale = data.score_scale;
        const normalized =
          scale === '0-100' || raw > 1.0001 ? raw : raw * 100;

        // 无脸：立即清空有效分，状态标为 missing（禁止显示「分散」）
        if (data.face_present === false) {
          setAttentionScore(null);
          setAttentionState('missing');
          setAttentionTrend(data.trend || 'stable');
          return;
        }

        if (!Number.isFinite(normalized)) return;
        setAttentionScore(normalized);
        setAttentionState(data.state);
        setAttentionTrend(data.trend || 'stable');
      });
      
      socket.on('session_summary', (data: SessionSummary) => {
        if (!eventMatchesCurrentSession(data)) return;
        console.log('📋 收到会话总结:', data);
        setSessionSummary(data);
        setShowSummaryModal(true);
      });

      socket.on('play_resource_ack', (data: any) => {
        const requestId = normalizeId(data?.requestId);
        if (!requestId) return;
        const pending = pendingPlayRequestsRef.current.get(requestId);
        if (!pending) {
          console.warn('忽略未知或已过期的 play_resource_ack:', requestId);
          return;
        }
        clearScheduledTimeout(pending.timeoutId);
        pendingPlayRequestsRef.current.delete(requestId);

        const activeStudentId = normalizeId(selectedStudentRef.current);
        const ackStudentId = normalizeId(data?.studentId ?? data?.student_id);
        const activeTrainingId = normalizeId(trainingSessionIdRef.current);
        const ackTrainingId = normalizeId(
          data?.trainingSessionId ?? data?.training_session_id,
        );
        const contextIsCurrent =
          pending.courseIndex === currentCourseIndexRef.current &&
          pending.itemIndex === currentItemIndexRef.current &&
          (!activeStudentId || pending.studentId === activeStudentId) &&
          (!ackStudentId || ackStudentId === pending.studentId) &&
          (!activeTrainingId || !ackTrainingId || activeTrainingId === ackTrainingId);

        if (!contextIsCurrent) {
          if (contentRequestRef.current?.requestId === requestId) {
            contentRequestRef.current = null;
          }
          clearContentResourceWait(requestId);
          clearPraiseRequestContext(requestId);
          clearCompletionRatingContext(requestId);
          releasePlaybackGate(requestId);
          return;
        }

        const accepted = data?.accepted === true && data?.busy !== true;
        const remainingMs = Math.max(0, Number(data?.remainingMs) || 0);
        const behaviorId = normalizeId(
          data?.behaviorId ?? data?.interactionId ?? data?.activeBehaviorId,
        );

        if (!accepted) {
          clearPraiseRequestContext(requestId);
          clearCompletionRatingContext(requestId);
          if (contentRequestRef.current?.requestId === requestId) {
            contentRequestRef.current = null;
          }
          if (pending.isContent) {
            clearContentResourceWait(requestId);
          }
          if (pending.isContent) {
            lastContentRequestKeyRef.current = null;
          }
          const message =
            data?.message ||
            data?.error ||
            (data?.busy ? '上一条语音或儿童屏动画仍在播放，请稍候' : '播放请求未被服务端接受');

          if (data?.busy === true) {
            holdPlaybackGate(requestId, behaviorId, remainingMs || 750, message);
            if (pending.isContent && pending.retryCount < 2) {
              deferredContentRetryRef.current = {
                requestId,
                courseIndex: pending.courseIndex,
                itemIndex: pending.itemIndex,
                retryCount: pending.retryCount + 1,
              };
            } else if (
              pending.intent === 'question' &&
              pending.retryCount < 2 &&
              currentQuestionIdRef.current
            ) {
              deferredAutoQuestionRef.current = {
                requestId,
                questionId: currentQuestionIdRef.current,
                courseIndex: pending.courseIndex,
                itemIndex: pending.itemIndex,
                retryCount: pending.retryCount + 1,
              };
            } else if (!pending.isContent) {
              deferredManualPlayRef.current = {
                aux: { ...pending.aux },
                intent: pending.intent,
                courseIndex: pending.courseIndex,
                itemIndex: pending.itemIndex,
                advanceAfterPlayback: pending.advanceAfterPlayback,
              };
              setHasFailedPlayback(false);
              setPlaybackNotice('当前课程输出尚未完成，本次操作已排队');
            } else {
              failedPlayRetryRef.current = {
                requestId,
                aux: pending.aux,
                courseIndex: pending.courseIndex,
                itemIndex: pending.itemIndex,
                retryCount: pending.retryCount,
                advanceAfterPlayback: pending.advanceAfterPlayback,
              };
              setHasFailedPlayback(true);
            }
          } else {
            failedPlayRetryRef.current = {
              requestId,
              aux: pending.aux,
              courseIndex: pending.courseIndex,
              itemIndex: pending.itemIndex,
              retryCount: pending.retryCount,
              advanceAfterPlayback: pending.advanceAfterPlayback,
            };
            setHasFailedPlayback(true);
            setPlaybackGate('idle', null, null, message);
          }
          return;
        }

        const knownRequest: KnownPlayRequest = {
          ...pending,
          sessionId: normalizeId(data?.sessionId),
          questionId: normalizeId(data?.questionId),
          behaviorId,
        };
        knownPlayRequestsRef.current.set(requestId, knownRequest);
        while (knownPlayRequestsRef.current.size > 100) {
          const oldest = knownPlayRequestsRef.current.keys().next().value;
          if (!oldest) break;
          knownPlayRequestsRef.current.delete(oldest);
        }
        const transitionFailed = failedTransitionRequestIdsRef.current.has(requestId);

        if (ackTrainingId) {
          setTrainingSessionId(ackTrainingId);
          trainingSessionIdRef.current = ackTrainingId;
          console.log('📥 训练会话ID:', ackTrainingId);
        }
        const ackSessionId = normalizeId(data?.sessionId);
        if (ackSessionId) {
          const previousSessionId = currentSessionIdRef.current;
          if (previousSessionId && previousSessionId !== ackSessionId) {
            socket.emit('leave_session', {
              sessionId: previousSessionId,
              role: 'teacher',
            });
          }
          setCurrentSessionId(ackSessionId);
          currentSessionIdRef.current = ackSessionId;
          if (previousSessionId !== ackSessionId) {
            socket.emit('join_session', { sessionId: ackSessionId, role: 'teacher' });
          }
        }

        if (!transitionFailed) {
          failedPlayRetryRef.current = null;
          setHasFailedPlayback(false);
        }
        if (
          !transitionFailed &&
          pending.isContent &&
          contentRequestRef.current?.requestId === requestId
        ) {
          contentRequestRef.current.status = 'accepted';
        }
        if (pending.intent === 'praise') {
          if (data?.teacherRatingRequired === false) {
            // 配对/排序的教师手动表扬播放完整行为包后回到当前题目，
            // 不进入普通课程的评分/推进流程。
            clearPraiseRequestContext(requestId);
          } else {
            const praiseContext = praiseRequestContextRef.current;
            if (praiseContext?.requestId === requestId) {
              praiseContext.sessionId = ackSessionId || praiseContext.sessionId;
              praiseContext.behaviorId = behaviorId;
              praiseContext.animationExpected = data?.animationExpected === true;
              const elapsedMs = Date.now() - pending.requestedAtMs;
              queuePraiseRating(
                praiseContext,
                undefined,
                Math.max(0, 800 - elapsedMs),
              );
            }
          }
        }
        const completionContext = completionRatingContextRef.current;
        if (completionContext?.requestId === requestId) {
          completionContext.sessionId = ackSessionId || completionContext.sessionId;
          completionContext.behaviorId = behaviorId;
          armCompletionRatingFallback(
            completionContext,
            Math.max(5000, remainingMs + 5000),
          );
        }

        if (remainingMs > 0) {
          holdPlaybackGate(requestId, behaviorId, remainingMs);
        } else {
          releasePlaybackGate(requestId);
        }

        const ackQuestionId = normalizeId(data?.questionId);
        if (ackQuestionId && pending.isContent && !transitionFailed) {
          setCurrentQuestionId(ackQuestionId);
          currentQuestionIdRef.current = ackQuestionId;
          questionStartedAtRef.current = Date.now();
          completionAtRef.current = null;

          const courseType =
            selectedCourseItemsRef.current[pending.courseIndex]?.course?.type;
          const skipAutoQuestion = new Set([
            'social',
            'pairing',
            'ordering',
          ]);
          if (
            !skipAutoQuestion.has(courseType || '') &&
            autoQuestionSentForRef.current !== ackQuestionId
          ) {
            armAutoQuestionWait(
              requestId,
              ackQuestionId,
              pending.courseIndex,
              pending.itemIndex,
            );
          }
        }
      });
      
      // 监听音频播放状态更新
      socket.on('audio_status_update', (data: {
        session_id: string;
        status: string;
        entry_id: string;
        progress: number;
      }) => {
        if (!eventMatchesCurrentSession(data)) return;
        console.log('🎵 音频状态更新:', data);
        const isPlaying = data.status === 'playing';
        audioPlayingRef.current = isPlaying;
        setAudioStatus({
          isPlaying,
          entryId: data.entry_id,
          progress: data.progress
        });
        if (!isPlaying) {
          scheduleTimeout(flushDeferredAutoQuestion, 0);
        }
      });

      socket.on('resource_ready', (data: any) => {
        const requestId = normalizeId(data?.requestId);
        if (!requestId) return;
        const request =
          pendingPlayRequestsRef.current.get(requestId) ||
          knownPlayRequestsRef.current.get(requestId);
        if (
          !request ||
          !request.isContent ||
          !eventMatchesCurrentStudent(data) ||
          !eventMatchesCurrentTraining(data) ||
          !eventMatchesCurrentSession(data) ||
          request.courseIndex !== currentCourseIndexRef.current ||
          request.itemIndex !== currentItemIndexRef.current
        ) {
          return;
        }
        const selected = selectedCourseItemsRef.current[request.courseIndex];
        const item = selected?.items?.[request.itemIndex];
        const socialRole = selected?.course?.type === 'social'
          ? getSocialRole(item)
          : null;
        if (socialRole && !socialEntryRequestIdsRef.current.has(requestId)) {
          socialEntryRequestIdsRef.current.add(requestId);
          while (socialEntryRequestIdsRef.current.size > 100) {
            const oldest = socialEntryRequestIdsRef.current.values().next().value;
            if (!oldest) break;
            socialEntryRequestIdsRef.current.delete(oldest);
          }
          deferredSocialEntryRef.current = {
            contentRequestId: requestId,
            auxKey: socialRole === 'greeting'
              ? 'socialGreetingIntro'
              : 'socialFarewellBye',
            courseIndex: request.courseIndex,
            itemIndex: request.itemIndex,
          };
          setPlaybackNotice(
            socialRole === 'greeting'
              ? '已进入课程，正在自动打招呼'
              : '已进入结束环节，正在自动说再见',
          );
        }
        markResourceReady(requestId);
        startPendingGame(requestId);
      });

      socket.on('resource_transition_failed', (data: any) => {
        const requestId = normalizeId(data?.requestId);
        if (!requestId || !eventMatchesCurrentSession(data)) return;
        const request =
          pendingPlayRequestsRef.current.get(requestId) ||
          knownPlayRequestsRef.current.get(requestId);
        if (
          !request ||
          !request.isContent ||
          request.courseIndex !== currentCourseIndexRef.current ||
          request.itemIndex !== currentItemIndexRef.current
        ) {
          return;
        }

        failedTransitionRequestIdsRef.current.add(requestId);
        while (failedTransitionRequestIdsRef.current.size > 100) {
          const oldest = failedTransitionRequestIdsRef.current.values().next().value;
          if (!oldest) break;
          failedTransitionRequestIdsRef.current.delete(oldest);
        }
        if (contentRequestRef.current?.requestId === requestId) {
          contentRequestRef.current = null;
        }
        clearContentResourceWait(requestId);
        lastContentRequestKeyRef.current = null;
        const pendingGame = pendingGameStarts.get(requestId);
        if (pendingGame) {
          clearScheduledTimeout(pendingGame.fallbackTimerId);
          pendingGameStarts.delete(requestId);
        }
        cancelAutoQuestionWait();
        failedPlayRetryRef.current = {
          requestId: createClientRequestId('play-content-retry'),
          aux: {},
          courseIndex: request.courseIndex,
          itemIndex: request.itemIndex,
          retryCount: request.retryCount,
        };
        setHasFailedPlayback(true);
        setPlaybackNotice(
          `新课点加载失败，儿童端已保留上一画面：${data?.reason || '资源不可用'}`,
        );
      });

      socket.on('behavior_completed', (data: any) => {
        const componentTimes = Object.values(data?.components || {})
          .map((component: any) => Number(
            component?.actualStartedAtServerMs ||
            component?.actualAtClientMs ||
            component?.startedAtClientMs ||
            0,
          ))
          .filter((value) => value > 0);
        if (componentTimes.length > 1) {
          setBehaviorSyncDeltaMs(Math.max(...componentTimes) - Math.min(...componentTimes));
        }
        const requestId = normalizeId(data?.requestId);
        const behaviorId = normalizeId(data?.behaviorId ?? data?.interactionId);
        const matchesRequest =
          Boolean(requestId) && requestId === activePlaybackRequestIdRef.current;
        const matchesBehavior =
          Boolean(behaviorId) && behaviorId === activeBehaviorIdRef.current;
        const praiseContext = praiseRequestContextRef.current;
        const matchesPraise = Boolean(
          praiseContext &&
          ((requestId && requestId === praiseContext.requestId) ||
            (behaviorId && behaviorId === praiseContext.behaviorId))
        );
        const completionContext = completionRatingContextRef.current;
        const matchesCompletion = Boolean(
          completionContext &&
          ((requestId && requestId === completionContext.requestId) ||
            (behaviorId && behaviorId === completionContext.behaviorId))
        );
        if (!matchesRequest && !matchesBehavior && !matchesPraise && !matchesCompletion) return;
        const eventSessionId = normalizeId(data?.sessionId ?? data?.session_id);
        if (
          eventSessionId &&
          currentSessionIdRef.current &&
          eventSessionId !== currentSessionIdRef.current
        ) {
          return;
        }
        const terminalStatus = String(
          data?.terminalStatus || data?.status || 'completed',
        ).toLowerCase();
        const failed = ['failed', 'cancelled', 'error'].includes(terminalStatus);
        const degraded = data?.degraded === true || terminalStatus === 'degraded';
        const componentLabels: Record<string, string> = {
          audio: '语音',
          childAnimation: '儿童端动画',
        };
        const componentStatuses: Array<[string, { status?: unknown }]> =
          data?.components && typeof data.components === 'object'
          ? Object.entries(data.components)
            .filter(([name]) => name === 'audio' || name === 'childAnimation')
            .map(([name, component]) => [
              name,
              component && typeof component === 'object'
                ? component as { status?: unknown }
                : {},
            ])
          : [
              ['childAnimation', { status: data?.animationStatus }],
            ];
        const abnormalComponents = componentStatuses
          .filter(([, component]) =>
            ['failed', 'timeout', 'incomplete', 'unverified', 'stopped', 'error', 'dropped']
              .includes(String(component?.status || '').toLowerCase()),
          )
          .map(([name, component]) =>
            `${componentLabels[name] || name}=${component?.status}`,
          );
        if (matchesPraise && praiseContext) {
          const reason = data?.message || data?.error || abnormalComponents.join('、');
          queuePraiseRating(
            praiseContext,
            failed || degraded
              ? `表扬已完成，但部分语音或儿童屏画面未完整播放${reason ? `（${reason}）` : ''}，现可评分`
              : undefined,
          );
        }
        if (matchesCompletion && completionContext) {
          const reason = data?.message || data?.error || abnormalComponents.join('、');
          queueCompletionRating(
            completionContext,
            failed || degraded
              ? `课程回应已结束，但部分语音或儿童屏画面未完整播放${reason ? `（${reason}）` : ''}，现进入评分`
              : undefined,
          );
        }
        if (matchesBehavior) {
          releasePlaybackGate(null, behaviorId);
        } else {
          releasePlaybackGate(requestId, null);
        }
        if (failed) {
          setPlaybackNotice(
            `课程输出失败：${data?.message || data?.error || abnormalComponents.join('、') || terminalStatus}`,
          );
        } else if (degraded) {
          setPlaybackNotice(
            `课程输出已完成，但部分状态未完整同步${abnormalComponents.length ? `（${abnormalComponents.join('、')}）` : ''}`,
          );
        }
      });
      
      socket.on('analysis_result', (data: any) => {
        console.log('🔬 收到分析结果:', data);
        // 可以根据需要处理其他分析结果
      });
      
      socket.on('trigger_action', (data: any) => {
        console.log('🎬 收到课程反馈触发:', data);
        // 教师端可以显示通知
      });
      
      // 监听 play_resource 回应以获取 sessionId
      socket.on('play_resource', (data: any) => {
        const requestId = normalizeId(data?.requestId);
        if (!requestId) return;
        const request =
          pendingPlayRequestsRef.current.get(requestId) ||
          knownPlayRequestsRef.current.get(requestId);
        if (
          !request ||
          !eventMatchesCurrentStudent(data) ||
          !eventMatchesCurrentTraining(data) ||
          request.courseIndex !== currentCourseIndexRef.current ||
          request.itemIndex !== currentItemIndexRef.current
        ) {
          return;
        }
        if (handledPlayBroadcastIdsRef.current.has(requestId)) return;
        handledPlayBroadcastIdsRef.current.add(requestId);
        while (handledPlayBroadcastIdsRef.current.size > 100) {
          const oldest = handledPlayBroadcastIdsRef.current.values().next().value;
          if (!oldest) break;
          handledPlayBroadcastIdsRef.current.delete(oldest);
        }

        const sessionId = normalizeId(data.sessionId);
        const courseType = data.courseType;
        const aux = data.aux;
        const resolvedFile = data.resolvedFile; // 服务端随机选择的真实图片路径
        
        // 判断是否是 aux 操作（表扬、提示、社交语音等）
        const isAuxOperation = aux && (
          aux.question || aux.praise || aux.hint || aux.attention || aux.reward || isSocialAux(aux)
        );
        
        if (sessionId) {
          console.log('📥 收到 play_resource 回应, sessionId:', sessionId, 'courseType:', courseType, 'isAux:', isAuxOperation, 'resolvedFile:', resolvedFile);
          const previousSessionId = currentSessionIdRef.current;
          if (previousSessionId && previousSessionId !== sessionId) {
            socket.emit('leave_session', {
              sessionId: previousSessionId,
              role: 'teacher',
            });
          }
          setCurrentSessionId(sessionId);
          currentSessionIdRef.current = sessionId;
          const nextTrainingSessionId = normalizeId(data.trainingSessionId);
          if (nextTrainingSessionId) {
            setTrainingSessionId(nextTrainingSessionId);
            trainingSessionIdRef.current = nextTrainingSessionId;
          }
          const nextQuestionId = normalizeId(data.questionId);
          if (nextQuestionId && request.isContent) {
            setCurrentQuestionId(nextQuestionId);
            currentQuestionIdRef.current = nextQuestionId;
            questionStartedAtRef.current = Date.now();
            completionAtRef.current = null;
            interactiveQuestionIdRef.current = null;
            const pendingNext = interactiveNextPendingRef.current;
            if (pendingNext) {
              clearScheduledTimeout(pendingNext.timeoutId);
              interactiveNextPendingRef.current = null;
              setInteractiveNextPending(false);
            }
          }
          
          // 保存服务端返回的真实图片路径（用于显示缩略图）
          if (resolvedFile && request.isContent) {
            setCurrentResolvedFile(resolvedFile);
            console.log('💾 保存真实图片路径:', resolvedFile);
          }
          
          // 加入 session room 以接收配对游戏状态更新
          if (previousSessionId !== sessionId) {
            socket.emit('join_session', { sessionId: sessionId, role: 'teacher' });
          }
          console.log('📍 教师端加入会话房间:', sessionId);
          
          if (
            request.isContent &&
            (courseType === 'pairing' || courseType === 'ordering')
          ) {
            const previous = pendingGameStarts.get(requestId);
            if (previous) {
              clearScheduledTimeout(previous.fallbackTimerId);
            }
            const pendingGame = {
              socket,
              sessionId,
              courseType,
              courseIndex: request.courseIndex,
              itemIndex: request.itemIndex,
              fallbackTimerId: null as number | null,
            };
            pendingGameStarts.set(requestId, pendingGame);
            if (readyContentRequestIdsRef.current.has(requestId)) {
              scheduleTimeout(() => startPendingGame(requestId), 0);
            }
          }
        }
      });
      
      // 配对游戏事件监听
      socket.on('matching_status_update', (data: any) => {
        if (!eventMatchesCurrentSession(data)) return;
        console.log('🎮 配对游戏状态更新:', data);
        
        // 从儿童端数据直接计算
        const questionIndex = data.questionIndex || 0;
        const totalQuestions = 15; // 固定15题
        const accuracy = data.accuracy || 0; // 百分比
        
        // 根据当前题号和正确率计算正确数和错误数
        const correctCount = questionIndex > 0 ? Math.round((accuracy / 100) * questionIndex) : 0;
        const wrongCount = questionIndex - correctCount;
        
        setMatchingStatus({
          currentDifficulty: data.difficulty,
          currentQuestion: questionIndex,
          totalQuestions: totalQuestions,
          correctCount: correctCount,
          wrongCount: wrongCount,
          accuracy: accuracy,
          isCorrect: data.selectedCorrect ?? data.isCorrect ?? false,
          consecutiveCorrect: data.consecutiveCorrect || 0,
          isSimplifiedMode: data.isSimplifiedMode || false
        });
      });

      socket.on('matching_question_ready', (data: any) => {
        if (!eventMatchesCurrentSession(data)) return;
        const readyQuestionId = normalizeId(
          data?.questionId ?? data?.pageContext?.questionId,
        );
        if (readyQuestionId) interactiveQuestionIdRef.current = readyQuestionId;
        completeInteractiveNext('pairing', readyQuestionId);
      });

      socket.on('interactive_course_completion_praise_started', (data: any) => {
        if (!eventMatchesCurrentSession(data)) return;
        const current = selectedCourseItemsRef.current[currentCourseIndexRef.current];
        const currentType = current?.course?.type;
        const eventType = String(data?.courseType || '').toLowerCase();
        const source: AdvanceSource | null =
          currentType === 'pairing' && ['pairing', 'matching'].includes(eventType)
            ? 'matching_end'
            : currentType === 'ordering' && ['ordering', 'sequencing'].includes(eventType)
              ? 'ordering_end'
              : null;
        const requestId = normalizeId(data?.requestId);
        if (!source || !requestId || advanceLockRef.current) return;
        if (completionRatingContextRef.current?.requestId === requestId) return;
        clearCompletionRatingContext();
        const completionContext: NonNullable<typeof completionRatingContextRef.current> = {
          requestId,
          behaviorId: normalizeId(data?.behaviorId),
          courseIndex: currentCourseIndexRef.current,
          itemIndex: currentItemIndexRef.current,
          sessionId: normalizeId(data?.sessionId) || currentSessionIdRef.current,
          source,
          fallbackTimerId: null,
        };
        completionRatingContextRef.current = completionContext;
        armCompletionRatingFallback(
          completionContext,
          Math.max(8000, Number(data?.remainingMs || 0) + 5000),
        );
        setPlaybackNotice('课程题组已完成，完整表扬结束后将自动进入评分');
      });

      socket.on('social_course_response_matched', (data: any) => {
        if (!eventMatchesCurrentSession(data) || advanceLockRef.current) return;
        const automationId = normalizeId(data?.requestId);
        if (!automationId || socialAutomationIdsRef.current.has(automationId)) return;
        const courseIndex = currentCourseIndexRef.current;
        const itemIndex = currentItemIndexRef.current;
        const selected = selectedCourseItemsRef.current[courseIndex];
        const item = selected?.items?.[itemIndex];
        const role = getSocialRole(item);
        const eventRole = String(data?.role || '').toLowerCase();
        const eventItemId = normalizeId(data?.itemId);
        if (
          selected?.course?.type !== 'social' ||
          role !== eventRole ||
          (eventItemId && item?.id != null && eventItemId !== String(item.id))
        ) {
          return;
        }
        const auxKey = data?.auxKey;
        if (
          (role === 'greeting' && auxKey !== 'socialGreetingPlay') ||
          (role === 'farewell' && auxKey !== 'socialFarewellReply')
        ) {
          return;
        }
        socialAutomationIdsRef.current.add(automationId);
        while (socialAutomationIdsRef.current.size > 100) {
          const oldest = socialAutomationIdsRef.current.values().next().value;
          if (!oldest) break;
          socialAutomationIdsRef.current.delete(oldest);
        }
        completionAtRef.current = Date.now();
        setPlaybackNotice(
          role === 'greeting'
            ? '已识别儿童问好，正在自动执行“一起玩耍”'
            : '已识别儿童告别，正在自动执行“回应”',
        );
        playCurrentItemRef.current(
          { [auxKey]: true } as PlayAux,
          {
            expectedCourseIndex: courseIndex,
            expectedItemIndex: itemIndex,
            advanceAfterPlayback: 'social_end',
          },
        );
      });
      
      socket.on('matching_game_end', (data: any) => {
        if (!eventMatchesCurrentSession(data)) return;
        console.log('🏁 配对游戏结束:', data);
        setMatchingGameStarted(false);
        matchingGameStartedRef.current = false;
        lastGameEndRef.current = Date.now();
        // 更新最终状态
        if (data.correct !== undefined && data.total !== undefined) {
          setMatchingStatus(prev => prev ? {
            ...prev,
            correctCount: data.correct,
            wrongCount: data.total - data.correct,
            accuracy: data.accuracy
          } : null);
        }
        setPlaybackNotice('配对题组已完成；完整表扬结束后将自动进入评分');
      });

      // 排序游戏事件监听
      socket.on('sequencing_status_update', (data: any) => {
        if (!eventMatchesCurrentSession(data)) return;
        console.log('📊 排序游戏状态更新:', data);

        if (data.category && data.rule) {
          sequencingActiveQuestionRef.current = {
            category: String(data.category),
            rule: String(data.rule),
            questionIndex: Number.isFinite(Number(data.questionIndex))
              ? Number(data.questionIndex)
              : null,
          };
        }
        
        // 兼容旧字段名 categoryStats 和新字段名 stats
        const statsData = data.stats || data.categoryStats;
        console.log('📊 statsData:', statsData);
        
        // 更新当前状态
        if (data.questionIndex !== undefined) {
          setSequencingStatus({
            currentQuestion: data.questionIndex,
            totalQuestions: data.totalQuestions || 16,
            category: data.category || 'unknown',
            rule: data.rule || 'unknown'
          });
        }
        
        // 更新统计数据
        if (statsData) {
          console.log('📊 准备更新stats...');
          const newStats = {
            size: statsData.size || { correct: 0, wrong: 0 },
            length: statsData.length || { correct: 0, wrong: 0 },
            height: statsData.height || { correct: 0, wrong: 0 },
            count: statsData.count || { correct: 0, wrong: 0 }
          };
          console.log('📊 newStats:', newStats);
          setSequencingStats(newStats);
          console.log('📊 setSequencingStats已调用');
        } else {
          console.warn('📊 警告: statsData 为空或未定义!');
        }
        
        // 同步配置（自动模式下）
        if (sequencingConfigRef.current.autoMode && data.category && data.rule) {
          setSequencingConfig(prev => ({
            ...prev,
            category: data.category,
            rule: data.rule
          }));
        }
      });

      // 以儿童端实际完成渲染的新题为事实源。教师面板中的类别/规则可能
      // 已经是下一题的待生效配置，不能用它覆盖当前题的语音上下文。
      socket.on('sequencing_question_ready', (data: any) => {
        if (!eventMatchesCurrentSession(data)) return;
        const pageContext = data?.pageContext && typeof data.pageContext === 'object'
          ? data.pageContext
          : {};
        const readyQuestionId = normalizeId(
          data?.questionId ?? pageContext.questionId,
        );
        if (readyQuestionId) interactiveQuestionIdRef.current = readyQuestionId;
        completeInteractiveNext('ordering', readyQuestionId);
        const category = String(data?.category || pageContext.category || '').trim();
        const rule = String(data?.rule || pageContext.rule || '').trim();
        if (!category || !rule) return;

        const parsedQuestionIndex = Number(
          data?.questionIndex ?? pageContext.questionIndex,
        );
        const parsedTotalQuestions = Number(pageContext.totalQuestions);
        const questionIndex = Number.isFinite(parsedQuestionIndex)
          ? parsedQuestionIndex
          : null;
        sequencingActiveQuestionRef.current = {
          category,
          rule,
          questionIndex,
        };
        setSequencingStatus((previous) => ({
          currentQuestion: questionIndex ?? previous?.currentQuestion ?? 0,
          totalQuestions: Number.isFinite(parsedTotalQuestions)
            ? parsedTotalQuestions
            : previous?.totalQuestions ?? 16,
          category,
          rule,
        }));
      });
      
      socket.on('sequencing_game_end', (data: any) => {
        if (!eventMatchesCurrentSession(data)) return;
        console.log('🏁 排序游戏结束:', data);
        setSequencingGameStarted(false);
        sequencingGameStartedRef.current = false;
        lastGameEndRef.current = Date.now();
        
        // 更新最终统计
        if (data.stats) {
          setSequencingStats({
            size: data.stats.size || { correct: 0, wrong: 0 },
            length: data.stats.length || { correct: 0, wrong: 0 },
            height: data.stats.height || { correct: 0, wrong: 0 },
            count: data.stats.count || { correct: 0, wrong: 0 }
          });
        }
        
        setPlaybackNotice('排序题组已完成；完整表扬结束后将自动进入评分');
      });
      
      // 关键词自动表扬：服务端已播完整表扬包时只挂打分；否则等同点「表扬」
      socket.on('keyword_auto_praise', (data: {
        sessionId?: string;
        requestId?: string;
        courseType?: string;
        itemId?: string | number;
        keyword?: string;
        serverPlayed?: boolean;
        behaviorId?: string;
        hasAnimation?: boolean;
        behaviorAnimation?: string;
      }) => {
        if (!eventMatchesCurrentSession(data)) {
          // Soft fallback: same item on teacher UI still accepts (session race).
          const courseIdxSoft = currentCourseIndexRef.current;
          const itemIdxSoft = currentItemIndexRef.current;
          const selectedSoft = selectedCourseItemsRef.current[courseIdxSoft];
          const currentItemSoft = selectedSoft?.items?.[itemIdxSoft];
          const eventItemIdSoft = data?.itemId != null ? String(data.itemId) : null;
          if (
            !(
              eventItemIdSoft &&
              currentItemSoft?.id != null &&
              eventItemIdSoft === String(currentItemSoft.id)
            )
          ) {
            console.log('🏅 忽略 keyword_auto_praise（会话不匹配）:', data);
            return;
          }
          console.log('🏅 keyword_auto_praise 会话软匹配（按课点）:', data);
        }
        const courseIdx = currentCourseIndexRef.current;
        const itemIdx = currentItemIndexRef.current;
        const selected = selectedCourseItemsRef.current[courseIdx];
        const currentType = selected?.course?.type;
        if (currentType === 'pairing' || currentType === 'ordering') {
          return;
        }
        // 课点已切走则忽略（避免迟到事件误表扬）
        const currentItem = selected?.items?.[itemIdx];
        const eventItemId = data?.itemId != null ? String(data.itemId) : null;
        if (
          eventItemId != null &&
          currentItem?.id != null &&
          eventItemId !== String(currentItem.id)
        ) {
          console.log('🏅 忽略 keyword_auto_praise（课点已切换）:', data);
          return;
        }
        // 已在打分/切题流程中则不再重复触发表扬
        if (advanceLockRef.current || praiseRequestContextRef.current) {
          console.log('🏅 忽略 keyword_auto_praise（已在表扬/打分流程）:', data);
          return;
        }
        // Socket 若仍投递到多个房间，ack 前会连收两次；用 requestId/课点立即占坑
        const eventRequestId = data?.requestId != null ? String(data.requestId) : null;
        const inflight = keywordAutoPraiseInFlightRef.current;
        const nowMs = Date.now();
        if (
          inflight &&
          (
            (eventRequestId && inflight.requestId === eventRequestId) ||
            (eventItemId &&
              inflight.itemId === eventItemId &&
              nowMs - inflight.atMs < 8000)
          )
        ) {
          console.log('🏅 忽略重复 keyword_auto_praise:', data);
          return;
        }
        keywordAutoPraiseInFlightRef.current = {
          requestId: eventRequestId,
          itemId: eventItemId || (currentItem?.id != null ? String(currentItem.id) : null),
          atMs: nowMs,
        };
        completionAtRef.current = nowMs;

        // Server already ran the full praise package — only attach scoring.
        if (data?.serverPlayed && eventRequestId) {
          console.log('🏅 收到 keyword_auto_praise（服务端已播完整包），挂接打分:', data);
          const praiseContext = {
            requestId: eventRequestId,
            courseIndex: courseIdx,
            itemIndex: itemIdx,
            sessionId:
              normalizeId(data?.sessionId) || currentSessionIdRef.current || null,
            behaviorId: normalizeId(data?.behaviorId),
            animationExpected: data?.hasAnimation === true,
            fallbackTimerId: null,
          };
          praiseRequestContextRef.current = praiseContext;
          queuePraiseRating(praiseContext);
          return;
        }

        console.log('🏅 收到 keyword_auto_praise，等同教师点击表扬:', data);
        playCurrentItemRef.current({ praise: true });
      });

      // 表扬视频结束仅负责清理播放状态；评分在请求接受后独立计时。
      socket.on('behavior_animation_ended', (data: {
        sessionId: string;
        requestId?: string;
        status?: string;
        terminalStatus?: string;
        reason?: string;
      }) => {
        if (!eventMatchesCurrentSession(data)) return;
        const praiseContext = praiseRequestContextRef.current;
        const eventRequestId = normalizeId(data?.requestId);
        if (
          !praiseContext ||
          !eventRequestId ||
          eventRequestId !== praiseContext.requestId ||
          praiseContext.courseIndex !== currentCourseIndexRef.current ||
          praiseContext.itemIndex !== currentItemIndexRef.current ||
          (praiseContext.sessionId && praiseContext.sessionId !== data.sessionId)
        ) {
          return;
        }
        console.log('🎬 收到 behavior_animation_ended 事件:', data);
        const animationStatus = String(
          data?.terminalStatus || data?.status || 'ended',
        ).toLowerCase();
        if (animationStatus !== 'ended') {
          queuePraiseRating(
            praiseContext,
            `表扬动画未完整播放（${data?.reason || animationStatus}），现可评分`,
          );
          return;
        }
        const selected = selectedCourseItemsRef.current;
        const courseIdx = currentCourseIndexRef.current;
        const current = selected?.[courseIdx];

        // 配对/排序课程仍播放完整语音和儿童屏动画，但结束后回到
        // 当前题目，不进入“表扬视频结束 -> 评分/下一题”链路。
        const currentType = current?.course?.type;
        if (currentType === 'pairing' || currentType === 'ordering') {
          console.log('🛡️ 忽略交互课的 behavior_animation_ended:', currentType);
          clearPraiseRequestContext(praiseContext.requestId);
          return;
        }

        queuePraiseRating(praiseContext);
      });
      
      return socket;
    };
    
    createSocket(socketUrl);

    // 清理函数：组件卸载时断开连接
    return () => {
      disposed = true;
      coursesAbortController.abort();
      console.log('清理 Socket.IO 连接');
      cancelAutoQuestionWait();
      cancelPendingGameStartsRef.current();
      cancelPendingGameStartsRef.current = () => {};
      clearAllScheduledTimeouts();
      if (latencyProbeTimerRef.current) {
        window.clearInterval(latencyProbeTimerRef.current);
        latencyProbeTimerRef.current = null;
      }
      pendingPlayRequestsRef.current.clear();
      knownPlayRequestsRef.current.clear();
      handledPlayBroadcastIdsRef.current.clear();
      readyContentRequestIdsRef.current.clear();
      failedTransitionRequestIdsRef.current.clear();
      contentResourceWaitRef.current = null;
      awaitingResourceReadyRef.current = false;
      contentRequestRef.current = null;
      clearPraiseRequestContext();
      clearCompletionRatingContext();
      socialAutomationIdsRef.current.clear();
      socialEntryRequestIdsRef.current.clear();
      deferredSocialEntryRef.current = null;
      interactiveQuestionIdRef.current = null;
      interactiveNextPendingRef.current = null;
      pendingPraiseAdvanceRef.current = null;
      praiseRatingTimerRef.current = null;
      if (dialogueControlTimerRef.current) {
        window.clearTimeout(dialogueControlTimerRef.current);
        dialogueControlTimerRef.current = null;
      }
      dialogueControlRequestRef.current = null;
      deferredManualPlayRef.current = null;
      const leavingTrainingId = trainingSessionIdRef.current;
      const leavingStudentId = selectedStudentRef.current
        ? parseInt(selectedStudentRef.current, 10)
        : undefined;
      const leaveOperationId = leavingTrainingId
        ? `teacher-leave:${leavingTrainingId}`
        : undefined;
      if (leavingTrainingId && navigator.sendBeacon) {
        const beaconPayload = new Blob([JSON.stringify({
          trainingSessionId: leavingTrainingId,
          studentId: leavingStudentId,
          operationId: leaveOperationId,
          requestId: leaveOperationId,
          reason: 'teacher_leave_control',
        })], { type: 'application/json' });
        navigator.sendBeacon(`${API_BASE}/api/training/finalize-beacon`, beaconPayload);
      }
      const activeSocket = socketRef.current;
      if (activeSocket) {
        const presenceTimer = (activeSocket as any).__presenceTimer;
        if (presenceTimer) {
          window.clearInterval(presenceTimer);
        }
        if (activeSocket.connected) {
          activeSocket.emit('teacher_leave_control', {
            status: 'leave',
            studentId: leavingStudentId,
            sessionId: currentSessionIdRef.current || undefined,
            trainingSessionId: leavingTrainingId || undefined,
            operationId: leaveOperationId,
            requestId: leaveOperationId,
          });
        }
        activeSocket.io.removeAllListeners();
        activeSocket.removeAllListeners();
        activeSocket.disconnect();
        socketRef.current = null;
      }
    };
  }, [
    armPlayRequestTimeout,
    armAutoQuestionWait,
    armCompletionRatingFallback,
    armPraiseRatingFallback,
    cancelAutoQuestionWait,
    clearAllScheduledTimeouts,
    clearContentResourceWait,
    clearCompletionRatingContext,
    clearCompletionRatingContext,
    clearPraiseRequestContext,
    clearScheduledTimeout,
    completeInteractiveNext,
    flushDeferredAutoQuestion,
    holdPlaybackGate,
    markResourceReady,
    queueCompletionRating,
    queuePraiseRating,
    releasePlaybackGate,
    scheduleTimeout,
    setPlaybackGate,
    isPreviewMode,
    previewCourses,
  ]);

  useEffect(() => {
    if (isPreviewMode) return;
    const finalizeOnPageExit = () => {
      const activeTrainingId = trainingSessionIdRef.current;
      if (!activeTrainingId || !navigator.sendBeacon) return;
      const operationId = `teacher-leave:${activeTrainingId}`;
      navigator.sendBeacon(
        `${API_BASE}/api/training/finalize-beacon`,
        new Blob([JSON.stringify({
          trainingSessionId: activeTrainingId,
          studentId: selectedStudentRef.current
            ? parseInt(selectedStudentRef.current, 10)
            : undefined,
          operationId,
          requestId: operationId,
          reason: 'browser_page_exit',
        })], { type: 'application/json' }),
      );
    };
    window.addEventListener('pagehide', finalizeOnPageExit);
    return () => window.removeEventListener('pagehide', finalizeOnPageExit);
  }, [isPreviewMode]);

  // 排序游戏：自动模式切换
  const handleSequencingAutoModeChange = useCallback((autoMode: boolean) => {
    const nextConfig = { ...sequencingConfigRef.current, autoMode };
    sequencingConfigRef.current = nextConfig;
    setSequencingConfig(nextConfig);
    console.log(`📊 设置排序游戏自动模式: ${autoMode ? '开启' : '关闭'}`);
    
    if (socketRef.current?.connected) {
      socketRef.current.emit('sequencing_set_config', {
        sessionId: currentSessionId,
        ...nextConfig
      });
    }
  }, [currentSessionId]);

  // 排序游戏：配置变更（类别或规则）
  const handleSequencingConfigChange = useCallback((key: string, value: string | number) => {
    const nextConfig = { ...sequencingConfigRef.current, [key]: value };

    // 切换类别时同时选择该类别的默认规则，保证下一题的图片与题干一致。
    if (key === 'category') {
      const defaultRules: Record<string, string> = {
        size: 'bigger',
        length: 'longer',
        height: 'taller',
        count: 'more'
      };
      nextConfig.rule = defaultRules[value as string] || 'bigger';
    }

    sequencingConfigRef.current = nextConfig;
    setSequencingConfig(nextConfig);
    
    console.log(`📊 排序游戏配置变更: ${key}=${value}`);

    if (socketRef.current?.connected) {
      socketRef.current.emit('sequencing_set_config', {
        sessionId: currentSessionId,
        ...nextConfig
      });
    }
  }, [currentSessionId]);

  // 排序游戏：发送提示
  const handleSequencingHint = useCallback(() => {
    if (socketRef.current?.connected) {
      socketRef.current.emit('sequencing_hint', {
        sessionId: currentSessionId
      });
      console.log('💡 发送排序游戏提示');
    }
  }, [currentSessionId]);

  // 配对游戏：发送提示
  const handleMatchingHint = useCallback(() => {
    if (socketRef.current?.connected) {
      socketRef.current.emit('matching_hint', {
        sessionId: currentSessionId
      });
      console.log('💡 发送配对游戏提示');
    }
  }, [currentSessionId]);

  // “下一题”只切换配对/排序内部题目；“下一个”仍负责切换课点。
  const handleInteractiveNextQuestion = useCallback(() => {
    const selected = selectedCourseItemsRef.current[currentCourseIndexRef.current];
    const courseType = selected?.course?.type;
    const eventName = courseType === 'pairing'
      ? 'matching_next'
      : courseType === 'ordering'
        ? 'sequencing_next'
        : null;
    const activeSocket = socketRef.current;
    const sessionId = currentSessionIdRef.current;
    if (!eventName || !activeSocket?.connected || !sessionId) {
      setPlaybackNotice('当前课程尚未准备好下一题');
      return;
    }
    if (interactiveNextPendingRef.current) {
      setPlaybackNotice('下一题正在准备，请不要连续点击');
      return;
    }
    const requestId = createClientRequestId(eventName);
    const interactiveCourseType = selected?.course?.type as 'pairing' | 'ordering';
    interactiveNextPendingRef.current = {
      courseType: interactiveCourseType,
      previousQuestionId: interactiveQuestionIdRef.current,
      requestId,
      timeoutId: null,
    };
    setInteractiveNextPending(true);
    const timeoutId = scheduleTimeout(() => {
      const pending = interactiveNextPendingRef.current;
      if (!pending || pending.requestId !== requestId) return;
      interactiveNextPendingRef.current = null;
      setInteractiveNextPending(false);
      setPlaybackNotice('下一题暂未显示，已解除按钮锁定；可重试，不会跳过更多题目');
    }, 6000);
    if (interactiveNextPendingRef.current?.requestId === requestId) {
      interactiveNextPendingRef.current.timeoutId = timeoutId;
    }
    activeSocket.emit(eventName, {
      sessionId,
      trainingSessionId: trainingSessionIdRef.current || undefined,
      questionId: interactiveQuestionIdRef.current || currentQuestionIdRef.current || undefined,
      mode,
      requestId,
      source: 'teacher_next_question',
    });
    setPlaybackNotice('正在进入下一题…');
  }, [mode, scheduleTimeout]);

  // 排序游戏：启动游戏
  const handleStartSequencingGame = useCallback(() => {
    console.log('📊 启动排序游戏');
    
    if (socketRef.current?.connected) {
      // 先发送配置
      socketRef.current.emit('sequencing_set_config', {
        sessionId: currentSessionId,
        autoMode: sequencingConfig.autoMode,
        category: sequencingConfig.category,
        difficulty: sequencingConfig.difficulty,
        rule: sequencingConfig.rule
      });
      
      // 再发送启动指令
      socketRef.current.emit('sequencing_start', {
        sessionId: currentSessionId
      });
      
      // 重置游戏状态
      setSequencingStatus({
        currentQuestion: 0,
        totalQuestions: 16,
        category: sequencingConfig.category,
        rule: sequencingConfig.rule
      });
      
      setSequencingStats({
        size: { correct: 0, wrong: 0 },
        length: { correct: 0, wrong: 0 },
        height: { correct: 0, wrong: 0 },
        count: { correct: 0, wrong: 0 }
      });
      
      setSequencingGameStarted(true);
      sequencingGameStartedRef.current = true;
    }
  }, [currentSessionId, sequencingConfig]);

  // 配对游戏：设置难度
  const handleSetMatchingDifficulty = useCallback((level: number) => {
    matchingDifficultyRef.current = level;
    setMatchingDifficulty(level);
    console.log(`🎮 设置配对游戏难度: ${level}选1`);
    
    if (socketRef.current?.connected) {
      socketRef.current.emit('matching_set_difficulty', {
        sessionId: currentSessionId,
        difficulty: level
      });
    }
  }, [currentSessionId]);

  // 配对游戏：启动游戏
  const handleStartMatchingGame = useCallback(() => {
    console.log('🎮 启动配对游戏');
    
    if (socketRef.current?.connected) {
      // 先发送难度设置
      socketRef.current.emit('matching_set_difficulty', {
        sessionId: currentSessionId,
        difficulty: matchingDifficulty
      });
      
      // 再发送启动指令
      socketRef.current.emit('matching_start', {
        sessionId: currentSessionId
      });
      
      // 重置游戏状态
      setMatchingStatus({
        currentDifficulty: matchingDifficulty,
        currentQuestion: 0,
        totalQuestions: 15,
        correctCount: 0,
        wrongCount: 0,
        accuracy: 0,
        isCorrect: false,
        consecutiveCorrect: 0,
        isSimplifiedMode: false
      });
      setMatchingGameStarted(true);
      matchingGameStartedRef.current = true;
    }
  }, [currentSessionId, matchingDifficulty]);

  const buildQuestionId = (courseId: number | string, itemId: number | string | null | undefined, index: number) =>
    `${courseId}_${itemId ?? 'na'}_${index}`;

  // 播放当前子项的函数
  const playCurrentItem = useCallback((
    aux: PlayAux = {},
    options: {
      retryCount?: number;
      expectedCourseIndex?: number;
      expectedItemIndex?: number;
      requestId?: string;
      advanceAfterPlayback?: AdvanceSource;
    } = {},
  ) => {
    console.log('🎯 playCurrentItem 被调用，参数:', aux);
    console.log('Socket 连接状态:', socketRef.current?.connected);
    const courseItems = selectedCourseItemsRef.current;
    const courseIndex = currentCourseIndexRef.current;
    const itemIndex = currentItemIndexRef.current;
    const intent = getPlayIntent(aux);
    const isContent = intent === 'content';
    console.log('选中的课程数量:', courseItems.length);

    if (
      (options.expectedCourseIndex != null &&
        options.expectedCourseIndex !== courseIndex) ||
      (options.expectedItemIndex != null &&
        options.expectedItemIndex !== itemIndex)
    ) {
      return;
    }
    
    if (!socketRef.current) {
      console.error('❌ 无法播放：Socket 引用不存在');
      setPlaybackNotice('连接尚未初始化，请稍后重试');
      return;
    }

    if (!socketRef.current.connected) {
      console.error('❌ 无法播放：Socket 未连接');
      setPlaybackNotice('网络连接中断，恢复连接后可继续');
      return;
    }

    if (courseItems.length === 0) {
      console.warn('⚠️ 无法播放：没有选中的课程');
      return;
    }

    const selectedItem = courseItems[courseIndex];
    if (!selectedItem) {
      console.warn('⚠️ 无法播放：当前课程不存在，索引:', courseIndex);
      return;
    }

    // 如果课程有子项，使用当前子项；否则 itemId 为 null（如 pairing/ordering 类型）
    const item = selectedItem.items.length > 0 ? selectedItem.items[itemIndex] : null;
    const itemId = item ? item.id : null;
    const contentKey =
      `${selectedItem.courseId}:${itemId ?? 'na'}:${courseIndex}:${itemIndex}`;

    if (
      isContent &&
      contentRequestRef.current?.key === contentKey &&
      (contentRequestRef.current.status === 'pending' ||
        contentRequestRef.current.status === 'accepted')
    ) {
      console.log('🛡️ 忽略同一课点的重复播放请求:', contentKey);
      return;
    }

    if (
      playbackPhaseRef.current !== 'idle' ||
      audioPlayingRef.current ||
      awaitingResourceReadyRef.current
    ) {
      if (!isContent) {
        const previous = deferredManualPlayRef.current;
        const isDuplicate = Boolean(
          previous &&
          previous.intent === intent &&
          previous.courseIndex === courseIndex &&
          previous.itemIndex === itemIndex
        );
        if (!isDuplicate) {
          deferredManualPlayRef.current = {
            aux: { ...aux },
            intent,
            courseIndex,
            itemIndex,
            advanceAfterPlayback: options.advanceAfterPlayback,
          };
        }
        const intentLabel: Record<Exclude<PlayIntent, 'content'>, string> = {
          attention: '吸引',
          reward: '夸奖',
          question: '提问',
          praise: '表扬',
          hint: '提示',
          social: '社交回应',
        };
        setPlaybackNotice(
          isDuplicate
            ? `${intentLabel[intent]}已在等待执行，请勿重复点击`
            : `当前课程输出尚未完成，已排队：${intentLabel[intent]}`,
        );
        return;
      }
      deferredContentRetryRef.current = {
        requestId: createClientRequestId('play-content-deferred'),
        courseIndex,
        itemIndex,
        retryCount: Math.max(0, options.retryCount || 0),
      };
      setPlaybackNotice(
        playbackPhaseRef.current === 'pending'
          ? '正在确认上一条操作，请稍候'
          : '上一条语音或儿童屏动画仍在播放，新课点将在结束后加载',
      );
      return;
    }

    // 验证studentId是否存在
    if (!selectedStudent) {
      console.error('❌ 无法播放：未选择学生');
      setPlaybackNotice('请先选择学生');
      return;
    }
    const studentId = parseInt(selectedStudent, 10);
    if (!Number.isFinite(studentId)) {
      setPlaybackNotice('儿童标识无效，请返回后重新选择');
      return;
    }

    if (!isContent && !currentSessionIdRef.current) {
      setPlaybackNotice('课点尚未准备完成，请稍候');
      return;
    }

    const expectedQuestionId = buildQuestionId(selectedItem.courseId, itemId, itemIndex);

    // 获取目标图片路径（用于姿态比对）
    // 优先使用子项的 file，其次使用课程的 file
    const targetImage = item?.file || selectedItem.course.file || null;
    
    // 构建完整的 aux 数据
    const { behaviorAnimationOverride, ...auxFlags } = aux;
    const fullAux = {
      ...auxFlags,
      targetImage: targetImage,  // 添加目标图片路径
      targetText: item?.speechTarget || item?.name || selectedItem.course.title,  // speech_target 优先，空则回退 name
    };

    const orderingQuestionConfig = (
      selectedItem.course.type === 'ordering' && !isContent
        ? sequencingActiveQuestionRef.current
        : null
    ) || sequencingConfigRef.current;

    const requestId = options.requestId || createClientRequestId(`play-${intent}`);
    const clientCommandAtMs = Date.now();
    const playData = {
      action: "play",
      requestId,
      clientCommandAtMs,
      teacherNetworkRttMs: teacherLatencyRef.current,
      clientTransport: (socketRef.current.io.engine.transport as any)?.name || 'unknown',
      studentId,
      courseId: selectedItem.courseId,
      itemId: itemId,
      courseType: selectedItem.course.type,  // 添加课程类型
      mode,
      ...(behaviorAnimationOverride ? { behaviorAnimationOverride } : {}),
      ...(selectedItem.course.type === 'ordering'
        ? {
            category: orderingQuestionConfig.category,
            rule: orderingQuestionConfig.rule,
          }
        : {}),
      questionIndex: itemIndex,
      itemIndex: itemIndex,
      sessionId: isContent ? undefined : currentSessionIdRef.current || undefined,
      trainingSessionId: trainingSessionIdRef.current || undefined,
      questionId: isContent ? expectedQuestionId : currentQuestionIdRef.current || expectedQuestionId,
      aux: fullAux
    };

    console.log('📤 发送播放请求到服务器:', playData);
    console.log('Socket ID:', socketRef.current.id);

    const pending: PendingPlayRequest = {
      requestId,
      intent,
      aux,
      isContent,
      contentKey: isContent ? contentKey : null,
      courseIndex,
      itemIndex,
      studentId: String(studentId),
      trainingSessionId: trainingSessionIdRef.current,
      requestedAtMs: Date.now(),
      payload: playData,
      timeoutId: null,
      retryCount: Math.max(0, options.retryCount || 0),
      advanceAfterPlayback: options.advanceAfterPlayback,
    };
    pendingPlayRequestsRef.current.set(requestId, pending);
    failedPlayRetryRef.current = null;
    setHasFailedPlayback(false);
    if (isContent) {
      contentRequestRef.current = {
        key: contentKey,
        requestId,
        status: 'pending',
      };
      armContentResourceWait(
        requestId,
        courseIndex,
        itemIndex,
        pending.retryCount,
      );
    }
    if (
      intent === 'praise' &&
      selectedItem.course.type !== 'pairing' &&
      selectedItem.course.type !== 'ordering'
    ) {
      clearPraiseRequestContext();
      const praiseContext: NonNullable<typeof praiseRequestContextRef.current> = {
        requestId,
        courseIndex,
        itemIndex,
        sessionId: currentSessionIdRef.current,
        behaviorId: null,
        animationExpected: null,
        fallbackTimerId: null,
      };
      praiseRequestContextRef.current = praiseContext;
      armPraiseRatingFallback(praiseContext, 15000);
    }
    if (options.advanceAfterPlayback) {
      clearCompletionRatingContext();
      const completionContext: NonNullable<typeof completionRatingContextRef.current> = {
        requestId,
        behaviorId: null,
        courseIndex,
        itemIndex,
        sessionId: currentSessionIdRef.current,
        source: options.advanceAfterPlayback,
        fallbackTimerId: null,
      };
      completionRatingContextRef.current = completionContext;
      armCompletionRatingFallback(completionContext, 15000);
    }
    setPlaybackGate('pending', requestId);
    setPlaybackNotice(null);
    armPlayRequestTimeout(pending);
    
    try {
      socketRef.current.emit("play_resource", playData);
      console.log('✅ 播放请求已发送');
    } catch (error) {
      clearScheduledTimeout(pending.timeoutId);
      pendingPlayRequestsRef.current.delete(requestId);
      clearPraiseRequestContext(requestId);
      clearCompletionRatingContext(requestId);
      if (contentRequestRef.current?.requestId === requestId) {
        contentRequestRef.current = null;
      }
      if (isContent) {
        clearContentResourceWait(requestId);
      }
      setPlaybackGate('idle', null, null, '发送播放请求失败');
      console.error('❌ 发送播放请求失败:', error);
    }
  }, [
    armContentResourceWait,
    armPlayRequestTimeout,
    armPraiseRatingFallback,
    armCompletionRatingFallback,
    clearCompletionRatingContext,
    clearPraiseRequestContext,
    clearScheduledTimeout,
    clearContentResourceWait,
    scheduleTimeout,
    selectedStudent,
    setPlaybackGate,
    mode,
  ]);

  useEffect(() => {
    playCurrentItemRef.current = playCurrentItem;
  }, [playCurrentItem]);

  const retryFailedPlayback = useCallback(() => {
    const retry = failedPlayRetryRef.current;
    if (!retry || playbackPhaseRef.current !== 'idle') return;
    if (
      retry.courseIndex !== currentCourseIndexRef.current ||
      retry.itemIndex !== currentItemIndexRef.current
    ) {
      failedPlayRetryRef.current = null;
      setHasFailedPlayback(false);
      return;
    }
    failedPlayRetryRef.current = null;
    setHasFailedPlayback(false);
    playCurrentItemRef.current(retry.aux, {
      requestId: retry.requestId,
      retryCount: retry.retryCount + 1,
      expectedCourseIndex: retry.courseIndex,
      expectedItemIndex: retry.itemIndex,
      advanceAfterPlayback: retry.advanceAfterPlayback,
    });
  }, []);

  // 统一的提示处理函数：根据课程类型分发
  const handleHint = useCallback(() => {
    const courseType = selectedCourseItems[currentCourseIndex]?.course?.type;
    
    if (courseType === 'ordering' && sequencingGameStarted) {
      // 排序课程：发送专用提示事件（高亮正确答案）
      handleSequencingHint();
    } else if (courseType === 'pairing' && matchingGameStarted) {
      // 配对课程：发送专用提示事件（高亮正确答案）
      handleMatchingHint();
    } else {
      // 其他课程：播放提示语音
      playCurrentItem({ hint: true });
    }
  }, [selectedCourseItems, currentCourseIndex, sequencingGameStarted, matchingGameStarted, handleSequencingHint, handleMatchingHint, playCurrentItem]);

  // 停止音频播放
  const handleStopAudio = useCallback(() => {
    if (!socketRef.current || !currentSessionId) {
      console.log('⚠️ 无法停止音频：Socket 未连接或无会话ID');
      return;
    }

    console.log('⏹️ 发送停止音频请求, session_id:', currentSessionId);
    
    try {
      socketRef.current.emit('stop_audio', {
        session_id: currentSessionId,
        immediate: true
      });
      console.log('✅ 停止音频请求已发送');
      
      // 立即更新本地状态
      audioPlayingRef.current = false;
      setAudioStatus({
        isPlaying: false,
        entryId: null,
        progress: 0
      });
    } catch (error) {
      console.error('❌ 发送停止音频请求失败:', error);
    }
  }, [currentSessionId]);

  const toggleDialogueAgent = useCallback(() => {
    const activeSocket = socketRef.current;
    const sessionId = currentSessionIdRef.current;
    if (!activeSocket?.connected || !sessionId) {
      setDialogueControlNotice('当前没有有效课程，或儿童端尚未连接');
      return;
    }
    const selected = selectedCourseItemsRef.current[currentCourseIndexRef.current];
    if (!selected && !dialogueAwake) {
      setDialogueControlNotice('当前没有有效课程，请先进入课程');
      return;
    }
    const item = selected?.items?.[currentItemIndexRef.current] || null;
    const action = dialogueAwake ? 'sleep' : 'wake';
    const requestId = createClientRequestId(`dialogue-${action}`);
    if (dialogueControlTimerRef.current) {
      window.clearTimeout(dialogueControlTimerRef.current);
    }
    dialogueControlRequestRef.current = requestId;
    setDialogueControlBusy(true);
    setDialogueControlNotice(dialogueAwake ? '正在停止智能体回复…' : '正在静默唤醒智能体…');
    activeSocket.emit(dialogueAwake ? 'teacher_dialogue_sleep' : 'teacher_dialogue_wake', {
      sessionId,
      trainingSessionId: trainingSessionIdRef.current || undefined,
      questionId: currentQuestionIdRef.current,
      requestId,
      clientTimestamp: Date.now(),
      ...(!dialogueAwake && selected ? {
        pageContext: {
          courseId: selected.courseId,
          courseType: selected.course?.type,
          itemId: item?.id ?? null,
          questionId: currentQuestionIdRef.current,
          target: item?.speechTarget || item?.name || selected.course?.title || '',
          speechTarget: item?.speechTarget || '',
          objectName: item?.name || selected.course?.title || '',
        },
      } : {}),
    });
    dialogueControlTimerRef.current = window.setTimeout(() => {
      if (dialogueControlRequestRef.current !== requestId) return;
      dialogueControlRequestRef.current = null;
      dialogueControlTimerRef.current = null;
      setDialogueControlBusy(false);
      setDialogueControlNotice('暂未收到儿童端回执，按钮已恢复，可确认连接后重试');
    }, 4000);
  }, [dialogueAwake]);

  useEffect(() => {
    const activeSocket = socketRef.current;
    const sessionId = currentSessionIdRef.current;
    if (!socketConnected || !activeSocket?.connected || !sessionId) return;
    const selected = selectedCourseItemsRef.current[currentCourseIndexRef.current];
    const item = selected?.items?.[currentItemIndexRef.current] || null;
    activeSocket.emit('teacher_dialogue_state_request', {
      sessionId,
      trainingSessionId: trainingSessionIdRef.current || undefined,
      pageContext: {
        courseId: selected?.courseId,
        courseType: selected?.course?.type,
        itemId: item?.id ?? null,
        questionId: currentQuestionIdRef.current,
      },
    });
  }, [socketConnected, currentSessionId, currentQuestionId]);

  // 只读观察模式下点击"接管控制"：重新发起控制权申请。
  // 服务端 TeacherControlRegistry 对同一教师的旧连接会替换其租约，
  // 本窗口升级为 controller，另一个窗口收到 teacher_control_state 后降级为 observer。
  const claimTeacherControl = useCallback(() => {
    const activeSocket = socketRef.current;
    if (!activeSocket?.connected) {
      setClaimingControlNotice('控制权不可用：连接未就绪');
      return;
    }
    setClaimingControl(true);
    activeSocket.emit('teacher_enter_control', {
      status: 'enter',
      studentId: selectedStudentRef.current
        ? parseInt(selectedStudentRef.current, 10)
        : undefined,
      sessionId: currentSessionIdRef.current || undefined,
      trainingSessionId: trainingSessionIdRef.current || undefined,
    });
    // teacher_control_state 会回调更新 controlRole；若 3s 内无回调则提示重试
    if (claimControlTimerRef.current != null) {
      clearTimeout(claimControlTimerRef.current);
    }
    claimControlTimerRef.current = window.setTimeout(() => {
      setClaimingControl(false);
      setClaimingControlNotice('暂未接管成功，请重试；可能是网络延迟或服务端繁忙');
    }, 3000);
  }, []);

  // 自动加载当前课点。提问语音只允许由非 aux 的 play_resource_ack 触发一次。
  useEffect(() => {
    if (isPreviewMode) return;
    if (selectedCourseItems.length === 0 || loading || !socketConnected || !socketRef.current?.connected) return;
    const selectedItem = selectedCourseItems[currentCourseIndex];
    if (!selectedItem) return;
    const item = selectedItem.items.length > 0 ? selectedItem.items[currentItemIndex] : null;
    if (selectedItem.items.length > 0 && !item) return;

    const requestKey = `${selectedItem.courseId}:${item?.id ?? 'na'}:${currentCourseIndex}:${currentItemIndex}`;
    if (lastContentRequestKeyRef.current === requestKey) {
      console.log('🛡️ 忽略重复课点自动加载:', requestKey);
      return;
    }
    lastContentRequestKeyRef.current = requestKey;
    autoQuestionSentForRef.current = null;

    const timer = scheduleTimeout(() => {
      console.log('🔄 自动加载课点:', requestKey, readinessPassed ? '(readinessPassed)' : '');
      playCurrentItemRef.current({});
    }, readinessPassed ? 50 : 100);
    return () => {
      clearScheduledTimeout(timer);
      // 定时器被依赖项变化取消时，清掉去重键，允许同课点重试；
      // 否则「下一个」后 effect 重跑会永久跳过，儿童端停在上一题。
      if (lastContentRequestKeyRef.current === requestKey) {
        lastContentRequestKeyRef.current = null;
      }
    };
  }, [
    clearScheduledTimeout,
    currentCourseIndex,
    currentItemIndex,
    selectedCourseItems,
    loading,
    readinessPassed,
    scheduleTimeout,
    socketConnected,
    isPreviewMode,
  ]);

  // 按类别分组选中的课程
  const coursesByCategory = selectedCourseItems.reduce((acc, selectedItem) => {
    const categoryId = selectedItem.course.type;
    if (!acc[categoryId]) {
      acc[categoryId] = [];
    }
    acc[categoryId].push(selectedItem);
    return acc;
  }, {} as Record<string, SelectedCourseItem[]>);

  const currentSelectedItem = selectedCourseItems[currentCourseIndex];
  const currentCourse = currentSelectedItem?.course;
  const currentItem = currentSelectedItem?.items[currentItemIndex];

  const toggleCategory = (categoryId: string) => {
    const newExpanded = new Set(expandedCategories);
    if (newExpanded.has(categoryId)) {
      newExpanded.delete(categoryId);
    } else {
      newExpanded.add(categoryId);
    }
    setExpandedCategories(newExpanded);
  };

  // 切换到指定课程
  const handleJumpToCourse = (courseIndex: number) => {
    if (
      playbackPhaseRef.current !== 'idle' ||
      audioStatus.isPlaying ||
      awaitingResourceReadyRef.current
    ) {
      setPlaybackNotice('当前交互尚未结束，暂不能切换课程');
      return;
    }
    if (courseIndex >= 0 && courseIndex < selectedCourseItems.length) {
      setCurrentCourseIndex(courseIndex);
      setCurrentItemIndex(0); // 切换到课程的第一个子项
    }
  };

  // 切换到指定课程的子项
  const handleJumpToItem = (courseIndex: number, itemIndex: number) => {
    if (
      playbackPhaseRef.current !== 'idle' ||
      audioStatus.isPlaying ||
      awaitingResourceReadyRef.current
    ) {
      setPlaybackNotice('当前交互尚未结束，暂不能切换课点');
      return;
    }
    if (courseIndex >= 0 && courseIndex < selectedCourseItems.length) {
      const selectedItem = selectedCourseItems[courseIndex];
      if (itemIndex >= 0 && itemIndex < selectedItem.items.length) {
        setCurrentCourseIndex(courseIndex);
        setCurrentItemIndex(itemIndex);
      }
    }
  };

  const commitAdvance = useCallback((snapshot: AdvanceSnapshot) => {
    const selected = selectedCourseItemsRef.current;
    const current = selected[snapshot.courseIndex];
    if (!current) return;
    keywordAutoPraiseInFlightRef.current = null;
    if (current.items.length > 0 && snapshot.itemIndex < current.items.length - 1) {
      const nextItemIndex = snapshot.itemIndex + 1;
      currentCourseIndexRef.current = snapshot.courseIndex;
      currentItemIndexRef.current = nextItemIndex;
      setCurrentCourseIndex(snapshot.courseIndex);
      setCurrentItemIndex(nextItemIndex);
    } else if (snapshot.courseIndex < selected.length - 1) {
      const nextCourseIndex = snapshot.courseIndex + 1;
      currentCourseIndexRef.current = nextCourseIndex;
      currentItemIndexRef.current = 0;
      setCurrentCourseIndex(nextCourseIndex);
      setCurrentItemIndex(0);
    } else {
      // 末课评分完成后弹出「课程完成」；训练结束由弹窗打开时自动 finalize
      setShowFinishConfirm(true);
    }
  }, []);

  // 所有手动/自动“下一个”都先冻结当前课点并请求教师评分。
  const requestAdvance = useCallback((source: AdvanceSource = 'manual') => {
    if (advanceLockRef.current) return;
    if (hasFailedPlayback) {
      setPlaybackNotice('新课点尚未成功显示，请先重试，儿童端仍保留上一帧');
      return;
    }
    if (
      source !== 'praise_end' &&
      (
        playbackPhaseRef.current !== 'idle' ||
        audioPlayingRef.current ||
        awaitingResourceReadyRef.current
      )
    ) {
      setPlaybackNotice('请等待当前语音或儿童屏动画播放完成后再进入下一项');
      return;
    }
    const selected = selectedCourseItemsRef.current;
    const courseIndex = currentCourseIndexRef.current;
    const itemIndex = currentItemIndexRef.current;
    const current = selected[courseIndex];
    if (!current) return;

    const item = current.items.length > 0 ? current.items[itemIndex] : null;
    const expectedQuestionId = `${current.courseId}_${item?.id ?? 'na'}_${itemIndex}`;
    let ts = trainingSessionIdRef.current;
    let questionId = currentQuestionIdRef.current || expectedQuestionId;

    // 首次进课 ACK 未到时：补发一次内容加载并短暂等待，避免误报“未关联”
    if (!ts) {
      playCurrentItemRef.current({});
      const expectedCourseIndex = courseIndex;
      const expectedItemIndex = itemIndex;
      scheduleTimeout(() => {
        if (advanceLockRef.current) return;
        if (
          currentCourseIndexRef.current !== expectedCourseIndex ||
          currentItemIndexRef.current !== expectedItemIndex
        ) {
          return;
        }
        ts = trainingSessionIdRef.current;
        questionId = currentQuestionIdRef.current || expectedQuestionId;
        if (!ts) {
          alert('课点数据仍在同步，请确认儿童端已显示内容后再试');
          return;
        }
        currentQuestionIdRef.current = questionId;
        setCurrentQuestionId(questionId);
        requestAdvance(source);
      }, 600);
      return;
    }

    if (!currentQuestionIdRef.current) {
      currentQuestionIdRef.current = questionId;
      setCurrentQuestionId(questionId);
    }

    const courseType = current.course.type;
    const completedAt = completionAtRef.current || Date.now();
    const startedAt = questionStartedAtRef.current;
    const usesGameMetrics = courseType === 'pairing' || courseType === 'ordering';
    const responseMs = !usesGameMetrics && startedAt != null
      ? Math.max(0, completedAt - startedAt)
      : null;

    if (socketRef.current?.connected && currentSessionIdRef.current) {
      socketRef.current.emit('freeze_course_frame', {
        sessionId: currentSessionIdRef.current,
        trainingSessionId: ts,
        questionId,
      });
    }
    advanceLockRef.current = true;
    completionAtRef.current = null;
    setSelectedRating(null);
    setRatingError(null);
    setPendingAdvance({
      source,
      trainingSessionId: ts,
      questionId,
      runtimeSessionId: currentSessionIdRef.current,
      courseIndex,
      itemIndex,
      courseId: current.courseId,
      courseItemId: item?.id ?? null,
      courseType,
      courseName: courseTypeMap[courseType]?.name || current.course.title,
      itemName: item?.name || current.course.title,
      responseMs,
      responseSource: usesGameMetrics ? 'game_metrics' : 'teacher_advance',
      clientRecordedAt: new Date(completedAt).toISOString(),
    });
  }, [hasFailedPlayback, scheduleTimeout]);

  useEffect(() => {
    handleNextRef.current = requestAdvance;
  }, [requestAdvance]);

  const cancelTeacherRating = useCallback(() => {
    if (ratingSaving) return;
    advanceLockRef.current = false;
    setPendingAdvance(null);
    setSelectedRating(null);
    setRatingError(null);
  }, [ratingSaving]);

  const submitTeacherRating = useCallback(async () => {
    const socket = socketRef.current;
    const snapshot = pendingAdvance;
    if (!socket?.connected || !snapshot || selectedRating == null || ratingSaving) {
      if (!socket?.connected) setRatingError('Socket.IO 未连接');
      return;
    }
    setRatingSaving(true);
    setRatingError(null);
    try {
      await new Promise<void>((resolve, reject) => {
        const requestId = createClientRequestId('teacher-rating');
        let settled = false;
        const onAck = (data: any) => {
          if (
            normalizeId(data?.requestId) !== requestId ||
            data?.trainingSessionId !== snapshot.trainingSessionId ||
            data?.questionId !== snapshot.questionId
          ) return;
          if (settled) return;
          settled = true;
          clearScheduledTimeout(timeout);
          socket.off('teacher_rating_ack', onAck);
          if (data?.success) resolve();
          else reject(new Error(data?.error || '服务端未保存评分'));
        };
        const timeout = scheduleTimeout(() => {
          if (settled) return;
          settled = true;
          socket.off('teacher_rating_ack', onAck);
          reject(new Error('等待服务端确认超时'));
        }, 8000);
        socket.on('teacher_rating_ack', onAck);
        socket.emit('teacher_rating_submit', {
          requestId,
          trainingSessionId: snapshot.trainingSessionId,
          questionId: snapshot.questionId,
          runtimeSessionId: snapshot.runtimeSessionId,
          courseId: snapshot.courseId,
          courseItemId: snapshot.courseItemId,
          courseType: snapshot.courseType,
          rating: selectedRating,
          responseMs: snapshot.responseMs,
          responseSource: snapshot.responseSource,
          advanceSource: snapshot.source,
          clientRecordedAt: snapshot.clientRecordedAt,
        });
      });
      setPendingAdvance(null);
      setSelectedRating(null);
      advanceLockRef.current = false;
      commitAdvance(snapshot);
    } catch (e: any) {
      setRatingError(e?.message || String(e));
    } finally {
      setRatingSaving(false);
    }
  }, [
    clearScheduledTimeout,
    commitAdvance,
    pendingAdvance,
    ratingSaving,
    scheduleTimeout,
    selectedRating,
  ]);

  const handlePraise = useCallback(() => {
    const courseType = selectedCourseItemsRef.current[currentCourseIndexRef.current]?.course?.type;
    if (courseType !== 'pairing' && courseType !== 'ordering') {
      completionAtRef.current = Date.now();
    }
    playCurrentItem({ praise: true });
  }, [playCurrentItem]);

  const handleAttention = useCallback(() => {
    playCurrentItem({ attention: true });
  }, [playCurrentItem]);

  const handleAttentionReward = useCallback(() => {
    playCurrentItem({
      reward: true,
      ...(rewardAnimation ? { behaviorAnimationOverride: rewardAnimation } : {}),
    });
  }, [playCurrentItem, rewardAnimation]);

  const handleRewardAnimationChange = useCallback((value: string) => {
    setRewardAnimation(value);
    if (!selectedStudent) return;
    try {
      if (value) localStorage.setItem(`maimai.reward-animation.${selectedStudent}`, value);
      else localStorage.removeItem(`maimai.reward-animation.${selectedStudent}`);
    } catch (_) { /* private browsing may disable storage */ }
  }, [selectedStudent]);

  const handleSocialVoice = useCallback((key: SocialAuxKey) => {
    playCurrentItem({ [key]: true });
  }, [playCurrentItem]);

  const handleBackClick = () => {
    setShowBackConfirm(true);
  };

  const confirmBack = () => {
    setShowBackConfirm(false);
    onBack();
  };

  const finalizeTraining = useCallback((): Promise<string | null> => {
    if (finalizePromiseRef.current) {
      return finalizePromiseRef.current;
    }

    const socket = socketRef.current;
    const activeTrainingId =
      normalizeId(trainingSessionIdRef.current) || normalizeId(trainingSessionId);
    if (!activeTrainingId) {
      return Promise.reject(new Error('当前训练尚未建立，无法结束训练'));
    }
    if (!socket?.connected) {
      return Promise.reject(new Error('网络连接已断开，恢复连接后再结束训练'));
    }

    const operationId =
      finalizeOperationIdRef.current || createClientRequestId('finalize-training');
    finalizeOperationIdRef.current = operationId;

    const promise = new Promise<string | null>((resolve, reject) => {
      let settled = false;
      const finish = (error: Error | null, resultId?: string | null) => {
        if (settled) return;
        settled = true;
        clearScheduledTimeout(timeout);
        socket.off('finalize_training_ack', onAck);
        if (error) reject(error);
        else resolve(resultId || null);
      };
      const onAck = (data: any) => {
        if (normalizeId(data?.operationId) !== operationId) return;
        const ackTrainingId = normalizeId(data?.trainingSessionId);
        if (ackTrainingId && ackTrainingId !== activeTrainingId) return;
        if (data?.success !== true) {
          finish(new Error(data?.error || '服务端未能结束本次训练'));
          return;
        }
        if (!ackTrainingId) {
          finish(new Error('结束训练确认缺少训练标识'));
          return;
        }
        setTrainingSessionId(ackTrainingId);
        trainingSessionIdRef.current = ackTrainingId;
        finish(null, ackTrainingId);
      };
      const timeout = scheduleTimeout(() => {
        finish(new Error('等待结束训练确认超时，请检查网络后重试'));
      }, 12000);

      socket.on('finalize_training_ack', onAck);
      socket.emit('finalize_training', {
        operationId,
        requestId: operationId,
        trainingSessionId: activeTrainingId,
        studentId: selectedStudent ? parseInt(selectedStudent, 10) : undefined,
      });
    });

    finalizePromiseRef.current = promise;
    promise.catch(() => {
      if (finalizePromiseRef.current === promise) {
        finalizePromiseRef.current = null;
      }
    });
    return promise;
  }, [
    clearScheduledTimeout,
    scheduleTimeout,
    selectedStudent,
    trainingSessionId,
  ]);

  const waitForRecentGameEnd = async () => {
    const courseType = selectedCourseItems[currentCourseIndex]?.course?.type;
    if (courseType !== 'pairing' && courseType !== 'ordering') return;
    // 游戏仍在进行（尚未收到 game_end）时最多等 3s
    if (!matchingGameStartedRef.current && !sequencingGameStartedRef.current) return;
    const start = Date.now();
    while (Date.now() - start < 3000) {
      if (lastGameEndRef.current > 0 && Date.now() - lastGameEndRef.current < 3500) return;
      if (!matchingGameStartedRef.current && !sequencingGameStartedRef.current) return;
      await new Promise<void>((resolve) => {
        scheduleTimeout(resolve, 200);
      });
    }
  };

  const probeReportStatus = async (ts: string, ensureGenerated = false) => {
    try {
      const readStatus = async () => {
        const response = await fetch(`${API_BASE}/api/report/${ts}/review-status`);
        return response.json();
      };
      let statusJson = await readStatus();
      // 课程结束时只在报告尚不存在时生成一次；之后的 2s 定时器只读取
      // 审核状态，避免把同一份 PARTIAL 报告反复广播为新提醒。
      if (
        ensureGenerated &&
        (!statusJson?.success || statusJson?.data?.publicationStatus === 'none')
      ) {
        await fetch(`${API_BASE}/api/report/${ts}/generate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ autoFinalize: false, soft: true }),
        });
        statusJson = await readStatus();
      }
      if (statusJson?.success && statusJson.data) {
        const pub = statusJson.data.publicationStatus === 'published';
        setReportPublished(pub);
        setReportModulesLoading(!pub);
      } else {
        setReportPublished(false);
        setReportModulesLoading(true);
      }
    } catch {
      setReportPublished(false);
      setReportModulesLoading(true);
    }
  };

  const confirmFinish = async () => {
    setFinalizing(true);
    try {
      await finalizeTraining();
      setShowFinishConfirm(false);
      onFinish();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setPlaybackNotice(message);
      alert(message);
    } finally {
      setFinalizing(false);
    }
  };

  const handleViewReport = async () => {
    if (!reportPublished) return;
    setFinalizing(true);
    try {
      await waitForRecentGameEnd();
      const ts = await finalizeTraining();
      if (!ts) {
        alert('无法获取训练会话ID，请确认本轮已开始上课');
        return;
      }
      setShowFinishConfirm(false);
      if (onViewReport) {
        onViewReport(ts);
      } else {
        onFinish();
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setPlaybackNotice(message);
      alert(message);
    } finally {
      setFinalizing(false);
    }
  };

  // 课程完成弹窗打开时：立即结束训练并探测审核/推送态（不等待按钮）
  useEffect(() => {
    if (isPreviewMode) return;
    if (!showFinishConfirm) return;
    let cancelled = false;
    setReportModulesLoading(true);
    setReportPublished(false);

    (async () => {
      try {
        const ts = await finalizeTraining();
        if (cancelled) return;
        const id = ts || trainingSessionIdRef.current;
        if (id) await probeReportStatus(id, true);
      } catch (e) {
        console.warn('课程完成自动结束失败:', e);
      }
    })();

    const t = window.setInterval(() => {
      const id = trainingSessionIdRef.current;
      if (id) probeReportStatus(id);
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [finalizeTraining, isPreviewMode, showFinishConfirm]);

  // 监听服务端推送
  useEffect(() => {
    if (!showFinishConfirm) return;
    const socket = socketRef.current;
    if (!socket) return;
    const onPublished = (payload: any) => {
      const id = normalizeId(payload?.trainingSessionId);
      const activeId = normalizeId(trainingSessionIdRef.current);
      if (!id || !activeId || id !== activeId) return;
      setReportPublished(true);
      setReportModulesLoading(false);
    };
    socket.on('report_published', onPublished);
    return () => {
      socket.off('report_published', onPublished);
    };
  }, [showFinishConfirm, trainingSessionId, socketConnected]);

  // 获取图片路径
  const getImageUrl = (path?: string) => {
    if (!path) return DEFAULT_ITEM_IMAGE;
    if (path.startsWith('http://') || path.startsWith('https://')) {
      return path;
    }
    return `/static/${path}`;
  };

  // 计算总进度（所有子项的总数）
  const getTotalProgress = () => {
    const totalItems = selectedCourseItems.reduce((sum, item) => sum + item.items.length, 0);
    let currentProgress = 0;
    for (let i = 0; i < currentCourseIndex; i++) {
      currentProgress += selectedCourseItems[i].items.length;
    }
    currentProgress += currentItemIndex + 1;
    return { current: currentProgress, total: totalItems };
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-indigo-50 to-blue-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600 mx-auto mb-4"></div>
          <p className="text-gray-600">加载课程数据中...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-indigo-50 to-blue-50 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-600 mb-4">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700"
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  if (selectedCourseItems.length === 0) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-indigo-50 to-blue-50 flex items-center justify-center">
        <div className="text-center">
          <p className="text-gray-600 mb-4">未找到选中的课程</p>
          <button
            onClick={onBack}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700"
          >
            返回选课
          </button>
        </div>
      </div>
    );
  }

  const progress = getTotalProgress();
  const retryControlsLocked =
    playbackPhase !== 'idle' ||
    audioStatus.isPlaying ||
    awaitingResourceReady ||
    !socketConnected;
  const interactionControlsLocked =
    retryControlsLocked || hasFailedPlayback || controlRole === 'observer';
  const commandControlsLocked =
    !socketConnected || hasFailedPlayback || controlRole === 'observer';

  return (
    <div className="bg-gradient-to-br from-indigo-50 to-blue-50 flex h-screen overflow-hidden">
      {/* 左侧课程列表 */}
      <div className="w-96 bg-white border-r border-gray-200 flex flex-col h-full">
        <div className="flex items-center gap-2 mb-6">
          <button
            onClick={handleBackClick}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <ArrowLeft className="w-5 h-5 text-gray-600" />
          </button>
          <h2 className="text-gray-900">课程列表</h2>
        </div>
        
        {/* Socket 连接状态指示器 */}
        <div className="mb-4 p-3 rounded-lg bg-gray-50 border border-gray-200">
          <div className="flex items-center gap-2">
            <div className={`w-3 h-3 rounded-full ${socketConnected ? 'bg-green-500' : 'bg-red-500'} animate-pulse`} />
            <span className="text-sm text-gray-700">
              {socketConnected ? '已连接' : '未连接'}
            </span>
            {socketRef.current && (
              <span className="text-xs text-gray-500 ml-2">
                ({socketRef.current.id || '连接中...'})
              </span>
            )}
          </div>
          {socketConnected && (
            <div className="mt-1 text-xs text-gray-500">
              网络 {teacherLatencyMs == null ? '--' : `${teacherLatencyMs} ms`}
              {behaviorSyncDeltaMs != null ? ` · 同步差 ${behaviorSyncDeltaMs} ms` : ''}
            </div>
          )}
          {!socketConnected && (
            <p className="text-xs text-red-600 mt-1">
              请检查网络连接或刷新页面
            </p>
          )}
          {controlRole === 'observer' && (
            <div className="mt-1 flex items-center gap-2">
              <p className="text-xs font-medium text-amber-700">
                当前课堂由另一位教师主控，本窗口为只读观察模式
              </p>
              <button
                type="button"
                onClick={claimTeacherControl}
                disabled={claimingControl || !socketConnected}
                className="shrink-0 rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800 hover:bg-amber-200 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {claimingControl ? '正在接管…' : '接管控制'}
              </button>
              {claimingControlNotice && (
                <span className="text-xs text-amber-600">{claimingControlNotice}</span>
              )}
            </div>
          )}
          {playbackPhase !== 'idle' && (
            <p className="text-xs text-indigo-600 mt-1">
              {playbackPhase === 'pending' ? '正在确认操作…' : '正在完整播放本次交互…'}
            </p>
          )}
          {awaitingResourceReady && playbackPhase === 'idle' && (
            <p className="text-xs text-indigo-600 mt-1">
              正在等待儿童端画面就绪…
            </p>
          )}
          {(playbackNotice || hasFailedPlayback) && (
            <div className="mt-1 flex items-center gap-2">
              <span className="text-left text-xs text-amber-700">
                {playbackNotice || '播放未完成，请重试；儿童端将继续保留上一帧'}
              </span>
              {hasFailedPlayback && (
                <button
                  type="button"
                  onClick={retryFailedPlayback}
                  disabled={retryControlsLocked}
                  className="shrink-0 rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800 hover:bg-amber-200 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  重试
                </button>
              )}
              {!hasFailedPlayback && playbackPhase === 'idle' && (
                <button
                  type="button"
                  onClick={() => setPlaybackNotice(null)}
                  className="text-xs text-amber-600 hover:text-amber-900"
                  aria-label="关闭提示"
                >
                  ×
                </button>
              )}
            </div>
          )}
        </div>
        
        <div className="mb-3 grid grid-cols-1 gap-2 xl:grid-cols-2" aria-label="课堂快捷控制">
          <section
            className="rounded-lg border border-slate-200 bg-slate-50 p-2"
            aria-label="全局注意力支持"
          >
          <div>
            <button
              type="button"
              onClick={handleAttention}
              disabled={commandControlsLocked}
              className="inline-flex h-8 items-center justify-center gap-1 rounded-md bg-violet-600 px-2 text-xs font-semibold text-white shadow-sm hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Target className="h-4 w-4" />
              吸引
            </button>
            <button
              type="button"
              onClick={handleAttentionReward}
              disabled={commandControlsLocked}
              className="inline-flex h-8 items-center justify-center gap-1 rounded-md bg-rose-500 px-2 text-xs font-semibold text-white shadow-sm hover:bg-rose-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Award className="h-4 w-4" />
              夸奖
            </button>
          </div>
          <button
            type="button"
            onClick={() => setEngagementSettingsOpen(true)}
            className="mt-1 flex h-6 w-full items-center justify-between rounded px-1.5 text-[11px] text-slate-500 hover:bg-white hover:text-slate-800"
          >
            <span>个性化配置</span>
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
          </section>

          <div className="rounded-lg border border-sky-200 bg-sky-50 p-2">
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-sky-900">儿童端智能体</span>
            <span className={`text-[11px] ${dialogueAwake ? 'text-green-700' : 'text-slate-500'}`}>
              {dialogueAwake ? '已唤醒' : '持续聆听中'}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            <button
              type="button"
              onClick={toggleDialogueAgent}
              disabled={dialogueControlBusy || !socketConnected || !currentSessionId}
              className={`h-8 rounded-md px-2 text-xs text-white disabled:cursor-not-allowed disabled:opacity-50 ${
                dialogueAwake ? 'bg-rose-600 hover:bg-rose-700' : 'bg-sky-600 hover:bg-sky-700'
              }`}
            >
              {dialogueAwake ? '停止智能体' : '唤醒智能体'}
            </button>
          </div>
          <p className="mt-1.5 text-[11px] leading-4 text-sky-700">
            {dialogueControlNotice || '点击唤醒会静默进入与唤醒词相同的对话状态；停止会中断回复，但儿童端继续聆听。'}
          </p>
          </div>
        </div>

        {/* 音频控制面板 */}
        {audioStatus.isPlaying && (
          <div className="mb-4 p-3 rounded-lg bg-gradient-to-r from-purple-50 to-pink-50 border border-purple-200">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full bg-purple-500 animate-pulse" />
                <span className="text-sm font-medium text-purple-900">正在播放音频</span>
              </div>
              <button
                onClick={handleStopAudio}
                className="px-3 py-1 bg-red-500 hover:bg-red-600 text-white text-sm rounded-lg transition-all shadow-sm"
              >
                ⏹️ 停止
              </button>
            </div>
            {audioStatus.entryId && (
              <div className="text-xs text-purple-700 mb-1">
                {audioStatus.entryId}
              </div>
            )}
            {audioStatus.progress > 0 && (
              <div className="w-full bg-purple-200 rounded-full h-1.5">
                <div
                  className="bg-purple-600 h-1.5 rounded-full transition-all duration-300"
                  style={{ width: `${audioStatus.progress}%` }}
                />
              </div>
            )}
          </div>
        )}
        
        <div className="flex-1 overflow-y-auto p-6 pt-4">
          <div className="space-y-2">
          {Object.entries(coursesByCategory).map(([categoryId, selectedItems]) => {
            const typeInfo = courseTypeMap[categoryId] || { name: categoryId, icon: DefaultIcon };
            const Icon = typeInfo.icon;
            const isExpanded = expandedCategories.has(categoryId);
            const isCategoryActive = currentCourse?.type === categoryId;

            return (
              <div key={categoryId}>
                {/* 类别标题 */}
                <button
                  onClick={() => toggleCategory(categoryId)}
                  className={`w-full flex items-center gap-3 p-3 rounded-lg transition-all ${
                    isCategoryActive
                      ? 'bg-indigo-50 border-2 border-indigo-300'
                      : 'bg-gray-50 border-2 border-transparent hover:bg-gray-100'
                  }`}
                >
                  <div className="flex-shrink-0">
                    {isExpanded ? (
                      <ChevronDown className="w-5 h-5 text-gray-600" />
                    ) : (
                      <ChevronRight className="w-5 h-5 text-gray-600" />
                    )}
                  </div>
                  <Icon className={`w-5 h-5 ${isCategoryActive ? 'text-indigo-600' : 'text-gray-600'}`} />
                  <span className="text-gray-900 flex-1 text-left">{typeInfo.name}</span>
                  <span className="text-gray-500">({selectedItems.length})</span>
                </button>

                {/* 展开的课程列表 */}
                {isExpanded && (
                  <div className="ml-8 mt-2 space-y-2">
                    {selectedItems.map((selectedItem) => {
                      // 社交课会把打招呼/再见拆成同 courseId 的多条序列；必须用引用定位，
                      // 不能 findIndex(courseId)，否则再见永远撞到打招呼那条。
                      const courseIndex = selectedCourseItems.indexOf(selectedItem);
                      const isActive = courseIndex === currentCourseIndex;
                      const course = selectedItem.course;
                      const sequenceLabel =
                        course.type === 'social' && selectedItem.items.length === 1
                          ? selectedItem.items[0].name
                          : course.title;
                      const sequenceKey = `${selectedItem.courseId}:${selectedItem.itemIds.join(',')}`;
                      // 优先使用服务端返回的真实图片路径（随机选择后的），其次使用icon/file
                      const courseImage = (isActive && currentResolvedFile) 
                        ? currentResolvedFile 
                        : (course.icon || course.file || getImageUrl(selectedItem.items[0]?.icon || selectedItem.items[0]?.file));

                      return (
                        <div key={sequenceKey}>
                          {/* 课程按钮 */}
                          <button
                            onClick={() => handleJumpToCourse(courseIndex)}
                            disabled={interactionControlsLocked}
                            className={`w-full flex items-center gap-3 p-3 rounded-lg transition-all relative overflow-hidden ${
                              isActive
                                ? 'bg-indigo-600 text-white shadow-lg'
                                : 'bg-white border border-gray-200 hover:border-indigo-300 text-gray-900'
                            } ${interactionControlsLocked ? 'opacity-60 cursor-not-allowed' : ''}`}
                          >
                            {/* 流动光效 */}
                            {isActive && (
                              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent animate-shimmer" 
                                   style={{
                                     backgroundSize: '200% 100%',
                                     animation: 'shimmer 2s infinite'
                                   }}
                              />
                            )}
                            
                            <img
                              src={getImageUrl(courseImage)}
                              alt={sequenceLabel}
                              className="w-12 h-12 rounded object-cover relative z-10"
                              onError={(e) => {
                                (e.target as HTMLImageElement).src = DEFAULT_ITEM_IMAGE;
                              }}
                            />
                            <div className="flex-1 text-left relative z-10">
                              <div className={isActive ? 'text-white' : 'text-gray-900'}>
                                {sequenceLabel}
                              </div>
                              {isActive && (
                                <div className="text-indigo-200 text-sm">
                                  {currentItem?.name || '正在播放'}
                                </div>
                              )}
                            </div>
                          </button>

                          {/* 当前课程的子项列表 */}
                          {isActive && selectedItem.items.length > 0 && (
                            <div className="ml-4 mt-2 space-y-1">
                              {selectedItem.items.map((item, itemIdx) => {
                                const isItemActive = itemIdx === currentItemIndex;
                                return (
                                  <button
                                    key={item.id}
                                    onClick={() => handleJumpToItem(courseIndex, itemIdx)}
                                    disabled={interactionControlsLocked}
                                    className={`w-full flex items-center gap-2 p-2 rounded-lg transition-all text-sm ${
                                      isItemActive
                                        ? 'bg-indigo-100 text-indigo-700 font-medium'
                                        : 'bg-gray-50 text-gray-700 hover:bg-gray-100'
                                    } ${interactionControlsLocked ? 'opacity-60 cursor-not-allowed' : ''}`}
                                  >
                                    <div className={`w-2 h-2 rounded-full ${isItemActive ? 'bg-indigo-600' : 'bg-gray-300'}`} />
                                    <span className="flex-1 text-left">{item.name}</span>
                                  </button>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
          </div>
        </div>
      </div>

      {/* 右侧控制区域 */}
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        {/* 顶部分析结果显示区域 */}
        <div className="flex-shrink-0 p-4 border-b border-gray-200 bg-white/50">
          <div className="flex items-center justify-center gap-6">
            {/* 匹配分数卡片 */}
            <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-200 min-w-[180px]">
              <div className="flex items-center gap-2 mb-2">
                <Target className="w-5 h-5 text-indigo-600" />
                <span className="text-sm text-gray-600">匹配分数</span>
              </div>
              <div className="flex items-end gap-2">
                <span className={`text-3xl font-bold ${
                  matchScore === null ? 'text-gray-300' : 
                  matchPassed ? 'text-green-600' : 
                  (matchScore ?? 0) > 70 ? 'text-yellow-600' : 'text-red-500'
                }`}>
                  {matchScore !== null ? `${matchScore.toFixed(0)}%` : '--'}
                </span>
                {matchType && (
                  <span className="text-xs text-gray-400 mb-1">{matchType}</span>
                )}
              </div>
              {matchPassed && (
                <div className="mt-1 text-xs text-green-600 font-medium">✓ 达标</div>
              )}
            </div>
            
            {/* 注意力分数卡片 */}
            <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-200 min-w-[180px]">
              <div className="flex items-center gap-2 mb-2">
                <Eye className="w-5 h-5 text-purple-600" />
                <span className="text-sm text-gray-600">注意力</span>
              </div>
              <div className="flex items-end gap-2">
                <span className={`text-3xl font-bold ${
                  attentionScore === null ? 'text-gray-300' :
                  attentionState === 'missing' ? 'text-slate-400' :
                  attentionState === 'high' ? 'text-green-600' :
                  attentionState === 'medium' ? 'text-yellow-600' : 'text-red-500'
                }`}>
                  {attentionScore !== null ? `${attentionScore.toFixed(0)}%` : '--'}
                </span>
              </div>
              {attentionState === 'missing' && (
                <div className="mt-0.5 text-[10px] text-slate-400">未检测到人脸 / 无有效样本</div>
              )}
              <div className="mt-1 flex items-center gap-2">
                <span className={`text-xs px-2 py-0.5 rounded ${
                  attentionState === 'high' ? 'bg-green-100 text-green-700' :
                  attentionState === 'medium' ? 'bg-yellow-100 text-yellow-700' :
                  attentionState === 'missing' ? 'bg-slate-100 text-slate-600' :
                  attentionState === 'low' ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-600'
                }`}>
                  {attentionState === 'high' ? '专注' : 
                   attentionState === 'medium' ? '一般' : 
                   attentionState === 'missing' ? '无有效样本' :
                   attentionState === 'low' ? '分散' : '未知'}
                </span>
                <span className="text-xs text-gray-400">
                  {attentionTrend === 'increasing' ? '↑' : 
                   attentionTrend === 'decreasing' ? '↓' : '→'}
                </span>
              </div>
            </div>
            
            {/* 实时状态指示器 */}
            <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-200 min-w-[120px]">
              <div className="flex items-center gap-2 mb-2">
                <BarChart3 className="w-5 h-5 text-blue-600" />
                <span className="text-sm text-gray-600">分析状态</span>
              </div>
              <div className="flex items-center gap-2">
                <div className={`w-3 h-3 rounded-full ${
                  socketConnected ? 'bg-green-500 animate-pulse' : 'bg-gray-300'
                }`} />
                <span className="text-sm text-gray-700">
                  {socketConnected ? '实时分析中' : '未连接'}
                </span>
              </div>
            </div>
          </div>
        </div>
        
        {/* 中央可滚动区域 */}
        <div className="flex-1 overflow-y-auto">
          {/* 排序课程专用控制面板 */}
          {currentCourse?.type === 'ordering' && (
            <div className="bg-white rounded-2xl p-4 sm:p-5 mx-4 sm:mx-6 mt-6 shadow-lg border border-gray-200">
            {/* 第一行：配置区 */}
            <div className="mb-4 flex flex-wrap items-center justify-center gap-4 2xl:justify-start">
              {/* 自动开关 */}
              <div className="flex shrink-0 items-center gap-2">
                <span className="whitespace-nowrap text-xs font-medium text-gray-500">自动模式</span>
                <button
                  onClick={() => handleSequencingAutoModeChange(!sequencingConfig.autoMode)}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                    sequencingConfig.autoMode ? 'bg-indigo-600' : 'bg-gray-300'
                  }`}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                      sequencingConfig.autoMode ? 'translate-x-6' : 'translate-x-1'
                    }`}
                  />
                </button>
                <span className="whitespace-nowrap text-xs text-gray-500">
                  {sequencingConfig.autoMode ? '开启' : '关闭'}
                </span>
              </div>
              
              {/* 类别选择器 */}
              <div className="flex min-w-0 flex-wrap items-center justify-center gap-2">
                <span className="shrink-0 whitespace-nowrap text-xs font-medium text-gray-500">下一题类别</span>
                <div className="flex flex-wrap justify-center gap-2">
                  {[
                    { value: 'size', label: '大小' },
                    { value: 'length', label: '长短' },
                    { value: 'height', label: '高矮' },
                    { value: 'count', label: '多少' }
                  ].map((cat) => (
                    <button
                      key={cat.value}
                      onClick={() => handleSequencingConfigChange('category', cat.value)}
                      disabled={sequencingConfig.autoMode}
                      className={`min-w-[3.5rem] whitespace-nowrap rounded-lg px-3 py-2 text-sm font-semibold transition-all ${
                        sequencingConfig.category === cat.value
                          ? 'bg-indigo-600 text-white shadow-md ring-2 ring-indigo-200'
                          : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                      } ${sequencingConfig.autoMode ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                      {cat.label}
                    </button>
                  ))}
                </div>
              </div>
              
              {/* 难度选择器（禁用） */}
              <div className="flex min-w-0 flex-wrap items-center justify-center gap-2">
                <span className="shrink-0 whitespace-nowrap text-xs font-medium text-gray-500">难度</span>
                <div className="flex flex-wrap justify-center gap-2">
                  {[
                    { value: 2, label: '两者' },
                    { value: 3, label: '三者', disabled: true },
                    { value: 4, label: '四者', disabled: true }
                  ].map((diff) => (
                    <button
                      key={diff.value}
                      disabled={true}
                      className={`min-w-[3.5rem] whitespace-nowrap rounded-lg px-3 py-2 text-sm font-semibold transition-all ${
                        sequencingConfig.difficulty === diff.value
                          ? 'bg-indigo-600 text-white shadow-md'
                          : 'bg-gray-100 text-gray-700'
                      } opacity-50 cursor-not-allowed`}
                    >
                      {diff.label}
                    </button>
                  ))}
                </div>
              </div>
              
              {/* 规则选择器 */}
              <div className="flex min-w-0 flex-wrap items-center justify-center gap-2">
                <span className="shrink-0 whitespace-nowrap text-xs font-medium text-gray-500">下一题规则</span>
                <div className="flex flex-wrap justify-center gap-2">
                  {(() => {
                    const ruleMap: Record<string, Array<{value: string, label: string}>> = {
                      size: [{ value: 'bigger', label: '选大的' }, { value: 'smaller', label: '选小的' }],
                      length: [{ value: 'longer', label: '选长的' }, { value: 'shorter', label: '选短的' }],
                      height: [{ value: 'taller', label: '选高的' }, { value: 'shorter', label: '选矮的' }],
                      count: [{ value: 'more', label: '选多的' }, { value: 'less', label: '选少的' }]
                    };
                    const rules = ruleMap[sequencingConfig.category] || ruleMap.size;
                    return rules.map((rule) => (
                      <button
                        key={rule.value}
                        onClick={() => handleSequencingConfigChange('rule', rule.value)}
                        disabled={sequencingConfig.autoMode}
                        className={`min-w-[4.25rem] whitespace-nowrap rounded-lg px-3 py-2 text-sm font-semibold transition-all ${
                          sequencingConfig.rule === rule.value
                            ? 'bg-indigo-600 text-white shadow-md ring-2 ring-indigo-200'
                            : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                        } ${sequencingConfig.autoMode ? 'opacity-50 cursor-not-allowed' : ''}`}
                      >
                        {rule.label}
                      </button>
                    ));
                  })()}
                </div>
              </div>
            </div>
            
            {/* 第二行：状态 + 统计区 */}
            <div className="flex flex-wrap items-center gap-4 border-t border-gray-100 pt-4">
              {/* 游戏状态指示 */}
              {sequencingGameStarted && (
                <div className="flex flex-[1_1_140px] items-center justify-center gap-2 2xl:justify-start">
                  <div className="flex shrink-0 items-center gap-2">
                    <div className="h-2 w-2 shrink-0 rounded-full bg-green-500 animate-pulse"></div>
                    <span className="whitespace-nowrap text-xs font-medium text-green-700">游戏进行中</span>
                  </div>
                </div>
              )}

              {/* 统计数据：无背景，仅以文字层级呈现 */}
              <div className="grid min-w-0 flex-[1_1_620px] grid-cols-2 gap-x-3 gap-y-4 sm:grid-cols-3 lg:grid-cols-5">
                {[
                  { key: 'size', label: '大小' },
                  { key: 'length', label: '长短' },
                  { key: 'height', label: '高矮' },
                  { key: 'count', label: '多少' }
                ].map((cat) => {
                  const stats = sequencingStats[cat.key as keyof typeof sequencingStats];
                  const total = stats.correct + stats.wrong;
                  const accuracy = total > 0 ? Math.round((stats.correct / total) * 100) : null;
                  return (
                    <div key={cat.key} className="min-w-0 text-center">
                      <div className={`whitespace-nowrap text-2xl font-bold ${
                        accuracy == null ? 'text-gray-400' :
                        accuracy >= 80 ? 'text-green-600' :
                        accuracy >= 60 ? 'text-amber-600' : 'text-red-500'
                      }`}>
                        {accuracy == null ? '--' : `${accuracy}%`}
                      </div>
                      <div className="mt-0.5 whitespace-nowrap text-[11px] text-gray-500">{cat.label}</div>
                    </div>
                  );
                })}

                {/* 当前进度 */}
                {sequencingStatus && (
                  <div className="col-span-2 min-w-0 text-center sm:col-span-1">
                    <div className="whitespace-nowrap text-2xl font-bold text-indigo-600">
                      {sequencingStatus.currentQuestion}/{sequencingStatus.totalQuestions}
                    </div>
                    <div className="mt-0.5 whitespace-nowrap text-[11px] font-medium text-gray-600">当前进度</div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
        
        {/* 配对课程专用控制面板 */}
        {currentCourse?.type === 'pairing' && (
          <div className="bg-white rounded-2xl p-4 sm:p-5 mx-4 sm:mx-6 mt-6 shadow-lg border border-gray-200">
            <div className="flex flex-wrap items-center gap-4 xl:gap-5">
              {/* 难度控制：空间不足时整组换行，避免文字被逐字挤压 */}
              <div className="flex min-w-0 flex-[1_1_390px] flex-wrap items-center justify-center gap-3 2xl:justify-start">
                <div className="flex min-w-0 flex-wrap items-center justify-center gap-2 2xl:justify-start">
                  <span className="shrink-0 whitespace-nowrap text-xs font-medium text-gray-500">难度设置</span>
                  <div className="flex flex-wrap gap-2">
                    {[2, 3, 4, 5].map((level) => (
                      <button
                        key={level}
                        onClick={() => handleSetMatchingDifficulty(level)}
                        className={`min-w-[3.5rem] whitespace-nowrap rounded-lg px-3 py-2 text-sm font-semibold transition-all ${
                          matchingDifficulty === level
                            ? 'bg-indigo-600 text-white shadow-md ring-2 ring-indigo-200'
                            : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                        }`}
                      >
                        {level}选1
                      </button>
                    ))}
                  </div>
                </div>
                
                {/* 游戏状态指示 */}
                {matchingGameStarted && (
                  <div className="flex shrink-0 items-center gap-2 rounded-lg border border-green-200 bg-green-50 px-3 py-2">
                    <div className="h-2 w-2 shrink-0 rounded-full bg-green-500 animate-pulse"></div>
                    <span className="whitespace-nowrap text-xs font-medium text-green-700">游戏进行中</span>
                  </div>
                )}
              </div>

              {/* 课堂数据：采用响应式网格，标签始终保持横向完整显示 */}
              {matchingStatus && (
                <div className="grid min-w-0 flex-[1_1_420px] grid-cols-2 gap-2 sm:grid-cols-3">
                  <div className="min-w-0 px-2 py-2 text-center">
                    <div className="whitespace-nowrap text-2xl font-bold text-indigo-600">
                      {matchingStatus.currentQuestion}/{matchingStatus.totalQuestions}
                    </div>
                    <div className="mt-0.5 whitespace-nowrap text-[11px] text-gray-500">题目进度</div>
                  </div>
                  <div className="min-w-0 px-2 py-2 text-center">
                    <div className={`whitespace-nowrap text-xl font-bold ${
                      matchingStatus.isSimplifiedMode ? 'text-orange-500' : 'text-gray-600'
                    }`}>
                      {matchingStatus.currentDifficulty}选1
                      {matchingStatus.isSimplifiedMode && (
                        <span className="ml-1 text-[10px]">(简化)</span>
                      )}
                    </div>
                    <div className="mt-0.5 whitespace-nowrap text-[11px] text-gray-500">当前难度</div>
                  </div>
                  <div className="col-span-2 min-w-0 px-2 py-2 text-center sm:col-span-1">
                    <div className={`whitespace-nowrap text-3xl font-bold ${
                      matchingStatus.currentQuestion <= 0 ? 'text-gray-400' :
                      (matchingStatus.correctCount / matchingStatus.currentQuestion) >= 0.8 ? 'text-green-600' :
                      (matchingStatus.correctCount / matchingStatus.currentQuestion) >= 0.6 ? 'text-amber-600' : 'text-red-500'
                    }`}>
                      {matchingStatus.currentQuestion > 0
                        ? `${((matchingStatus.correctCount / matchingStatus.currentQuestion) * 100).toFixed(0)}%`
                        : '--'}
                    </div>
                    <div className="mt-0.5 whitespace-nowrap text-[11px] font-medium text-gray-600">正确率</div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* 中央控制按钮 */}
        <div className="flex items-center justify-center min-h-[400px] py-8">
          <div className="grid grid-cols-2 gap-6">
            {getSocialRole(currentItem) === 'greeting' ? (
              <>
                <button
                  onClick={() => handleSocialVoice('socialGreetingIntro')}
                  disabled={commandControlsLocked}
                  className="flex flex-col items-center justify-center w-48 h-48 bg-sky-500 hover:bg-sky-600 text-white rounded-3xl shadow-2xl transition-all hover:scale-105 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
                >
                  <Users className="w-16 h-16 mb-4" />
                  <span className="text-2xl text-center px-2">初见打招呼</span>
                </button>
                <button
                  onClick={() => handleSocialVoice('socialGreetingPlay')}
                  disabled={commandControlsLocked}
                  className="flex flex-col items-center justify-center w-48 h-48 bg-teal-500 hover:bg-teal-600 text-white rounded-3xl shadow-2xl transition-all hover:scale-105 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
                >
                  <Award className="w-16 h-16 mb-4" />
                  <span className="text-2xl text-center px-2">一起玩耍吧</span>
                </button>
              </>
            ) : getSocialRole(currentItem) === 'farewell' ? (
              <>
                <button
                  onClick={() => handleSocialVoice('socialFarewellBye')}
                  disabled={commandControlsLocked}
                  className="flex flex-col items-center justify-center w-48 h-48 bg-sky-500 hover:bg-sky-600 text-white rounded-3xl shadow-2xl transition-all hover:scale-105 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
                >
                  <Users className="w-16 h-16 mb-4" />
                  <span className="text-2xl">再见</span>
                </button>
                <button
                  onClick={() => handleSocialVoice('socialFarewellReply')}
                  disabled={commandControlsLocked}
                  className="flex flex-col items-center justify-center w-48 h-48 bg-teal-500 hover:bg-teal-600 text-white rounded-3xl shadow-2xl transition-all hover:scale-105 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
                >
                  <Award className="w-16 h-16 mb-4" />
                  <span className="text-2xl">回应</span>
                </button>
              </>
            ) : (
              <>
                {currentCourse?.type === 'pairing' || currentCourse?.type === 'ordering' ? (
                  <button
                    onClick={handleInteractiveNextQuestion}
                    disabled={commandControlsLocked || interactiveNextPending}
                    className="flex flex-col items-center justify-center w-48 h-48 bg-sky-600 hover:bg-sky-700 text-white rounded-3xl shadow-2xl transition-transform duration-150 ease-out active:scale-[0.97] disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <ArrowRight className="w-16 h-16 mb-4" />
                    <span className="text-2xl">{interactiveNextPending ? '切题中…' : '下一题'}</span>
                  </button>
                ) : (
                  <button
                    onClick={() => playCurrentItem({ question: true })}
                    disabled={commandControlsLocked}
                    className="flex flex-col items-center justify-center w-48 h-48 bg-yellow-500 hover:bg-yellow-600 text-white rounded-3xl shadow-2xl transition-all hover:scale-105 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
                  >
                    <Lightbulb className="w-16 h-16 mb-4" />
                    <span className="text-2xl">提问</span>
                  </button>
                )}

                {/* 提示按钮 */}
                <button
                  onClick={handleHint}
                  disabled={commandControlsLocked}
                  className="flex flex-col items-center justify-center w-48 h-48 bg-orange-500 hover:bg-orange-600 text-white rounded-3xl shadow-2xl transition-all hover:scale-105 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
                >
                  <HelpCircle className="w-16 h-16 mb-4" />
                  <span className="text-2xl">提示</span>
                </button>

                {/* 表扬按钮 */}
                <button
                  onClick={handlePraise}
                  disabled={commandControlsLocked}
                  className="flex flex-col items-center justify-center w-48 h-48 bg-green-500 hover:bg-green-600 text-white rounded-3xl shadow-2xl transition-all hover:scale-105 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
                >
                  <Award className="w-16 h-16 mb-4" />
                  <span className="text-2xl">表扬</span>
                </button>
              </>
            )}

            {/* 下一个按钮（社交课点也保留） */}
            <button
              onClick={() => requestAdvance('manual')}
              disabled={interactionControlsLocked || advanceLockRef.current}
              className="flex flex-col items-center justify-center w-48 h-48 bg-indigo-600 hover:bg-indigo-700 text-white rounded-3xl shadow-2xl transition-all hover:scale-105 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
            >
              <ArrowRight className="w-16 h-16 mb-4" />
              <span className="text-2xl">下一个</span>
            </button>
          </div>
        </div>

        {/* 底部进度信息 */}
        <div className="p-6 text-center">
          <div className="inline-block bg-white px-6 py-3 rounded-xl shadow-sm">
            <p className="text-gray-600">
              当前进度：<span className="text-indigo-600">{progress.current}/{progress.total}</span>
            </p>
            {currentCourse && currentItem && (
              <p className="text-gray-500 text-sm mt-1">
                {currentCourse.title} - {currentItem.name}
              </p>
            )}
          </div>
        </div>
        </div>
      </div>

      {/* 返回确认弹窗 */}
      <TeacherRatingDialog
        open={pendingAdvance != null}
        courseName={pendingAdvance?.courseName || ''}
        itemName={pendingAdvance?.itemName || ''}
        selectedRating={selectedRating}
        saving={ratingSaving}
        error={ratingError}
        onSelect={(rating) => {
          setSelectedRating(rating);
          setRatingError(null);
        }}
        onCancel={cancelTeacherRating}
        onConfirm={submitTeacherRating}
      />

      {engagementSettingsOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="engagement-settings-title"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) setEngagementSettingsOpen(false);
          }}
        >
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 id="engagement-settings-title" className="text-lg font-semibold text-slate-900">
                  吸引与夸奖设置
                </h3>
                <p className="mt-1 text-sm leading-6 text-slate-500">
                  吸引使用 Server 端预设；夸奖可为当前儿童单独选择下屏动画。
                </p>
              </div>
              <button
                type="button"
                onClick={() => setEngagementSettingsOpen(false)}
                className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                aria-label="关闭个性化配置"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <label htmlFor="reward-animation" className="mt-6 block text-sm font-medium text-slate-700">
              夸奖下屏动画
              <select
                id="reward-animation"
                value={rewardAnimation}
                onChange={(event) => handleRewardAnimationChange(event.target.value)}
                className="mt-2 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-rose-400 focus:ring-2 focus:ring-rose-100"
              >
                <option value="">使用 Server 默认</option>
                {engagementAnimations.map((item) => (
                  <option key={item.name} value={item.name}>{item.name}</option>
                ))}
              </select>
            </label>

            <div className="mt-6 flex justify-end">
              <button
                type="button"
                onClick={() => setEngagementSettingsOpen(false)}
                className="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-700"
              >
                完成
              </button>
            </div>
          </div>
        </div>
      )}

      {showBackConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-8 max-w-md w-full mx-4 shadow-2xl">
            <h3 className="text-gray-900 mb-4">确认返回</h3>
            <p className="text-gray-600 mb-6">确定返回到选课界面吗？</p>
            <div className="flex gap-4">
              <button
                onClick={() => setShowBackConfirm(false)}
                className="flex-1 px-6 py-3 bg-gray-200 hover:bg-gray-300 text-gray-900 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={confirmBack}
                className="flex-1 px-6 py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition-colors"
              >
                确定
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 完成确认弹窗 */}
      {showFinishConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-8 max-w-md w-full mx-4 shadow-2xl">
            <h3 className="text-gray-900 mb-4">课程完成</h3>
            <p className="text-gray-600 mb-6">
              课程内容已全部完成，训练已结束。可等待服务端推送后查看报告，或返回学生列表。
            </p>
            <div className="flex flex-col gap-3">
              <button
                onClick={handleViewReport}
                disabled={finalizing || !reportPublished}
                className="w-full px-6 py-3 bg-sky-600 hover:bg-sky-700 disabled:opacity-60 text-white rounded-lg transition-colors"
              >
                {finalizing
                  ? '正在整理数据…'
                  : reportPublished
                    ? '查看报告'
                    : '查看报告（正在处理中）'}
              </button>
              <button
                onClick={confirmFinish}
                disabled={finalizing}
                className="w-full px-6 py-3 bg-green-600 hover:bg-green-700 disabled:opacity-60 text-white rounded-lg transition-colors"
              >
                返回学生列表
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 录制被控制台强制关闭提示 */}
      {forcedStopInfo && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" role="dialog" aria-modal="true">
          <div className="bg-white rounded-2xl p-8 max-w-lg w-full mx-4 shadow-2xl">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-xl font-semibold text-gray-900">录制已被强制关闭</h3>
            </div>
            <div className="space-y-3 text-sm text-gray-600">
              <p>控制台已结束本场录制{forcedStopInfo.humanDirName ? `（${forcedStopInfo.humanDirName}）` : ''}，当前课程无法继续记录数据。</p>
              <p>请重新选择角色和课程以开始新的训练。</p>
              {forcedStopInfo.trainingSessionId && (
                <p className="text-xs text-gray-400">训练：<code>{forcedStopInfo.trainingSessionId}</code></p>
              )}
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => {
                  setForcedStopInfo(null);
                  window.dispatchEvent(new CustomEvent('recording:forced-stop-restart'));
                }}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700"
              >
                重新选择角色和课程
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 会话总结弹窗 */}
      {showSummaryModal && sessionSummary && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-8 max-w-lg w-full mx-4 shadow-2xl">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-xl font-semibold text-gray-900">会话分析总结</h3>
              <button
                onClick={() => setShowSummaryModal(false)}
                className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>
            
            <div className="space-y-4">
              {/* 基本统计 */}
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-indigo-50 rounded-lg p-4">
                  <div className="text-sm text-indigo-600 mb-1">会话时长</div>
                  <div className="text-2xl font-bold text-indigo-900">
                    {Math.round(sessionSummary.summary.duration)}秒
                  </div>
                </div>
                <div className="bg-green-50 rounded-lg p-4">
                  <div className="text-sm text-green-600 mb-1">视频帧数</div>
                  <div className="text-2xl font-bold text-green-900">
                    {sessionSummary.summary.total_frames}
                  </div>
                </div>
                <div className="bg-purple-50 rounded-lg p-4">
                  <div className="text-sm text-purple-600 mb-1">音频块数</div>
                  <div className="text-2xl font-bold text-purple-900">
                    {sessionSummary.summary.total_chunks}
                  </div>
                </div>
                <div className="bg-yellow-50 rounded-lg p-4">
                  <div className="text-sm text-yellow-600 mb-1">平均注意力</div>
                  <div className="text-2xl font-bold text-yellow-900">
                    {sessionSummary.summary.statistics?.average_attention 
                      ? `${(sessionSummary.summary.statistics.average_attention * 100).toFixed(0)}%`
                      : '--'}
                  </div>
                </div>
              </div>
              
              {/* 详细统计 */}
              {sessionSummary.summary.statistics && (
                <div className="bg-gray-50 rounded-lg p-4">
                  <div className="text-sm text-gray-600 mb-2">详细统计</div>
                  <div className="text-sm text-gray-700 space-y-1">
                    <div className="flex justify-between">
                      <span>识别词数:</span>
                      <span className="font-medium">{sessionSummary.summary.statistics.word_count || 0}</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
            
            <div className="mt-6">
              <button
                onClick={() => setShowSummaryModal(false)}
                className="w-full px-6 py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition-colors"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        @keyframes shimmer {
          0% {
            background-position: -200% 0;
          }
          100% {
            background-position: 200% 0;
          }
        }
        .animate-shimmer {
          animation: shimmer 2s infinite;
        }
      `}</style>
    </div>
  );
}
