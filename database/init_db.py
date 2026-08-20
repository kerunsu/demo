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

from app import app, create_app  # noqa: E402
from database.models import (  # noqa: E402
    db,
    Teacher,
    CourseType,
    AbilityType,
    Course,
    CourseItem
)


if app is None:
    app, _socketio = create_app()
    app.static_folder = os.path.join(project_root, 'static')


def init_database():
    """初始化数据库"""
    with app.app_context():
        # 创建所有表
        db.create_all()
        print("数据库表创建成功！")
        
        # 初始化课程类型字典表
        if CourseType.query.count() == 0:
            course_types = [
                CourseType(name='命名'),
                CourseType(name='拟声'),
                CourseType(name='模仿'),
                CourseType(name='配对'),
                CourseType(name='排序'),
                CourseType(name='社交'),
            ]
            db.session.add_all(course_types)
            print("课程类型字典表初始化成功！")
        else:
            # 幂等补齐：已有库可能缺「社交」
            if not CourseType.query.filter_by(name='社交').first():
                db.session.add(CourseType(name='社交'))
                print("已补齐课程类型：社交")
            else:
                print("课程类型字典表已有数据，跳过初始化")
        
        # 初始化能力类型字典表
        if AbilityType.query.count() == 0:
            ability_types = [
                AbilityType(name='注意力'),
                AbilityType(name='模仿'),
                AbilityType(name='配对'),
                AbilityType(name='排序'),
                AbilityType(name='表达性语言'),
                AbilityType(name='接收性语言'),
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

