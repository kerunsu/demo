"""
语音注册表 - 管理所有语音条目
从 YAML 配置文件加载语音清单，提供查询接口
"""
import yaml
from pathlib import Path
from typing import Dict, List, Optional
from app.utils.logger import setup_logger
from .models import (
    AudioEntry, 
    AudioFile, 
    AudioManifest, 
    SelectionStrategy
)

logger = setup_logger('audio.registry')


class AudioRegistry:
    """语音注册表 - 单例模式"""
    
    _instance: Optional['AudioRegistry'] = None
    
    def __init__(self):
        """初始化注册表"""
        self._manifest: Optional[AudioManifest] = None
        self._loaded = False
    
    @classmethod
    def get_instance(cls) -> 'AudioRegistry':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance.load_manifest()
        return cls._instance
    
    def load_manifest(self, config_path: str = 'config/audio_manifest.yaml') -> bool:
        """
        加载语音清单配置
        
        Args:
            config_path: 配置文件路径
        
        Returns:
            是否加载成功
        """
        try:
            config_file = Path(config_path)
            
            if not config_file.exists():
                logger.warning(f"语音配置文件不存在: {config_path}")
                # 创建默认配置
                self._create_default_manifest()
                return False
            
            # 读取 YAML 配置
            with open(config_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            
            if not data:
                logger.error(f"配置文件为空: {config_path}")
                return False
            
            # 解析配置
            self._parse_manifest(data)
            self._loaded = True
            
            logger.info(f"成功加载语音清单: {len(self._manifest.entries)} 个条目")
            return True
            
        except yaml.YAMLError as e:
            logger.error(f"解析 YAML 配置失败: {e}")
            return False
        except Exception as e:
            logger.error(f"加载语音清单失败: {e}")
            return False
    
    def _parse_manifest(self, data: dict):
        """解析 YAML 数据为 AudioManifest"""
        version = data.get('version', '1.0')
        base_path = data.get('base_path', 'resources/audios')
        
        # 解析语音条目
        entries_dict = {}
        raw_entries = data.get('entries', {})
        
        for entry_id, entry_data in raw_entries.items():
            try:
                # 解析文件列表
                files = self._parse_files(entry_data.get('files', []))
                question_files = self._parse_files(entry_data.get('question_files', []))
                answer_files = self._parse_files(entry_data.get('answer_files', []))
                
                # 创建 AudioEntry
                entry = AudioEntry(
                    entry_id=entry_id,
                    category=entry_data.get('category', ''),
                    intent=entry_data.get('intent', ''),
                    description=entry_data.get('description', ''),
                    files=files,
                    selection=SelectionStrategy(entry_data.get('selection', 'random')),
                    cooldown=entry_data.get('cooldown', 0),
                    tags=entry_data.get('tags', []),
                    question_files=question_files,
                    answer_files=answer_files
                )
                
                entries_dict[entry_id] = entry
                
            except Exception as e:
                logger.warning(f"解析语音条目失败 [{entry_id}]: {e}")
                continue
        
        # 解析别名和默认映射
        aliases = data.get('aliases', {})
        course_defaults = data.get('course_defaults', {})
        
        # 创建 Manifest
        self._manifest = AudioManifest(
            version=version,
            base_path=base_path,
            entries=entries_dict,
            aliases=aliases,
            course_defaults=course_defaults
        )
    
    def _parse_files(self, files_data: List) -> List[AudioFile]:
        """解析文件列表"""
        audio_files = []
        
        for file_item in files_data:
            if isinstance(file_item, str):
                # 简单字符串形式
                audio_files.append(AudioFile(path=file_item))
            elif isinstance(file_item, dict):
                # 字典形式（带权重等）
                audio_files.append(AudioFile(
                    path=file_item.get('path', ''),
                    weight=file_item.get('weight', 1.0),
                    description=file_item.get('description')
                ))
        
        return audio_files
    
    def _create_default_manifest(self):
        """创建默认的空清单"""
        self._manifest = AudioManifest(
            version='1.0',
            base_path='resources/audios',
            entries={},
            aliases={},
            course_defaults={}
        )
        logger.info("创建了默认的空语音清单")
    
    # ========== 查询接口 ==========
    
    def get_entry(self, entry_id: str) -> Optional[AudioEntry]:
        """
        根据ID获取语音条目（支持别名）
        
        Args:
            entry_id: 语音条目ID或别名
        
        Returns:
            AudioEntry 或 None
        """
        if not self._manifest:
            logger.warning("语音清单未加载")
            return None
        
        return self._manifest.get_entry(entry_id)
    
    def get_by_category(self, category: str) -> List[AudioEntry]:
        """
        根据分类获取语音条目列表
        
        Args:
            category: 分类名称，如 "system.greeting" 或 "system"
        
        Returns:
            匹配的语音条目列表
        """
        if not self._manifest:
            return []
        
        results = []
        for entry in self._manifest.entries.values():
            # 支持前缀匹配（如 "system" 匹配 "system.greeting"）
            if entry.category.startswith(category):
                results.append(entry)
        
        return results
    
    def get_by_intent(self, intent: str) -> List[AudioEntry]:
        """
        根据语义意图获取语音条目列表
        
        Args:
            intent: 意图标识，如 "hello"
        
        Returns:
            匹配的语音条目列表
        """
        if not self._manifest:
            return []
        
        return [entry for entry in self._manifest.entries.values() 
                if entry.intent == intent]
    
    def get_by_tags(self, tags: List[str], match_all: bool = False) -> List[AudioEntry]:
        """
        根据标签获取语音条目列表
        
        Args:
            tags: 标签列表
            match_all: 是否需要匹配所有标签（True=AND，False=OR）
        
        Returns:
            匹配的语音条目列表
        """
        if not self._manifest:
            return []
        
        results = []
        for entry in self._manifest.entries.values():
            if not entry.tags:
                continue
            
            if match_all:
                # 需要匹配所有标签
                if all(tag in entry.tags for tag in tags):
                    results.append(entry)
            else:
                # 匹配任意标签
                if any(tag in entry.tags for tag in tags):
                    results.append(entry)
        
        return results
    
    def resolve_alias(self, alias: str) -> Optional[str]:
        """
        解析别名
        
        Args:
            alias: 别名
        
        Returns:
            实际的条目ID，或 None
        """
        if not self._manifest:
            return None
        
        return self._manifest.aliases.get(alias)
    
    def get_course_default(self, course_type: str, audio_type: str) -> Optional[str]:
        """
        获取课程类型的默认语音条目ID
        
        Args:
            course_type: 课程类型，如 "naming", "mimic"
            audio_type: 语音类型，如 "question", "praise", "hint"
        
        Returns:
            语音条目ID，或 None
        """
        if not self._manifest:
            return None
        
        return self._manifest.get_course_default(course_type, audio_type)
    
    def get_base_path(self) -> str:
        """获取基础路径"""
        if not self._manifest:
            return 'resources/audios'
        return self._manifest.base_path
    
    def is_loaded(self) -> bool:
        """是否已加载"""
        return self._loaded
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        if not self._manifest:
            return {
                'loaded': False,
                'total_entries': 0,
                'total_files': 0,
                'categories': [],
                'aliases': 0
            }
        
        categories = set(entry.category for entry in self._manifest.entries.values())
        total_files = sum(entry.get_file_count() for entry in self._manifest.entries.values())
        
        return {
            'loaded': True,
            'version': self._manifest.version,
            'base_path': self._manifest.base_path,
            'total_entries': len(self._manifest.entries),
            'total_files': total_files,
            'categories': list(categories),
            'aliases': len(self._manifest.aliases),
            'course_defaults': len(self._manifest.course_defaults)
        }


# 全局实例获取函数
def get_audio_registry() -> AudioRegistry:
    """获取语音注册表单例"""
    return AudioRegistry.get_instance()
