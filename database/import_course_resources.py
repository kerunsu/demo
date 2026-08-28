"""
课程资源导入脚本
从 CSV 映射文件导入命名和拟声课程的资源数据到数据库

使用方法:
    python database/import_course_resources.py
    
CSV 格式:
    course_type,folder_id,name,hint_audio
    naming,001,猫,resources/audios/naming/hint_cat.mp3
"""
import sys
import csv
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from database.models import db, Course, CourseItem, CourseType
from app.config import Config
from app.course_scope import is_course_type_enabled
from app.utils.resource_utils import folder_exists, get_first_file_from_folder, count_files_in_folder
from flask import Flask

# 创建临时 Flask 应用用于数据库操作
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = Config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)


# 课程类型映射
COURSE_TYPE_MAPPING = {
    'naming': '命名',
    'voice': '拟声',
    'mimic': '模仿'
}


def read_csv_mapping(csv_path: Path) -> list:
    """读取 CSV 映射文件"""
    items = []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            canonical_type = 'onomatopoeia' if row['course_type'].strip() == 'voice' else row['course_type'].strip()
            if not is_course_type_enabled(canonical_type):
                continue
            items.append({
                'course_type': row['course_type'].strip(),
                'folder_id': row['folder_id'].strip(),
                'name': row['name'].strip(),
                'hint_audio': row['hint_audio'].strip() if row['hint_audio'].strip() else None
            })
    
    return items


def validate_resources(items: list) -> tuple:
    """验证资源文件是否存在"""
    valid_items = []
    errors = []
    
    for item in items:
        course_type = item['course_type']
        folder_id = item['folder_id']
        
        # 构建文件夹路径
        if course_type == 'naming':
            folder_path = f"resources/images/naming/{folder_id}/"
        elif course_type == 'voice':
            folder_path = f"resources/images/voice/{folder_id}/"
        else:
            errors.append(f"未知的课程类型: {course_type} (文件夹 {folder_id})")
            continue
        
        # 检查文件夹是否存在
        if not folder_exists(folder_path):
            errors.append(f"文件夹不存在: {folder_path} ({item['name']})")
            continue
        
        # 统计文件数量
        file_count = count_files_in_folder(folder_path)
        if file_count == 0:
            errors.append(f"文件夹为空: {folder_path} ({item['name']})")
            continue
        
        # 获取第一张图片作为缩略图
        icon_path = get_first_file_from_folder(folder_path)
        if not icon_path:
            errors.append(f"无法获取缩略图: {folder_path} ({item['name']})")
            continue
        
        # 添加到有效列表
        item['folder_path'] = folder_path
        item['icon_path'] = icon_path
        item['file_count'] = file_count
        valid_items.append(item)
        
        print(f"✓ {item['name']}: {folder_path} ({file_count} 个文件)")
    
    return valid_items, errors


def import_to_database(items: list, dry_run: bool = False):
    """导入数据到数据库"""
    with app.app_context():
        # 按课程类型分组
        grouped = {}
        for item in items:
            course_type = item['course_type']
            if course_type not in grouped:
                grouped[course_type] = []
            grouped[course_type].append(item)
        
        # 遍历每个课程类型
        for course_type_en, course_items in grouped.items():
            course_type_cn = COURSE_TYPE_MAPPING.get(course_type_en)
            if not course_type_cn:
                print(f"⚠ 跳过未知课程类型: {course_type_en}")
                continue
            
            # 查找或创建课程类型
            course_type_obj = CourseType.query.filter_by(name=course_type_cn).first()
            if not course_type_obj:
                print(f"⚠ 课程类型不存在，需要先运行 init_db.py: {course_type_cn}")
                continue
            
            # 查找或创建课程
            course_title = f"{course_type_cn}课程"
            # Course identity is the unique CourseType, not a mutable title.
            # migrate_courses creates the canonical row as “命名”; looking for
            # “命名课程” would attempt a duplicate and violate the DB constraint.
            course = Course.query.filter_by(
                course_type_id=course_type_obj.id,
            ).first()
            
            if not course:
                if dry_run:
                    print(f"[DRY RUN] 将创建课程: {course_title}")
                else:
                    course = Course(
                        course_type_id=course_type_obj.id,
                        title=course_title,
                        question_audio=None,  # 音频资源待后续添加
                        praise_audio=None
                    )
                    db.session.add(course)
                    db.session.flush()  # 获取课程 ID
                    print(f"✓ 创建课程: {course_title} (ID: {course.id})")
            else:
                print(f"✓ 使用已有课程: {course_title} (ID: {course.id})")
            
            # 导入课程项
            for item_data in course_items:
                # 资源目录是稳定标识；显示名称可能因标注纠错而变化。
                # 先按目录查找，避免改名时新增重复课程项；名称仅兼容旧数据。
                existing_item = CourseItem.query.filter_by(
                    course_id=course.id,
                    media_file=item_data['folder_path'],
                ).first()
                if existing_item is None:
                    existing_item = CourseItem.query.filter_by(
                        course_id=course.id,
                        name=item_data['name'],
                    ).first()
                
                if existing_item:
                    # 更新现有记录
                    if dry_run:
                        print(f"[DRY RUN] 将更新课程项: {item_data['name']}")
                    else:
                        existing_item.name = item_data['name']
                        existing_item.icon = item_data['icon_path']
                        existing_item.type = 'image'
                        existing_item.media_file = item_data['folder_path']
                        existing_item.hint_audio = item_data['hint_audio']
                        print(f"  ↻ 更新: {item_data['name']} (ID: {existing_item.id})")
                else:
                    # 创建新记录
                    if dry_run:
                        print(f"[DRY RUN] 将创建课程项: {item_data['name']}")
                    else:
                        new_item = CourseItem(
                            course_id=course.id,
                            name=item_data['name'],
                            icon=item_data['icon_path'],
                            type='image',
                            media_file=item_data['folder_path'],
                            hint_audio=item_data['hint_audio']
                        )
                        db.session.add(new_item)
                        print(f"  + 新增: {item_data['name']}")
        
        # 提交更改
        if not dry_run:
            db.session.commit()
            print("\n✓ 数据导入完成")
        else:
            print("\n[DRY RUN] 未提交更改")


def main() -> bool:
    """主函数。成功返回 True，失败返回 False（不再直接 sys.exit，便于 seed 调用）。"""
    # CSV 文件路径
    csv_path = project_root / 'config' / 'course_items_mapping.csv'
    
    if not csv_path.exists():
        print(f"❌ 映射文件不存在: {csv_path}")
        return False
    
    print(f"📖 读取映射文件: {csv_path}")
    items = read_csv_mapping(csv_path)
    print(f"✓ 读取到 {len(items)} 条记录\n")
    
    # 验证资源文件
    print("🔍 验证资源文件...")
    valid_items, errors = validate_resources(items)
    
    if errors:
        print(f"\n⚠ 发现 {len(errors)} 个错误:")
        for error in errors:
            print(f"  - {error}")
        print()
    
    print(f"✓ 验证通过 {len(valid_items)} 条记录\n")
    
    if len(valid_items) == 0:
        print("❌ 没有有效的记录可导入")
        return False
    
    # 询问是否继续（--yes / --force 跳过确认）
    print("即将导入数据到数据库...")
    print(f"  - 命名课程项: {len([i for i in valid_items if i['course_type'] == 'naming'])} 个")
    print(f"  - 拟声课程项: {len([i for i in valid_items if i['course_type'] == 'voice'])} 个")

    auto_yes = '--yes' in sys.argv or '--force' in sys.argv
    dry = '--dry-run' in sys.argv or '-d' in sys.argv
    if auto_yes:
        response = 'd' if dry else 'y'
    else:
        response = input("\n是否继续? (y/n, 输入 'd' 进行 dry-run): ").strip().lower()
    
    if response == 'y':
        print("\n📝 开始导入...")
        import_to_database(valid_items, dry_run=False)
        print("\n✓ 完成！")
        return True
    elif response == 'd':
        print("\n📝 Dry-run 模式（不会实际修改数据库）...")
        import_to_database(valid_items, dry_run=True)
        print("\n✓ Dry-run 完成！")
        return True
    else:
        print("❌ 取消导入")
        return False


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
