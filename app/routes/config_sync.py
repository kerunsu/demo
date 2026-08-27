"""Configuration-center collaboration manifest and export package."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from flask import Blueprint, after_this_request, jsonify, send_file

from app.config import BASE_DIR
from app.course_scope import is_course_type_enabled
from database.models import CourseType


config_sync_bp = Blueprint("config_sync", __name__, url_prefix="/api/v2/config/sync")
_ROOT = Path(BASE_DIR).resolve()
_EXCLUDED_DOLL_DATA = {"students.json"}


def _iter_sync_files() -> Iterable[tuple[Path, str]]:
    roots = [
        (_ROOT / "config", "configuration"),
        (_ROOT / "doll" / "data", "demo-behavior-data"),
        (_ROOT / "static" / "resources", "content-media"),
    ]
    seen: set[Path] = set()
    for root, kind in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen or _ROOT not in resolved.parents:
                continue
            if root == _ROOT / "doll" / "data" and path.name in _EXCLUDED_DOLL_DATA:
                continue
            if path.name in {"motions.json", "emotions_meta.json"}:
                continue
            if any(part.casefold() == "emotions" for part in path.parts):
                continue
            if any(part in {"recordings", "results", "temp", ".runtime"} for part in path.parts):
                continue
            seen.add(resolved)
            yield path, kind


def _course_catalog() -> dict[str, Any]:
    courses: list[dict[str, Any]] = []
    for course_type in CourseType.query.order_by(CourseType.id).all():
        for course in sorted(course_type.courses, key=lambda item: item.id):
            if not is_course_type_enabled(course.to_dict().get("type")):
                continue
            courses.append({
                "id": course.id,
                "typeId": course_type.id,
                "type": course_type.name,
                "title": course.title,
                "icon": course.icon,
                "questionAudio": course.question_audio,
                "praiseAudio": course.praise_audio,
                "entryFile": course.entry_file,
                "items": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "type": item.type,
                        "icon": item.icon,
                        "mediaFile": item.media_file,
                        "hintAudio": item.hint_audio,
                        "difficulty": item.difficulty,
                        "config": item.config,
                        "speechTarget": getattr(item, "speech_target", None),
                    }
                    for item in course.items
                ],
            })
    return {
        "schemaVersion": 1,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "courses": courses,
    }


def build_sync_manifest() -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for path, kind in _iter_sync_files():
        data = path.read_bytes()
        relative = path.relative_to(_ROOT).as_posix()
        files.append({
            "path": relative,
            "kind": kind,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
        total_bytes += len(data)
    catalog = _course_catalog()
    return {
        "schemaVersion": 1,
        "packageType": "demo-machine-config-center",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "fileCount": len(files),
        "totalBytes": total_bytes,
        "courseCount": len(catalog["courses"]),
        "excluded": [
            "database/app.db (target database must never be replaced by Git)",
            "static/recordings, static/results, static/temp",
            "doll/data/students.json (student personal data)",
            "robot motion/runtime files (Demo has no mechanical structure)",
            "static/resources/Emotions and emotions_meta.json (Demo expression system is external)",
        ],
    }


@config_sync_bp.route("/manifest", methods=["GET"])
def sync_manifest():
    try:
        return jsonify({"success": True, "manifest": build_sync_manifest()})
    except Exception as exc:  # pragma: no cover - defensive API envelope
        return jsonify({"success": False, "error": str(exc)}), 500


@config_sync_bp.route("/export", methods=["GET"])
def export_sync_package():
    """Download a reviewable package for Git/manual collaboration."""
    temp_dir = Path(tempfile.mkdtemp(prefix="config-center-sync-"))
    zip_path = temp_dir / "config-center-sync.zip"
    try:
        manifest = build_sync_manifest()
        catalog = _course_catalog()
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("config/sync_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
            archive.writestr("config/sync/course_catalog.json", json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True))
            archive.writestr(
                "config/sync/README.txt",
                "本包用于配置中心协作同步。请先检查 sync_manifest.json，再将文件合并到仓库。\n"
                "不要用包内内容覆盖目标 database/app.db；课程目录请按 course_catalog.json 做增量导入。\n",
            )
            for entry in manifest["files"]:
                path = _ROOT / entry["path"]
                archive.write(path, entry["path"])

        @after_this_request
        def cleanup(response):
            shutil.rmtree(temp_dir, ignore_errors=True)
            return response

        return send_file(zip_path, as_attachment=True, download_name="config-center-sync.zip", mimetype="application/zip")
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
