# Server 配置控制台 API（最小说明）

用于 `server` 页面管理分析配置（`config/analyzers.yaml` + 运行时内存配置）。

## 1) 获取当前配置

- `GET /api/server/config`
- 返回：

```json
{
  "success": true,
  "config": { "global": {}, "analyzers": {}, "matchers": {} },
  "configPath": "config/analyzers.yaml"
}
```

## 2) 更新配置（内存）

- `PUT /api/server/config`
- 请求体：

```json
{
  "replace": true,
  "actor": "server_ui",
  "config": {
    "global": { "mode": "mock" },
    "analyzers": {},
    "matchers": {}
  }
}
```

- 说明：
  - `replace=true`：整体替换（要求包含 `global/analyzers/matchers`）
  - `replace=false`：局部合并更新
  - `actor`：可选，写入审计日志（默认 `server_console`）
  - 后端会按 analyzer/matcher 类型做字段校验与范围校验

## 3) 保存到 YAML

- `POST /api/server/config/save`
- 可选请求体：

```json
{ "path": "config/analyzers.yaml" }
```

## 4) 恢复默认配置（内存）

- `POST /api/server/config/reset-defaults`
- 可选请求体：

```json
{ "applyEnvOverrides": false, "actor": "server_ui" }
```

## 5) 回滚到上一版快照

- `POST /api/server/config/rollback`
- 说明：
  - 回滚到最近一次快照（配置更新、替换、恢复默认都会自动生成快照）
  - 无快照时返回 400
- 可选请求体：

```json
{ "actor": "server_ui" }
```

## 6) 应用影响预检

- `GET /api/server/config/apply-preview`
- 返回：
  - `activeSessionCount`
  - `activeSessionIds`
  - `requiresForceForActiveReload`
  - `restartRequiredHint`

## 7) 应用到运行时

- `POST /api/server/config/apply`
- 请求体：

```json
{ "scope": "new_sessions_only", "force": false }
```

- `scope` 取值：
  - `new_sessions_only`：只影响后续新会话
  - `active_sessions`：重载流水线，尝试让运行中会话也生效
  - `restart_required`：标记需重启后生效（适合底层依赖切换）
- `force` 说明：
  - 当 `scope=active_sessions` 且存在活跃会话时，需要 `force=true`
  - 否则接口返回 `409`，并带 `requiresForce=true` 和影响会话信息

## 8) 获取控制台状态

- `GET /api/server/status`
- 返回：
  - `statistics`：分析服务统计
  - `sessions`：会话状态快照
  - `modelStatus`：`model_path` 文件存在性检查
  - `globalMode`：当前全局模式
  - `snapshotCount`：可回滚快照数量
  - `historyCount`：审计日志条目数

## 9) 获取配置变更历史

- `GET /api/server/config/history?limit=80`
- 说明：
  - 返回最近配置变更审计日志
  - 包含 `timestamp`、`actor`、`action`、`changedPaths`、`changedCount`

## 10) 获取预设模板

- `GET /api/server/presets`
- 返回内置模板名称：
  - `classroom_stable`
  - `dev_real`
  - `mock_only`

## 11) 应用预设模板

- `POST /api/server/presets/apply`

```json
{
  "presetName": "classroom_stable",
  "actor": "server_ui"
}
```

## 12) 获取诊断指标

- `GET /api/server/diagnostics`
- 返回：
  - `diagnostics.runtime_sec`
  - `diagnostics.analyzers.<name>.error_rate`
  - `diagnostics.analyzers.<name>.avg_latency_ms`
  - `diagnostics.analyzers.<name>.throughput_per_sec`
  - `diagnostics.analyzers.<name>.last_error`（最近一次错误信息，可能为空）

## 错误格式

常见错误返回：

```json
{
  "success": false,
  "error": "错误描述"
}
```

字段校验失败返回：

```json
{
  "success": false,
  "errors": ["analyzers.pose.sample_rate 不能大于 1.0"]
}
```

