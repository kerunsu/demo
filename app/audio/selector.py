"""
语音选择器 - 根据策略选择具体文件
支持随机、顺序、加权、上下文感知等选择策略
"""
import random
from typing import Optional, List, Dict
from collections import defaultdict
from app.utils.logger import setup_logger
from .models import (
    AudioEntry,
    AudioFile,
    AudioContext,
    SelectionStrategy
)
from .registry import AudioRegistry

logger = setup_logger('audio.selector')


class AudioSelector:
    """语音选择器 - 根据策略选择具体文件"""
    
    def __init__(self, registry: AudioRegistry):
        """
        初始化选择器
        
        Args:
            registry: 语音注册表实例
        """
        self.registry = registry
        
        # 播放历史 {entry_id: [file_indices]}
        self._play_history: Dict[str, List[int]] = defaultdict(list)
        
        # 顺序播放计数器 {entry_id: next_index}
        self._sequential_counters: Dict[str, int] = defaultdict(int)
    
    def select(
        self, 
        entry_id: str, 
        context: Optional[AudioContext] = None,
        file_type: str = 'files'  # 'files' | 'question_files' | 'answer_files'
    ) -> Optional[str]:
        """
        选择一个语音文件路径
        
        Args:
            entry_id: 语音条目ID或别名
            context: 上下文（课程类型、学生ID等）
            file_type: 文件类型（用于拟声课程区分提问/回答）
        
        Returns:
            语音文件相对路径，如 "resources/audios/301/1/1.mp3"
            如果找不到，返回 None
        """
        # 获取语音条目
        entry = self.registry.get_entry(entry_id)
        if not entry:
            logger.warning(f"语音条目不存在: {entry_id}")
            return None
        
        # 获取对应的文件列表
        files = self._get_files_by_type(entry, file_type)
        if not files:
            logger.warning(f"语音条目 {entry_id} 没有 {file_type} 文件")
            return None
        
        # 应用选择策略
        file_index = self._apply_strategy(entry, files, context)
        if file_index is None or file_index >= len(files):
            logger.error(f"选择策略返回无效索引: {file_index}")
            return None
        
        # 记录播放历史
        self._record_play(entry.entry_id, file_index)
        
        # 获取文件路径（支持 folder/ → 目录内随机选音频）
        selected_file = files[file_index]
        full_path = selected_file.get_full_path(self.registry.get_base_path())
        from app.utils.resource_utils import resolve_playable_audio_path
        resolved = resolve_playable_audio_path(full_path)
        if not resolved:
            logger.warning(
                f"语音路径无法解析为可播文件: entry={entry_id}, path={full_path}"
            )
            return None

        logger.debug(
            f"选择语音: {entry_id} -> {resolved} "
            f"(策略: {entry.selection.value}, raw={full_path})"
        )
        return resolved
    
    def _get_files_by_type(self, entry: AudioEntry, file_type: str) -> List[AudioFile]:
        """获取指定类型的文件列表"""
        if file_type == 'question_files':
            return entry.question_files
        elif file_type == 'answer_files':
            return entry.answer_files
        else:
            return entry.files
    
    def _apply_strategy(
        self, 
        entry: AudioEntry, 
        files: List[AudioFile],
        context: Optional[AudioContext]
    ) -> Optional[int]:
        """
        应用选择策略，返回文件索引
        
        Args:
            entry: 语音条目
            files: 文件列表
            context: 上下文
        
        Returns:
            文件索引，或 None
        """
        strategy = entry.selection
        
        if strategy == SelectionStrategy.RANDOM:
            return self._select_random(entry, files)
        elif strategy == SelectionStrategy.SEQUENTIAL:
            return self._select_sequential(entry, files)
        elif strategy == SelectionStrategy.WEIGHTED:
            return self._select_weighted(entry, files)
        elif strategy == SelectionStrategy.CONTEXT_AWARE:
            return self._select_context_aware(entry, files, context)
        else:
            logger.warning(f"未知选择策略: {strategy}")
            return self._select_random(entry, files)
    
    def _select_random(self, entry: AudioEntry, files: List[AudioFile]) -> int:
        """
        随机选择策略（带冷却机制）
        
        避免短时间内重复播放相同文件
        """
        if len(files) == 1:
            return 0
        
        # 获取播放历史
        history = self._play_history.get(entry.entry_id, [])
        cooldown = entry.cooldown
        
        # 如果设置了冷却，排除最近播放的文件
        if cooldown > 0 and history:
            recent_indices = set(history[-cooldown:])
            available_indices = [i for i in range(len(files)) if i not in recent_indices]
            
            # 如果有可用的，从可用中随机选择
            if available_indices:
                return random.choice(available_indices)
        
        # 否则完全随机
        return random.randint(0, len(files) - 1)
    
    def _select_sequential(self, entry: AudioEntry, files: List[AudioFile]) -> int:
        """
        顺序播放策略
        
        按顺序循环播放所有文件
        """
        entry_id = entry.entry_id
        current_index = self._sequential_counters[entry_id]
        
        # 更新计数器
        self._sequential_counters[entry_id] = (current_index + 1) % len(files)
        
        return current_index
    
    def _select_weighted(self, entry: AudioEntry, files: List[AudioFile]) -> int:
        """
        加权选择策略
        
        根据文件的 weight 属性进行加权随机选择
        """
        # 提取权重
        weights = [f.weight for f in files]
        
        # 如果所有权重都相同，退化为随机选择
        if len(set(weights)) == 1:
            return self._select_random(entry, files)
        
        # 加权随机选择
        total_weight = sum(weights)
        rand_val = random.uniform(0, total_weight)
        
        cumulative = 0
        for i, weight in enumerate(weights):
            cumulative += weight
            if rand_val <= cumulative:
                return i
        
        # 兜底
        return len(files) - 1
    
    def _select_context_aware(
        self, 
        entry: AudioEntry, 
        files: List[AudioFile],
        context: Optional[AudioContext]
    ) -> int:
        """
        上下文感知选择策略
        
        TODO: 根据学生ID、课程类型、时间等上下文信息智能选择
        目前暂时使用加权策略
        """
        # 未来可以实现更复杂的逻辑，比如：
        # - 根据学生偏好调整权重
        # - 根据时间段选择不同风格
        # - 根据最近表现调整鼓励程度
        
        logger.debug(f"上下文感知选择（当前使用加权策略）: {context}")
        return self._select_weighted(entry, files)
    
    def _record_play(self, entry_id: str, file_index: int):
        """记录播放历史"""
        self._play_history[entry_id].append(file_index)
        
        # 限制历史长度，避免内存占用过大
        max_history = 100
        if len(self._play_history[entry_id]) > max_history:
            self._play_history[entry_id] = self._play_history[entry_id][-max_history:]
    
    # ========== 便捷接口 ==========
    
    def select_for_course(
        self,
        course_type: str,
        audio_type: str,  # 'question' | 'praise' | 'hint'
        item_id: Optional[int] = None,
        context: Optional[AudioContext] = None
    ) -> Optional[str]:
        """
        为课程选择语音（兼容旧接口）
        
        Args:
            course_type: 课程类型，如 "naming", "mimic"
            audio_type: 语音类型，如 "question", "praise", "hint"
            item_id: 课程项ID（可选，用于特定项的专属语音）
            context: 上下文
        
        Returns:
            语音文件路径，或 None
        """
        # 获取课程默认语音条目ID
        entry_id = self.registry.get_course_default(course_type, audio_type)

        # 排序八问未单独配置时回退到通用 question
        if (
            not entry_id
            and course_type == 'ordering'
            and isinstance(audio_type, str)
            and audio_type.startswith('question_')
        ):
            entry_id = self.registry.get_course_default(course_type, 'question')
        
        if not entry_id:
            logger.warning(f"课程 {course_type} 没有配置 {audio_type} 默认语音")
            # 尝试使用通用别名
            entry_id = audio_type
        
        return self.select(entry_id, context)
    
    def select_vocalization(
        self,
        animal_name: str,
        is_question: bool = True,
        context: Optional[AudioContext] = None
    ) -> Optional[str]:
        """
        为拟声课程选择语音
        
        Args:
            animal_name: 动物名称，如 "cat", "dog"
            is_question: 是否是提问语音（True=提问，False=回答）
            context: 上下文
        
        Returns:
            语音文件路径，或 None
        """
        entry_id = f"vocalization_{animal_name}"
        file_type = 'question_files' if is_question else 'answer_files'
        
        return self.select(entry_id, context, file_type)
    
    def get_play_history(self, entry_id: str, limit: int = 10) -> List[int]:
        """
        获取播放历史
        
        Args:
            entry_id: 语音条目ID
            limit: 返回最近N条
        
        Returns:
            文件索引列表
        """
        history = self._play_history.get(entry_id, [])
        return history[-limit:]
    
    def reset_history(self, entry_id: Optional[str] = None):
        """
        重置播放历史
        
        Args:
            entry_id: 如果指定，只重置该条目；否则重置所有
        """
        if entry_id:
            self._play_history.pop(entry_id, None)
            self._sequential_counters.pop(entry_id, None)
            logger.info(f"重置播放历史: {entry_id}")
        else:
            self._play_history.clear()
            self._sequential_counters.clear()
            logger.info("重置所有播放历史")


# 全局实例
_selector_instance: Optional[AudioSelector] = None


def get_audio_selector() -> AudioSelector:
    """获取语音选择器单例"""
    global _selector_instance
    
    if _selector_instance is None:
        from .registry import get_audio_registry
        registry = get_audio_registry()
        _selector_instance = AudioSelector(registry)
    
    return _selector_instance
