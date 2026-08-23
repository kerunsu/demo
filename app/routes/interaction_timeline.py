"""HTTP query/export endpoints for the full interaction audit timeline."""
from __future__ import annotations

import json

from flask import Blueprint, Response, jsonify, request

from app.behavior.audit_timeline import get_full_interaction_timeline, record_audit_event
from app.diagnostics.latency_report import build_latency_report, render_latency_markdown
from app.storage.session_catalog import build_session_catalog


interaction_timeline_bp = Blueprint("interaction_timeline", __name__, url_prefix="/api/v2/timeline")


@interaction_timeline_bp.route("/events", methods=["POST"])
def append_timeline_event():
    payload = request.get_json(silent=True) or {}
    event = str(payload.get("event") or "").strip()
    if not event:
        return jsonify({"success": False, "error": "event_required"}), 400
    item = record_audit_event(
        event,
        training_session_id=payload.get("trainingSessionId") or payload.get("training_session_id"),
        runtime_session_id=payload.get("sessionId") or payload.get("session_id"),
        question_id=payload.get("questionId") or payload.get("question_id"),
        request_id=payload.get("requestId") or payload.get("request_id"),
        behavior_id=payload.get("behaviorId") or payload.get("behavior_id"),
        actor=payload.get("actor") or "client",
        source=payload.get("source") or "browser",
        category=payload.get("category") or "ui",
        phase=payload.get("phase"),
        status=payload.get("status"),
        modality=payload.get("modality"),
        client_timestamp=payload.get("clientTimestamp") or payload.get("client_timestamp"),
        degraded=bool(payload.get("degraded")),
        error=payload.get("error"),
        details=payload.get("details"),
    )
    if item is None:
        return jsonify({"success": False, "error": "training_session_not_resolved"}), 409
    return jsonify({"success": True, "event": item}), 201


@interaction_timeline_bp.route("/latency/sessions", methods=["GET"])
def list_latency_sessions():
    """List recording sessions that can own a persistent latency report."""
    try:
        limit = max(1, min(int(request.args.get("limit") or 100), 500))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "limit_must_be_integer"}), 400
    catalog = build_session_catalog(limit=limit)
    sessions = []
    for item in catalog.get("sessions") or []:
        training_id = item.get("trainingSessionId")
        if not training_id:
            continue
        student = item.get("student") if isinstance(item.get("student"), dict) else {}
        sessions.append({
            "trainingSessionId": str(training_id),
            "mediaSessionId": item.get("mediaSessionId"),
            "folderName": item.get("folderName"),
            "studentName": student.get("name") or "未关联儿童",
            "recordingStartedAt": item.get("recordingStartedAt"),
            "status": item.get("status"),
            "liveActive": bool(item.get("liveActive")),
        })
    return jsonify({
        "success": True,
        "schemaVersion": "interaction-latency-session-list-v1",
        "sessions": sessions,
    })


@interaction_timeline_bp.route("/<training_session_id>/latency", methods=["GET"])
def get_latency_report(training_session_id: str):
    store = get_full_interaction_timeline()
    media_session_id = str(
        request.args.get("mediaSessionId")
        or request.args.get("sessionId")
        or ""
    ).strip() or None
    try:
        report = build_latency_report(
            training_session_id,
            store.read(training_session_id, media_session_id),
            media_session_id=media_session_id,
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    output_format = str(request.args.get("format") or "json").strip().lower()
    if output_format in {"md", "markdown"}:
        return Response(
            render_latency_markdown(report),
            mimetype="text/markdown",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{training_session_id}-latency-report.md"'
                )
            },
        )
    return jsonify(report)


@interaction_timeline_bp.route("/<training_session_id>", methods=["GET"])
def get_timeline(training_session_id: str):
    store = get_full_interaction_timeline()
    media_session_id = str(
        request.args.get("mediaSessionId")
        or request.args.get("sessionId")
        or ""
    ).strip() or None
    try:
        rows = store.read(training_session_id, media_session_id)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    output_format = str(request.args.get("format") or "json").lower()
    if output_format == "jsonl":
        body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        return Response(body, mimetype="application/x-ndjson", headers={
            "Content-Disposition": f'attachment; filename="{training_session_id}-timeline.jsonl"'
        })
    if output_format == "csv":
        return Response(store.export_csv(training_session_id, media_session_id), mimetype="text/csv", headers={
            "Content-Disposition": f'attachment; filename="{training_session_id}-timeline.csv"'
        })
    media_query = (
        f"&mediaSessionId={media_session_id}" if media_session_id else ""
    )
    return jsonify({
        "success": True,
        "schemaVersion": "full-interaction-timeline-v1",
        "trainingSessionId": training_session_id,
        "mediaSessionId": media_session_id,
        "count": len(rows),
        "events": rows,
        "exports": {
            "jsonl": (
                f"/api/v2/timeline/{training_session_id}?format=jsonl"
                f"{media_query}"
            ),
            "csv": (
                f"/api/v2/timeline/{training_session_id}?format=csv"
                f"{media_query}"
            ),
        },
    })


__all__ = ["interaction_timeline_bp"]
