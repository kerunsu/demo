from pathlib import Path
from types import SimpleNamespace
import threading


def test_voice_model_bootstrap_reuses_complete_manifest(tmp_path, monkeypatch):
    from app.utils import voice_service_launcher as launcher

    paths = {}
    for key in (
        "VOICE_SERVICE_FUNASR_MODEL",
        "VOICE_SERVICE_FUNASR_VAD_MODEL",
        "VOICE_SERVICE_FUNASR_PUNC_MODEL",
    ):
        path = tmp_path / key.lower()
        path.mkdir()
        paths[key] = str(path)
    monkeypatch.setattr(launcher, "_read_voice_model_paths", lambda: paths)
    monkeypatch.setattr(
        launcher,
        "_run_checked",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )
    env = {"VOICE_SERVICE_STT_PROVIDER": "local-funasr"}
    assert launcher._prepare_voice_models("python", env)
    assert env["VOICE_SERVICE_FUNASR_MODEL"] == paths["VOICE_SERVICE_FUNASR_MODEL"]


def test_voice_model_bootstrap_installs_then_downloads(tmp_path, monkeypatch):
    from app.utils import voice_service_launcher as launcher

    calls = []
    ready_paths = {}
    for key in (
        "VOICE_SERVICE_FUNASR_MODEL",
        "VOICE_SERVICE_FUNASR_VAD_MODEL",
        "VOICE_SERVICE_FUNASR_PUNC_MODEL",
    ):
        path = tmp_path / key.lower()
        path.mkdir()
        ready_paths[key] = str(path)

    manifests = iter([{}, ready_paths])
    monkeypatch.setattr(launcher, "_read_voice_model_paths", lambda: next(manifests))
    monkeypatch.setattr(launcher, "_env_flag", lambda name, default: True)

    def run(command, **kwargs):
        calls.append(command)
        if command[1:3] == ["-c", "import torch, funasr, modelscope"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="missing")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(launcher, "_run_checked", run)
    env = {"VOICE_SERVICE_STT_PROVIDER": "local-funasr"}
    assert launcher._prepare_voice_models("voice-python", env)
    assert any(command[1:4] == ["-m", "pip", "install"] for command in calls)
    assert any(Path(command[1]).name == "prepare_models.py" for command in calls if len(command) == 2)
    assert env["VOICE_SERVICE_FUNASR_MODEL"] == ready_paths["VOICE_SERVICE_FUNASR_MODEL"]


def test_start_voice_service_does_not_wait_for_model_download(monkeypatch):
    from app.utils import voice_service_launcher as launcher

    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(launcher, "should_start_voice_service", lambda: True)
    monkeypatch.setattr(launcher, "_port_listening", lambda *args, **kwargs: False)
    monkeypatch.setattr(launcher, "_voice_proc", None)
    monkeypatch.setattr(launcher, "_startup_thread", None)

    def slow_start(logger=None):
        entered.set()
        release.wait(timeout=2)
        return True

    monkeypatch.setattr(launcher, "_start_voice_service_sync", slow_start)
    assert launcher.start_voice_service()
    assert entered.wait(timeout=1)
    thread = launcher._startup_thread
    assert thread is not None and thread.is_alive()
    release.set()
    thread.join(timeout=1)


def test_start_voice_service_schedules_only_one_worker(monkeypatch):
    from app.utils import voice_service_launcher as launcher

    entered = threading.Event()
    release = threading.Event()
    calls = []
    monkeypatch.setattr(launcher, "should_start_voice_service", lambda: True)
    monkeypatch.setattr(launcher, "_port_listening", lambda *args, **kwargs: False)
    monkeypatch.setattr(launcher, "_voice_proc", None)
    monkeypatch.setattr(launcher, "_startup_thread", None)

    def slow_start(logger=None):
        calls.append(1)
        entered.set()
        release.wait(timeout=2)
        return True

    monkeypatch.setattr(launcher, "_start_voice_service_sync", slow_start)
    assert launcher.start_voice_service()
    assert entered.wait(timeout=1)
    thread = launcher._startup_thread
    assert launcher.start_voice_service()
    assert calls == [1]
    release.set()
    thread.join(timeout=1)
