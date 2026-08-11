# 第四阶段迁移日志

本阶段只增加稳定端口、兼容 adapter、V2 控制端入口和 characterization tests，没有移动既有计算/语音业务文件。

## 增量

- `app/computation/model_plugins.py`：descriptor、registry、real/mock 选择、超时、取消、背压和 degraded observation。
- `app/computation/interaction/`：16 个事件、V2 resolver、profile 发布校验、旧映射 dry-run 迁移。
- `app/dialogue/boundary.py`：`DialogueRequest/Response`、`DialogueGateway` 和 `LegacyDialogueAdapter`；旧 sockets 未切换。
- `app/robot/batch_asset_import.py`、`app/storage/repositories/asset_index.py`：动作/表情 staging、预览、提交、回滚、逻辑 assetId/version 与物理文件索引。
- `/api/v2/assets/*`、`/api/v2/interaction/*`：全是新增版本化接口，旧接口未重命名。

## 契约快照

新增 rollback 与 deploy 后，`contracts.snapshot.json` 为 143 条源码 route、144 条运行时规则（包含 implicit static），Socket 57 个注册事件和 53 个字面量 server emit 保持不变。

## 回滚

若新能力不可用，控制端不发布 profile，运行时自动使用 legacy MappingResolver；模型、TTS、资源索引异常均返回明确 degraded/error。删除新增 blueprint 注册即可停用新 HTTP 入口，不需触碰旧 sessions、数据库、录音录像或前端资源。

## 验证

新增 `tests/test_phase4_computation_dialogue_contracts.py` 和 `tests/test_phase4_asset_and_profile_api.py`。测试只使用 fake provider、临时目录和 Flask test client；批量导入测试会验证 0/1/N、预览、重复提交幂等、冲突和回滚。
