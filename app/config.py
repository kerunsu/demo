"""
配置管理模块
统一管理所有配置项
"""
import os
from pathlib import Path

from sqlalchemy.pool import NullPool

# 获取项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    """应用配置类"""
    
    # ==================== Flask基础配置 ====================
    SECRET_KEY = os.environ.get('SECRET_KEY', 'secret!')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # ==================== 数据库配置 ====================
    # Deployment databases are mutable runtime data.  Allow operators to keep
    # them outside the source tree and do not retain long-lived SQLite file
    # handles: replacing/restoring app.db while Flask is running otherwise
    # leaves pooled connections stuck on Windows with ``disk I/O error``.
    DATABASE_PATH = Path(
        os.environ.get('EIART_DATABASE_PATH', BASE_DIR / 'database' / 'app.db')
    ).expanduser().resolve()
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        f'sqlite:///{DATABASE_PATH.as_posix()}',
    )
    SQLALCHEMY_ENGINE_OPTIONS = {
        'poolclass': NullPool,
        'connect_args': {
            'timeout': float(os.environ.get('SQLITE_BUSY_TIMEOUT_SECONDS', '30')),
        },
    }
    
    # ==================== 录制配置 ====================
    # 视频配置
    # 注意：分辨率必须与前端 child.js 中的配置匹配！
    # 前端使用 640x480 分辨率
    VIDEO_FPS = int(os.environ.get('VIDEO_FPS', 30))
    VIDEO_CODEC = os.environ.get('VIDEO_CODEC', 'mjpg')  # 使用 MJPG，Windows 兼容性更好
    VIDEO_QUALITY = os.environ.get('VIDEO_QUALITY', 'medium')  # low, medium, high
    VIDEO_WIDTH = int(os.environ.get('VIDEO_WIDTH', 640))
    VIDEO_HEIGHT = int(os.environ.get('VIDEO_HEIGHT', 480))
    
    # 音频配置
    # 注意：必须与前端 child.js 中的配置匹配！
    # 前端使用 16000 Hz 采样率和单声道（1通道）
    AUDIO_SAMPLE_RATE = int(os.environ.get('AUDIO_SAMPLE_RATE', 16000))
    AUDIO_CHANNELS = int(os.environ.get('AUDIO_CHANNELS', 1))
    AUDIO_CODEC = os.environ.get('AUDIO_CODEC', 'aac')
    AUDIO_BITRATE = os.environ.get('AUDIO_BITRATE', '128k')
    
    # ==================== 存储配置 ====================
    # 静态文件目录
    STATIC_DIR = BASE_DIR / 'static'
    # 录制文件存储目录
    RECORDINGS_DIR = BASE_DIR / 'static' / 'recordings'
    # 分析结果存储目录
    RESULTS_DIR = BASE_DIR / 'static' / 'results'
    # 临时文件目录
    TEMP_DIR = BASE_DIR / 'static' / 'temp'
    
    # 确保目录存在
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    
    # ==================== 队列配置 ====================
    # 视频帧队列大小（超过此大小会丢弃最旧的帧）
    VIDEO_QUEUE_SIZE = int(os.environ.get('VIDEO_QUEUE_SIZE', 100))
    # 音频块队列大小
    AUDIO_QUEUE_SIZE = int(os.environ.get('AUDIO_QUEUE_SIZE', 200))
    # 结果队列大小
    RESULT_QUEUE_SIZE = int(os.environ.get('RESULT_QUEUE_SIZE', 50))
    
    # ==================== 分析配置 ====================
    # 是否启用各种分析功能
    POSE_ESTIMATION_ENABLED = os.environ.get('POSE_ESTIMATION_ENABLED', 'true').lower() == 'true'
    FACE_ANALYSIS_ENABLED = os.environ.get('FACE_ANALYSIS_ENABLED', 'true').lower() == 'true'
    AUDIO_ANALYSIS_ENABLED = os.environ.get('AUDIO_ANALYSIS_ENABLED', 'true').lower() == 'true'
    OBJECT_DETECTION_ENABLED = os.environ.get('OBJECT_DETECTION_ENABLED', 'false').lower() == 'true'
    
    # 分析频率（每N帧分析一次，降低计算负担）
    VISION_ANALYSIS_INTERVAL = int(os.environ.get('VISION_ANALYSIS_INTERVAL', 5))  # 每5帧分析一次
    AUDIO_ANALYSIS_INTERVAL = float(os.environ.get('AUDIO_ANALYSIS_INTERVAL', 1.0))  # 每1秒分析一次
    
    # ==================== 会话配置 ====================
    # 会话超时时间（秒），超过此时间未活动则自动结束会话
    SESSION_TIMEOUT = int(os.environ.get('SESSION_TIMEOUT', 3600))  # 1小时
    # 最大并发会话数
    MAX_CONCURRENT_SESSIONS = int(os.environ.get('MAX_CONCURRENT_SESSIONS', 10))
    
    # ==================== WebSocket配置 ====================
    # WebSocket心跳间隔（秒）
    WS_HEARTBEAT_INTERVAL = int(os.environ.get('WS_HEARTBEAT_INTERVAL', 25))
    # WebSocket超时时间（秒）
    WS_TIMEOUT = int(os.environ.get('WS_TIMEOUT', 60))

    # ==================== 儿童端媒体采集模式 ====================
    # Demo 不启动 Robot Runtime；儿童页直接通过浏览器采集并上行。
    CHILD_MEDIA_MODE = "browser"
    MEDIA_UPLOAD_SHARED_KEY = os.environ.get(
        'MEDIA_UPLOAD_SHARED_KEY', os.environ.get('CHILD_MEDIA_AGENT_KEY', '')
    )
    BROWSER_JPEG_QUALITY = int(os.environ.get(
        'BROWSER_JPEG_QUALITY', os.environ.get('CHILD_MEDIA_AGENT_JPEG_QUALITY', 50)
    ))

    # ==================== Server 监控台预览（阶段 E2）====================
    # 默认开启：从 agent 上行 probe 缓存抽稀展示；仅预览不进评分
    MONITOR_PREVIEW_ENABLED = os.environ.get('MONITOR_PREVIEW_ENABLED', '1').strip().lower() in (
        '1', 'true', 'yes', 'on',
    )
    MONITOR_PREVIEW_TTL_MS = int(os.environ.get('MONITOR_PREVIEW_TTL_MS', 3000))
    MONITOR_PREVIEW_MAX_BYTES = int(os.environ.get('MONITOR_PREVIEW_MAX_BYTES', 350_000))
    # 监控远端预览快通道轮询建议间隔（前端使用）
    MONITOR_REMOTE_PREVIEW_POLL_MS = int(os.environ.get('MONITOR_REMOTE_PREVIEW_POLL_MS', 250))

    @classmethod
    def get_child_media_mode(cls) -> str:
        return 'browser'

    @classmethod
    def set_child_media_mode(cls, mode: str, *, persist: bool = True) -> str:
        normalized = (mode or '').strip().lower()
        if normalized != 'browser':
            raise ValueError("Demo 机儿童媒体模式固定为 browser")
        cls.CHILD_MEDIA_MODE = normalized
        if persist:
            from app.runtime_modes import save_runtime_modes
            save_runtime_modes(child_media_mode=normalized)
        return normalized

    @classmethod
    def get_child_runtime_config(cls) -> dict:
        """Demo 儿童端启动配置；不暴露 Robot/Media Agent 地址。"""
        try:
            from app.behavior.camera_config import (
                load_camera_analysis_config,
                should_run_browser_camera_analysis,
            )
            cam = load_camera_analysis_config()
            cam_enabled = should_run_browser_camera_analysis(cam)
        except Exception:
            cam = {"enabled": True, "fps": 1, "width": 160, "height": 120}
            cam_enabled = True
        return {
            'mediaMode': 'browser',
            'videoFps': cls.VIDEO_FPS,
            'videoWidth': cls.VIDEO_WIDTH,
            'videoHeight': cls.VIDEO_HEIGHT,
            'jpegQuality': cls.BROWSER_JPEG_QUALITY,
            'audioSampleRate': cls.AUDIO_SAMPLE_RATE,
            'audioChannels': cls.AUDIO_CHANNELS,
            'cameraAnalysis': {
                'enabled': bool(cam_enabled),
                'fps': float(cam.get('fps', 1)),
                'width': int(cam.get('width', 160)),
                'height': int(cam.get('height', 120)),
            },
            'dialogueTtsMode': cls.DIALOGUE_TTS_MODE,
            'dialogueEnabled': cls.DIALOGUE_ENABLED,
            'dialogueWakeWordEnabled': bool(cls.DIALOGUE_WAKE_WORD_ENABLED),
            'browserSpeechRate': float(cls.BROWSER_SPEECH_RATE),
            'chatProvider': cls.AI_CHAT_PROVIDER,
        }
    
    # ==================== 儿童对话 / 浏览器 TTS ====================
    # 课程语音统一由儿童端浏览器实时生成；旧 MP3 字段仅保留数据兼容。
    DIALOGUE_TTS_MODE = 'browser'
    BROWSER_SPEECH_RATE = 0.88
    DIALOGUE_ENABLED = os.environ.get('DIALOGUE_ENABLED', 'true').lower() == 'true'
    # Teacher-triggered wake is the production default.  Voice wake remains an
    # explicit Server-console option for environments that need it.
    DIALOGUE_WAKE_WORD_ENABLED = os.environ.get(
        'DIALOGUE_WAKE_WORD_ENABLED', 'false'
    ).strip().lower() in ('1', 'true', 'yes', 'on')
    AI_CHAT_PROVIDER = (os.environ.get('AI_CHAT_PROVIDER') or 'asd').strip().lower()
    VOICE_PYTHON_SERVICE_URL = (
        os.environ.get('VOICE_PYTHON_SERVICE_URL') or 'http://127.0.0.1:8765'
    ).rstrip('/')

    # ==================== 日志配置 ====================
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    LOG_FILE = BASE_DIR / 'logs' / 'app.log'
    LOG_DIR = BASE_DIR / 'logs'
    
    # 确保日志目录存在
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    # ==================== 性能配置 ====================
    # 分析线程池大小
    ANALYSIS_THREAD_POOL_SIZE = int(os.environ.get('ANALYSIS_THREAD_POOL_SIZE', 4))
    # 录制线程池大小
    RECORDING_THREAD_POOL_SIZE = int(os.environ.get('RECORDING_THREAD_POOL_SIZE', 2))
    
    # ==================== 文件格式配置 ====================
    # 使用 AVI 格式，与 MJPG 编解码器配合更稳定
    VIDEO_FILE_EXTENSION = '.avi'
    AUDIO_FILE_EXTENSION = '.wav'
    RESULT_FILE_EXTENSION = '.json'
    
    @classmethod
    def get_recording_path(cls, session_id: str) -> Path:
        """
        解析会话的录制文件存储路径，不创建目录。

        连续录制（方案 B）：若已登记 human_dir，则落在
        ``static/recordings/sessions/{姓名-年龄-日期-N}/``；
        否则回退到 legacy ``static/recordings/{session_id}/``。

        目录只能由第一笔实际元数据或媒体写入创建；路径查询、会话预留和
        预检不得留下空 UUID 目录。
        """
        try:
            from app.services.recording_timeline import resolve_recording_dir

            mapped = resolve_recording_dir(session_id)
            if mapped is not None:
                return mapped
        except Exception:
            pass
        session_dir = cls.RECORDINGS_DIR / session_id
        return session_dir

    @classmethod
    def get_result_path(cls, session_id: str) -> Path:
        """解析会话的分析结果路径，不在只读查询时创建目录。"""
        return cls.RESULTS_DIR / session_id

    @classmethod
    def get_video_file_path(cls, session_id: str) -> Path:
        """获取视频文件完整路径"""
        return cls.get_recording_path(session_id) / f'video{cls.VIDEO_FILE_EXTENSION}'

    @classmethod
    def get_audio_file_path(cls, session_id: str) -> Path:
        """获取音频文件完整路径"""
        return cls.get_recording_path(session_id) / f'audio{cls.AUDIO_FILE_EXTENSION}'

    @classmethod
    def get_result_file_path(cls, session_id: str) -> Path:
        """获取结果文件完整路径"""
        return cls.get_result_path(session_id) / f'results{cls.RESULT_FILE_EXTENSION}'

