# 领域事件契约 V2

本文是未来事件契约草案，不实现业务代码。

## 1. 通用事件字段

每个事件必须包含：

| 字段 | 说明 |
| -- | -- |
| `eventId` | 全局唯一事件 ID。 |
| `eventType` | 事件类型，使用大写枚举。 |
| `sessionId` | 会话 ID。 |
| `timestamp` | ISO 8601 时间。 |
| `source` | `child_screen`、`robot_screen`、`backend`、`speech_pipeline`、`assessment_engine` 等。 |
| `correlationId` | 同一用户动作或语音 turn 的关联 ID。 |
| `causationId` | 触发当前事件的上游事件 ID。 |
| `payload` | 事件负载，按事件类型定义。 |
| `schemaVersion` | 契约版本，例如 `v1`. |
| `idempotencyKey` | 命令型事件可带，用于重复提交去重。 |
| `persist` | 是否需要持久化。 |

## 2. TypeScript 类型草案

```ts
export type DomainEventSource =
  | "child_screen"
  | "robot_screen"
  | "backend"
  | "speech_pipeline"
  | "assessment_engine"
  | "safety_gateway";

export type DomainEventType =
  | "SESSION_STARTED"
  | "SESSION_ENDED"
  | "QUESTION_PRESENTED"
  | "ANSWER_SUBMITTED"
  | "ANSWER_EVALUATED"
  | "FEEDBACK_REQUESTED"
  | "ANIMATION_REQUESTED"
  | "ANIMATION_STARTED"
  | "ANIMATION_FINISHED"
  | "LISTENING_STARTED"
  | "LISTENING_FINISHED"
  | "TRANSCRIPT_READY"
  | "LLM_REPLY_REQUESTED"
  | "LLM_REPLY_GENERATED"
  | "SAFETY_REVIEW_PASSED"
  | "SAFETY_REVIEW_REJECTED"
  | "TTS_STARTED"
  | "TTS_FINISHED"
  | "ATTENTION_OBSERVATION_RECORDED"
  | "LANGUAGE_OBSERVATION_RECORDED"
  | "ASSESSMENT_UPDATED"
  | "REPORT_GENERATED"
  | "CLIENT_CONNECTED"
  | "CLIENT_DISCONNECTED";

export interface DomainEvent<TPayload = Record<string, unknown>> {
  eventId: string;
  eventType: DomainEventType;
  sessionId: string;
  timestamp: string;
  source: DomainEventSource;
  correlationId: string;
  causationId?: string;
  payload: TPayload;
  schemaVersion: "v1";
  idempotencyKey?: string;
  persist: boolean;
}
```

## 3. 事件清单

| eventType | 典型 payload | 幂等要求 | 持久化 |
| -- | -- | -- | -- |
| `SESSION_STARTED` | `childAlias`, `courseQueue`, `startedAt` | 同一 start request 只能建一个 session | 是 |
| `SESSION_ENDED` | `reason`, `endedAt` | 重复结束返回同一结果 | 是 |
| `QUESTION_PRESENTED` | `questionId`, `courseType`, `index`, `total`, `prompt` | 同一题重复展示不重复计数 | 是 |
| `ANSWER_SUBMITTED` | `questionId`, `selectedOptionId`, `responseTimeMs`, `attemptIndex` | `idempotencyKey` 防重复点击 | 是 |
| `ANSWER_EVALUATED` | `questionId`, `correct`, `wrongType`, `nextAction`, `hintId` | 同一答案提交返回同一判题 | 是 |
| `FEEDBACK_REQUESTED` | `feedbackKind`, `text`, `requiresSpeech`, `animationIntent` | 与判题事件一一关联 | 是 |
| `ANIMATION_REQUESTED` | `commandId`, `animationId`, `intent`, `priority`, `interruptPolicy` | `commandId` 去重 | 是 |
| `ANIMATION_STARTED` | `commandId`, `animationId`, `startedAt` | 重复 ACK 忽略 | 可选 |
| `ANIMATION_FINISHED` | `commandId`, `status`, `durationMs`, `errorCode` | 重复完成忽略 | 可选 |
| `LISTENING_STARTED` | `turnId`, `mode`, `deviceIdHash` | 同一 turn 不重复启动 | 是 |
| `LISTENING_FINISHED` | `turnId`, `reason`, `durationMs` | 重复结束忽略 | 是 |
| `TRANSCRIPT_READY` | `turnId`, `transcriptRedacted`, `confidence`, `language` | 同一 audio segment 只产一条 final | 是 |
| `LLM_REPLY_REQUESTED` | `turnId`, `provider`, `contextVersion` | `turnId` 去重 | 是 |
| `LLM_REPLY_GENERATED` | `turnId`, `provider`, `replyDraft`, `latencyMs` | 同一 request 只采用首个成功结果 | 是 |
| `SAFETY_REVIEW_PASSED` | `targetEventId`, `reviewer`, `policyVersion` | 审核结果不可由客户端伪造 | 是 |
| `SAFETY_REVIEW_REJECTED` | `targetEventId`, `reason`, `fallbackText`, `policyVersion` | 拒绝结果优先级最高 | 是 |
| `TTS_STARTED` | `turnId`, `provider`, `textHash`, `voice` | 同一已审核文本不重复合成 | 是 |
| `TTS_FINISHED` | `turnId`, `audioRef`, `durationMs`, `mimeType` | 重复完成忽略 | 是 |
| `ATTENTION_OBSERVATION_RECORDED` | `observationId`, `kind`, `durationMs`, `confidence`, `quality` | `observationId` 去重 | 是 |
| `LANGUAGE_OBSERVATION_RECORDED` | `observationId`, `sourceTurnId`, `feature`, `value`, `quality` | `observationId` 去重 | 是 |
| `ASSESSMENT_UPDATED` | `assessmentId`, `metricVersion`, `metrics`, `dataQuality` | 同一输入版本产一份结果 | 是 |
| `REPORT_GENERATED` | `reportId`, `reportVersion`, `generatedAt` | 同一完成 session 重复返回已有报告 | 是 |
| `CLIENT_CONNECTED` | `clientId`, `screenRole`, `lastSeenEventId` | 心跳重复可覆盖 | 可选 |
| `CLIENT_DISCONNECTED` | `clientId`, `screenRole`, `reason` | 心跳超时只记录状态变化 | 可选 |

## 4. 持久化策略

- 业务事实事件必须持久化：会话、题目、答题、评估、报告、安全审核。
- 客户端在线状态可选持久化，但至少要进入运行日志。
- 音频、视频、聊天原文不默认进入事件 payload；使用脱敏文本、哈希或外部受控引用。
- 事件 schema 变更必须增加版本，旧事件不可静默改写。
