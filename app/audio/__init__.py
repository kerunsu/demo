"""
语音系统模块
提供语音管理、选择、播放控制等功能
"""
from .models import (
    AudioEntry,
    AudioFile,
    AudioContext,
    AudioStatus,
    PlaybackStatus,
    SelectionStrategy,
    AudioManifest
)
from .registry import AudioRegistry, get_audio_registry
from .selector import AudioSelector, get_audio_selector
from .events import (
    AudioEventEmitter, 
    get_audio_emitter, 
    init_audio_emitter
)
from .controller import (
    AudioController, 
    get_audio_controller, 
    init_audio_controller
)
from .service import (
    AudioService,
    get_audio_service,
    init_audio_service
)

__all__ = [
    # 数据模型
    'AudioEntry',
    'AudioFile',
    'AudioContext',
    'AudioStatus',
    'PlaybackStatus',
    'SelectionStrategy',
    'AudioManifest',
    
    # 注册表
    'AudioRegistry',
    'get_audio_registry',
    
    # 选择器
    'AudioSelector',
    'get_audio_selector',
    
    # 事件发送器
    'AudioEventEmitter',
    'get_audio_emitter',
    'init_audio_emitter',
    
    # 播放控制器
    'AudioController',
    'get_audio_controller',
    'init_audio_controller',
    
    # 语音服务
    'AudioService',
    'get_audio_service',
    'init_audio_service',
]
