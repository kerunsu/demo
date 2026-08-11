import { CheckCircle2, Loader2, Star } from 'lucide-react';

export interface RatingOption {
  score: number;
  label: string;
  description: string;
}

const RATING_OPTIONS: RatingOption[] = [
  { score: 1, label: '需要大量协助', description: '需要持续示范、分步提示和直接协助' },
  { score: 2, label: '需要较多提示', description: '能部分参与，需要多次提示或明显协助' },
  { score: 3, label: '基本完成', description: '在少量提示下完成，表现基本稳定' },
  { score: 4, label: '独立完成', description: '基本独立且准确完成，反应较流畅' },
  { score: 5, label: '熟练完成', description: '独立、准确、迅速，并有主动或迁移表现' },
];

const optionStyles = [
  'from-stone-50 to-stone-100 text-stone-700',
  'from-amber-50 to-orange-50 text-amber-800',
  'from-sky-50 to-blue-50 text-sky-800',
  'from-indigo-50 to-violet-50 text-indigo-800',
  'from-emerald-50 to-teal-50 text-emerald-800',
];

interface TeacherRatingDialogProps {
  open: boolean;
  courseName: string;
  itemName: string;
  selectedRating: number | null;
  saving: boolean;
  error: string | null;
  onSelect: (rating: number) => void;
  onCancel: () => void;
  onConfirm: () => void;
}

export function TeacherRatingDialog({
  open,
  courseName,
  itemName,
  selectedRating,
  saving,
  error,
  onSelect,
  onCancel,
  onConfirm,
}: TeacherRatingDialogProps) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/55 px-4 py-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="teacher-rating-title"
      onKeyDown={(event) => {
        if (event.key === 'Escape') event.preventDefault();
      }}
    >
      <div className="w-full max-w-5xl overflow-hidden rounded-[28px] border border-white/70 bg-white shadow-[0_28px_90px_rgba(15,23,42,0.32)]">
        <div className="flex items-start justify-between gap-6 border-b border-slate-100 bg-gradient-to-r from-indigo-50 via-white to-sky-50 px-7 py-5">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full bg-indigo-100 px-3 py-1 text-xs font-semibold text-indigo-700">
              <Star className="h-3.5 w-3.5 fill-indigo-500" />
              逐题表现记录
            </div>
            <h2 id="teacher-rating-title" className="text-2xl font-bold text-slate-900">请评价本题表现</h2>
            <p className="mt-1 text-sm text-slate-500">
              {courseName}<span className="mx-2 text-slate-300">/</span>{itemName || '综合任务'}
            </p>
          </div>
          <div className="rounded-2xl bg-white/80 px-4 py-3 text-right shadow-sm ring-1 ring-slate-100">
            <div className="text-xs text-slate-400">评分后继续</div>
            <div className="mt-0.5 font-semibold text-slate-700">1–5 分能力量表</div>
          </div>
        </div>

        <div className="px-6 py-5">
          <div className="grid grid-cols-5 gap-3">
            {RATING_OPTIONS.map((option, index) => {
              const selected = selectedRating === option.score;
              return (
                <button
                  key={option.score}
                  type="button"
                  disabled={saving}
                  onClick={() => onSelect(option.score)}
                  className={`relative min-h-[166px] rounded-2xl border bg-gradient-to-b p-4 text-left transition-all duration-200 disabled:cursor-wait ${optionStyles[index]} ${
                    selected
                      ? 'border-indigo-500 shadow-[0_12px_32px_rgba(79,70,229,0.18)] ring-2 ring-indigo-200 -translate-y-1'
                      : 'border-slate-200 shadow-sm hover:-translate-y-0.5 hover:border-indigo-300 hover:shadow-lg'
                  }`}
                  aria-pressed={selected}
                >
                  {selected && <CheckCircle2 className="absolute right-3 top-3 h-5 w-5 text-indigo-600" />}
                  <div className="text-4xl font-black leading-none">{option.score}</div>
                  <div className="mt-3 text-sm font-bold leading-5">{option.label}</div>
                  <div className="mt-2 text-xs leading-5 opacity-75">{option.description}</div>
                </button>
              );
            })}
          </div>

          {error && (
            <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              评分保存失败：{error}。请检查连接后重试。
            </div>
          )}

          <div className="mt-5 flex items-center justify-between gap-4 border-t border-slate-100 pt-5">
            <p className="max-w-xl text-xs leading-5 text-slate-400">
              评分会与本题正确率、响应时长等数据一起进入训练报告。返回当前题不会保存，也不会切换内容。
            </p>
            <div className="flex shrink-0 gap-3">
              <button
                type="button"
                disabled={saving}
                onClick={onCancel}
                className="rounded-xl border border-slate-300 bg-white px-5 py-3 font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-50"
              >
                返回当前题
              </button>
              <button
                type="button"
                disabled={saving || selectedRating == null}
                onClick={onConfirm}
                className="inline-flex min-w-[178px] items-center justify-center gap-2 rounded-xl bg-indigo-600 px-6 py-3 font-semibold text-white shadow-lg shadow-indigo-200 transition-all hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-45 disabled:shadow-none"
              >
                {saving ? <><Loader2 className="h-4 w-4 animate-spin" />正在记录…</> : '记录评分并继续'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
