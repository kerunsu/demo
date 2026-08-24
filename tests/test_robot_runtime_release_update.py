from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import requests


def _release_zip(path: Path, version: str, *, include_sidecars: bool = True) -> bytes:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("EIArt-Robot/VERSION", version)
        archive.writestr("EIArt-Robot/RobotRuntime.exe", b"MZ" + b"\0" * (1024 * 1024))
        if include_sidecars:
            archive.writestr("EIArt-Robot/start.bat", b"@echo off\r\n")
    return path.read_bytes()


def _manifest(version: str, filename: str, payload: bytes) -> dict:
    return {
        "available": True,
        "version": version,
        "filename": filename,
        "latest": "EIArt-Robot-latest.zip",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "sizeBytes": len(payload),
    }


def test_release_resolver_requires_manifest_size_hash_and_embedded_version(tmp_path, monkeypatch):
    from app.robot import release_package

    monkeypatch.setattr(release_package, "RELEASE_DIR", tmp_path)
    release_package._VALIDATION_CACHE.clear()
    version = "20260823-1200-good"
    filename = f"EIArt-Robot-{version}.zip"
    payload = _release_zip(tmp_path / filename, version)
    meta = _manifest(version, filename, payload)

    path, resolved = release_package.resolve_zip_path(meta)

    assert path == tmp_path / filename
    assert resolved["available"] is True
    assert resolved["resolvedSha256"] == hashlib.sha256(payload).hexdigest()
    assert resolved["resolvedSizeBytes"] == len(payload)


def test_release_resolver_never_advertises_unrelated_latest_as_new_version(tmp_path, monkeypatch):
    from app.robot import release_package

    monkeypatch.setattr(release_package, "RELEASE_DIR", tmp_path)
    release_package._VALIDATION_CACHE.clear()
    old_payload = _release_zip(
        tmp_path / "EIArt-Robot-latest.zip",
        "20260811-0100-old",
    )
    declared_payload = b"new package bytes that were never copied"
    meta = _manifest(
        "20260823-1200-new",
        "EIArt-Robot-20260823-1200-new.zip",
        declared_payload,
    )

    path, resolved = release_package.resolve_zip_path(meta)

    assert path is None
    assert resolved["available"] is False
    assert "file missing" in resolved["error"]
    assert str(len(old_payload)) in resolved["error"]


def test_release_resolver_prefers_lightweight_update_package(tmp_path, monkeypatch):
    from app.robot import release_package

    monkeypatch.setattr(release_package, "RELEASE_DIR", tmp_path)
    release_package._VALIDATION_CACHE.clear()
    version = "20260823-1201-update"
    full_name = f"EIArt-Robot-{version}.zip"
    update_name = f"EIArt-Robot-Update-{version}.zip"
    full = _release_zip(tmp_path / full_name, version)
    update = _release_zip(tmp_path / update_name, version)
    meta = _manifest(version, full_name, full)
    meta.update({
        "updateFilename": update_name,
        "updateLatest": "EIArt-Robot-Update-latest.zip",
        "updateSha256": hashlib.sha256(update).hexdigest(),
        "updateSizeBytes": len(update),
    })

    path, resolved = release_package.resolve_update_zip_path(meta)

    assert path == tmp_path / update_name
    assert resolved["dedicatedUpdatePackage"] is True
    assert resolved["resolvedSizeBytes"] == len(update)


class _Response:
    def __init__(self, *, status=200, body=None, chunks=(), headers=None):
        self.status_code = status
        self._body = body or {}
        self._chunks = list(chunks)
        self.headers = headers or {}
        self.content = b"{}"
        self.text = ""

    def json(self):
        return dict(self._body)

    def iter_content(self, chunk_size=0):
        del chunk_size
        for item in self._chunks:
            if isinstance(item, BaseException):
                raise item
            yield item

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_update_check_selects_slim_package_and_blocks_timestamp_downgrade(monkeypatch):
    from robot_runtime import updater

    monkeypatch.setattr(updater, "read_runtime_version", lambda: "20260823-1300-local")
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setattr(
        updater.requests,
        "get",
        lambda *args, **kwargs: _Response(body={
            "version": "20260822-1200-remote",
            "available": True,
            "filename": "full.zip",
            "sizeBytes": 200,
            "sha256": "a" * 64,
            "downloadUrl": "/full",
            "updatePackageAvailable": True,
            "dedicatedUpdatePackage": True,
            "updateFilename": "update.zip",
            "updateSizeBytes": 100,
            "updateSha256": "b" * 64,
            "updateDownloadUrl": "/update",
        }),
    )

    result = updater.check_update("http://server:8080")

    assert result["available"] is True
    assert result["dedicatedUpdatePackage"] is True
    assert result["filename"] == "update.zip"
    assert result["downloadUrl"] == "/update"
    assert result["remoteOlder"] is True
    assert result["updateAvailable"] is False


def test_downloader_resumes_partial_file_after_network_interruption(tmp_path, monkeypatch):
    from robot_runtime import updater

    payload = b"0123456789" * 100
    calls = []

    def fake_get(url, *, headers, stream, timeout):
        del url, stream, timeout
        calls.append(dict(headers))
        if len(calls) == 1:
            return _Response(
                status=200,
                chunks=[payload[:300], requests.ConnectionError("cable interrupted")],
            )
        assert headers["Range"] == "bytes=300-"
        return _Response(
            status=206,
            headers={"Content-Range": f"bytes 300-{len(payload) - 1}/{len(payload)}"},
            chunks=[payload[300:]],
        )

    monkeypatch.setattr(updater.requests, "get", fake_get)
    monkeypatch.setattr(updater.time, "sleep", lambda _seconds: None)
    destination = tmp_path / "release.zip"

    error = updater._download_with_resume(
        "http://server/update.zip",
        destination,
        expected_size=len(payload),
        progress=None,
    )

    assert error is None
    assert destination.read_bytes() == payload
    assert len(calls) == 2


def test_download_prepare_verifies_hash_exe_and_embedded_version(tmp_path, monkeypatch):
    from robot_runtime import updater

    version = "20260823-1400-runtime"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("EIArt-Robot/VERSION", version)
        archive.writestr("EIArt-Robot/RobotRuntime.exe", b"MZ" + b"\0" * (1024 * 1024))
        archive.writestr("EIArt-Robot/start.bat", b"@echo off\r\n")
    payload = buffer.getvalue()
    monkeypatch.setattr(updater.register_client, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(
        updater,
        "check_update",
        lambda _base: {
            "ok": True,
            "available": True,
            "updateAvailable": True,
            "remoteOlder": False,
            "localVersion": "20260822-1000-old",
            "remoteVersion": version,
            "sizeBytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "downloadUrl": "/api/robot/runtime/download?kind=update",
            "dedicatedUpdatePackage": True,
        },
    )
    monkeypatch.setattr(
        updater.requests,
        "get",
        lambda *args, **kwargs: _Response(status=200, chunks=[payload]),
    )
    stages = []

    result = updater.download_and_prepare_update(
        "http://server:8080",
        progress=lambda event: stages.append(event["stage"]),
    )

    assert result["ok"] is True
    assert result["remoteVersion"] == version
    assert Path(result["exePath"]).read_bytes()[:2] == b"MZ"
    assert (Path(result["preparedDir"]) / "VERSION").read_text() == version
    assert stages == ["checking", "downloading", "downloading", "verifying", "extracting", "prepared"]


def test_runtime_update_ui_exposes_progress_status_and_failure_log():
    text = Path("robot_runtime/static/ui.html").read_text(encoding="utf-8")

    assert 'id="updateProgress"' in text
    assert 'fetch("/update/status?jobId="' in text
    assert 'fetch("/update/log"' in text
    assert "支持断点续传" in text
