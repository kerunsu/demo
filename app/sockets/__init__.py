"""
WebSocket事件处理模块
处理前端发送的WebSocket事件
"""
from app.sockets.events import register_socket_events
from app.sockets.handlers import (
    PlayResourceHandler,
    VideoFrameHandler,
    AudioChunkHandler,
    StopRecordingHandler
)

__all__ = [
    'register_socket_events',
    'PlayResourceHandler',
    'VideoFrameHandler',
    'AudioChunkHandler',
    'StopRecordingHandler'
]
