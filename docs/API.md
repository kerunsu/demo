# MVP 接口定义（API）

## 1. 约定

- Base URL：`/api`
- 数据格式：`application/json`
- 时间字段：ISO 8601
- 响应结构：

```json
{
  "success": true,
  "data": {},
  "error": null
}
```

失败示例：

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "SESSION_NOT_FOUND",
    "message": "Session not found"
  }
}
```

## 2. 会话与流程接口

## 2.1 开始会话

- `POST /session/start`

请求：

```json
{
  "childName": "Tom",
  "courseType": "matching"
}
```

响应：

```json
{
  "success": true,
  "data": {
    "sessionId": "sess_123",
    "state": "TRAINING_ACTIVE",
    "startedAt": "2026-05-16T14:00:00.000Z"
  },
  "error": null
}
```

## 2.2 获取会话状态

- `GET /session/:sessionId`

返回当前状态、进度、已答题统计。

## 3. 课程接口

## 3.1 获取当前题目

- `GET /course/:sessionId/current`

响应：

```json
{
  "success": true,
  "data": {
    "questionId": "q_001",
    "courseType": "matching",
    "index": 1,
    "total": 5,
    "prompt": "把动物和食物配对",
    "payload": {
      "leftItems": ["猫", "兔子"],
      "rightItems": ["胡萝卜", "鱼"]
    }
  },
  "error": null
}
```

## 3.2 提交答案

- `POST /course/:sessionId/answer`

请求：

```json
{
  "questionId": "q_001",
  "answer": {
    "pairs": [
      { "left": "猫", "right": "鱼" },
      { "left": "兔子", "right": "胡萝卜" }
    ]
  },
  "responseTimeMs": 4200
}
```

响应：

```json
{
  "success": true,
  "data": {
    "correct": true,
    "feedback": "太棒了，继续下一题！",
    "hint": null,
    "nextAction": "NEXT_QUESTION",
    "courseCompleted": false
  },
  "error": null
}
```

错误两次触发提示时：

```json
{
  "success": true,
  "data": {
    "correct": false,
    "feedback": "再想一想哦",
    "hint": "可以先从最熟悉的图片开始配对",
    "nextAction": "RETRY_SAME_QUESTION",
    "courseCompleted": false
  },
  "error": null
}
```

## 4. 对话接口

## 4.1 发送对话消息

- `POST /chat/:sessionId/message`

请求：

```json
{
  "text": "我有点不会"
}
```

响应：

```json
{
  "success": true,
  "data": {
    "reply": "没关系，我们一步一步来，你可以先试试看第一个。",
    "strategy": "encourage_and_hint",
    "timestamp": "2026-05-16T14:10:00.000Z"
  },
  "error": null
}
```

说明：`strategy` 便于后续分析模板效果。

## 5. 报告接口

## 5.1 生成报告

- `POST /report/:sessionId/generate`

响应：

```json
{
  "success": true,
  "data": {
    "reportId": "rep_123",
    "sessionId": "sess_123",
    "status": "READY"
  },
  "error": null
}
```

## 5.2 查询报告

- `GET /report/:sessionId`

响应中的 `data` 结构遵循 `docs/REPORT_SCHEMA.md`。

## 6. 健康检查与日志（可选但建议）

- `GET /health`：服务健康状态
- 后端日志事件：
  - `session_started`
  - `answer_submitted`
  - `hint_triggered`
  - `chat_replied`
  - `report_generated`
