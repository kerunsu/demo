"""计算块骨架：就绪、分析、评分、课程推进和行为决策。

当前实现仍由 ``app.core``、``app.services``、``app.behavior`` 和 ``app.report``
提供；本包只作为后续 adapter 的目标边界。
"""
from .preflight import PreflightOrchestrator, PreflightPlan
from .model_plugins import ModelPipeline, ModelRegistry
from .interaction import EventCatalog, InteractionResolver, LegacyInteractionAdapter, validate_profile

__all__ = [
    "PreflightOrchestrator",
    "PreflightPlan",
    "ModelPipeline",
    "ModelRegistry",
    "EventCatalog",
    "InteractionResolver",
    "LegacyInteractionAdapter",
    "validate_profile",
]
