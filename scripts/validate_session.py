"""Read-only session dataset validator.

Usage: python scripts/validate_session.py path/to/session
The command never repairs, deletes or creates files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.storage.session_validator import validate_session_directory


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a session directory without changing it")
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    report = validate_session_directory(args.directory)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
