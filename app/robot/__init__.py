"""
机械臂模块

提供机械臂动作录制、播放、映射管理功能
"""

from app.robot.robot_service import RobotService, get_robot_service
from app.robot.motion_recorder import MotionRecorder
from app.robot.motion_player import MotionPlayer
from app.robot.mapping_resolver import MappingResolver
from app.robot.routes import robot_bp

__all__ = [
    'RobotService',
    'get_robot_service',
    'MotionRecorder',
    'MotionPlayer',
    'MappingResolver',
    'robot_bp'
]
