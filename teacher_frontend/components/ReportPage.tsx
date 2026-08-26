import { useCallback, useEffect, useMemo, useState } from 'react';

interface ReportPageProps {
  trainingSessionId: string;
  studentName?: string | null;
  onBack: () => void;
}

type DimensionKey =
  | 'attention'
  | 'matching'
  | 'ordering';

type CourseEvaluation = {
  courseType: string;
  label: string;
  status: 'evaluated' | 'not_evaluated' | 'insufficient_data' | string;
  score: number | null;
  targetScore: number;
  gapToTarget?: number | null;
  itemCount?: number;
};

type RecommendationView = {
  courseType: string;
  priority: string;
  title: string;
  evidence: string;
  practice: string;
  why: string;
  progressCheck: string;
  body: string;
  legacySingle: boolean;
};

const DIMENSIONS: Array<{ key: DimensionKey; label: string }> = [
  { key: 'attention', label: '注意力与模仿参与' },
  { key: 'matching', label: '配对能力' },
  { key: 'ordering', label: '排序能力' },
];

const COURSE_TYPES = [
  { key: 'mimic', label: '模仿' },
  { key: 'pairing', label: '配对' },
  { key: 'ordering', label: '排序' },
];
const ACTIVE_COURSE_TYPES = new Set(COURSE_TYPES.map(({ key }) => key));

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
const POLL_MS = 1500;
const POLL_MAX_MS = 45000;

function clampPercentage(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.min(100, number)) : 0;
}

function ModuleBlock({
  status,
  timedOut,
  children,
  pendingLabel = '正在整理本项结果…',
  missingLabel = '本项未评估',
}: {
  status?: string;
  timedOut?: boolean;
  children: React.ReactNode;
  pendingLabel?: string;
  missingLabel?: string;
}) {
  const effective = timedOut && status === 'pending' ? 'missing' : status;
  if (effective === 'pending') {
    return (
      <div className="animate-pulse rounded-2xl border border-dashed border-slate-300 p-5 text-center text-sm text-slate-500">
        {pendingLabel}
      </div>
    );
  }
  if (effective === 'missing' || !effective) {
    return (
      <div className="rounded-2xl border border-slate-200 p-5 text-center text-sm text-slate-400">
        {missingLabel}
      </div>
    );
  }
  return <>{children}</>;
}

function formatReportTime(value: unknown) {
  const raw = String(value || '').trim();
  if (!raw) return '—';
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

function courseStatusText(course: CourseEvaluation) {
  if (course.status === 'evaluated' && course.score != null) return `${Number(course.score).toFixed(1)}%`;
  if (course.status === 'insufficient_data') return '数据不足';
  return '未评估';
}

function teacherFriendlyLimitation(value: unknown) {
  const text = String(value || '').trim();
  if (!text) return '';
  if (/^[A-Z][A-Z0-9_]*$/.test(text)) return '部分过程数据未形成有效结果，相关项目未作推断';
  return text.replace('相关维度已降级', '相关结果仅依据已有有效记录呈现');
}

function splitAnalysis(value: unknown) {
  return percentageCopy(String(value || ''))
    .replace(/[A-Z][A-Z0-9_]+/g, '部分过程数据未形成有效结果')
    .split(/(?<=[。！？])/)
    .map((sentence) => sentence.trim())
    .filter(Boolean);
}

function percentageCopy(value: unknown) {
  return String(value || '')
    .replace(/表现参考分为\s*([\d.]+)/g, '表现为 $1%')
    .replace(/综合参考分为\s*([\d.]+)/g, '综合表现为 $1%')
    .replace(/距离\s*([\d.]+)\s*分参考目标还有\s*([\d.]+)\s*分/g, '距离 $1% 的课程参考目标还有 $2 个百分点')
    .replace(/已达到\s*([\d.]+)\s*分参考目标/g, '已达到 $1% 的课程参考目标');
}

function normalizeRecommendation(item: any, index: number): RecommendationView {
  const body = String(item?.body || '').trim();
  const title = String(item?.title || `训练建议 ${index + 1}`);
  const parsed = body.match(
    /练什么[：:]\s*([\s\S]*?)\s*为什么[：:]\s*([\s\S]*?)\s*(?:进步判断|如何判断进步)[：:]\s*([\s\S]*)/,
  );
  let practice = String(item?.practice || parsed?.[1] || '').trim();
  let why = percentageCopy(item?.why || parsed?.[2] || item?.evidence || '').trim();
  let progressCheck = String(item?.progressCheck || parsed?.[3] || '').trim();
  const evidence = percentageCopy(item?.evidence || '').trim();
  const onomatopoeia = String(item?.courseType || '').toLowerCase() === 'onomatopoeia' || String(item?.title || '').includes('拟声');
  if (onomatopoeia && practice.includes('图片配对')) {
    practice = '先听成人示范一个短声音，再请儿童模仿发声；从单个熟悉声音逐步扩展到不同音量和节奏。';
    progressCheck = '连续 3 次训练中，每次至少 4/5 个声音能在示范后独立模仿，不需要图片选择提示。';
    why = why.replace(
      '拟声表现反映儿童听辨、模仿发音和声音—对象联结的稳定性。',
      '拟声表现反映儿童听辨声音并尝试模仿发音的稳定性。',
    );
  }
  return {
    courseType: String(item?.courseType || 'course'),
    priority: String(item?.priority || (title.includes('优先') ? `优先 ${index + 1}` : title.includes('巩固') ? `巩固 ${index + 1}` : `建议 ${index + 1}`)),
    title,
    evidence,
    practice,
    why,
    progressCheck,
    body,
    legacySingle: Boolean(body && !practice && !why && !progressCheck),
  };
}

function fallbackHeadline(grade: unknown, overall: number | null, evaluatedCount: number) {
  if (overall == null || evaluatedCount === 0) return '数据不足';
  if (evaluatedCount < 2) return '数据覆盖有限';
  const raw = String(grade || '');
  if (raw.includes('优秀') || raw.includes('Excellent')) return '高分表现';
  if (raw.includes('良好') || raw.includes('Good')) return '整体表现较稳定';
  if (raw.includes('一般') || raw.includes('Fair')) return '中等且有波动';
  if (raw.includes('需加强') || raw.includes('Support')) return '部分任务完成较困难';
  return raw || '本次训练结果';
}

export function ReportPage({ trainingSessionId, studentName, onBack }: ReportPageProps) {
  const [report, setReport] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);
  const [awaitingPublish, setAwaitingPublish] = useState(false);
  const [layout, setLayout] = useState<'landscape' | 'portrait'>('landscape');
  const [resolvedStudentName, setResolvedStudentName] = useState('');
  const isLandscape = layout === 'landscape';

  const fetchPublishedReport = useCallback(async () => {
    const getRes = await fetch(`${API_BASE}/api/report/${trainingSessionId}?role=teacher`);
    const getJson = await getRes.json();
    if (getRes.status === 409 || getJson?.error === 'report_not_published') {
      const pendingError: any = new Error('report_not_published');
      pendingError.code = 'report_not_published';
      throw pendingError;
    }
    if (getJson?.success && getJson.data) return getJson.data;
    throw new Error('报告暂时无法显示，请稍后重试');
  }, [trainingSessionId]);

  const handleManualRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const data = await fetchPublishedReport();
      setReport(data);
      setError(null);
      setAwaitingPublish(false);
      const pending = Object.values(data.modules || {}).some((status) => status === 'pending');
      if (!pending) setTimedOut(false);
    } catch (caught: any) {
      if (caught?.code === 'report_not_published' || caught?.message === 'report_not_published') {
        setAwaitingPublish(true);
        setError(null);
      } else {
        setError('报告暂时无法显示，请稍后重试');
      }
    } finally {
      setRefreshing(false);
    }
  }, [fetchPublishedReport]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const started = Date.now();

    async function loop() {
      try {
        const data = await fetchPublishedReport();
        if (cancelled) return;
        setReport(data);
        setLoading(false);
        setError(null);
        setAwaitingPublish(false);
        const pending = Object.values(data.modules || {}).some((status) => status === 'pending');
        if (data.status === 'READY' || !pending) return;
        if (Date.now() - started >= POLL_MAX_MS) {
          setTimedOut(true);
          return;
        }
        timer = window.setTimeout(loop, POLL_MS);
      } catch (caught: any) {
        if (cancelled) return;
        if (caught?.code === 'report_not_published' || caught?.message === 'report_not_published') {
          setAwaitingPublish(true);
          setLoading(false);
          setError(null);
          timer = window.setTimeout(loop, POLL_MS);
          return;
        }
        setError('报告暂时无法显示，请稍后重试');
        setLoading(false);
      }
    }

    void loop();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [fetchPublishedReport]);

  useEffect(() => {
    let styleEl = document.getElementById('report-page-print-style') as HTMLStyleElement | null;
    if (!styleEl) {
      styleEl = document.createElement('style');
      styleEl.id = 'report-page-print-style';
      document.head.appendChild(styleEl);
    }
    styleEl.textContent = isLandscape
      ? '@page { size: landscape; margin: 8mm; }'
      : '@page { size: portrait; margin: 10mm; }';
  }, [isLandscape]);

  useEffect(() => {
    const directName = String(report?.studentName || '').trim();
    if (directName) {
      setResolvedStudentName(directName);
      return;
    }
    const studentId = report?.studentId ?? studentName;
    if (studentId == null || String(studentId).trim() === '') return;
    let cancelled = false;
    fetch(`${API_BASE}/api/students/${encodeURIComponent(String(studentId))}`)
      .then((response) => response.json())
      .then((payload) => {
        if (!cancelled && payload?.success && payload?.student?.name) {
          setResolvedStudentName(String(payload.student.name));
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [report?.studentId, report?.studentName, studentName]);

  const scopedCourseTypes = useMemo(() => {
    const configured = Array.isArray(report?.courseScope?.enabledCourseTypes)
      ? report.courseScope.enabledCourseTypes.filter((key: string) => ACTIVE_COURSE_TYPES.has(key))
      : [];
    return new Set<string>(configured.length ? configured : ACTIVE_COURSE_TYPES);
  }, [report?.courseScope?.enabledCourseTypes]);
  const activeCourseCount = scopedCourseTypes.size;

  const courseEvaluations = useMemo<CourseEvaluation[]>(() => {
    const fromReport = Array.isArray(report?.courseEvaluations)
      ? report.courseEvaluations.filter((course: CourseEvaluation) => scopedCourseTypes.has(course.courseType))
      : [];
    if (fromReport.length) return fromReport;
    const scores = report?.courseScores || {};
    const targetScore = Number(report?.courseGoalScore ?? 70);
    return COURSE_TYPES.map(({ key, label }) => {
      const rawScore = scores[key];
      const score = rawScore == null ? null : Number(rawScore);
      return {
        courseType: key,
        label,
        status: score == null ? 'not_evaluated' : 'evaluated',
        score,
        targetScore,
        gapToTarget: score == null ? null : score - targetScore,
      };
    });
  }, [report, scopedCourseTypes]);

  const evaluatedCount = courseEvaluations.filter((course) => course.status === 'evaluated' && course.score != null).length;
  const narrative = report?.narrative || {};
  const narrativeSummary = narrative.summary || {};
  const kpi = report?.kpi || {};
  const isPartial = report?.status === 'PARTIAL' && !timedOut;
  const targetScore = clampPercentage(report?.courseGoalScore ?? 70);

  const translatedLimitations = useMemo(() => {
    const source = Array.isArray(report?.dataQuality?.limitationLabels)
      ? report.dataQuality.limitationLabels
      : [];
    return Array.from(new Set(source.map(teacherFriendlyLimitation).filter(Boolean)));
  }, [report]);

  const curveCoordinates = useMemo(() => {
    const curve = (report?.attentionCurve || []).filter((point: any) => point.score != null);
    const width = 760;
    const height = 120;
    return curve.map((point: any, index: number) => {
      const x = curve.length === 1 ? width / 2 : (index / (curve.length - 1)) * width;
      const score = clampPercentage(point.score);
      const y = height - (score / 100) * (height - 20) - 10;
      return { x, y, score };
    });
  }, [report]);

  const recommendations = useMemo(
    () => {
      const normalized = (Array.isArray(narrative.recommendations) ? narrative.recommendations : [])
        .map(normalizeRecommendation)
        .filter((item) => item.courseType === 'coverage' || scopedCourseTypes.has(item.courseType));
      if (normalized.length === 1 && normalized[0].title.includes('保持节奏')) {
        const lowest = courseEvaluations
          .filter((course) => course.status === 'evaluated' && course.score != null)
          .sort((left, right) => Number(left.score) - Number(right.score))[0];
        if (lowest) {
          const score = Number(lowest.score);
          const target = Number(lowest.targetScore || 70);
          return [{
            ...normalized[0],
            courseType: lowest.courseType,
            priority: '巩固 1',
            title: `${lowest.label}：巩固与迁移`,
            evidence: `本次${lowest.label}表现为 ${score.toFixed(1)}%，${score >= target ? `已达到 ${target.toFixed(1)}% 的课程参考目标` : `距离 ${target.toFixed(1)}% 的课程参考目标还有 ${(target - score).toFixed(1)} 个百分点`}。`,
            practice: `更换不同材料和提示顺序，重复练习${lowest.label}任务，并逐步减少额外提示。`,
            why: `继续巩固是为了确认本次${lowest.label}表现能否在不同材料中保持稳定，而不只是完成当前题目。`,
            progressCheck: `连续 3 次训练达到 ${target.toFixed(0)}% 课程参考目标，且不增加提示。`,
            legacySingle: false,
          }];
        }
      }
      return normalized;
    },
    [courseEvaluations, narrative.recommendations, scopedCourseTypes],
  );

  if (loading && !report) {
    return <div className="grid min-h-screen place-items-center bg-slate-100 text-slate-600">正在整理评估结果…</div>;
  }

  if (awaitingPublish && !report) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-100 p-6">
        <div className="max-w-md text-center text-slate-700">报告正在等待确认，确认后会自动显示。</div>
        <div className="flex gap-2">
          <button onClick={handleManualRefresh} className="rounded-lg bg-sky-600 px-4 py-2 text-white">重新检查</button>
          <button onClick={onBack} className="rounded-lg bg-slate-200 px-4 py-2 text-slate-800">返回</button>
        </div>
      </div>
    );
  }

  if (error && !report) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-100 p-6">
        <div className="text-rose-600">{error}</div>
        <div className="flex gap-2">
          <button onClick={handleManualRefresh} className="rounded-lg bg-sky-600 px-4 py-2 text-white">重试</button>
          <button onClick={onBack} className="rounded-lg bg-slate-200 px-4 py-2 text-slate-800">返回</button>
        </div>
      </div>
    );
  }

  const overall = report?.overall == null ? null : Number(report.overall);
  const overallProgress = overall == null ? 0 : clampPercentage(overall);
  const headline = String(narrative.headline || fallbackHeadline(report?.grade, overall, evaluatedCount));
  const analysisSentences = splitAnalysis(narrative.analysis);
  const stableAnalysis = analysisSentences.find((sentence) => /相对优势|相对稳定|相对较高|达到.*目标/.test(sentence));
  const attentionAnalysis = analysisSentences.find((sentence) => /低点|波动|困难|较低|需要关注|完成情况.*有限/.test(sentence));
  const overview = narrative.overview || {};
  const overviewRows = [
    {
      title: '整体表现',
      value: overview.overall || (overall == null ? '本次尚未形成有效综合结果。' : `本次综合表现为 ${overall.toFixed(1)}%，已完成 ${evaluatedCount}/${activeCourseCount} 类课程评估。`),
    },
    {
      title: '相对稳定',
      value: overview.stable || narrativeSummary.strengths || stableAnalysis || '本次暂无足够结果判断相对稳定的能力。',
    },
    {
      title: '值得关注',
      value: overview.attention || narrativeSummary.consolidation || attentionAnalysis || '完成更多课程后再确定需要优先巩固的部分。',
    },
    {
      title: '结果边界',
      value: overview.boundary || narrative.disclaimer || '结果仅反映本次任务情境，建议结合多次训练记录观察。',
    },
  ];
  const displayStudentName = resolvedStudentName || (studentName && !/^\d+$/.test(String(studentName)) ? String(studentName) : '姓名未填写');
  const curvePoints = curveCoordinates.map((point) => `${point.x},${point.y}`).join(' ');
  const emotion = kpi.emotion || {};
  const emotionReady = emotion.label && emotion.label !== '数据不足';

  return (
    <div className="min-h-screen bg-[#edf2f6] text-[#21364b] print:bg-white">
      <div className={`sticky top-0 z-20 mx-auto flex items-center justify-between border-b border-slate-200 bg-white/95 px-5 py-3 backdrop-blur print:hidden ${isLandscape ? 'max-w-[1440px]' : 'max-w-[980px]'}`}>
        <div>
          <div className="font-semibold text-slate-800">儿童认知训练评估报告</div>
          <div className="mt-0.5 text-xs text-slate-500">{isLandscape ? '横版查看' : '竖版查看'}{isPartial ? ' · 部分结果仍在整理' : ''}</div>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <button onClick={() => setLayout((value) => value === 'landscape' ? 'portrait' : 'landscape')} className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700">切换版式</button>
          <button onClick={handleManualRefresh} disabled={refreshing || loading} className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 disabled:opacity-60">{refreshing ? '检查中…' : '更新结果'}</button>
          <button onClick={() => window.print()} className="rounded-lg bg-[#3489ca] px-4 py-2 text-sm font-semibold text-white">打印</button>
          <button onClick={onBack} className="rounded-lg bg-slate-200 px-4 py-2 text-sm text-slate-800">返回</button>
        </div>
      </div>

      <main className={`mx-auto my-5 min-h-screen overflow-hidden bg-white shadow-[0_12px_40px_rgba(23,40,60,.08)] print:my-0 print:shadow-none ${isLandscape ? 'max-w-[1440px]' : 'max-w-[980px]'}`}>
        <header className="flex flex-col gap-4 border-b-[5px] border-[#17283c] px-7 py-7 sm:flex-row sm:items-start sm:justify-between md:px-11 md:py-9">
          <div>
            <div className="text-2xl font-black tracking-[0.04em] text-[#17283c] md:text-[32px]">EVALUATION SYSTEM</div>
            <div className="mt-2 text-sm font-bold text-[#3489ca] md:text-lg">儿童认知训练中心评估系统</div>
          </div>
          <div className="text-sm leading-7 text-slate-500 sm:text-right">
            <div>受测儿童：<strong className="ml-2 text-base text-[#17283c]">{displayStudentName}</strong></div>
            <div>评估时间：<strong className="ml-2 text-[#17283c]">{formatReportTime(report?.generatedAt)}</strong></div>
          </div>
        </header>

        <div className="space-y-6 px-5 py-6 md:px-10 md:py-8">
          <section className={`grid gap-5 ${isLandscape ? 'lg:grid-cols-[320px_1fr]' : 'grid-cols-1'}`}>
            <article className="flex min-h-[350px] flex-col items-center justify-center rounded-[24px] border border-[#d7e9f6] bg-gradient-to-b from-[#eef8fe] to-[#f8fbfd] p-6 text-center shadow-[0_5px_18px_rgba(33,55,78,.05)]">
              <div
                className="grid h-40 w-40 place-items-center rounded-full"
                style={{ background: `conic-gradient(#3489ca ${overallProgress}%, #d7eafa 0)` }}
              >
                <div className="grid h-[126px] w-[126px] place-items-center rounded-full bg-white">
                  <div>
                    <div className="text-4xl font-black leading-none text-[#17283c]">{overall == null ? '—' : overall.toFixed(1)}{overall != null && <span className="ml-0.5 text-lg">%</span>}</div>
                    <div className="mt-2 text-xs font-bold text-slate-500">综合表现</div>
                  </div>
                </div>
              </div>
              <h1 className="mt-6 text-xl font-black text-[#17283c]">{headline}</h1>
              <div className="mt-3 rounded-full bg-white px-4 py-1.5 text-xs font-bold text-[#2b6f9f] shadow-sm">已评估 {evaluatedCount}/{activeCourseCount} 类课程</div>
              <p className="mt-4 max-w-[250px] text-xs leading-5 text-slate-500">综合百分比只根据本次已完成课程计算，未参加课程不按 0 分处理。</p>
            </article>

            <article className="rounded-[24px] border border-slate-200 bg-white p-5 shadow-[0_5px_18px_rgba(33,55,78,.045)] md:p-7" aria-label="核心能力百分比柱状图">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-xl font-black text-[#17283c]">核心能力百分比柱状图</h2>
                  <p className="mt-1 text-sm text-slate-500">当前达到多少、目标在哪里、还需提升多少，在同一行直接比较。</p>
                </div>
                <div className="flex items-center gap-4 text-xs text-slate-500">
                  <span className="flex items-center gap-2"><i className="h-3 w-5 rounded-sm bg-[#3489ca]" />当前表现</span>
                  <span className="flex items-center gap-2"><i className="h-4 w-0.5 bg-[#e5a13a]" />课程参考目标 {targetScore.toFixed(0)}%</span>
                </div>
              </div>

              <div className="mt-6 space-y-4">
                <div className="grid grid-cols-[88px_1fr_104px] items-end gap-3 text-[10px] text-slate-400 sm:grid-cols-[112px_1fr_132px]">
                  <span />
                  <div className="flex justify-between px-0.5"><span>0%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div>
                  <span className="text-right">当前 / 差距</span>
                </div>
                {DIMENSIONS.map(({ key, label }) => {
                  const meta = report?.dimensions?.[key];
                  const evaluated = Boolean(meta?.available && meta?.score != null && meta?.status === 'ready');
                  const score = evaluated ? clampPercentage(meta.score) : 0;
                  const gap = score - targetScore;
                  return (
                    <div key={key} className="grid grid-cols-[88px_1fr_104px] items-center gap-3 sm:grid-cols-[112px_1fr_132px]">
                      <div className="text-sm font-bold text-slate-700">{label}</div>
                      <div className="relative h-9 overflow-hidden rounded-lg bg-[#eff3f6]">
                        <div className="absolute inset-0 grid grid-cols-4">
                          <i className="border-r border-white/80" /><i className="border-r border-white/80" /><i className="border-r border-white/80" /><i />
                        </div>
                        {evaluated ? (
                          <>
                            <div className="absolute inset-y-0 left-0 rounded-lg bg-gradient-to-r from-[#65b2e4] to-[#3489ca]" style={{ width: `${score}%` }} />
                            <div className="absolute inset-y-0 z-[2] w-0.5 bg-[#e5a13a] shadow-[0_0_0_1px_rgba(255,255,255,.7)]" style={{ left: `${targetScore}%` }} />
                          </>
                        ) : (
                          <div className="absolute inset-0 flex items-center px-3 text-xs text-slate-400">本次没有有效结果</div>
                        )}
                      </div>
                      <div className="text-right">
                        {evaluated ? (
                          <>
                            <div className="text-base font-black text-[#17283c]">{score.toFixed(1)}%</div>
                            <div className={`mt-0.5 text-[11px] font-bold ${gap >= 0 ? 'text-emerald-600' : 'text-amber-600'}`}>{gap >= 0 ? `已达目标 +${gap.toFixed(1)}` : `还差 ${Math.abs(gap).toFixed(1)} 个百分点`}</div>
                          </>
                        ) : <div className="text-sm font-bold text-slate-400">未评估</div>}
                      </div>
                    </div>
                  );
                })}
              </div>
              <p className="mt-6 border-t border-dashed border-slate-200 pt-4 text-xs leading-5 text-slate-400">所有数值均为本次训练任务中的百分比表现；目标用于安排训练，不代表年龄常模或百分位。</p>
            </article>
          </section>

          <section className="rounded-[20px] border border-slate-200 bg-[#fbfdff] p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-black text-[#17283c]">本次课程覆盖</h2>
              <span className="text-xs text-slate-500">没有参加的课程明确显示“未评估”</span>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3">
              {courseEvaluations.map((course) => {
                const evaluated = course.status === 'evaluated' && course.score != null;
                const score = evaluated ? Number(course.score) : null;
                const reached = evaluated && score != null && score >= Number(course.targetScore || targetScore);
                return (
                  <div key={course.courseType} className={`rounded-2xl border p-3.5 ${evaluated ? 'border-sky-200 bg-white' : 'border-slate-200 bg-slate-50'}`}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-bold text-slate-700">{course.label}</span>
                      <span className={`h-2.5 w-2.5 rounded-full ${evaluated ? (reached ? 'bg-emerald-500' : 'bg-amber-500') : 'bg-slate-300'}`} />
                    </div>
                    <div className={`mt-2 text-lg font-black ${evaluated ? 'text-[#2b6f9f]' : 'text-slate-400'}`}>{courseStatusText(course)}</div>
                    <div className="mt-1 text-[11px] text-slate-400">{evaluated ? `目标 ${Number(course.targetScore || targetScore).toFixed(0)}%` : course.status === 'insufficient_data' ? '有效数据不足' : '本次未参加'}</div>
                  </div>
                );
              })}
            </div>
          </section>

          <section className={`grid gap-5 ${isLandscape ? 'lg:grid-cols-[1.08fr_.92fr]' : 'grid-cols-1'}`}>
            <article>
              <div className="mb-3 border-l-4 border-[#3489ca] pl-3 text-lg font-black text-[#17283c]">核心数据与过程监测</div>
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_4px_14px_rgba(33,55,78,.04)]">
                  <div className="text-xs font-bold text-slate-500">综合任务表现</div>
                  <div className="mt-2 text-2xl font-black text-[#17283c]">{kpi.taskPerformance != null ? `${Number(kpi.taskPerformance).toFixed(1)}%` : '未评估'}</div>
                  <div className="mt-2 text-[11px] leading-4 text-slate-400">按已完成课程平衡计算</div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_4px_14px_rgba(33,55,78,.04)]">
                  <div className="text-xs font-bold text-slate-500">平均响应时长</div>
                  <div className="mt-2 text-2xl font-black text-[#17283c]">{kpi.avgResponseSec != null ? `${Number(kpi.avgResponseSec).toFixed(1)} 秒` : '未评估'}</div>
                  <div className="mt-2 text-[11px] leading-4 text-slate-400">仅统计形成有效响应的课点</div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_4px_14px_rgba(33,55,78,.04)]">
                  <div className="text-xs font-bold text-slate-500">主要情绪状态</div>
                  <div className="mt-2 text-lg font-black text-[#17283c]">{emotionReady ? emotion.label : '数据不足'}</div>
                  {emotionReady && [emotion.happy, emotion.focus, emotion.frustration].every((value) => value != null) && (
                    <>
                      <div className="mt-3 flex h-1.5 overflow-hidden rounded-full bg-slate-100">
                        <i className="bg-emerald-500" style={{ width: `${clampPercentage(emotion.happy)}%` }} />
                        <i className="bg-[#54a3d6]" style={{ width: `${clampPercentage(emotion.focus)}%` }} />
                        <i className="bg-amber-400" style={{ width: `${clampPercentage(emotion.frustration)}%` }} />
                      </div>
                      <div className="mt-1.5 text-[10px] font-semibold text-slate-400">愉悦 {Number(emotion.happy).toFixed(0)}% · 专注 {Number(emotion.focus).toFixed(0)}% · 急躁 {Number(emotion.frustration).toFixed(0)}%</div>
                    </>
                  )}
                </div>
              </div>

              <div className="mt-4 rounded-[20px] border border-slate-200 bg-white p-5 shadow-[0_4px_14px_rgba(33,55,78,.04)]">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="font-black text-[#17283c]">训练期间注意力变化</h2>
                  <span className="text-[11px] text-slate-400">从课程开始到结束</span>
                </div>
                <ModuleBlock status={report?.modules?.attentionCurve} timedOut={timedOut} missingLabel="本次没有足够的注意力过程数据">
                  {curvePoints ? (
                    <div className="mt-4 rounded-2xl bg-[#f4faff] p-3">
                      <svg viewBox="0 0 760 120" className="h-32 w-full" preserveAspectRatio="none" aria-label="训练期间注意力变化曲线">
                        <line x1="0" y1="60" x2="760" y2="60" stroke="#cce8f8" strokeDasharray="8 8" />
                        <polyline points={`0,120 ${curvePoints} 760,120`} fill="rgba(52,137,202,.08)" stroke="none" />
                        <polyline points={curvePoints} fill="none" stroke="#3489ca" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
                        {curveCoordinates.map((point, index) => <circle key={index} cx={point.x} cy={point.y} r="4" fill="#fff" stroke="#3489ca" strokeWidth="3" />)}
                      </svg>
                      <div className="mt-1 flex justify-between text-[10px] text-slate-400"><span>开始</span><span>结束</span></div>
                    </div>
                  ) : <div className="py-8 text-center text-sm text-slate-400">本次没有足够的注意力过程数据</div>}
                </ModuleBlock>
              </div>
            </article>

            <article>
              <div className="mb-3 border-l-4 border-[#3489ca] pl-3 text-lg font-black text-[#17283c]">综合表现分析</div>
              <div className="rounded-[22px] border border-[#cde5f7] bg-gradient-to-b from-[#eef8fe] to-[#f8fbfd] p-5 shadow-[0_5px_18px_rgba(33,55,78,.045)] md:p-6">
                <div className="mb-5 flex items-center justify-between gap-3">
                  <div>
                    <div className="text-xs font-bold tracking-[0.12em] text-[#3489ca]">本次训练结论</div>
                    <div className="mt-1 text-xl font-black text-[#17283c]">{headline}</div>
                  </div>
                  {overall != null && <div className="rounded-xl bg-white px-3 py-2 text-lg font-black text-[#2b6f9f] shadow-sm">{overall.toFixed(1)}%</div>}
                </div>
                <div className="space-y-3">
                  {overviewRows.map((row, index) => (
                    <div key={row.title} className="grid grid-cols-[30px_1fr] gap-3 rounded-2xl border border-white/80 bg-white/75 p-3.5">
                      <div className="grid h-7 w-7 place-items-center rounded-full bg-[#3489ca] text-xs font-black text-white">{index + 1}</div>
                      <div>
                        <div className="text-xs font-black text-[#2b6f9f]">{row.title}</div>
                        <p className="mt-1 text-sm leading-6 text-slate-700">{row.value}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </article>
          </section>

          <section>
            <div className="mb-3 border-l-4 border-[#3489ca] pl-3 text-lg font-black text-[#17283c]">训练安排要点</div>
            <div className="grid gap-3 md:grid-cols-3">
              <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
                <div className="text-xs font-black text-emerald-700">优势能力</div>
                <div className="mt-2 text-sm leading-6 text-slate-700">{narrativeSummary.strengths || overviewRows[1].value}</div>
              </div>
              <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
                <div className="text-xs font-black text-amber-700">需要巩固</div>
                <div className="mt-2 text-sm leading-6 text-slate-700">{narrativeSummary.consolidation || overviewRows[2].value}</div>
              </div>
              <div className="rounded-2xl border border-sky-200 bg-sky-50 p-4">
                <div className="text-xs font-black text-sky-700">下一步重点</div>
                <div className="mt-2 text-sm leading-6 text-slate-700">{narrativeSummary.nextFocus || '根据柱状图中与目标差距最大的课程安排下一阶段训练。'}</div>
              </div>
            </div>
          </section>

          <section>
            <div className="mb-3 flex flex-wrap items-end justify-between gap-2 border-l-4 border-[#3489ca] pl-3">
              <div>
                <h2 className="text-lg font-black text-[#17283c]">后续训练建议</h2>
                <p className="mt-1 text-xs text-slate-500">按优先顺序说明练什么、为什么练，以及如何判断已经进步。</p>
              </div>
            </div>
            {recommendations.length ? (
              <div className={`grid gap-4 ${recommendations.length > 1 ? 'lg:grid-cols-2' : 'grid-cols-1'}`}>
                {recommendations.map((recommendation, index) => (
                  <article key={`${recommendation.courseType}-${index}`} className="break-inside-avoid rounded-[22px] border border-slate-200 bg-white p-5 shadow-[0_4px_16px_rgba(33,55,78,.045)]">
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="text-base font-black text-[#17283c]">{recommendation.title}</h3>
                      <span className={`shrink-0 rounded-full px-3 py-1 text-xs font-black ${recommendation.priority.startsWith('优先') ? 'bg-rose-50 text-rose-700' : recommendation.priority.startsWith('巩固') ? 'bg-emerald-50 text-emerald-700' : 'bg-sky-50 text-sky-700'}`}>{recommendation.priority}</span>
                    </div>
                    {recommendation.legacySingle ? (
                      <div className="mt-4 rounded-2xl bg-sky-50 p-4 text-sm leading-7 text-slate-700">{recommendation.body}</div>
                    ) : (
                      <div className="mt-4 space-y-3 text-sm">
                        {recommendation.evidence && <div className="rounded-xl border border-sky-100 bg-sky-50 px-3 py-2.5 leading-6"><strong className="text-[#2b6f9f]">本次依据：</strong>{recommendation.evidence}</div>}
                        <div className="grid gap-3 sm:grid-cols-2">
                          <div className="rounded-xl bg-[#f7f9fb] p-3 leading-6"><strong className="block text-xs text-[#2b6f9f]">练什么</strong><span className="mt-1 block text-slate-700">{recommendation.practice || recommendation.body}</span></div>
                          <div className="rounded-xl bg-[#fff9ef] p-3 leading-6"><strong className="block text-xs text-amber-700">为什么练</strong><span className="mt-1 block text-slate-700">{recommendation.why || '用于巩固本次相对薄弱的课程表现。'}</span></div>
                        </div>
                        <div className="rounded-xl bg-emerald-50 px-3 py-2.5 leading-6"><strong className="text-emerald-700">进步标志：</strong>{recommendation.progressCheck || '连续多次训练达到当前课程参考目标。'}</div>
                      </div>
                    )}
                  </article>
                ))}
              </div>
            ) : (
              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">本次没有足够结果形成针对性建议，请先补充有效课程评估。</div>
            )}
          </section>

          {(translatedLimitations.length > 0 || timedOut || isPartial) && (
            <section className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
              <strong>数据完整性：</strong>
              {timedOut
                ? '部分过程数据暂未形成有效结果，相关项目已按“数据不足”或“未评估”展示。'
                : isPartial
                  ? '部分过程数据仍在整理，当前没有结果的课程不会按 0 分计算。'
                  : translatedLimitations.slice(0, 4).join('；')}
            </section>
          )}
        </div>

        <footer className="flex flex-col gap-2 border-t border-slate-200 bg-[#fafcfd] px-7 py-4 text-xs leading-5 text-slate-500 sm:flex-row sm:items-center sm:justify-between md:px-10">
          <div>{narrative.disclaimer || '本报告用于教育训练观察，仅反映当前任务情境，不构成诊断或医疗建议。'}</div>
          <div className="shrink-0 font-semibold">根据本次课程有效结果生成</div>
        </footer>
      </main>
    </div>
  );
}
