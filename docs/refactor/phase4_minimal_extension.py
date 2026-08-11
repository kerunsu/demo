"""第四阶段最小扩展示例：新增一个分析模型和一个课程事件。

该文件只演示纯端口，不启动 Flask、线程、硬件或文件写入。
"""

from app.computation.interaction import EventCatalog, EventDefinition
from app.computation.model_plugins import ModelPipeline, ModelRegistry
from app.contracts.models import ModelDescriptor, Observation


descriptor = ModelDescriptor(
    model_id="demo.pose",
    version="1.0.0",
    modalities=("video",),
    capabilities=("pose",),
)


class DemoPoseModel:
    descriptor = descriptor

    def prepare(self, config=None):
        return {"ok": True}

    def health(self):
        return {"ok": True}

    def analyze(self, batch):
        return Observation(
            observation_id="demo-observation",
            model_id=self.descriptor.model_id,
            model_version=self.descriptor.version,
            session=batch.session,
            modality="video",
            values={"pose": "ready"},
            confidence=1.0,
            relative_ms=batch.start_relative_ms,
        )

    def close(self):
        pass


registry = ModelRegistry()
registry.register(descriptor, lambda config: DemoPoseModel(), mode="mock")
catalog = EventCatalog()
catalog.register(EventDefinition("question.custom", "自定义提问", kind="instant"))

# composition root 中再创建 ModelPipeline 并注入 use case；此示例不启动资源。
