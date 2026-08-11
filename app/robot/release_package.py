"""Robot Runtime release package (zip under releases/robot/)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# app/robot/release_package.py -> repo root is parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_DIR = _REPO_ROOT / "releases" / "robot"
MANIFEST_NAME = "manifest.json"


def release_dir() -> Path:
    return RELEASE_DIR


def manifest_path() -> Path:
    return RELEASE_DIR / MANIFEST_NAME


def load_manifest() -> Dict[str, Any]:
    path = manifest_path()
    if not path.is_file():
        return {
            "available": False,
            "version": None,
            "filename": None,
            "latest": "EIArt-Robot-latest.zip",
            "sha256": None,
            "sizeBytes": 0,
            "builtAt": None,
            "error": "manifest.json missing — run scripts/pack_robot_release.ps1 on Windows",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "version": None,
            "filename": None,
            "latest": "EIArt-Robot-latest.zip",
            "sha256": None,
            "sizeBytes": 0,
            "builtAt": None,
            "error": f"invalid manifest: {exc}",
        }
    if not isinstance(data, dict):
        return {"available": False, "error": "manifest must be a JSON object"}
    return data


def resolve_zip_path(manifest: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Path], Dict[str, Any]]:
    """Return (zip_path_or_None, status_dict). Prefer versioned filename, then latest."""
    meta = dict(manifest or load_manifest())
    candidates = []
    filename = meta.get("filename")
    latest = meta.get("latest") or "EIArt-Robot-latest.zip"
    if filename:
        candidates.append(str(filename))
    if latest and latest not in candidates:
        candidates.append(str(latest))

    for name in candidates:
        path = RELEASE_DIR / name
        if path.is_file():
            size = path.stat().st_size
            meta["available"] = True
            meta["resolvedFilename"] = path.name
            meta["sizeBytes"] = meta.get("sizeBytes") or size
            return path, meta

    meta["available"] = False
    if "error" not in meta or not meta.get("error"):
        meta["error"] = (
            "release zip not found under releases/robot/ - "
            "build with scripts/pack_robot_release.ps1 and copy the zip to the server"
        )
    return None, meta
