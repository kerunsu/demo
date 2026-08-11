"""
课程动作映射解析器
负责从多层级配置中查找匹配的动作和表情

查找优先级：项目级 > 学生-课程级 > 课程级 > 默认级
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
        'motionOffsetMs': _as_ms(raw.get('motionOffsetMs')),
        'audio': {
            'offsetMs': _as_ms(audio.get('offsetMs')),
        },
    }


def _default_emotion_name() -> str:
    """单一真相源：emotions_meta.json（缺省时回退目录内现存素材）。"""
    try:
        from app.robot.emotion_assets import get_default_emotion
        return get_default_emotion()
    except Exception:
        return 'v3_speak_excitedly_short.mp4'


class MappingResolver:
    """
    课程动作映射解析器
    
    支持四级映射配置：
    1. 项目级（最高优先级）：特定学生 + 课程 + 项目
    2. 学生-课程级：特定学生 + 课程
    3. 课程级：特定课程
    4. 默认级：通用动作
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
    
    def _load_course_map(self) -> Dict[str, Any]:
        """加载映射配置"""
        try:
            with open(self._course_map_file, 'r', encoding='utf-8') as f:
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
        if aux.get('praise') is True:
            return 'praise'
        if aux.get('hint') is True:
            return 'hint'
        if aux.get('question') is True:
            return 'question'
        if aux.get('socialGreetingIntro') is True:
            return 'social_greeting_intro'
        if aux.get('socialGreetingPlay') is True:
            return 'social_greeting_play'
        if aux.get('socialFarewellBye') is True:
            return 'social_farewell_bye'
        if aux.get('socialFarewellReply') is True:
            return 'social_farewell_reply'
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
        with self._map_lock:
            course_map = copy.deepcopy(self._course_map)

        sid = str(student_id) if student_id else None
        cid = str(course_id)
        iid = str(item_id) if item_id is not None else None
        
        # 1. 项目级（最高优先级）
        if sid and iid:
            data = self._get_nested(
                course_map,
                ['students', sid, cid, 'items', iid, aux_type]
            )
            if self._layer_has_config(data):
                logger.debug(f"✓ 找到项目级映射: student={sid}, course={cid}, item={iid}, type={aux_type}")
                return self._normalize_action_data(data)
        
        # 2. 学生-课程级
        if sid:
            data = self._get_nested(
                course_map,
                ['students', sid, cid, aux_type]
            )
            if self._layer_has_config(data):
                logger.debug(f"✓ 找到学生-课程级映射: student={sid}, course={cid}, type={aux_type}")
                return self._normalize_action_data(data)
        
        # 3. 课程级
        data = self._get_nested(
            course_map,
            ['courses', cid, aux_type]
        )
        if self._layer_has_config(data):
            logger.debug(f"✓ 找到课程级映射: course={cid}, type={aux_type}")
            return self._normalize_action_data(data)
        
        # 4. 默认级（允许 silent：无动作但有 emotion）
        data = self._get_nested(
            course_map,
            ['defaults', aux_type]
        )
        if self._layer_has_config(data):
            logger.debug(f"✓ 找到默认级映射: type={aux_type}")
            return self._normalize_action_data(data)
        
        logger.warning(f"⚠️ 未找到匹配映射: student={sid}, course={cid}, item={iid}, type={aux_type}")
        return {
            "motions": [],
            "emotion": _default_emotion_name(),
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
    
    def _normalize_action_data(self, data: Any) -> Dict[str, Any]:
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
                "motions": data,
                "emotion": _default_emotion_name(),
                "animation": "",
                "sequence": _normalize_sequence({}),
            }
        elif isinstance(data, dict):
            # 新格式：确保字段完整（勿原地污染 course_map）
            out = {
                "motions": list(data.get("motions") or []),
                "emotion": data.get("emotion") or _default_emotion_name(),
                "animation": str(data.get("animation") or "").strip(),
                "sequence": _normalize_sequence(data.get("sequence")),
            }
            return out
        else:
            return {"motions": [], "emotion": _default_emotion_name(), "animation": "", "sequence": _normalize_sequence({})}
    
    def select_motion(self, motions: List[str]) -> Optional[str]:
        """
        从动作列表中随机选择一个
        
        Args:
            motions: 动作名称列表
            
        Returns:
            选中的动作名称
        """
        if not motions or len(motions) == 0:
            return None
        if len(motions) == 1:
            return motions[0]
        
        return random.choice(motions)
    
    # ========== 静态姿势 ==========
    
    def get_idle_pose(self) -> Optional[str]:
        """获取静态姿势动作名称"""
        with self._map_lock:
            return self._course_map.get('defaults', {}).get('idle')
    
    def set_idle_pose(self, motion_name: str) -> None:
        """设置静态姿势"""
        with self._map_lock:
            if 'defaults' not in self._course_map:
                self._course_map['defaults'] = {}
            self._course_map['defaults']['idle'] = motion_name
            self._save_course_map()
    
    # ========== 通用动作 CRUD ==========
    
    def update_default_motions(self, aux_type: str, motions: List[str], emotion: Optional[str] = None, sequence: Optional[Dict[str, Any]] = None, animation: Optional[str] = None) -> None:
        """更新通用动作（支持新格式：motions + emotion）"""
        with self._map_lock:
            if 'defaults' not in self._course_map:
                self._course_map['defaults'] = {}
            action_data = {
                'motions': motions or [],
                'emotion': emotion or _default_emotion_name(),
                'animation': str(animation or '').strip(),
                'sequence': _normalize_sequence(sequence),
            }
            self._course_map['defaults'][aux_type] = action_data
            self._save_course_map()
    
    def delete_default_motions(self, aux_type: str) -> None:
        """删除通用动作"""
        with self._map_lock:
            if 'defaults' in self._course_map and aux_type in self._course_map['defaults']:
                del self._course_map['defaults'][aux_type]
                self._save_course_map()
    
    # ========== 课程级动作 CRUD ==========
    
    def update_course_motions(self, course_id: int, aux_type: str, motions: List[str], emotion: Optional[str] = None, sequence: Optional[Dict[str, Any]] = None, animation: Optional[str] = None) -> None:
        """更新课程级动作（支持新格式：motions + emotion）"""
        cid = str(course_id)
        with self._map_lock:
            if 'courses' not in self._course_map:
                self._course_map['courses'] = {}
            if cid not in self._course_map['courses']:
                self._course_map['courses'][cid] = {}
            action_data = {
                'motions': motions or [],
                'emotion': emotion or _default_emotion_name(),
                'animation': str(animation or '').strip(),
                'sequence': _normalize_sequence(sequence),
            }
            self._course_map['courses'][cid][aux_type] = action_data
            self._save_course_map()
    
    def delete_course_motions(self, course_id: int, aux_type: str) -> None:
        """删除课程级动作"""
        cid = str(course_id)
        with self._map_lock:
            if self._get_nested(self._course_map, ['courses', cid, aux_type]):
                del self._course_map['courses'][cid][aux_type]
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
    ) -> None:
        """更新学生-课程级动作（支持新格式：motions + emotion）"""
        sid = str(student_id)
        cid = str(course_id)
        
        with self._map_lock:
            if 'students' not in self._course_map:
                self._course_map['students'] = {}
            if sid not in self._course_map['students']:
                self._course_map['students'][sid] = {}
            if cid not in self._course_map['students'][sid]:
                self._course_map['students'][sid][cid] = {}
            action_data = {
                'motions': motions or [],
                'emotion': emotion or _default_emotion_name(),
                'animation': str(animation or '').strip(),
                'sequence': _normalize_sequence(sequence),
            }
            self._course_map['students'][sid][cid][aux_type] = action_data
            self._save_course_map()
    
    def delete_student_course_motions(
        self, 
        student_id: int, 
        course_id: int, 
        aux_type: str
    ) -> None:
        """删除学生-课程级动作"""
        sid = str(student_id)
        cid = str(course_id)
        
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
    ) -> None:
        """更新项目级动作（支持新格式：motions + emotion）"""
        sid = str(student_id)
        cid = str(course_id)
        iid = str(item_id)
        
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
            action_data = {
                'motions': motions or [],
                'emotion': emotion or _default_emotion_name(),
                'animation': str(animation or '').strip(),
                'sequence': _normalize_sequence(sequence),
            }
            self._course_map['students'][sid][cid]['items'][iid][aux_type] = action_data
            self._save_course_map()
    
    def delete_item_motions(
        self, 
        student_id: int, 
        course_id: int, 
        item_id: int, 
        aux_type: str
    ) -> None:
        """删除项目级动作"""
        sid = str(student_id)
        cid = str(course_id)
        iid = str(item_id)
        
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
        return mapping.get('emotion', _default_emotion_name())
    
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
        with self._map_lock:
            return copy.deepcopy(self._course_map)
