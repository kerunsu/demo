"""F-Algo：camera_analysis / report_scoring 校验与写盘 API。"""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from flask import Flask, render_template

from app.behavior import camera_config as cam_mod
from app.behavior.camera_config import (
    load_camera_analysis_config,
    save_camera_analysis_config,
    validate_camera_analysis_config,
)
from app.report.scoring import (
    load_scoring_config,
    save_scoring_config,
    validate_scoring_config,
)
from app.routes.server_config_files import server_config_files_bp

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "tests" / "_tmp_algo"


def _fresh_scratch() -> Path:
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH, ignore_errors=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    return SCRATCH


def test_validate_camera_rejects_non_positive_fps():
    errs = validate_camera_analysis_config({"fps": 0, "width": 160, "height": 120})
    assert any("fps" in e for e in errs)


def test_validate_camera_rejects_bad_factor():
    errs = validate_camera_analysis_config({"attention_incomplete_factor": 1.5})
    assert any("attention_incomplete_factor" in e for e in errs)


def test_save_camera_writes_bak(monkeypatch):
    scratch = _fresh_scratch()
    path = scratch / "camera_analysis.yaml"
    path.write_text("enabled: true\nfps: 1\nwidth: 160\nheight: 120\n", encoding="utf-8")
    monkeypatch.setattr(cam_mod, "_CAMERA_PATH", path)

    saved = save_camera_analysis_config(
        {
            "enabled": True,
            "fps": 2,
            "width": 320,
            "height": 240,
            "prefer_browser_for_report": False,
            "prefer_browser_when_media_mode_browser": True,
            "attention_incomplete_factor": 0.7,
            "emotion_min_samples": 2,
        }
    )
    assert saved["fps"] == 2
    bak = path.with_suffix(path.suffix + ".bak")
    assert bak.exists()
    reloaded = load_camera_analysis_config()
    assert reloaded["fps"] == 2
    assert reloaded["width"] == 320


def test_validate_scoring_weights_must_sum_100():
    bad = {
        "weights": {
            "attention": 10,
            "matching": 10,
            "ordering": 10,
        }
    }
    errs = validate_scoring_config(bad)
    assert any("100" in e for e in errs)


def test_validate_scoring_ok_when_sum_100():
    cfg = {
        "weights": {
            "attention": 34,
            "matching": 33,
            "ordering": 33,
        },
        "narrative_provider": "rule",
    }
    assert validate_scoring_config(cfg) == []


def test_save_scoring_writes_bak(monkeypatch):
    scratch = _fresh_scratch()
    config_dir = scratch / "config"
    config_dir.mkdir()
    target = config_dir / "report_scoring.yaml"
    base = {
        "schema_version": "test-v",
        "weights": {
            "attention": 34,
            "matching": 33,
            "ordering": 33,
        },
        "narrative_provider": "rule",
        "interactive_course": {},
        "grade_thresholds": {"excellent": 85, "good": 70, "fair": 55, "needs_support": 0},
    }
    target.write_text(yaml.safe_dump(base), encoding="utf-8")
    monkeypatch.setattr("app.config.BASE_DIR", scratch)

    new_cfg = dict(base)
    new_cfg["weights"] = {
        "attention": 40,
        "matching": 30,
        "ordering": 30,
    }
    saved = save_scoring_config(new_cfg)
    assert saved["weights"]["attention"] == 40
    bak = target.with_suffix(target.suffix + ".bak")
    assert bak.exists()
    loaded = load_scoring_config()
    assert loaded["weights"]["attention"] == 40


def _patch_config_files(monkeypatch):
    scratch = _fresh_scratch()
    cam = scratch / "camera_analysis.yaml"
    cam.write_text(
        yaml.safe_dump(
            {
                "enabled": True,
                "fps": 1,
                "width": 160,
                "height": 120,
                "prefer_browser_for_report": False,
                "prefer_browser_when_media_mode_browser": True,
                "attention_incomplete_factor": 0.7,
                "emotion_min_samples": 2,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cam_mod, "_CAMERA_PATH", cam)

    config_dir = scratch / "config"
    config_dir.mkdir(exist_ok=True)
    rep = config_dir / "report_scoring.yaml"
    rep.write_text(
        yaml.safe_dump(
            {
                "schema_version": "education-training-index-v2-teacher-rating",
                "weights": {
                    "attention": 34,
                    "matching": 33,
                    "ordering": 33,
                },
                "narrative_provider": "rule",
                "interactive_course": {
                    "accuracy_weight": 0.75,
                    "response_weight": 0.25,
                    "objective_weight": 0.7,
                    "teacher_weight": 0.3,
                    "ideal_response_sec": 3,
                    "slow_response_sec": 12,
                },
                "grade_thresholds": {
                    "excellent": 85,
                    "good": 70,
                    "fair": 55,
                    "needs_support": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.config.BASE_DIR", scratch)
    return scratch


def _api_client():
    app = Flask(__name__)
    app.register_blueprint(server_config_files_bp)
    app.config["TESTING"] = True
    return app.test_client()


def test_api_camera_get_put(monkeypatch):
    _patch_config_files(monkeypatch)
    client = _api_client()

    r = client.get("/api/server/config/camera-analysis")
    assert r.status_code == 200
    assert r.get_json()["success"] is True
    assert r.get_json()["config"]["fps"] == 1

    bad = client.put(
        "/api/server/config/camera-analysis",
        json={"config": {"fps": -1}},
    )
    assert bad.status_code == 400

    ok = client.put(
        "/api/server/config/camera-analysis",
        json={
            "config": {
                "enabled": True,
                "fps": 3,
                "width": 160,
                "height": 120,
                "prefer_browser_for_report": False,
                "prefer_browser_when_media_mode_browser": True,
                "attention_incomplete_factor": 0.7,
                "emotion_min_samples": 2,
            }
        },
    )
    assert ok.status_code == 200
    assert ok.get_json()["config"]["fps"] == 3


def test_api_report_weights_reject_and_accept(monkeypatch):
    _patch_config_files(monkeypatch)
    client = _api_client()

    bad = client.put(
        "/api/server/config/report-scoring",
        json={
            "config": {
                "weights": {
                    "attention": 10,
                    "matching": 10,
                    "ordering": 10,
                }
            }
        },
    )
    assert bad.status_code == 400
    assert "100" in (bad.get_json().get("error") or "")

    ok = client.put(
        "/api/server/config/report-scoring",
        json={
            "config": {
                "weights": {
                    "attention": 40,
                    "matching": 30,
                    "ordering": 30,
                },
                "narrative_provider": "mock",
            }
        },
    )
    assert ok.status_code == 200
    body = ok.get_json()
    assert body["config"]["weights"]["attention"] == 40
    assert body["config"]["narrative_provider"] == "mock"


def test_config_shell_modules_render():
    """壳模板可按 active_module 渲染（不启动完整 app.py）。"""
    app = Flask(
        __name__,
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    app.config["TESTING"] = True

    @app.route("/m/<module>")
    def page(module):
        return render_template("server/config.html", active_module=module)

    client = app.test_client()
    for module in ("overview", "camera", "speech", "report", "content"):
        r = client.get(f"/m/{module}")
        assert r.status_code == 200, module
        html = r.get_data(as_text=True)
        assert f'data-module="{module}"' in html or f'id="module-{module}"' in html
