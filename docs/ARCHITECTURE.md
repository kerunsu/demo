# 系统架构与模块边界（MVP）

## 1. 总体架构

采用前后端分离的单体部署结构：

- `frontend`：儿童端单界面应用（React + TS）
- `backend`：接口服务、训练会话、规则对话、报告生成（Express + TS）
- `docs`：需求、架构、流程、接口、数据 schema 文档

MVP 运行方式：本地两个进程（前端 dev server + 后端 API server）。

## 2. 目录建议

```text
Project/
  frontend/
    src/
      pages/
      components/
      services/
      store/
      types/
  backend/
    src/
      routes/
      controllers/
      services/
      engine/
      repositories/
      schemas/
      types/
      utils/
  docs/
```

## 3. 前端模块边界

### 3.1 页面层（pages）

- `WelcomePage`
- `CourseSelectPage`
- `CoursePlayPage`
- `ReportPage`

职责：页面编排与视图展示，不承载业务规则。

### 3.2 组件层（components）

- `QuestionCard`
- `FeedbackBanner`
- `ProgressBar`
- `ChatBox`

职责：可复用 UI 单元。

### 3.3 前端服务层（services）

- `apiClient`：HTTP 请求封装
- `sessionService`：会话开始/答题提交/下一题请求
- `chatService`：对话消息发送
- `reportService`：报告读取

职责：隔离接口调用细节，页面只调用 service。

## 4. 后端模块边界

### 4.1 路由层（routes）

按资源划分：

- `/api/session/*`
- `/api/course/*`
- `/api/chat/*`
- `/api/report/*`

### 4.2 控制器层（controllers）

负责参数校验、调用 service、返回统一响应。

### 4.3 业务服务层（services）

- `CourseEngineService`：题目推进、答题判定、提示触发
- `DialogueService`：规则+模板回复（可替换）
- `ReportService`：统计汇总与报告生成
- `SessionService`：会话生命周期管理

### 4.4 引擎与规则层（engine）

- `flowEngine`：自动推进规则
- `hintPolicy`：错误次数触发提示
- `encouragementPolicy`：正确后鼓励语

### 4.5 数据层（repositories）

MVP 采用：

- 内存仓储（运行态）
- JSON 文件落盘（报告）

接口化设计，后续可换数据库。

## 5. 关键设计决策

## 5.1 课程引擎独立

课程判题与推进放在后端 `CourseEngineService`，避免前端页面出现复杂逻辑分散。

## 5.2 对话服务独立

对话能力统一由 `DialogueService` 提供：

- `generateReply(input, context)`（当前规则模板实现）
- 预留替换为 LLM provider 的适配层

## 5.3 报告 schema 独立

报告字段集中在 `backend/src/schemas/report.schema.ts`（或 JSON schema），确保统计与展示一致。

## 5.4 状态机驱动流程

流程状态统一（WELCOME -> SELECTING -> TRAINING -> COMPLETED -> REPORT_READY），减少页面跳转分叉风险。

## 6. 运行时交互简图

1. 前端调用 `POST /session/start` 建立会话
2. 前端拉取首题 `GET /course/current`
3. 儿童答题 `POST /course/answer`
4. 后端返回判题结果 + 是否下一题 + 反馈语
5. 完成后后端生成报告 `POST /report/generate`
6. 前端展示 `GET /report/:sessionId`
7. 训练中可随时 `POST /chat/message`

## 7. 非功能要求（MVP）

- 响应可用：核心接口响应目标 < 500ms（本地）
- 稳定优先：异常时返回可读错误信息并保持会话可恢复
- 可观测性：基础日志（会话开始、答题、报告生成、错误）
