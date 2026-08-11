"""
重建「标准库」课程数据（非交互）。

顺序：
1. init_db（表 / 课型 / 能力 / 默认 admin）
2. migrate_courses ← static/courses.json（模仿/命名/拟声/配对/排序骨架）
3. import_course_resources ← CSV（充实命名/拟声课点）
4. import_matching / import_sequencing（交互课入口与媒体路径对齐）
5. import_social（社交课）

用法:
    python database/seed_standard.py
    python database/seed_standard.py --force   # 覆盖已有课程
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
    from database.import_matching_course import import_matching_course
    from database.import_sequencing_course import import_sequencing_course
    from database.import_social_course import import_social_course

    print("=" * 60)
    print("标准库播种：init_db + import")
    print("=" * 60)

    print("\n[1/5] init_db")
    init_database()

    print("\n[2/5] migrate_courses (courses.json)")
    ok = migrate_courses(force=force)
    if ok is False:
        print("migrate_courses 失败或取消")
        return False

    print("\n[3/5] import_course_resources (CSV 命名/拟声)")
    # import_course_resources.main 读 sys.argv；临时注入 --yes
    prev = list(sys.argv)
    try:
        sys.argv = [prev[0], '--yes']
        if import_course_resources_main() is False:
            print("import_course_resources 失败（将继续后续导入）")
    finally:
        sys.argv = prev

    print("\n[4/5] import matching + sequencing")
    if not import_matching_course(force=True):
        print("import_matching_course 失败")
        return False
    if not import_sequencing_course(force=True):
        print("import_sequencing_course 失败")
        return False

    print("\n[5/5] import social")
    if not import_social_course(force=True):
        print("import_social_course 失败")
        return False

    print("\n" + "=" * 60)
    print("标准库播种完成")
    print("默认账号: admin / admin123")
    print("=" * 60)
    return True


if __name__ == '__main__':
    # 本脚本用途即重建标准库，默认覆盖课程数据
    ok = seed_standard(force=True)
    sys.exit(0 if ok else 1)
