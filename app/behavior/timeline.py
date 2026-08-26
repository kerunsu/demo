"""
训练会话时间线：开训 / 开窗 / 关窗 / finalize
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from app.behavior.models import (
    QuestionWindow,
    SessionBehaviorSummary,
    TrainingSessionRecord,
)
from app.behavior.store import BehaviorStore, get_behavior_store
from app.utils.logger import setup_logger

logger = setup_logger("behavior_timeline")


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def make_question_id(course_id: Any, item_id: Any, index: int) -> str:
    c = course_id if course_id is not None else "na"
    i = item_id if item_id is not None else "na"
    return f"{c}_{i}_{index}"


class BehaviorTimeline:
    def __init__(self, store: Optional[BehaviorStore] = None):
        self.store = store or get_behavior_store()

    def open_training(
        self,
        student_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TrainingSessionRecord:
        if student_id is not None:
            existing_id = self.store.get_active_training_id(student_id)
            if existing_id:
                existing = self.store.get_training(existing_id)
                if existing and existing.status == "active":
                    logger.info(
                        "复用活动训练会话: student=%s training=%s",
                        student_id, existing_id
                    )
                    return existing

        record = TrainingSessionRecord(
            training_session_id=str(uuid.uuid4()),
            student_id=student_id,
            status="active",
            metadata=metadata or {},
        )
        self.store.save_training(record)
        logger.info(
            "开启训练会话: training=%s student=%s",
            record.training_session_id, student_id
        )
        return record

    def open_window(
        self,
        training_session_id: str,
        *,
        course_id: Optional[int] = None,
        course_item_id: Optional[int] = None,
        question_index: int = 0,
        course_type: str = "default",
        runtime_session_id: Optional[str] = None,
        question_id: Optional[str] = None,
    ) -> QuestionWindow:
        qid = question_id or make_question_id(course_id, course_item_id, question_index)
        window = QuestionWindow(
            question_id=qid,
            training_session_id=training_session_id,
            runtime_session_id=runtime_session_id,
            course_id=course_id,
            course_item_id=course_item_id,
            question_index=question_index,
            course_type=course_type,
            opened_at=_now_iso(),
            status="open",
        )
        self.store.save_window(window)

        training = self.store.get_training(training_session_id)
        if training:
            training.current_question_id = qid
            training.window_count = int(training.window_count or 0) + 1
            self.store.save_training(training)

        logger.info(
            "开启题目窗口: training=%s question=%s index=%s type=%s",
            training_session_id, qid, question_index, course_type
        )
        return window

    def close_window(
        self,
        training_session_id: str,
        question_id: str,
        *,
        analysis_summary: Optional[Dict[str, Any]] = None,
        task_metrics: Optional[Dict[str, Any]] = None,
    ) -> Optional[QuestionWindow]:
        window = self.store.get_window(training_session_id, question_id)
        if not window:
            logger.warning(
                "关窗失败，窗口不存在: training=%s question=%s",
                training_session_id, question_id
            )
            return None

        if window.status == "closed":
            return window

        # 聚合窗口内观测摘要
        attention_obs = self.store.list_attention(training_session_id, question_id)
        language_obs = self.store.list_language(training_session_id, question_id)
        emotion_obs = self.store.list_emotion(training_session_id, question_id)

        from app.behavior.camera_config import load_camera_analysis_config, should_prefer_browser_for_report
        from app.behavior.emotion_scoring import select_attention_observations
        cam_cfg = load_camera_analysis_config()
        prefer_browser = should_prefer_browser_for_report(cam_cfg)
        use_attn = select_attention_observations(attention_obs, prefer_browser)
        scores = [o.score for o in use_attn if o.data_quality != "MISSING"]
        qualities = [o.data_quality for o in use_attn]
        incomplete = any(q in ("MISSING", "DEGRADED", "low_confidence", "missing_device") for q in qualities)
        factor = float(cam_cfg.get("attention_incomplete_factor", 0.7)) if incomplete and scores else 1.0
        avg_score = (sum(scores) / len(scores) * factor) if scores else None
        providers = {getattr(o, "provider", "server") for o in use_attn} if use_attn else set()
        window.attention_summary = {
            "sample_count": len(use_attn),
            "avg_score": avg_score,
            "last_score": use_attn[-1].score if use_attn else None,
            "last_quality": use_attn[-1].data_quality if use_attn else "MISSING",
            "provider": "browser" if providers == {"browser"} else (
                "mixed" if len(providers) > 1 else "server"
            ),
        }

        speech_ratios = [o.speech_ratio for o in language_obs if o.speech_ratio is not None]
        word_counts = [o.word_count for o in language_obs if o.word_count is not None]
        window.language_summary = {
            "sample_count": len(language_obs),
            "avg_speech_ratio": (sum(speech_ratios) / len(speech_ratios)) if speech_ratios else None,
            "total_word_count": sum(word_counts) if word_counts else 0,
        }

        valid_emo = [
            o for o in emotion_obs
            if o.data_quality not in ("MISSING", "insufficient", "missing_device")
            and not (o.positive == 0 and o.focused == 0 and o.frustrated == 0 and o.degraded)
        ]
        min_emo = int(cam_cfg.get("emotion_min_samples", 2))
        if len(valid_emo) >= min_emo:
            p = sum(o.positive for o in valid_emo) / len(valid_emo)
            f = sum(o.focused for o in valid_emo) / len(valid_emo)
            r = sum(o.frustrated for o in valid_emo) / len(valid_emo)
            tot = p + f + r
            if tot > 0:
                p, f, r = p / tot, f / tot, r / tot
            window.emotion_summary = {
                "sample_count": len(valid_emo),
                "positive": round(p, 3),
                "focused": round(f, 3),
                "frustrated": round(r, 3),
                "status": "READY",
            }
        else:
            window.emotion_summary = {
                "sample_count": len(emotion_obs),
                "status": "INSUFFICIENT_SIGNALS",
            }

        if analysis_summary:
            window.analysis_summary = analysis_summary
        if task_metrics:
            window.task_metrics.update(task_metrics)

        window.closed_at = _now_iso()
        window.status = "closed"
        self.store.save_window(window)
        logger.info("关闭题目窗口: training=%s question=%s", training_session_id, question_id)
        return window

    def _build_summary(self, training_session_id: str) -> SessionBehaviorSummary:
        from app.behavior.camera_config import load_camera_analysis_config, should_prefer_browser_for_report
        from app.behavior.emotion_scoring import select_attention_observations
        from app.behavior.screen_interaction import (
            load_screen_interaction_summary,
            summary_for_question,
        )
        cam_cfg = load_camera_analysis_config()
        prefer_browser = should_prefer_browser_for_report(cam_cfg)
        incomplete_factor = float(cam_cfg.get("attention_incomplete_factor", 0.7))
        min_emo = int(cam_cfg.get("emotion_min_samples", 2))

        training = self.store.get_training(training_session_id)
        windows = self.store.list_windows(training_session_id)
        all_attention = self.store.list_attention(training_session_id)
        all_language = self.store.list_language(training_session_id)
        all_emotion = self.store.list_emotion(training_session_id)
        screen_interaction = load_screen_interaction_summary(training_session_id)
        for window in windows:
            analysis = dict(window.analysis_summary or {})
            window_clicks = {
                "schema_version": "screen-interaction-window-v1",
                "tracking_status": screen_interaction.get("tracking_status"),
                "available": bool(screen_interaction.get("available")),
                **summary_for_question(screen_interaction, window.question_id),
            }
            if analysis.get("screen_interaction") != window_clicks:
                analysis["screen_interaction"] = window_clicks
                window.analysis_summary = analysis
                self.store.save_window(window)

        use_attn = select_attention_observations(all_attention, prefer_browser)
        scores = [o.score for o in use_attn if o.data_quality != "MISSING"]
        attn_incomplete = any(
            o.data_quality in ("MISSING", "DEGRADED", "low_confidence", "missing_device")
            for o in use_attn
        )
        speech_ratios = [o.speech_ratio for o in all_language if o.speech_ratio is not None]
        word_counts = [o.word_count for o in all_language if o.word_count is not None]

        matching_acc: List[float] = []
        sequencing_acc: List[float] = []
        receptive_pass: List[float] = []
        response_ms: List[float] = []
        teacher_scores_by_course: Dict[str, List[float]] = {}
        response_by_course: Dict[str, List[float]] = {}
        course_types = set()

        course_aliases = {
            "matching": "pairing",
            "sequencing": "ordering",
            "speech": "naming",
            "imitation": "mimic",
            "pose": "mimic",
        }

        def _metric_section(tm: Dict[str, Any], key: str) -> Dict[str, Any]:
            section = tm.get(key)
            if isinstance(section, dict):
                return section
            if tm.get("type") == key:
                return tm
            return {}

        for w in windows:
            if w.course_type:
                course_types.add(w.course_type)
            tm = w.task_metrics or {}
            ct = course_aliases.get((w.course_type or "").lower(), (w.course_type or "").lower())
            matching = _metric_section(tm, "matching")
            sequencing = _metric_section(tm, "sequencing")
            receptive = _metric_section(tm, "receptive")
            teacher_rating = tm.get("teacher_rating") if isinstance(tm.get("teacher_rating"), dict) else {}
            teacher_score = teacher_rating.get("normalized_score")
            if teacher_score is None and teacher_rating.get("rating") is not None:
                teacher_score = float(teacher_rating["rating"]) * 20.0
            if teacher_score is not None and ct:
                teacher_scores_by_course.setdefault(ct, []).append(float(teacher_score))

            if matching.get("accuracy") is not None:
                matching_acc.append(float(matching["accuracy"]))
            elif (w.course_type or "").lower() in ("pairing", "matching") and tm.get("accuracy") is not None:
                # 兼容：receptive 覆盖 type 后仍保留了 pairing 正确率字段
                matching_acc.append(float(tm["accuracy"]))

            if sequencing.get("accuracy") is not None:
                sequencing_acc.append(float(sequencing["accuracy"]))
            elif (w.course_type or "").lower() in ("ordering", "sequencing") and tm.get("accuracy") is not None:
                sequencing_acc.append(float(tm["accuracy"]))

            for section in (matching, sequencing):
                avg_ms = section.get("avg_response_ms")
                if avg_ms is None:
                    avg_ms = tm.get("avg_response_ms")
                if avg_ms is not None:
                    try:
                        response_ms.append(float(avg_ms))
                    except (TypeError, ValueError):
                        pass

            course_response = teacher_rating.get("response_ms")
            if ct == "pairing" and matching.get("avg_response_ms") is not None:
                course_response = matching.get("avg_response_ms")
            elif ct == "ordering" and sequencing.get("avg_response_ms") is not None:
                course_response = sequencing.get("avg_response_ms")
            if course_response is not None and ct:
                try:
                    value = float(course_response)
                    if value >= 0:
                        response_by_course.setdefault(ct, []).append(value)
                except (TypeError, ValueError):
                    pass

            if receptive.get("pass_rate") is not None:
                ct = (w.course_type or "").lower()
                # 配对/排序窗上的 receptive 多为语音 match 误写入，不计入接受性语言
                if ct not in ("pairing", "matching", "ordering", "sequencing"):
                    receptive_pass.append(float(receptive["pass_rate"]))

        limitations: List[str] = []
        if not scores:
            limitations.append("ATTENTION_DATA_MISSING")
        if not speech_ratios and not word_counts:
            limitations.append("LANGUAGE_DATA_MISSING")
        if not matching_acc:
            limitations.append("MATCHING_DATA_MISSING")
        if not sequencing_acc:
            limitations.append("SEQUENCING_DATA_MISSING")
        # 接受性语言过渡方案依赖配对/排序；二者皆无时才标缺失
        if not matching_acc and not sequencing_acc and not receptive_pass:
            limitations.append("RECEPTIVE_DATA_MISSING")

        attention_curve = []
        for w in windows:
            avg = (w.attention_summary or {}).get("avg_score")
            if avg is None:
                obs = self.store.list_attention(training_session_id, w.question_id)
                use_w = select_attention_observations(obs, prefer_browser)
                obs_scores = [o.score for o in use_w if o.data_quality != "MISSING"]
                if obs_scores:
                    avg = sum(obs_scores) / len(obs_scores)
            attention_curve.append({
                "question_id": w.question_id,
                "question_index": w.question_index,
                "course_type": w.course_type,
                "score": avg,
            })

        avg_attention = (sum(scores) / len(scores)) if scores else None
        if avg_attention is not None and attn_incomplete and use_attn:
            avg_attention = avg_attention * incomplete_factor

        # 若曲线全空但有全局注意力样本，补一条会话级点
        if avg_attention is not None and not any(c.get("score") is not None for c in attention_curve):
            attention_curve = [{
                "question_id": "session",
                "question_index": 0,
                "course_type": "session",
                "score": avg_attention,
            }]

        # 情绪会话聚合
        valid_emo = [
            o for o in all_emotion
            if o.data_quality not in ("MISSING", "insufficient", "missing_device")
        ]
        emotion_summary: Dict[str, Any]
        if len(valid_emo) >= min_emo:
            p = sum(o.positive for o in valid_emo) / len(valid_emo)
            f = sum(o.focused for o in valid_emo) / len(valid_emo)
            r = sum(o.frustrated for o in valid_emo) / len(valid_emo)
            tot = p + f + r
            if tot > 0:
                p, f, r = p / tot, f / tot, r / tot
            labels = [("愉悦", p), ("专注", f), ("急躁", r)]
            labels.sort(key=lambda x: x[1], reverse=True)
            emotion_summary = {
                "sample_count": len(valid_emo),
                "positive": round(p, 3),
                "focused": round(f, 3),
                "frustrated": round(r, 3),
                "happy": round(p * 100, 1),
                "focus": round(f * 100, 1),
                "frustration": round(r * 100, 1),
                "label": f"{labels[0][0]}为主" if labels[0][1] > 0 else "数据不足",
                "status": "READY",
            }
        else:
            emotion_summary = {
                "sample_count": len(all_emotion),
                "status": "INSUFFICIENT_SIGNALS",
                "label": "数据不足",
                "happy": None,
                "focus": None,
                "frustration": None,
            }
            if all_emotion:
                limitations.append("EMOTION_DATA_INSUFFICIENT")

        providers = {getattr(o, "provider", "server") for o in use_attn} if use_attn else set()
        attn_provider = (
            "browser" if providers == {"browser"}
            else ("mixed" if len(providers) > 1 else "server")
        )

        return SessionBehaviorSummary(
            training_session_id=training_session_id,
            student_id=training.student_id if training else None,
            finalized_at=_now_iso(),
            window_count=len(windows),
            attention={
                "sample_count": len(use_attn),
                "avg_score": avg_attention,
                "curve": attention_curve,
                "provider": attn_provider,
                "quality_incomplete": bool(attn_incomplete),
            },
            language={
                "sample_count": len(all_language),
                "avg_speech_ratio": (sum(speech_ratios) / len(speech_ratios)) if speech_ratios else None,
                "total_word_count": sum(word_counts) if word_counts else 0,
            },
            emotion=emotion_summary,
            task={
                "matching_accuracy": (sum(matching_acc) / len(matching_acc)) if matching_acc else None,
                "sequencing_accuracy": (sum(sequencing_acc) / len(sequencing_acc)) if sequencing_acc else None,
                "receptive_pass_rate": (sum(receptive_pass) / len(receptive_pass)) if receptive_pass else None,
                "avg_response_ms": (sum(response_ms) / len(response_ms)) if response_ms else None,
                "avg_response_sec": (sum(response_ms) / len(response_ms) / 1000.0) if response_ms else None,
                "teacher_rating_by_course": {
                    key: sum(values) / len(values)
                    for key, values in teacher_scores_by_course.items() if values
                },
                "teacher_rating_count": sum(len(values) for values in teacher_scores_by_course.values()),
                "avg_response_by_course_ms": {
                    key: sum(values) / len(values)
                    for key, values in response_by_course.items() if values
                },
                "response_covered_course_types": sorted(response_by_course.keys()),
            },
            screen_interaction=screen_interaction,
            windows=[w.to_dict() for w in windows],
            limitations=limitations,
        )

    def reaggregate(self, training_session_id: str) -> SessionBehaviorSummary:
        """基于最新观测/窗口重算摘要（允许 late metrics）。"""
        summary = self._build_summary(training_session_id)
        self.store.save_summary(summary)
        logger.info(
            "训练会话已 reaggregate: training=%s windows=%s limitations=%s",
            training_session_id, summary.window_count, summary.limitations
        )
        return summary

    def finalize(self, training_session_id: str) -> SessionBehaviorSummary:
        training = self.store.get_training(training_session_id)
        windows = self.store.list_windows(training_session_id)

        for w in windows:
            if w.status == "open":
                self.close_window(training_session_id, w.question_id)

        summary = self._build_summary(training_session_id)
        self.store.save_summary(summary)

        if training:
            # soft finalize：标记 finalized，但仍允许 late metrics 经 reaggregate 更新
            training.status = "finalized"
            training.finalized_at = summary.finalized_at
            # 保留 current_question_id 以便 late game_end 挂载
            self.store.save_training(training)

        logger.info(
            "训练会话已 finalize: training=%s windows=%s limitations=%s",
            training_session_id, summary.window_count, summary.limitations
        )
        return summary
