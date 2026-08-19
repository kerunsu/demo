import { useCallback, useEffect, useState } from 'react';
import { Socket } from 'socket.io-client';
import { CheckCircle2, Loader2, RefreshCw, XCircle } from 'lucide-react';

export type ReadinessModuleId = 'M2';

export interface ReadinessCourseItem {
  courseId: string | number;
  itemId: string | number | null;
  courseType: string;
  file?: string;
}

type GateStatus = 'STARTING' | 'RECORDING_CONFIRMED' | 'FAILED' | 'CANCELLED';

interface GateState {
  status: GateStatus;
  ok: boolean;
  detail: string;
  progress01: number;
  error: string | null;
  deadlineAt: number;
}

const initialState: GateState = {
  status: 'STARTING',
  ok: false,
  detail: '正在启动本场录制',
  progress01: 0.1,
  error: null,
  deadlineAt: Date.now() + 30000,
};

export interface TrainingReadinessDialogProps {
  open: boolean;
  socket: Socket | null;
  studentId: string | null;
  trainingSessionId: string | null;
  items: ReadinessCourseItem[];
  onEnter: () => void;
  onCancel: () => void;
  /** When the media session was wiped (e.g. server restart), re-run prepare. */
  onReprepare?: () => Promise<string | null | void> | string | null | void;
}

function isSessionLostError(text: string | null | undefined): boolean {
  const value = String(text || '');
  return (
    value.includes('strict_preflight_session_not_found')
    || value.includes('录制会话已丢失')
    || value.includes('重新点击开始评估')
  );
}

/**
 * The dialog mirrors one server-owned fact: whether this recording has a
 * real video sample. Resource and voice checks are intentionally absent.
 */
export function TrainingReadinessDialog({
  open,
  socket,
  studentId,
  trainingSessionId,
  items,
  onEnter,
  onCancel,
  onReprepare,
}: TrainingReadinessDialogProps) {
  const [state, setState] = useState<GateState>(initialState);
  const [now, setNow] = useState(() => Date.now());
  const [retryToken, setRetryToken] = useState(0);
  const [retrying, setRetrying] = useState(false);

  const start = useCallback((retry = false) => {
    if (!socket || !studentId || !trainingSessionId || items.length === 0) {
      setState((current) => ({ ...current, status: 'FAILED', error: '缺少学生、训练会话或课程信息' }));
      return;
    }
    setState({
      status: 'STARTING',
      ok: false,
      detail: '正在启动本场录制',
      progress01: 0.1,
      error: null,
      deadlineAt: Date.now() + 30000,
    });
    const emitStart = () => socket.emit('readiness_start', {
      studentId: Number(studentId),
      trainingSessionId,
      items,
      timeoutMs: 30000,
      ...(retry ? { retry: true } : {}),
    });
    if (socket.connected) emitStart();
    else {
      socket.once('connect', emitStart);
      socket.connect();
    }
  }, [items, socket, studentId, trainingSessionId]);

  useEffect(() => {
    if (!open || !socket) return undefined;
    const onUpdate = (data: any) => {
      if (data?.trainingSessionId && data.trainingSessionId !== trainingSessionId) return;
      const snapshot = data?.snapshot || data;
      const module = snapshot?.modules?.find((item: any) => item.moduleId === 'M2');
      setState((current) => ({
        ...current,
        status: (snapshot?.status || (module?.status === 'success' ? 'RECORDING_CONFIRMED' : module?.status === 'failed' ? 'FAILED' : current.status)) as GateStatus,
        ok: Boolean(snapshot?.ok),
        detail: data?.detail || module?.detail || current.detail,
        progress01: typeof snapshot?.progress01 === 'number' ? snapshot.progress01 : (module?.progress01 ?? current.progress01),
        error: module?.status === 'failed' ? (data?.detail || module?.detail) : current.error,
        deadlineAt: snapshot?.deadlineAtMs || current.deadlineAt,
      }));
    };
    const onComplete = (data: any) => {
      if (data?.trainingSessionId && data.trainingSessionId !== trainingSessionId) return;
      setState((current) => ({
        ...current,
        status: data?.ok ? 'RECORDING_CONFIRMED' : 'FAILED',
        ok: Boolean(data?.ok),
        detail: data?.ok ? '服务器已收到有效视频，可以开课' : (data?.error || '录制未就绪'),
        progress01: data?.ok ? 1 : current.progress01,
        error: data?.ok ? null : (data?.error || current.error),
        deadlineAt: data?.deadlineAtMs || current.deadlineAt,
      }));
    };
    const onAck = (data: any) => {
      if (data?.success === false) setState((current) => ({ ...current, status: 'FAILED', error: data.error || '录制启动失败', detail: data.error || '录制启动失败' }));
      else if (data?.snapshot) onUpdate(data.snapshot);
    };
    socket.on('readiness_update', onUpdate);
    socket.on('readiness_complete', onComplete);
    socket.on('readiness_start_ack', onAck);
    start(retryToken > 0);
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      window.clearInterval(timer);
      socket.off('readiness_update', onUpdate);
      socket.off('readiness_complete', onComplete);
      socket.off('readiness_start_ack', onAck);
    };
  }, [open, retryToken, socket, start, trainingSessionId]);

  if (!open) return null;
  const confirmed = state.status === 'RECORDING_CONFIRMED' && state.ok;
  const failed = state.status === 'FAILED';
  const remaining = Math.max(0, Math.ceil((state.deadlineAt - now) / 1000));

  const cancel = () => {
    if (socket && trainingSessionId) socket.emit('readiness_cancel', { trainingSessionId, studentId: Number(studentId) });
    onCancel();
  };

  const retry = async () => {
    if (retrying) return;
    setRetrying(true);
    try {
      if (isSessionLostError(state.error || state.detail) && onReprepare) {
        await onReprepare();
        // Parent updates trainingSessionId; effect below restarts readiness.
        return;
      }
      setRetryToken((value) => value + 1);
    } catch (error: any) {
      setState((current) => ({
        ...current,
        status: 'FAILED',
        error: error?.message || String(error) || '重新准备录制失败',
        detail: error?.message || String(error) || '重新准备录制失败',
      }));
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/55 px-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white shadow-xl">
        <div className="border-b border-slate-100 px-6 py-5">
          <h2 className="text-xl font-bold text-slate-900">开课准备</h2>
          <p className="mt-1 text-sm text-slate-500">只确认本场录制已真正收到视频，其他诊断在后台继续。</p>
        </div>
        <div className="px-6 py-8">
          <div className="flex items-start gap-3">
            {confirmed ? <CheckCircle2 className="mt-0.5 h-6 w-6 shrink-0 text-emerald-500" /> : failed ? <XCircle className="mt-0.5 h-6 w-6 shrink-0 text-rose-500" /> : <Loader2 className="mt-0.5 h-6 w-6 shrink-0 animate-spin text-indigo-500" />}
            <div className="min-w-0">
              <div className="font-medium text-slate-900">{confirmed ? '录制已确认' : failed ? '录制没有就绪' : '正在启动本场录制'}</div>
              <div className="mt-1 text-sm leading-6 text-slate-600">{state.error || state.detail}</div>
              {!confirmed && !failed && <div className="mt-2 text-xs text-slate-400">等待服务器视频数据，最多 {remaining} 秒</div>}
            </div>
          </div>
          <div className="mt-6 h-2 overflow-hidden rounded-full bg-slate-100"><div className={`h-full transition-all ${failed ? 'bg-rose-400' : confirmed ? 'bg-emerald-500' : 'bg-indigo-500'}`} style={{ width: `${Math.round(state.progress01 * 100)}%` }} /></div>
        </div>
        <div className="flex items-center justify-between gap-3 border-t border-slate-100 px-6 py-4">
          <button type="button" onClick={cancel} className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100">返回选课</button>
          <div className="flex gap-2">
            {failed && (
              <button
                type="button"
                disabled={retrying}
                onClick={() => { void retry(); }}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
              >
                <RefreshCw className={`h-4 w-4 ${retrying ? 'animate-spin' : ''}`} />
                {isSessionLostError(state.error || state.detail) && onReprepare ? '重新准备并重试' : '重试录制'}
              </button>
            )}
            <button type="button" disabled={!confirmed} onClick={onEnter} className={`rounded-lg px-5 py-2 text-sm font-semibold text-white ${confirmed ? 'bg-indigo-600 hover:bg-indigo-700' : 'cursor-not-allowed bg-indigo-300'}`}>进入课堂</button>
          </div>
        </div>
      </div>
    </div>
  );
}
