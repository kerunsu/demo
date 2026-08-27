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
  provisionalScore?: number | null;
  validSampleCount?: number;
  requiredSampleCount?: number;
  sampleUnit?: 'rated_item' | 'answered_question' | string;
  sampleAdequacy?: number;
  contributesToOverall?: boolean;
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
  { key: 'attention', label: '注意力参与' },
  { key: 'matching', label: '配对能力' },
  { key: 'ordering', label: '排序能力' },
];

const COURSE_TYPES = [
  { key: 'pairing', label: '配对' },
  { key: 'ordering', label: '排序' },
];

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
      <div className="animate-pulse rounded-xl border border-dashed border-slate-300 p-3 text-center text-xs text-slate-500">
        {pendingLabel}
      </div>
    );
  }
  if (effective === 'missing' || !effective) {
    return (
      <div className="rounded-xl border border-slate-200 p-3 text-center text-xs text-slate-400">
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
  if (course.status === 'insufficient_data') return '数据不足';
  if (course.status === 'evaluated' && course.score != null) return `${clampPercentage(course.score).toFixed(1)}%`;
  return '未评估';
}

function courseSampleText(course: CourseEvaluation) {
  const valid = Number(course.validSampleCount);
  const required = Number(course.requiredSampleCount);
  if (!Number.isFinite(valid) || !Number.isFinite(required) || required <= 0) return '';
  const unit = course.sampleUnit === 'answered_question' ? '有效作答' : '有效评分课点';
  return `${unit} ${Math.max(0, valid)}/${required}`;
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
    .replace(/距离\s*([\d.]+)\s*分参考目标还有\s*([\d.]+)\s*分/g, '距离 $1% 的训练参考目标还有 $2 个百分点')
    .replace(/已达到\s*([\d.]+)\s*分参考目标/g, '已达到 $1% 的训练参考目标')
    .replace(/课程参考目标/g, '训练参考目标')
    .replace(/(?<!训练)参考目标/g, '训练参考目标');
}

function normalizeRecommendation(item: any, index: number): RecommendationView {
  const body = String(item?.body || '').trim();
  const title = String(item?.title || `训练建议 ${index + 1}`);
  const parsed = body.match(
    /(?:训练内容|练什么|做什么)[：:]\s*([\s\S]*?)\s*(?:建议依据|为什么练|为什么做|为什么)[：:]\s*([\s\S]*?)\s*(?:成效判据|进步标志|进步判断|如何判断进步)[：:]\s*([\s\S]*)/,
  );
  let practice = String(item?.practice || parsed?.[1] || '').trim();
  let why = percentageCopy(item?.why || parsed?.[2] || item?.evidence || '').trim();
  let progressCheck = percentageCopy(item?.progressCheck || parsed?.[3] || '').trim();
  const evidence = percentageCopy(item?.evidence || '').trim();
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

  const courseEvaluations = useMemo<CourseEvaluation[]>(() => {
    const fromReport = Array.isArray(report?.courseEvaluations) ? report.courseEvaluations : [];
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
  }, [report]);

  const evaluatedCount = courseEvaluations.filter((course) => course.status === 'evaluated' && course.score != null).length;
  const narrative = report?.narrative || {};
  const narrativeSummary = narrative.summary || {};
  const kpi = report?.kpi || {};
  const isPartial = report?.status === 'PARTIAL' && !timedOut;
  const targetScore = clampPercentage(report?.courseGoalScore ?? 70);
  const previousPerformance = report?.previousPerformance || null;
  const previousDimensions = previousPerformance?.dimensions || {};
  const previousComparisonStatus = String(previousPerformance?.comparisonStatus || 'unavailable');
  const hasPreviousPerformance = Object.values(previousDimensions).some((meta: any) => meta?.score != null);
  const previousLegendLabel = !hasPreviousPerformance
    ? '上次表现（暂无）'
    : previousComparisonStatus === 'comparable'
      ? '上次表现'
      : '上次表现（口径不同）';

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
        .map(normalizeRecommendation);
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
            evidence: `本次${lowest.label}表现为 ${score.toFixed(1)}%，${score >= target ? `已达到 ${target.toFixed(1)}% 的训练参考目标` : `距离 ${target.toFixed(1)}% 的训练参考目标还有 ${(target - score).toFixed(1)} 个百分点`}。`,
            practice: `更换不同材料和提示顺序，重复练习${lowest.label}任务，并逐步减少额外提示。`,
            why: `继续巩固是为了确认本次${lowest.label}表现能否在不同材料中保持稳定，而不只是完成当前题目。`,
            progressCheck: `连续 3 次训练达到 ${target.toFixed(0)}% 训练参考目标，且不增加提示。`,
            legacySingle: false,
          }];
        }
      }
      return normalized;
    },
    [courseEvaluations, narrative.recommendations],
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
      value: overview.overall || (overall == null ? '本次尚未形成有效综合结果。' : `本次综合表现为 ${overall.toFixed(1)}%，已完成 ${evaluatedCount}/5 类课程评估。`),
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
  ].map((row) => ({ ...row, value: percentageCopy(row.value) }));
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

      <main className={`mx-auto my-3 min-h-screen overflow-hidden bg-white shadow-[0_12px_40px_rgba(23,40,60,.08)] print:my-0 print:shadow-none ${isLandscape ? 'max-w-[1440px]' : 'max-w-[980px]'}`}>
        <header className="flex flex-col gap-3 border-b-[3px] border-[#17283c] px-5 py-4 sm:flex-row sm:items-start sm:justify-between md:px-7 md:py-5">
          <div>
            <div className="text-xl font-black tracking-[0.04em] text-[#17283c] md:text-[24px]">EVALUATION SYSTEM</div>
            <div className="mt-1 text-xs font-bold text-[#3489ca] md:text-sm">儿童认知训练中心评估系统</div>
          </div>
          <div className="text-xs leading-6 text-slate-500 sm:text-right">
            <div>受测儿童：<strong className="ml-2 text-sm text-[#17283c]">{displayStudentName}</strong></div>
            <div>评估时间：<strong className="ml-2 text-[#17283c]">{formatReportTime(report?.generatedAt)}</strong></div>
          </div>
        </header>

        <div className="space-y-4 px-4 py-4 md:px-6 md:py-5">
          <section
            aria-label="评估总览"
            className={`grid items-start gap-3 rounded-[18px] border border-slate-200 bg-[#f8fbfd] p-3 shadow-[0_4px_14px_rgba(33,55,78,.045)] ${isLandscape ? 'xl:grid-cols-[.9fr_1.15fr_1.05fr]' : 'grid-cols-1'}`}
          >
            <article className="flex min-w-0 flex-col items-center rounded-[16px] border border-[#d7e9f6] bg-gradient-to-b from-[#eef8fe] to-white p-3 text-center">
              <h2 className="self-start border-l-[3px] border-[#3489ca] pl-2.5 text-base font-black text-[#17283c]">综合表现分析</h2>
              <div
                className="mt-3 grid h-24 w-24 place-items-center rounded-full"
                style={{ background: `conic-gradient(#3489ca ${overallProgress}%, #d7eafa 0)` }}
              >
                <div className="grid h-[76px] w-[76px] place-items-center rounded-full bg-white">
                  <div>
                    <div className="text-xl font-black leading-none text-[#17283c]">{overall == null ? '—' : overall.toFixed(1)}{overall != null && <span className="ml-0.5 text-xs">%</span>}</div>
                    <div className="mt-1 text-[10px] font-bold text-slate-500">综合表现</div>
                  </div>
                </div>
              </div>
              <h1 className="mt-2 text-base font-black text-[#17283c]">{headline}</h1>
              <p className="mt-1 text-[10px] leading-4 text-slate-500">综合百分比只根据本次有效课程结果计算，缺少结果的课程不按 0 分处理。</p>
              <div className="mt-3 w-full space-y-1.5 text-left">
                {overviewRows.map((row, index) => (
                  <div key={row.title} className="grid grid-cols-[20px_1fr] gap-2 rounded-lg border border-white bg-white/85 p-2">
                    <div className="grid h-5 w-5 place-items-center rounded-full bg-[#3489ca] text-[9px] font-black text-white">{index + 1}</div>
                    <div>
                      <div className="text-[10px] font-black text-[#2b6f9f]">{row.title}</div>
                      <p className="mt-0.5 text-[11px] leading-[17px] text-slate-700">{row.value}</p>
                    </div>
                  </div>
                ))}
              </div>
            </article>

            <div className="grid min-w-0 gap-3 xl:col-span-2">
              <div className="grid min-w-0 items-start gap-3 xl:grid-cols-[1.15fr_1.05fr]">
                <article className="min-w-0 rounded-[16px] border border-slate-200 bg-white p-3" aria-label="核心能力百分比柱状图">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="border-l-[3px] border-[#3489ca] pl-2.5 text-base font-black text-[#17283c]">核心能力表现</h2>
                  <p className="mt-1 text-[10px] text-slate-500">当前表现、上次已发布报告基线与训练参考线</p>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-2 text-[9px] text-slate-500">
                  <span className="flex items-center gap-2"><i className="h-3 w-5 rounded-sm bg-[#3489ca]" />当前表现</span>
                  <span className={`flex items-center gap-2 ${hasPreviousPerformance ? '' : 'text-slate-300'}`}><i className="h-2.5 w-2.5 rounded-full border-2 border-[#19537b] bg-white" />{previousLegendLabel}</span>
                  <span className="flex items-center gap-2"><i className="h-4 w-0.5 bg-[#e5a13a]" />训练参考线 {targetScore.toFixed(0)}%</span>
                </div>
              </div>

              <div className="mt-3 space-y-2.5">
                <div className="grid grid-cols-[86px_minmax(0,1fr)_108px] items-end gap-2 text-[8px] text-slate-400">
                  <span />
                  <div className="flex justify-between px-0.5"><span>0%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div>
                  <span className="text-right">当前 / 对比</span>
                </div>
                {DIMENSIONS.map(({ key, label }) => {
                  const meta = report?.dimensions?.[key];
                  const evaluated = Boolean(meta?.available && meta?.score != null && meta?.status === 'ready');
                  const score = evaluated ? clampPercentage(meta.score) : 0;
                  const gap = score - targetScore;
                  const previousMeta = previousDimensions?.[key];
                  const previousAvailable = previousMeta?.score != null;
                  const previousScore = previousAvailable ? clampPercentage(previousMeta.score) : 0;
                  const changeFromPrevious = score - previousScore;
                  const comparablePrevious = previousAvailable && previousComparisonStatus === 'comparable';
                  return (
                    <div key={key} className="grid grid-cols-[86px_minmax(0,1fr)_108px] items-center gap-2">
                      <div className="text-[11px] font-bold text-slate-700">{label}</div>
                      <div className="relative h-5 overflow-hidden rounded-md bg-[#eff3f6]">
                        <div className="absolute inset-0 grid grid-cols-4">
                          <i className="border-r border-white/80" /><i className="border-r border-white/80" /><i className="border-r border-white/80" /><i />
                        </div>
                        {evaluated && <div className="absolute inset-y-0 left-0 rounded-lg bg-gradient-to-r from-[#65b2e4] to-[#3489ca]" style={{ width: `${score}%` }} />}
                        {!evaluated && <div className="absolute inset-0 z-[1] flex items-center px-2 text-[10px] text-slate-400">本次没有有效结果</div>}
                        <div className="absolute inset-y-0 z-[2] w-0.5 bg-[#e5a13a] shadow-[0_0_0_1px_rgba(255,255,255,.7)]" style={{ left: `${targetScore}%` }} />
                        {previousAvailable && (
                          <div
                            className="absolute top-1/2 z-[3] h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[#19537b] bg-white shadow-sm"
                            style={{ left: `${Math.max(1.5, Math.min(98.5, previousScore))}%` }}
                            title={`上次表现 ${previousScore.toFixed(1)}%`}
                          />
                        )}
                      </div>
                      <div className="text-right">
                        {evaluated ? (
                          <>
                            <div className="text-xs font-black text-[#17283c]">{score.toFixed(1)}%</div>
                            <div className={`text-[8px] font-bold ${gap >= 0 ? 'text-emerald-600' : 'text-amber-600'}`}>{gap >= 0 ? `较参考 +${gap.toFixed(1)}` : `较参考 -${Math.abs(gap).toFixed(1)}`}</div>
                          </>
                        ) : <div className="text-xs font-bold text-slate-400">未评估</div>}
                        {previousAvailable && (
                          <div className="mt-0.5 text-[8px] font-semibold text-[#19537b]">
                            {comparablePrevious && evaluated
                              ? `上次 ${previousScore.toFixed(1)} · ${changeFromPrevious >= 0 ? '+' : ''}${changeFromPrevious.toFixed(1)}`
                              : `上次 ${previousScore.toFixed(1)}${previousComparisonStatus === 'comparable' ? '' : ' · 口径不同'}`}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
              <p className="mt-3 border-t border-dashed border-slate-200 pt-2 text-[9px] leading-4 text-slate-400">
                {hasPreviousPerformance
                  ? previousComparisonStatus === 'comparable'
                    ? `上次基线来自 ${formatReportTime(previousPerformance?.generatedAt)} 的已发布报告；升降只比较两次都有结果的同一维度。`
                    : `上次基线来自 ${formatReportTime(previousPerformance?.generatedAt)} 的已发布报告，但评分公式口径不同，仅展示位置，不计算升降结论。`
                  : '当前没有更早且包含有效维度的已发布报告，因此不绘制上次基线。'}
                训练参考线可在 Server 报告评分配置中调整，不是年龄常模、百分位或诊断阈值。
              </p>
                </article>
                <article className="min-w-0 rounded-[16px] border border-slate-200 bg-white p-3">
              <h2 className="border-l-[3px] border-[#3489ca] pl-2.5 text-base font-black text-[#17283c]">核心数据与过程监测</h2>
              <div className="mt-3 grid grid-cols-3 gap-1.5">
                <div className="rounded-lg border border-slate-200 bg-[#fbfdff] p-2">
                  <div className="text-[9px] font-bold text-slate-500">综合任务表现</div>
                  <div className="mt-1 text-sm font-black text-[#17283c]">{kpi.taskPerformance != null ? `${Number(kpi.taskPerformance).toFixed(1)}%` : '未评估'}</div>
                  <div className="mt-1 text-[8px] leading-3 text-slate-400">按有效课程平衡计算</div>
                </div>
                <div className="rounded-lg border border-slate-200 bg-[#fbfdff] p-2">
                  <div className="text-[9px] font-bold text-slate-500">平均响应时长</div>
                  <div className="mt-1 text-sm font-black text-[#17283c]">{kpi.avgResponseSec != null ? `${Number(kpi.avgResponseSec).toFixed(1)} 秒` : '未评估'}</div>
                  <div className="mt-1 text-[8px] leading-3 text-slate-400">仅统计有效响应</div>
                </div>
                <div className="rounded-lg border border-slate-200 bg-[#fbfdff] p-2">
                  <div className="text-[9px] font-bold text-slate-500">主要情绪状态</div>
                  <div className="mt-1 text-xs font-black text-[#17283c]">{emotionReady ? emotion.label : '数据不足'}</div>
                  {emotionReady && [emotion.happy, emotion.focus, emotion.frustration].every((value) => value != null) && (
                    <>
                      <div className="mt-2 flex h-1 overflow-hidden rounded-full bg-slate-100">
                        <i className="bg-emerald-500" style={{ width: `${clampPercentage(emotion.happy)}%` }} />
                        <i className="bg-[#54a3d6]" style={{ width: `${clampPercentage(emotion.focus)}%` }} />
                        <i className="bg-amber-400" style={{ width: `${clampPercentage(emotion.frustration)}%` }} />
                      </div>
                      <div className="mt-1 text-[8px] leading-3 text-slate-400">愉悦 {Number(emotion.happy).toFixed(0)} · 专注 {Number(emotion.focus).toFixed(0)} · 急躁 {Number(emotion.frustration).toFixed(0)}</div>
                    </>
                  )}
                </div>
              </div>

              <div className="mt-3 rounded-xl border border-slate-200 bg-white p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-xs font-black text-[#17283c]">训练期间注意力变化</h3>
                  <span className="text-[9px] text-slate-400">课程开始 → 结束</span>
                </div>
                <ModuleBlock status={report?.modules?.attentionCurve} timedOut={timedOut} missingLabel="本次没有足够的注意力过程数据">
                  {curvePoints ? (
                    <div className="mt-2 rounded-lg bg-[#f4faff] p-2">
                      <svg viewBox="0 0 760 120" className="h-20 w-full" preserveAspectRatio="none" aria-label="训练期间注意力变化曲线">
                        <line x1="0" y1="60" x2="760" y2="60" stroke="#cce8f8" strokeDasharray="8 8" />
                        <polyline points={`0,120 ${curvePoints} 760,120`} fill="rgba(52,137,202,.08)" stroke="none" />
                        <polyline points={curvePoints} fill="none" stroke="#3489ca" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
                        {curveCoordinates.map((point, index) => <circle key={index} cx={point.x} cy={point.y} r="4" fill="#fff" stroke="#3489ca" strokeWidth="3" />)}
                      </svg>
                      <div className="mt-1 flex justify-between text-[9px] text-slate-400"><span>开始</span><span>结束</span></div>
                    </div>
                  ) : <div className="py-4 text-center text-xs text-slate-400">本次没有足够的注意力过程数据</div>}
                </ModuleBlock>
              </div>
                </article>
              </div>

              <article className="min-w-0 rounded-[16px] border border-slate-200 bg-white p-3" aria-label="本次课程得分">
                <div className="flex flex-wrap items-end justify-between gap-2">
                  <div>
                    <h2 className="border-l-[3px] border-[#3489ca] pl-2.5 text-base font-black text-[#17283c]">本次课程得分</h2>
                    <p className="mt-1 text-[10px] text-slate-500">仅展示 Demo 启用的配对和排序；未评估或数据不足不会按 0 分计入综合表现。</p>
                  </div>
                  <span className="text-[9px] text-slate-400">训练参考线 {targetScore.toFixed(0)}%</span>
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
                  {courseEvaluations.map((course) => {
                    const evaluated = course.status === 'evaluated' && course.score != null;
                    const score = evaluated ? clampPercentage(course.score) : 0;
                    const sampleText = courseSampleText(course);
                    const provisionalScore = course.provisionalScore == null
                      ? null
                      : clampPercentage(course.provisionalScore);
                    const sampleAdequacy = clampPercentage(Number(course.sampleAdequacy || 0) * 100);
                    const courseTarget = clampPercentage(course.targetScore ?? targetScore);
                    const gap = score - courseTarget;
                    return (
                      <div key={course.courseType} className="min-w-0 rounded-xl border border-slate-200 bg-[#fbfdff] p-2.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-[11px] font-black text-slate-700">{course.label}</span>
                          <i className={`h-2 w-2 shrink-0 rounded-full ${evaluated ? (gap >= 0 ? 'bg-emerald-500' : 'bg-amber-400') : 'bg-slate-300'}`} />
                        </div>
                        <div className={`mt-1 text-base font-black ${evaluated ? 'text-[#17283c]' : 'text-slate-400'}`}>{courseStatusText(course)}</div>
                        <div className="mt-1 text-[9px] leading-3 text-slate-400">
                          {evaluated
                            ? (gap >= 0 ? `高于参考线 ${gap.toFixed(1)} 个百分点` : `距离参考线 ${Math.abs(gap).toFixed(1)} 个百分点`)
                            : (course.status === 'insufficient_data'
                              ? `${sampleText || '有效样本不足'}；${provisionalScore == null ? '暂未形成分数' : `暂定 ${provisionalScore.toFixed(1)}%，不计入综合表现`}`
                              : '本次没有有效课程结果')}
                        </div>
                        {evaluated && sampleText && <div className="mt-1 text-[9px] text-slate-400">{sampleText}，已达到最低样本量</div>}
                        <div className="relative mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
                          {evaluated && <div className="absolute inset-y-0 left-0 rounded-full bg-[#3489ca]" style={{ width: `${score}%` }} />}
                          {!evaluated && course.status === 'insufficient_data' && <div className="absolute inset-y-0 left-0 rounded-full bg-slate-300" style={{ width: `${sampleAdequacy}%` }} />}
                          {evaluated && <div className="absolute inset-y-0 z-[2] w-px bg-[#e5a13a]" style={{ left: `${courseTarget}%` }} />}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </article>
            </div>
          </section>

          <section>
            <div className="mb-2 flex flex-wrap items-end justify-between gap-2 border-l-[3px] border-[#3489ca] pl-2.5">
              <div>
                <h2 className="text-base font-black text-[#17283c]">后续训练建议</h2>
                <p className="mt-0.5 text-[11px] text-slate-500">依据本次评估结果，按优先顺序呈现训练内容、建议依据与成效判据。</p>
              </div>
            </div>
            {recommendations.length ? (
              <div className={`grid gap-3 ${recommendations.length > 1 ? 'lg:grid-cols-2' : 'grid-cols-1'}`}>
                {recommendations.map((recommendation, index) => (
                  <article key={`${recommendation.courseType}-${index}`} className="break-inside-avoid rounded-[16px] border border-slate-200 bg-white p-3.5 shadow-[0_3px_12px_rgba(33,55,78,.045)]">
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="text-base font-black text-[#17283c]">{recommendation.title}</h3>
                      <span className={`shrink-0 rounded-full px-2.5 py-1 text-[10px] font-black ${recommendation.priority.startsWith('优先') ? 'bg-rose-50 text-rose-700' : recommendation.priority.startsWith('巩固') ? 'bg-emerald-50 text-emerald-700' : 'bg-sky-50 text-sky-700'}`}>{recommendation.priority}</span>
                    </div>
                    {recommendation.legacySingle ? (
                      <div className="mt-2 rounded-xl bg-sky-50 p-3 text-xs leading-5 text-slate-700">{recommendation.body}</div>
                    ) : (
                      <div className="mt-2 space-y-2 text-xs">
                        {recommendation.evidence && <div className="rounded-lg border border-sky-100 bg-sky-50 px-2.5 py-2 leading-5"><strong className="text-[#2b6f9f]">评估依据：</strong>{recommendation.evidence}</div>}
                        <div className="grid gap-2 sm:grid-cols-2">
                          <div className="rounded-lg bg-[#f7f9fb] p-2.5 leading-5"><strong className="block text-[11px] text-[#2b6f9f]">训练内容</strong><span className="mt-0.5 block text-slate-700">{recommendation.practice || recommendation.body}</span></div>
                          <div className="rounded-lg bg-[#fff9ef] p-2.5 leading-5"><strong className="block text-[11px] text-amber-700">建议依据</strong><span className="mt-0.5 block text-slate-700">{recommendation.why || '用于巩固本次相对薄弱的课程表现。'}</span></div>
                        </div>
                        <div className="rounded-lg bg-emerald-50 px-2.5 py-2 leading-5"><strong className="text-emerald-700">成效判据：</strong>{recommendation.progressCheck || '连续多次训练达到当前训练参考目标。'}</div>
                      </div>
                    )}
                  </article>
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-center text-xs text-slate-500">本次没有足够结果形成针对性建议，请先补充有效课程评估。</div>
            )}
          </section>

          {(translatedLimitations.length > 0 || timedOut || isPartial) && (
            <section className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
              <strong>数据完整性：</strong>
              {timedOut
                ? '部分过程数据暂未形成有效结果，相关项目已按“数据不足”或“未评估”展示。'
                : isPartial
                  ? '部分过程数据仍在整理，当前没有结果的课程不会按 0 分计算。'
                  : translatedLimitations.slice(0, 4).join('；')}
            </section>
          )}
        </div>

        <footer className="flex flex-col gap-2 border-t border-slate-200 bg-[#fafcfd] px-5 py-3 text-[11px] leading-4 text-slate-500 sm:flex-row sm:items-center sm:justify-between md:px-6">
          <div>{narrative.disclaimer || '本报告用于教育训练观察，仅反映当前任务情境，不构成诊断或医疗建议。'}</div>
          <div className="shrink-0 font-semibold">根据本次课程有效结果生成</div>
        </footer>
      </main>
    </div>
  );
}
