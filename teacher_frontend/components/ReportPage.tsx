import { useCallback, useEffect, useMemo, useState } from 'react';

interface ReportPageProps {
  trainingSessionId: string;
  studentName?: string | null;
  onBack: () => void;
}

type DimensionKey =
  | 'attention'
  | 'expressiveLanguage'
  | 'receptiveLanguage'
  | 'matching'
  | 'ordering';

const DIM_LABELS: Record<DimensionKey, string> = {
  attention: '注意力',
  expressiveLanguage: '表达性语言',
  receptiveLanguage: '接受性语言',
  matching: '配对',
  ordering: '排序',
};

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
const POLL_MS = 1500;
const POLL_MAX_MS = 45000;

function ModuleBlock({
  status,
  timedOut,
  children,
  pendingLabel = '该模块加载中…',
  missingLabel = '本课未采集到数据',
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
      <div className="border border-dashed border-slate-300 rounded-xl p-6 text-center text-slate-500 text-sm animate-pulse">
        {pendingLabel}
      </div>
    );
  }
  if (effective === 'missing' || !effective) {
    return (
      <div className="border border-slate-200 rounded-xl p-6 text-center text-slate-400 text-sm">
        {missingLabel}
      </div>
    );
  }
  return <>{children}</>;
}

export function ReportPage({ trainingSessionId, studentName, onBack }: ReportPageProps) {
  const [report, setReport] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);
  const [awaitingPublish, setAwaitingPublish] = useState(false);
  // 默认横板，对齐样例可切换
  const [layout, setLayout] = useState<'landscape' | 'portrait'>('landscape');
  const isLandscape = layout === 'landscape';

  const fetchPublishedReport = useCallback(async () => {
    const getRes = await fetch(`${API_BASE}/api/report/${trainingSessionId}?role=teacher`);
    const getJson = await getRes.json();
    if (getRes.status === 409 || getJson?.error === 'report_not_published') {
      const err: any = new Error('report_not_published');
      err.code = 'report_not_published';
      throw err;
    }
    if (getJson?.success && getJson.data) return getJson.data;
    throw new Error(getJson?.error || '报告加载失败');
  }, [trainingSessionId]);

  const handleManualRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const data = await fetchPublishedReport();
      setReport(data);
      setError(null);
      setAwaitingPublish(false);
      const pending = Object.values(data.modules || {}).some((s) => s === 'pending');
      if (!pending) setTimedOut(false);
    } catch (e: any) {
      if (e?.code === 'report_not_published' || e?.message === 'report_not_published') {
        setAwaitingPublish(true);
        setError(null);
      } else {
        setError(e?.message || String(e));
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

        const elapsed = Date.now() - started;
        const pending = Object.values(data.modules || {}).some((s) => s === 'pending');
        if (data.status === 'READY' || !pending) return;
        if (elapsed >= POLL_MAX_MS) {
          setTimedOut(true);
          return;
        }
        timer = window.setTimeout(() => loop(), POLL_MS);
      } catch (e: any) {
        if (cancelled) return;
        if (e?.code === 'report_not_published' || e?.message === 'report_not_published') {
          setAwaitingPublish(true);
          setLoading(false);
          setError(null);
          timer = window.setTimeout(() => loop(), POLL_MS);
          return;
        }
        setError(e?.message || String(e));
        setLoading(false);
      }
    }

    loop();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [trainingSessionId, fetchPublishedReport]);

  const dimStatus = (key: DimensionKey) => report?.dimensions?.[key]?.status as string | undefined;

  const radarPoints = useMemo(() => {
    const dims = report?.dimensions || {};
    const order: DimensionKey[] = [
      'attention',
      'expressiveLanguage',
      'receptiveLanguage',
      'matching',
      'ordering',
    ];
    const cx = 100;
    const cy = 100;
    const r = 70;
    return order.map((key, i) => {
      const angle = -Math.PI / 2 + (i * 2 * Math.PI) / order.length;
      const ready = dims[key]?.status === 'ready' || dims[key]?.available;
      const score = ready ? Number(dims[key].score || 0) : 0;
      const rr = (score / 100) * r;
      return {
        key,
        label: DIM_LABELS[key],
        x: cx + Math.cos(angle) * rr,
        y: cy + Math.sin(angle) * rr,
        lx: cx + Math.cos(angle) * (r + 18),
        ly: cy + Math.sin(angle) * (r + 18),
        score,
        ready: !!ready,
      };
    });
  }, [report]);

  const curvePoints = useMemo(() => {
    const curve = (report?.attentionCurve || []).filter((c: any) => c.score != null);
    if (!curve.length) return '';
    const w = 760;
    const h = 100;
    return curve
      .map((c: any, i: number) => {
        const x = curve.length === 1 ? 0 : (i / (curve.length - 1)) * w;
        const score = Number(c.score);
        const y = h - (score / 100) * (h - 10) - 5;
        return `${x},${y}`;
      })
      .join(' ');
  }, [report]);

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

  if (loading && !report) {
    return (
      <div className="min-h-screen bg-slate-100 flex items-center justify-center">
        <div className="text-slate-600">正在加载报告…</div>
      </div>
    );
  }

  if (awaitingPublish && !report) {
    return (
      <div className="min-h-screen bg-slate-100 flex flex-col items-center justify-center gap-4 p-6">
        <div className="text-slate-700 text-center max-w-md">
          报告尚未由服务端推送。请在 /server 实时监控完成审核后（直接推送或修改后推送），再查看。
        </div>
        <button onClick={onBack} className="px-4 py-2 bg-slate-800 text-white rounded-lg">返回</button>
      </div>
    );
  }

  if (error && !report) {
    return (
      <div className="min-h-screen bg-slate-100 flex flex-col items-center justify-center gap-4 p-6">
        <div className="text-red-600">报告加载失败：{error}</div>
        <button onClick={onBack} className="px-4 py-2 bg-slate-800 text-white rounded-lg">返回</button>
      </div>
    );
  }

  const narrative = report?.narrative || {};
  const kpi = report?.kpi || {};
  const responseCoverage = (kpi.responseCoveredCourseTypes || []) as string[];
  const courseTypeLabels: Record<string, string> = {
    mimic: '模仿',
    naming: '命名',
    onomatopoeia: '拟声',
    pairing: '配对',
    ordering: '排序',
  };
  const limitations = report?.dataQuality?.limitations || [];
  const limitationLabels: string[] =
    (report?.dataQuality?.limitationLabels as string[] | undefined)?.length
      ? (report.dataQuality.limitationLabels as string[])
      : limitations;
  const formulaVersion = report?.formulaVersion || report?.schemaVersion;
  const isPartial = report?.status === 'PARTIAL' && !timedOut;

  const summaryBlock = (
    <div className={`grid gap-4 mb-5 ${isLandscape ? 'grid-cols-2' : 'grid-cols-1 sm:grid-cols-2'}`}>
      <ModuleBlock status={report?.overall != null ? 'ready' : 'pending'} timedOut={timedOut} pendingLabel="综合得分计算中…">
        <div className="bg-sky-50 rounded-2xl p-5 text-center h-full">
          <div className={`${isLandscape ? 'w-28 h-28 border-[10px]' : 'w-36 h-36 border-[12px]'} mx-auto rounded-full border-sky-600 bg-white flex flex-col items-center justify-center shadow`}>
            <div className={`${isLandscape ? 'text-3xl' : 'text-4xl'} font-extrabold`}>{report?.overall ?? '—'}</div>
            <div className="text-xs text-slate-500 font-semibold">综合得分</div>
          </div>
          <h3 className="mt-3 text-base font-semibold">表现评定：{report?.grade || '—'}</h3>
          <p className="text-xs text-slate-500 mt-1">
            {report?.overallNote || '教育训练参考指数，非临床诊断'}
          </p>
        </div>
      </ModuleBlock>

      <div className="border border-slate-200 rounded-2xl p-4 flex flex-col items-center">
        <p className="text-sm font-bold text-slate-500 mb-2">核心能力五维分布图</p>
        <svg viewBox="-20 -10 240 220" className={`w-full ${isLandscape ? 'max-w-[220px]' : 'max-w-xs'}`}>
          <polygon points="100,30 166.5,75 141,155 59,155 33.5,75" fill="none" stroke="#e2e8f0" />
          <polygon points="100,65 133,90 120,130 80,130 67,90" fill="none" stroke="#e2e8f0" />
          <polygon
            points={radarPoints.map((p) => `${p.x},${p.y}`).join(' ')}
            fill="rgba(2,132,199,0.2)"
            stroke="#0284c7"
            strokeWidth="2"
          />
          {radarPoints.map((p) => (
            <text
              key={p.key}
              x={p.lx}
              y={p.ly}
              fontSize="11"
              fill={p.ready ? '#64748b' : '#cbd5e1'}
              textAnchor="middle"
            >
              {p.label}
            </text>
          ))}
        </svg>
        <div className="text-xs text-slate-400 mt-1">灰色标签表示该维仍在加载或未采集</div>
      </div>
    </div>
  );

  const processBlock = (
    <div className="mb-5">
      <h3 className="text-base font-bold border-l-4 border-sky-600 pl-3 mb-3">核心数据与过程监测</h3>
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="border border-slate-200 rounded-xl p-3">
          <div className="text-[11px] font-bold text-slate-500 uppercase mb-1">综合任务表现</div>
          <div className="text-xl font-bold">
            {kpi.taskPerformance != null ? `${kpi.taskPerformance}%` : (timedOut ? '—' : '加载中')}
          </div>
          <div className="mt-1 text-[10px] text-slate-400">客观指标与教师评分按课程类型平衡</div>
        </div>
        <div className="border border-slate-200 rounded-xl p-3">
          <div className="text-[11px] font-bold text-slate-500 uppercase mb-1">平均响应时长</div>
          <div className="text-xl font-bold">{kpi.avgResponseSec != null ? `${kpi.avgResponseSec}s` : '—'}</div>
          <div className="mt-1 text-[10px] text-slate-400">
            {responseCoverage.length
              ? `覆盖：${responseCoverage.map((key) => courseTypeLabels[key] || key).join('、')}`
              : '暂无有效时长'}
          </div>
        </div>
        <div className="border border-slate-200 rounded-xl p-3">
          <div className="text-[11px] font-bold text-slate-500 uppercase mb-1">主要情绪状态</div>
          <div className="text-sm font-semibold flex items-center gap-1">
            {kpi.emotion?.label && kpi.emotion.label !== '数据不足' ? (
              <>
                <span className="text-emerald-600">☺</span>
                <span>{kpi.emotion.label}</span>
              </>
            ) : (
              <span className="text-slate-400">数据不足</span>
            )}
          </div>
          {kpi.emotion?.happy != null && kpi.emotion?.focus != null && kpi.emotion?.frustration != null ? (
            <>
              <div className="flex w-full h-1.5 rounded overflow-hidden mt-2 bg-slate-100">
                <div className="bg-emerald-500" style={{ width: `${kpi.emotion.happy}%` }} />
                <div className="bg-sky-500" style={{ width: `${kpi.emotion.focus}%` }} />
                <div className="bg-amber-500" style={{ width: `${kpi.emotion.frustration}%` }} />
              </div>
              <div className="flex justify-between text-[10px] text-slate-500 font-semibold mt-1">
                <span>愉悦 {kpi.emotion.happy}%</span>
                <span>专注 {kpi.emotion.focus}%</span>
                <span>急躁 {kpi.emotion.frustration}%</span>
              </div>
            </>
          ) : (
            <div className="text-[11px] text-slate-400 mt-1">需至少 2 帧有效情绪样本</div>
          )}
        </div>
      </div>

      <div className="border border-slate-200 rounded-xl p-3 mb-3">
        <div className="flex justify-between mb-2">
          <div className="text-sm font-bold">训练期间注意力波动曲线</div>
          <div className="text-xs text-slate-500">X: 课点序 | Y: 专注度</div>
        </div>
        <ModuleBlock
          status={report?.modules?.attentionCurve || dimStatus('attention')}
          timedOut={timedOut}
          pendingLabel="注意力曲线加载中…"
          missingLabel="暂无注意力曲线数据"
        >
          {curvePoints ? (
            <svg viewBox="0 0 760 100" className="w-full h-24" preserveAspectRatio="none">
              <polyline points={curvePoints} fill="none" stroke="#0284c7" strokeWidth="2" />
            </svg>
          ) : (
            <div className="text-sm text-slate-400 py-6 text-center">暂无注意力曲线数据</div>
          )}
        </ModuleBlock>
      </div>

      <div className="grid grid-cols-5 gap-2 text-xs">
        {(Object.keys(DIM_LABELS) as DimensionKey[]).map((key) => {
          const st = dimStatus(key);
          const eff = timedOut && st === 'pending' ? 'missing' : st;
          const score = report?.dimensions?.[key]?.score;
          return (
            <div key={key} className="border border-slate-200 rounded-lg p-2 text-center">
              <div className="text-slate-500 mb-1">{DIM_LABELS[key]}</div>
              <div className="font-bold">
                {eff === 'ready' ? score : eff === 'pending' ? '…' : '—'}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );

  const narrativeBlock = (
    <div className={isLandscape ? '' : 'mb-5'}>
      <ModuleBlock status={report?.modules?.narrative} timedOut={timedOut} pendingLabel="分析建议生成中…">
        <div className="bg-sky-50 border border-sky-200 rounded-xl p-4 mb-4">
          <h4 className="text-sky-700 font-semibold mb-2">专家系统分析建议</h4>
          <p className="text-sm leading-7 text-slate-800">{narrative.analysis || '—'}</p>
        </div>
      </ModuleBlock>
      <h3 className="text-base font-bold border-l-4 border-sky-600 pl-3 mb-3">教育干预建议</h3>
      <ModuleBlock status={report?.modules?.narrative} timedOut={timedOut} pendingLabel="建议加载中…">
        <div className="space-y-3">
          {(narrative.recommendations || []).map((r: any, idx: number) => (
            <div key={idx} className="border border-slate-200 rounded-xl p-3 bg-slate-50">
              <div className="font-semibold mb-1 text-sm">{r.title}</div>
              <div className="text-sm text-slate-600 leading-6">{r.body}</div>
            </div>
          ))}
        </div>
      </ModuleBlock>
    </div>
  );

  return (
    <div className="min-h-screen bg-slate-100 text-slate-800 print:bg-white">
      <div
        className={`sticky top-0 z-10 bg-white/95 border-b border-slate-200 px-6 py-3 flex items-center justify-between mx-auto ${
          isLandscape ? 'max-w-[1160px]' : 'max-w-[900px]'
        }`}
      >
        <div>
          <div className="font-semibold">儿童认知训练评估报告</div>
          <div className="text-xs text-slate-500">
            当前模式：{isLandscape ? '横版 A4 (Landscape)' : '竖版 A4 (Portrait)'}
            {' · '}
            {trainingSessionId.slice(0, 8)}…
            {isPartial ? ' · 部分模块加载中' : ''}
          </div>
        </div>
        <div className="flex gap-2 flex-wrap justify-end">
          <button
            onClick={() => setLayout((v) => (v === 'landscape' ? 'portrait' : 'landscape'))}
            className="px-4 py-2 rounded-lg bg-white border border-slate-300 text-slate-700 text-sm"
          >
            切换横/竖版
          </button>
          <button
            onClick={handleManualRefresh}
            disabled={refreshing || loading}
            className="px-4 py-2 rounded-lg bg-white border border-slate-300 text-slate-700 text-sm disabled:opacity-60"
          >
            {refreshing ? '刷新中…' : '刷新报告'}
          </button>
          <button onClick={() => window.print()} className="px-4 py-2 rounded-lg bg-sky-600 text-white text-sm">打印</button>
          <button onClick={onBack} className="px-4 py-2 rounded-lg bg-slate-200 text-slate-800 text-sm">返回</button>
        </div>
      </div>

      <div
        className={`mx-auto my-6 bg-white shadow-lg rounded-xl overflow-hidden print:shadow-none print:my-0 ${
          isLandscape ? 'max-w-[1160px]' : 'max-w-[900px]'
        }`}
      >
        <div className={`${isLandscape ? 'px-10 pt-8 pb-4' : 'px-12 pt-10 pb-5'} border-b-4 border-slate-800 flex justify-between`}>
          <div>
            <h1 className="text-2xl font-bold tracking-wide">EVALUATION SYSTEM</h1>
            <p className="text-sky-600 text-sm font-semibold mt-1">儿童认知训练中心评估系统</p>
          </div>
          <div className="text-right text-sm text-slate-500 leading-7">
            <div>受测学员：<strong className="text-slate-800">{studentName || report?.studentId || '—'}</strong></div>
            <div>评估时间：<strong className="text-slate-800">{(report?.generatedAt || '').replace('T', ' ').replace('Z', '')}</strong></div>
          </div>
        </div>

        <div className={`${isLandscape ? 'px-10 py-6 grid grid-cols-2 gap-10' : 'px-12 py-8 block'}`}>
          <div>
            {summaryBlock}
            {processBlock}
          </div>
          <div className={isLandscape ? '' : 'mt-2'}>
            {narrativeBlock}
          </div>
        </div>

        {(limitationLabels.length > 0 || timedOut || isPartial) && (
          <div className={`${isLandscape ? 'px-10' : 'px-12'} pb-3 text-xs text-amber-700`}>
            数据质量说明：
            {timedOut
              ? '自动加载约 45 秒后仍有模块未就绪；可点右上角「刷新报告」再试，或按未采集展示。'
              : isPartial
                ? '报告会在约 45 秒内自动刷新；也可随时点「刷新报告」。'
                : limitationLabels.join('；')}
          </div>
        )}

        <div className={`${isLandscape ? 'px-10' : 'px-12'} py-4 border-t border-slate-200 text-xs text-slate-500 flex justify-between gap-4`}>
          <div>{narrative.disclaimer || '本报告仅供教育参考'}</div>
          <div className="text-right shrink-0">
            {formulaVersion ? <div>公式版本：{formulaVersion}</div> : null}
            <div>© Intelligent Media Innovation Lab</div>
          </div>
        </div>
      </div>
    </div>
  );
}
