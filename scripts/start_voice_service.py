"""Standalone launcher for tools/voice-service (FunASR on :8765)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.utils.voice_service_launcher import (  # noqa: E402
    _port_listening,
    _script_path,
    _service_host_port,
    build_voice_service_env,
    resolve_voice_python,
)


def main() -> int:
    host, port = _service_host_port()
    if _port_listening(host, port):
        print(f"Already listening on http://{host}:{port}/health — not starting another.")
        return 0

    script = _script_path()
    if not script.is_file():
        print(f"Missing script: {script}", file=sys.stderr)
        return 1

    python_exe = resolve_voice_python()
    env = build_voice_service_env()
    print(f"Starting voice-service with {python_exe}")
    print(f"  script={script}")
    print(f"  stt={env.get('VOICE_SERVICE_STT_PROVIDER')} url=http://{host}:{port}")
    print(f"  funasr={env.get('VOICE_SERVICE_FUNASR_MODEL')}")
    return subprocess.call([python_exe, str(script)], cwd=str(ROOT), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
