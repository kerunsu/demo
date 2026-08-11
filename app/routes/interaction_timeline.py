"""HTTP query/export endpoints for the full interaction audit timeline."""
from __future__ import annotations

import json

from flask import Blueprint, Response, jsonify, request

from app.behavior.audit_timeline import get_full_interaction_timeline, record_audit_event


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


@interaction_timeline_bp.route("/<training_session_id>", methods=["GET"])
def get_timeline(training_session_id: str):
    store = get_full_interaction_timeline()
    try:
        rows = store.read(training_session_id)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    output_format = str(request.args.get("format") or "json").lower()
    if output_format == "jsonl":
        body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        return Response(body, mimetype="application/x-ndjson", headers={
            "Content-Disposition": f'attachment; filename="{training_session_id}-timeline.jsonl"'
        })
    if output_format == "csv":
        return Response(store.export_csv(training_session_id), mimetype="text/csv", headers={
            "Content-Disposition": f'attachment; filename="{training_session_id}-timeline.csv"'
        })
    return jsonify({
        "success": True,
        "schemaVersion": "full-interaction-timeline-v1",
        "trainingSessionId": training_session_id,
        "count": len(rows),
        "events": rows,
        "exports": {
            "jsonl": f"/api/v2/timeline/{training_session_id}?format=jsonl",
            "csv": f"/api/v2/timeline/{training_session_id}?format=csv",
        },
    })


__all__ = ["interaction_timeline_bp"]
