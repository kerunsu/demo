"""
课程数据迁移脚本
将 courses.json 文件中的数据迁移到数据库
后续可以直接删掉这个脚本
"""
import os
import sys
import json            

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app import create_app  # noqa: E402
from database.models import (  # noqa: E402
    db,
    CourseType,
    Course,
    CourseItem
)


# JSON 中的 type 字段到 CourseType name 的映射
TYPE_MAPPING = {
    'mimic': '模仿',
    'naming': '命名',
    'onomatopoeia': '拟声',
    'pairing': '配对',
    'ordering': '排序',
    'social': '社交',
}


def migrate_courses(force: bool = False):
    """将 courses.json 数据迁移到数据库。force=True 时跳过确认并覆盖已有课程。"""
    # app/__init__.py 全局 app 默认为 None；须 create_app
    application, _ = create_app()
    with application.app_context():
        # 课程配置在项目根 static/（非 app 包内 static）
        courses_file = os.path.join(project_root, "static", "courses.json")
        if not os.path.exists(courses_file):
            print(f"错误：课程配置文件不存在: {courses_file}")
            return False
        
        try:
            with open(courses_file, encoding="utf-8") as f:
                courses_data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"错误：课程配置文件格式错误: {e}")
            return False
        except (IOError, OSError) as e:
            print(f"错误：读取课程配置失败: {e}")
            return False
        
        # 检查是否已有课程数据
        if Course.query.count() > 0:
            if not force:
                print("警告：数据库中已存在课程数据，是否继续迁移？")
                response = input("继续将覆盖现有数据，输入 'yes' 继续: ")
                if response.lower() != 'yes':
                    print("迁移已取消")
                    return False
            # 删除现有数据
            CourseItem.query.delete()
            Course.query.delete()
            db.session.commit()
            print("已清空现有课程数据")
        
        # 开始迁移
        print(f"开始迁移 {len(courses_data)} 个课程...")
        
        for course_data in courses_data:
            # 获取课程类型
            course_type_name = TYPE_MAPPING.get(course_data.get('type'))
            if not course_type_name:
                print(f"警告：未知的课程类型 '{course_data.get('type')}'，跳过课程 ID {course_data.get('id')}")
                continue
            
            course_type = CourseType.query.filter_by(name=course_type_name).first()
            if not course_type:
                print(f"错误：课程类型 '{course_type_name}' 不存在于数据库中，请先运行 init_db.py")
                continue
            
            # 创建课程（保留原始ID，因为课程ID在JSON中是全局唯一的）
            course = Course(
                id=course_data.get('id'),
                course_type_id=course_type.id,
                title=course_data.get('title', ''),
                icon=course_data.get('icon'),  # JSON 中可能没有这个字段
                question_audio=course_data.get('question'),
                praise_audio=course_data.get('praise'),
                entry_file=course_data.get('file')  # JSON 中的 file 字段对应 entry_file
            )
            
            db.session.add(course)
            db.session.flush()  # 获取 course.id
            
            # 创建课程项（不保留原始ID，让数据库自动生成，因为不同课程的item可能有相同的ID）
            items_data = course_data.get('items', [])
            for item_data in items_data:
                # 将 config 转换为 JSON 字符串
                config_json = None
                if 'config' in item_data:
                    try:
                        config_json = json.dumps(item_data['config'], ensure_ascii=False)
                    except (TypeError, ValueError) as e:
                        print(f"警告：课程项 {item_data.get('name')} 的 config 转换失败: {e}")
                
                course_item = CourseItem(
                    # 不设置 id，让数据库自动生成
                    course_id=course.id,
                    name=item_data.get('name', ''),
                    icon=item_data.get('icon'),  # JSON 中可能没有这个字段
                    type=item_data.get('type', 'image'),
                    media_file=item_data.get('file'),  # JSON 中的 file 字段对应 media_file
                    hint_audio=item_data.get('hint'),  # JSON 中的 hint 字段对应 hint_audio
                    difficulty=item_data.get('difficulty'),
                    config=config_json
                )
                
                db.session.add(course_item)
            
            print(f"✓ 已迁移课程: {course.title} (ID: {course.id}, 包含 {len(items_data)} 个课程项)")
        
        # 提交所有更改
        try:
            db.session.commit()
            print(f"\n迁移完成！共迁移 {len(courses_data)} 个课程")
            return True
        except Exception as e:
            db.session.rollback()
            print(f"错误：迁移失败: {e}")
            raise


if __name__ == '__main__':
    migrate_courses(force=('--force' in sys.argv or '--yes' in sys.argv))
