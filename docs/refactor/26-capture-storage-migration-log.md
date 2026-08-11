# 26. 第三阶段迁移日志

## 已完成

- 新增 `DeviceProfile`、`DeviceProfileSnapshot`、`CapturePacket`、`PreflightCheck/Result` 及采集/存储 Protocol。
- 新增线程安全 `InMemoryDeviceRegistry`、稳定 track ID、注入式 `CallbackDeviceBroker` 和 `TimebaseMapper`。
- 新增 `SessionLayout`：保留 `video.avi`、`audio.wav`、环境兼容轨、timeline/meta/archive 文件名，并为额外环境轨提供稳定名称。
- 新增原子 JSON/CSV repository 和只读 `validate_session_directory`。
- 新增 `/api/v2/capture/*` 控制面；旧 ambient 和 Runtime/media API 未改名。
- 新增显式 strict prepare/readiness 分支；默认 legacy warmup 测试保持通过。
- 新增 `tests/test_phase3_capture_storage_contracts.py` 和 `tests/test_phase3_device_control_api.py`，均使用 fake/临时目录。
- 更新 phase1 runtime contract snapshot，明确新增 6 条版本化路由；原有 route/event 条目未删除。
- 设备配置接入原子 JSON store；配置损坏 fail closed，保存失败回滚内存，discover DTO 已兼容 `DeviceRef`。
- registry/repository/layout 增加并发保护、ID/track/file 校验；timeline 和 recording finalize 修正开放段与单调时长语义。
- strict 线上路径改为“启动请求 → 儿童端确认 → 服务端正式样本确认 → 教师端完成”的两阶段屏障；客户端 probe/count 不可使正式采集假绿。
- 审查后全量基线为 `218 passed`；新增审查结论见 `27-phase3-review.md`。

## 未完成且下一步准确入口

1. 将真实 ambient camera/mic、浏览器和 Robot Runtime 统一接到 `DeviceBroker`，入口为 `ReadinessService.set_device_preflight_callback`。
2. 将 strict 线上启动从 `start_preflight_capture` legacy adapter 接到 `PreflightOrchestrator.start_barrier`，并让每路 Runtime/recorder 返回按 trackId 区分的可验证首样本（当前只确认旧主上行）。
3. 将旧 `recording_timeline.py` 的 wall-clock offset 替换为 TimebaseMapper adapter，先做双写对照，不能直接改历史 CSV。
4. 让 late upload 写入统一 manifest/checksum repository，同时保留现有 `archive_meta.json` 字段形态。
5. 为控制端增加设备级自检结果、轨道时间轴和 session validator 可视化；本阶段 API 只提供稳定数据。

## 回滚边界

移除 `/api/v2/capture` 注册和 strict 可选字段即可恢复旧入口；legacy prepare、旧文件名、媒体上传、Runtime endpoint 和原 tests 不依赖新 repository。任何新 adapter 失败均应回到旧函数，不得通过修改旧断言掩盖差异。
