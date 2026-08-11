"""将报告结果同步到学生档案 SQLite（训练记录 / 能力项 / 干预摘要）。"""
from __future__ import annotations

import json
from datetime import datetime, date, time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from app.utils.logger import setup_logger

logger = setup_logger("report_archive_sync")

# 报告课型 key → DB course_type.name
COURSE_TYPE_EN_TO_CN = {
    "naming": "命名",
    "onomatopoeia": "拟声",
    "mimic": "模仿",
    "pairing": "配对",
    "ordering": "排序",
    "social": "社交",
    "matching": "配对",
    "sequencing": "排序",
    "speech": "命名",
    "imitation": "模仿",
    "pose": "模仿",
}

# 报告维度 → DB ability_type.name
DIMENSION_TO_ABILITY = {
    "attention": "注意力",
    "matching": "配对",
    "ordering": "排序",
    "expressiveLanguage": "表达性语言",
    "receptiveLanguage": "接收性语言",
}

IMITATION_PLACEHOLDER_SCORE = 60


def ensure_training_archive_schema() -> None:
    """SQLite：补齐 training_session 新列，并创建 training_report_summary 表。"""
    from database.models import db, TrainingReportSummary

    try:
        rows = db.session.execute(text("PRAGMA table_info(training_session)")).fetchall()
        cols = {r[1] for r in rows}
        alters = []
        if "behavior_session_id" not in cols:
            alters.append(
                "ALTER TABLE training_session ADD COLUMN behavior_session_id VARCHAR(64)"
            )
        if "overall_score" not in cols:
            alters.append("ALTER TABLE training_session ADD COLUMN overall_score INTEGER")
        if "report_status" not in cols:
            alters.append(
                "ALTER TABLE training_session ADD COLUMN report_status VARCHAR(16)"
            )
        if "report_generated_at" not in cols:
            alters.append(
                "ALTER TABLE training_session ADD COLUMN report_generated_at DATETIME"
            )
        for sql in alters:
            db.session.execute(text(sql))
        if alters:
            db.session.commit()
            logger.info("已为 training_session 补充档案同步字段: %s", alters)

        # 唯一索引（忽略已存在）
        try:
            db.session.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_training_session_behavior_id "
                "ON training_session(behavior_session_id)"
            ))
            db.session.commit()
        except Exception as idx_err:
            db.session.rollback()
            logger.debug("behavior_session_id 唯一索引: %s", idx_err)

        TrainingReportSummary.__table__.create(bind=db.engine, checkfirst=True)
    except Exception as e:
        db.session.rollback()
        logger.warning("ensure_training_archive_schema: %s", e)


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text_val = str(value).strip()
    if not text_val:
        return None
    if text_val.endswith("Z"):
        text_val = text_val[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text_val)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except ValueError:
        return None


_COURSE_ALIASES = {
    "matching": "pairing",
    "sequencing": "ordering",
    "speech": "naming",
    "imitation": "mimic",
    "pose": "mimic",
}
_CANONICAL_COURSES = ("naming", "onomatopoeia", "mimic", "pairing", "ordering")
_CN_TO_EN = {
    "命名": "naming",
    "拟声": "onomatopoeia",
    "模仿": "mimic",
    "配对": "pairing",
    "排序": "ordering",
}


def _canonical_course_key(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    text_raw = str(raw).strip()
    if not text_raw or text_raw.lower() == "default":
        return None
    if text_raw in _CN_TO_EN:
        return _CN_TO_EN[text_raw]
    key = text_raw.lower()
    key = _COURSE_ALIASES.get(key, key)
    if key in _CANONICAL_COURSES:
        return key
    return None


def _count_course_types(windows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for window in windows or []:
        key = _canonical_course_key(window.get("course_type"))
        if not key:
            continue
        cn = COURSE_TYPE_EN_TO_CN.get(key)
        if not cn:
            continue
        counts[cn] = counts.get(cn, 0) + 1
    return counts


def _resolve_student_id(report: Dict[str, Any]) -> Optional[int]:
    raw = report.get("studentId")
    if raw is None:
        try:
            from app.behavior import get_behavior_service
            training = get_behavior_service().get_training(
                str(report.get("trainingSessionId") or "")
            )
            if training and getattr(training, "student_id", None) is not None:
                raw = training.student_id
        except Exception:
            pass
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _session_times(report: Dict[str, Any]) -> Tuple[date, Optional[time], Optional[time], datetime]:
    """返回 (date, start_time, end_time, created_at_fallback)。"""
    behavior_id = str(report.get("trainingSessionId") or "")
    created_dt = _parse_iso_datetime(report.get("generatedAt")) or datetime.utcnow()
    start_dt = None
    end_dt = None

    try:
        from app.behavior import get_behavior_service
        training = get_behavior_service().get_training(behavior_id)
        if training:
            start_dt = _parse_iso_datetime(getattr(training, "created_at", None))
            end_dt = _parse_iso_datetime(getattr(training, "finalized_at", None))
            if start_dt:
                created_dt = start_dt
    except Exception:
        pass

    if end_dt is None:
        end_dt = _parse_iso_datetime(report.get("updatedAt")) or created_dt

    session_date = (start_dt or created_dt).date()
    start_t = start_dt.time().replace(microsecond=0) if start_dt else None
    end_t = end_dt.time().replace(microsecond=0) if end_dt else None
    return session_date, start_t, end_t, created_dt


def _score_from_dimension(meta: Any) -> Optional[int]:
    if not isinstance(meta, dict):
        return None
    if meta.get("available") is False:
        return None
    score = meta.get("score")
    if score is None:
        return None
    try:
        return int(round(float(score)))
    except (TypeError, ValueError):
        return None


def sync_student_archive_from_report(report: Dict[str, Any]) -> Optional[int]:
    """
    报告落盘后同步档案数据。失败仅记日志，不抛给调用方。
    返回 training_session.id；无法同步时返回 None。
    """
    try:
        return _sync_student_archive_from_report(report)
    except Exception as e:
        logger.exception("档案同步失败（不影响报告返回）: %s", e)
        try:
            from database.models import db
            db.session.rollback()
        except Exception:
            pass
        return None


def _sync_student_archive_from_report(report: Dict[str, Any]) -> Optional[int]:
    from database.models import (
        db,
        Student,
        TrainingSession,
        TrainingDetail,
        AbilityItem,
        AbilityType,
        CourseType,
        TrainingReportSummary,
    )

    behavior_id = str(report.get("trainingSessionId") or "").strip()
    if not behavior_id:
        logger.warning("档案同步跳过：缺少 trainingSessionId")
        return None

    student_id = _resolve_student_id(report)
    if student_id is None:
        logger.warning("档案同步跳过：缺少 studentId training=%s", behavior_id)
        return None

    student = Student.query.get(student_id)
    if not student:
        logger.warning("档案同步跳过：学生不存在 id=%s", student_id)
        return None

    session_date, start_t, end_t, created_dt = _session_times(report)
    overall = report.get("overall")
    try:
        overall_score = int(round(float(overall))) if overall is not None else None
    except (TypeError, ValueError):
        overall_score = None

    report_status = str(report.get("status") or "") or None
    generated_at = _parse_iso_datetime(report.get("generatedAt")) or datetime.utcnow()

    session = TrainingSession.query.filter_by(behavior_session_id=behavior_id).first()
    if session is None:
        session = TrainingSession(
            student_id=student_id,
            date=session_date,
            start_time=start_t,
            end_time=end_t,
            created_at=created_dt,
            behavior_session_id=behavior_id,
        )
        db.session.add(session)
        db.session.flush()
    else:
        session.student_id = student_id
        session.date = session_date
        if start_t is not None:
            session.start_time = start_t
        if end_t is not None:
            session.end_time = end_t

    session.overall_score = overall_score
    session.report_status = report_status
    session.report_generated_at = generated_at

    # training_detail：先删后插
    TrainingDetail.query.filter_by(training_session_id=session.id).delete()
    course_counts = _count_course_types(report.get("windows") or [])
    course_types = {ct.name: ct for ct in CourseType.query.all()}
    for cn_name, count in course_counts.items():
        ct = course_types.get(cn_name)
        if not ct:
            logger.warning("未知课型名称，跳过 detail: %s", cn_name)
            continue
        db.session.add(TrainingDetail(
            training_session_id=session.id,
            course_type_id=ct.id,
            count=int(count),
        ))

    # ability_item：先删后插
    AbilityItem.query.filter_by(training_session_id=session.id).delete()
    ability_types = {at.name: at for at in AbilityType.query.all()}
    dimensions = report.get("dimensions") or {}

    ability_scores: Dict[str, int] = {}
    for dim_key, ability_name in DIMENSION_TO_ABILITY.items():
        score = _score_from_dimension(dimensions.get(dim_key))
        if score is not None:
            ability_scores[ability_name] = max(0, min(100, score))

    # 模仿：暂统一占位 60
    ability_scores["模仿"] = IMITATION_PLACEHOLDER_SCORE

    for ability_name, score in ability_scores.items():
        at = ability_types.get(ability_name)
        if not at:
            logger.warning("未知能力类型，跳过: %s", ability_name)
            continue
        db.session.add(AbilityItem(
            training_session_id=session.id,
            ability_type_id=at.id,
            score=score,
        ))

    narrative = report.get("narrative") or {}
    recommendations = narrative.get("recommendations") or []
    if not isinstance(recommendations, list):
        recommendations = []
    analysis = narrative.get("analysis")
    dimensions_dump = json.dumps(dimensions, ensure_ascii=False) if dimensions else None
    recommendations_dump = json.dumps(recommendations, ensure_ascii=False)

    summary = TrainingReportSummary.query.filter_by(
        behavior_session_id=behavior_id
    ).first()
    if summary is None:
        summary = TrainingReportSummary(
            training_session_id=session.id,
            student_id=student_id,
            behavior_session_id=behavior_id,
        )
        db.session.add(summary)
    summary.training_session_id = session.id
    summary.student_id = student_id
    summary.narrative_analysis = analysis
    summary.recommendations_json = recommendations_dump
    summary.dimensions_json = dimensions_dump
    summary.updated_at = datetime.utcnow()

    db.session.commit()
    logger.info(
        "档案已同步: student=%s behavior=%s session_db=%s abilities=%s courses=%s",
        student_id,
        behavior_id,
        session.id,
        list(ability_scores.keys()),
        course_counts,
    )
    return session.id
