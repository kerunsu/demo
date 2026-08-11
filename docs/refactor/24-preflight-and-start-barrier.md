# 24. Preflight 与启动屏障

## 两条兼容路径

| 路径 | prepare | readiness | 正式采集 |
|---|---|---|---|
| legacy（默认） | 创建 warmup 并立即按历史逻辑录制 | M1-M7 复用既有检查 | 保持原行为 |
| strict（显式） | 只预留 session/目录身份，`preflightOnly=true` | M1-M7 + M8 设备检查 | 全部 required success 后启动 |

strict 路径保留既有事件名和主要 payload 字段，只增加 `preflightOnly`、`captureStarted`、`preflightMode`、`devices` 等可选字段。儿童端收到 strict prepare 只绑定 session 和预览，不启动录制；服务端只向该 session 的儿童 owner 发出带 `captureStart` 的既有 `readiness_complete`，此时 `captureStarted=false`。儿童端启动并回报 `captureStartConfirmed` 后，服务端还必须从自身 recorder/uplink 元数据验证正式首帧或近期数据块，随后才向教师端发最终 `readiness_complete(captureStarted=true)`。

M8 的语义是设备清单逐台结果：enabled+required 必须 success；optional 失败只记录状态；disabled 不参加门禁；零环境设备是合法部署。当前 `ReadinessService` 在没有真实 DeviceBroker 注入时，对已配置的 required 环境设备明确阻塞，对零配置明确通过；真实探针接入必须由 composition root 注入，不能把逻辑注册当物理设备成功。

## 强屏障顺序

1. 冻结 `DeviceProfileSnapshot` 和 track manifest。
2. 执行 presence、媒体、模型、课程、资源、语音和设备检查。
3. required 全部 success 后调用 `CapturePort.start`/旧 recorder adapter。
4. 验证每条 required track 首帧/首音频块和文件可写；客户端探针和自报计数不是证据，失败就 stop + release。
5. 之后才允许播放课程资源、追加题目窗口和进入分析/对话主流程。
6. finalize 只停止整场 session 一次，写完 timeline/meta 后才报告完成。

当前代码已提供可注入、可回滚的 `PreflightOrchestrator` 强屏障；strict legacy adapter 已具备服务端正式样本二次确认。下一步仍须把真实 Runtime/ambient broker 和每路轨道的首样本结果接入该 orchestrator，不能在没有真实探针时扩大 strict 默认范围。
