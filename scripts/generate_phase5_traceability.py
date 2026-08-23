"""Generate the Stage 5 machine-readable traceability matrix.

The source route/event list is intentionally read from the frozen contract
snapshot.  This keeps the matrix reviewable and prevents a hand-maintained
list from silently drifting from the contract test.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tests" / "fixtures" / "contracts" / "contracts.snapshot.json"
OUTPUT = ROOT / "tests" / "fixtures" / "contracts" / "traceability.matrix.json"


def _owner(path: str) -> str:
    if path.startswith("/api/v2/capture") or path.startswith("/api/media"):
        return "facade + acquisition"
    if path.startswith("/api/v2/assets"):
        return "facade + storage"
    if path.startswith("/api/v2/interaction"):
        return "facade + computation"
    if path.startswith("/api/report"):
        return "facade + computation/storage"
    if path.startswith("/api/config") or path.startswith("/api/robot"):
        return "facade + storage/computation/acquisition"
    return "facade"


def _http_rows(snapshot: dict) -> list[dict]:
    rows = []
    for route in snapshot["routes"]:
        method, path = route.split(" ", 1)
        rows.append({
            "method": method,
            "path": path,
            "owner": _owner(path),
            "sourceSnapshot": True,
            "runtimeCrossChecked": path != "/static/<path:filename>",
            "behaviorFixture": "partial; see tests/test_phase1_contract_surface.py",
        })
    for route in snapshot.get("runtimeImplicitRoutes", []):
        method, path = route.split(" ", 1)
        rows.append({
            "method": method,
            "path": path,
            "owner": "frontend Web/static serving",
            "sourceSnapshot": False,
            "runtimeCrossChecked": True,
            "behaviorFixture": "runtime URL map",
        })
    return rows


def main() -> None:
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    pages = [
        "/", "/therapist", "/child", "/server", "/server/report-review/<training_session_id>",
        "/server/config", "/server/config/overview", "/server/config/camera",
        "/server/config/speech", "/server/config/report", "/server/config/content",
        "/robot", "/robot/emotion", "/robot/download", "/courses", "/matching", "/sequencing",
    ]
    runtime = [
        {"transport": "HTTP", "endpoint": "POST /api/media/<sessionId>/frames", "owner": "acquisition", "verification": "automated fixture + fake Runtime"},
        {"transport": "HTTP", "endpoint": "POST /api/media/<sessionId>/audio-chunks", "owner": "acquisition", "verification": "automated fixture + fake Runtime"},
        {"transport": "HTTP", "endpoint": "POST /api/media/<sessionId>/upload", "owner": "acquisition + storage", "verification": "checksum/archive fixture"},
        {"transport": "HTTP", "endpoint": "POST /api/robot/runtime/register", "owner": "acquisition/facade", "verification": "source + fake protocol; real Runtime pending"},
        {"transport": "HTTP", "endpoint": "POST /api/robot/runtime/heartbeat", "owner": "acquisition/facade", "verification": "source + fake protocol; real Runtime pending"},
        {"transport": "HTTP", "endpoint": "POST /api/robot/runtime/behavior/event", "owner": "acquisition/facade", "verification": "exact three-ID callback contract; real Runtime pending"},
        {"transport": "HTTP", "endpoint": "POST /behavior/prepare", "owner": "Robot Runtime", "verification": "packaged Runtime protocol test; real motion pending"},
        {"transport": "HTTP", "endpoint": "POST /behavior/commit", "owner": "Robot Runtime", "verification": "packaged Runtime protocol test; real motion pending"},
        {"transport": "HTTP", "endpoint": "POST /osc/frame", "owner": "acquisition", "verification": "Robot Runtime protocol; real hardware pending"},
        {"transport": "HTTP", "endpoint": "POST /osc/play", "owner": "acquisition", "verification": "Robot Runtime protocol; real hardware pending"},
        {"transport": "HTTP", "endpoint": "POST /osc/stop", "owner": "acquisition", "verification": "Robot Runtime protocol; real hardware pending"},
    ]
    session_files = [
        {"filename": name, "owner": "storage", "compatibility": "legacy name frozen", "verification": "session validator + fixture"}
        for name in snapshot["stableFileNames"]
    ]
    scenarios = [
        {"id": "golden-flow", "owner": "facade + acquisition + computation + storage + dialogue", "verification": "automated characterization; browser/Runtime manual still required"},
        {"id": "required-device-fail-closed", "owner": "acquisition + facade", "verification": "fake-device strict tests; real 0/1/N hardware pending"},
        {"id": "room-isolation-and-busy", "owner": "facade + computation", "verification": "automated Socket tests"},
        {"id": "runtime-reconnect-and-late-upload", "owner": "acquisition + storage", "verification": "fake Runtime tests; physical network pending"},
        {"id": "v2-profile-fallback-and-freeze", "owner": "computation + facade", "verification": "automated resolver/Socket tests"},
        {"id": "model-asr-tts-degradation", "owner": "computation + dialogue", "verification": "fake provider tests; production health pending"},
    ]
    matrix = {
        "schemaVersion": 1,
        "generatedAt": date.today().isoformat(),
        "sourceSnapshot": str(SNAPSHOT.relative_to(ROOT)).replace("\\", "/"),
        "interfaces": {
            "http": _http_rows(snapshot),
            "socket": [
                {"event": event, "owner": "facade adapter + legacy handler", "sourceSnapshot": True,
                 "runtimeRegistered": True, "behaviorFixture": "partial; see contract tests"}
                for event in snapshot["socketDecoratedEvents"]
            ],
            "pages": [
                {"path": page, "owner": "frontend Web", "verification": "manual browser required"}
                for page in pages
            ],
            "runtime": runtime,
        },
        "sessionFiles": session_files,
        "configuration": [
            {"key": "CHILD_MEDIA_MODE", "owner": "facade + acquisition", "verification": "automated config/runtime tests"},
            {"key": "ROBOT_CONTROL_MODE", "owner": "facade + acquisition", "verification": "fake protocol; real Robot pending"},
            {"key": "CAPTURE_DEVICE_REGISTRY_PATH", "owner": "acquisition + storage", "verification": "automated registry tests"},
            {"key": "DIALOGUE_ENABLED / AI_CHAT_PROVIDER / DIALOGUE_TTS_MODE", "owner": "dialogue", "verification": "fake provider tests; real voice service pending"},
        ],
        "interaction": {
            "events": 16,
            "contexts": ["courseId", "courseType", "sceneKey", "eventKey", "lineId", "profileVersion", "sessionId"],
            "assetBinding": ["motion", "emotion", "fixed audio", "TTS", "timing"],
            "owner": "computation + dialogue + storage",
            "verification": "V2 resolver, validation, speech dispatch and legacy fallback automated; authoring UI/manual preview pending",
        },
        "faultScenarios": scenarios,
        "notes": [
            "Rows marked pending are not acceptance passes.",
            "No row grants permission to rename legacy files or change an existing external payload.",
            "Runtime source coverage is not equivalent to a physical camera, microphone, DollSer or browser acceptance test.",
        ],
    }
    OUTPUT.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
