# 模型插件指南

## 最小实现

```python
from app.contracts.models import ModelDescriptor, Observation
from app.computation.model_plugins import ModelRegistry, ModelPipeline

descriptor = ModelDescriptor(
    model_id="attention.example",
    version="1.0.0",
    modalities=("video",),
    capabilities=("attention",),
    config_schema={"type": "object"},
    resource_needs={"gpu": False},
)

class ExampleModel:
    descriptor = descriptor
    def prepare(self, config=None): return {"ok": True}
    def health(self): return {"ok": True}
    def analyze(self, batch):
        return Observation(
            observation_id="generated-by-provider",
            model_id=self.descriptor.model_id,
            model_version=self.descriptor.version,
            session=batch.session,
            modality="video",
            values={"attention": 0.8},
            confidence=0.9,
            relative_ms=batch.start_relative_ms,
        )
    def close(self): pass

registry = ModelRegistry()
registry.register(descriptor, lambda config: ExampleModel(), mode="real")
pipeline = ModelPipeline(registry)
result = pipeline.analyze("attention.example", frame_batch, timeout_ms=1000)
```

生产 provider 必须验证输入时间轴、输出范围和模型版本；不可用时抛异常或返回带 `missing_reason` 的结果，不得把默认值伪装成高置信度结果。`close()` 要释放自身线程/进程/模型句柄，且必须可重复调用。

## 选择与健康检查

`mode="real"` 优先 real；只有显式注册了 mock 时才允许回退 mock。`health()` 是数据查询，不应让 Flask 启动失败。配置、模型文件和硬件句柄只能由 composition root/adapter 注入，不能在 `app/computation` 导入时创建。

## 输出约束

- 时间：使用 session 相对毫秒，不能把机器墙上时间当排序依据。
- 置信度：缺失时为 `None`，不能填 0.99。
- 分数：必须带 `score_min/score_max`、`confidence` 和 `missing_reason`。
- 关联：所有 observation/score/decision 必须带 session 和 model id/version。
- 失败：超时、取消、未注册、背压、异常各自保留原因，供报告和审计区分。
