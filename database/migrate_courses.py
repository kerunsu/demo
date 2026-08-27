"""
课程数据迁移脚本
将 courses.json 文件中的数据迁移到数据库
按 CourseType 原地补齐课程骨架，不删除已有课程或课点。
"""
import os
import sys
import json            
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app import create_app  # noqa: E402
from app.config import BASE_DIR  # noqa: E402
from app.robot.config import COURSE_MAP_FILE  # noqa: E402
from app.storage.course_catalog import ensure_canonical_course_catalog  # noqa: E402
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
    """幂等导入 courses.json；force 仅保留旧 CLI 兼容，不执行破坏性覆盖。"""
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
        
        # 先修复历史重复行和外部 ID，再执行幂等补齐。迁移失败时整个
        # 操作中止，不能通过清空数据库来绕过不一致。
        catalog_result = ensure_canonical_course_catalog(
            preset_path=Path(BASE_DIR) / 'config' / 'course_presets.json',
            course_map_path=Path(COURSE_MAP_FILE),
        )
        if catalog_result['removedCourseIds']:
            print(f"已合并重复课程: {catalog_result['courseAliases']}")
        
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
            
            # 课程身份由 CourseType 决定，标题和 JSON 中的历史编号都不能
            # 再创建同课型兄弟行。仅在目标 ID 空闲时为新库保留种子 ID。
            course = Course.query.filter_by(course_type_id=course_type.id).first()
            created = course is None
            if created:
                desired_id = course_data.get('id')
                if desired_id and db.session.get(Course, desired_id) is not None:
                    desired_id = None
                course = Course(
                    id=desired_id,
                    course_type_id=course_type.id,
                    title=course_type.name,
                )
                db.session.add(course)
                db.session.flush()
            course.title = course_type.name
            for field, value in (
                ('icon', course_data.get('icon')),
                ('question_audio', course_data.get('question')),
                ('praise_audio', course_data.get('praise')),
                ('entry_file', course_data.get('file')),
            ):
                if not getattr(course, field) and value:
                    setattr(course, field, value)
            
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
                
                media_file = item_data.get('file')
                course_item = None
                if media_file:
                    course_item = CourseItem.query.filter_by(
                        course_id=course.id,
                        media_file=media_file,
                    ).first()
                if course_item is None:
                    course_item = CourseItem.query.filter_by(
                        course_id=course.id,
                        name=item_data.get('name', ''),
                    ).first()
                if course_item is None:
                    course_item = CourseItem(
                        course_id=course.id,
                        name=item_data.get('name', ''),
                        type=item_data.get('type', 'image'),
                    )
                    db.session.add(course_item)
                for field, value in (
                    ('icon', item_data.get('icon')),
                    ('media_file', media_file),
                    ('hint_audio', item_data.get('hint')),
                    ('difficulty', item_data.get('difficulty')),
                    ('config', config_json),
                ):
                    if not getattr(course_item, field) and value:
                        setattr(course_item, field, value)
            
            verb = '创建' if created else '更新'
            print(f"✓ 已{verb}课程大类: {course.title} (ID: {course.id}, 种子课点 {len(items_data)} 个)")
        
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
