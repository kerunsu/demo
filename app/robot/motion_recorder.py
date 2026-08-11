"""
动作录制器
负责录制、保存机械臂动作序列
"""
import time
import threading
from typing import List, Dict, Optional, Any

from app.robot.motion_storage import (
    get_motion_metadata,
    load_motions,
    save_motions,
    sanitize_frames,
)
from app.robot.neutral_pose import complete_pose
from app.utils.logger import setup_logger

logger = setup_logger('motion_recorder')


class MotionRecorder:
    """
    动作录制器
    
    录制姿态数据帧序列，支持保存到 JSON 文件
    """
    
    def __init__(self):
        self._is_recording = False
        self._frames: List[Dict[str, Any]] = []
        self._start_time: Optional[float] = None
        self._lock = threading.Lock()
    
    @property
    def is_recording(self) -> bool:
        """是否正在录制"""
        return self._is_recording
    
    def start(self) -> None:
        """开始录制"""
        with self._lock:
            self._is_recording = True
            self._frames = []
            self._start_time = time.time()
            logger.info("🔴 录制开始")
    
    def add_frame(self, pose_data: Dict[str, float]) -> None:
        """
        添加一帧数据
        
        Args:
            pose_data: 姿态数据 {pitch, yaw, armL, armR}
        """
        if not self._is_recording:
            return
        
        with self._lock:
            timestamp = int((time.time() - self._start_time) * 1000)  # 毫秒
            self._frames.append({
                'time': timestamp,
                'pose': complete_pose(pose_data),
            })
    
    def stop(self) -> List[Dict[str, Any]]:
        """
        停止录制
        
        Returns:
            录制的帧列表
        """
        with self._lock:
            self._is_recording = False
            recorded_frames = self._frames.copy()
            logger.info(f"⏹️ 录制停止，共捕获 {len(recorded_frames)} 帧")
            return recorded_frames
    
    def save(self, motion_name: str, frames: List[Dict[str, Any]]) -> bool:
        """
        保存动作到文件
        
        Args:
            motion_name: 动作名称
            frames: 帧数据列表
            
        Returns:
            是否保存成功
        """
        try:
            motions = load_motions()
            motions[motion_name] = sanitize_frames(frames)
            save_motions(motions)
            
            logger.info(f"💾 动作 '{motion_name}' 已保存，共 {len(frames)} 帧")
            return True
        except Exception as e:
            logger.error(f"保存动作失败: {e}")
            return False
    
    def get_all_motions(self) -> Dict[str, List[Dict]]:
        """获取所有已保存的动作"""
        try:
            return load_motions()
        except Exception as e:
            logger.error(f"读取动作文件失败: {e}")
            return {}
    
    def get_motion(self, motion_name: str) -> Optional[List[Dict]]:
        """获取指定动作的帧数据"""
        motions = self.get_all_motions()
        return motions.get(motion_name)
    
    def delete_motion(self, motion_name: str) -> bool:
        """删除指定动作"""
        try:
            motions = load_motions()
            
            if motion_name not in motions:
                return False
            
            del motions[motion_name]
            save_motions(motions)
            
            logger.info(f"🗑️ 动作 '{motion_name}' 已删除")
            return True
        except Exception as e:
            logger.error(f"删除动作失败: {e}")
            return False
    
    def get_motion_list(self) -> List[Dict[str, Any]]:
        """
        获取动作列表（含统计信息）
        
        Returns:
            动作列表 [{name, frameCount, duration}, ...]
        """
        motions = self.get_all_motions()
        motion_list = []
        
        for name, frames in motions.items():
            metadata = get_motion_metadata(name)
            speed = float(metadata.get('speedMultiplier') or 1.0)
            duration = int(round(frames[-1]['time'] / speed)) if frames else 0
            motion_list.append({
                'name': name,
                'frameCount': len(frames),
                'duration': duration,
                'metadata': metadata,
            })
        
        return motion_list
