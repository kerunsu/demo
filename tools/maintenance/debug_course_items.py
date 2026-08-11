"""调试脚本：检查所有课程及其项目"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app
from database.models import Course, CourseItem

app, socketio = create_app()

with app.app_context():
    print("=" * 60)
    print("所有课程列表")
    print("=" * 60)
    courses = Course.query.all()
    for course in courses:
        items = CourseItem.query.filter_by(course_id=course.id).all()
        course_type = course.course_type.name if course.course_type else "未知"
        print(f"\n课程 ID={course.id}: {course.title} ({course_type})")
        print(f"  共 {len(items)} 个项目")
        for item in items[:5]:  # 只显示前5个
            print(f"    - Item ID={item.id}: {item.name}")
            print(f"      media_file: {item.media_file}")
        if len(items) > 5:
            print(f"    ... 还有 {len(items) - 5} 个项目")
    
    print("\n" + "=" * 60)
    print("课程项目ID对照表（用于调试）")
    print("=" * 60)
    
    # 查找所有命名课程的项目
    all_items = CourseItem.query.order_by(CourseItem.id).all()
    print(f"\n所有项目总数: {len(all_items)}")
    for item in all_items:
        is_folder = item.media_file.endswith('/') if item.media_file else False
        folder_mark = "[文件夹]" if is_folder else "[文件]"
        course_title = item.course.title if item.course else "无课程"
        print(f"  ID={item.id}: {item.name} {folder_mark} (课程: {course_title})")
