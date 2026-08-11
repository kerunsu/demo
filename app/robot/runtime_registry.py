"""In-memory registry for Robot Runtime instances (backend side)."""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from app.versioning import runtime_protocol_compatibility, version_matrix

_lock = threading.RLock()
# runtime_id -> record
_runtimes: Dict[str, Dict[str, Any]] = {}
_STALE_MS = 30_000
_preferred_runtime_id: Optional[str] = None
_preferred_runtime_source: Optional[str] = None


def _now_ms() -> int:
    return int(time.time() * 1000)


def register_runtime(
    advertised_url: str,
    *,
    port: Optional[int] = None,
    capabilities: Optional[list] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = (advertised_url or "").rstrip("/")
    if not url:
        raise ValueError("advertisedUrl required")
    rid = url
    with _lock:
        metadata = meta or {}
        instance_id = str(metadata.get("instanceId") or "").strip()
        if instance_id:
            # A physical installation may change IP/port or be started twice.
            # Keep one endpoint for that stable installation identity.
            for old_id, old in list(_runtimes.items()):
                if old_id != rid and str((old.get("meta") or {}).get("instanceId") or "") == instance_id:
                    _runtimes.pop(old_id, None)
        compatibility = runtime_protocol_compatibility(metadata.get("protocolVersion"))
        record = {
            "id": rid,
            "advertisedUrl": url,
            "port": port,
            "capabilities": capabilities or [],
            "meta": metadata,
            "buildVersion": metadata.get("buildVersion") or metadata.get("runtimeVersion"),
            **compatibility,
            "registeredAt": _runtimes.get(rid, {}).get("registeredAt", _now_ms()),
            "lastSeenMs": _now_ms(),
            "online": True,
        }
        _runtimes[rid] = record
        return dict(record)


def heartbeat_runtime(advertised_url: Optional[str] = None) -> bool:
    with _lock:
        if advertised_url:
            url = advertised_url.rstrip("/")
            rec = _runtimes.get(url)
            if not rec:
                return False
            rec["lastSeenMs"] = _now_ms()
            rec["online"] = True
            return True
        # A legacy heartbeat has no stable identity. It is safe only when
        # exactly one runtime is registered; refreshing every record keeps
        # stopped/test runtimes alive forever and creates false duplicates.
        if len(_runtimes) != 1:
            return False
        rec = next(iter(_runtimes.values()))
        rec["lastSeenMs"] = _now_ms()
        rec["online"] = True
        return True


def prefer_runtime(advertised_url: Optional[str], *, source: str = "child") -> bool:
    """Pin the Runtime reported by the one live child page.

    Runtime registration heartbeats are intentionally not allowed to steal this
    preference.  Otherwise two installed Runtime copies can alternate as the
    primary every few milliseconds and split prepare/commit/cancel across hosts.
    """
    global _preferred_runtime_id, _preferred_runtime_source
    url = str(advertised_url or "").rstrip("/")
    if not url:
        return False
    with _lock:
        if url not in _runtimes:
            return False
        _preferred_runtime_id = url
        _preferred_runtime_source = str(source or "child")
        return True


def get_primary_runtime() -> Optional[Dict[str, Any]]:
    """Return the best usable non-stale runtime, then use recency as tie-breaker."""
    now = _now_ms()
    with _lock:
        candidates = [
            dict(r)
            for r in _runtimes.values()
            if now - int(r.get("lastSeenMs", 0)) <= _STALE_MS
        ]
    if not candidates:
        return None
    preferred = next(
        (item for item in candidates if item.get("id") == _preferred_runtime_id),
        None,
    )
    if preferred is not None:
        return preferred
    def priority(record: Dict[str, Any]) -> tuple[int, int, int, int, int]:
        capabilities = set(record.get("capabilities") or [])
        return (
            int(record.get("compatible") is True),
            int("behavior-sync-v1" in capabilities),
            int("device-preflight-v1" in capabilities),
            int("multi-track-media-v1" in capabilities),
            int(record.get("lastSeenMs", 0)),
        )

    candidates.sort(key=priority, reverse=True)
    return candidates[0]


def get_runtime_status() -> Dict[str, Any]:
    now = _now_ms()
    with _lock:
        items = []
        for r in _runtimes.values():
            item = dict(r)
            age = now - int(r.get("lastSeenMs", 0))
            item["online"] = age <= _STALE_MS
            item["ageMs"] = age
            items.append(item)
    primary = get_primary_runtime()
    status = {
        "count": len(items),
        "onlineCount": sum(1 for i in items if i.get("online")),
        "primary": primary,
        "runtimes": items,
        "staleMs": _STALE_MS,
        "preferredRuntimeId": _preferred_runtime_id,
        "preferredRuntimeSource": _preferred_runtime_source,
    }
    status["versionMatrix"] = version_matrix(primary)
    return status


def unregister_runtime(advertised_url: str) -> bool:
    global _preferred_runtime_id, _preferred_runtime_source
    with _lock:
        url = advertised_url.rstrip("/")
        removed = _runtimes.pop(url, None) is not None
        if _preferred_runtime_id == url:
            _preferred_runtime_id = None
            _preferred_runtime_source = None
        return removed
