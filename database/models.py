"""
数据库模型定义
"""
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# 创建数据库实例
db = SQLAlchemy()


class Teacher(db.Model):
    """
    教师账户数据表
    存储教师登录的账号和密码信息
    """
    __tablename__ = 'teachers'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(80), unique=True, nullable=False, comment='用户名')
    password_hash = db.Column(db.String(255), nullable=False, comment='密码哈希值')
    real_name = db.Column(db.String(100), nullable=True, comment='真实姓名')
    email = db.Column(db.String(120), nullable=True, comment='邮箱')
    phone = db.Column(db.String(20), nullable=True, comment='手机号')
    is_active = db.Column(db.Boolean, default=True, nullable=False, comment='是否激活')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, comment='更新时间')
    last_login = db.Column(db.DateTime, nullable=True, comment='最后登录时间')
    
    def set_password(self, password):
        """设置密码（自动加密）"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """验证密码"""
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        """转换为字典（不包含敏感信息）"""
        return {
            'id': self.id,
            'username': self.username,
            'real_name': self.real_name,
            'email': self.email,
            'phone': self.phone,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }
    
    def __repr__(self):
        return f'<Teacher {self.username}>'


# ==================== 学生信息相关表 ====================

class Student(db.Model):
    """
    学生基本信息表
    每个学生一条记录
    """
    __tablename__ = 'students'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True, comment='学生ID')
    name = db.Column(db.String(100), nullable=False, comment='姓名')
    avatar = db.Column(db.String(500), nullable=True, comment='头像URL')
    age = db.Column(db.Integer, nullable=True, comment='年龄')
    preference = db.Column(db.String(200), nullable=True, comment='偏好')
    teacher = db.Column(db.String(100), nullable=True, comment='任课老师')
    screening = db.Column(db.Text, nullable=True, comment='初步筛查或简介')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, comment='更新时间')
    
    # 关联关系
    training_sessions = db.relationship('TrainingSession', backref='student', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'avatar': self.avatar,
            'age': self.age,
            'preference': self.preference,
            'teacher': self.teacher,
            'screening': self.screening,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def __repr__(self):
        return f'<Student {self.name}>'


class CourseType(db.Model):
    """
    课程类型字典表
    存储固定的5类课程：命名、拟声、模仿、配对、排序
    """
    __tablename__ = 'course_type'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True, comment='课程类型ID')
    name = db.Column(db.String(50), nullable=False, unique=True, comment='课程类型名称')
    
    # 关联关系
    training_details = db.relationship('TrainingDetail', backref='course_type', lazy=True)
    courses = db.relationship('Course', backref='course_type', lazy=True)
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name
        }
    
    def __repr__(self):
        return f'<CourseType {self.name}>'


class Course(db.Model):
    """
    课程主表
    存储课程的基本信息
    """
    __tablename__ = 'course'
    __table_args__ = (
        db.Index('uq_course_course_type', 'course_type_id', unique=True),
    )
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True, comment='课程ID')
    course_type_id = db.Column(db.Integer, db.ForeignKey('course_type.id', ondelete='RESTRICT'), nullable=False, comment='课程类型ID')
    title = db.Column(db.String(200), nullable=False, comment='显示标题')
    icon = db.Column(db.String(500), nullable=True, comment='课程图标路径')
    question_audio = db.Column(db.String(500), nullable=True, comment='问题音频路径')
    praise_audio = db.Column(db.String(500), nullable=True, comment='表扬音频路径')
    entry_file = db.Column(db.String(500), nullable=True, comment='HTML入口文件（仅交互课有）')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, comment='更新时间')
    
    # 关联关系
    items = db.relationship('CourseItem', backref='course', lazy=True, cascade='all, delete-orphan', order_by='CourseItem.id')
    
    def to_dict(self):
        """转换为字典（包含课程项，保持与原有 JSON 格式兼容）"""
        # 中文课程类型名称到英文的映射（用于前端兼容）
        type_mapping = {
            '模仿': 'mimic',
            '命名': 'naming',
            '拟声': 'onomatopoeia',
            '配对': 'pairing',
            '排序': 'ordering',
            '社交': 'social',
        }
        
        course_type_name = self.course_type.name if self.course_type else None
        type_en = type_mapping.get(course_type_name, course_type_name)
        
        result = {
            'id': self.id,
            'title': self.title,
            'type': type_en,
            'question': self.question_audio,
            'praise': self.praise_audio,
            'items': [item.to_dict() for item in self.items]
        }
        
        # 只有交互课才有 file 字段
        if self.entry_file:
            result['file'] = self.entry_file
        
        # icon 字段可选
        if self.icon:
            result['icon'] = self.icon
        
        return result
    
    def __repr__(self):
        return f'<Course {self.id} - {self.title}>'


class CourseItem(db.Model):
    """
    课程具体内容项表
    存储每个课程的具体内容项
    """
    __tablename__ = 'course_item'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True, comment='课程项ID')
    course_id = db.Column(db.Integer, db.ForeignKey('course.id', ondelete='CASCADE'), nullable=False, comment='课程ID')
    name = db.Column(db.String(200), nullable=False, comment='条目名称')
    icon = db.Column(db.String(500), nullable=True, comment='该条目图标路径')
    type = db.Column(db.String(50), nullable=False, comment='类型（image/interactive）')
    media_file = db.Column(db.String(500), nullable=True, comment='资源文件（图片/音频路径）')
    hint_audio = db.Column(db.String(500), nullable=True, comment='提示音频路径')
    difficulty = db.Column(db.String(20), nullable=True, comment='难度（easy/medium/hard）')
    config = db.Column(db.Text, nullable=True, comment='特殊配置（JSON格式，cardCount, timeLimit等）')
    speech_target = db.Column(db.String(200), nullable=True, comment='ASR 比对文本；空则回退 name')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, comment='更新时间')
    
    def to_dict(self):
        """转换为字典"""
        import json
        config_dict = None
        if self.config:
            try:
                config_dict = json.loads(self.config)
            except json.JSONDecodeError:
                config_dict = None
        
        result = {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'file': self.media_file,
            'icon': self.icon,
            'speechTarget': self.speech_target,
        }
        
        if self.hint_audio:
            result['hint'] = self.hint_audio
        
        if self.difficulty:
            result['difficulty'] = self.difficulty
        
        if config_dict:
            result['config'] = config_dict
        
        return result
    
    def __repr__(self):
        return f'<CourseItem {self.id} - {self.name} (Course {self.course_id})>'


class AbilityType(db.Model):
    """
    能力类型字典表
    存储固定的6类能力：注意力、模仿、配对、排序、表达性语言、接收性语言
    用于前端下拉选择等场景
    """
    __tablename__ = 'ability_type'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True, comment='能力类型ID')
    name = db.Column(db.String(50), nullable=False, unique=True, comment='能力类型名称')
    
    # 关联关系
    ability_items = db.relationship('AbilityItem', backref='ability_type', lazy=True)
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name
        }
    
    def __repr__(self):
        return f'<AbilityType {self.name}>'


class TrainingSession(db.Model):
    """
    训练事件表
    记录一次完整的训练事件
    """
    __tablename__ = 'training_session'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True, comment='训练事件ID')
    student_id = db.Column(db.Integer, db.ForeignKey('students.id', ondelete='CASCADE'), nullable=False, comment='学生ID')
    date = db.Column(db.Date, nullable=False, comment='训练日期')
    start_time = db.Column(db.Time, nullable=True, comment='开始时间')
    end_time = db.Column(db.Time, nullable=True, comment='结束时间')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, comment='创建时间')
    # 与 behavior/报告子系统 UUID 桥接（样例数据可为空）
    behavior_session_id = db.Column(db.String(64), unique=True, nullable=True, comment='behavior 训练会话 UUID')
    overall_score = db.Column(db.Integer, nullable=True, comment='报告综合分')
    report_status = db.Column(db.String(16), nullable=True, comment='报告状态 READY/PARTIAL')
    report_generated_at = db.Column(db.DateTime, nullable=True, comment='报告生成时间')
    
    # 关联关系
    training_details = db.relationship('TrainingDetail', backref='training_session', lazy=True, cascade='all, delete-orphan')
    ability_items = db.relationship('AbilityItem', backref='training_session', lazy=True, cascade='all, delete-orphan')
    report_summary = db.relationship(
        'TrainingReportSummary',
        backref='training_session',
        lazy=True,
        uselist=False,
        cascade='all, delete-orphan',
    )
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'student_id': self.student_id,
            'date': self.date.isoformat() if self.date else None,
            'start_time': self.start_time.strftime('%H:%M:%S') if self.start_time else None,
            'end_time': self.end_time.strftime('%H:%M:%S') if self.end_time else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'behavior_session_id': self.behavior_session_id,
            'overall_score': self.overall_score,
            'report_status': self.report_status,
            'report_generated_at': (
                self.report_generated_at.isoformat() + 'Z'
                if self.report_generated_at else None
            ),
        }
    
    def __repr__(self):
        return f'<TrainingSession {self.id} - Student {self.student_id}>'


class TrainingReportSummary(db.Model):
    """
    训练报告摘要表
    存干预建议等档案页所需摘要，完整报告仍在 behavior JSON
    """
    __tablename__ = 'training_report_summary'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True, comment='摘要ID')
    training_session_id = db.Column(
        db.Integer,
        db.ForeignKey('training_session.id', ondelete='CASCADE'),
        nullable=False,
        unique=True,
        comment='训练事件ID',
    )
    student_id = db.Column(
        db.Integer,
        db.ForeignKey('students.id', ondelete='CASCADE'),
        nullable=False,
        comment='学生ID',
    )
    behavior_session_id = db.Column(db.String(64), nullable=False, unique=True, comment='behavior UUID')
    narrative_analysis = db.Column(db.Text, nullable=True, comment='叙事分析摘要')
    recommendations_json = db.Column(db.Text, nullable=True, comment='干预建议 JSON 数组')
    dimensions_json = db.Column(db.Text, nullable=True, comment='维度分 JSON（对账用）')
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
        comment='更新时间',
    )

    def to_dict(self):
        import json
        recommendations = []
        if self.recommendations_json:
            try:
                recommendations = json.loads(self.recommendations_json)
            except (json.JSONDecodeError, TypeError):
                recommendations = []
        return {
            'id': self.id,
            'training_session_id': self.training_session_id,
            'student_id': self.student_id,
            'behavior_session_id': self.behavior_session_id,
            'analysis': self.narrative_analysis,
            'recommendations': recommendations,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<TrainingReportSummary session={self.training_session_id}>'


class TrainingDetail(db.Model):
    """
    训练详情表
    记录某次训练中每种课程的训练量
    """
    __tablename__ = 'training_detail'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True, comment='训练详情ID')
    training_session_id = db.Column(db.Integer, db.ForeignKey('training_session.id', ondelete='CASCADE'), nullable=False, comment='训练事件ID')
    course_type_id = db.Column(db.Integer, db.ForeignKey('course_type.id', ondelete='RESTRICT'), nullable=False, comment='课程类型ID')
    count = db.Column(db.Integer, nullable=False, default=0, comment='本课程训练的次数')
    
    # 唯一约束：同一训练事件中，每种课程类型只能有一条记录
    __table_args__ = (db.UniqueConstraint('training_session_id', 'course_type_id', name='uq_training_detail'),)
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'training_session_id': self.training_session_id,
            'course_type_id': self.course_type_id,
            'count': self.count,
            'course_type_name': self.course_type.name if self.course_type else None
        }
    
    def __repr__(self):
        return f'<TrainingDetail Session {self.training_session_id} - Course {self.course_type_id} - Count {self.count}>'


class AbilityItem(db.Model):
    """
    能力项表
    记录每次训练后更新的每个能力项
    通过 ability_type_id 外键关联 ability_type 表
    """
    __tablename__ = 'ability_item'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True, comment='能力项ID')
    training_session_id = db.Column(db.Integer, db.ForeignKey('training_session.id', ondelete='CASCADE'), nullable=False, comment='训练事件ID')
    ability_type_id = db.Column(db.Integer, db.ForeignKey('ability_type.id', ondelete='RESTRICT'), nullable=False, comment='能力类型ID')
    score = db.Column(db.Integer, nullable=False, comment='分数')
    
    # 唯一约束：同一训练事件中，每种能力类型只能有一条记录
    __table_args__ = (db.UniqueConstraint('training_session_id', 'ability_type_id', name='uq_ability_item'),)
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'training_session_id': self.training_session_id,
            'ability_type_id': self.ability_type_id,
            'score': self.score,
            'ability_type_name': self.ability_type.name if self.ability_type else None
        }
    
    def __repr__(self):
        return f'<AbilityItem Session {self.training_session_id} - AbilityType {self.ability_type_id} - Score {self.score}>'

