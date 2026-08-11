"""
语音分析器（Mock）
分析音频中的语音内容、语音活动检测等
"""
import random
import time
from typing import Optional, Dict, Any, List
import numpy as np

from app.core.base_analyzer import BaseAudioAnalyzer
from app.core.models import (
    AnalysisMode,
    AnalyzerType,
    AnalysisResult,
    AnalysisContext
)
from app.utils.logger import setup_logger

logger = setup_logger('speech_analyzer')


# 模拟的音素列表
MOCK_PHONEMES = [
    'a', 'ai', 'an', 'ang', 'ao',
    'b', 'c', 'ch', 'd', 'e',
    'ei', 'en', 'eng', 'er', 'f',
    'g', 'h', 'i', 'j', 'k',
    'l', 'm', 'n', 'o', 'ou',
    'p', 'q', 'r', 's', 'sh',
    't', 'u', 'v', 'w', 'x',
    'y', 'z', 'zh'
]

# 模拟的简单词汇
MOCK_WORDS = [
    '苹果', '香蕉', '西瓜', '橙子',
    '你好', '谢谢', '再见', '对不起',
    '老师', '同学', '妈妈', '爸爸',
    '红色', '蓝色', '绿色', '黄色',
    '一', '二', '三', '四', '五'
]


class MockSpeechAnalyzer(BaseAudioAnalyzer):
    """
    Mock语音分析器
    
    返回模拟的语音识别和分析数据
    用于在没有真实ASR模型时验证整个分析流程
    
    功能：
    - 语音活动检测（VAD）
    - 语音识别（ASR）模拟
    - 语音特征提取（时长、响度等）
    """
    
    def __init__(
        self,
        mode: AnalysisMode = AnalysisMode.REALTIME,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        初始化Mock语音分析器
        
        Args:
            mode: 分析模式
            config: 配置参数
        """
        super().__init__(AnalyzerType.SPEECH, mode, config)
        
        # Mock配置
        self._speech_probability = config.get('speech_probability', 0.3) if config else 0.3
        self._recognition_confidence = config.get('recognition_confidence', 0.8) if config else 0.8
        
        # 统计
        self._total_speech_duration = 0.0
        self._word_count = 0
        
        logger.info("Mock语音分析器已创建")
    
    def _detect_speech_activity(self, audio_chunk: np.ndarray) -> Dict[str, Any]:
        """
        语音活动检测（VAD）- Mock实现
        
        Args:
            audio_chunk: 音频数据
        
        Returns:
            VAD结果
        """
        # Mock: 根据概率判断是否有语音
        is_speech = random.random() < self._speech_probability
        
        # 模拟能量计算
        if isinstance(audio_chunk, np.ndarray) and len(audio_chunk) > 0:
            energy = float(np.mean(np.abs(audio_chunk)))
        else:
            energy = random.uniform(0.01, 0.1)
        
        return {
            'is_speech': is_speech,
            'energy': round(energy, 4),
            'energy_db': round(20 * np.log10(max(energy, 1e-10)), 2),
            'confidence': round(random.uniform(0.7, 0.95), 3)
        }
    
    def _recognize_speech(self, audio_chunk: np.ndarray) -> Dict[str, Any]:
        """
        语音识别（ASR）- Mock实现
        
        Args:
            audio_chunk: 音频数据
        
        Returns:
            ASR结果
        """
        # Mock: 随机选择一个词作为识别结果
        if random.random() < 0.8:  # 80%概率识别出词
            word = random.choice(MOCK_WORDS)
            confidence = self._recognition_confidence + random.uniform(-0.15, 0.1)
            confidence = max(0.0, min(1.0, confidence))
            
            # 模拟音素序列
            phoneme_count = random.randint(2, 5)
            phonemes = random.sample(MOCK_PHONEMES, min(phoneme_count, len(MOCK_PHONEMES)))
            
            return {
                'text': word,
                'confidence': round(confidence, 3),
                'phonemes': phonemes,
                'word_count': 1,
                'is_final': True
            }
        else:
            return {
                'text': '',
                'confidence': 0.0,
                'phonemes': [],
                'word_count': 0,
                'is_final': True
            }
    
    def _extract_audio_features(self, audio_chunk: np.ndarray) -> Dict[str, float]:
        """
        提取音频特征 - Mock实现
        
        Returns:
            音频特征字典
        """
        # Mock: 生成随机的音频特征
        return {
            'pitch_mean': round(random.uniform(100, 400), 2),  # Hz
            'pitch_std': round(random.uniform(10, 50), 2),
            'volume_mean': round(random.uniform(-40, -10), 2),  # dB
            'volume_std': round(random.uniform(2, 10), 2),
            'speaking_rate': round(random.uniform(2, 6), 2),  # 音节/秒
            'pause_ratio': round(random.uniform(0.1, 0.4), 3)
        }
    
    def analyze_chunk(
        self,
        audio_chunk: np.ndarray,
        context: AnalysisContext
    ) -> Optional[AnalysisResult]:
        """
        分析单个音频块
        
        Args:
            audio_chunk: 音频数据（numpy数组）
            context: 分析上下文
        
        Returns:
            语音分析结果
        """
        if not self.is_ready:
            if not self.initialize():
                return None
        
        try:
            # 语音活动检测
            vad_result = self._detect_speech_activity(audio_chunk)
            
            # 初始化结果
            asr_result = {'text': '', 'confidence': 0.0, 'phonemes': [], 'word_count': 0}
            audio_features = {}
            
            # 如果检测到语音，进行识别
            if vad_result['is_speech']:
                asr_result = self._recognize_speech(audio_chunk)
                audio_features = self._extract_audio_features(audio_chunk)
                
                # 更新统计
                chunk_duration = len(audio_chunk) / 16000 if isinstance(audio_chunk, np.ndarray) else 0.1
                self._total_speech_duration += chunk_duration
                self._word_count += asr_result.get('word_count', 0)
            
            # 构建结果数据
            chunk_duration = len(audio_chunk) / 16000 if isinstance(audio_chunk, np.ndarray) else 0.1
            volume_mean = float(audio_features.get('volume_mean', 0) or 0)
            pause_ratio = float(audio_features.get('pause_ratio', 0) or 0)
            clarity_proxy = max(0.0, min(1.0, (1.0 - pause_ratio) * 0.5 + min(1.0, volume_mean) * 0.5)) if audio_features else (
                0.6 if vad_result.get('is_speech') else 0.0
            )
            speech_ratio = 1.0 if vad_result.get('is_speech') else 0.0

            data = {
                'vad': vad_result,
                'asr': asr_result,
                'audio_features': audio_features,
                # 表达性语言稳定字段（默认人声=儿童）
                'speech_ratio': speech_ratio,
                'word_count': asr_result.get('word_count', 0),
                'speech_duration': round(chunk_duration if vad_result.get('is_speech') else 0.0, 3),
                'clarity_proxy': round(clarity_proxy, 3),
                'is_speech': bool(vad_result.get('is_speech')),
                'transcript': asr_result.get('text', ''),
                'data_quality': 'VALID' if vad_result.get('is_speech') else 'DEGRADED',
                'speaker_assumption': 'child',
                'statistics': {
                    'total_speech_duration': round(self._total_speech_duration, 2),
                    'total_word_count': self._word_count
                }
            }
            
            result = AnalysisResult(
                session_id=context.session_id,
                analyzer_type=self._analyzer_type.value,
                mode=self._mode,
                timestamp=time.time(),
                data=data,
                confidence=vad_result['confidence']
            )
            
            return result
            
        except Exception as e:
            logger.error(f"语音分析失败: {e}")
            return None
    
    def reset_statistics(self) -> None:
        """重置统计数据"""
        self._total_speech_duration = 0.0
        self._word_count = 0
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取当前统计数据"""
        return {
            'total_speech_duration': round(self._total_speech_duration, 2),
            'total_word_count': self._word_count,
            'average_words_per_minute': round(
                self._word_count / max(self._total_speech_duration / 60, 0.001), 2
            )
        }


class MockSessionSpeechAnalyzer(BaseAudioAnalyzer):
    """
    Mock会话级语音分析器（Type C：会话总结分析）
    
    用于在课程结束后统计整个会话的语音数据
    - 总词数
    - 总语音时长
    - 平均语速
    等
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化会话级语音分析器
        
        Args:
            config: 配置参数
        """
        super().__init__(AnalyzerType.SPEECH, AnalysisMode.SESSION, config)
        logger.info("Mock会话级语音分析器已创建")
    
    def analyze_session(
        self,
        all_speech_results: List[AnalysisResult],
        context: AnalysisContext
    ) -> Optional[AnalysisResult]:
        """
        分析整个会话的语音数据
        
        Args:
            all_speech_results: 会话中所有的语音分析结果
            context: 分析上下文
        
        Returns:
            会话总结结果
        """
        if not self.is_ready:
            if not self.initialize():
                return None
        
        try:
            # 统计总词数
            total_words = 0
            total_speech_duration = 0.0
            all_texts = []
            speech_segments = 0
            
            for result in all_speech_results:
                if result.data:
                    asr = result.data.get('asr', {})
                    vad = result.data.get('vad', {})
                    
                    total_words += asr.get('word_count', 0)
                    if asr.get('text'):
                        all_texts.append(asr['text'])
                    
                    if vad.get('is_speech'):
                        speech_segments += 1
                        # 估算语音时长（每段约0.1秒）
                        total_speech_duration += 0.1
            
            # 计算统计指标
            session_duration = context.metadata.get('session_duration', 60.0)  # 默认1分钟
            speech_ratio = total_speech_duration / session_duration if session_duration > 0 else 0
            words_per_minute = total_words / (session_duration / 60) if session_duration > 0 else 0
            
            # 构建结果数据
            data = {
                'summary': {
                    'total_words': total_words,
                    'total_speech_duration': round(total_speech_duration, 2),
                    'speech_segments': speech_segments,
                    'session_duration': round(session_duration, 2),
                    'speech_ratio': round(speech_ratio, 3),
                    'words_per_minute': round(words_per_minute, 2)
                },
                'recognized_words': all_texts[:20],  # 最多保留20个词
                'analyzed_results_count': len(all_speech_results)
            }
            
            result = AnalysisResult(
                session_id=context.session_id,
                analyzer_type=f"{self._analyzer_type.value}_session",
                mode=self._mode,
                timestamp=time.time(),
                data=data,
                confidence=1.0
            )
            
            logger.info(
                f"会话语音分析完成: words={total_words}, "
                f"duration={total_speech_duration:.2f}s"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"会话语音分析失败: {e}")
            return None
    
    def analyze_chunk(
        self,
        audio_chunk: np.ndarray,
        context: AnalysisContext
    ) -> Optional[AnalysisResult]:
        """不适用于会话级分析器"""
        logger.warning("会话级分析器不支持analyze_chunk方法")
        return None

