"""Small read-only file content catalog used by later facade adapters."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional, Sequence

from app.contracts.models import AssetRef


class FileContentCatalog:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _path(self, asset: AssetRef) -> Path:
        if not asset.filename:
            raise ValueError("asset filename is required")
        path = (self.root / asset.filename).resolve()
        if self.root != path and self.root not in path.parents:
            raise ValueError("asset is outside the content catalog")
        return path

    def get(self, asset: AssetRef) -> Optional[dict]:
        path = self._path(asset)
        if not path.is_file():
            return None
        return {"asset": asset, "path": str(path), "size": path.stat().st_size}

    def list(self, kind: Optional[str] = None) -> Sequence[AssetRef]:
        if not self.root.is_dir():
            return ()
        values = []
        for path in sorted(item for item in self.root.rglob("*") if item.is_file()):
            if kind and path.suffix.lstrip(".") != kind and kind not in path.name:
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            values.append(AssetRef(asset_id=path.stem, version="1", kind=kind or path.suffix.lstrip("."), filename=str(path.relative_to(self.root)), checksum=digest))
        return tuple(values)


__all__ = ["FileContentCatalog"]
