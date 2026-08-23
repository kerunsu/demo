"""Validated Robot Runtime release packages under ``releases/robot``.

The manifest is the release transaction boundary: a zip is downloadable only
when its size, SHA-256 and embedded VERSION all match the manifest. This
prevents a missing versioned artifact from silently falling back to an older
``latest.zip`` while still advertising the newer manifest metadata.
"""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional, Tuple

# app/robot/release_package.py -> repo root is parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_DIR = _REPO_ROOT / "releases" / "robot"
MANIFEST_NAME = "manifest.json"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_VALIDATION_LOCK = RLock()
_VALIDATION_CACHE: Dict[tuple[Any, ...], Optional[str]] = {}


def release_dir() -> Path:
    return RELEASE_DIR


def manifest_path() -> Path:
    return RELEASE_DIR / MANIFEST_NAME


def _unavailable(error: str) -> Dict[str, Any]:
    return {
        "available": False,
        "version": None,
        "filename": None,
        "latest": "EIArt-Robot-latest.zip",
        "sha256": None,
        "sizeBytes": 0,
        "builtAt": None,
        "error": error,
    }


def load_manifest() -> Dict[str, Any]:
    path = manifest_path()
    if not path.is_file():
        return _unavailable(
            "manifest.json missing — run scripts/pack_robot_release.ps1 on Windows"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        return _unavailable(f"invalid manifest: {exc}")
    if not isinstance(data, dict):
        return _unavailable("manifest must be a JSON object")
    return data


def _safe_release_name(value: Any) -> Optional[str]:
    name = str(value or "").strip()
    if not name or Path(name).name != name or not name.lower().endswith(".zip"):
        return None
    return name


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _embedded_version(path: Path) -> Optional[str]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            version_entries = [
                item
                for item in archive.namelist()
                if Path(item.replace("\\", "/")).name == "VERSION"
            ]
            if not version_entries:
                return None
            entry = min(version_entries, key=lambda item: item.count("/"))
            return archive.read(entry).decode("utf-8-sig").strip() or None
    except (OSError, UnicodeError, zipfile.BadZipFile):
        return None


def _validate_candidate(
    path: Path,
    *,
    expected_size: Any,
    expected_sha256: Any,
    expected_version: Any,
) -> Optional[str]:
    try:
        size = int(expected_size)
    except (TypeError, ValueError):
        return "manifest sizeBytes is missing or invalid"
    expected_hash = str(expected_sha256 or "").strip().lower()
    version = str(expected_version or "").strip()
    if size <= 0:
        return "manifest sizeBytes must be positive"
    if not _SHA256_RE.fullmatch(expected_hash):
        return "manifest sha256 is missing or invalid"
    if not version:
        return "manifest version is missing"
    try:
        stat = path.stat()
    except OSError as exc:
        return f"release zip cannot be read: {exc}"
    if stat.st_size != size:
        return f"release size mismatch: manifest={size}, actual={stat.st_size}"

    cache_key = (
        str(path.resolve()),
        stat.st_mtime_ns,
        stat.st_size,
        expected_hash,
        version,
    )
    with _VALIDATION_LOCK:
        if cache_key in _VALIDATION_CACHE:
            return _VALIDATION_CACHE[cache_key]

    actual_hash = _sha256(path)
    if actual_hash != expected_hash:
        error = (
            "release sha256 mismatch: "
            f"manifest={expected_hash}, actual={actual_hash}"
        )
    else:
        embedded = _embedded_version(path)
        error = None if embedded == version else (
            "release VERSION mismatch: "
            f"manifest={version}, embedded={embedded or 'missing'}"
        )
    with _VALIDATION_LOCK:
        _VALIDATION_CACHE[cache_key] = error
    return error


def _package_fields(meta: Dict[str, Any], kind: str) -> Dict[str, Any]:
    if kind == "update" and meta.get("updateFilename"):
        return {
            "filename": meta.get("updateFilename"),
            "latest": meta.get("updateLatest") or "EIArt-Robot-Update-latest.zip",
            "sha256": meta.get("updateSha256"),
            "sizeBytes": meta.get("updateSizeBytes"),
            "dedicated": True,
        }
    return {
        "filename": meta.get("filename"),
        "latest": meta.get("latest") or "EIArt-Robot-latest.zip",
        "sha256": meta.get("sha256"),
        "sizeBytes": meta.get("sizeBytes"),
        "dedicated": False,
    }


def resolve_zip_path(
    manifest: Optional[Dict[str, Any]] = None,
    *,
    kind: str = "full",
) -> Tuple[Optional[Path], Dict[str, Any]]:
    """Resolve and strongly validate a full-install or hot-update zip.

    The versioned filename is preferred. ``latest`` is accepted only when it
    contains the exact same bytes and embedded version declared by the
    manifest, making the fallback an alias rather than an unrelated package.
    """
    meta = dict(manifest or load_manifest())
    if kind not in {"full", "update"}:
        meta.update({"available": False, "error": f"unsupported package kind: {kind}"})
        return None, meta
    fields = _package_fields(meta, kind)
    candidates = []
    invalid_names = []
    for raw_name in (fields["filename"], fields["latest"]):
        if not raw_name:
            continue
        safe_name = _safe_release_name(raw_name)
        if not safe_name:
            invalid_names.append(str(raw_name))
            continue
        if safe_name not in candidates:
            candidates.append(safe_name)

    errors = []
    for name in candidates:
        path = RELEASE_DIR / name
        if not path.is_file():
            errors.append(f"{name}: file missing")
            continue
        error = _validate_candidate(
            path,
            expected_size=fields["sizeBytes"],
            expected_sha256=fields["sha256"],
            expected_version=meta.get("version"),
        )
        if error:
            errors.append(f"{name}: {error}")
            continue
        meta.update({
            "available": True,
            "packageKind": kind,
            "dedicatedUpdatePackage": bool(fields["dedicated"]),
            "resolvedFilename": path.name,
            "resolvedSizeBytes": path.stat().st_size,
            "resolvedSha256": str(fields["sha256"]).lower(),
        })
        return path, meta

    if invalid_names:
        errors.append("unsafe manifest filenames: " + ", ".join(invalid_names))
    meta["available"] = False
    meta["packageKind"] = kind
    meta["error"] = (
        f"{kind} release unavailable or inconsistent: " + "; ".join(errors)
        if errors
        else f"{kind} release not declared in manifest"
    )
    return None, meta


def resolve_update_zip_path(
    manifest: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Path], Dict[str, Any]]:
    return resolve_zip_path(manifest, kind="update")
