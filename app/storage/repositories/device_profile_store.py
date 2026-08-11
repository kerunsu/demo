"""Atomic JSON persistence for capture device configuration."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from app.contracts.models import DeviceProfile
from app.storage.session_layout import atomic_write_json


class JsonDeviceProfileStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> Sequence[DeviceProfile]:
        if not self.path.exists():
            return ()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if (
            not isinstance(raw, dict)
            or raw.get("schemaVersion", 1) != 1
            or not isinstance(raw.get("devices"), list)
        ):
            raise ValueError("invalid_capture_device_registry")
        devices = []
        for index, item in enumerate(raw["devices"]):
            if not isinstance(item, dict):
                raise ValueError(f"invalid_capture_device_registry_item:{index}")
            try:
                enabled = item.get("enabled", True)
                required = item.get("required", False)
                if not isinstance(enabled, bool) or not isinstance(required, bool):
                    raise ValueError("device_boolean_fields_must_be_boolean")
                devices.append(DeviceProfile(
                    device_id=str(item["device_id"]),
                    track_id=str(item.get("track_id") or ""),
                    kind=str(item["kind"]),
                    role=str(item["role"]),
                    location=item.get("location"),
                    owner=str(item.get("owner") or "server"),
                    runtime_id=item.get("runtime_id"),
                    selector=dict(item.get("selector") or {}),
                    enabled=enabled,
                    required=required,
                    priority=int(item.get("priority", 0)),
                    format=dict(item.get("format") or {}),
                    capabilities=dict(item.get("capabilities") or {}),
                    schema_version=int(item.get("schema_version", 1)),
                ))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid_capture_device_registry_item:{index}") from exc
        return tuple(devices)

    def save(self, devices: Sequence[DeviceProfile]) -> None:
        atomic_write_json(self.path, {
            "schemaVersion": 1,
            "devices": [asdict(device) for device in devices],
        })


__all__ = ["JsonDeviceProfileStore"]
