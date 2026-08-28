"""
重建「标准库」课程数据（非交互）。

顺序：
1. init_db（表 / 课型 / 能力 / 默认 admin）
2. migrate_courses ← static/courses.json（仅命名/排序）
3. import_course_resources（充实命名课点）
4. import_sequencing（排序交互入口与媒体路径对齐）

用法:
    python database/seed_standard.py
    python database/seed_standard.py --force   # 兼容参数；仍为幂等原地补齐
"""
from __future__ import annotations

import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def seed_standard(force: bool = True) -> bool:
    from database.init_db import init_database
    from database.migrate_courses import migrate_courses
    from database.import_course_resources import main as import_course_resources_main
    from database.import_sequencing_course import import_sequencing_course

    print("=" * 60)
    print("标准库播种：init_db + import")
    print("=" * 60)

    print("\n[1/4] init_db")
    init_database()

    print("\n[2/4] migrate_courses (Demo courses.json)")
    ok = migrate_courses(force=force)
    if ok is False:
        print("migrate_courses 失败或取消")
        return False

    print("\n[3/4] import_course_resources (Demo 命名)")
    previous_argv = list(sys.argv)
    try:
        sys.argv = [previous_argv[0], '--yes']
        if import_course_resources_main() is False:
            print("import_course_resources 失败")
            return False
    finally:
        sys.argv = previous_argv

    print("\n[4/4] import sequencing")
    if not import_sequencing_course(force=True):
        print("import_sequencing_course 失败")
        return False

    print("\n" + "=" * 60)
    print("标准库播种完成")
    print("默认账号: admin / admin123")
    print("=" * 60)
    return True


if __name__ == '__main__':
    # 标准种子始终原地补齐；force 不再删除课程或稳定课点 ID。
    ok = seed_standard(force=True)
    sys.exit(0 if ok else 1)
