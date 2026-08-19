"""
随机生成学生数据脚本
每次运行都会生成一个新的随机学生信息并插入数据库
后续可以直接删掉这个脚本
"""
import os
import sys
import random
from datetime import datetime, date, timedelta, time

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app import create_app  # noqa: E402
from database.models import (  # noqa: E402
    db,
    Student,
    CourseType,
    AbilityType,
    TrainingSession,
    TrainingDetail,
    AbilityItem
)

# 中文姓氏
SURNAMES = ['张', '王', '李', '赵', '刘', '陈', '杨', '黄', '周', '吴',
            '徐', '孙', '胡', '朱', '高', '林', '何', '郭', '马', '罗',
            '梁', '宋', '郑', '谢', '韩', '唐', '冯', '于', '董', '萧']

# 中文名字（常用字）
GIVEN_NAMES = ['明', '华', '强', '伟', '芳', '娜', '敏', '静', '丽', '艳',
               '军', '杰', '涛', '超', '勇', '刚', '辉', '鹏', '飞', '龙',
               '雪', '梅', '兰', '竹', '菊', '莲', '蓉', '霞', '红', '青',
               '文', '武', '斌', '博', '智', '慧', '思', '念', '心', '意',
               '浩', '宇', '天', '星', '辰', '阳', '光', '亮', '新', '欣']

# 偏好选项
PREFERENCES = [
    '积木玩具', '绘画', '乐高积木', '音乐玩具', '拼图游戏',
    '阅读绘本', '角色扮演', '运动游戏', '科学实验', '手工制作',
    '电子游戏', '户外活动', '动物玩具', '汽车模型', '娃娃玩具'
]

# 老师姓名
TEACHERS = ['李老师', '王老师', '张老师', '刘老师', '陈老师',
            '杨老师', '赵老师', '黄老师', '周老师', '吴老师']

# 筛查信息模板
SCREENING_TEMPLATES = [
    '注意力集中时间较短，对视觉刺激敏感，社交互动需要引导。在结构化环境中表现较好，建议继续加强社交技能训练。',
    '语言发展良好，创造力强，喜欢艺术类活动。注意力持续时间适中，社交主动性较强。',
    '逻辑思维能力突出，对规则理解清晰。精细动作发展良好，适合进阶训练内容。',
    '听觉学习能力强，对音乐和节奏敏感。情绪稳定，配合度高，建议多进行听觉训练。',
    '视觉空间能力较好，喜欢动手操作。需要加强语言表达和社交互动训练。',
    '运动协调能力良好，喜欢户外活动。注意力需要进一步训练，建议增加专注力训练。',
    '认知能力发展正常，学习兴趣浓厚。情绪调节能力需要加强，建议进行情绪管理训练。',
    '社交能力较强，善于与他人互动。精细动作需要进一步训练，建议增加手眼协调练习。'
]

# 头像URL（使用占位符）
AVATAR_URLS = [
    'https://images.unsplash.com/photo-1654027879796-b9dee8caabb6?w=100&h=100&fit=crop',
    'https://images.unsplash.com/photo-1503454537195-1dcabb73ffb9?w=100&h=100&fit=crop',
    'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=100&h=100&fit=crop',
    'https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=100&h=100&fit=crop',
    'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=100&h=100&fit=crop'
]


def generate_chinese_name():
    """生成随机中文姓名"""
    surname = random.choice(SURNAMES)
    # 随机选择1-2个字的名字
    if random.random() < 0.5:
        given_name = random.choice(GIVEN_NAMES)
    else:
        given_name = random.choice(GIVEN_NAMES) + random.choice(GIVEN_NAMES)
    return surname + given_name


def generate_student():
    """生成一个随机学生"""
    name = generate_chinese_name()
    age = random.randint(4, 8)
    preference = random.choice(PREFERENCES)
    teacher = random.choice(TEACHERS)
    screening = random.choice(SCREENING_TEMPLATES)
    avatar = random.choice(AVATAR_URLS)
    
    student = Student(
        name=name,
        age=age,
        preference=preference,
        teacher=teacher,
        screening=screening,
        avatar=avatar
    )
    
    return student


def generate_training_sessions(student_id, num_sessions=5):
    """为学生生成训练记录"""
    sessions = []
    course_types = CourseType.query.all()
    ability_types = AbilityType.query.all()
    
    # 生成最近30天内的训练记录
    base_date = date.today()
    
    for i in range(num_sessions):
        # 随机选择过去30天内的日期
        days_ago = random.randint(0, 30)
        training_date = base_date - timedelta(days=days_ago)
        
        # 随机生成开始和结束时间
        start_hour = random.randint(9, 16)
        start_minute = random.randint(0, 59)
        end_hour = start_hour + random.randint(1, 2)
        end_minute = random.randint(0, 59)
        
        start_time = time(start_hour, start_minute)
        end_time = time(end_hour, end_minute)
        
        session = TrainingSession(
            student_id=student_id,
            date=training_date,
            start_time=start_time,
            end_time=end_time
        )
        db.session.add(session)
        db.session.flush()  # 获取session的ID
        
        # 为这次训练生成训练详情（每种课程随机训练次数）
        for course_type in course_types:
            count = random.randint(1, 10)
            detail = TrainingDetail(
                training_session_id=session.id,
                course_type_id=course_type.id,
                count=count
            )
            db.session.add(detail)
        
        # 为这次训练生成能力项（每种能力随机分数）
        for ability_type in ability_types:
            score = random.randint(40, 95)  # 分数范围40-95
            ability_item = AbilityItem(
                training_session_id=session.id,
                ability_type_id=ability_type.id,
                score=score
            )
            db.session.add(ability_item)
        
        sessions.append(session)
    
    return sessions


def generate_sample_data():
    """生成随机学生数据"""
    # app/__init__.py global app defaults to None; create_app provides a usable instance
    application, _ = create_app()
    with application.app_context():
        # 生成学生
        student = generate_student()
        db.session.add(student)
        db.session.flush()  # 获取student的ID
        
        print(f"✓ 生成学生: {student.name} (ID: {student.id})")
        print(f"  - 年龄: {student.age}岁")
        print(f"  - 偏好: {student.preference}")
        print(f"  - 任课老师: {student.teacher}")
        
        # 生成训练记录（随机生成3-7条）
        num_sessions = random.randint(3, 7)
        sessions = generate_training_sessions(student.id, num_sessions)
        
        print(f"✓ 生成训练记录: {len(sessions)}条")
        
        # 提交所有更改
        db.session.commit()
        
        print(f"\n✅ 数据生成成功！")
        print(f"学生ID: {student.id}")
        print(f"学生姓名: {student.name}")
        print(f"训练记录数: {len(sessions)}")
        
        return student


if __name__ == '__main__':
    try:
        generate_sample_data()
    except Exception as e:
        print(f"❌ 生成数据失败: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

