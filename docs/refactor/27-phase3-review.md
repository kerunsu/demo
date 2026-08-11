# 27. 第三阶段审查与优化结论

## 结论

第三阶段的“契约骨架、兼容文件名、可选 strict 路径、设备控制面与存储适配器”可以验收；“0..N 环境设备真实录制、逐设备硬件自检、统一多轨首样本屏障”尚不能按已交付功能验收。旧默认流程未改变，全量测试为 `218 passed`。在完成下列阻塞项前，不应把 strict 设为默认，也不应向现场承诺多环境设备已经进入正式 session 数据集。

## 本次发现并已修复

- 设备注册表原为进程内状态：新增原子 JSON 持久化、损坏配置 fail closed、保存失败回滚。
- discovery 返回 `DeviceRef` 而 registry 只接受 `DeviceProfile`：增加规范转换并保留用户 required/role/track 配置。
- 默认 broker 在没有真实探针时可能形成逻辑成功：改为 fail closed，并补齐 check/reserve/release 并发所有权。
- strict legacy adapter 忽略 media service 的 `False`：现明确失败并回滚 timeline/session 状态。
- strict readiness 在打开 recorder 后立即向教师端宣布成功：改成两阶段正式样本屏障，并拒绝客户端 probeFrame/frameCount/hasRecentUplink 充当服务端证据。
- timeline、metadata、recording repository 存在并发和开放段时长风险：增加锁、边界校验、开放段闭合与单调时长计算。
- validator 对畸形 manifest 可能抛异常且未检查重叠：改为只读结构化错误报告。

## 尚存阻塞项

1. `app.monitor.ambient_camera` 仍是单摄像头 singleton，环境麦克风没有对应的多实例采集服务；新 registry 目前只管理配置。
2. `ReadinessService.set_device_preflight_callback` 尚未接入真实 Server/Runtime 逐设备 probe；required 设备会正确阻塞，但无法在生产中通过。
3. strict 线上启动仍走旧 recorder adapter，尚未使用 `PreflightOrchestrator` 的按轨 reserve/start/first-sample/rollback 全链路。
4. `session_meta.tracks` 的多轨 manifest 尚未由旧实时录制生命周期持续写入；新增 filename 规则目前只在新 repository/测试中成立。
5. `TimebaseMapper` 尚未接入浏览器、Runtime、环境设备的真实 packet ingestion；跨机器时钟校准与补传 sequence 仍是契约而非生产闭环。
6. 控制端缺少逐设备 test、实时质量、track timeline 和 validator 可视化。

## 下一步准确施工顺序

先实现可注入的 Server camera/audio 与 Runtime device probe，并用 fake hardware contract tests 固化错误码；再实现 legacy ambient/Runtime 到 `CapturePort` 的 adapter，确保第一路仍写兼容文件名；随后把 strict composition root 接到 `PreflightOrchestrator`，要求每个 required track 返回服务端首样本证据；最后增加控制端 test/quality 可视化。每一步继续保留 legacy 默认路径，adapter 异常不得降级成成功。
