"""逻辑素材身份与物理文件位置的原子索引。"""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from app.storage.session_layout import atomic_write_json


class JsonAssetIndex:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schemaVersion": 1, "assets": []}
        import json

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schemaVersion", 1) != 1 or not isinstance(raw.get("assets"), list):
            raise ValueError("invalid_asset_index")
        return raw

    @staticmethod
    def _key(item: Mapping[str, Any]) -> tuple[str, str, str]:
        return (str(item.get("kind") or ""), str(item.get("assetId") or ""), str(item.get("version") or ""))

    def upsert(self, records: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any], ...]:
        with self._lock:
            document = self._load()
            assets = [copy.deepcopy(item) for item in document["assets"] if isinstance(item, dict)]
            positions = {self._key(item): index for index, item in enumerate(assets)}
            for raw in records:
                item = copy.deepcopy(dict(raw))
                key = self._key(item)
                if not all(key):
                    raise ValueError("asset_index_identity_required")
                if key in positions:
                    assets[positions[key]] = item
                else:
                    positions[key] = len(assets)
                    assets.append(item)
            atomic_write_json(self.path, {"schemaVersion": 1, "assets": assets})
            return tuple(copy.deepcopy(assets))

    def get(self, asset_id: str, *, kind: Optional[str] = None, version: Optional[str] = None) -> Optional[Mapping[str, Any]]:
        with self._lock:
            for item in self._load()["assets"]:
                if str(item.get("assetId")) != str(asset_id):
                    continue
                if kind is not None and str(item.get("kind")) != str(kind):
                    continue
                if version is not None and str(item.get("version")) != str(version):
                    continue
                return copy.deepcopy(item)
        return None

    def list(self, *, kind: Optional[str] = None) -> tuple[Mapping[str, Any], ...]:
        with self._lock:
            values = self._load()["assets"]
            return tuple(copy.deepcopy(item) for item in values if kind is None or str(item.get("kind")) == str(kind))

    def replace(self, records: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any], ...]:
        """Atomically restore a previous index snapshot after a commit failure."""
        with self._lock:
            values = [copy.deepcopy(dict(item)) for item in records]
            if any(not all(self._key(item)) for item in values):
                raise ValueError("asset_index_identity_required")
            atomic_write_json(self.path, {"schemaVersion": 1, "assets": values})
            return tuple(copy.deepcopy(values))


__all__ = ["JsonAssetIndex"]
