"""
动作播放器
负责通过 OSC 协议播放动作序列到机械臂
"""
import time
import threading
from typing import List, Dict, Optional, Callable, Any

from pythonosc import udp_client

from app.robot.config import OSC_IP, OSC_PORT, SERVO_TIME
from app.robot.motion_storage import get_scaled_motion_frames
from app.robot.neutral_pose import complete_pose
from app.utils.logger import setup_logger

logger = setup_logger('motion_player')


class MotionPlayer:
    """
    动作播放器
    
    通过 OSC 协议将动作帧序列发送到机械臂硬件
    """
    
    def __init__(self, osc_ip: str = OSC_IP, osc_port: int = OSC_PORT):
        """
        初始化播放器
        
        Args:
            osc_ip: OSC 目标 IP
            osc_port: OSC 目标端口
        """
        self._osc_client: Optional[udp_client.SimpleUDPClient] = None
        self._osc_ip = osc_ip
        self._osc_port = osc_port
        self._is_playing = False
        self._stop_event = threading.Event()
        self._playback_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        self._init_osc_client()
    
    def _init_osc_client(self) -> None:
        """初始化 OSC 客户端"""
        try:
            self._osc_client = udp_client.SimpleUDPClient(self._osc_ip, self._osc_port)
            logger.info(f"OSC 客户端已初始化: {self._osc_ip}:{self._osc_port}")
        except Exception as e:
            logger.error(f"OSC 客户端初始化失败: {e}")
            self._osc_client = None
    
    @property
    def is_playing(self) -> bool:
        """是否正在播放"""
        with self._lock:
            return self._is_playing
    
    def send_frame(
        self,
        pose: Dict[str, float],
        move_ms: int = SERVO_TIME,
    ) -> None:
        """
        发送单帧姿态数据
        
        Args:
            pose: 姿态数据 {pitch, yaw, armL, armR}
        """
        if not self._osc_client:
            logger.warning("OSC 客户端未初始化，无法发送数据")
            return
        
        try:
            # 缺失的轴用中性位补齐，避免落入历史中间值
            safe_pose = complete_pose(pose)
            # 发送四个轴的数据
            self._osc_client.send_message(
                '/pitch', [safe_pose['pitch'], move_ms]
            )
            self._osc_client.send_message(
                '/yaw', [safe_pose['yaw'], move_ms]
            )
            self._osc_client.send_message(
                '/arml', [safe_pose['armL'], move_ms]
            )
            self._osc_client.send_message(
                '/armr', [safe_pose['armR'], move_ms]
            )
        except Exception as e:
            logger.error(f"发送 OSC 消息失败: {e}")
    
    def play(self, motion_name: str, on_complete: Optional[Callable] = None) -> bool:
        """
        播放指定动作
        
        Args:
            motion_name: 动作名称
            on_complete: 播放完成回调
            
        Returns:
            是否成功开始播放
        """
        # 读取动作数据（兼容旧格式）
        frames = get_scaled_motion_frames(motion_name)
        if not frames or len(frames) == 0:
            logger.warning(f"⚠️ 动作 '{motion_name}' 不存在或为空")
            return False
        
        logger.info(f"▶️ 播放动作 '{motion_name}' ({len(frames)} 帧)")
        
        # 启动播放线程
        stop_event = threading.Event()
        with self._lock:
            # 与 Robot Runtime 一致：新动作直接接管，不等待待机缓冲线程。
            self._stop_event.set()
            self._stop_event = stop_event
            self._is_playing = True
        thread = threading.Thread(
            target=self._playback_loop,
            args=(motion_name, frames, on_complete, stop_event),
            daemon=True,
            name=f"MotionPlayer-{motion_name}"
        )
        with self._lock:
            self._playback_thread = thread
        thread.start()
        
        return True
    
    def _playback_loop(
        self, 
        motion_name: str, 
        frames: List[Dict[str, Any]], 
        on_complete: Optional[Callable],
        stop_event: threading.Event,
    ) -> None:
        """
        播放循环（在独立线程中运行）
        
        Args:
            motion_name: 动作名称
            frames: 帧数据列表
            on_complete: 完成回调
        """
        start_time = time.time() * 1000  # 转换为毫秒
        frame_index = 0
        
        try:
            while frame_index < len(frames) and not stop_event.is_set():
                frame = frames[frame_index]
                current_time = time.time() * 1000 - start_time
                frame_time = frame['time']
                
                # 等待到达帧时间
                if frame_time > current_time:
                    sleep_time = (frame_time - current_time) / 1000.0
                    if stop_event.wait(sleep_time):
                        break
                
                if stop_event.is_set():
                    break
                
                # 发送帧数据
                self.send_frame(
                    frame['pose'],
                    int(frame.get('moveMs', SERVO_TIME)),
                )
                frame_index += 1
            
            if not stop_event.is_set():
                logger.info(f"✓ 动作 '{motion_name}' 播放完成")
        except Exception as e:
            logger.error(f"播放过程出错: {e}")
        finally:
            with self._lock:
                if self._stop_event is stop_event:
                    self._is_playing = False
                    self._playback_thread = None
            if on_complete and not stop_event.is_set():
                try:
                    on_complete()
                except Exception as e:
                    logger.error(f"播放完成回调出错: {e}")
    
    def stop(self) -> None:
        """停止播放"""
        with self._lock:
            if self._is_playing:
                self._stop_event.set()
                self._is_playing = False
                logger.info("⏹️ 播放已停止")
        # 不 join：教师的新动作可立即下发，旧线程由自己的 stop_event 退出。
    
    def send_realtime(self, pose_data: Dict[str, float]) -> None:
        """
        实时发送姿态数据（用于实时控制模式）
        
        Args:
            pose_data: 姿态数据 {pitch, yaw, armL, armR}
        """
        self.send_frame(pose_data)
