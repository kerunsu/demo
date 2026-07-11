# M5 工程任务拆分：训练过程行为观测与数据采集

当前事实：M4 当前状态为 `COMPLETE_CODE_WITH_ENVIRONMENT_PENDING`。语音链路代码、Mock/本地 Provider 边界、自动化测试和 M4-014 开发环境验收准备已经完成；真实机器人双屏、麦克风、扬声器、局域网和现场噪声验收仍为 `ENVIRONMENT_PENDING`。该现场验收不阻塞 M5 规划和不依赖真实摄像头算法的契约类开发。

当前事实：当前仓库已经有可复用的 `sessionId`、`questionId`、`turnId`、`eventId`、`correlationId`、领域事件、语音 turn、Transcript 规范化、媒体接入和语音可观测性代码。`shared/src/domainEvents.ts` 已包含 `ATTENTION_OBSERVATION_RECORDED` 与 `LANGUAGE_OBSERVATION_RECORDED` 草案事件，`shared/src/providers.ts` 已包含 Mock 注意力/语言观测 Provider 雏形。

建议：M5 第一版先固定统一行为观测契约与时间线基线，再实现存储、摄像头采集、推理服务、注意力/语言特征、窗口聚合和数据质量。不要先绑定某个视觉模型，也不要把普通摄像头的头部朝向粗粒度判断夸大为精准眼动追踪。

## M5 目标

M5 负责在训练过程中采集、处理并保存可追溯的行为观测数据：

- 注意力观测：人脸存在、人脸数量、头部朝向、是否大致朝向交互屏、连续关注/中断区间、每题关注比例、摄像头不可用、人脸丢失、多人干扰、遮挡、光照/图像质量、算法置信度和算法版本。
- 语言表达观测：复用 M4 STT 和语音 turn 数据，记录是否回应、响应开始时延、音频时长、Transcript、Transcript 置信度、字数/词数、有效表达长度、空响应、重复表达、提示前后变化、相关性 Provider 结果、数据质量和规则/算法版本。
- 时间对齐：所有观测必须关联 `sessionId`、`questionId`、`turnId`、`eventId`、`correlationId`、`timestamp`、机器人反馈/动画事件、提示事件、答题结果和语音轮次。

## M5 与 M6 边界

M5 只负责：数据采集、原始观测、特征、时间窗口、题目级聚合、课程级聚合输入、数据质量、可追溯证据、Provider 和算法版本。

M5 不负责：正式能力分数、专业权重、常模、百分位、临床诊断、由大模型自由生成评分、正式评估报告结论。

正式评分、规则组合和报告结论进入 M6。专业评分规则未确认不阻塞 M5 的工程数据管线，但会阻塞 M6 的正式评分。

## 第一版推荐技术路线

### 注意力第一版

建议：M5 v1 使用“浏览器采集 + 服务器侧轻量聚合 + Mock/可替换 Provider”的路线。

| 路线 | 延迟 | 带宽 | 浏览器性能 | 服务器性能 | Windows 支持 | 隐私 | 可测试性 | 多机器人扩展 | 模型替换 | 图像质量 | GPU |
| -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |
| 浏览器内轻量人脸/头部检测 | 低 | 极低 | 中到高压力 | 低 | 取决于 Web 模型 | 强，帧不出端 | 中，浏览器自动化较难 | 端侧模型分发复杂 | 中 | 受摄像头与浏览器限制 | 通常不需要 |
| 浏览器采样低帧率图像到服务器 | 中 | 中，可控 | 低 | 中 | 好 | 中，需避免长期保存帧 | 高，HTTP fixture 易测 | 好 | 高 | 可统一质检 | 可选 |
| 浏览器传输视频流到服务器 | 中到高 | 高 | 中 | 高 | 好 | 风险高 | 中 | 需强资源管理 | 高 | 好 | 可能需要 |
| 服务器独立视觉推理服务 | 中 | 取决于输入 | 低 | 中到高 | 好 | 可控但需严格边界 | 高 | 好 | 高 | 好 | 可选，模型决定 |

建议：M5 v1 先采用“浏览器权限与设备管理 + 低频采样/Mock 推理接口 + 服务器窗口聚合”的可替换架构。默认不保存原始图像，不上传外部云视觉服务，先输出粗粒度“任务参与/朝向状态”而不是眼动精度。

升级条件：

- 真实机器人摄像头、光照和遮挡环境验收完成。
- 普通摄像头下头部朝向/人脸存在准确性满足人工抽检阈值。
- 服务器 CPU/GPU 和多机器人并发预算明确。
- 隐私流程确认是否允许短暂缓存低帧率图像。
- 专业人员确认注意力定义、阈值和报告措辞。

### 语言表达第一版

建议：M5 v1 优先复用 M4 的 STT、Transcript 规范化、voice turn 和 voice observability。

确定性特征：

- 是否发生语言回应。
- 响应开始时延。
- 语音持续时长。
- Transcript 长度、句子数、字数/词数。
- STT 置信度、空响应、重复 final transcript。
- 提示次数、提示前后响应变化。

模型或规则特征：

- 回答相关性。
- 表达完整度。
- 信息丰富度。
- 语法复杂度。
- 提示依赖。

建议：模型/规则类特征必须通过 `LanguageFeatureProvider` 或等价 Provider 隔离，并记录 provider、model/rule version、confidence、input evidence、failure/degraded state。M5 不允许 LLM 直接输出最终语言能力分数。

## 统一行为数据模型

M5 规划以下模型，第一轮编码优先固定 TypeScript 契约和测试：

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
- Session、Question、Turn 和 Correlation 关联。
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

数据保存边界：

| 数据 | 存储策略 | 说明 |
| -- | -- | -- |
| 观测摘要、窗口、题目级汇总、会话级汇总 | 进入数据库或未来 Repository | 用于 M6 评分输入和报告引用。 |
| 事件 ID、时间戳、provider/model/rule version、数据质量、证据引用 | 进入数据库 | 保证可追溯。 |
| 高频逐帧中间状态 | 默认只在内存环形缓冲 | 经窗口聚合后下采样保存。 |
| 低帧率图像样本 | 默认不保存；仅开发调试可显式开启短期缓存 | 不进入默认日志或数据库。 |
| 原始连续视频帧、原始视频文件 | 不允许默认保存 | 不发送外部云视觉服务。 |
| 原始音频 | 遵循 M4 规则，默认不长期保存 | 仅保存脱敏 Transcript 或指标。 |
| 真实儿童敏感身份信息 | 不允许进入行为日志 | 使用别名、哈希或脱敏引用。 |

防止无界增长：

- 高频观测先进入内存环形缓冲。
- 按固定窗口聚合，例如 500ms、1s、题目窗口、语音 turn 窗口。
- 数据库只保存窗口特征、质量标记和必要证据引用。
- 每个 session 设置最大观测数量和最大写入频率。
- 低置信度连续状态合并为区间，不逐帧写入。

## 执行顺序

必须顺序执行：

1. `M5-001` 统一行为观测契约与时间线基线。
2. `M5-002` 行为观测领域事件。
3. `M5-003` 行为数据存储接口。
4. `M5-004` 摄像头权限与设备管理。

契约固定后可以并行：

- `M5-005` 到 `M5-009` 注意力采集和 Provider。
- `M5-010` 到 `M5-011` 语言表达特征和相关性 Provider。
- `M5-012` 到 `M5-016` 时间线、聚合、质量和可观测性。
- `M5-017` 测试 fixture 可与各实现任务配套推进。

需要专业人员确认后才能完成：

- 注意力定义、阈值和报告措辞。
- 语言表达能力正式维度和评分规则。
- 题目相关性、表达完整度等模型类特征的解释边界。
- 数据质量阈值和人工验收样例。

可标记 `ENVIRONMENT_PENDING`：

- `M5-004` 摄像头权限与设备管理的真实设备验收。
- `M5-008` 真实注意力候选技术 Spike 的现场准确性。
- `M5-018` 开发环境验收中的真实摄像头/麦克风组合。
- `M5-019` 真实双设备环境验收准备。

## 任务清单

### M5-001

- 任务编号：`M5-001`
- 标题：统一行为观测契约与时间线基线
- 目标：定义 `BehaviorObservation`、`AttentionObservation`、`LanguageObservation`、`ObservationWindow`、`EvidenceReference`、`DataQuality`、`AlgorithmVersion` 的共享契约，并对齐 `sessionId`、`questionId`、`turnId`、`eventId`、`correlationId`。
- 非目标：不接真实摄像头模型；不实现正式评分；不修改训练业务流程。
- 前置依赖：M4 状态为 `COMPLETE_CODE_WITH_ENVIRONMENT_PENDING`；M3/M4 自动化基线通过。
- 输入文档：`docs/BEHAVIOR_ASSESSMENT_DATA_MODEL.md`、`docs/DOMAIN_EVENTS.md`、`docs/SPEECH_LLM_PIPELINE.md`、`docs/M5_TECHNICAL_DECISIONS.md`。
- 允许修改文件：`shared/src/**`、shared contract tests、必要的 docs。
- 禁止修改文件：`frontend/src/App.tsx`、`backend/src/index.ts`、`backend/src/services/sessionService.ts`、真实 provider、package/lock 文件。
- 共享文件 Owner：behavior-contract owner。
- 实现步骤：审查现有 shared provider/event 类型；新增或扩展行为契约；定义 evidence 引用；补契约测试；更新文档引用。
- 自动化测试：shared contract typecheck、runtime contract test、`npm test`、`npm run build`、`git diff --check`。
- 人工验收：确认字段覆盖注意力和语言两类观测，且没有评分字段越界。
- 数据安全：禁止原始音视频字段进入默认观测契约。
- 性能风险：契约过细会诱导逐帧存储；必须包含窗口和下采样边界。
- 是否允许 Mock：是。
- 是否依赖真实摄像头：否。
- 是否依赖真实服务器：否。
- 验收标准：契约可编译、测试覆盖必需字段、文档区分 M5/M6。
- 验收命令：`npm run test:contracts`、`npm test`、`npm run build`、`git diff --check`。
- 是否可并行：否，第一任务必须单独完成。
- 回滚方式：移除新增契约和测试，恢复文档引用。

### M5-002

- 任务编号：`M5-002`
- 标题：行为观测领域事件
- 目标：固定 attention/language observation 的领域事件 payload、幂等键、持久化标记和恢复语义。
- 非目标：不实现推理算法；不写数据库。
- 前置依赖：`M5-001`。
- 输入文档：`docs/DOMAIN_EVENTS.md`、`docs/INTERACTION_STATE_MACHINE.md`、`docs/WORK_ITEMS_M5.md`。
- 允许修改文件：`shared/src/domainEvents.ts`、领域事件测试、docs。
- 禁止修改文件：业务路由、页面组件、真实 provider。
- 共享文件 Owner：domain-event owner。
- 实现步骤：扩展 observation payload；加入 observation window/evidence refs；补事件工厂或测试 fixture；验证旧事件兼容。
- 自动化测试：domain event contract tests、E2E 回归。
- 人工验收：检查事件不携带原始帧、原始音频或敏感文本。
- 数据安全：payload 只保存摘要、hash、证据引用和质量状态。
- 性能风险：事件频率过高；要求窗口化后再持久化。
- 是否允许 Mock：是。
- 是否依赖真实摄像头：否。
- 是否依赖真实服务器：否。
- 验收标准：事件可被前后端共享类型导入，幂等和 schemaVersion 明确。
- 验收命令：`npm run test:contracts`、`npm test`、`npm run build`、`git diff --check`。
- 是否可并行：否，依赖 `M5-001` 后单 Owner 完成。
- 回滚方式：恢复事件类型和测试。

### M5-003

- 任务编号：`M5-003`
- 标题：行为数据存储接口
- 目标：定义行为观测 Repository 接口、内存实现和未来 SQLite 映射边界。
- 非目标：不落地正式数据库迁移；不保存原始音视频。
- 前置依赖：`M5-001`、`M5-002`。
- 输入文档：`docs/PROJECT_OWNER_DECISIONS.md` D-006、`docs/M5_TECHNICAL_DECISIONS.md`。
- 允许修改文件：backend storage/service 边界、新增测试、docs。
- 禁止修改文件：现有判题规则、前端页面、Python 语音服务。
- 共享文件 Owner：behavior-storage owner。
- 实现步骤：新增接口；实现 bounded in-memory repository；定义查询方法；补隐私测试和容量测试。
- 自动化测试：repository 单元测试、backend test、full build。
- 人工验收：确认哪些数据入库、哪些仅内存、哪些禁止保存。
- 数据安全：默认不保存图像帧、视频、原始音频和未脱敏敏感文本。
- 性能风险：高频写入导致内存增长；必须支持容量上限和窗口聚合输入。
- 是否允许 Mock：是。
- 是否依赖真实摄像头：否。
- 是否依赖真实服务器：否。
- 验收标准：Repository 接口不绑定 SQLite 具体库，但未来可迁移。
- 验收命令：`npm run test:backend`、`npm test`、`npm run build`、`git diff --check`。
- 是否可并行：否，需先固定契约。
- 回滚方式：删除 repository 文件和测试。

### M5-004

- 任务编号：`M5-004`
- 标题：摄像头权限与设备管理
- 目标：建立浏览器摄像头权限、设备枚举、不可用状态、设备切换和质量状态的前端边界。
- 非目标：不实现真实视觉模型；不上传原始视频到外部云。
- 前置依赖：`M5-001`。
- 输入文档：`docs/M5_TECHNICAL_DECISIONS.md`、`docs/TARGET_PRODUCT_REQUIREMENTS.md`。
- 允许修改文件：frontend camera feature 文件、frontend tests、docs runbook。
- 禁止修改文件：后端判题、报告评分、真实 provider。
- 共享文件 Owner：frontend-camera owner。
- 实现步骤：封装 camera capture hook/client；记录 permission/device/quality states；支持停止和释放资源；加入 mock test。
- 自动化测试：frontend smoke/type tests、build。
- 人工验收：真实摄像头权限弹窗、断开摄像头、遮挡、无摄像头状态。
- 数据安全：不在日志输出设备原始 ID；使用 hash 或 label redaction。
- 性能风险：摄像头常开耗电和占用；必须有停止和最大采样率。
- 是否允许 Mock：是。
- 是否依赖真实摄像头：自动化不依赖；人工验收依赖，未执行时标记 `ENVIRONMENT_PENDING`。
- 是否依赖真实服务器：否。
- 验收标准：无摄像头时系统降级，不影响答题主流程。
- 验收命令：`npm run test:frontend`、`npm test`、`npm run build`、`git diff --check`。
- 是否可并行：`M5-001` 后可与 `M5-003` 并行，但热点文件需独占。
- 回滚方式：移除 camera feature 和入口引用。

### M5-005

- 任务编号：`M5-005`
- 标题：摄像头帧采样与传输
- 目标：定义低帧率采样、压缩、传输、序号、丢帧和取消接口。
- 非目标：不传输连续高清视频流；不长期保存帧。
- 前置依赖：`M5-004`、`M5-003`。
- 输入文档：`docs/M5_TECHNICAL_DECISIONS.md`。
- 允许修改文件：frontend camera transport、backend ingest route/service、shared media/behavior contracts、tests。
- 禁止修改文件：真实视觉模型、报告评分、package/lock。
- 共享文件 Owner：camera-ingress owner。
- 实现步骤：定义 control message；实现 low-fps sample POST 或 WebSocket frame metadata；服务端只接收临时处理引用；补丢帧和超时测试。
- 自动化测试：shared contract、backend ingress、frontend client smoke。
- 人工验收：不同分辨率和采样率下浏览器不卡顿。
- 数据安全：默认不落盘；日志不得含 frame base64。
- 性能风险：带宽和 CPU；默认 1-2 fps、低分辨率，采样率可配置。
- 是否允许 Mock：是。
- 是否依赖真实摄像头：自动化不依赖；性能验收依赖。
- 是否依赖真实服务器：否，开发本机可测。
- 验收标准：采样可开始/停止/取消，异常不会影响语音和答题。
- 验收命令：`npm run test:contracts`、`npm run test:backend`、`npm run test:frontend`、`npm test`、`npm run build`、`git diff --check`。
- 是否可并行：可与 `M5-006` Mock skeleton 并行，需共享契约冻结。
- 回滚方式：移除 transport 和 route，保留契约可独立回滚。

### M5-006

- 任务编号：`M5-006`
- 标题：服务器视觉推理服务骨架
- 目标：建立可替换视觉推理服务接口，支持 mock/local/external-disabled metadata、health、timeout、cancel 和版本字段。
- 非目标：本任务不安装模型、不启用 GPU、不接外部云视觉。
- 前置依赖：`M5-001`、`M5-003`。
- 输入文档：`docs/M5_TECHNICAL_DECISIONS.md`。
- 允许修改文件：shared providers、backend behavior provider skeleton、tests。
- 禁止修改文件：Python 语音服务、真实模型文件、package/lock。
- 共享文件 Owner：vision-provider owner。
- 实现步骤：定义 `AttentionObservationProvider` v2；补 health/status；实现 mock provider；连接 repository 但不启用真实模型。
- 自动化测试：provider contract tests、backend tests。
- 人工验收：确认 mock 输出可被后续聚合消费。
- 数据安全：provider metadata 明确 raw frame persistence false。
- 性能风险：后续真实模型可能阻塞 event loop；接口应预留异步服务边界。
- 是否允许 Mock：是，且本任务默认只 Mock。
- 是否依赖真实摄像头：否。
- 是否依赖真实服务器：否。
- 验收标准：mock provider 可生成带算法版本和置信度的观测。
- 验收命令：`npm run test:contracts`、`npm run test:backend`、`npm test`、`npm run build`、`git diff --check`。
- 是否可并行：`M5-001` 后可并行。
- 回滚方式：删除 provider skeleton 和测试。

### M5-007

- 任务编号：`M5-007`
- 标题：注意力 Provider Mock
- 目标：实现可配置注意力 Mock 场景：face present、no face、multiple faces、looking away、low confidence、camera unavailable、occluded。
- 非目标：不输出正式注意力分数。
- 前置依赖：`M5-006`。
- 输入文档：`docs/BEHAVIOR_ASSESSMENT_DATA_MODEL.md`、`docs/M5_TECHNICAL_DECISIONS.md`。
- 允许修改文件：mock provider、fixtures、tests、docs。
- 禁止修改文件：真实视觉 provider、评分规则。
- 共享文件 Owner：attention-mock owner。
- 实现步骤：扩展 mock scenarios；生成 deterministic fixtures；覆盖数据质量；写 contract tests。
- 自动化测试：provider fixture tests、backend tests。
- 人工验收：确认 Mock 场景足以驱动 UI/聚合测试。
- 数据安全：fixtures 不包含真实儿童图像。
- 性能风险：无。
- 是否允许 Mock：是。
- 是否依赖真实摄像头：否。
- 是否依赖真实服务器：否。
- 验收标准：每个质量/降级场景可稳定复现。
- 验收命令：`npm run test:contracts`、`npm run test:backend`、`npm test`、`npm run build`、`git diff --check`。
- 是否可并行：可与 `M5-010` 并行。
- 回滚方式：移除 mock scenarios 和 fixtures。

### M5-008

- 任务编号：`M5-008`
- 标题：真实注意力候选技术 Spike
- 目标：比较浏览器端轻量模型、低帧率图像到服务器、视频流、独立视觉推理服务四类方案，输出 benchmark 和推荐。
- 非目标：不把 spike 模型设为产品默认；不保存真实儿童视频；不安装模型到主链路。
- 前置依赖：`M5-006`、`M5-007`。
- 输入文档：`docs/M5_TECHNICAL_DECISIONS.md`。
- 允许修改文件：独立 spike 工具目录、`.runtime/` 输出、benchmark 报告、docs。
- 禁止修改文件：生产业务代码、package/lock、真实资源。
- 共享文件 Owner：attention-spike owner。
- 实现步骤：定义 benchmark matrix；使用合成/授权非儿童素材；记录延迟/CPU/带宽/准确性观察；输出报告。
- 自动化测试：spike schema test、无真实数据检查。
- 人工验收：真实摄像头和现场光照验证，未执行时标记 `ENVIRONMENT_PENDING`。
- 数据安全：测试素材必须合成或授权非儿童；输出不含原始图像。
- 性能风险：模型安装和 GPU 依赖；本任务不得污染默认运行链路。
- 是否允许 Mock：是。
- 是否依赖真实摄像头：可选；真实验收依赖并可 pending。
- 是否依赖真实服务器：可选。
- 验收标准：给出 M5 v1 推荐路线和升级条件。
- 验收命令：spike schema command、`npm test`、`npm run build`、`git diff --check`。
- 是否可并行：可并行，但不得改共享契约。
- 回滚方式：删除独立 spike 产物和报告。

### M5-009

- 任务编号：`M5-009`
- 标题：注意力实时观测
- 目标：将注意力 provider 输出接入会话时间线，生成窗口化 attention observations。
- 非目标：不计算正式注意力能力分数。
- 前置依赖：`M5-003`、`M5-006`、`M5-007`。
- 输入文档：`docs/DOMAIN_EVENTS.md`、`docs/M5_TECHNICAL_DECISIONS.md`。
- 允许修改文件：backend behavior service、event publication、tests。
- 禁止修改文件：报告评分、真实 provider、前端热点文件除非任务独占。
- 共享文件 Owner：attention-runtime owner。
- 实现步骤：订阅/调用 provider；合并连续状态；写入 repository；发布 observation event；处理 unavailable/degraded。
- 自动化测试：backend unit/integration、event contract。
- 人工验收：Mock 场景下可看到关注/中断窗口。
- 数据安全：只保存窗口和质量，不保存帧。
- 性能风险：高频事件；必须限制写入频率和窗口数量。
- 是否允许 Mock：是。
- 是否依赖真实摄像头：否，真实摄像头仅人工验收。
- 是否依赖真实服务器：否。
- 验收标准：每题可追溯 attention evidence refs。
- 验收命令：`npm run test:backend`、`npm test`、`npm run build`、`git diff --check`。
- 是否可并行：可与语言链路并行。
- 回滚方式：关闭 runtime wiring，保留契约。

### M5-010

- 任务编号：`M5-010`
- 标题：Transcript 语言特征提取
- 目标：基于 M4 Transcript 提取确定性语言特征：回应存在、时延、音频时长、字数、句子数、空响应、重复、低置信度、提示前后变化。
- 非目标：不调用 LLM 给最终语言分数。
- 前置依赖：`M5-001`；复用 M4-007/M4-012。
- 输入文档：`docs/SPEECH_LLM_PIPELINE.md`、`docs/BEHAVIOR_ASSESSMENT_DATA_MODEL.md`。
- 允许修改文件：backend language feature service、tests、docs。
- 禁止修改文件：STT/TTS provider 默认配置、报告正式评分。
- 共享文件 Owner：language-feature owner。
- 实现步骤：读取 transcript/voice metrics；计算确定性特征；生成 language observations；补重复和低置信度测试。
- 自动化测试：backend service tests、privacy tests。
- 人工验收：样例 transcript 对应特征可解释。
- 数据安全：保存脱敏 transcript 或 hash/长度；敏感文本不进日志。
- 性能风险：低。
- 是否允许 Mock：是。
- 是否依赖真实摄像头：否。
- 是否依赖真实服务器：否。
- 验收标准：无语音、空语音、重复语音均有数据质量标记。
- 验收命令：`npm run test:backend`、`npm test`、`npm run build`、`git diff --check`。
- 是否可并行：可与注意力 provider 并行。
- 回滚方式：删除 language feature service 和测试。

### M5-011

- 任务编号：`M5-011`
- 标题：语言相关性 Provider
- 目标：定义并实现可替换的题目相关性/表达完整度 Provider mock/rule 接口。
- 非目标：不启用外部 LLM；不输出正式语言能力分数。
- 前置依赖：`M5-010`。
- 输入文档：`docs/SPEECH_LLM_PIPELINE.md`、`docs/M5_TECHNICAL_DECISIONS.md`。
- 允许修改文件：shared provider contract、backend provider skeleton、fixtures、tests。
- 禁止修改文件：真实外部 LLM provider、API keys、报告评分。
- 共享文件 Owner：language-provider owner。
- 实现步骤：定义 input evidence；实现 rule/mock provider；记录 confidence/ruleVersion/failure；接入 language observation。
- 自动化测试：provider contract tests、failure/degraded tests。
- 人工验收：确认输出只作为 M6 输入，不作为最终分。
- 数据安全：input 使用脱敏上下文和最小题目证据。
- 性能风险：后续外部 provider 延迟；M5 只保留超时和降级字段。
- 是否允许 Mock：是。
- 是否依赖真实摄像头：否。
- 是否依赖真实服务器：否。
- 验收标准：provider metadata 完整，失败可降级。
- 验收命令：`npm run test:contracts`、`npm run test:backend`、`npm test`、`npm run build`、`git diff --check`。
- 是否可并行：可在 `M5-010` 之后与聚合任务并行。
- 回滚方式：删除 provider skeleton 和 tests。

### M5-012

- 任务编号：`M5-012`
- 标题：题目级时间线对齐
- 目标：按题目窗口对齐题目展示、答题、提示、反馈、动画、语音 turn、attention/language observations。
- 非目标：不计算课程级总评。
- 前置依赖：`M5-001`、`M5-002`、`M5-010`。
- 输入文档：`docs/INTERACTION_STATE_MACHINE.md`、`docs/DOMAIN_EVENTS.md`。
- 允许修改文件：backend timeline service、tests、docs。
- 禁止修改文件：现有判题规则、页面 UI。
- 共享文件 Owner：timeline owner。
- 实现步骤：定义 window start/end；处理缺失事件；按 eventId/correlationId 归因；输出 `ObservationWindow`。
- 自动化测试：timeline unit tests、missing event tests。
- 人工验收：抽查一个 session 的事件链可解释。
- 数据安全：窗口只引用事件和观测 ID。
- 性能风险：事件扫描成本；需限制 session 范围并使用索引接口。
- 是否允许 Mock：是。
- 是否依赖真实摄像头：否。
- 是否依赖真实服务器：否。
- 验收标准：每题窗口能解释输入事件范围。
- 验收命令：`npm run test:backend`、`npm test`、`npm run build`、`git diff --check`。
- 是否可并行：契约后可与 `M5-013` 顺序衔接，不可反向。
- 回滚方式：删除 timeline service 和 tests。

### M5-013

- 任务编号：`M5-013`
- 标题：题目级聚合
- 目标：生成 `QuestionBehaviorSummary`，包含关注比例、关注中断、语言回应、时延、提示依赖输入、数据质量和证据引用。
- 非目标：不输出正式能力等级。
- 前置依赖：`M5-012`。
- 输入文档：`docs/BEHAVIOR_ASSESSMENT_DATA_MODEL.md`。
- 允许修改文件：backend aggregation service、tests。
- 禁止修改文件：报告正式文案、专业评分规则。
- 共享文件 Owner：question-aggregation owner。
- 实现步骤：读取窗口；聚合 attention/language；合并 quality flags；保留 evidence refs；处理 missing/unavailable。
- 自动化测试：aggregation fixture tests。
- 人工验收：确认汇总可追溯到原观测。
- 数据安全：不展开敏感 transcript 原文。
- 性能风险：大 session 聚合耗时；使用按题窗口增量聚合。
- 是否允许 Mock：是。
- 是否依赖真实摄像头：否。
- 是否依赖真实服务器：否。
- 验收标准：每题 summary 可作为 M6 输入。
- 验收命令：`npm run test:backend`、`npm test`、`npm run build`、`git diff --check`。
- 是否可并行：依赖 `M5-012`，之后可与 `M5-014` 顺序。
- 回滚方式：删除 aggregation service 和 tests。

### M5-014

- 任务编号：`M5-014`
- 标题：Session 级聚合
- 目标：生成 `SessionBehaviorSummary`，按课程/会话聚合题目级行为特征、数据质量和缺失原因。
- 非目标：不生成正式报告结论或临床解释。
- 前置依赖：`M5-013`。
- 输入文档：`docs/BEHAVIOR_ASSESSMENT_DATA_MODEL.md`、`docs/REPORT_SCHEMA.md`。
- 允许修改文件：backend aggregation service、tests、docs。
- 禁止修改文件：报告 UI 正式分数、LLM 报告文案。
- 共享文件 Owner：session-aggregation owner。
- 实现步骤：汇总题目 summary；输出课程级输入；标记 insufficient data；支持 evidence range。
- 自动化测试：session aggregation fixtures。
- 人工验收：确认缺失摄像头时不会伪造注意力指标。
- 数据安全：只保存汇总和证据引用。
- 性能风险：重复全量聚合；应支持缓存或增量。
- 是否允许 Mock：是。
- 是否依赖真实摄像头：否。
- 是否依赖真实服务器：否。
- 验收标准：session summary 可被 M6 评分引擎读取。
- 验收命令：`npm run test:backend`、`npm test`、`npm run build`、`git diff --check`。
- 是否可并行：依赖题目级聚合。
- 回滚方式：删除 session aggregation service 和 tests。

### M5-015

- 任务编号：`M5-015`
- 标题：数据质量与缺失数据
- 目标：统一 `DataQuality`：complete、partial、missing_device、low_confidence、timeout、manual_override、insufficient，并定义报告给 M6 的降级语义。
- 非目标：不决定专业评分阈值。
- 前置依赖：`M5-001`、`M5-013`。
- 输入文档：`docs/BEHAVIOR_ASSESSMENT_DATA_MODEL.md`、`docs/DECISIONS_REQUIRED.md`。
- 允许修改文件：shared behavior contract、backend quality service、tests、docs。
- 禁止修改文件：正式评分规则。
- 共享文件 Owner：data-quality owner。
- 实现步骤：定义 quality enum；映射 provider errors；聚合 quality；加入 missing device fixture。
- 自动化测试：quality mapping tests。
- 人工验收：专业人员确认哪些质量状态不足以评分。
- 数据安全：质量标记不得包含敏感原文。
- 性能风险：低。
- 是否允许 Mock：是。
- 是否依赖真实摄像头：否。
- 是否依赖真实服务器：否。
- 验收标准：所有观测和 summary 都携带质量状态。
- 验收命令：`npm run test:contracts`、`npm run test:backend`、`npm test`、`npm run build`、`git diff --check`。
- 是否可并行：可与 `M5-013` 后半并行，但最终需合并。
- 回滚方式：恢复 quality enum 和映射。

### M5-016

- 任务编号：`M5-016`
- 标题：可观测性和性能
- 目标：记录行为管线延迟、写入量、降采样率、provider 状态、错误和降级，同时避免敏感数据日志。
- 非目标：不引入外部监控服务。
- 前置依赖：`M5-003`、`M5-009`、`M5-010`。
- 输入文档：`docs/SPEECH_LLM_PIPELINE.md`、`docs/M5_TECHNICAL_DECISIONS.md`。
- 允许修改文件：backend observability service、routes/tests、docs。
- 禁止修改文件：外部监控 SDK、真实 API key。
- 共享文件 Owner：behavior-observability owner。
- 实现步骤：复用 voice observability 模式；新增 behavior stages；去重；容量限制；隐私测试。
- 自动化测试：metric dedupe、bounded memory、privacy assertions。
- 人工验收：查看开发环境指标摘要。
- 数据安全：不记录 frame base64、原始 transcript、设备原始 ID。
- 性能风险：日志过量；必须限流和聚合。
- 是否允许 Mock：是。
- 是否依赖真实摄像头：否。
- 是否依赖真实服务器：否。
- 验收标准：行为管线异常可定位，日志不含敏感原始数据。
- 验收命令：`npm run test:backend`、`npm test`、`npm run build`、`git diff --check`。
- 是否可并行：可与聚合任务并行。
- 回滚方式：删除 behavior observability wiring。

### M5-017

- 任务编号：`M5-017`
- 标题：自动化测试与 Fixture
- 目标：建立注意力、语言、时间线、质量和聚合 fixture，覆盖无设备、低置信度、多人干扰、空语音、重复 transcript、提示前后变化。
- 非目标：不提交真实儿童图像、音频或敏感文本。
- 前置依赖：`M5-001`、`M5-007`、`M5-010`。
- 输入文档：`docs/TEST_FIXTURES.md`、`docs/M5_TECHNICAL_DECISIONS.md`。
- 允许修改文件：test fixtures、shared/backend/frontend tests、docs。
- 禁止修改文件：真实媒体资源、模型文件、package/lock。
- 共享文件 Owner：behavior-test owner。
- 实现步骤：定义 fixture manifest；生成 synthetic descriptors；覆盖 regression；加入 privacy guard。
- 自动化测试：fixture manifest tests、full `npm test`。
- 人工验收：检查 fixture 名称和说明不暗示真实儿童数据。
- 数据安全：只允许合成、开发授权或非儿童授权数据描述。
- 性能风险：测试时间增长；按层拆分。
- 是否允许 Mock：是。
- 是否依赖真实摄像头：否。
- 是否依赖真实服务器：否。
- 验收标准：M5 主要异常路径均有 fixture。
- 验收命令：`npm test`、`npm run build`、`git diff --check`。
- 是否可并行：可随实现任务增量推进。
- 回滚方式：删除 fixture 和测试引用。

### M5-018

- 任务编号：`M5-018`
- 标题：开发环境验收
- 目标：在当前开发机验证行为管线的自动化、Mock、摄像头权限、语音复用、性能和隐私边界。
- 非目标：不宣称真实机器人现场完成。
- 前置依赖：`M5-014`、`M5-016`、`M5-017`。
- 输入文档：`docs/M5_TECHNICAL_DECISIONS.md`、`docs/M4_DEPLOYMENT_ACCEPTANCE.md`。
- 允许修改文件：docs acceptance checklist、optional runbook。
- 禁止修改文件：业务代码，除非另开实现任务。
- 共享文件 Owner：m5-acceptance owner。
- 实现步骤：整理验收步骤；跑自动化；记录开发环境限制；标记现场未验收项。
- 自动化测试：`npm test`、`npm run build`、`git diff --check`。
- 人工验收：开发机浏览器摄像头/麦克风组合检查。
- 数据安全：验收不得使用真实儿童数据。
- 性能风险：开发机结果不代表目标服务器。
- 是否允许 Mock：是。
- 是否依赖真实摄像头：部分人工验收依赖；缺失则 `ENVIRONMENT_PENDING`。
- 是否依赖真实服务器：否。
- 验收标准：开发机 M5 可演示，现场限制清楚。
- 验收命令：`npm test`、`npm run build`、`git diff --check`、人工 checklist。
- 是否可并行：否，收口任务。
- 回滚方式：恢复验收文档。

### M5-019

- 任务编号：`M5-019`
- 标题：真实双设备环境验收准备
- 目标：准备真实机器人浏览器终端、局域网、高性能服务器、摄像头、麦克风、扬声器和现场噪声下的 M5 验收清单。
- 非目标：本任务不要求 Codex 当前完成真实现场验收。
- 前置依赖：`M5-018`。
- 输入文档：`docs/M4_DEPLOYMENT_ACCEPTANCE.md`、`docs/M5_TECHNICAL_DECISIONS.md`。
- 允许修改文件：docs acceptance checklist、runbook。
- 禁止修改文件：业务代码、真实设备配置密钥。
- 共享文件 Owner：field-acceptance owner。
- 实现步骤：列设备清单；定义现场脚本；定义通过/失败记录；准备问题模板；标记 pending。
- 自动化测试：文档检查、`npm test`、`npm run build`。
- 人工验收：真实现场执行后补结果。
- 数据安全：现场测试需授权，不使用真实儿童数据作为默认样本。
- 性能风险：LAN 抖动、光照、遮挡、噪声和设备驱动差异。
- 是否允许 Mock：是，准备阶段允许；现场需要真实设备。
- 是否依赖真实摄像头：现场验收依赖，当前可 `ENVIRONMENT_PENDING`。
- 是否依赖真实服务器：现场验收依赖。
- 验收标准：现场人员可按清单执行并回填结果。
- 验收命令：`npm test`、`npm run build`、`git diff --check`、现场 checklist。
- 是否可并行：收口任务，不建议并行。
- 回滚方式：恢复验收文档。

## 推荐第一个 M5 编码任务

建议第一个 M5 编码任务为：`M5-001 统一行为观测契约与时间线基线`。

原因：

- 不依赖真实摄像头算法。
- 能统一注意力与语言数据。
- 为后续存储、推理、聚合和 M6 评分提供基础。
- 能通过单元和契约测试。
- 不会提前绑定某个视觉模型。
