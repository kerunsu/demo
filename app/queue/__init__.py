"""
消息队列模块
管理视频帧、音频块和分析结果的队列
"""
import threading
from typing import Optional
from app.queue.video_queue import VideoQueue
from app.queue.audio_queue import AudioQueue
from app.queue.result_queue import (
    ResultQueue,
    get_result_queue,
    ResultType,
    QueuedResult
)

__all__ = [
    'VideoQueue',
    'AudioQueue',
    'get_video_queue',
    'get_audio_queue',
    # 结果队列
    'ResultQueue',
    'get_result_queue',
    'ResultType',
    'QueuedResult'
]

# 全局队列实例（单例模式）
_video_queue: Optional[VideoQueue] = None
_audio_queue: Optional[AudioQueue] = None
_queue_lock = threading.Lock()


def get_video_queue() -> VideoQueue:
    """获取全局视频队列实例"""
    global _video_queue
    if _video_queue is None:
        with _queue_lock:
            if _video_queue is None:
                _video_queue = VideoQueue()
    return _video_queue


def get_audio_queue() -> AudioQueue:
    """获取全局音频队列实例"""
    global _audio_queue
    if _audio_queue is None:
        with _queue_lock:
            if _audio_queue is None:
                _audio_queue = AudioQueue()
    return _audio_queue
