"""Deployment stages and side-effect-free comparison for interaction profiles."""

from __future__ import annotations

from typing import Any, Mapping, Optional


DEPLOYMENT_STAGES = (
    "legacy_only",
    "shadow",
    "draft_preview",
    "published_canary",
    "published",
)


def normalize_stage(value: Optional[str]) -> str:
    stage = str(value or "published").strip().lower()
    if stage not in DEPLOYMENT_STAGES:
        raise ValueError("interaction_deployment_stage_invalid")
    return stage


def compare_plans(legacy: Any, candidate: Any) -> dict[str, Any]:
    """Return a stable, JSON-safe shadow diff without executing either plan."""

    def assets(value: Any) -> list[str]:
        result = []
        for item in value or ():
            if isinstance(item, Mapping):
                result.append(str(item.get("assetId") or item.get("id") or ""))
            else:
                result.append(str(item))
        return [item for item in result if item]

    def sequence(plan: Any) -> Mapping[str, Any]:
        metadata = getattr(plan, "metadata", {})
        value = metadata.get("sequence") if isinstance(metadata, Mapping) else {}
        return value if isinstance(value, Mapping) else {}

    legacy_sequence = sequence(legacy)
    candidate_sequence = sequence(candidate)
    fields = {
        "motion": {
            "legacy": assets(getattr(legacy, "motions", ())),
            "candidate": assets(getattr(candidate, "motions", ())),
        },
        "emotion": {
            "legacy": assets(getattr(legacy, "expressions", ())),
            "candidate": assets(getattr(candidate, "expressions", ())),
        },
        "offset": {
            "legacy": legacy_sequence.get("motionOffsetMs", 0),
            "candidate": candidate_sequence.get("motionOffsetMs", 0),
        },
        "duration": {
            "legacy": legacy_sequence.get("durationMs"),
            "candidate": candidate_sequence.get("durationMs"),
        },
        "audioOffset": {
            "legacy": (legacy_sequence.get("audio") or {}).get("offsetMs", 0)
            if isinstance(legacy_sequence.get("audio"), Mapping) else 0,
            "candidate": (candidate_sequence.get("audio") or {}).get("offsetMs", 0)
            if isinstance(candidate_sequence.get("audio"), Mapping) else 0,
        },
        "fallbackPath": {
            "legacy": list(getattr(legacy, "resolution_trace", ()) or ()),
            "candidate": list(getattr(candidate, "resolution_trace", ()) or ()),
        },
    }
    differences = [key for key, value in fields.items() if value["legacy"] != value["candidate"]]
    return {
        "schemaVersion": 1,
        "equal": not differences,
        "differences": differences,
        "fields": fields,
        "legacySource": getattr(legacy, "source", "legacy"),
        "candidateSource": getattr(candidate, "source", "legacy"),
    }


__all__ = ["DEPLOYMENT_STAGES", "compare_plans", "normalize_stage"]
