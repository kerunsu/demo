"""
课程表情映射解析器
负责从三层配置中查找匹配的表情和儿童屏幕动画。

查找优先级：课点级 > 课程级 > 全局默认级
"""
import json
import os
import random
import copy
import tempfile
import threading
from typing import Dict, List, Optional, Any, Tuple

from app.robot.config import COURSE_MAP_FILE
from app.config import Config
from app.utils.logger import setup_logger

logger = setup_logger('mapping_resolver')


def _as_ms(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _normalize_sequence(data: Any) -> Dict[str, Any]:
    """标准化行为内的表情主时间轴配置。"""
    raw = data if isinstance(data, dict) else {}
    audio = raw.get('audio') if isinstance(raw.get('audio'), dict) else {}
    return {
        # 表情资源为空时，运行时会回退 emotion 字段或导入动作携带的 mediaId。
        'expressionMediaId': str(raw.get('expressionMediaId') or '').strip(),
        # 0 表示由 GIF / 导入 JSON 元数据推断；MP4 请在控制端填写实际时长。
        'expressionDurationMs': _as_ms(raw.get('expressionDurationMs')),
        'audio': {
            'offsetMs': _as_ms(audio.get('offsetMs')),
        },
    }


def _default_emotion_name() -> str:
    """Use the same reviewed expression default as the main product."""
    try:
        from app.robot.emotion_assets import get_default_emotion
        return get_default_emotion()
    except Exception:
        return 'v4_idle.mp4'


def _normalize_emotion_pool(value: Any) -> List[str]:
    """Return a stable, duplicate-free list of expression filenames."""
    if not isinstance(value, list):
        return []
    normalized: List[str] = []
    for raw_name in value:
        name = str(raw_name or '').strip()
        if name and name not in normalized:
            normalized.append(name)
    return normalized


class MappingResolver:
    """
    课程动作映射解析器
    
    支持三级映射配置：
    1. 课点级（最高优先级）：特定课程 + 课点
    2. 课程级：特定课程
    3. 全局默认级：所有课程的兜底

    ``students`` 旧节点只为数据安全保留，不再参与运行时解析。
    """
    
    def __init__(self, course_map_file: str = COURSE_MAP_FILE):
        """
        初始化映射解析器
        
        Args:
            course_map_file: 映射配置文件路径
        """
        self._course_map_file = course_map_file
        self._map_lock = threading.RLock()
        self._course_map: Dict[str, Any] = self._load_course_map()
        self._course_map_signature = self._file_signature()

    def _file_signature(self) -> Optional[Tuple[int, int]]:
        try:
            stat = os.stat(self._course_map_file)
            return (int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            return None

    def _refresh_from_disk_if_changed(self) -> None:
        """Refresh a long-lived resolver after an atomic config deployment."""
        with self._map_lock:
            signature = self._file_signature()
            if signature is None or signature == self._course_map_signature:
                return
            loaded = self._load_course_map()
            if not isinstance(loaded, dict):
                raise ValueError('invalid_course_map')
            self._course_map = loaded
            self._course_map_signature = signature
            logger.info('course_map.json changed on disk; refreshed mapping snapshot')
    
    def _load_course_map(self) -> Dict[str, Any]:
        """加载映射配置"""
        try:
            # utf-8-sig accepts both regular UTF-8 and files saved with a
            # Windows UTF-8 BOM, avoiding a silent fallback to an empty map.
            with open(self._course_map_file, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载 course_map.json 失败: {e}")
            return {'defaults': {}, 'courses': {}, 'students': {}}
    
    def _save_course_map(self) -> None:
        """同目录原子替换映射配置，避免读取方看到只写了一半的 JSON。"""
        temp_path = None
        try:
            target_dir = os.path.dirname(os.path.abspath(self._course_map_file))
            os.makedirs(target_dir, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=target_dir,
                prefix='.course_map.',
                suffix='.tmp',
                delete=False,
            ) as f:
                temp_path = f.name
                json.dump(self._course_map, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self._course_map_file)
            temp_path = None
            self._course_map_signature = self._file_signature()
        except Exception as e:
            logger.error(f"保存 course_map.json 失败: {e}")
            raise
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
    
    def reload(self) -> None:
        """重新加载配置"""
        loaded = self._load_course_map()
        with self._map_lock:
            self._course_map = loaded
            self._course_map_signature = self._file_signature()
    
    def parse_aux_type(self, aux: Optional[Dict[str, bool]]) -> str:
        """
        解析 aux 对象，确定动作类型
        
        Args:
            aux: {question: bool, praise: bool, hint: bool, social*: bool}
            
        Returns:
            'praise' | 'hint' | 'question' | 'silent' | social_* 槽名
        """
        if not aux:
            return 'silent'
        if aux.get('attention') is True:
            return 'attention'
        if aux.get('reward') is True:
            return 'reward'
        if aux.get('praise') is True:
            return 'praise'
        if aux.get('hint') is True:
            return 'hint'
        if aux.get('socialGreetingIntro') is True:
            return 'social_greeting_intro'
        if aux.get('socialGreetingPlay') is True:
            return 'social_greeting_play'
        if aux.get('socialFarewellBye') is True:
            return 'social_farewell_bye'
        if aux.get('socialFarewellReply') is True:
            return 'social_farewell_reply'
        if aux.get('question') is True:
            return 'question'
        return 'silent'
    
    def find_motions(
        self, 
        student_id: Optional[int], 
        course_id: int, 
        item_id: Optional[int], 
        aux_type: str
    ) -> List[str]:
        """
        查找匹配的动作列表（按优先级）
        
        Args:
            student_id: 学生 ID
            course_id: 课程 ID
            item_id: 项目 ID（可选）
            aux_type: 动作类型 ('praise' | 'hint' | 'question' | 'silent')
            
        Returns:
            动作名称列表
        """
        mapping = self.find_mapping(student_id, course_id, item_id, aux_type)
        return mapping.get('motions', [])
    
    def find_mapping(
        self, 
        student_id: Optional[int], 
        course_id: int, 
        item_id: Optional[int], 
        aux_type: str
    ) -> Dict[str, Any]:
        """
        查找匹配的动作和表情（按优先级）
        
        Args:
            student_id: 学生 ID
            course_id: 课程 ID
            item_id: 项目 ID（可选）
            aux_type: 动作类型 ('praise' | 'hint' | 'question' | 'silent')
            
        Returns:
            {"motions": [...], "emotion": "...", "sequence": {...}}
        """
        self._refresh_from_disk_if_changed()
        with self._map_lock:
            course_map = copy.deepcopy(self._course_map)

        cid = str(course_id)
        iid = str(item_id) if item_id is not None else None
        
        # 1. 课点级（最高优先级）
        if iid:
            data = self._get_nested(
                course_map,
                ['courses', cid, 'items', iid, aux_type]
            )
            if self._layer_has_config(data):
                logger.debug(f"✓ 找到课点级映射: course={cid}, item={iid}, type={aux_type}")
                return self._normalize_action_data(data, aux_type)

        # 2. 课程级
        data = self._get_nested(
            course_map,
            ['courses', cid, aux_type]
        )
        if self._layer_has_config(data):
            logger.debug(f"✓ 找到课程级映射: course={cid}, type={aux_type}")
            return self._normalize_action_data(data, aux_type)
        
        # 3. 全局默认级（允许 silent：无动作但有 emotion）
        data = self._get_nested(
            course_map,
            ['defaults', aux_type]
        )
        if self._layer_has_config(data):
            logger.debug(f"✓ 找到默认级映射: type={aux_type}")
            return self._normalize_action_data(data, aux_type)
        
        logger.warning(f"⚠️ 未找到匹配映射: course={cid}, item={iid}, type={aux_type}")
        return {
            "motions": [],
            "emotion": _default_emotion_name(),
            "emotions": [],
            "animation": "",
            "sequence": _normalize_sequence({}),
        }
    
    def _layer_has_config(self, data: Any) -> bool:
        """
        判断该层是否有有效覆盖。
        - 空数组 []：旧格式「未配置」，不算命中（继续向下找）
        - 非空动作列表：命中
        - 对象含非空 motions，或显式 emotion：命中（支持 silent 仅表情）
        """
        if data is None:
            return False
        if isinstance(data, list):
            return len(data) > 0
        if isinstance(data, dict):
            motions = data.get('motions')
            if isinstance(motions, list) and len(motions) > 0:
                return True
            emotion = data.get('emotion')
            if isinstance(emotion, str) and emotion.strip():
                return True
            emotions = data.get('emotions')
            if isinstance(emotions, list) and any(str(item or '').strip() for item in emotions):
                return True
            animation = data.get('animation')
            if isinstance(animation, str) and animation.strip():
                return True
            return False
        return False
    
    def _get_nested(self, data: Dict, keys: List[str]) -> Any:
        """安全获取嵌套字典值"""
        current = data
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current
    
    def _normalize_action_data(self, data: Any, aux_type: str = '') -> Dict[str, Any]:
        """
        归一化动作数据格式（向下兼容）
        
        旧格式（数组）：["动作1", "动作2"]
        新格式（对象）：{"motions": ["动作1"], "emotion": "003_Happy.gif"}
        
        Args:
            data: 原始数据（可能是数组或对象）
            
        Returns:
            归一化后的对象格式
        """
        if isinstance(data, list):
            # 旧格式：数组 → 转为对象（表情走库默认）
            return {
                "motions": [],
                "emotion": _default_emotion_name(),
                "emotions": [],
                "animation": "",
                "sequence": _normalize_sequence({}),
            }
        elif isinstance(data, dict):
            # 新格式：确保字段完整（勿原地污染 course_map）
            emotion_pool = (
                _normalize_emotion_pool(data.get('emotions'))
                if aux_type == 'praise' else []
            )
            out = {
                "motions": [],
                "emotion": (
                    str(data.get('emotion') or '').strip()
                    or (emotion_pool[0] if emotion_pool else _default_emotion_name())
                ),
                "emotions": emotion_pool,
                "animation": str(data.get("animation") or "").strip(),
                "sequence": _normalize_sequence(data.get("sequence")),
            }
            return out
        else:
            return {"motions": [], "emotion": _default_emotion_name(), "emotions": [], "animation": "", "sequence": _normalize_sequence({})}
    
    def select_motion(self, motions: List[str]) -> Optional[str]:
        """
        从动作列表中随机选择一个
        
        Args:
            motions: 动作名称列表
            
        Returns:
            选中的动作名称
        """
        # Demo 没有机械结构；保留兼容方法但绝不选择动作。
        return None

    def select_emotion(self, mapping: Any) -> str:
        """表扬事件从配置池随机取一个，其他事件保持固定表情。"""
        data = mapping if isinstance(mapping, dict) else {}
        pool = _normalize_emotion_pool(data.get('emotions'))
        if pool:
            return random.choice(pool)
        return str(data.get('emotion') or _default_emotion_name()).strip()

    @staticmethod
    def _build_action_data(
        aux_type: str,
        emotion: Optional[str],
        sequence: Optional[Dict[str, Any]],
        animation: Optional[str],
        emotions: Optional[List[str]],
    ) -> Dict[str, Any]:
        """只落盘表情/儿童动画绑定，丢弃所有机械动作输入。"""
        if emotions is not None and not isinstance(emotions, list):
            raise ValueError('emotions must be an array')
        pool = _normalize_emotion_pool(emotions)
        if pool and aux_type != 'praise':
            raise ValueError('random emotion pool is only supported for praise')
        if pool and len(pool) < 2:
            raise ValueError('praise random emotion pool must contain at least two emotions')
        fixed = str(emotion or '').strip()
        if pool and fixed not in pool:
            fixed = pool[0]
        action_data = {
            'emotion': fixed or _default_emotion_name(),
            'animation': str(animation or '').strip(),
            'sequence': _normalize_sequence(sequence),
        }
        if pool:
            action_data['emotions'] = pool
        return action_data
    
    # ========== 静态姿势 ==========
    
    def get_idle_pose(self) -> Optional[str]:
        """获取静态姿势动作名称"""
        return None
    
    def set_idle_pose(self, motion_name: str) -> None:
        """设置静态姿势"""
        return None
    
    # ========== 通用动作 CRUD ==========
    
    def update_default_motions(self, aux_type: str, motions: List[str], emotion: Optional[str] = None, sequence: Optional[Dict[str, Any]] = None, animation: Optional[str] = None, emotions: Optional[List[str]] = None) -> None:
        """更新通用表情；motions 参数仅为旧调用方兼容且始终被忽略。"""
        self._refresh_from_disk_if_changed()
        with self._map_lock:
            if 'defaults' not in self._course_map:
                self._course_map['defaults'] = {}
            action_data = self._build_action_data(aux_type, emotion, sequence, animation, emotions)
            self._course_map['defaults'][aux_type] = action_data
            self._save_course_map()
    
    def delete_default_motions(self, aux_type: str) -> None:
        """删除通用表情绑定。"""
        self._refresh_from_disk_if_changed()
        with self._map_lock:
            if 'defaults' in self._course_map and aux_type in self._course_map['defaults']:
                del self._course_map['defaults'][aux_type]
                self._save_course_map()
    
    # ========== 课程级动作 CRUD ==========
    
    def update_course_motions(self, course_id: int, aux_type: str, motions: List[str], emotion: Optional[str] = None, sequence: Optional[Dict[str, Any]] = None, animation: Optional[str] = None, emotions: Optional[List[str]] = None) -> None:
        """更新课程级表情绑定。"""
        cid = str(course_id)
        self._refresh_from_disk_if_changed()
        with self._map_lock:
            if 'courses' not in self._course_map:
                self._course_map['courses'] = {}
            if cid not in self._course_map['courses']:
                self._course_map['courses'][cid] = {}
            action_data = self._build_action_data(aux_type, emotion, sequence, animation, emotions)
            self._course_map['courses'][cid][aux_type] = action_data
            self._save_course_map()
    
    def delete_course_motions(self, course_id: int, aux_type: str) -> None:
        """删除课程级表情绑定。"""
        cid = str(course_id)
        self._refresh_from_disk_if_changed()
        with self._map_lock:
            if self._get_nested(self._course_map, ['courses', cid, aux_type]):
                del self._course_map['courses'][cid][aux_type]
                self._save_course_map()

    # ========== 课点级动作 CRUD（三级模型） ==========

    def update_course_item_motions(
        self,
        course_id: int,
        item_id: int,
        aux_type: str,
        motions: List[str],
        emotion: Optional[str] = None,
        sequence: Optional[Dict[str, Any]] = None,
        animation: Optional[str] = None,
        emotions: Optional[List[str]] = None,
    ) -> None:
        """更新课程课点覆盖；未配置字段继续由课程/全局层兜底。"""
        cid, iid = str(course_id), str(item_id)
        self._refresh_from_disk_if_changed()
        with self._map_lock:
            courses = self._course_map.setdefault('courses', {})
            course = courses.setdefault(cid, {})
            items = course.setdefault('items', {})
            item = items.setdefault(iid, {})
            item[aux_type] = self._build_action_data(
                aux_type, emotion, sequence, animation, emotions,
            )
            self._save_course_map()

    def delete_course_item_motions(
        self,
        course_id: int,
        item_id: int,
        aux_type: str,
    ) -> None:
        cid, iid = str(course_id), str(item_id)
        self._refresh_from_disk_if_changed()
        with self._map_lock:
            item = self._get_nested(self._course_map, ['courses', cid, 'items', iid])
            if isinstance(item, dict) and aux_type in item:
                del item[aux_type]
                self._save_course_map()
    
    # ========== 学生-课程级动作 CRUD ==========
    
    def update_student_course_motions(
        self, 
        student_id: int, 
        course_id: int, 
        aux_type: str, 
        motions: List[str],
        emotion: Optional[str] = None,
        sequence: Optional[Dict[str, Any]] = None,
        animation: Optional[str] = None,
        emotions: Optional[List[str]] = None,
    ) -> None:
        """更新学生-课程级表情绑定。"""
        sid = str(student_id)
        cid = str(course_id)

        self._refresh_from_disk_if_changed()
        with self._map_lock:
            if 'students' not in self._course_map:
                self._course_map['students'] = {}
            if sid not in self._course_map['students']:
                self._course_map['students'][sid] = {}
            if cid not in self._course_map['students'][sid]:
                self._course_map['students'][sid][cid] = {}
            action_data = self._build_action_data(aux_type, emotion, sequence, animation, emotions)
            self._course_map['students'][sid][cid][aux_type] = action_data
            self._save_course_map()
    
    def delete_student_course_motions(
        self, 
        student_id: int, 
        course_id: int, 
        aux_type: str
    ) -> None:
        """删除学生-课程级表情绑定。"""
        sid = str(student_id)
        cid = str(course_id)

        self._refresh_from_disk_if_changed()
        with self._map_lock:
            if self._get_nested(self._course_map, ['students', sid, cid, aux_type]):
                del self._course_map['students'][sid][cid][aux_type]
                self._save_course_map()
    
    # ========== 项目级动作 CRUD ==========
    
    def update_item_motions(
        self, 
        student_id: int, 
        course_id: int, 
        item_id: int, 
        aux_type: str, 
        motions: List[str],
        emotion: Optional[str] = None,
        sequence: Optional[Dict[str, Any]] = None,
        animation: Optional[str] = None,
        emotions: Optional[List[str]] = None,
    ) -> None:
        """更新项目级表情绑定。"""
        sid = str(student_id)
        cid = str(course_id)
        iid = str(item_id)

        self._refresh_from_disk_if_changed()
        with self._map_lock:
            if 'students' not in self._course_map:
                self._course_map['students'] = {}
            if sid not in self._course_map['students']:
                self._course_map['students'][sid] = {}
            if cid not in self._course_map['students'][sid]:
                self._course_map['students'][sid][cid] = {'items': {}}
            if 'items' not in self._course_map['students'][sid][cid]:
                self._course_map['students'][sid][cid]['items'] = {}
            if iid not in self._course_map['students'][sid][cid]['items']:
                self._course_map['students'][sid][cid]['items'][iid] = {}
            action_data = self._build_action_data(aux_type, emotion, sequence, animation, emotions)
            self._course_map['students'][sid][cid]['items'][iid][aux_type] = action_data
            self._save_course_map()
    
    def delete_item_motions(
        self, 
        student_id: int, 
        course_id: int, 
        item_id: int, 
        aux_type: str
    ) -> None:
        """删除项目级表情绑定。"""
        sid = str(student_id)
        cid = str(course_id)
        iid = str(item_id)

        self._refresh_from_disk_if_changed()
        with self._map_lock:
            if self._get_nested(self._course_map, ['students', sid, cid, 'items', iid, aux_type]):
                del self._course_map['students'][sid][cid]['items'][iid][aux_type]
                self._save_course_map()
    
    # ========== 表情相关方法 ==========
    
    def find_emotion(
        self, 
        student_id: Optional[int], 
        course_id: int, 
        item_id: Optional[int], 
        aux_type: str
    ) -> str:
        """
        查找匹配的表情（按优先级）
        
        Args:
            student_id: 学生 ID
            course_id: 课程 ID
            item_id: 项目 ID（可选）
            aux_type: 动作类型
            
        Returns:
            表情文件名（如 "003_Happy.gif"）
        """
        mapping = self.find_mapping(student_id, course_id, item_id, aux_type)
        return self.select_emotion(mapping)
    
    def get_available_emotions(self) -> List[str]:
        """
        获取所有可用的表情文件列表
        
        Returns:
            表情文件名列表
        """
        emotions_dir = os.path.join(Config.STATIC_DIR, 'resources', 'Emotions')
        
        if not os.path.exists(emotions_dir):
            logger.warning(f"表情目录不存在: {emotions_dir}")
            return []
        
        try:
            files = [f for f in os.listdir(emotions_dir) if f.endswith('.mp4')]
            files.sort()
            logger.debug(f"找到 {len(files)} 个表情文件")
            return files
        except Exception as e:
            logger.error(f"读取表情目录失败: {e}")
            return []
    
    # ========== 获取完整配置 ==========
    
    def get_full_mapping(self) -> Dict[str, Any]:
        """获取完整配置（用于前端显示）"""
        self._refresh_from_disk_if_changed()
        with self._map_lock:
            return copy.deepcopy(self._course_map)
