"""
导入配对课程到数据库
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models import db, Course, CourseItem, CourseType
from flask import Flask

def import_matching_course(force: bool = False):
    """幂等补齐配对大类和课点；force 不删除稳定 ID。"""
    
    # 创建临时 Flask 应用以使用数据库
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'app.db'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    
    with app.app_context():
        # 1. 获取配对课程类型ID
        pairing_type = CourseType.query.filter_by(name='配对').first()
        if not pairing_type:
            print("❌ 错误：找不到'配对'课程类型，请先运行 init_db.py 初始化数据库")
            return False
        
        print(f"✓ 找到配对课程类型: id={pairing_type.id}, name={pairing_type.name}")
        
        # 2. 检查是否已存在配对课程
        existing_course = Course.query.filter_by(course_type_id=pairing_type.id).first()
        if existing_course:
            print(f"✓ 使用已有配对大类: id={existing_course.id}")
            existing_course.title = '配对'
            existing_course.entry_file = 'resources/interactive/matching.html'
        
        # 3. 创建配对课程
        course = existing_course or Course(
            course_type_id=pairing_type.id,
            title='配对',
            icon=None,
            question_audio=None,
            praise_audio=None,
            entry_file='resources/interactive/matching.html'
        )
        if existing_course is None:
            db.session.add(course)
            db.session.flush()
        
        print(f"✓ 创建配对课程: id={course.id}, title={course.title}")
        
        # 4. 创建课程项
        course_item = CourseItem.query.filter_by(
            course_id=course.id,
            media_file='resources/images/matching/',
        ).first() or CourseItem.query.filter_by(
            course_id=course.id,
            name='相同物品视觉配对',
        ).first()
        if course_item is None:
            course_item = CourseItem(course_id=course.id, name='相同物品视觉配对', type='interactive')
            db.session.add(course_item)
        course_item.name = '相同物品视觉配对'
        course_item.type = 'interactive'
        course_item.media_file = 'resources/images/matching/'
        db.session.commit()
        
        print(f"✓ 已同步课程项: id={course_item.id}, name={course_item.name}")
        print(f"  - type: {course_item.type}")
        print(f"  - media_file: {course_item.media_file}")
        
        print("\n✅ 配对课程导入完成！")
        
        # 5. 验证
        print("\n--- 验证导入结果 ---")
        course = Course.query.filter_by(course_type_id=pairing_type.id).first()
        print(f"Course: id={course.id}, title={course.title}, entry_file={course.entry_file}")
        for item in course.items:
            print(f"  └── CourseItem: id={item.id}, name={item.name}, type={item.type}")
        
        return True


if __name__ == '__main__':
    print("=" * 50)
    print("配对课程导入脚本")
    print("=" * 50)
    import_matching_course(force=('--force' in sys.argv or '--yes' in sys.argv))
