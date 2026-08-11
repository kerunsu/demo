# 第二阶段：Composition Root 与生命周期

## 1. 当前与目标

当前生产入口仍为 `app.py`：导入时加载 `.env`、创建 Flask/SocketIO、初始化 SQLAlchemy、注册 Blueprint、创建媒体/分析/反馈/触发/音频/机器人/对话服务并注册 Socket。该行为属于既有兼容事实，第二阶段不通过重写入口改变它。

新增 `app/facade/bootstrap.py` 提供无副作用的应用层容器：

```text
app.py
 ├─ 按旧顺序创建 Flask、SocketIO、DB 和现有单例
 ├─ create_application_container()
 │   ├─ clock = SystemClock
 │   └─ server_status_use_case = lazy factory
 ├─ 旧 route → facade use case + presenter
 └─ 旧 Socket 注册 → facade legacy adapter → 原 register_socket_events
```

容器只缓存显式绑定；它不导入 `app.py`、不创建 Flask、不开线程、不打开摄像头/麦克风、不建目录、不写 DB。`close()` 对已创建实例调用幂等 `close`，便于测试和未来进程生命周期管理。

## 2. 装配规则

1. Composition root 是唯一创建和连接基础设施的地方。
2. 业务用例只接受 Protocol/DTO 或显式输入，不从模块级 singleton 取依赖。
3. Legacy adapter 可以持有旧 singleton，但必须在 root 显式传入，不能让新领域模块局部 import `app.py`。
4. Socket/HTTP transport 由 facade 持有；领域服务只发布 `EventEnvelope`、`SpeechCommand` 或决策结果。
5. 每个线程、队列、设备和外部进程登记 owner、start、stop、close 和异常回调；重复 close 不得抛出二次清理错误。
6. 测试使用 fake clock、fake device、fake provider 和临时目录；不得依赖真实硬件或修改 `database/app.db`。

## 3. 首个切片的实际 wiring

`get_server_status` 的旧函数名和 route decorator 保持不变，仍由 phase1 测试通过 `view_functions["get_server_status"]` 观察。函数只组装当前已存在的状态读取依赖，调用 `ServerStatusUseCase.execute`，再调用 `present_server_status`；旧异常捕获和日志文本保持在 route。

`register_legacy_socket_events(socketio, register_socket_events)` 只调用旧注册函数一次。它没有新增事件、room、broadcast、ack 或线程，等后续每组事件 adapter 完成 characterization 后再替换传入的 legacy callable。

## 4. 关闭和回滚

本阶段回滚只需移除 `app.py` 对 facade container/presenter/use case/Socket adapter 的接线，并恢复旧 route 函数体；新 `app/facade` 与 `app/contracts` 不会覆盖旧 session、数据库、日志或媒体文件。建议把本阶段作为独立 Git checkpoint，再开始下一条 route/event 切片。

## 5. 进入下一切片的门槛

- status route 的字段级 fixture、runtime URL 快照和全量根测试继续通过。
- 验证容器导入不启动运行时资源；测试 teardown 无新增后台线程。
- 选下一个只读 route 或 report/monitor presenter，完成旧/新逐字段比较后再移动装饰器。
- `prepare_training`、`play_resource`、`finalize_training`、机器人互斥和环境设备在 facade adapter 具备完整生命周期测试前不得迁移。
