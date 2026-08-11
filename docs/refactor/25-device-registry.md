# 25. 设备注册表与控制端

## API

新版本化控制面：

- `GET /api/v2/capture/devices`：列出当前配置。
- `POST /api/v2/capture/devices`：新增一台 video/audio 设备；不传 `trackId` 时由 `deviceId + kind + role` 稳定生成。
- `PATCH /api/v2/capture/devices/{deviceId}`：修改 enabled/required/selector/format 等配置。
- `DELETE /api/v2/capture/devices/{deviceId}`：解除当前配置，返回 `historyPreserved=true`，不触碰历史 session。
- `POST /api/v2/capture/devices/discover`：调用注入的 discovery provider。
- `POST /api/v2/capture/snapshot`：冻结当前 enabled 设备和 DeploymentProfile，返回 `snapshotId`。

注册表默认原子持久化到 `config/capture_devices.json`，可用 `CAPTURE_DEVICE_REGISTRY_PATH` 覆盖（测试和 CI 必须指向临时目录）。损坏配置不会静默回退为空清单，而是使设备控制面/strict freeze 明确失败，防止 required 设备被误当成“零配置”。写入失败时内存修改回滚。

旧 `/api/monitor/ambient/devices`、control、preview 保持原行为，作为单实例兼容适配。新增 API 只改变未来 session 的配置；已经冻结的 session 使用自己的 snapshot，控制端的增删改不会热切换正在采集的轨道。

## 身份和约束

设备配置和历史事实分离：unregister 只删除 registry 配置，不删除录音、timeline、meta 或报告。`trackId` 不依赖数组顺序；primary environment 第一轨继续映射到兼容文件名，后续轨按 stable trackId 命名。不同设备若产生同一物理文件名，prepare 直接拒绝，不能静默覆盖。

真实设备打开、探测和预览必须由 `DeviceBroker`/`DeviceDiscoveryPort` 提供。默认 `CallbackDeviceBroker` 未注入真实探针时 fail closed；API 本身不打开摄像头、麦克风、不启动线程，也不创建媒体文件。当前控制面还没有设备级 test endpoint，不能把 discover/register 响应解释为硬件自检通过。
