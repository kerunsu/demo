# 行为检测与评估数据模型 V2

本文设计数据模型，不定义正式专业评分规则。

## 1. 分层原则

1. 数据采集记录事实。
2. 特征提取描述可计算信号。
3. 指标计算使用明确算法和版本。
4. 报告解释基于结构化指标生成。
5. LLM 不生成核心定量分数。

## 2. 原始观测

| 观测 | 字段示例 | 来源 |
| -- | -- | -- |
| `session_started` | sessionId、childAlias、courseQueue、device | 后端 |
| `question_shown` | questionId、courseType、index、prompt、shownAt | 后端事件 |
| `answer_attempted` | attemptId、selectedOptionId、isCorrect、latencyMs、wrongType | 儿童屏/后端 |
| `hint_shown` | hintId、triggerReason、hintLevel、shownAt | 后端 |
| `chat_message` | role、redactedText、strategy、provider、timestamp | 语音/聊天 |
| `voice_event` | turnId、mode、startedAt、finishedAt、sttStatus | 语音管线 |
| `attention_event` | kind、durationMs、confidence、quality | 摄像头 Mock 或行为信号 |
| `focus_event` | tabHidden、idleStart、idleEnd | 儿童屏 |

## 3. 特征

| 维度 | 特征 |
| -- | -- |
| 注意力 | 连续无操作时长、题间停顿、长尾响应、离屏、提示后是否回到任务。 |
| 语言表达 | 儿童消息数、平均长度、求助词、否定或挫败表达、主动提问。 |
| 答题表现 | 首答正确、最终正确、错误尝试次数、错误类型、同类题错误聚集。 |
| 响应时间 | 首答反应时、最终完成时长、尝试间隔、题间准备时长。 |
| 提示依赖 | 提示次数、提示等级、提示后正确率、无提示正确率。 |
| 数据质量 | 设备不可用、低置信度、缺失观测、异常延迟。 |

## 4. 时间窗口

- 题目窗口：单题从 `QUESTION_PRESENTED` 到题目完成。
- 尝试窗口：每次答案提交之间的时间。
- 课程阶段窗口：每 N 题或按课程类别分段。
- 会话窗口：从 `SESSION_STARTED` 到 `SESSION_ENDED`。

窗口必须记录开始、结束、输入事件范围和算法版本。

## 5. 题目级指标

```ts
export interface QuestionMetric {
  questionId: string;
  firstAttemptCorrect: boolean;
  eventualCorrect: boolean;
  attempts: number;
  wrongAttempts: number;
  firstResponseMs?: number;
  solveTimeMs?: number;
  hintCount: number;
  hintUsedBeforeCorrect: boolean;
  idleMs?: number;
  chatDuringQuestionCount: number;
  dataQuality: DataQualityFlag[];
  metricVersion: string;
}
```

## 6. 课程级指标

```ts
export interface CourseMetric {
  sessionId: string;
  courseType: "matching" | "ordering" | "mixed";
  totalQuestions: number;
  firstTryAccuracy: number;
  eventualAccuracy: number;
  medianResponseMs?: number;
  p90ResponseMs?: number;
  wrongAttemptsByType: Record<string, number>;
  hintDependencyRate: number;
  completionDurationSec: number;
  languageSummary?: LanguageMetric;
  attentionSummary?: AttentionMetric;
  dataQuality: DataQualityFlag[];
  metricVersion: string;
  ruleVersion?: string;
}
```

## 7. 注意力

当前阶段建议只称为“任务参与度/响应稳定性”，除非专业人员确认注意力定义和算法。可用输入：

- 无操作时长。
- 题间停顿。
- 页面可见性。
- 摄像头 Mock 的 `face_present`、`looking_away`、`no_face`。

禁止把这些信号直接解释为临床注意力障碍。

## 8. 语言表达

语言指标先做描述性统计：

- 儿童主动表达次数。
- 求助表达次数。
- 平均句长。
- 低置信度转写比例。
- 安全审核拒绝或脱敏类别。

正式语言能力评分需要专业规则。

## 9. 答题表现

当前可复用指标：

- 总题数。
- 首答正确数。
- 正确率。
- 平均响应时长。
- 错误类型统计。
- 尝试次数。

需要新增：

- 首答反应时和最终完成时长分离。
- 每次尝试记录。
- 题库元数据和难度标签。

## 10. 提示依赖

提示依赖应记录：

- 提示触发原因。
- 提示等级。
- 提示前错误次数。
- 提示后是否正确。
- 提示后响应时间变化。

提示等级和解释边界需专业确认。

## 11. 数据质量、缺失和设备不可用

每项指标必须带数据质量：

- `complete`
- `partial`
- `missing_device`
- `low_confidence`
- `timeout`
- `manual_override`

设备不可用时不得伪造指标，应在报告中说明缺失。

## 12. 算法版本和规则版本

- `algorithmVersion`：特征提取或指标计算代码版本。
- `ruleVersion`：专业规则、阈值和权重版本。
- `schemaVersion`：数据结构版本。

报告必须引用这些版本。

## 13. 可追溯性

每个报告指标应能追溯到：

- 输入观测事件 ID 范围。
- 特征版本。
- 指标算法版本。
- 规则版本。
- 数据质量标记。

## 14. 报告如何引用指标

报告文案应写：

- “本次训练中，首答正确率为 X。”
- “在可用观测范围内，任务参与事件显示 Y。”
- “该结论基于 `metricVersion` 和 `ruleVersion`。”

报告文案不应写：

- “超过同龄常模”，除非有真实常模。
- “深度诊断”，除非产品和专业资质确认。
- “注意力障碍/语言障碍”等诊断性结论。

## 15. 需专业人员提供的评分规则

1. 注意力/任务参与度定义和阈值。
2. 语言表达能力定义和阈值。
3. 响应时间的年龄段标准。
4. 提示依赖等级。
5. 错误类型到能力解释的映射。
6. 综合分权重。
7. 常模或百分位数据来源。
8. 报告建议语料和禁用措辞。
