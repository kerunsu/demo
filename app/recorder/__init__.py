"""
录制模块
负责视频和音频的录制和保存
"""
from app.recorder.base_recorder import BaseRecorder
from app.recorder.video_recorder import VideoRecorder
from app.recorder.audio_recorder import AudioRecorder
from app.recorder.media_recorder import MediaRecorder

__all__ = [
    'BaseRecorder',
    'VideoRecorder',
    'AudioRecorder',
    'MediaRecorder'
]

