# 评估报告 Schema（MVP）

## 1. 设计原则

- 字段结构化、可稳定生成
- 同时兼容前端展示与后端统计
- 对话摘要保留最小必要信息

## 2. TypeScript Interface

```ts
export interface TrainingReport {
  reportId: string;
  sessionId: string;
  childName?: string;
  courseType: "matching" | "ordering" | "mixed";
  startedAt: string; // ISO 8601
  completedAt: string; // ISO 8601
  durationSec: number;
  summary: {
    totalQuestions: number;
    correctAnswers: number;
    accuracy: number; // 0-1
    averageResponseTimeMs: number;
  };
  errorStats: {
    totalWrongAttempts: number;
    byType: Array<{
      errorType: "mismatch" | "wrong_order" | "timeout" | "invalid_input" | "other";
      count: number;
    }>;
  };
  questionResults: Array<{
    questionId: string;
    correct: boolean;
    attempts: number;
    responseTimeMs: number;
    errorType?: string;
  }>;
  chatSummary: {
    totalMessages: number;
    childMessageCount: number;
    botMessageCount: number;
    keywords: string[];
    highlights: string[];
  };
  generatedAt: string; // ISO 8601
  version: "v1";
}
```

## 3. JSON Schema（Draft 2020-12）

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://demo.local/schemas/training-report.v1.json",
  "title": "TrainingReport",
  "type": "object",
  "required": [
    "reportId",
    "sessionId",
    "courseType",
    "startedAt",
    "completedAt",
    "durationSec",
    "summary",
    "errorStats",
    "questionResults",
    "chatSummary",
    "generatedAt",
    "version"
  ],
  "properties": {
    "reportId": { "type": "string", "minLength": 1 },
    "sessionId": { "type": "string", "minLength": 1 },
    "childName": { "type": "string" },
    "courseType": {
      "type": "string",
      "enum": ["matching", "ordering", "mixed"]
    },
    "startedAt": { "type": "string", "format": "date-time" },
    "completedAt": { "type": "string", "format": "date-time" },
    "durationSec": { "type": "number", "minimum": 0 },
    "summary": {
      "type": "object",
      "required": ["totalQuestions", "correctAnswers", "accuracy", "averageResponseTimeMs"],
      "properties": {
        "totalQuestions": { "type": "integer", "minimum": 0 },
        "correctAnswers": { "type": "integer", "minimum": 0 },
        "accuracy": { "type": "number", "minimum": 0, "maximum": 1 },
        "averageResponseTimeMs": { "type": "number", "minimum": 0 }
      },
      "additionalProperties": false
    },
    "errorStats": {
      "type": "object",
      "required": ["totalWrongAttempts", "byType"],
      "properties": {
        "totalWrongAttempts": { "type": "integer", "minimum": 0 },
        "byType": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["errorType", "count"],
            "properties": {
              "errorType": {
                "type": "string",
                "enum": ["mismatch", "wrong_order", "timeout", "invalid_input", "other"]
              },
              "count": { "type": "integer", "minimum": 0 }
            },
            "additionalProperties": false
          }
        }
      },
      "additionalProperties": false
    },
    "questionResults": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["questionId", "correct", "attempts", "responseTimeMs"],
        "properties": {
          "questionId": { "type": "string" },
          "correct": { "type": "boolean" },
          "attempts": { "type": "integer", "minimum": 1 },
          "responseTimeMs": { "type": "number", "minimum": 0 },
          "errorType": { "type": "string" }
        },
        "additionalProperties": false
      }
    },
    "chatSummary": {
      "type": "object",
      "required": ["totalMessages", "childMessageCount", "botMessageCount", "keywords", "highlights"],
      "properties": {
        "totalMessages": { "type": "integer", "minimum": 0 },
        "childMessageCount": { "type": "integer", "minimum": 0 },
        "botMessageCount": { "type": "integer", "minimum": 0 },
        "keywords": {
          "type": "array",
          "items": { "type": "string" }
        },
        "highlights": {
          "type": "array",
          "items": { "type": "string" }
        }
      },
      "additionalProperties": false
    },
    "generatedAt": { "type": "string", "format": "date-time" },
    "version": { "type": "string", "const": "v1" }
  },
  "additionalProperties": false
}
```

## 4. 示例数据（精简）

```json
{
  "reportId": "rep_001",
  "sessionId": "sess_001",
  "courseType": "matching",
  "startedAt": "2026-05-16T14:00:00.000Z",
  "completedAt": "2026-05-16T14:08:30.000Z",
  "durationSec": 510,
  "summary": {
    "totalQuestions": 5,
    "correctAnswers": 4,
    "accuracy": 0.8,
    "averageResponseTimeMs": 3900
  },
  "errorStats": {
    "totalWrongAttempts": 3,
    "byType": [{ "errorType": "mismatch", "count": 3 }]
  },
  "questionResults": [
    {
      "questionId": "q_001",
      "correct": true,
      "attempts": 1,
      "responseTimeMs": 3200
    }
  ],
  "chatSummary": {
    "totalMessages": 4,
    "childMessageCount": 2,
    "botMessageCount": 2,
    "keywords": ["不会", "再试试"],
    "highlights": ["孩子在第2题请求帮助，系统给出分步提示。"]
  },
  "generatedAt": "2026-05-16T14:08:31.000Z",
  "version": "v1"
}
```
