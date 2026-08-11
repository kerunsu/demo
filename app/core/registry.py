"""
分析器注册表
提供统一的分析器注册、发现和创建机制
"""
from typing import Dict, Type, Optional, Any, Callable
from enum import Enum

from app.utils.logger import setup_logger

logger = setup_logger('registry')


class AnalyzerMode(str, Enum):
    """分析器模式"""
    MOCK = "mock"
    REAL = "real"


class AnalyzerRegistry:
    """
    分析器注册表
    
    提供分析器的注册、查找和创建功能。
    支持 Mock/Real 两种模式的自动切换。
    """
    
    # 注册表：{name: {'mock': MockClass, 'real': RealClass, 'metadata': {...}}}
    _analyzers: Dict[str, Dict[str, Any]] = {}
    _matchers: Dict[str, Dict[str, Any]] = {}
    
    @classmethod
    def register_analyzer(
        cls,
        name: str,
        mock_cls: Optional[Type] = None,
        real_cls: Optional[Type] = None,
        category: str = "vision",
        description: str = "",
        **metadata
    ) -> None:
        """
        注册分析器
        
        Args:
            name: 分析器名称（如 'pose', 'face', 'speech'）
            mock_cls: Mock 实现类
            real_cls: Real 实现类
            category: 类别 ('vision' 或 'audio')
            description: 描述信息
            **metadata: 额外的元数据
        """
        if name in cls._analyzers:
            logger.warning(f"分析器 '{name}' 已存在，将被覆盖")
        
        cls._analyzers[name] = {
            'mock': mock_cls,
            'real': real_cls,
            'category': category,
            'description': description,
            'metadata': metadata
        }
        
        logger.info(
            f"已注册分析器: {name} "
            f"(mock={'✓' if mock_cls else '✗'}, "
            f"real={'✓' if real_cls else '✗'})"
        )
    
    @classmethod
    def register_matcher(
        cls,
        name: str,
        mock_cls: Optional[Type] = None,
        real_cls: Optional[Type] = None,
        category: str = "vision",
        description: str = "",
        **metadata
    ) -> None:
        """
        注册比对器
        
        Args:
            name: 比对器名称（如 'pose', 'speech'）
            mock_cls: Mock 实现类
            real_cls: Real 实现类
            category: 类别
            description: 描述信息
            **metadata: 额外的元数据
        """
        if name in cls._matchers:
            logger.warning(f"比对器 '{name}' 已存在，将被覆盖")
        
        cls._matchers[name] = {
            'mock': mock_cls,
            'real': real_cls,
            'category': category,
            'description': description,
            'metadata': metadata
        }
        
        logger.info(
            f"已注册比对器: {name} "
            f"(mock={'✓' if mock_cls else '✗'}, "
            f"real={'✓' if real_cls else '✗'})"
        )
    
    @classmethod
    def get_analyzer_class(
        cls,
        name: str,
        mode: AnalyzerMode = AnalyzerMode.MOCK
    ) -> Optional[Type]:
        """
        获取分析器类
        
        Args:
            name: 分析器名称
            mode: 模式 (MOCK 或 REAL)
        
        Returns:
            分析器类，如果不存在返回 None
        """
        entry = cls._analyzers.get(name)
        if not entry:
            logger.error(f"分析器 '{name}' 未注册")
            return None
        
        analyzer_cls = entry.get(mode.value)
        if not analyzer_cls:
            # 如果没有对应模式的实现，尝试回退到 Mock
            if mode == AnalyzerMode.REAL:
                logger.warning(
                    f"分析器 '{name}' 没有 Real 实现，回退到 Mock"
                )
                analyzer_cls = entry.get('mock')
        
        return analyzer_cls
    
    @classmethod
    def get_matcher_class(
        cls,
        name: str,
        mode: AnalyzerMode = AnalyzerMode.MOCK
    ) -> Optional[Type]:
        """
        获取比对器类
        
        Args:
            name: 比对器名称
            mode: 模式 (MOCK 或 REAL)
        
        Returns:
            比对器类，如果不存在返回 None
        """
        entry = cls._matchers.get(name)
        if not entry:
            logger.error(f"比对器 '{name}' 未注册")
            return None
        
        matcher_cls = entry.get(mode.value)
        if not matcher_cls:
            if mode == AnalyzerMode.REAL:
                logger.warning(
                    f"比对器 '{name}' 没有 Real 实现，回退到 Mock"
                )
                matcher_cls = entry.get('mock')
        
        return matcher_cls
    
    @classmethod
    def create_analyzer(
        cls,
        name: str,
        mode: AnalyzerMode = AnalyzerMode.MOCK,
        config: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        """
        创建分析器实例
        
        Args:
            name: 分析器名称
            mode: 模式
            config: 配置参数
            **kwargs: 额外的构造参数
        
        Returns:
            分析器实例
        """
        analyzer_cls = cls.get_analyzer_class(name, mode)
        if not analyzer_cls:
            raise ValueError(f"无法创建分析器 '{name}'")

        from app.core.models import AnalysisMode
        analysis_mode = kwargs.pop('analysis_mode', AnalysisMode.REALTIME)
        
        try:
            instance = analyzer_cls(mode=analysis_mode, config=config, **kwargs)
            logger.debug(f"创建分析器实例: {name} ({mode.value})")
            return instance
        except Exception as e:
            if mode == AnalyzerMode.REAL:
                mock_cls = cls.get_analyzer_class(name, AnalyzerMode.MOCK)
                if mock_cls and mock_cls is not analyzer_cls:
                    logger.warning(
                        "创建 Real 分析器 '%s' 失败，回退 Mock: %s", name, e
                    )
                    try:
                        return mock_cls(mode=analysis_mode, config=config, **kwargs)
                    except Exception as e2:
                        logger.error("回退 Mock 分析器 '%s' 仍失败: %s", name, e2)
            logger.error(f"创建分析器 '{name}' 失败: {e}")
            raise
    
    @classmethod
    def create_matcher(
        cls,
        name: str,
        mode: AnalyzerMode = AnalyzerMode.MOCK,
        threshold: float = 0.8,
        config: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        """
        创建比对器实例
        
        Args:
            name: 比对器名称
            mode: 模式
            threshold: 匹配阈值
            config: 配置参数
            **kwargs: 额外的构造参数
        
        Returns:
            比对器实例
        """
        matcher_cls = cls.get_matcher_class(name, mode)
        if not matcher_cls:
            raise ValueError(f"无法创建比对器 '{name}'")
        
        try:
            instance = matcher_cls(threshold=threshold, config=config, **kwargs)
            logger.debug(f"创建比对器实例: {name} ({mode.value})")
            return instance
        except Exception as e:
            if mode == AnalyzerMode.REAL:
                mock_cls = cls.get_matcher_class(name, AnalyzerMode.MOCK)
                if mock_cls and mock_cls is not matcher_cls:
                    logger.warning(
                        "创建 Real 比对器 '%s' 失败，回退 Mock: %s", name, e
                    )
                    try:
                        return mock_cls(threshold=threshold, config=config, **kwargs)
                    except Exception as e2:
                        logger.error("回退 Mock 比对器 '%s' 仍失败: %s", name, e2)
            logger.error(f"创建比对器 '{name}' 失败: {e}")
            raise
    
    @classmethod
    def list_analyzers(cls, category: Optional[str] = None) -> Dict[str, Dict]:
        """
        列出所有已注册的分析器
        
        Args:
            category: 可选，只列出指定类别
        
        Returns:
            分析器信息字典
        """
        if category:
            return {
                name: info for name, info in cls._analyzers.items()
                if info.get('category') == category
            }
        return cls._analyzers.copy()
    
    @classmethod
    def list_matchers(cls, category: Optional[str] = None) -> Dict[str, Dict]:
        """
        列出所有已注册的比对器
        
        Args:
            category: 可选，只列出指定类别
        
        Returns:
            比对器信息字典
        """
        if category:
            return {
                name: info for name, info in cls._matchers.items()
                if info.get('category') == category
            }
        return cls._matchers.copy()
    
    @classmethod
    def has_real_implementation(cls, name: str, is_matcher: bool = False) -> bool:
        """
        检查是否有 Real 实现
        
        Args:
            name: 名称
            is_matcher: 是否是比对器
        
        Returns:
            True 如果有 Real 实现
        """
        registry = cls._matchers if is_matcher else cls._analyzers
        entry = registry.get(name)
        return entry and entry.get('real') is not None
    
    @classmethod
    def clear(cls) -> None:
        """清空注册表（主要用于测试）"""
        cls._analyzers.clear()
        cls._matchers.clear()
        logger.info("注册表已清空")


def register_analyzer(
    name: str,
    mode: str = "mock",
    category: str = "vision",
    description: str = "",
    **metadata
) -> Callable:
    """
    分析器注册装饰器
    
    使用示例:
    ```python
    @register_analyzer('face', mode='real', category='vision')
    class RealFaceAnalyzer(BaseVisionAnalyzer):
        ...
    ```
    
    Args:
        name: 分析器名称
        mode: 'mock' 或 'real'
        category: 类别
        description: 描述
        **metadata: 额外元数据
    """
    def decorator(cls):
        # 注册到对应的 mode
        if mode.lower() == "mock":
            AnalyzerRegistry.register_analyzer(
                name,
                mock_cls=cls,
                category=category,
                description=description,
                **metadata
            )
        elif mode.lower() == "real":
            # 查找是否已经注册了 Mock 版本
            existing = AnalyzerRegistry._analyzers.get(name, {})
            AnalyzerRegistry.register_analyzer(
                name,
                mock_cls=existing.get('mock'),
                real_cls=cls,
                category=category,
                description=description or existing.get('description', ''),
                **{**existing.get('metadata', {}), **metadata}
            )
        else:
            raise ValueError(f"不支持的模式: {mode}")
        
        return cls
    
    return decorator


def register_matcher(
    name: str,
    mode: str = "mock",
    category: str = "vision",
    description: str = "",
    **metadata
) -> Callable:
    """
    比对器注册装饰器
    
    使用示例:
    ```python
    @register_matcher('pose', mode='real', category='vision')
    class RealPoseMatcher(BasePoseMatcher):
        ...
    ```
    
    Args:
        name: 比对器名称
        mode: 'mock' 或 'real'
        category: 类别
        description: 描述
        **metadata: 额外元数据
    """
    def decorator(cls):
        if mode.lower() == "mock":
            AnalyzerRegistry.register_matcher(
                name,
                mock_cls=cls,
                category=category,
                description=description,
                **metadata
            )
        elif mode.lower() == "real":
            existing = AnalyzerRegistry._matchers.get(name, {})
            AnalyzerRegistry.register_matcher(
                name,
                mock_cls=existing.get('mock'),
                real_cls=cls,
                category=category,
                description=description or existing.get('description', ''),
                **{**existing.get('metadata', {}), **metadata}
            )
        else:
            raise ValueError(f"不支持的模式: {mode}")
        
        return cls
    
    return decorator


# 全局注册表实例（单例）
_global_registry = AnalyzerRegistry()


def get_registry() -> AnalyzerRegistry:
    """获取全局注册表实例"""
    return _global_registry

