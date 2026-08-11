# 系统架构说明

## 1. 总览

本仓库是一套**教育训练系统**：教师管理学生与课程、通过 WebSocket 驱动儿童端展示与采集；服务端完成媒体录制、分析流水线、结果反馈与可选机械臂/语音子系统。

需求与验收口径见 [PRD.md](PRD.md)。Socket 事件与 payload 契约见 [CONTRACT.md](CONTRACT.md)。

三条主链路：

1. **HTTP 页面与 REST API**：`app.py` 中路由与 `/api/*`，页面模板在 `templates/`，静态资源在 `static/`。
2. **Socket.IO 事件**：注册入口在 `app/sockets/`（主业务）、`app/sockets/robot_events.py`、`app/sockets/audio_events.py` 等；与 `teacher_frontend` 及 `static/js/child.js` 协同。
3. **媒体 → 分析 → 存储**：`app/services/media_service.py`、队列 `app/queue/`、`app/core/` 中分析器与流水线、`app/storage/` 持久化。

## 2. 后端包结构（`app/`）

| 目录/模块 | 职责 |
|-----------|------|
| `app/config.py` | 全局配置与环境变量 |
| `app/session/` | 会话模型与生命周期 |
| `app/sockets/` | Socket.IO 事件与 handler |
| `app/services/` | 媒体、分析、反馈服务编排 |
| `app/queue/` | 音视频与结果队列 |
| `app/recorder/` | 录制实现 |
| `app/core/` | 分析器/比对器注册表、`auto_register`、vision/audio 流水线、`trigger` |
| `app/storage/` | 分析结果存储 |
| `app/audio/` | 语音清单与播放控制 |
| `app/robot/` | 机械臂 HTTP API 与动作相关逻辑 |

更细的模块说明见同目录 [README.md](../app/README.md)。

## 3. 前端与入口

| 组件 | 说明 |
|------|------|
| `templates/child.html` + `static/js/child.js` | 儿童端：摄像头、iframe 互动课、`/static/...` 资源 |
| `teacher_frontend/` | 教师端 Vite + React，Socket 默认连 `127.0.0.1:8080` |
| `/sequencing`、`/matching` | 重定向至 `static/resources/interactive/` 下静态页，保留 query |

## 4. 配置与扩展点

- **分析器模式**：`config/analyzers.yaml` + `USE_REAL_ANALYZERS`。
- **新课程资源**：静态文件 + 数据库 `Course` / `CourseItem`（见数据库文档）。

## 5. 过程文档与归档

历史阶段规划、总结、BUG 记录已移至 [docs/archive/](archive/)，便于检索且不打乱根目录。
