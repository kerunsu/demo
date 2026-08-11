"""
行为观测服务门面
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Dict, Optional

from app.behavior.models import (
    AttentionObservation,
    EmotionObservation,
    LanguageObservation,
    QuestionWindow,
    SessionBehaviorSummary,
    TrainingSessionRecord,
)
from app.behavior.store import BehaviorStore, get_behavior_store
from app.behavior.timeline import BehaviorTimeline, make_question_id
from app.behavior.camera_config import load_camera_analysis_config
from app.utils.logger import setup_logger

logger = setup_logger("behavior_service")


class BehaviorService:
    def __init__(self):
        self.store: BehaviorStore = get_behavior_store()
        self.timeline = BehaviorTimeline(self.store)
        self._interaction_service = None

    def _interactions(self):
        from app.behavior.interaction import InteractionStateService

        if (
            self._interaction_service is None
            or self._interaction_service.store is not self.store
        ):
            self._interaction_service = InteractionStateService(self.store)
        return self._interaction_service

    def record_interaction(self, event_type: str, training_session_id: str, **kwargs):
        return self._interactions().record(event_type, training_session_id, **kwargs)

    def get_response_metrics(
        self, training_session_id: str, question_id: Optional[str]
    ) -> Dict[str, Optional[float]]:
        return self._interactions().response_metrics(training_session_id, question_id)

    def get_interaction_snapshot(
        self, training_session_id: str, question_id: Optional[str]
    ) -> Dict[str, Any]:
        return self._interactions().snapshot(training_session_id, question_id)

    def open_training(
        self,
        student_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TrainingSessionRecord:
        return self.timeline.open_training(student_id=student_id, metadata=metadata)

    def get_active_training_id(self, student_id: Optional[int]) -> Optional[str]:
        if student_id is None:
            return None
        return self.store.get_active_training_id(student_id)

    def get_training(self, training_session_id: str) -> Optional[TrainingSessionRecord]:
        return self.store.get_training(training_session_id)

    def open_window(self, training_session_id: str, **kwargs) -> QuestionWindow:
        return self.timeline.open_window(training_session_id, **kwargs)

    def close_window(self, training_session_id: str, question_id: str, **kwargs) -> Optional[QuestionWindow]:
        return self.timeline.close_window(training_session_id, question_id, **kwargs)

    def finalize(self, training_session_id: str) -> SessionBehaviorSummary:
        return self.timeline.finalize(training_session_id)

    def reaggregate(self, training_session_id: str) -> SessionBehaviorSummary:
        return self.timeline.reaggregate(training_session_id)

    def record_attention(
        self,
        training_session_id: str,
        question_id: str,
        *,
        score: float,
        state: str = "unknown",
        trend: str = "stable",
        data_quality: str = "VALID",
        face_present: Optional[bool] = None,
        runtime_session_id: Optional[str] = None,
        features: Optional[Dict[str, Any]] = None,
        orientation: Optional[str] = None,
        confidence: Optional[float] = None,
        algorithm_version: Optional[str] = None,
        provider: str = "server",
    ) -> AttentionObservation:
        obs = AttentionObservation(
            training_session_id=training_session_id,
            question_id=question_id,
            runtime_session_id=runtime_session_id,
            score=float(score),
            state=state,
            trend=trend,
            data_quality=data_quality,
            face_present=face_present,
            orientation=orientation,
            confidence=confidence,
            algorithm_version=algorithm_version,
            provider=provider,
            features=features or {},
        )
        self.store.add_attention(obs)
        try:
            from app.monitor.events import note_attention_quality

            note_attention_quality(training_session_id, question_id, data_quality)
        except Exception:
            pass
        return obs

    def record_emotion(
        self,
        training_session_id: str,
        question_id: str,
        *,
        positive: float,
        focused: float,
        frustrated: float,
        confidence: float = 0.0,
        data_quality: str = "VALID",
        degraded: bool = False,
        algorithm_version: Optional[str] = None,
        provider: str = "browser",
        runtime_session_id: Optional[str] = None,
        features: Optional[Dict[str, Any]] = None,
    ) -> EmotionObservation:
        obs = EmotionObservation(
            training_session_id=training_session_id,
            question_id=question_id,
            runtime_session_id=runtime_session_id,
            positive=float(positive),
            focused=float(focused),
            frustrated=float(frustrated),
            confidence=float(confidence or 0),
            data_quality=data_quality,
            degraded=bool(degraded),
            algorithm_version=algorithm_version,
            provider=provider,
            features=features or {},
        )
        self.store.add_emotion(obs)
        return obs

    def ingest_camera_analysis(self, data: Dict[str, Any]) -> bool:
        """接收浏览器 camera_analysis 描述符并写入注意力/情绪观测。"""
        cfg = load_camera_analysis_config()
        if not cfg.get("enabled", True):
            return False

        session_id = data.get("sessionId") or data.get("session_id")
        ts_id = data.get("trainingSessionId") or data.get("training_session_id")
        qid = data.get("questionId") or data.get("question_id")
        if not ts_id or not qid:
            ctx = self.get_current_context_for_runtime(session_id) if session_id else {}
            ts_id = ts_id or ctx.get("training_session_id")
            qid = qid or ctx.get("question_id")
        if not ts_id or not qid:
            logger.warning(
                "camera_analysis 缺少训练上下文 session=%s training=%s question=%s",
                session_id, ts_id, qid
            )
            return False

        visual = data.get("visualFeatures") or {}
        emotion = data.get("emotionFeatures") or {}
        dq = data.get("dataQuality") or {}
        provider = data.get("provider") or "browser"

        score = visual.get("attentionScore100")
        if score is None and visual.get("facingScore") is not None:
            score = float(visual["facingScore"]) * 100.0
        score = float(score or 0)
        facing = float(visual.get("facingScore") or 0)
        if facing >= 0.7:
            state = "high"
        elif facing >= 0.4:
            state = "medium"
        else:
            state = "low"

        attn_q = dq.get("attention") or "complete"
        # 映射到既有 VALID/DEGRADED/MISSING 兼容字面
        if attn_q in ("missing_device", "insufficient"):
            dq_attn = "MISSING"
        elif attn_q == "low_confidence":
            dq_attn = "DEGRADED"
        elif attn_q == "complete":
            dq_attn = "VALID"
        else:
            dq_attn = str(attn_q)

        self.record_attention(
            ts_id,
            qid,
            score=score,
            state=state,
            trend="stable",
            data_quality=dq_attn,
            face_present=bool(visual.get("facePresent")),
            runtime_session_id=session_id,
            orientation=visual.get("headOrientation"),
            confidence=visual.get("confidence"),
            algorithm_version=visual.get("algorithmVersion") or "browser-attention-v2",
            provider=provider,
            features={
                "visual": visual,
                "frameId": data.get("frameId"),
                "sequence": data.get("sequence"),
                "dataQuality": attn_q,
            },
        )

        emo_q = dq.get("emotion") or "insufficient"
        if emotion and not emotion.get("unavailable"):
            if emo_q in ("insufficient", "missing_device"):
                dq_emo = "MISSING"
            elif emo_q == "low_confidence":
                dq_emo = "DEGRADED"
            else:
                dq_emo = "VALID"
            self.record_emotion(
                ts_id,
                qid,
                positive=float(emotion.get("positiveScore") or 0),
                focused=float(emotion.get("focusedScore") or 0),
                frustrated=float(emotion.get("frustratedScore") or 0),
                confidence=float(emotion.get("confidence") or 0),
                data_quality=dq_emo,
                degraded=bool(emotion.get("degraded")),
                algorithm_version=emotion.get("algorithmVersion") or "browser-emotion-v1",
                provider=provider,
                runtime_session_id=session_id,
                features={"emotion": emotion, "dataQuality": emo_q},
            )

        return True

    def record_language(
        self,
        training_session_id: str,
        question_id: str,
        *,
        kind: str = "speech_activity",
        value: Any = None,
        speech_ratio: Optional[float] = None,
        word_count: Optional[int] = None,
        speech_duration: Optional[float] = None,
        clarity_proxy: Optional[float] = None,
        is_speech: Optional[bool] = None,
        transcript: Optional[str] = None,
        confidence: Optional[float] = None,
        data_quality: str = "VALID",
        runtime_session_id: Optional[str] = None,
        features: Optional[Dict[str, Any]] = None,
    ) -> LanguageObservation:
        obs = LanguageObservation(
            training_session_id=training_session_id,
            question_id=question_id,
            runtime_session_id=runtime_session_id,
            kind=kind,
            value=value,
            speech_ratio=speech_ratio,
            word_count=word_count,
            speech_duration=speech_duration,
            clarity_proxy=clarity_proxy,
            is_speech=is_speech,
            transcript=transcript,
            confidence=confidence,
            data_quality=data_quality,
            features=features or {},
        )
        self.store.add_language(obs)
        return obs

    def record_task_metrics(
        self,
        training_session_id: str,
        question_id: str,
        metrics: Dict[str, Any],
    ) -> Optional[QuestionWindow]:
        from app.behavior.models import QuestionWindow

        window = None
        qid = question_id
        if qid:
            window = self.store.get_window(training_session_id, qid)
        if not window:
            training = self.store.get_training(training_session_id)
            if training and training.current_question_id:
                qid = training.current_question_id
                window = self.store.get_window(training_session_id, qid)
        if not window:
            # 轻量补丁窗口，保证 late game_end 不丢
            qid = question_id or f"patch_{metrics.get('type', 'task')}"
            window = QuestionWindow(
                question_id=qid,
                training_session_id=training_session_id,
                course_type=str(metrics.get('type') or 'default'),
                question_index=999,
                status='closed',
                task_metrics=dict(metrics or {}),
            )
            self.store.save_window(window)
            logger.warning(
                "record_task_metrics 创建补丁窗口: training=%s question=%s",
                training_session_id, qid
            )
        else:
            # 按 type 分桶合并，避免 speech match 的 receptive 覆盖 pairing 的 matching
            incoming = dict(metrics or {})
            mtype = str(incoming.get("type") or "").strip()
            tm = window.task_metrics if isinstance(window.task_metrics, dict) else {}
            if mtype in ("matching", "sequencing", "receptive"):
                # 迁移旧版扁平结构
                legacy_type = tm.get("type")
                if legacy_type in ("matching", "sequencing", "receptive") and legacy_type not in tm:
                    legacy = {k: v for k, v in tm.items()}
                    tm = {legacy_type: legacy}
                section = dict(tm.get(mtype) or {})
                section.update(incoming)
                section["type"] = mtype
                tm[mtype] = section
                # 同步常用顶层字段，便于旧读取路径；不改写其他 type 的桶
                if mtype == "matching" and incoming.get("accuracy") is not None:
                    tm["accuracy"] = incoming.get("accuracy")
                    tm["correct"] = incoming.get("correct")
                    tm["total"] = incoming.get("total")
                if mtype == "sequencing" and incoming.get("accuracy") is not None:
                    tm.setdefault("sequencing", section)
                window.task_metrics = tm
            else:
                tm.update(incoming)
                window.task_metrics = tm
            self.store.save_window(window)

        # 若已有报告，刷新
        try:
            if self.store.get_report(training_session_id):
                from app.report import get_report_service
                get_report_service().refresh(training_session_id)
        except Exception as e:
            logger.warning("task_metrics 后刷新报告失败: %s", e)

        return window

    def record_teacher_rating(
        self,
        training_session_id: str,
        question_id: Optional[str],
        *,
        rating: int,
        response_ms: Optional[float] = None,
        response_source: str = "teacher_advance",
        advance_source: str = "manual",
        client_recorded_at: Optional[str] = None,
    ) -> QuestionWindow:
        """幂等保存逐课点教师评分，并刷新已有摘要/报告。"""
        if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
            raise ValueError("rating_must_be_integer_1_to_5")

        training = self.store.get_training(training_session_id)
        if not training:
            raise ValueError("training_session_not_found")

        qid = str(question_id or training.current_question_id or "").strip()
        if not qid:
            raise ValueError("question_id_missing")
        window = self.store.get_window(training_session_id, qid)
        if not window:
            raise ValueError("question_window_not_found")

        clean_response_ms = None
        if response_ms is not None:
            try:
                candidate = float(response_ms)
                # 单课点最长按 2 小时保护；异常值不阻断评分。
                if math.isfinite(candidate) and 0 <= candidate <= 7_200_000:
                    clean_response_ms = candidate
            except (TypeError, ValueError):
                pass

        updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        teacher_rating = {
            "rating": rating,
            "normalized_score": rating * 20,
            "response_ms": clean_response_ms,
            "response_source": str(response_source or "teacher_advance"),
            "advance_source": str(advance_source or "manual"),
            "client_recorded_at": client_recorded_at,
            "updated_at": updated_at,
            "schema_version": "teacher-rating-v1",
        }
        metrics = window.task_metrics if isinstance(window.task_metrics, dict) else {}
        metrics["teacher_rating"] = teacher_rating
        window.task_metrics = metrics
        self.store.save_window(window)

        # 报告 refresh 自身会 reaggregate，避免重复聚合。
        try:
            if self.store.get_report(training_session_id):
                from app.report import get_report_service
                get_report_service().refresh(training_session_id)
            elif self.store.get_summary(training_session_id):
                self.reaggregate(training_session_id)
        except Exception as e:
            logger.warning("教师评分后刷新摘要/报告失败: %s", e)

        logger.info(
            "教师评分已保存: training=%s question=%s rating=%s",
            training_session_id, qid, rating
        )
        return window

    def get_summary(self, training_session_id: str) -> Optional[SessionBehaviorSummary]:
        return self.store.get_summary(training_session_id)

    def get_current_context_for_runtime(
        self, runtime_session_id: str
    ) -> Dict[str, Optional[str]]:
        """从 runtime session 反查 training/question（依赖 Session 字段）。"""
        try:
            from app.session import get_session_manager
            session = get_session_manager().get_session(runtime_session_id)
            if not session:
                return {"training_session_id": None, "question_id": None}
            return {
                "training_session_id": getattr(session, "training_session_id", None),
                "question_id": getattr(session, "question_id", None),
            }
        except Exception:
            return {"training_session_id": None, "question_id": None}


_service: Optional[BehaviorService] = None


def get_behavior_service() -> BehaviorService:
    global _service
    if _service is None:
        _service = BehaviorService()
    return _service


__all__ = [
    "BehaviorService",
    "get_behavior_service",
    "make_question_id",
]
