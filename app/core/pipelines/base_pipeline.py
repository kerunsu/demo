"""
分析流水线基类
用于组装多个分析器，统一调度分析流程
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple
import time
import threading

from app.core.models import (
    AnalysisMode,
    AnalysisContext,
    AnalysisResult,
    MatchResult
)
from app.core.base_analyzer import BaseAnalyzer, BaseWindowAnalyzer
from app.core.base_matcher import BaseMatcher
from app.utils.logger import setup_logger

logger = setup_logger('pipeline')


class BasePipeline(ABC):
    """
    分析流水线抽象基类
    
    职责：
    - 管理多个分析器
    - 协调分析流程
    - 支持三种分析模式（实时/窗口/会话）
    """
    
    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        """
        初始化流水线
        
        Args:
            name: 流水线名称
            config: 配置参数
        """
        self._name = name
        self._config = config or {}
        
        # 分析器按模式分组
        self._realtime_analyzers: List[BaseAnalyzer] = []  # Type A
        self._window_analyzers: List[BaseWindowAnalyzer] = []  # Type B
        self._session_analyzers: List[BaseAnalyzer] = []  # Type C
        
        # 比对器
        self._matchers: Dict[str, BaseMatcher] = {}
        
        # 状态
        self._is_initialized = False
        self._is_running = False
        self._lock = threading.Lock()
        self._initialization_failures: List[Dict[str, Any]] = []
        
        logger.info(f"流水线已创建: {name}")
    
    @property
    def name(self) -> str:
        """返回流水线名称"""
        return self._name
    
    @property
    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._is_initialized
    
    @property
    def is_running(self) -> bool:
        """检查是否正在运行"""
        return self._is_running
    
    def add_realtime_analyzer(self, analyzer: BaseAnalyzer) -> None:
        """添加实时分析器（Type A）"""
        self._realtime_analyzers.append(analyzer)
        logger.debug(f"添加实时分析器: {analyzer._analyzer_type.value}")
    
    def add_window_analyzer(self, analyzer: BaseWindowAnalyzer) -> None:
        """添加窗口分析器（Type B）"""
        self._window_analyzers.append(analyzer)
        logger.debug(f"添加窗口分析器: {analyzer._analyzer_type.value}")
    
    def add_session_analyzer(self, analyzer: BaseAnalyzer) -> None:
        """添加会话分析器（Type C）"""
        self._session_analyzers.append(analyzer)
        logger.debug(f"添加会话分析器: {analyzer._analyzer_type.value}")
    
    def add_matcher(self, name: str, matcher: BaseMatcher) -> None:
        """添加比对器"""
        self._matchers[name] = matcher
        logger.debug(f"添加比对器: {name}")
    
    def get_matcher(self, name: str) -> Optional[BaseMatcher]:
        """获取比对器"""
        return self._matchers.get(name)
    
    def initialize(self) -> bool:
        """
        初始化流水线
        
        初始化所有分析器和比对器
        
        Returns:
            True如果初始化成功
        """
        try:
            # 初始化实时分析器
            for analyzer in self._realtime_analyzers:
                if not analyzer.initialize():
                    logger.error(f"实时分析器初始化失败: {analyzer._analyzer_type.value}")
                    return False
            
            # 初始化窗口分析器
            for analyzer in self._window_analyzers:
                if not analyzer.initialize():
                    logger.error(f"窗口分析器初始化失败: {analyzer._analyzer_type.value}")
                    return False
            
            # 初始化会话分析器
            for analyzer in self._session_analyzers:
                if not analyzer.initialize():
                    logger.error(f"会话分析器初始化失败: {analyzer._analyzer_type.value}")
                    return False
            
            # 初始化比对器
            for name, matcher in self._matchers.items():
                if not matcher.initialize():
                    logger.error(f"比对器初始化失败: {name}")
                    return False
            
            self._is_initialized = True
            logger.info(f"流水线初始化成功: {self._name}")
            return True
            
        except Exception as e:
            logger.error(f"流水线初始化失败: {e}")
            return False
    
    def record_initialization_failure(
        self,
        component: str,
        error: Any,
        *,
        required: bool = True,
        stage: str = "create",
    ) -> None:
        self._initialization_failures.append({
            "component": str(component),
            "required": bool(required),
            "stage": str(stage),
            "error": str(error),
        })

    def initialize(self) -> bool:
        """Initialize every component and retain actionable health details."""
        self._initialization_failures = [
            item for item in self._initialization_failures
            if item.get("stage") == "create"
        ]
        try:
            for analyzers in (
                self._realtime_analyzers,
                self._window_analyzers,
                self._session_analyzers,
            ):
                for analyzer in analyzers:
                    component = analyzer._analyzer_type.value
                    try:
                        initialized = bool(analyzer.initialize())
                        error = (
                            getattr(analyzer, "last_error", None)
                            or "initialize_returned_false"
                        )
                    except Exception as exc:
                        initialized = False
                        error = exc
                    if not initialized:
                        self.record_initialization_failure(
                            component,
                            error,
                            required=bool(getattr(analyzer, "_health_required", True)),
                            stage="initialize",
                        )

            for name, matcher in self._matchers.items():
                try:
                    initialized = bool(matcher.initialize())
                    error = "initialize_returned_false"
                except Exception as exc:
                    initialized = False
                    error = exc
                if not initialized:
                    self.record_initialization_failure(
                        f"matcher:{name}",
                        error,
                        required=bool(getattr(matcher, "_health_required", False)),
                        stage="initialize",
                    )

            required_failures = [
                item for item in self._initialization_failures
                if item.get("required")
            ]
            self._is_initialized = not required_failures
            log = logger.info if self._is_initialized else logger.error
            log(
                "pipeline health name=%s initialized=%s failures=%s",
                self._name,
                self._is_initialized,
                self._initialization_failures,
            )
            return self._is_initialized
        except Exception as exc:
            self.record_initialization_failure(
                self._name, exc, required=True, stage="pipeline"
            )
            self._is_initialized = False
            logger.error("pipeline initialization crashed: %s", exc)
            return False

    def cleanup(self) -> None:
        """清理流水线资源"""
        try:
            # 清理所有分析器
            for analyzer in self._realtime_analyzers:
                analyzer.cleanup()
            for analyzer in self._window_analyzers:
                analyzer.cleanup()
            for analyzer in self._session_analyzers:
                analyzer.cleanup()
            
            # 清理比对器
            for matcher in self._matchers.values():
                matcher.cleanup()
            
            self._is_initialized = False
            self._is_running = False
            logger.info(f"流水线已清理: {self._name}")
            
        except Exception as e:
            logger.error(f"流水线清理失败: {e}")
    
    @abstractmethod
    def process_realtime(
        self,
        data: Any,
        context: AnalysisContext
    ) -> Tuple[List[AnalysisResult], List[MatchResult]]:
        """
        实时处理数据（Type A）
        
        Args:
            data: 输入数据（帧或音频块）
            context: 分析上下文
        
        Returns:
            (分析结果列表, 匹配结果列表)
        """
        pass
    
    @abstractmethod
    def process_window(
        self,
        video_frames: List[Tuple[float, Any]],
        audio_chunks: List[Tuple[float, Any]],
        context: AnalysisContext
    ) -> List[AnalysisResult]:
        """
        窗口处理数据（Type B）
        
        Args:
            video_frames: 视频帧列表 [(timestamp, frame), ...]
            audio_chunks: 音频块列表 [(timestamp, chunk), ...]
            context: 分析上下文
        
        Returns:
            分析结果列表
        """
        pass
    
    @abstractmethod
    def process_session(
        self,
        all_results: List[AnalysisResult],
        context: AnalysisContext
    ) -> List[AnalysisResult]:
        """
        会话结束处理（Type C）
        
        Args:
            all_results: 会话中所有的分析结果
            context: 分析上下文
        
        Returns:
            会话总结结果列表
        """
        pass
    
    def get_info(self) -> Dict[str, Any]:
        """获取流水线信息"""
        return {
            'name': self._name,
            'is_initialized': self._is_initialized,
            'is_running': self._is_running,
            'realtime_analyzers': len(self._realtime_analyzers),
            'window_analyzers': len(self._window_analyzers),
            'session_analyzers': len(self._session_analyzers),
            'matchers': list(self._matchers.keys()),
            'config': self._config,
            'initialization_failures': [
                dict(item) for item in self._initialization_failures
            ],
        }


class PipelineManager:
    """
    流水线管理器
    
    管理多个流水线实例，支持按名称获取
    """
    
    _instance: Optional['PipelineManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._pipelines: Dict[str, BasePipeline] = {}
                    logger.info("流水线管理器已创建")
        return cls._instance
    
    def register(self, pipeline: BasePipeline) -> None:
        """注册流水线"""
        self._pipelines[pipeline.name] = pipeline
        logger.info(f"注册流水线: {pipeline.name}")
    
    def get(self, name: str) -> Optional[BasePipeline]:
        """获取流水线"""
        return self._pipelines.get(name)
    
    def remove(self, name: str) -> None:
        """移除流水线"""
        if name in self._pipelines:
            self._pipelines[name].cleanup()
            del self._pipelines[name]
            logger.info(f"移除流水线: {name}")
    
    def get_all(self) -> Dict[str, BasePipeline]:
        """获取所有流水线"""
        return self._pipelines.copy()
    
    def cleanup_all(self) -> None:
        """清理所有流水线"""
        for pipeline in self._pipelines.values():
            pipeline.cleanup()
        self._pipelines.clear()
        logger.info("所有流水线已清理")


def get_pipeline_manager() -> PipelineManager:
    """获取流水线管理器单例"""
    return PipelineManager()

