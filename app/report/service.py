"""报告生成服务（支持 PARTIAL + refresh + 审核推送）"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import math
from typing import Any, Dict, List, Optional

from app.behavior import get_behavior_service
from app.behavior.store import get_behavior_store
from app.course_scope import enabled_course_types
from app.report.scoring import COURSE_LABELS, compute_dimensions, load_scoring_config
from app.report.narrative import generate_narrative
from app.report.limitations_copy import translate_limitations
from app.report.archive_sync import sync_student_archive_from_report
from app.utils.logger import setup_logger

logger = setup_logger("report_service")


def _emit(event: str, payload: Dict[str, Any]) -> None:
    try:
        from flask import current_app
        socketio = current_app.extensions.get("socketio")
        if socketio is not None:
            socketio.emit(event, payload)
    except Exception as e:
        logger.debug("emit %s 失败: %s", event, e)


def _sync_course_evaluations(report: Dict[str, Any]) -> None:
    """Keep the teacher chart aligned with Server-reviewed course scores."""
    scores = report.get("courseScores") if isinstance(report.get("courseScores"), dict) else {}
    existing = {
        str(item.get("courseType")): item
        for item in (report.get("courseEvaluations") or [])
        if isinstance(item, dict) and item.get("courseType")
    }
    try:
        default_target = float(report.get("courseGoalScore") or 70)
    except (TypeError, ValueError):
        default_target = 70.0
    default_target = max(0.0, min(100.0, default_target))

    evaluations: List[Dict[str, Any]] = []
    normalized_scores: Dict[str, Optional[float]] = {}
    for course_type in enabled_course_types():
        label = COURSE_LABELS.get(course_type, course_type)
        previous = existing.get(course_type) or {}
        raw_score = scores.get(course_type)
        score: Optional[float] = None
        try:
            candidate = float(raw_score) if raw_score is not None else None
            if candidate is not None and math.isfinite(candidate):
                score = round(max(0.0, min(100.0, candidate)), 1)
        except (TypeError, ValueError):
            score = None
        try:
            target = float(previous.get("targetScore", default_target))
        except (TypeError, ValueError):
            target = default_target
        target = round(max(0.0, min(100.0, target)), 1)
        observed = int(previous.get("itemCount") or 0)
        status = (
            "evaluated"
            if score is not None
            else "insufficient_data"
            if previous.get("status") == "insufficient_data" or observed > 0
            else "not_evaluated"
        )
        normalized_scores[course_type] = score
        evaluations.append({
            "courseType": course_type,
            "label": str(previous.get("label") or label),
            "status": status,
            "score": score,
            "targetScore": target,
            "gapToTarget": round(score - target, 1) if score is not None else None,
            "itemCount": observed,
            "teacherRatingCount": int(previous.get("teacherRatingCount") or 0),
        })
    report["courseScores"] = normalized_scores
    report["courseEvaluations"] = evaluations


class ReportService:
    def _build_report(
        self,
        training_session_id: str,
        summary_dict: Dict[str, Any],
        *,
        soft: bool = True,
    ) -> Dict[str, Any]:
        cfg = load_scoring_config()
        scored = compute_dimensions(summary_dict, cfg, soft=soft)
        attention_curve = (summary_dict.get("attention") or {}).get("curve") or []

        task_performance = scored.get("taskPerformance")
        response_metrics = scored.get("responseMetrics") or {}
        avg_response_ms = response_metrics.get("avgResponseMs")
        avg_response_sec = float(avg_response_ms) / 1000.0 if avg_response_ms is not None else None

        emotion = summary_dict.get("emotion") or {}
        emotion_kpi = {
            "label": emotion.get("label") or "数据不足",
            "happy": emotion.get("happy"),
            "focus": emotion.get("focus"),
            "frustration": emotion.get("frustration"),
            "positive": emotion.get("positive"),
            "focused": emotion.get("focused"),
            "frustrated": emotion.get("frustrated"),
            "status": emotion.get("status"),
        }

        return {
            "schemaVersion": "professional-report-v2",
            "courseScope": {
                "deployment": "demo-machine",
                "enabledCourseTypes": list(enabled_course_types()),
            },
            "formulaVersion": scored.get("formulaVersion"),
            "scoreBoundary": scored.get("scoreBoundary"),
            "trainingSessionId": training_session_id,
            "studentId": summary_dict.get("student_id"),
            "generatedAt": datetime.utcnow().isoformat() + "Z",
            "updatedAt": datetime.utcnow().isoformat() + "Z",
            "status": scored.get("status") or "PARTIAL",
            "publicationStatus": "pending_review",
            "manualOverride": False,
            "modules": scored.get("modules") or {},
            "overall": scored.get("overall"),
            "overallNote": scored.get("overallNote"),
            "grade": scored.get("grade"),
            "dimensions": scored.get("dimensions"),
            "courseScores": scored.get("courseScores") or {},
            "courseEvaluations": scored.get("courseEvaluations") or [],
            "courseGoalScore": scored.get("courseGoalScore"),
            "teacherRatingCounts": scored.get("teacherRatingCounts") or {},
            "attentionCurve": attention_curve,
            "attentionSummary": summary_dict.get("attention") or {},
            "languageSummary": summary_dict.get("language") or {},
            "emotionSummary": emotion,
            "kpi": {
                "taskAccuracy": task_performance,
                "taskPerformance": task_performance,
                "avgResponseSec": round(float(avg_response_sec), 1) if avg_response_sec is not None else None,
                "responseSampleCount": response_metrics.get("sampleCount", 0),
                "responseCoveredCourseTypes": response_metrics.get("coveredCourseTypes") or [],
                "emotion": emotion_kpi,
            },
            "narrative": generate_narrative({
                **scored,
                "attentionCurve": attention_curve,
                "narrative_provider": cfg.get("narrative_provider") or "rule",
            }, provider=cfg.get("narrative_provider")),
            "dataQuality": {
                "limitations": scored.get("limitations") or [],
                "limitationLabels": translate_limitations(scored.get("limitations") or []),
            },
            "windows": summary_dict.get("windows") or [],
        }

    def generate(
        self,
        training_session_id: str,
        *,
        auto_finalize: bool = True,
        soft: bool = True,
    ) -> Dict[str, Any]:
        behavior = get_behavior_service()
        store = get_behavior_store()

        training = behavior.get_training(training_session_id)
        summary = behavior.get_summary(training_session_id)

        if auto_finalize:
            if summary is None or (training and training.status == "active"):
                try:
                    summary = behavior.finalize(training_session_id)
                except Exception as e:
                    logger.warning("soft finalize 失败: %s", e)
                    if summary is None:
                        try:
                            summary = behavior.reaggregate(training_session_id)
                        except Exception as e2:
                            logger.warning("reaggregate 失败: %s", e2)

        if summary is None:
            try:
                summary = behavior.reaggregate(training_session_id)
            except Exception:
                raise ValueError("training_session_not_finalized")

        previous = store.get_report(training_session_id) or {}
        published = store.get_published_report(training_session_id)
        summary_dict = summary.to_dict() if hasattr(summary, "to_dict") else summary
        report = self._build_report(training_session_id, summary_dict, soft=soft)
        # “生成”是幂等读取准备动作。教师端状态轮询或重复进入结束页不得
        # 把已经发布的快照重新变成待审核，也不得反复广播同一条待审提醒。
        if published:
            report["publicationStatus"] = "published"
        store.save_report(training_session_id, report)
        logger.info(
            "报告已生成: training=%s status=%s overall=%s",
            training_session_id, report.get("status"), report.get("overall")
        )
        if (
            report.get("publicationStatus") == "pending_review"
            and previous.get("publicationStatus") != "pending_review"
        ):
            _emit("report_ready_for_review", {
                "trainingSessionId": training_session_id,
                "studentId": report.get("studentId"),
                "overall": report.get("overall"),
                "status": report.get("status"),
                "publicationStatus": "pending_review",
            })
        return report

    def refresh(self, training_session_id: str) -> Dict[str, Any]:
        """晚到数据后重算算法稿；不覆盖 manual / published 快照。"""
        behavior = get_behavior_service()
        store = get_behavior_store()
        summary = behavior.reaggregate(training_session_id)
        summary_dict = summary.to_dict()
        report = self._build_report(training_session_id, summary_dict, soft=True)
        old = store.get_report(training_session_id) or {}
        if old.get("generatedAt"):
            report["generatedAt"] = old["generatedAt"]
        # 若已有人工稿，算法稿仍更新，但标记不覆盖 manual
        if store.get_manual_report(training_session_id):
            report["manualOverride"] = True
        store.save_report(training_session_id, report)
        logger.info(
            "报告已刷新(算法稿): training=%s status=%s overall=%s",
            training_session_id, report.get("status"), report.get("overall")
        )
        return report

    def get(self, training_session_id: str) -> Optional[Dict[str, Any]]:
        return get_behavior_store().get_report(training_session_id)

    def get_for_viewer(
        self,
        training_session_id: str,
        *,
        role: str = "teacher",
        view: str = "auto",
    ) -> Dict[str, Any]:
        """
        role=teacher → 仅 published；未推送抛 ValueError('report_not_published')
        role=server → algorithm / manual / published
        """
        store = get_behavior_store()
        role_l = (role or "teacher").strip().lower()
        view_l = (view or "auto").strip().lower()

        if role_l == "server":
            if view_l == "published":
                data = store.get_published_report(training_session_id)
            elif view_l == "manual":
                data = store.get_manual_report(training_session_id) or store.get_report(training_session_id)
            elif view_l == "algorithm":
                data = store.get_report(training_session_id)
            else:
                data = (
                    store.get_manual_report(training_session_id)
                    or store.get_report(training_session_id)
                )
            if not data:
                raise ValueError("report_not_found")
            out = deepcopy(data)
            out["publicationStatus"] = store.get_publication_status(training_session_id)
            out["hasManual"] = store.get_manual_report(training_session_id) is not None
            return out

        published = store.get_published_report(training_session_id)
        if published:
            out = deepcopy(published)
            out["publicationStatus"] = "published"
            return out
        status = store.get_publication_status(training_session_id)
        if status == "published":
            # 旧报告：无 published 快照但视为已发布
            algo = store.get_report(training_session_id)
            if algo:
                out = deepcopy(algo)
                out["publicationStatus"] = "published"
                return out
        raise ValueError("report_not_published" if status != "none" else "report_not_found")

    def review_status(self, training_session_id: str) -> Dict[str, Any]:
        store = get_behavior_store()
        algo = store.get_report(training_session_id)
        published = store.get_published_report(training_session_id)
        manual = store.get_manual_report(training_session_id)
        return {
            "trainingSessionId": training_session_id,
            "publicationStatus": store.get_publication_status(training_session_id),
            "reportStatus": (algo or {}).get("status") if algo else None,
            "overall": (manual or algo or published or {}).get("overall"),
            "studentId": (algo or published or {}).get("studentId"),
            "hasManual": manual is not None,
            "publishedAt": (published or {}).get("publishedAt"),
            "generatedAt": (algo or {}).get("generatedAt"),
        }

    def save_manual(self, training_session_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        store = get_behavior_store()
        base = store.get_manual_report(training_session_id) or store.get_report(training_session_id)
        if not base:
            raise ValueError("report_not_found")
        merged = deepcopy(base)
        for key in (
            "overall", "grade", "overallNote", "dimensions", "courseScores", "narrative", "kpi"
        ):
            if key in patch:
                merged[key] = patch[key]
        if "courseScores" in patch:
            _sync_course_evaluations(merged)
        merged["manualOverride"] = True
        merged["publicationStatus"] = "pending_review"
        merged["updatedAt"] = datetime.utcnow().isoformat() + "Z"
        store.save_manual_report(training_session_id, merged)
        # 同步标记算法稿
        algo = store.get_report(training_session_id)
        if algo:
            algo["manualOverride"] = True
            algo["publicationStatus"] = "pending_review"
            store.save_report(training_session_id, algo)
        return merged

    def revert_manual(self, training_session_id: str) -> Dict[str, Any]:
        store = get_behavior_store()
        algo = store.get_report(training_session_id)
        if not algo:
            raise ValueError("report_not_found")
        store.clear_manual_report(training_session_id)
        algo["manualOverride"] = False
        algo["publicationStatus"] = store.get_publication_status(training_session_id)
        if algo["publicationStatus"] == "published":
            # 已有 published 快照时，撤回人工后仍保持已推送，但编辑态回到算法
            pass
        else:
            algo["publicationStatus"] = "pending_review"
        store.save_report(training_session_id, algo)
        return deepcopy(algo)

    def publish(self, training_session_id: str) -> Dict[str, Any]:
        store = get_behavior_store()
        source = store.get_manual_report(training_session_id) or store.get_report(training_session_id)
        if not source:
            # 尝试生成
            source = self.generate(training_session_id, auto_finalize=True, soft=True)
        published = deepcopy(source)
        published["publicationStatus"] = "published"
        published["publishedAt"] = datetime.utcnow().isoformat() + "Z"
        published["updatedAt"] = published["publishedAt"]
        store.save_published_report(training_session_id, published)

        algo = store.get_report(training_session_id)
        if algo:
            algo["publicationStatus"] = "published"
            store.save_report(training_session_id, algo)
        manual = store.get_manual_report(training_session_id)
        if manual:
            manual["publicationStatus"] = "published"
            manual["publishedAt"] = published["publishedAt"]
            store.save_manual_report(training_session_id, manual)

        sync_student_archive_from_report(published)
        payload = {
            "trainingSessionId": training_session_id,
            "studentId": published.get("studentId"),
            "overall": published.get("overall"),
            "status": published.get("status"),
            "publicationStatus": "published",
            "publishedAt": published.get("publishedAt"),
        }
        _emit("report_published", payload)
        logger.info("报告已推送教师端: training=%s", training_session_id)
        return published

    def list_pending_reviews(self, limit: int = 20) -> List[Dict[str, Any]]:
        """扫描 behavior 目录中待审核报告（轻量）。"""
        store = get_behavior_store()
        pending: List[Dict[str, Any]] = []
        for tid in store.list_persisted_training_ids():
            status = store.get_publication_status(tid)
            if status != "pending_review":
                continue
            algo = store.get_report(tid) or {}
            # 仅列出显式带 pending_review 的新报告
            if str(algo.get("publicationStatus") or "") != "pending_review":
                continue
            pending.append({
                "trainingSessionId": tid,
                "studentId": algo.get("studentId"),
                "overall": algo.get("overall"),
                "status": algo.get("status"),
                "generatedAt": algo.get("generatedAt"),
                "publicationStatus": status,
            })
            if len(pending) >= limit:
                break
        return pending


_report_service: Optional[ReportService] = None


def get_report_service() -> ReportService:
    global _report_service
    if _report_service is None:
        _report_service = ReportService()
    return _report_service
