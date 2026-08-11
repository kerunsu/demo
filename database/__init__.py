"""
数据库模块初始化文件
"""
from .models import (
    db,
    Teacher,
    Student,
    CourseType,
    AbilityType,
    TrainingSession,
    TrainingDetail,
    AbilityItem,
    TrainingReportSummary,
)

__all__ = [
    'db',
    'Teacher',
    'Student',
    'CourseType',
    'AbilityType',
    'TrainingSession',
    'TrainingDetail',
    'AbilityItem',
    'TrainingReportSummary',
]

