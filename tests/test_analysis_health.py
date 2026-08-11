from app.services import analysis_service as analysis_module


class _FakePipeline:
    def __init__(self, _config, *, name, initialized, failures):
        self.name = name
        self.is_initialized = initialized
        self._failures = failures

    def initialize(self):
        return self.is_initialized

    def get_info(self):
        return {
            "name": self.name,
            "is_initialized": self.is_initialized,
            "initialization_failures": list(self._failures),
        }


def test_analysis_diagnostics_report_required_pipeline_failure(monkeypatch):
    monkeypatch.setattr(
        analysis_module,
        "VisionPipeline",
        lambda config: _FakePipeline(
            config, name="vision", initialized=False,
            failures=[{
                "component": "attention",
                "required": True,
                "stage": "initialize",
                "error": "mediapipe solutions unavailable",
            }],
        ),
    )
    monkeypatch.setattr(
        analysis_module,
        "AudioPipeline",
        lambda config: _FakePipeline(
            config, name="audio", initialized=True, failures=[]
        ),
    )

    service = analysis_module.AnalysisService()
    service.wait_for_audio_initialization(timeout=1)
    diagnostics = service.get_diagnostics()

    assert diagnostics["ready"] is False
    assert diagnostics["status"] == "unhealthy"
    assert diagnostics["visionPipelineInitialized"] is False
    assert diagnostics["audioPipelineInitialized"] is True
    assert diagnostics["pipelineHealth"]["requiredFailures"][0] == {
        "pipeline": "vision",
        "component": "attention",
        "required": True,
        "stage": "initialize",
        "error": "mediapipe solutions unavailable",
    }


def test_optional_pipeline_failure_is_visible_but_does_not_fake_unhealthy(monkeypatch):
    monkeypatch.setattr(
        analysis_module,
        "VisionPipeline",
        lambda config: _FakePipeline(
            config, name="vision", initialized=True,
            failures=[{
                "component": "face",
                "required": False,
                "stage": "create",
                "error": "optional model missing",
            }],
        ),
    )
    monkeypatch.setattr(
        analysis_module,
        "AudioPipeline",
        lambda config: _FakePipeline(
            config, name="audio", initialized=True, failures=[]
        ),
    )

    service = analysis_module.AnalysisService()
    service.wait_for_audio_initialization(timeout=1)
    diagnostics = service.get_diagnostics()
    assert diagnostics["ready"] is True
    assert diagnostics["degraded"] is True
    assert diagnostics["status"] == "degraded"
    assert diagnostics["pipelineHealth"]["requiredFailures"] == []
