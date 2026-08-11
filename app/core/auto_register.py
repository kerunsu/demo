"""
分析器自动注册模块

在应用启动时自动注册所有已实现的分析器和比对器
"""
from app.core.registry import AnalyzerRegistry
from app.utils.logger import setup_logger

logger = setup_logger('auto_register')


def register_all_analyzers():
    """注册所有分析器"""
    
    # ========== 视觉分析器 ==========
    
    # 姿态分析器
    try:
        from app.core.vision.pose_analyzer import MockPoseAnalyzer
        from app.core.vision.real_pose_analyzer import RealPoseAnalyzer
        
        AnalyzerRegistry.register_analyzer(
            'pose',
            mock_cls=MockPoseAnalyzer,
            real_cls=RealPoseAnalyzer,
            category='vision',
            description='姿态检测 (33关键点)'
        )
    except ImportError as e:
        logger.warning(f"注册姿态分析器失败: {e}")
    
    # 表情分析器
    try:
        from app.core.vision.face_analyzer import MockFaceAnalyzer
        
        AnalyzerRegistry.register_analyzer(
            'face',
            mock_cls=MockFaceAnalyzer,
            real_cls=None,  # Real 版本待实现
            category='vision',
            description='表情分析'
        )
    except ImportError as e:
        logger.warning(f"注册表情分析器失败: {e}")
    
    # 注意力分析器
    try:
        from app.core.vision.attention_analyzer import MockAttentionAnalyzer
        from app.core.vision.real_attention_analyzer import RealAttentionAnalyzer
        
        AnalyzerRegistry.register_analyzer(
            'attention',
            mock_cls=MockAttentionAnalyzer,
            real_cls=RealAttentionAnalyzer,
            category='vision',
            description='注意力分析 (滑动窗口)'
        )
    except ImportError as e:
        logger.warning(f"注册注意力分析器失败: {e}")
    
    # ========== 音频分析器 ==========
    
    # 语音分析器
    try:
        from app.core.audio.speech_analyzer import MockSpeechAnalyzer
        from app.core.audio.real_speech_analyzer import RealSpeechAnalyzer
        
        AnalyzerRegistry.register_analyzer(
            'speech',
            mock_cls=MockSpeechAnalyzer,
            real_cls=RealSpeechAnalyzer,
            category='audio',
            description='语音识别 (ASR)'
        )
    except ImportError as e:
        logger.warning(f"注册语音分析器失败: {e}")
    
    logger.info(f"已注册 {len(AnalyzerRegistry.list_analyzers())} 个分析器")


def register_all_matchers():
    """注册所有比对器"""
    
    # ========== 视觉比对器 ==========
    
    # 姿态比对器
    try:
        from app.core.matchers.pose_matcher import MockPoseMatcher
        from app.core.matchers.real_pose_matcher import RealPoseMatcher
        
        AnalyzerRegistry.register_matcher(
            'pose',
            mock_cls=MockPoseMatcher,
            real_cls=RealPoseMatcher,
            category='vision',
            description='姿态相似度比对'
        )
    except ImportError as e:
        logger.warning(f"注册姿态比对器失败: {e}")
    
    # ========== 音频比对器 ==========
    
    # 语音比对器
    try:
        from app.core.matchers.speech_matcher import MockSpeechMatcher
        from app.core.matchers.real_speech_matcher import RealSpeechMatcher
        
        AnalyzerRegistry.register_matcher(
            'speech',
            mock_cls=MockSpeechMatcher,
            real_cls=RealSpeechMatcher,
            category='audio',
            description='语音文本比对'
        )
    except ImportError as e:
        logger.warning(f"注册语音比对器失败: {e}")
    
    logger.info(f"已注册 {len(AnalyzerRegistry.list_matchers())} 个比对器")


def auto_register():
    """自动注册所有分析器和比对器"""
    logger.info("开始自动注册分析器和比对器...")
    register_all_analyzers()
    register_all_matchers()
    logger.info("自动注册完成")


# 导出便捷函数
__all__ = ['auto_register', 'register_all_analyzers', 'register_all_matchers']

