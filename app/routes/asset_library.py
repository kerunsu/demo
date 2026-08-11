"""版本化动作/表情批量素材控制面；旧单文件 API 保持不变。"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.robot.batch_asset_import import get_batch_asset_importer


asset_library_bp = Blueprint("asset_library", __name__, url_prefix="/api/v2/assets")


def _files():
    files = request.files.getlist("files")
    if not files:
        files = request.files.getlist("file")
    return files


def _read_uploads_limited(uploads, importer):
    """Read at most configured item/total limits plus one sentinel byte."""
    remaining = int(importer.max_total_bytes)
    items = []
    for upload in uploads:
        item_limit = int(importer.max_item_bytes)
        read_limit = min(item_limit + 1, max(1, remaining + 1))
        content = upload.stream.read(read_limit)
        oversized = len(content) > item_limit or len(content) > remaining
        if not oversized:
            remaining -= len(content)
        items.append({
            "filename": upload.filename,
            "content": content,
            "mimeType": upload.mimetype,
            "oversized": oversized,
        })
    return items


@asset_library_bp.route("/batch-import", methods=["POST"])
def stage_asset_batch():
    kind = request.form.get("kind") or (request.get_json(silent=True) or {}).get("kind")
    uploads = _files()
    if not kind or not uploads:
        return jsonify({"success": False, "error": "kind_and_files_required"}), 400
    try:
        importer = get_batch_asset_importer()
        expanded = []
        for item in _read_uploads_limited(uploads, importer):
            filename = str(item.get("filename") or "")
            if filename.lower().endswith(".zip"):
                if item.get("oversized"):
                    expanded.append(item)
                else:
                    expanded.extend(importer.expand_zip(kind, item.get("content", b"")))
            else:
                expanded.append(item)
        record = importer.stage(
            kind=kind,
            items=expanded,
        )
        commit = str(request.form.get("commit") or "false").lower() == "true"
        if commit:
            result = importer.commit(
                record["stagingId"],
                conflict=request.form.get("conflict") or "skip",
            )
            return jsonify({"success": bool(result.get("success")), **result})
        return jsonify({"success": True, "stage": record})
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:  # pragma: no cover - defensive transport boundary
        return jsonify({"success": False, "error": str(exc)}), 500


@asset_library_bp.route("/batch-import/<staging_id>", methods=["GET"])
def preview_asset_batch(staging_id: str):
    try:
        return jsonify({"success": True, "stage": get_batch_asset_importer().preview(staging_id)})
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404


@asset_library_bp.route("/batch-import/<staging_id>/commit", methods=["POST"])
def commit_asset_batch(staging_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        result = get_batch_asset_importer().commit(
            staging_id,
            conflict=payload.get("conflict") or "skip",
        )
        return jsonify({"success": bool(result.get("success")), **result})
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@asset_library_bp.route("/batch-import/<staging_id>/rollback", methods=["POST"])
def rollback_asset_batch(staging_id: str):
    try:
        result = get_batch_asset_importer().rollback(staging_id)
        return jsonify({"success": True, **result})
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404


__all__ = ["asset_library_bp"]
