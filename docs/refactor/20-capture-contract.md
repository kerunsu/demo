# 20. 采集契约

## 范围

采集块负责浏览器帧/音频块、Robot Runtime 上行与补传、服务端环境摄像头/麦克风以及设备健康状态。它不决定 session 目录、评分、报告或对话内容。当前旧实现仍由 `app.recorder`、`app.queue`、`app.services.media_service`、`app.monitor.ambient_camera` 和 `/api/media` 提供；第三阶段新增的是稳定端口和适配边界，不替换这些实现。

## 稳定数据

`CapturePacket` 的最小字段为 `source`、`session`、`sequence`、`monotonic_ns`、`relative_ms`、`wall_time_iso`、`format`、`payload`、`quality` 和 `status`。`source` 至少携带 `source_type`、`owner`、`device_id`、`track_id`、`runtime_id`。payload 可以是内存块，也可以是隔离的临时 artifact 引用；采集层不解释落盘文件名。

`DeviceProfile` 支持 0..N 路设备，身份由稳定 `device_id` 和 `track_id` 表示，不使用设备数组下标。设备有 `enabled`、`required`、`owner`、`runtime_id`、`selector`、`format` 和 `capabilities`。一次训练通过 `DeviceProfileSnapshot` 冻结配置；训练中编辑注册表不会改变该快照。配置由 `DeviceProfileStore` 原子持久化；重复 `trackId`、不安全 ID、非法 kind/布尔值必须在控制面拒绝。

## 兼容入口

以下接口保持原路径、方法和 payload：浏览器/Agent 的 `/record/start`、`/record/stop`、预览、帧/音频块上行、`/api/media/<session_id>/upload`、Socket 的 `video_frame`/`audio_chunk` 以及 Runtime OSC/update。旧环境单实例接口 `/api/monitor/ambient/*` 也保持不变。新的多设备控制面使用版本化 `/api/v2/capture/*`，不会让旧前端感知内部 DTO。

## 生命周期

默认 payload 不变，继续执行旧的 prepare warmup 行为。显式携带 `preflightMode: "strict"` 或 `strictPreflight: true` 时，prepare 只建立训练/媒体身份和目录计划，返回 `preflightOnly: true`、`captureStarted: false`，不会启动旧 recorder 或 media service；就绪门通过后才调用正式采集适配器。取消未启动的严格会话只撤销应用会话，不伪造媒体文件。

`PreflightOrchestrator` 是可注入的强门禁实现：required 检查全部 success 后才能调用 `CapturePort.start`；启动返回的每一条 required track 必须有首样本，否则调用 stop 并释放已预留设备。重复 start/stop 是幂等的。线上 strict 兼容路径采用两阶段确认：先打开旧 recorder 并定向通知对应儿童端，再由服务端已接收的正式帧/块确认 M2；预检探针帧和客户端自报计数不能越过第二道屏障。当前完整多设备 broker/capture adapter 尚未接入，不得把注册成功当成硬件或多轨采集成功。
