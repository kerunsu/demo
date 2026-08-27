"""
导入排序课程到数据库
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models import db, Course, CourseItem, CourseType
from app.config import Config
from flask import Flask

def import_sequencing_course(force: bool = False):
    """幂等补齐排序大类和课点；force 不删除稳定 ID。"""
    
    # 创建临时 Flask 应用以使用数据库
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = Config.SQLALCHEMY_DATABASE_URI
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    
    with app.app_context():
        # 1. 获取排序课程类型ID
        sequencing_type = CourseType.query.filter_by(name='排序').first()
        if not sequencing_type:
            print("❌ 错误：找不到'排序'课程类型，请先运行 init_db.py 初始化数据库")
            return False
        
        print(f"✓ 找到排序课程类型: id={sequencing_type.id}, name={sequencing_type.name}")
        
        # 2. 检查是否已存在排序课程
        existing_course = Course.query.filter_by(course_type_id=sequencing_type.id).first()
        if existing_course:
            print(f"✓ 使用已有排序大类: id={existing_course.id}")
            existing_course.title = '排序'
            existing_course.entry_file = 'resources/interactive/sequencing.html'
        
        # 3. 创建排序课程
        course = existing_course or Course(
            course_type_id=sequencing_type.id,
            title='排序',
            icon=None,
            question_audio=None,
            praise_audio=None,
            entry_file='resources/interactive/sequencing.html'
        )
        if existing_course is None:
            db.session.add(course)
            db.session.flush()
        
        print(f"✓ 创建排序课程: id={course.id}, title={course.title}")
        
        # 4. 创建课程项
        course_item = CourseItem.query.filter_by(
            course_id=course.id,
            media_file='resources/images/paixu/',
        ).first() or CourseItem.query.filter_by(
            course_id=course.id,
            name='排序',
        ).first()
        if course_item is None:
            course_item = CourseItem(course_id=course.id, name='排序', type='interactive')
            db.session.add(course_item)
        course_item.name = '排序'
        course_item.type = 'interactive'
        course_item.media_file = 'resources/images/paixu/'
        db.session.commit()
        
        print(f"✓ 已同步课程项: id={course_item.id}, name={course_item.name}")
        print(f"  - type: {course_item.type}")
        print(f"  - media_file: {course_item.media_file}")
        
        print("\n✅ 排序课程导入完成！")
        
        # 5. 验证
        print("\n📊 验证结果:")
        all_courses = Course.query.filter_by(course_type_id=sequencing_type.id).all()
        for c in all_courses:
            print(f"  课程: {c.title} (id={c.id})")
            items = CourseItem.query.filter_by(course_id=c.id).all()
            for item in items:
                print(f"    └─ 课程项: {item.name} (id={item.id})")
        
        return True

if __name__ == '__main__':
    print("=" * 60)
    print("排序课程数据导入脚本")
    print("=" * 60)
    print()
    
    success = import_sequencing_course(force=('--force' in sys.argv or '--yes' in sys.argv))
    
    if success:
        print("\n✅ 导入成功！")
    else:
        print("\n❌ 导入失败")
        sys.exit(1)
