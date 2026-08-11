"""Stage 5 documentation and machine-matrix integrity checks."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_phase5_traceability_matrix_covers_frozen_surface():
    snapshot = json.loads((ROOT / "docs/refactor/contracts.snapshot.json").read_text(encoding="utf-8"))
    matrix = json.loads((ROOT / "docs/refactor/traceability.matrix.json").read_text(encoding="utf-8"))
    assert len(matrix["interfaces"]["http"]) == snapshot["routeCount"] + len(snapshot["runtimeImplicitRoutes"])
    assert len(matrix["interfaces"]["socket"]) == snapshot["socketDecoratorCount"]
    assert {item["filename"] for item in matrix["sessionFiles"]} == set(snapshot["stableFileNames"])
    assert {item["path"] for item in matrix["interfaces"]["pages"]} >= {"/child", "/server", "/robot"}
    assert matrix["interaction"]["events"] == 16


def test_phase5_canonical_docs_and_release_records_exist():
    required = (
        "README.md",
        "docs/ARCHITECTURE.md",
        "docs/CONTRACT.md",
        "docs/DATA_SCHEMA.md",
        "docs/CONFIGURATION.md",
        "docs/OPERATIONS.md",
        "docs/EXTENDING.md",
        "docs/TESTING.md",
        "docs/refactor/FINAL_ACCEPTANCE.md",
        "docs/refactor/FINAL_DEPENDENCY_MAP.md",
        "docs/refactor/CONTRACT_DIFF_REPORT.md",
        "docs/refactor/DEVICE_TRACK_ACCEPTANCE.md",
        "docs/refactor/INTERACTION_PROFILE_COMPATIBILITY.md",
        "docs/refactor/PERFORMANCE_COMPARISON.md",
        "docs/refactor/DEPRECATION_AND_CLEANUP.md",
        "docs/refactor/DEPLOYMENT_ROLLBACK.md",
    )
    assert all((ROOT / path).is_file() for path in required)
    final = (ROOT / "docs/refactor/FINAL_ACCEPTANCE.md").read_text(encoding="utf-8")
    assert "Conditional handoff" in final
    assert "250 passed" in final
    assert "must not be called" in final or "not a full production acceptance" in final


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
        ROOT / "docs/refactor/FINAL_ACCEPTANCE.md",
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
