"""
触发系统
实现阈值判断和自动控制
"""
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from enum import Enum

from app.core.models import AnalysisResult, MatchResult, Action
from app.core.actions import ActionDefinition, ActionExecutor, ActionResult, ActionFactory
from app.utils.logger import setup_logger

logger = setup_logger('trigger')


class TriggerType(Enum):
    """触发器类型枚举"""
    THRESHOLD_ABOVE = "threshold_above"     # 高于阈值触发
    THRESHOLD_BELOW = "threshold_below"     # 低于阈值触发
    MATCH_SUCCESS = "match_success"         # 匹配成功触发
    MATCH_FAIL = "match_fail"               # 匹配失败触发（连续N次）
    DURATION = "duration"                   # 持续时间触发
    COUNT = "count"                         # 计数触发
    CUSTOM = "custom"                       # 自定义条件


@dataclass
class TriggerCondition:
    """
    触发条件配置
    """
    trigger_type: TriggerType               # 触发类型
    
    # 阈值相关
    threshold: float = 0.0                  # 阈值
    field_name: str = "score"               # 要检查的字段名
    
    # 计数/持续时间相关
    count: int = 1                          # 触发所需的计数
    duration: float = 0.0                   # 持续时间（秒）
    
    # 自定义条件
    custom_condition: Optional[Callable[[Any], bool]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'trigger_type': self.trigger_type.value,
            'threshold': self.threshold,
            'field_name': self.field_name,
            'count': self.count,
            'duration': self.duration
        }


@dataclass
class TriggerDefinition:
    """
    触发器定义
    """
    name: str                               # 触发器名称
    condition: TriggerCondition             # 触发条件
    action: ActionDefinition                # 触发动作
    cooldown: float = 3.0                   # 冷却时间（秒）
    enabled: bool = True                    # 是否启用
    priority: int = 0                       # 优先级（数值越大越先检查）
    description: str = ""                   # 描述
    
    # 内部状态
    _last_triggered: Optional[float] = field(default=None, repr=False)
    _trigger_count: int = field(default=0, repr=False)
    _consecutive_count: int = field(default=0, repr=False)  # 连续满足条件的次数
    
    def can_trigger(self) -> bool:
        """检查是否可以触发（考虑冷却时间）"""
        if not self.enabled:
            return False
        if self._last_triggered is None:
            return True
        return (time.time() - self._last_triggered) >= self.cooldown
    
    def mark_triggered(self) -> None:
        """标记已触发"""
        self._last_triggered = time.time()
        self._trigger_count += 1
    
    def reset_consecutive(self) -> None:
        """重置连续计数"""
        self._consecutive_count = 0
    
    def increment_consecutive(self) -> int:
        """增加连续计数并返回"""
        self._consecutive_count += 1
        return self._consecutive_count
    
    @property
    def trigger_count(self) -> int:
        """已触发次数"""
        return self._trigger_count
    
    @property
    def time_since_last_trigger(self) -> Optional[float]:
        """距离上次触发的时间"""
        if self._last_triggered is None:
            return None
        return time.time() - self._last_triggered
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'name': self.name,
            'condition': self.condition.to_dict(),
            'action': self.action.to_dict(),
            'cooldown': self.cooldown,
            'enabled': self.enabled,
            'priority': self.priority,
            'description': self.description,
            'trigger_count': self._trigger_count
        }


class TriggerEvaluator:
    """
    触发条件评估器
    
    负责评估各种触发条件
    """
    
    @staticmethod
    def evaluate(
        condition: TriggerCondition,
        data: Any,
        trigger_def: TriggerDefinition
    ) -> bool:
        """
        评估触发条件
        
        Args:
            condition: 触发条件
            data: 输入数据（AnalysisResult 或 MatchResult）
            trigger_def: 触发器定义（用于状态管理）
        
        Returns:
            是否满足触发条件
        """
        trigger_type = condition.trigger_type
        
        if trigger_type == TriggerType.THRESHOLD_ABOVE:
            return TriggerEvaluator._evaluate_threshold_above(condition, data)
        elif trigger_type == TriggerType.THRESHOLD_BELOW:
            return TriggerEvaluator._evaluate_threshold_below(condition, data)
        elif trigger_type == TriggerType.MATCH_SUCCESS:
            return TriggerEvaluator._evaluate_match_success(condition, data)
        elif trigger_type == TriggerType.MATCH_FAIL:
            return TriggerEvaluator._evaluate_match_fail(condition, data, trigger_def)
        elif trigger_type == TriggerType.COUNT:
            return TriggerEvaluator._evaluate_count(condition, data, trigger_def)
        elif trigger_type == TriggerType.CUSTOM:
            return TriggerEvaluator._evaluate_custom(condition, data)
        else:
            logger.warning(f"未知的触发类型: {trigger_type}")
            return False
    
    @staticmethod
    def _get_field_value(data: Any, field_name: str) -> Optional[float]:
        """从数据中获取字段值"""
        if isinstance(data, MatchResult):
            if field_name == 'score':
                return data.score
            elif field_name in data.details:
                return data.details[field_name]
        elif isinstance(data, AnalysisResult):
            if field_name in data.data:
                return data.data[field_name]
        elif isinstance(data, dict):
            return data.get(field_name)
        
        return None
    
    @staticmethod
    def _evaluate_threshold_above(condition: TriggerCondition, data: Any) -> bool:
        """评估高于阈值条件"""
        value = TriggerEvaluator._get_field_value(data, condition.field_name)
        if value is None:
            return False
        return value >= condition.threshold
    
    @staticmethod
    def _evaluate_threshold_below(condition: TriggerCondition, data: Any) -> bool:
        """评估低于阈值条件"""
        value = TriggerEvaluator._get_field_value(data, condition.field_name)
        if value is None:
            return False
        return value < condition.threshold
    
    @staticmethod
    def _evaluate_match_success(condition: TriggerCondition, data: Any) -> bool:
        """评估匹配成功条件"""
        if isinstance(data, MatchResult):
            return data.passed
        return False
    
    @staticmethod
    def _evaluate_match_fail(
        condition: TriggerCondition,
        data: Any,
        trigger_def: TriggerDefinition
    ) -> bool:
        """评估匹配失败条件（连续N次失败）"""
        if not isinstance(data, MatchResult):
            return False
        
        if data.passed:
            trigger_def.reset_consecutive()
            return False
        else:
            count = trigger_def.increment_consecutive()
            return count >= condition.count
    
    @staticmethod
    def _evaluate_count(
        condition: TriggerCondition,
        data: Any,
        trigger_def: TriggerDefinition
    ) -> bool:
        """评估计数条件"""
        count = trigger_def.increment_consecutive()
        if count >= condition.count:
            trigger_def.reset_consecutive()
            return True
        return False
    
    @staticmethod
    def _evaluate_custom(condition: TriggerCondition, data: Any) -> bool:
        """评估自定义条件"""
        if condition.custom_condition is None:
            return False
        try:
            return condition.custom_condition(data)
        except Exception as e:
            logger.error(f"评估自定义条件失败: {e}")
            return False


class TriggerSystem:
    """
    触发系统
    
    管理触发器的注册、评估和执行
    """
    
    def __init__(self, action_executor: Optional[ActionExecutor] = None):
        """
        初始化触发系统
        
        Args:
            action_executor: 动作执行器
        """
        self._triggers: Dict[str, TriggerDefinition] = {}
        # session_id -> internal trigger keys。键包含 session，避免两个儿童的
        # 同名成功触发器共享 cooldown / trigger_count 状态。
        self._session_triggers: Dict[str, List[str]] = {}
        self._executor = action_executor or ActionExecutor()
        self._lock = threading.Lock()
        
        logger.info("触发系统已初始化")
    
    @property
    def executor(self) -> ActionExecutor:
        """返回动作执行器"""
        return self._executor
    
    def set_executor(self, executor: ActionExecutor) -> None:
        """设置动作执行器"""
        self._executor = executor
    
    def register_trigger(
        self,
        trigger: TriggerDefinition,
        session_id: Optional[str] = None
    ) -> None:
        """
        注册触发器
        
        Args:
            trigger: 触发器定义
            session_id: 会话ID（如果指定，则只对该会话有效）
        """
        with self._lock:
            trigger_key = (
                f'{session_id}:{trigger.name}' if session_id else trigger.name
            )
            self._triggers[trigger_key] = trigger

            if session_id:
                if session_id not in self._session_triggers:
                    self._session_triggers[session_id] = []
                if trigger_key not in self._session_triggers[session_id]:
                    self._session_triggers[session_id].append(trigger_key)
            
            logger.info(f"注册触发器: {trigger.name}, session={session_id}")
    
    def unregister_trigger(self, name: str) -> bool:
        """
        取消注册触发器
        
        Args:
            name: 触发器名称
        
        Returns:
            是否成功
        """
        with self._lock:
            matching_keys = [
                key
                for key, trigger in self._triggers.items()
                if key == name or trigger.name == name
            ]
            if matching_keys:
                for key in matching_keys:
                    del self._triggers[key]

                # 从会话映射中移除
                for session_id in self._session_triggers:
                    self._session_triggers[session_id] = [
                        key
                        for key in self._session_triggers[session_id]
                        if key not in matching_keys
                    ]

                logger.info(f"取消注册触发器: {name}")
                return True
            return False
    
    def enable_trigger(self, name: str) -> bool:
        """启用触发器"""
        with self._lock:
            matches = [
                trigger
                for key, trigger in self._triggers.items()
                if key == name or trigger.name == name
            ]
            if matches:
                for trigger in matches:
                    trigger.enabled = True
                return True
            return False
    
    def disable_trigger(self, name: str) -> bool:
        """禁用触发器"""
        with self._lock:
            matches = [
                trigger
                for key, trigger in self._triggers.items()
                if key == name or trigger.name == name
            ]
            if matches:
                for trigger in matches:
                    trigger.enabled = False
                return True
            return False
    
    def get_triggers_for_session(self, session_id: str) -> List[TriggerDefinition]:
        """获取会话的触发器列表"""
        with self._lock:
            trigger_names = self._session_triggers.get(session_id, [])
            # 包含全局触发器（未绑定到特定会话的）
            bound_keys = {
                key
                for keys in self._session_triggers.values()
                for key in keys
            }
            global_triggers = [
                key for key in self._triggers
                if key not in bound_keys
            ]
            all_names = list(set(trigger_names + global_triggers))
            
            triggers = [self._triggers[name] for name in all_names if name in self._triggers]
            # 按优先级排序
            triggers.sort(key=lambda t: t.priority, reverse=True)
            return triggers
    
    def check_and_execute(
        self,
        data: Any,
        session_id: str
    ) -> List[ActionResult]:
        """
        检查触发条件并执行动作
        
        Args:
            data: 输入数据（AnalysisResult 或 MatchResult）
            session_id: 会话ID
        
        Returns:
            执行的动作结果列表
        """
        results = []
        triggers = self.get_triggers_for_session(session_id)
        
        for trigger in triggers:
            if not trigger.can_trigger():
                continue
            
            # 评估条件
            if TriggerEvaluator.evaluate(trigger.condition, data, trigger):
                # 执行动作
                result = self._executor.execute(trigger.action, session_id)
                results.append(result)

                # behavior_busy 表示另一个完整行为仍在播放；这次自动反馈
                # 没有真正发生，不能消耗一次性语音结果的 cooldown。后续
                # 分析结果可在互斥释放后重试。其他结果仍按历史语义计入
                # cooldown，避免配置/资源错误形成高频热循环。
                if result.success or result.error != 'behavior_busy':
                    trigger.mark_triggered()
                
                logger.info(
                    f"触发器已触发: {trigger.name}, "
                    f"session={session_id}, "
                    f"success={result.success}"
                )
        
        return results
    
    def check_match_result(
        self,
        match_result: MatchResult
    ) -> List[ActionResult]:
        """
        检查匹配结果并执行触发
        
        Args:
            match_result: 匹配结果
        
        Returns:
            执行的动作结果列表
        """
        return self.check_and_execute(match_result, match_result.session_id)
    
    def check_analysis_result(
        self,
        analysis_result: AnalysisResult
    ) -> List[ActionResult]:
        """
        检查分析结果并执行触发
        
        Args:
            analysis_result: 分析结果
        
        Returns:
            执行的动作结果列表
        """
        return self.check_and_execute(analysis_result, analysis_result.session_id)
    
    def clear_session_triggers(self, session_id: str) -> None:
        """清除会话的所有触发器"""
        with self._lock:
            if session_id in self._session_triggers:
                trigger_names = self._session_triggers[session_id]
                for name in trigger_names:
                    if name in self._triggers:
                        del self._triggers[name]
                del self._session_triggers[session_id]
                logger.info(f"清除会话触发器: session={session_id}")
    
    def list_triggers(self) -> List[Dict[str, Any]]:
        """列出所有触发器"""
        with self._lock:
            return [trigger.to_dict() for trigger in self._triggers.values()]
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取触发系统统计信息"""
        with self._lock:
            return {
                'total_triggers': len(self._triggers),
                'session_count': len(self._session_triggers),
                'triggers': {
                    name: {
                        'enabled': t.enabled,
                        'trigger_count': t.trigger_count,
                        'time_since_last': t.time_since_last_trigger
                    }
                    for name, t in self._triggers.items()
                }
            }


# ==================== 预定义触发器工厂 ====================

class TriggerFactory:
    """
    触发器工厂
    
    提供创建常用触发器的便捷方法
    """
    
    @staticmethod
    def pose_match_success(
        threshold: float = 0.95,
        cooldown: float = 3.0,
        praise_audio: str = "/static/resources/audio/praise.mp3"
    ) -> TriggerDefinition:
        """
        创建姿态匹配成功触发器
        
        仅在 MatchResult.passed=True 时触发。不要用 THRESHOLD_ABOVE 直接比
        score：Real 匹配器分数是 0–100，旧阈值 0.85/0.95 会把几乎任何分数
        都当成成功并误触发表扬。
        
        Args:
            threshold: 保留参数，供日志说明；实际以 matcher.passed 为准
            cooldown: 冷却时间
            praise_audio: 表扬音频路径
        
        Returns:
            TriggerDefinition
        """
        return TriggerDefinition(
            name="pose_match_success",
            condition=TriggerCondition(
                trigger_type=TriggerType.MATCH_SUCCESS,
                threshold=threshold,
                field_name="passed"
            ),
            action=ActionFactory.play_praise_audio(praise_audio),
            cooldown=cooldown,
            priority=10,
            description=f"姿态匹配成功（matcher.passed，参考阈值={threshold}）时播放表扬"
        )
    
    @staticmethod
    def speech_match_success(
        threshold: float = 0.90,
        cooldown: float = 8.0,
        praise_audio: str = "/static/resources/audio/praise.mp3"
    ) -> TriggerDefinition:
        """
        创建语音匹配成功触发器
        
        仅在 MatchResult.passed=True 时触发。旧实现用 score>=0.80，但 Real
        语音分是 0–100，导致 score=1 也会触发表扬。
        
        Args:
            threshold: 保留参数，供日志说明；实际以 matcher.passed 为准
            cooldown: 冷却时间
            praise_audio: 表扬音频路径
        
        Returns:
            TriggerDefinition
        """
        return TriggerDefinition(
            name="speech_match_success",
            condition=TriggerCondition(
                trigger_type=TriggerType.MATCH_SUCCESS,
                threshold=threshold,
                field_name="passed"
            ),
            action=ActionFactory.play_praise_audio(praise_audio),
            cooldown=cooldown,
            priority=10,
            description=f"语音匹配成功（matcher.passed，参考阈值={threshold}）时播放表扬"
        )
    
    @staticmethod
    def attention_low(
        threshold: float = 0.3,
        cooldown: float = 10.0,
        interest_content: str = "/static/resources/audio/interest.mp3"
    ) -> TriggerDefinition:
        """
        创建注意力低触发器
        
        当注意力低于阈值时，播放感兴趣内容
        
        Args:
            threshold: 注意力阈值
            cooldown: 冷却时间
            interest_content: 感兴趣内容路径
        
        Returns:
            TriggerDefinition
        """
        return TriggerDefinition(
            name="attention_low",
            condition=TriggerCondition(
                trigger_type=TriggerType.THRESHOLD_BELOW,
                threshold=threshold,
                field_name="score"
            ),
            action=ActionFactory.play_interest_content(interest_content),
            cooldown=cooldown,
            priority=5,
            description=f"注意力低于{threshold}时播放感兴趣内容"
        )
    
    @staticmethod
    def match_result_notify(
        cooldown: float = 0.5
    ) -> TriggerDefinition:
        """
        创建匹配结果通知触发器
        
        将匹配结果实时通知教师端
        
        Args:
            cooldown: 冷却时间（设置较短以保证实时性）
        
        Returns:
            TriggerDefinition
        """
        # 使用自定义条件：任何匹配结果都触发
        return TriggerDefinition(
            name="match_result_notify",
            condition=TriggerCondition(
                trigger_type=TriggerType.CUSTOM,
                custom_condition=lambda data: isinstance(data, MatchResult)
            ),
            action=ActionFactory.emit_to_therapist(
                'match_result',
                {}  # 实际数据会在执行时填充
            ),
            cooldown=cooldown,
            priority=1,
            description="将匹配结果通知教师端"
        )
    
    @staticmethod
    def consecutive_fail(
        fail_count: int = 3,
        cooldown: float = 5.0,
        hint_audio: str = "/static/resources/audio/hint.mp3"
    ) -> TriggerDefinition:
        """
        创建连续失败触发器
        
        连续N次匹配失败时，播放提示音频
        
        Args:
            fail_count: 连续失败次数
            cooldown: 冷却时间
            hint_audio: 提示音频路径
        
        Returns:
            TriggerDefinition
        """
        return TriggerDefinition(
            name="consecutive_fail",
            condition=TriggerCondition(
                trigger_type=TriggerType.MATCH_FAIL,
                count=fail_count
            ),
            action=ActionFactory.play_hint_audio(hint_audio),
            cooldown=cooldown,
            priority=8,
            description=f"连续{fail_count}次匹配失败时播放提示"
        )


# 全局触发系统实例
_trigger_system: Optional[TriggerSystem] = None
_trigger_system_lock = threading.Lock()


def get_trigger_system() -> TriggerSystem:
    """
    获取全局触发系统实例（单例模式）
    
    Returns:
        TriggerSystem实例
    """
    global _trigger_system
    if _trigger_system is None:
        with _trigger_system_lock:
            if _trigger_system is None:
                _trigger_system = TriggerSystem()
    return _trigger_system

