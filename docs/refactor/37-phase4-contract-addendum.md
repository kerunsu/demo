# 第四阶段契约补充

第四阶段新增 HTTP 入口：

| 方法 | 路径 | 成功核心字段 | 错误 |
|---|---|---|---|
| POST | `/api/v2/assets/batch-import` | `success,stage.stagingId,stage.items[]` | 400 |
| GET | `/api/v2/assets/batch-import/<id>` | `success,stage` | 404 |
| POST | `/api/v2/assets/batch-import/<id>/commit` | `success,stagingId,kind,items[]` | 400/404 |
| POST | `/api/v2/assets/batch-import/<id>/rollback` | `success,stagingId,status=rolled_back` | 404 |
| GET | `/api/v2/interaction/events` | `success,events[]` | — |
| POST | `/api/v2/interaction/events` | `success,event` | 400 |
| GET | `/api/v2/interaction/profiles/<course>` | `success,profile` | 404 |
| PUT | `/api/v2/interaction/profiles/<course>/draft` | `success,profile` | 400 |
| POST | `/api/v2/interaction/profiles/<course>/publish` | `success,profile` | 400/404 |
| POST | `/api/v2/interaction/profiles/<course>/rollback` | `success,profile` | 400/404 |
| POST | `/api/v2/interaction/resolve` | `success,plan` | 400 |

旧 HTTP/Socket 契约没有统一错误 DTO。新入口使用 `success` envelope，但不要求旧接口改用它。新增路由已同步 `contracts.snapshot.json` 的 `routes`、计数和 `runtimeDump`。

## 版本冻结

profile 只有曾经 `published` 才能被 resolver 使用；session 若携带 `profileVersion`，即使该历史版本后来标记为 `archived`，仍按冻结版本读取。控制端修改 draft 或发布新版本不会改变已冻结 session 的解析结果。
