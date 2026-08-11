"""
Child Media Agent 兼容入口。

请改用统一 Robot Runtime：
  python -m robot_runtime.agent
  或 robot_runtime/start.bat

本文件仅转发到 robot_runtime.agent，避免旧脚本失效。
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

print("[DEPRECATED] child_media_agent → robot_runtime.agent (port 19091)")
runpy.run_module("robot_runtime.agent", run_name="__main__")
