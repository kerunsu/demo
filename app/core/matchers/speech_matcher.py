"""
语音比对器（Mock）
用于比较儿童发音与目标发音的相似度
"""
import time
import random
from typing import Optional, Dict, Any, List
import numpy as np

from app.core.base_matcher import BaseSpeechMatcher
from app.core.models import MatchResult, AnalysisResult, AnalysisContext
from app.utils.logger import setup_logger

logger = setup_logger('speech_matcher')


class MockSpeechMatcher(BaseSpeechMatcher):
    """
    Mock语音比对器
    
    比较儿童的发音与目标发音，返回匹配分数
    用于"命名"课程等需要语音比对的场景
    
    Type A：实时分析与控制
    
    比对维度：
    - 文本内容匹配（ASR结果与目标文字的匹配）
    - 发音准确度（音素匹配）
    - 语调/韵律相似度（Mock）
    """
    
    def __init__(
        self,
        threshold: float = 0.80,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        初始化Mock语音比对器
        
        Args:
            threshold: 匹配阈值
            config: 配置参数
        """
        super().__init__(threshold, config)
        
        # 目标语音
        self._target_text: str = ""
        self._target_phonemes: List[str] = []
        self._target_audio_features: Dict[str, float] = {}
        
        # Mock配置
        self._base_match_score = config.get('base_match_score', 0.75) if config else 0.75
        self._noise_level = config.get('noise_level', 0.15) if config else 0.15
        
        # 权重配置
        self._weights = config.get('weights', {
            'text': 0.5,
            'phoneme': 0.3,
            'prosody': 0.2
        }) if config else {'text': 0.5, 'phoneme': 0.3, 'prosody': 0.2}
        
        # 统计
        self._match_count = 0
        self._total_count = 0
        self._score_history: List[float] = []
        
        logger.info(f"Mock语音比对器已创建: threshold={threshold}")
    
    def set_target(self, target_audio: bytes) -> bool:
        """
        设置目标音频（实现抽象方法）
        
        Mock实现：从音频"提取"特征
        
        Args:
            target_audio: 目标音频数据
        
        Returns:
            True如果设置成功
        """
        try:
            # Mock: 假设从音频中识别出文本
            self._target = target_audio
            self._target_text = "mock_audio_text"
            self._target_phonemes = self._text_to_phonemes(self._target_text)
            self._target_features = {
                'text': self._target_text,
                'phonemes': self._target_phonemes,
                'audio_features': {}
            }
            
            logger.info(f"设置目标音频: text={self._target_text}")
            return True
        except Exception as e:
            logger.error(f"设置目标音频失败: {e}")
            return False
    
    def set_target_text_extended(
        self,
        text: str,
        phonemes: Optional[List[str]] = None,
        audio_features: Optional[Dict[str, float]] = None
    ) -> None:
        """
        设置目标语音（扩展方法）
        
        Args:
            text: 目标文字
            phonemes: 目标音素序列（可选）
            audio_features: 目标音频特征（可选）
        """
        self._target_text = text
        self._target = text
        self._target_phonemes = phonemes or self._text_to_phonemes(text)
        self._target_audio_features = audio_features or {}
        self._target_features = {
            'text': self._target_text,
            'phonemes': self._target_phonemes,
            'audio_features': self._target_audio_features
        }
        
        logger.info(f"设置目标语音: text='{text}', phonemes={self._target_phonemes}")
    
    def _text_to_phonemes(self, text: str) -> List[str]:
        """
        文字转音素（Mock实现）
        
        实际实现应使用专业的G2P（Grapheme-to-Phoneme）模型
        """
        phonemes = []
        for char in text:
            phonemes.append(f"p_{ord(char) % 38}")
            if random.random() > 0.5:
                phonemes.append(f"t_{ord(char) % 10}")
        return phonemes
    
    def extract_features(self, data: Any) -> Optional[Dict[str, Any]]:
        """
        提取特征（实现抽象方法）
        
        从分析结果中提取语音特征
        
        Args:
            data: 输入数据（AnalysisResult）
        
        Returns:
            特征字典
        """
        try:
            if isinstance(data, AnalysisResult):
                asr_result = data.data.get('asr', {})
                audio_features = data.data.get('audio_features', {})
                
                return {
                    'text': asr_result.get('text', ''),
                    'phonemes': asr_result.get('phonemes', []),
                    'audio_features': audio_features
                }
            elif isinstance(data, dict):
                return data
            else:
                logger.warning(f"不支持的数据类型: {type(data)}")
                return None
            
        except Exception as e:
            logger.error(f"提取特征失败: {e}")
            return None
    
    def compute_similarity(self, features1: Any, features2: Any) -> float:
        """
        计算两个特征的相似度（实现抽象方法）
        
        Args:
            features1: 特征1（儿童语音特征）
            features2: 特征2（目标语音特征）
        
        Returns:
            相似度 (0-1)
        """
        if not features1 or not features2:
            return 0.0
        
        # 文本相似度
        text1 = features1.get('text', '')
        text2 = features2.get('text', '') if isinstance(features2, dict) else self._target_text
        text_sim = self._calculate_text_similarity(text1, text2)
        
        # 音素相似度
        phonemes1 = features1.get('phonemes', [])
        phonemes2 = features2.get('phonemes', []) if isinstance(features2, dict) else self._target_phonemes
        phoneme_sim = self._calculate_phoneme_similarity(phonemes1, phonemes2)
        
        # 韵律相似度
        audio_f1 = features1.get('audio_features', {})
        audio_f2 = features2.get('audio_features', {}) if isinstance(features2, dict) else self._target_audio_features
        prosody_sim = self._calculate_prosody_similarity(audio_f1, audio_f2)
        
        # 加权综合
        score = (
            text_sim * self._weights['text'] +
            phoneme_sim * self._weights['phoneme'] +
            prosody_sim * self._weights['prosody']
        )
        
        # 添加噪声
        score += random.uniform(-self._noise_level, self._noise_level)
        score = max(0.0, min(1.0, score))
        
        return round(score, 3)
    
    def _calculate_text_similarity(
        self,
        recognized_text: str,
        target_text: str
    ) -> float:
        """计算文本相似度"""
        if not target_text:
            return 0.0
        if not recognized_text:
            return 0.0
        if recognized_text == target_text:
            return 1.0
        
        match_count = sum(1 for c in recognized_text if c in target_text)
        max_len = max(len(recognized_text), len(target_text))
        
        return match_count / max_len if max_len > 0 else 0.0
    
    def _calculate_phoneme_similarity(
        self,
        child_phonemes: List[str],
        target_phonemes: List[str]
    ) -> float:
        """计算音素序列相似度"""
        if not target_phonemes:
            return 0.0
        if not child_phonemes:
            return 0.0
        
        child_set = set(child_phonemes)
        target_set = set(target_phonemes)
        
        intersection = len(child_set & target_set)
        union = len(child_set | target_set)
        
        return intersection / union if union > 0 else 0.0
    
    def _calculate_prosody_similarity(
        self,
        child_features: Dict[str, float],
        target_features: Dict[str, float]
    ) -> float:
        """计算韵律相似度（Mock）"""
        if not target_features or not child_features:
            return random.uniform(0.6, 0.9)
        
        similarities = []
        for feature in ['pitch_mean', 'speaking_rate']:
            if feature in child_features and feature in target_features:
                child_val = child_features[feature]
                target_val = target_features[feature]
                
                if target_val > 0:
                    ratio = min(child_val, target_val) / max(child_val, target_val)
                    similarities.append(ratio)
        
        if similarities:
            return sum(similarities) / len(similarities)
        
        return random.uniform(0.6, 0.9)
    
    def _get_match_details(self, features: Any, score: float) -> Dict[str, Any]:
        """获取匹配详细信息"""
        recognized_text = features.get('text', '') if features else ''
        
        # 计算各维度分数
        text_sim = self._calculate_text_similarity(recognized_text, self._target_text)
        phoneme_sim = self._calculate_phoneme_similarity(
            features.get('phonemes', []) if features else [],
            self._target_phonemes
        )
        prosody_sim = self._calculate_prosody_similarity(
            features.get('audio_features', {}) if features else {},
            self._target_audio_features
        )
        
        return {
            'score': score,
            'threshold': self._threshold,
            'target_text': self._target_text,
            'recognized_text': recognized_text,
            'text_similarity': round(text_sim, 3),
            'phoneme_similarity': round(phoneme_sim, 3),
            'prosody_similarity': round(prosody_sim, 3),
            'weights': self._weights,
            'statistics': {
                'total_matches': self._match_count,
                'total_attempts': self._total_count,
                'match_rate': round(self._match_count / max(self._total_count, 1), 3)
            }
        }
    
    def match_from_result(
        self,
        analysis_result: AnalysisResult,
        context: Optional[AnalysisContext] = None
    ) -> MatchResult:
        """
        从分析结果执行匹配（便捷方法）
        
        Args:
            analysis_result: 语音分析结果
            context: 分析上下文（可选）
        
        Returns:
            匹配结果
        """
        if context is None:
            context = AnalysisContext(
                session_id=analysis_result.session_id,
                frame_index=getattr(analysis_result, 'frame_index', None)
            )
        
        # 更新统计
        self._total_count += 1
        
        # 使用基类的match方法
        result = super().match(analysis_result, context)
        
        if result and result.passed:
            self._match_count += 1
        
        if result:
            self._score_history.append(result.score)
            if len(self._score_history) > 100:
                self._score_history.pop(0)
        
        return result
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取比对统计"""
        return {
            'total_matches': self._match_count,
            'total_attempts': self._total_count,
            'match_rate': round(self._match_count / max(self._total_count, 1), 3),
            'average_score': round(
                sum(self._score_history) / max(len(self._score_history), 1), 3
            ),
            'current_target': self._target_text
        }
    
    def reset_statistics(self) -> None:
        """重置统计"""
        self._match_count = 0
        self._total_count = 0
        self._score_history.clear()

    def reset_target(self) -> None:
        """清除语音比对目标（换课时必须调用）"""
        self._target = None
        self._target_text = ""
        self._target_phonemes = []
        self._target_audio_features = {}
        self._target_features = None
        logger.info("Mock语音目标已重置")
