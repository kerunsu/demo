"""Current documentation and machine-matrix integrity checks."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/contracts"


def test_phase5_traceability_matrix_covers_frozen_surface():
    snapshot = json.loads((FIXTURES / "contracts.snapshot.json").read_text(encoding="utf-8"))
    matrix = json.loads((FIXTURES / "traceability.matrix.json").read_text(encoding="utf-8"))
    assert len(matrix["interfaces"]["http"]) == snapshot["routeCount"] + len(snapshot["runtimeImplicitRoutes"])
    assert len(matrix["interfaces"]["socket"]) == snapshot["socketDecoratorCount"]
    assert {item["filename"] for item in matrix["sessionFiles"]} == set(snapshot["stableFileNames"])
    assert {item["path"] for item in matrix["interfaces"]["pages"]} >= {"/child", "/server", "/robot"}
    assert matrix["interaction"]["events"] == 16


def test_current_canonical_docs_exist_without_historical_tree():
    required = (
        "README.md",
        "docs/ARCHITECTURE.md",
        "docs/CONTRACT.md",
        "docs/DATA_SCHEMA.md",
        "docs/CONFIGURATION.md",
        "docs/OPERATIONS.md",
        "docs/EXTENDING.md",
        "docs/TESTING.md",
        "docs/INTERACTION_LATENCY.md",
        "tests/fixtures/contracts/contracts.snapshot.json",
        "tests/fixtures/contracts/traceability.matrix.json",
    )
    assert all((ROOT / path).is_file() for path in required)
    assert not (ROOT / "docs/archive").exists()
    assert not (ROOT / "docs/refactor").exists()


def test_phase5_canonical_document_links_resolve():
    canonical = [
        ROOT / "README.md",
        ROOT / "docs/ARCHITECTURE.md",
        ROOT / "docs/CONTRACT.md",
        ROOT / "docs/DATA_SCHEMA.md",
        ROOT / "docs/CONFIGURATION.md",
        ROOT / "docs/OPERATIONS.md",
        ROOT / "docs/EXTENDING.md",
        ROOT / "docs/TESTING.md",
        ROOT / "docs/INTERACTION_LATENCY.md",
    ]
    missing = []
    for path in canonical:
        content = path.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]+\]\(([^)#]+)", content):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if not (path.parent / target).resolve().exists():
                missing.append(f"{path}: {target}")
    assert missing == []
