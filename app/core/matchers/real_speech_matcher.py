"""
真实语音比对器
接收分析器的强制对齐结果，进行评分判定和统计
"""
import time
import difflib
from typing import Optional, Dict, Any, List
import numpy as np

# 尝试导入基类，兼容独立测试环境
try:
    from app.core.base_matcher import BaseSpeechMatcher
except ImportError:
    class BaseSpeechMatcher:
        def __init__(self, threshold, config):
            self._threshold = threshold
            self._config = config
            self._is_initialized = False
            self._target = None

from app.core.models import MatchResult, AnalysisResult, AnalysisContext
from app.utils.logger import setup_logger

logger = setup_logger('real_speech_matcher')


class RealSpeechMatcher(BaseSpeechMatcher):
    """
    真实语音比对器
    """
    
    def __init__(
        self,
        threshold: float = 60.0,
        config: Optional[Dict[str, Any]] = None
    ):
        super().__init__(threshold, config)
        
        self._config = config or {}
        self._target_text: Optional[str] = None
        
        # 比对统计
        self._match_count = 0
        self._total_count = 0
        self._score_history: List[float] = []
        
        logger.info(f"真实语音比对器已创建: threshold={threshold}")
    
    # ==========================================
    # 必须实现的抽象方法 (满足基类契约)
    # ==========================================
    def extract_features(self, data: Any) -> Any:
        return data

    def compute_similarity(self, features1: Any, features2: Any) -> float:
        return 0.0

    # ==========================================
    # 核心业务逻辑
    # ==========================================
    def set_target(self, text: str) -> bool:
        """设置目标文本"""
        if not text:
            return False
        try:
            clean_text = text.strip().replace(" ", "").replace("\n", "")
            self._target_text = clean_text
            self._target = clean_text
            self._is_initialized = True
            logger.info(f"设置语音目标成功: {clean_text}")
            return True
        except Exception as e:
            logger.error(f"设置语音目标失败: {e}")
            return False

    def get_target(self) -> Optional[str]:
        return self._target_text

    def has_target(self) -> bool:
        return self._target_text is not None
    
    def _get_match_details(
        self, 
        analysis_data: Dict[str, Any], 
        score: float
    ) -> Dict[str, Any]:
        """获取匹配详细信息"""
        details = analysis_data.get('details', [])
        tokens = analysis_data.get('tokens', [])
        
        matched_count = 0
        for item in details:
            if item.get('score', 0) >= self._threshold:
                matched_count += 1
        
        return {
            'score': score,
            'threshold': self._threshold,
            'target_text': self._target_text,
            'latency_ms': analysis_data.get('latency_ms', 0),
            'matched_tokens': matched_count,
            'total_tokens': len(tokens),
            'token_details': details,
            'statistics': self.get_statistics()
        }
    
    def match_from_result(
        self,
        analysis_result: AnalysisResult,
        context: Optional[AnalysisContext] = None
    ) -> Optional[MatchResult]:
        """从分析结果执行匹配"""
        if not self._target_text:
            return None
            
        if "scores" not in analysis_result.data:
            return None

        self._total_count += 1
        
        # Prefer contain match; SequenceMatcher only for near-equal length phrases
        # to avoid loose fuzzy auto-praise style false positives.
        recognized_text = str(
            analysis_result.data.get('transcript')
            or (analysis_result.data.get('asr') or {}).get('text')
            or ''
        ).strip().replace(' ', '')
        target_text = str(self._target_text or '').strip().replace(' ', '')
        if not recognized_text or not target_text:
            final_score = 0.0
        elif target_text in recognized_text:
            final_score = 100.0
        elif (
            len(target_text) >= 2
            and abs(len(recognized_text) - len(target_text)) <= max(2, len(target_text) // 2)
        ):
            final_score = difflib.SequenceMatcher(None, recognized_text, target_text).ratio() * 100.0
        else:
            final_score = 0.0
        
        passed = final_score >= self._threshold
        
        if passed:
            self._match_count += 1
            
        self._score_history.append(final_score)
        if len(self._score_history) > 100:
            self._score_history.pop(0)
            
        details = self._get_match_details(analysis_result.data, final_score)
        details['recognized_text'] = recognized_text
        
        # ====================================================
        # [修复点] 补全 MatchResult 所需的所有参数
        # ====================================================
        return MatchResult(
            session_id=analysis_result.session_id,  # 补上 session_id
            timestamp=time.time(),
            matcher_type="speech_matcher",
            passed=passed,
            score=final_score,
            threshold=self._threshold,              # 补上 threshold
            details=details
        )
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取比对统计"""
        avg_score = 0.0
        if self._score_history:
            avg_score = sum(self._score_history) / len(self._score_history)

        return {
            'total_matches': self._match_count,
            'total_attempts': self._total_count,
            'match_rate': round(self._match_count / max(self._total_count, 1), 3),
            'average_score': round(avg_score, 1),
            'score_history': self._score_history[-10:],
            'target_text': self._target_text
        }
    
    def reset_statistics(self) -> None:
        self._match_count = 0
        self._total_count = 0
        self._score_history.clear()
    
    def reset_target(self) -> None:
        self._target_text = None
        self._target = None
        logger.info("语音目标已重置")
    
    def cleanup(self) -> None:
        self.reset_target()
        self.reset_statistics()
        logger.info("真实语音比对器资源已清理")
