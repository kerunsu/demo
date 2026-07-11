import type { ProfessionalReportV2, TrainingReport } from "../../types";
import { deriveReportMetrics } from "./reportMetrics";
import { AttentionCurveChart } from "./AttentionCurveChart";
import { CapabilityRadarChart } from "./CapabilityRadarChart";
import { EmotionSummaryCard } from "./EmotionSummaryCard";

type Props = {
  report: TrainingReport;
  childName: string;
  narrativeLoading?: boolean;
};

function ReportNarrativeLoadingPanel({ title }: { title: string }) {
  return (
    <div className="report-narrative-loading" role="status" aria-live="polite">
      <div className="report-narrative-loading-spinner" aria-hidden="true" />
      <div className="report-narrative-loading-copy">
        <strong>{title}</strong>
        <p>AI 正在根据本次训练数据生成深度解读与教育建议，请稍候…</p>
      </div>
    </div>
  );
}

export function ProfessionalReportV2Content({ report, childName, narrativeLoading = false }: Props) {
  const reportMetrics = deriveReportMetrics(report);
  const v2 = report.professionalReportV2;
  const narrativePending = narrativeLoading || v2?.narrative.status === "PENDING";
  const overallScore = v2?.overallScore ?? reportMetrics.score;
  const dimensions = v2?.dimensions ?? {
    ordering: reportMetrics.score,
    matching: reportMetrics.score,
    receptiveLanguage: reportMetrics.score,
    attention: reportMetrics.score,
    expressiveLanguage: reportMetrics.score
  };

  return (
    <>
      <header className="report-detail-header">
        <div className="report-detail-brand">
          <h1>FUN ACADEMY</h1>
          <p>儿童认知训练观察系统</p>
        </div>
        <div className="report-detail-meta">
          报告流水号：<strong>#{report.reportId.slice(0, 12).toUpperCase()}</strong>
          <br />
          受测学员：<strong>{childName}</strong>
          <br />
          训练完成时间：<strong>{new Date(report.completedAt).toLocaleString("zh-CN", { hour12: false })}</strong>
        </div>
      </header>

      <div className="report-detail-body">
        <div className="report-detail-content-left">
          <section className="report-detail-summary-grid">
            <div className="report-detail-score-panel">
              <div className="report-detail-score-ring">
                <span className="value">{overallScore}</span>
                <span className="label">综合得分</span>
              </div>
              <h3>
                表现评定：
                {overallScore >= 85 ? "稳定" : overallScore >= 70 ? "良好" : "需继续观察"}
              </h3>
              <p>{v2?.formulaVersion ?? "education-training-index-v1"} · 教育训练参考指数</p>
            </div>
            <CapabilityRadarChart dimensions={dimensions} />
          </section>

          <h3 className="report-detail-section-title">核心数据与过程监测 / Process Monitoring</h3>
          <section className="report-detail-kpi-row">
            <div className="report-detail-kpi-card">
              <div className="kpi-label">任务正确率</div>
              <div className="kpi-value">{((v2?.taskAccuracy ?? report.summary.accuracy) * 100).toFixed(0)}%</div>
              <div className="kpi-status kpi-status-up">结构化训练数据</div>
            </div>
            <div className="report-detail-kpi-card">
              <div className="kpi-label">平均响应时长</div>
              <div className="kpi-value">{(report.summary.averageResponseTimeMs / 1000).toFixed(1)}s</div>
              <div className="kpi-status kpi-status-blue">反应时长得分已纳入指数</div>
            </div>
            {v2 ? (
              <EmotionSummaryCard emotionSummary={v2.emotionSummary} />
            ) : (
              <div className="report-detail-kpi-card">
                <div className="kpi-label">主要情绪状态</div>
                <div className="kpi-value report-detail-emotion-title">数据不足</div>
                <div className="kpi-status kpi-status-warn">报告 V2 数据缺失</div>
              </div>
            )}
          </section>

          {v2 ? <AttentionCurveChart curve={v2.attentionCurve} /> : null}
          {v2?.attentionSummary ? (
            <p className="report-detail-attention-meta">
              注意力来源：{v2.attentionSummary.provider ?? "unknown"} · {v2.attentionSummary.algorithmVersion ?? "—"} ·
              观测 {v2.attentionSummary.observationCount} 次
              {v2.attentionSummary.degraded ? " · 含降级/mock 数据" : " · 本地 descriptor 分析"}
            </p>
          ) : null}
          {v2?.languageSummary ? (
            <p className="report-detail-attention-meta">
              表达性语言声学：{v2.languageSummary.provider ?? "unknown"} · {v2.languageSummary.algorithmVersion ?? "—"} ·
              回合 {v2.languageSummary.observationCount} 次
              {typeof v2.languageSummary.averageLoudnessRms === "number"
                ? ` · 响度 ${v2.languageSummary.averageLoudnessRms.toFixed(3)}`
                : ""}
              {typeof v2.languageSummary.averageClarityProxy === "number"
                ? ` · 清晰度 ${v2.languageSummary.averageClarityProxy.toFixed(2)}`
                : ""}
              {v2.languageSummary.degraded ? " · 含降级/模拟数据" : " · 浏览器 Web Audio 标量"}
            </p>
          ) : null}
        </div>

        <div className="report-detail-content-right">
          <h3 className="report-detail-section-title">深度诊断报告 / Deep Diagnosis</h3>
          {narrativePending ? (
            <ReportNarrativeLoadingPanel title="正在生成深度诊断报告" />
          ) : (
            <section className="report-detail-diagnosis-box report-detail-diagnosis-box-v2">
              <h4>专家系统分析建议：</h4>
              <p>
                {v2?.narrative.analysis ??
                  `根据本次训练数据，学员出现 ${report.errorStats.totalWrongAttempts} 次错误触发。建议后续适当增加多指令排序组合练习，增强执行功能与稳定性。`}
              </p>
            </section>
          )}

          <h3 className="report-detail-section-title">教育干预建议 / Recommendations</h3>
          {narrativePending ? (
            <ReportNarrativeLoadingPanel title="正在生成教育干预建议" />
          ) : (
            <section className="report-detail-advice-grid">
              {(v2?.narrative.recommendations ?? [
                "日常可增加多指令排序小游戏，通过生活化指令提升序列记忆和执行能力。",
                "在噪杂环境中进行简短视觉寻找任务，帮助建立更强的过滤噪音与锁定目标能力。"
              ]).map((text, index) => (
                <div className="report-detail-advice-item" key={`${index}-${text.slice(0, 12)}`}>
                  <div className="report-detail-advice-icon" aria-hidden="true">
                    {index === 0 ? "🧩" : index === 1 ? "🧠" : "📋"}
                  </div>
                  <div className="report-detail-advice-content">
                    <h5>{index === 0 ? "逻辑强化练习" : index === 1 ? "视觉搜索抗干扰" : "持续观察建议"}</h5>
                    <p>{text}</p>
                  </div>
                </div>
              ))}
            </section>
          )}
        </div>

        <footer className="report-detail-footer">
          <div>
            评估系统：{v2?.schemaVersion ?? "professional-report-v2"} · 生成器：
            {narrativePending ? "pending" : (v2?.narrative.generator ?? "rule_fallback")}
            {v2?.narrative.provider && !narrativePending ? ` · ${v2.narrative.provider}` : ""}
          </div>
          <div>
            数据质量：{v2?.dataQuality.status ?? "unknown"}
            {v2?.dataQuality.degraded ? " · 含降级项" : ""} · © 2026 奇趣校园认知实验室 - 本报告仅供教育参考
          </div>
        </footer>
      </div>
    </>
  );
}
