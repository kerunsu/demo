"""
数据库初始化脚本
用于创建数据库表和初始化默认数据
"""
import os
import sys

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app import create_app  # noqa: E402
from database.models import (  # noqa: E402
    db,
    Teacher,
    CourseType,
    AbilityType,
    Course,
    CourseItem
)


def init_database():
    """初始化数据库"""
    # app/__init__.py 里的全局 app 默认为 None；须 create_app 才有可用实例
    application, _ = create_app()
    with application.app_context():
        # 创建所有表
        db.create_all()
        print("数据库表创建成功！")
        
        # 初始化课程类型字典表
        # Fresh Demo databases only receive the reviewed two-course scope.
        # Existing deployments are upgraded in place: historical inactive rows
        # are retained for data safety but never exposed by Demo APIs.
        missing_types = [
            name for name in ('配对', '排序')
            if not CourseType.query.filter_by(name=name).first()
        ]
        if missing_types:
            db.session.add_all(CourseType(name=name) for name in missing_types)
            print(f"已补齐 Demo 课程类型：{', '.join(missing_types)}")
        else:
            print("Demo 课程类型字典表已有数据，跳过初始化")
        
        # 初始化能力类型字典表
        if AbilityType.query.count() == 0:
            ability_types = [
                AbilityType(name='注意力'),
                AbilityType(name='配对'),
                AbilityType(name='排序'),
            ]
            db.session.add_all(ability_types)
            print("能力类型字典表初始化成功！")
        else:
            print("能力类型字典表已有数据，跳过初始化")
        
        # 检查是否已有数据
        if Teacher.query.count() == 0:
            # 创建默认管理员账户
            admin = Teacher(
                username='admin',
                real_name='管理员',
                email='admin@example.com',
                is_active=True
            )
            admin.set_password('admin123')  # 默认密码：admin123
            
            db.session.add(admin)
            print("默认管理员账户创建成功！")
            print("用户名: admin")
            print("密码: admin123")
        else:
            print("数据库中已有教师账户数据，跳过默认账户创建")
        
        db.session.commit()
        print("\n数据库初始化完成！")


if __name__ == '__main__':
    init_database()

