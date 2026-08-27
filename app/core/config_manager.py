"""
改进的分析器配置系统
支持 YAML 配置文件和环境变量
"""
import os
import copy
from datetime import datetime
import yaml
from typing import Dict, Any, Optional

from app.core.registry import AnalyzerMode
from app.utils.logger import setup_logger

logger = setup_logger('analyzer_config_v2')


class AnalyzerConfigManager:
    """
    分析器配置管理器
    
    支持多种配置来源（按优先级）：
    1. 环境变量
    2. YAML 配置文件
    3. 默认配置
    """
    
    DEFAULT_CONFIG_PATH = "config/analyzers.yaml"
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置管理器
        
        Args:
            config_path: 配置文件路径（可选）
        """
        self._config_path = config_path or self.DEFAULT_CONFIG_PATH
        self._config: Dict[str, Any] = {}
        self._history: list[Dict[str, Any]] = []
        self._audit_logs: list[Dict[str, Any]] = []
        self._load_config()
    
    def _load_config(self) -> None:
        """加载配置"""
        # 1. 加载默认配置
        self._config = self._get_default_config()
        
        # 2. 尝试加载 YAML 配置文件
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    yaml_config = yaml.safe_load(f) or {}
                    self._merge_config(yaml_config)
                    logger.info(f"已加载配置文件: {self._config_path}")
            except Exception as e:
                logger.warning(f"加载配置文件失败: {e}，使用默认配置")
        else:
            logger.info(f"配置文件不存在: {self._config_path}，使用默认配置")
        
        # 3. 应用环境变量覆盖
        self._apply_env_overrides()
        
        logger.info(f"配置加载完成，全局模式: {self.global_mode}")
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            'global': {
                'mode': 'real',  # 默认 Real；无实现/创建失败时 Registry 回退 Mock
                'enable_sampling': True,
                'enable_metrics': False
            },
            'analyzers': {
                'pose': {
                    'mode': 'real',  # None 表示继承 global.mode
                    'enabled': True,
                    'sample_rate': 0.05,  # 1.0 = 每帧分析
                    'model_path': 'models/pose_landmarker_lite.task',
                    'min_detection_confidence': 0.5,
                    'num_poses': 1
                },
                'face': {
                    'mode': None,
                    'enabled': True,
                    'sample_rate': 1.0,
                    'model_path': 'models/face_model.onnx'
                },
                'attention': {
                    'mode': None,
                    'enabled': True,
                    'window_size': 10.0
                },
                'speech': {
                    'mode': None,
                    'enabled': True,
                    'sample_rate': 1.0,
                    'model_path': 'models/whisper_tiny.bin',
                    'language': 'zh'
                }
            },
            'matchers': {
                'pose': {
                    'mode': 'real',
                    'enabled': True,
                    'threshold': 0.70,
                    'min_keypoint_visibility': 0.35,
                    'action_sigma': 0.55,
                    'allow_mirror': True,
                    'stable_frames': 4,
                    'stable_hold_seconds': 0.6,
                    'max_frame_gap_seconds': 0.55,
                },
                'speech': {
                    'mode': None,
                    'enabled': True,
                    'threshold': 0.80
                }
            }
        }
    
    def _merge_config(self, new_config: Dict[str, Any]) -> None:
        """合并配置（深度合并）"""
        def deep_merge(base: dict, update: dict) -> dict:
            for key, value in update.items():
                if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                    deep_merge(base[key], value)
                else:
                    base[key] = value
            return base
        
        deep_merge(self._config, new_config)
    
    def _apply_env_overrides(self) -> None:
        """应用环境变量覆盖"""
        # 全局模式
        global_mode = os.environ.get('USE_REAL_ANALYZERS', '').lower()
        if global_mode == 'true':
            self._config['global']['mode'] = 'real'
        elif global_mode == 'false':
            self._config['global']['mode'] = 'mock'
        
        # 单个分析器覆盖（如 ANALYZER_POSE_MODE=real）
        for analyzer_name in self._config.get('analyzers', {}).keys():
            env_key = f'ANALYZER_{analyzer_name.upper()}_MODE'
            env_value = os.environ.get(env_key, '').lower()
            if env_value in ['mock', 'real']:
                self._config['analyzers'][analyzer_name]['mode'] = env_value
        
        # 单个比对器覆盖
        for matcher_name in self._config.get('matchers', {}).keys():
            env_key = f'MATCHER_{matcher_name.upper()}_MODE'
            env_value = os.environ.get(env_key, '').lower()
            if env_value in ['mock', 'real']:
                self._config['matchers'][matcher_name]['mode'] = env_value
    
    @property
    def global_mode(self) -> AnalyzerMode:
        """获取全局模式"""
        mode_str = self._config.get('global', {}).get('mode', 'real')
        return AnalyzerMode.REAL if mode_str == 'real' else AnalyzerMode.MOCK
    
    def get_analyzer_mode(self, name: str) -> AnalyzerMode:
        """
        获取指定分析器的模式
        
        Args:
            name: 分析器名称
        
        Returns:
            AnalyzerMode
        """
        analyzer_config = self._config.get('analyzers', {}).get(name, {})
        mode = analyzer_config.get('mode')
        
        # 如果未指定，使用全局模式
        if mode is None:
            return self.global_mode
        
        return AnalyzerMode.REAL if mode == 'real' else AnalyzerMode.MOCK
    
    def get_matcher_mode(self, name: str) -> AnalyzerMode:
        """
        获取指定比对器的模式
        
        Args:
            name: 比对器名称
        
        Returns:
            AnalyzerMode
        """
        matcher_config = self._config.get('matchers', {}).get(name, {})
        mode = matcher_config.get('mode')
        
        if mode is None:
            return self.global_mode
        
        return AnalyzerMode.REAL if mode == 'real' else AnalyzerMode.MOCK
    
    def get_analyzer_config(self, name: str) -> Dict[str, Any]:
        """
        获取指定分析器的完整配置
        
        Args:
            name: 分析器名称
        
        Returns:
            配置字典
        """
        return self._config.get('analyzers', {}).get(name, {}).copy()
    
    def get_matcher_config(self, name: str) -> Dict[str, Any]:
        """
        获取指定比对器的完整配置
        
        Args:
            name: 比对器名称
        
        Returns:
            配置字典
        """
        return self._config.get('matchers', {}).get(name, {}).copy()
    
    def is_analyzer_enabled(self, name: str) -> bool:
        """检查分析器是否启用"""
        return self._config.get('analyzers', {}).get(name, {}).get('enabled', True)
    
    def is_matcher_enabled(self, name: str) -> bool:
        """检查比对器是否启用"""
        return self._config.get('matchers', {}).get(name, {}).get('enabled', True)
    
    def get_sample_rate(self, name: str) -> float:
        """获取分析器的采样率"""
        return self._config.get('analyzers', {}).get(name, {}).get('sample_rate', 1.0)
    
    def set_global_mode(self, mode: AnalyzerMode) -> None:
        """设置全局模式"""
        self._config['global']['mode'] = mode.value
        logger.info(f"全局模式已切换: {mode.value}")
    
    def set_analyzer_mode(self, name: str, mode: AnalyzerMode) -> None:
        """设置指定分析器的模式"""
        if name not in self._config.get('analyzers', {}):
            logger.warning(f"分析器 '{name}' 不在配置中")
            return
        
        self._config['analyzers'][name]['mode'] = mode.value
        logger.info(f"分析器 '{name}' 模式已切换: {mode.value}")
    
    def save_config(self, path: Optional[str] = None) -> bool:
        """
        保存配置到 YAML 文件
        
        Args:
            path: 保存路径（可选）
        
        Returns:
            是否成功
        """
        save_path = path or self._config_path
        
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(save_path) or '.', exist_ok=True)
            
            with open(save_path, 'w', encoding='utf-8') as f:
                yaml.dump(
                    self._config,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False
                )
            
            logger.info(f"配置已保存: {save_path}")
            return True
            
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            return False
    
    def get_all_config(self) -> Dict[str, Any]:
        """获取完整配置"""
        return self._config.copy()
    
    @property
    def config_path(self) -> str:
        """当前配置文件路径"""
        return self._config_path
    
    def update_config(
        self,
        partial_config: Dict[str, Any],
        actor: str = "server_console"
    ) -> Dict[str, Any]:
        """
        深度合并更新配置。
        
        Args:
            partial_config: 需要合并到当前配置的部分配置
        
        Returns:
            更新后的完整配置
        """
        if not isinstance(partial_config, dict):
            raise ValueError("partial_config 必须是字典")
        
        before = copy.deepcopy(self._config)
        self.create_snapshot("update_config")
        self._merge_config(partial_config)
        self._record_audit(
            action="update",
            actor=actor,
            before=before,
            after=self._config
        )
        logger.info("配置已更新（内存）")
        return self.get_all_config()
    
    def replace_config(
        self,
        new_config: Dict[str, Any],
        actor: str = "server_console"
    ) -> Dict[str, Any]:
        """
        使用新配置替换当前配置（内存）。
        
        Args:
            new_config: 完整配置
        
        Returns:
            替换后的完整配置
        """
        if not isinstance(new_config, dict):
            raise ValueError("new_config 必须是字典")
        
        before = copy.deepcopy(self._config)
        self.create_snapshot("replace_config")
        self._config = new_config.copy()
        self._record_audit(
            action="replace",
            actor=actor,
            before=before,
            after=self._config
        )
        logger.info("配置已整体替换（内存）")
        return self.get_all_config()
    
    def reset_to_default(
        self,
        apply_env_overrides: bool = False,
        actor: str = "server_console"
    ) -> Dict[str, Any]:
        """
        重置为默认配置。
        
        Args:
            apply_env_overrides: 是否应用环境变量覆盖
        
        Returns:
            重置后的完整配置
        """
        before = copy.deepcopy(self._config)
        self.create_snapshot("reset_to_default")
        self._config = self._get_default_config()
        if apply_env_overrides:
            self._apply_env_overrides()
        self._record_audit(
            action="reset_default",
            actor=actor,
            before=before,
            after=self._config
        )
        logger.info("配置已重置为默认值")
        return self.get_all_config()
    
    def create_snapshot(self, reason: str = "") -> int:
        """创建配置快照，返回当前快照数量。"""
        snapshot = {
            "reason": reason or "manual",
            "config": copy.deepcopy(self._config)
        }
        self._history.append(snapshot)
        if len(self._history) > 20:
            self._history = self._history[-20:]
        return len(self._history)
    
    def rollback_last_snapshot(
        self,
        actor: str = "server_console"
    ) -> Optional[Dict[str, Any]]:
        """回滚到最近一次快照，若无快照则返回 None。"""
        if not self._history:
            return None
        before = copy.deepcopy(self._config)
        snapshot = self._history.pop()
        self._config = copy.deepcopy(snapshot["config"])
        self._record_audit(
            action="rollback",
            actor=actor,
            before=before,
            after=self._config,
            detail={"from_reason": snapshot.get("reason")}
        )
        logger.info("已回滚到最近配置快照: %s", snapshot.get("reason"))
        return self.get_all_config()
    
    def get_snapshot_count(self) -> int:
        """获取当前可回滚快照数量。"""
        return len(self._history)
    
    def get_presets(self) -> Dict[str, Dict[str, Any]]:
        """获取内置预设模板。"""
        stable = self._get_default_config()
        stable["global"]["mode"] = "mock"
        stable["analyzers"]["pose"]["sample_rate"] = 0.2
        stable["analyzers"]["speech"]["sample_rate"] = 0.5
        stable["matchers"]["pose"]["threshold"] = 0.9
        
        dev = self._get_default_config()
        dev["global"]["mode"] = "real"
        dev["analyzers"]["pose"]["sample_rate"] = 1.0
        dev["analyzers"]["face"]["sample_rate"] = 1.0
        dev["analyzers"]["speech"]["sample_rate"] = 1.0
        
        mock_only = self._get_default_config()
        mock_only["global"]["mode"] = "mock"
        for analyzer_name in mock_only["analyzers"].keys():
            mock_only["analyzers"][analyzer_name]["mode"] = "mock"
            mock_only["analyzers"][analyzer_name]["enabled"] = True
        for matcher_name in mock_only["matchers"].keys():
            mock_only["matchers"][matcher_name]["mode"] = "mock"
        
        return {
            "classroom_stable": stable,
            "dev_real": dev,
            "mock_only": mock_only,
        }
    
    def apply_preset(self, preset_name: str, actor: str = "server_console") -> Dict[str, Any]:
        """应用预设模板到当前配置。"""
        presets = self.get_presets()
        if preset_name not in presets:
            raise ValueError(f"未知预设: {preset_name}")
        
        before = copy.deepcopy(self._config)
        self.create_snapshot(f"apply_preset:{preset_name}")
        self._config = copy.deepcopy(presets[preset_name])
        self._record_audit(
            action="apply_preset",
            actor=actor,
            before=before,
            after=self._config,
            detail={"preset": preset_name}
        )
        return self.get_all_config()
    
    def get_audit_logs(self, limit: int = 100) -> list[Dict[str, Any]]:
        """获取最近变更日志。"""
        if limit <= 0:
            return []
        return self._audit_logs[-limit:]
    
    def _record_audit(
        self,
        action: str,
        actor: str,
        before: Dict[str, Any],
        after: Dict[str, Any],
        detail: Optional[Dict[str, Any]] = None
    ) -> None:
        changed_paths = self._diff_paths(before, after)
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "action": action,
            "actor": actor,
            "changedPaths": changed_paths[:80],
            "changedCount": len(changed_paths),
            "detail": detail or {}
        }
        self._audit_logs.append(entry)
        if len(self._audit_logs) > 500:
            self._audit_logs = self._audit_logs[-500:]
    
    def _diff_paths(self, before: Any, after: Any, prefix: str = "") -> list[str]:
        """比较两个对象并返回变更路径列表。"""
        if type(before) != type(after):
            return [prefix or "<root>"]
        
        if isinstance(before, dict):
            paths: list[str] = []
            all_keys = set(before.keys()) | set(after.keys())
            for key in sorted(all_keys):
                next_prefix = f"{prefix}.{key}" if prefix else str(key)
                if key not in before or key not in after:
                    paths.append(next_prefix)
                else:
                    paths.extend(self._diff_paths(before[key], after[key], next_prefix))
            return paths
        
        if isinstance(before, list):
            if before != after:
                return [prefix or "<root>"]
            return []
        
        if before != after:
            return [prefix or "<root>"]
        return []


# 全局配置管理器实例
_global_config_manager: Optional[AnalyzerConfigManager] = None


def get_config_manager(config_path: Optional[str] = None) -> AnalyzerConfigManager:
    """
    获取全局配置管理器实例
    
    Args:
        config_path: 配置文件路径（仅首次调用时有效）
    
    Returns:
        配置管理器实例
    """
    global _global_config_manager
    if _global_config_manager is None:
        _global_config_manager = AnalyzerConfigManager(config_path)
    return _global_config_manager


def reset_config_manager() -> None:
    """重置配置管理器（主要用于测试）"""
    global _global_config_manager
    _global_config_manager = None

