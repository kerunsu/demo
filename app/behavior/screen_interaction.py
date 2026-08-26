"""Child-screen click validation and derived interaction summaries.

Raw clicks remain immutable events in ``full_interaction_timeline.jsonl``.
This module validates the bounded browser payload and derives per-question and
per-session counts without creating a second raw click store.
"""
from __future__ import annotations

from collections import Counter
import math
import re
from typing import Any, Dict, Iterable, Mapping, Optional


CLICK_EVENT = "child_screen_click"
TRACKING_STARTED_EVENT = "child_screen_tracking_started"
CLICK_SCHEMA_VERSION = "child-screen-click-v1"
TRACKING_SCHEMA_VERSION = "child-screen-tracking-v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_POINTER_TYPES = {"mouse", "touch", "pen"}
_PAGE_TYPES = {"child_main", "interactive_iframe"}
_INTERACTION_KINDS = {"task", "dialogue", "control", "blank", "other"}


def _text(value: Any, *, limit: int = 160, default: str = "") -> str:
    text = str(value or "").strip()
    return text[:limit] if text else default


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field}_must_be_number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field}_must_be_number") from None
    if not math.isfinite(number):
        raise ValueError(f"{field}_must_be_finite")
    return number


def _bounded_number(
    value: Any,
    field: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    number = _finite(value, field)
    if number < minimum or number > maximum:
        raise ValueError(f"{field}_out_of_range")
    return number


def _optional_number(
    value: Any,
    field: str,
    *,
    minimum: float,
    maximum: float,
) -> Optional[float]:
    if value is None:
        return None
    return _bounded_number(value, field, minimum=minimum, maximum=maximum)


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field}_must_be_integer")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field}_must_be_integer") from None
    if number < 1 or number > 1_000_000_000:
        raise ValueError(f"{field}_out_of_range")
    return number


def _ratio(value: Any, field: str, *, numerator: float, denominator: float) -> float:
    provided = _bounded_number(value, field, minimum=0, maximum=1)
    computed = numerator / max(1.0, denominator)
    if abs(provided - computed) > 0.01:
        raise ValueError(f"{field}_mismatch")
    return round(computed, 6)


def _optional_identifier(value: Any, field: str) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or isinstance(value, (dict, list, tuple, set)):
        raise ValueError(f"{field}_invalid")
    if isinstance(value, int):
        return value
    text = _text(value, limit=160)
    if not text:
        return None
    return text


def _validate_viewport(details: Mapping[str, Any]) -> Dict[str, float]:
    width = _bounded_number(
        details.get("viewportWidth"), "viewport_width", minimum=1, maximum=100_000
    )
    height = _bounded_number(
        details.get("viewportHeight"), "viewport_height", minimum=1, maximum=100_000
    )
    x = _bounded_number(
        details.get("viewportX"), "viewport_x", minimum=0, maximum=width
    )
    y = _bounded_number(
        details.get("viewportY"), "viewport_y", minimum=0, maximum=height
    )
    return {
        "viewportX": round(x, 3),
        "viewportY": round(y, 3),
        "viewportWidth": round(width, 3),
        "viewportHeight": round(height, 3),
        "viewportXRatio": _ratio(
            details.get("viewportXRatio"),
            "viewport_x_ratio",
            numerator=x,
            denominator=width,
        ),
        "viewportYRatio": _ratio(
            details.get("viewportYRatio"),
            "viewport_y_ratio",
            numerator=y,
            denominator=height,
        ),
    }


def _validate_content(details: Mapping[str, Any]) -> Dict[str, Optional[float]]:
    values = {
        "contentX": details.get("contentX"),
        "contentY": details.get("contentY"),
        "contentWidth": details.get("contentWidth"),
        "contentHeight": details.get("contentHeight"),
        "contentXRatio": details.get("contentXRatio"),
        "contentYRatio": details.get("contentYRatio"),
    }
    if all(value is None for value in values.values()):
        return {key: None for key in values}
    if any(value is None for value in values.values()):
        raise ValueError("content_coordinates_incomplete")
    width = _bounded_number(
        values["contentWidth"], "content_width", minimum=1, maximum=100_000
    )
    height = _bounded_number(
        values["contentHeight"], "content_height", minimum=1, maximum=100_000
    )
    x = _bounded_number(values["contentX"], "content_x", minimum=0, maximum=width)
    y = _bounded_number(values["contentY"], "content_y", minimum=0, maximum=height)
    return {
        "contentX": round(x, 3),
        "contentY": round(y, 3),
        "contentWidth": round(width, 3),
        "contentHeight": round(height, 3),
        "contentXRatio": _ratio(
            values["contentXRatio"],
            "content_x_ratio",
            numerator=x,
            denominator=width,
        ),
        "contentYRatio": _ratio(
            values["contentYRatio"],
            "content_y_ratio",
            numerator=y,
            denominator=height,
        ),
    }


def _validated_target(value: Any) -> Dict[str, Any]:
    target = value if isinstance(value, Mapping) else {}
    interaction_kind = _text(target.get("interactionKind"), limit=32, default="other")
    if interaction_kind not in _INTERACTION_KINDS:
        interaction_kind = "other"
    return {
        "tag": _text(target.get("tag"), limit=32, default="unknown").lower(),
        "id": _text(target.get("id"), limit=120) or None,
        "role": _text(target.get("role"), limit=80) or None,
        "dataAction": _text(target.get("dataAction"), limit=120) or None,
        "targetType": _text(target.get("targetType"), limit=80, default="other"),
        "targetKey": _text(target.get("targetKey"), limit=160, default="other"),
        "interactionKind": interaction_kind,
        "interactive": bool(target.get("interactive")),
    }


def validate_click_details(value: Any) -> Dict[str, Any]:
    """Return a bounded canonical click payload or raise ``ValueError``."""
    if not isinstance(value, Mapping):
        raise ValueError("click_details_must_be_object")
    click_id = _text(value.get("clickId"), limit=160)
    if not _SAFE_ID.fullmatch(click_id):
        raise ValueError("click_id_invalid")
    pointer_type = _text(value.get("pointerType"), limit=16).lower()
    if pointer_type not in _POINTER_TYPES:
        raise ValueError("pointer_type_invalid")
    page_type = _text(value.get("pageType"), limit=32)
    if page_type not in _PAGE_TYPES:
        raise ValueError("page_type_invalid")
    capture_event = _text(value.get("captureEvent"), limit=32)
    if capture_event != "pointerdown":
        raise ValueError("capture_event_invalid")
    if value.get("isPrimary") is not True:
        raise ValueError("primary_pointer_required")

    viewport = _validate_viewport(value)
    content = _validate_content(value)
    button = int(_bounded_number(value.get("button", 0), "button", minimum=-1, maximum=5))
    if pointer_type == "mouse" and button != 0:
        raise ValueError("mouse_button_not_primary")

    result: Dict[str, Any] = {
        "schemaVersion": CLICK_SCHEMA_VERSION,
        "clickId": click_id,
        "clientSequence": _positive_int(value.get("clientSequence"), "client_sequence"),
        "captureEvent": "pointerdown",
        "pointerType": pointer_type,
        "button": button,
        "isPrimary": True,
        "clientMonotonicMs": round(
            _bounded_number(
                value.get("clientMonotonicMs"),
                "client_monotonic_ms",
                minimum=0,
                maximum=10**15,
            ),
            3,
        ),
        "pageType": page_type,
        "frameId": _text(value.get("frameId"), limit=120) or None,
        "coordinateSpace": _text(
            value.get("coordinateSpace"), limit=80, default="top_viewport"
        ),
        "devicePixelRatio": round(
            _bounded_number(
                value.get("devicePixelRatio", 1),
                "device_pixel_ratio",
                minimum=0.1,
                maximum=20,
            ),
            3,
        ),
        "orientation": _text(value.get("orientation"), limit=32) or None,
        "courseType": _text(value.get("courseType"), limit=80) or None,
        "courseId": _optional_identifier(value.get("courseId"), "course_id"),
        "courseItemId": _optional_identifier(
            value.get("courseItemId"), "course_item_id"
        ),
        "questionId": _optional_identifier(value.get("questionId"), "question_id"),
        "target": _validated_target(value.get("target")),
        **viewport,
        **content,
    }
    return result


def validate_tracking_started_details(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("tracking_details_must_be_object")
    return {
        "schemaVersion": TRACKING_SCHEMA_VERSION,
        "clientMonotonicMs": round(
            _bounded_number(
                value.get("clientMonotonicMs"),
                "client_monotonic_ms",
                minimum=0,
                maximum=10**15,
            ),
            3,
        ),
        "viewportWidth": round(
            _bounded_number(
                value.get("viewportWidth"),
                "viewport_width",
                minimum=1,
                maximum=100_000,
            ),
            3,
        ),
        "viewportHeight": round(
            _bounded_number(
                value.get("viewportHeight"),
                "viewport_height",
                minimum=1,
                maximum=100_000,
            ),
            3,
        ),
        "devicePixelRatio": round(
            _bounded_number(
                value.get("devicePixelRatio", 1),
                "device_pixel_ratio",
                minimum=0.1,
                maximum=20,
            ),
            3,
        ),
    }


def add_session_offset(
    details: Dict[str, Any],
    *,
    training_session_id: Any = None,
    runtime_session_id: Any = None,
) -> Dict[str, Any]:
    """Add the authoritative recording-relative receipt time when available."""
    result = dict(details)
    try:
        from app.services.recording_timeline import (
            get_recording_session,
            get_recording_session_by_training,
        )

        recording = (
            get_recording_session(str(runtime_session_id))
            if runtime_session_id
            else None
        )
        if recording is None and training_session_id:
            recording = get_recording_session_by_training(str(training_session_id))
        if recording is not None:
            result["sessionOffsetMs"] = round(recording.elapsed_sec * 1000.0, 3)
    except Exception:
        pass
    return result


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def summarize_screen_interaction(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Derive a stable session summary from immutable full-timeline rows."""
    materialized = [row for row in rows if isinstance(row, Mapping)]
    tracking_rows = [
        row for row in materialized
        if row.get("event") == TRACKING_STARTED_EVENT
    ]
    click_rows = [
        row for row in materialized
        if row.get("event") in {CLICK_EVENT, f"child_socket_emit.{CLICK_EVENT}"}
    ]
    available = bool(tracking_rows or click_rows)

    baseline_priorities = {
        "question_audio_ended": 0,
        "question_presented": 1,
        "content_presented": 2,
    }
    baselines: Dict[str, tuple[int, float]] = {}
    for row in materialized:
        event = str(row.get("event") or "")
        priority = baseline_priorities.get(event)
        qid = _text(row.get("questionId"), limit=160)
        epoch = _number(row.get("serverEpochMs"))
        if priority is None or not qid or epoch is None:
            continue
        current = baselines.get(qid)
        candidate = (priority, epoch)
        if current is None or candidate < current:
            baselines[qid] = candidate

    seen_click_ids: set[str] = set()
    duplicate_count = 0
    accepted: list[Mapping[str, Any]] = []
    for row in click_rows:
        details = row.get("details") if isinstance(row.get("details"), Mapping) else {}
        click_id = _text(details.get("clickId"), limit=160)
        dedupe_key = click_id or _text(row.get("eventId"), limit=160)
        if dedupe_key and dedupe_key in seen_click_ids:
            duplicate_count += 1
            continue
        if dedupe_key:
            seen_click_ids.add(dedupe_key)
        accepted.append(row)

    pointer_counts: Counter[str] = Counter()
    page_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    question_rows: Dict[str, list[Mapping[str, Any]]] = {}
    first_offset: Optional[float] = None
    for row in accepted:
        details = row.get("details") if isinstance(row.get("details"), Mapping) else {}
        target = details.get("target") if isinstance(details.get("target"), Mapping) else {}
        pointer_counts[_text(details.get("pointerType"), limit=16, default="unknown")] += 1
        page_counts[_text(details.get("pageType"), limit=32, default="unknown")] += 1
        kind = _text(target.get("interactionKind"), limit=32, default="other")
        kind_counts[kind if kind in _INTERACTION_KINDS else "other"] += 1
        qid = _text(row.get("questionId") or details.get("questionId"), limit=160)
        if qid:
            question_rows.setdefault(qid, []).append(row)
        offset = _number(details.get("sessionOffsetMs"))
        if offset is not None and (first_offset is None or offset < first_offset):
            first_offset = offset

    by_question: Dict[str, Dict[str, Any]] = {}
    for qid, qrows in question_rows.items():
        q_kind_counts: Counter[str] = Counter()
        epochs: list[float] = []
        offsets: list[float] = []
        for row in qrows:
            details = row.get("details") if isinstance(row.get("details"), Mapping) else {}
            target = details.get("target") if isinstance(details.get("target"), Mapping) else {}
            kind = _text(target.get("interactionKind"), limit=32, default="other")
            q_kind_counts[kind if kind in _INTERACTION_KINDS else "other"] += 1
            epoch = _number(row.get("serverEpochMs"))
            if epoch is not None:
                epochs.append(epoch)
            offset = _number(details.get("sessionOffsetMs"))
            if offset is not None:
                offsets.append(offset)
        first_latency = None
        baseline = baselines.get(qid)
        if baseline is not None and epochs:
            first_latency = round(max(0.0, min(epochs) - baseline[1]), 3)
        by_question[qid] = {
            "total_click_count": len(qrows),
            "task_click_count": q_kind_counts["task"],
            "blank_click_count": q_kind_counts["blank"],
            "other_click_count": len(qrows)
            - q_kind_counts["task"]
            - q_kind_counts["blank"],
            "first_click_latency_ms": first_latency,
            "first_session_offset_ms": round(min(offsets), 3) if offsets else None,
        }

    first_tracking = min(
        (_number(row.get("serverEpochMs")) for row in tracking_rows),
        default=None,
        key=lambda value: float("inf") if value is None else value,
    )
    return {
        "schema_version": "screen-interaction-summary-v1",
        "tracking_status": "READY" if available else "NOT_COLLECTED",
        "available": available,
        "total_click_count": len(accepted) if available else None,
        "task_click_count": kind_counts["task"] if available else None,
        "blank_click_count": kind_counts["blank"] if available else None,
        "other_click_count": (
            len(accepted) - kind_counts["task"] - kind_counts["blank"]
            if available else None
        ),
        "clicks_by_pointer_type": dict(sorted(pointer_counts.items())),
        "clicks_by_page": dict(sorted(page_counts.items())),
        "clicks_by_question": by_question,
        "first_session_offset_ms": round(first_offset, 3) if first_offset is not None else None,
        "tracking_started_server_epoch_ms": first_tracking,
        "duplicate_clicks_ignored": duplicate_count,
    }


def load_screen_interaction_summary(
    training_session_id: str,
    runtime_session_id: Any = None,
) -> Dict[str, Any]:
    from app.behavior.audit_timeline import get_full_interaction_timeline

    try:
        rows = get_full_interaction_timeline().read(
            training_session_id, runtime_session_id
        )
    except (OSError, ValueError):
        rows = []
    return summarize_screen_interaction(rows)


def summary_for_question(
    session_summary: Mapping[str, Any], question_id: str
) -> Dict[str, Any]:
    available = bool(session_summary.get("available"))
    by_question = session_summary.get("clicks_by_question")
    if isinstance(by_question, Mapping) and question_id in by_question:
        value = by_question[question_id]
        if isinstance(value, Mapping):
            return dict(value)
    return {
        "total_click_count": 0 if available else None,
        "task_click_count": 0 if available else None,
        "blank_click_count": 0 if available else None,
        "other_click_count": 0 if available else None,
        "first_click_latency_ms": None,
        "first_session_offset_ms": None,
    }


__all__ = [
    "CLICK_EVENT",
    "CLICK_SCHEMA_VERSION",
    "TRACKING_STARTED_EVENT",
    "TRACKING_SCHEMA_VERSION",
    "add_session_offset",
    "load_screen_interaction_summary",
    "summary_for_question",
    "summarize_screen_interaction",
    "validate_click_details",
    "validate_tracking_started_details",
]
