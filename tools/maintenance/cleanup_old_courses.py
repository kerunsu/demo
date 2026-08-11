"""清理旧测试课程数据，保留新导入的课程"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app
from database.models import db, Course, CourseItem

app, socketio = create_app()

with app.app_context():
    # 旧测试课程ID列表（ID 1-5）
    old_course_ids = [1, 2, 3, 4, 5]
    
    print("将删除以下旧课程及其项目:")
    for cid in old_course_ids:
        course = Course.query.get(cid)
        if course:
            items = CourseItem.query.filter_by(course_id=cid).all()
            print(f"  - 课程 ID={cid}: {course.title} ({len(items)} 个项目)")
    
    confirm = input("\n确认删除? (输入 yes 确认): ")
    if confirm.lower() == 'yes':
        for cid in old_course_ids:
            # 先删除项目
            CourseItem.query.filter_by(course_id=cid).delete()
            # 再删除课程
            Course.query.filter_by(id=cid).delete()
        
        db.session.commit()
        print("\n旧课程已删除！")
        
        # 显示剩余课程
        print("\n剩余课程:")
        for course in Course.query.all():
            items = CourseItem.query.filter_by(course_id=course.id).all()
            print(f"  - ID={course.id}: {course.title} ({len(items)} 个项目)")
    else:
        print("取消操作")
