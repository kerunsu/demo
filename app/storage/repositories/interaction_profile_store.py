"""InteractionProfileV2 的原子 JSON 仓储。

旧 ``course_map.json`` 永远只读；本仓储使用独立文件保存 draft/published 版本，
因此发布、回滚和删除不会原地改写旧映射。
"""

from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from app.storage.session_layout import atomic_write_json

_DEPLOYMENT_STAGES = {
    "legacy_only", "shadow", "draft_preview", "published_canary", "published"
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JsonInteractionProfileStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schemaVersion": 1, "profiles": []}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schemaVersion", 1) != 1 or not isinstance(raw.get("profiles"), list):
            raise ValueError("invalid_interaction_profile_store")
        if any(not isinstance(item, dict) for item in raw["profiles"]):
            raise ValueError("invalid_interaction_profile_item")
        return raw

    @staticmethod
    def _identity(profile: Mapping[str, Any]) -> tuple[str, str]:
        course_id = str(profile.get("courseId") or profile.get("course_id") or "").strip()
        version = str(profile.get("version") or "").strip()
        if not course_id or not version:
            raise ValueError("profile_course_id_and_version_required")
        return course_id, version

    @staticmethod
    def _validate(profile: Mapping[str, Any]) -> dict[str, Any]:
        course_id, version = JsonInteractionProfileStore._identity(profile)
        events = profile.get("events") or {}
        if not isinstance(events, dict):
            raise ValueError("profile_events_must_be_object")
        course_type = str(profile.get("courseType") or profile.get("course_type") or "").strip() or None
        status = str(profile.get("status") or "draft").strip().lower()
        if status not in {"draft", "published", "archived"}:
            raise ValueError("profile_status_invalid")
        result = copy.deepcopy(dict(profile))
        result.update({
            "schemaVersion": int(profile.get("schemaVersion", 1)),
            "courseId": course_id,
            "courseType": course_type,
            "version": version,
            "status": status,
            "events": copy.deepcopy(events),
        })
        return result

    def list(self, course_id: Optional[str] = None) -> Sequence[Mapping[str, Any]]:
        with self._lock:
            profiles = self._load().get("profiles", [])
            selected = [p for p in profiles if course_id is None or str(p.get("courseId")) == str(course_id)]
            return tuple(copy.deepcopy(selected))

    def get(self, course_id: str, version: Optional[str] = None) -> Optional[Mapping[str, Any]]:
        candidates = list(self.list(course_id))
        if version is not None:
            for profile in candidates:
                if str(profile.get("version")) == str(version):
                    return profile
            return None
        published = [p for p in candidates if p.get("status") == "published"]
        if not published:
            return None
        published.sort(key=lambda p: str(p.get("publishedAt") or p.get("version") or ""), reverse=True)
        return published[0]

    def save_draft(self, profile: Mapping[str, Any]) -> Mapping[str, Any]:
        candidate = self._validate({**dict(profile), "status": "draft"})
        with self._lock:
            document = self._load()
            profiles = document["profiles"]
            identity = self._identity(candidate)
            profiles[:] = [item for item in profiles if self._identity(item) != identity]
            profiles.append(candidate)
            atomic_write_json(self.path, {"schemaVersion": 1, "profiles": profiles})
        return copy.deepcopy(candidate)

    def publish(self, course_id: str, version: str) -> Mapping[str, Any]:
        with self._lock:
            document = self._load()
            target = None
            for item in document["profiles"]:
                if str(item.get("courseId")) == str(course_id) and str(item.get("version")) == str(version):
                    target = item
            if target is None:
                raise KeyError("interaction_profile_not_found")
            for item in document["profiles"]:
                if str(item.get("courseId")) == str(course_id) and item.get("status") == "published":
                    item["status"] = "archived"
            target["status"] = "published"
            target["publishedAt"] = _now()
            deployment = dict(target.get("deployment") or {})
            deployment["stage"] = "published"
            deployment.setdefault("canaryPercent", 0)
            target["deployment"] = deployment
            atomic_write_json(self.path, {"schemaVersion": 1, "profiles": document["profiles"]})
            return copy.deepcopy(target)

    def deploy(
        self,
        course_id: str,
        version: str,
        stage: str,
        canary_percent: float = 0,
    ) -> Mapping[str, Any]:
        stage = str(stage or "").strip().lower()
        if stage not in _DEPLOYMENT_STAGES:
            raise ValueError("interaction_deployment_stage_invalid")
        try:
            percent = max(0.0, min(100.0, float(canary_percent)))
        except (TypeError, ValueError) as exc:
            raise ValueError("interaction_canary_percent_invalid") from exc
        with self._lock:
            document = self._load()
            target = next(
                (
                    item for item in document["profiles"]
                    if str(item.get("courseId")) == str(course_id)
                    and str(item.get("version")) == str(version)
                ),
                None,
            )
            if target is None:
                raise KeyError("interaction_profile_not_found")
            if stage in {"published", "published_canary", "shadow", "legacy_only"} and target.get("status") not in {"published", "archived"}:
                raise ValueError("interaction_profile_must_be_published")
            target["deployment"] = {
                **dict(target.get("deployment") or {}),
                "stage": stage,
                "canaryPercent": percent,
                "updatedAt": _now(),
            }
            atomic_write_json(self.path, {"schemaVersion": 1, "profiles": document["profiles"]})
            return copy.deepcopy(target)

    def rollback(self, course_id: str, version: str) -> Mapping[str, Any]:
        # Rollback is a new atomic publication of an existing immutable version.
        return self.publish(course_id, version)


__all__ = ["JsonInteractionProfileStore"]
