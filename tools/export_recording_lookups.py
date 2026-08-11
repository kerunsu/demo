"""导出录制目录对照表：course_type_lookup.csv / course_item_lookup.csv

用法（在项目根、已配置 Flask app context 时）::

    python -m tools.export_recording_lookups

或::

    from app import create_app
    from tools.export_recording_lookups import main
    app = create_app()
    with app.app_context():
        main()
"""
from __future__ import annotations

import sys
from pathlib import Path


def main(target: str | None = None) -> dict:
    # 保证可从任意 cwd 导入 app
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from app import create_app
    from app.services.recording_timeline import export_recording_lookups

    app = create_app()
    with app.app_context():
        out = Path(target) if target else None
        paths = export_recording_lookups(out)
        print("exported:")
        for k, v in paths.items():
            print(f"  {k}: {v}")
        return paths


if __name__ == "__main__":
    dest = sys.argv[1] if len(sys.argv) > 1 else None
    main(dest)
