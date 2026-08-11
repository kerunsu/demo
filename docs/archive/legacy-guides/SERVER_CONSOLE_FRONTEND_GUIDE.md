# Server 前端使用说明

## 入口

| 页面 | URL | 用途 |
|------|-----|------|
| **配置中心** | `/server/config/overview`（及 camera/speech/report/content） | 改配置的主入口 |
| **实时监控** | `/server` 或 `/server?view=monitor` | 训练中 Snapshot 监控 |

旧 `/server?view=config`（高级 YAML）**已下线**，会重定向到配置中心概览。相关 API 仍保留。

## 配置中心 · 概览

- **运行时环境**（写入 `config/runtime_modes.yaml`，重启仍生效）
  - 默认：儿童媒体 `agent`、机械臂 `robot_runtime`
  - 修改下拉后「应用」才可点；一次保存两项
  - API：`GET/PUT /api/server/runtime-modes`（单项 PUT 仍可用且同样写盘）
- **analyzers 运维**
  - 预设模板、回滚、恢复默认
  - 默认发布作用域（存 localStorage，摄像头/语音「发布应用」读取）
- 只读：分析器摘要、模型文件检查、变更历史

## 摄像头 / 语音 / 报告

- **摄像头**：上块写 `camera_analysis.yaml`；下块 analyzers 视觉字段 +「高级参数」折叠；发布带 scope/preview
- **语音**：常用字段 + 高级参数（device/model_*）
- **报告**：五维权重和=100；写 `report_scoring.yaml`

## 推荐流程

1. 概览切好 mediaMode / 机械臂模式  
2. 摄像头或语音改参数 → 更新内存 → 保存 YAML → 发布应用（确认作用域）  
3. 需要持久化运行时模式时改环境变量后重启  

## active_sessions 注意

发布作用域选「运行中会话」时会走 apply-preview；有活跃会话会二次确认并 `force` 重载流水线，可能重置分析状态。日常优先「仅新会话」。
