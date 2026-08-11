# 第四阶段：计算块边界

## 目标

计算块负责就绪门、分析模型编排、课程推进、题目窗口、注意力/情绪/动作决策、评分和报告计算。它不负责 Flask/Socket.IO 传输，不负责录音文件写入，也不负责 ASR、LLM、TTS 主链路。

本阶段采用 strangler 方式：旧 `app/services/analysis_service.py`、`app/core/` 和评分流程继续运行；新代码通过 `app/contracts` 的 DTO/Protocol 接入，不复制旧规则。旧模型和旧配置没有默认值变化。

## 已落地的稳定端口

- `ModelDescriptor`、`FrameBatch`、`AudioBatch`、`TextObservation`、`Observation`、`Score`、`DecisionCandidate`：字段带 `schema_version`、session 关联、相对时间、置信度、缺失原因和模型版本。
- `AnalysisModel`：`descriptor → prepare → health → analyze → close`。构造和注册不加载硬件、不启动线程；关闭可重复调用。
- `ModelRegistry`/`ModelPipeline`：支持 `real/mock` 选择、超时、取消、背压、错误降级和明确 `missing_reason`。模型失败只能得到 degraded/no-data，不能伪造高分或阻止录制。
- `ResourceResolver`/`BehaviorPlan`：将 `course/event/scene/line` 上下文解析为一个不可变多模态计划，包含 speech、motions、expressions、visual、course commands 和 `resolution_trace`。

## 旧逻辑兼容

`LegacyInteractionAdapter` 只包裹现有 `MappingResolver`，保留项目级 → 学生课程级 → 课程级 → 默认级优先级。没有已发布 V2 profile 时，解析结果和旧字段逐项一致。已发布 profile 才能进入 V2；draft、archived 或非法 profile 只能在控制端查看，不能被运行时使用。

`RobotService` 的 `trigger_course_event` 和 `resolve_audio_offset_ms` 先取得旧结果，再在 V2 明确命中时覆盖对应动作/表情/序列；任何 V2 读失败都回到旧解析器。行为互斥、行为 ID、音频偏移和现有 Socket 字段仍由原链路负责。

## 降级语义

| 情况 | 计算输出 | 录制/主流程 |
|---|---|---|
| 模型未注册 | `Observation.missing_reason=model_not_registered` | 不伪造分数，不阻止采集 |
| 超时/异常/背压 | degraded observation，`confidence=None` | 保留原有可用结果或显式无数据 |
| V2 未发布/事件未知 | legacy `BehaviorPlan` | 完全走旧映射 |
| profile 发布校验失败 | 不写入、不切换当前版本 | 当前已发布版本不变 |

## 下一步边界

将来替换具体分析模型时，只新增 provider 和 composition-root 注册，不修改 route、Socket、sessions 文件名或报告 presenter；若新模型不可用，注册表必须选择既有 real/mock adapter 或返回显式无数据。
