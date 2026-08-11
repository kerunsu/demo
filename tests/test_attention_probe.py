"""注意力探针路径回归：须走 analyze_frame，而非 process_realtime。"""
from types import SimpleNamespace

import numpy as np

from app.services.analysis_service import AnalysisService
from app.core.models import AnalysisResult, AnalysisMode


class _FakeAttention:
    is_ready = True

    def initialize(self):
        return True

    def analyze_frame(self, frame, context):
        return AnalysisResult(
            session_id=context.session_id,
            analyzer_type="attention",
            mode=AnalysisMode.REALTIME,
            timestamp=0.0,
            data={
                "score": 72.0,
                "emotion": "Neutral",
                "emotion_scores": {"positiveScore": 0.2},
                "face_present": True,
            },
            confidence=0.72,
        )


def test_probe_attention_uses_analyze_frame_not_realtime(monkeypatch):
    svc = AnalysisService.__new__(AnalysisService)
    svc._vision_pipeline = SimpleNamespace(
        attention_analyzer=_FakeAttention(),
        get_info=lambda: {"ok": True},
        process_realtime=lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("不应走 process_realtime")
        ),
    )
    # 伪造解码
    monkeypatch.setattr(
        svc,
        "_decode_frame",
        lambda frame_data: np.zeros((48, 48, 3), dtype=np.uint8),
    )

    result = svc.probe_attention("dGVzdA==", session_id="probe-test")
    assert result["attentionOk"] is True
    assert result["emotionOk"] is True
    assert result["attentionScore"] == 72.0
    assert result["emotion"] == "Neutral"
    assert result["facePresent"] is True


def test_probe_attention_rejects_missing_face(monkeypatch):
    class _NoFace:
        is_ready = True

        def initialize(self):
            return True

        def analyze_frame(self, frame, context):
            return AnalysisResult(
                session_id=context.session_id,
                analyzer_type="attention",
                mode=AnalysisMode.REALTIME,
                timestamp=0.0,
                data={"score": 0.0, "face_present": False},
                confidence=0.0,
            )

    svc = AnalysisService.__new__(AnalysisService)
    svc._vision_pipeline = SimpleNamespace(
        attention_analyzer=_NoFace(),
        get_info=lambda: {"ok": True},
    )
    monkeypatch.setattr(
        svc,
        "_decode_frame",
        lambda frame_data: np.zeros((48, 48, 3), dtype=np.uint8),
    )
    result = svc.probe_attention("dGVzdA==", session_id="probe-noface")
    assert result["attentionOk"] is False
    assert result["emotionOk"] is False
    assert "face=missing" in (result.get("detail") or "")
