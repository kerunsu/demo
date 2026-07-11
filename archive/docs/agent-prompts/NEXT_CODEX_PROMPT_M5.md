# 下一轮 Codex Prompt：M5-001 统一行为观测契约与时间线基线

请执行第一个 M5 编码任务：

`M5-001 统一行为观测契约与时间线基线`

当前 M4 状态为：

`COMPLETE_CODE_WITH_ENVIRONMENT_PENDING`

M4 代码和自动化测试已完成；真实机器人双屏、麦克风、扬声器、局域网和现场噪声验收仍为 `ENVIRONMENT_PENDING`。该现场验收不阻塞 M5-001。

本轮只使用当前主 Agent，不创建或调用任何子 Agent。

## Git 自主管理

本轮 Git 操作由 Codex 自行完成：

1. 检查 `git status --short`、`git diff` 和最近 commit。
2. 保护无关修改。
3. 禁止使用 `git add .`。
4. 只暂存本轮相关文件。
5. 验证通过后创建本地 commit。
6. 不 push。
7. 不合并 main。

建议 commit message：

`M5-001: add behavior observation contract baseline`

## 开始前阅读

按顺序阅读：

1. `AGENTS.md`
2. `frontend/AGENTS.md`
3. `backend/AGENTS.md`
4. `docs/WORK_ITEMS_M5.md`
5. `docs/M5_TECHNICAL_DECISIONS.md`
6. `docs/BEHAVIOR_ASSESSMENT_DATA_MODEL.md`
7. `docs/INTERACTION_STATE_MACHINE.md`
8. `docs/DOMAIN_EVENTS.md`
9. `docs/SYSTEM_ARCHITECTURE_V2.md`
10. `docs/SPEECH_LLM_PIPELINE.md`
11. `shared/src/domainEvents.ts`
12. `shared/src/providers.ts`
13. `backend/src/services/transcriptService.ts`
14. `backend/src/services/voiceObservabilityService.ts`

执行：

```bash
git status --short
git log -8 --oneline
npm test
npm run build
```

## 任务目标

定义并测试 M5 统一行为观测契约与时间线基线，至少覆盖：

- `BehaviorObservation`
- `AttentionObservation`
- `LanguageObservation`
- `ObservationWindow`
- `QuestionBehaviorSummary`
- `SessionBehaviorSummary`
- `DataQuality`
- `AlgorithmVersion`
- `EvidenceReference`

每个观测至少包含：

- 唯一 ID。
- `sessionId`
- `questionId`
- `turnId`
- `eventId`
- `correlationId`
- 开始和结束时间。
- 观测来源。
- Provider。
- 算法版本。
- 特征。
- 置信度。
- 数据质量。
- 是否降级。
- 错误。
- 创建时间。

## 范围边界

允许：

- 修改 shared contract/type 文件。
- 新增 shared contract tests。
- 如确有必要，更新 `docs/WORK_ITEMS_M5.md` 或 `docs/M5_TECHNICAL_DECISIONS.md` 中与 M5-001 实现结果相关的事实。

禁止：

- 修改 `frontend/src/App.tsx`。
- 修改 `backend/src/index.ts`。
- 修改 `backend/src/services/sessionService.ts`。
- 修改真实 STT/TTS/LLM/vision provider。
- 启用真实外部 API。
- 保存原始音频、原始视频、摄像头帧或未脱敏敏感文本。
- 实现正式注意力/语言能力评分。
- 让 LLM 生成最终能力分数。
- 修改 `package.json` 或 lock 文件，除非用户另行批准。

## 设计要求

- 复用现有 `DomainEvent`、`ProviderMetadata`、Mock observation provider 的字段风格。
- 观测必须能关联 `sessionId`、`questionId`、`turnId`、`eventId`、`correlationId`。
- `EvidenceReference` 必须能引用领域事件、语音 turn、Transcript、动画/反馈事件、provider result 或观察窗口。
- `DataQuality` 必须覆盖：`complete`、`partial`、`missing_device`、`low_confidence`、`timeout`、`manual_override`、`insufficient`。
- `AlgorithmVersion` 必须区分 schema、algorithm、rule/provider/model version。
- `QuestionBehaviorSummary` 和 `SessionBehaviorSummary` 只做 M6 输入，不包含正式评分、常模、百分位或诊断结论。
- 普通摄像头注意力字段只能表达粗粒度任务参与/头部朝向/图像质量，不得表达精准眼动追踪。

## 测试要求

至少补充：

- Contract typecheck。
- Runtime fixture test：构造 attention observation、language observation、question summary、session summary。
- Privacy guard：fixture 不包含 raw frame、raw audio、raw transcript required fields。
- Data quality test：missing camera、low confidence transcript、empty speech 都可表达。

验证命令：

```bash
npm run test:contracts
npm test
npm run build
git diff --check
git status --short
git diff --stat
```

## 完成标准

1. M5 行为观测契约可编译。
2. 关键 fixture 测试通过。
3. 不修改前端或后端业务代码。
4. 不新增真实 API、模型文件、媒体资源或敏感数据。
5. `npm test`、`npm run build`、`git diff --check` 通过。
6. 已选择性暂存并创建本地 commit。

## 最终回复

汇报：

1. 创建/修改的文件。
2. 新增的契约模型。
3. 数据安全边界。
4. 测试和 build 结果。
5. 本地 commit hash。
6. 是否修改业务代码。
7. 确认没有调用子 Agent。
