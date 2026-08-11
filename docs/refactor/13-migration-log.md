# 第二阶段：迁移日志

## 1. 进入基线

| 项目 | 结果 |
|---|---|
| 分支 / HEAD | `add_voice` / `6836cbffa882e768912cb96e9d2f7bcd01f13d4c` |
| 初始工作区 | 129 项既有修改/未跟踪项；包含数据库、日志、构建缓存、pycache、`temp_clone` 和第一阶段交付物，均保留 |
| 进入基线 `python -m pytest tests -q` | `243 passed`（warnings only） |
| 第一阶段契约快照 | 143 源码 route、144 运行时 URL（含 implicit static）、57 Socket handler、53 literal emit |
| 产品代码搬迁 | 未搬迁训练、录制、Socket 业务、数据库、媒体、前端或 Runtime |

## 2. 本次施工内容

### 2.1 新增纯契约层

新增 `app/contracts/`：

- `models.py`：时间、session、设备、轨道、素材、交互、语音、事件、就绪和 server status DTO。
- `ports.py`：存储、采集、素材交互、计算、语音、机器人、事件和时钟 Protocol。
- `errors.py`：稳定错误分类。

该目录无 Flask、SocketIO、SQLAlchemy、数据库、cv2、PyAudio 等实现依赖。

### 2.2 新增门面骨架

新增 `app/facade/`：

- `application.py`：轻量可替换容器。
- `bootstrap.py`：`SystemClock` 和 lazy use case 注册，不拉起资源。
- `use_cases/server_status.py`：首个应用用例。
- `presenters/server_status.py`：旧 JSON 呈现。
- `sockets/registry.py`：旧 Socket 注册兼容 adapter。
- `routes/`、`sockets/` 包目录：后续逐条迁移位置。

新增 `app/acquisition/`、`app/computation/`、`app/storage/repositories/`、`app/storage/content_catalog/` 目标骨架；现有实现目录保留。

### 2.3 首条完整链路

已将 `/api/server/status` 的函数体接入：

```text
Flask route → ApplicationContainer → ServerStatusUseCase
→ ServerStatusSnapshot → presenter → 原 JSON response
```

并将主 Socket 注册调用包入兼容 adapter。原 route/event 名称、注册数量、响应字段、状态码、异常形态和初始化顺序均由 phase1 测试覆盖。

### 2.4 架构守卫

新增 `tests/test_phase2_architecture_guards.py`，检查：

- 目标目录存在且旧 `app.py`/`events.py` 未被删除。
- contracts 不依赖框架/数据库/硬件。
- 新 facade/acquisition/computation/storage 目标包遵守依赖禁区。
- 前端不导入服务端 DB、模型或设备实现模块。
- composition root lazy 创建，不新增线程或运行时资源。
- status vertical slice 的 presenter 字段与旧契约一致。
- Socket legacy adapter 只委托一次。

## 3. 验证结果

本阶段最终复跑结果：

- `python -m pytest tests -q`：`201 passed, 91 warnings`
- `python -m py_compile app.py app/contracts/models.py app/contracts/ports.py app/facade/bootstrap.py app/facade/routes/server_status.py app/facade/use_cases/server_status.py`：通过
- `python -m pytest tests/test_phase2_architecture_guards.py tests/test_phase1_contract_surface.py tests/test_phase1_http_contract_fixtures.py tests/test_phase1_runtime_contracts.py -q`：`19 passed`
- 根 tests 已包含 Flask test client + Socket.IO test client 的第一阶段黄金链路；status vertical slice 另由 HTTP fixture 和 presenter 测试覆盖。

任何基线失败都必须先与当前 `243 passed` 的进入基线比较；不能把新增失败标记为旧问题，也不能删除或放宽测试。

## 4. 未做事项与下一步

本次没有移动 `app/sockets/events.py`、`app/sockets/handlers.py`、`app/services/media_service.py`、`readiness_service.py`、`robot_service.py` 或任何前端/数据库/媒体实现。尚未接入 0..N 环境设备管理、批量素材导入、InteractionProfile V2、严格 preflight、模型 provider 或 DialogueUseCase；这些必须各自先有 characterization test 和兼容开关。

下一条建议切片是 `GET /api/monitor/snapshot` 的只读 presenter。训练生命周期、`play_resource`、Socket room/ack、行为互斥和录制文件名应继续保持 legacy adapter，直到双路径逐字段/逐事件测试完成。
