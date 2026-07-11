# M3 工程任务拆分：双屏与 GIF 动画最小闭环

当前事实：M1/M2 已完成本地检查点，`/child` 与 `/robot` 页面壳存在，共享领域事件、状态机、Provider Mock 和 Animation Adapter 契约存在，后端已完成 App/Server、路由和服务边界拆分。当前事实：项目负责人已确认 `Emotions/` 是正式 GIF 资源目录，包含 9 个 GIF。

当前事实：本阶段目标是局域网双主机、同一训练会话、HTTP 命令/查询、WebSocket 实时事件、答题判定后驱动机器人屏 GIF 和 Mock TTS/预录音播放，完成回执后推进下一题。当前事实：本阶段不调用真实外部 API，不实现真实 STT、真实外部 LLM、真实云端 TTS、正式安全审核模型、正式注意力检测、正式语言表达评估、正式报告扩展、临床或专业评分，也不重新制作动画资源。

## M3 进入条件核验

- 当前事实：分支为 `codex/overnight-m1-m2`。
- 当前事实：`npm test` 通过，覆盖 contracts、backend、frontend 和 E2E。
- 当前事实：`npm run build` 通过。
- 当前事实：`git log --oneline -20` 显示 `M1-001` 至 `M2-011` 已形成连续本地提交。
- 当前事实：`Emotions/` 已作为正式资源目录进入当前工作区状态。
- 当前事实：M3 实现后前端 API Base URL、WebSocket URL、后端 Host/Port、CORS Origin 和课程素材 public origin 均已有运行时配置入口。
- 当前事实：M3 实现后后端已有 `/ws` WebSocket 事件通道，前端机器人屏已有实时客户端。
- 当前事实：M3 实现后动画 manifest 的 `resourceRef` 已对齐 `/Emotions/*.gif`。

## GIF 资源核验

当前事实：以下正式 GIF 已在仓库工作区中找到，但目录尚未被 Git 跟踪：

| 文件名 | 实际路径 |
| -- | -- |
| `001_Eye.gif` | `Emotions/001_Eye.gif` |
| `002_Curious.gif` | `Emotions/002_Curious.gif` |
| `003_Happy.gif` | `Emotions/003_Happy.gif` |
| `004_Excited.gif` | `Emotions/004_Excited.gif` |
| `005_LookDown.gif` | `Emotions/005_LookDown.gif` |
| `006_Sad.gif` | `Emotions/006_Sad.gif` |
| `007_Yawn.gif` | `Emotions/007_Yawn.gif` |
| `008_Dissatisfied.gif` | `Emotions/008_Dissatisfied.gif` |
| `009_OpenEyes.gif` | `Emotions/009_OpenEyes.gif` |

待确认：M3 编码前需要决定是否将 `Emotions/` 纳入 Git、是否保持该目录名作为静态资源源目录，或是否复制到前端可发布目录。不得在未确认前移动、重命名或重新编码 GIF。

## 执行顺序总览

必须顺序执行：

1. `M3-001` 局域网运行时配置。
2. `M3-002` WebSocket 最小连接基线。
3. `M3-003` 会话快照与重连恢复。
4. `M3-006` 答题结果领域事件。
5. `M3-009` 动画、语音与下一题时序编排。
6. `M3-010` 双屏 E2E 测试。
7. `M3-011` 局域网双主机验收。

契约固定后可以并行：

- `M3-004` 可在 `M3-001` 后与 `M3-002` 并行准备，但需等待资源目录决策。
- `M3-005` 可在 `M3-004` 后与 `M3-006` 并行。
- `M3-007` 依赖 `M3-002`、`M3-004`、`M3-005`，可与 `M3-008` 并行。
- `M3-008` 依赖 `M3-002` 和 Mock/本地资源边界，可与 `M3-007` 并行。

会修改共享文件的任务：

- `M3-001`：运行时配置、API 客户端、后端启动配置和 CORS。
- `M3-002`：WebSocket 服务、客户端和连接类型。
- `M3-003`：会话快照 API、事件恢复字段和客户端恢复逻辑。
- `M3-006`：领域事件发布和答题领域事件 payload。
- `M3-009`：后端编排状态、动画/TTS ACK 和下一题推进。

需要真实双主机环境才能最终验收的任务：

- `M3-001` 的局域网手工验收部分。
- `M3-011` 全部验收。

## M3-001

- 任务编号：`M3-001`
- 标题：局域网运行时配置
- 目标：让前端 API Base URL、WebSocket URL、后端 Host、端口、CORS Origin 和静态资源访问不再依赖硬编码 `127.0.0.1`，支持机器人主机访问独立后端主机。
- 非目标：不实现 WebSocket 业务通道，不改变训练流程，不移动 GIF，不接真实外部 provider。
- 前置依赖：M1/M2 基线通过；项目负责人确认 `Emotions/` 资源来源。
- 输入文档：`AGENTS.md`、`frontend/AGENTS.md`、`backend/AGENTS.md`、`docs/PROJECT_OWNER_DECISIONS.md`、`docs/SYSTEM_ARCHITECTURE_V2.md`、`docs/API.md`、`docs/DEMO_RUNBOOK.md`。
- 允许修改文件：`frontend/src/config/**`、`frontend/src/services/api.ts`、必要的前端测试；`backend/src/config/**`、`backend/src/index.ts`、`backend/src/app.ts`、`backend/src/services/courseService.ts`、必要的后端测试；必要的运行说明文档。
- 禁止修改文件：GIF 资源、Lock 文件、真实 `.env`、判题规则、状态机契约语义、报告规则、真实 provider。
- 共享文件 Owner：runtime-config owner。
- 实现步骤：梳理现有 `127.0.0.1` 使用点；新增前端运行时配置读取和校验；新增后端运行时配置读取和校验；配置 CORS 白名单或安全默认值；保持本机默认 Demo 可运行；更新测试覆盖默认值和环境变量覆盖；记录局域网启动示例。
- 测试要求：默认无环境变量时测试仍可跑；配置错误要有明确失败信息；不得访问外部网络。
- 验收标准：代码中业务路径不再硬编码后端 `127.0.0.1`；后端可配置监听 `0.0.0.0`；前端可配置后端 LAN 地址；现有 API/E2E 行为不变。
- 验收命令：`npm test`、`npm run build`、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：否，首个 M3 编码任务，涉及共享运行时配置。
- 依赖任务：无。
- 风险：配置默认值变化可能破坏本机 Demo 或 E2E；CORS 过宽会掩盖后续安全边界。
- 回滚方式：恢复新增配置文件、API 客户端、后端启动配置和测试改动。

## M3-002

- 任务编号：`M3-002`
- 标题：WebSocket 最小连接基线
- 目标：建立后端 WebSocket 服务和前端最小客户端，支持 screen role、sessionId 订阅、连接、断开和心跳，不实现完整业务事件。
- 非目标：不实现答题事件发布，不实现动画播放，不实现会话恢复。
- 前置依赖：`M3-001`。
- 输入文档：`docs/DOMAIN_EVENTS.md`、`docs/SYSTEM_ARCHITECTURE_V2.md`、`docs/PROJECT_OWNER_DECISIONS.md`。
- 允许修改文件：后端 WebSocket 服务和测试、前端 WebSocket 客户端和测试、共享连接类型中必要的最小补充。
- 禁止修改文件：判题规则、动画资源、真实 provider、报告逻辑。
- 共享文件 Owner：event-channel owner。
- 实现步骤：选择最小依赖方案；在后端启动时挂载 WebSocket；定义连接 query 或握手 payload；记录 clientId、screenRole、sessionId、lastSeenEventId；实现 ping/pong 或应用层心跳；前端暴露可测试客户端函数；机器人页面显示连接占位状态。
- 测试要求：覆盖 child/robot 两种角色连接、断开、心跳超时和非法参数。
- 验收标准：两个页面可连接同一个后端 WebSocket endpoint；断开不会影响 HTTP API；不发布业务事件。
- 验收命令：`npm run test:backend`、`npm run test:frontend`、`npm test`、`npm run build`、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：否，建立共享事件通道基线。
- 依赖任务：`M3-001`。
- 风险：新增 WebSocket 依赖可能影响 lock 文件；心跳实现不稳定会导致测试偶发失败。
- 回滚方式：移除 WebSocket 服务、客户端和测试，恢复 server 启动路径。

## M3-003

- 任务编号：`M3-003`
- 标题：会话快照与重连恢复
- 目标：支持页面首次连接、刷新和短暂断线后从后端获取当前会话快照，并按 `eventId` 或等价机制避免重复事件处理。
- 非目标：不实现完整事件存储数据库，不实现跨进程持久化，不实现正式断网离线队列。
- 前置依赖：`M3-002`。
- 输入文档：`docs/DOMAIN_EVENTS.md`、`docs/INTERACTION_STATE_MACHINE.md`、`docs/SYSTEM_ARCHITECTURE_V2.md`。
- 允许修改文件：后端 session snapshot 服务/API、WebSocket 会话订阅逻辑、前端 snapshot 客户端、页面连接状态测试。
- 禁止修改文件：真实 provider、GIF 文件、专业评分规则。
- 共享文件 Owner：session-recovery owner。
- 实现步骤：定义最小 snapshot 字段；为当前内存 session 提供查询入口；客户端连接后先拉快照再订阅事件；记录 lastSeenEventId；重复事件不重复应用；覆盖刷新和短断线场景。
- 测试要求：单元或集成测试覆盖快照字段、无效 session、重复 eventId 和重连后状态一致。
- 验收标准：`/child` 和 `/robot` 刷新后能恢复当前会话显示；短暂断线后不会重复推进题目。
- 验收命令：`npm run test:backend`、`npm run test:frontend`、`npm test`、`npm run build`、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：否，恢复语义会影响后续业务事件。
- 依赖任务：`M3-002`。
- 风险：当前内存 session 不持久，进程重启恢复仍不可用；需在文案中明确不是生产持久化。
- 回滚方式：移除 snapshot API、客户端恢复逻辑和相关测试。

## M3-004

- 任务编号：`M3-004`
- 标题：机器人屏动画资源与元数据
- 目标：将 9 个 GIF 的 animationId、实际路径、loop、expectedDurationMs、优先级、中断属性和加载失败处理集中到可测试 manifest。
- 非目标：不重新制作动画，不移动资源，除非项目负责人明确确认资源目录纳入方式；不实现播放 UI。
- 前置依赖：`M3-001`；资源目录纳入方式确认。
- 输入文档：`docs/PROJECT_OWNER_DECISIONS.md`、`docs/ROBOT_ANIMATION_INTEGRATION.md`、`shared/src/animations.ts`。
- 允许修改文件：共享动画 manifest、动画契约测试、必要资源说明文档。
- 禁止修改文件：GIF 二进制文件、判题规则、WebSocket 业务编排。
- 共享文件 Owner：robot-animation-manifest owner。
- 实现步骤：确认 `Emotions/` 是否作为实际 resource root；校验 9 个文件名；补充 resourceRef 映射；先保留 `expectedDurationMs` 为待验证或填入可追溯估算；明确答错默认不使用 `sad` 或 `dissatisfied`；测试资源清单完整性。
- 测试要求：manifest 含 9 个动画；路径和文件名匹配；安全默认映射不选明显负面动画。
- 验收标准：机器人屏实现可只依赖 manifest 查找资源；缺失资源有明确错误或 fallback。
- 验收命令：`npm run test:contracts`、`npm test`、`npm run build`、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：可在 `M3-001` 后与 `M3-002` 并行，但共享 manifest 需单 Owner。
- 依赖任务：`M3-001`。
- 风险：GIF 时长未校准会影响完成回执；资源目录若未纳入构建产物会导致浏览器 404。
- 回滚方式：恢复 manifest 和契约测试。

## M3-005

- 任务编号：`M3-005`
- 标题：GIF Animation Adapter 实现
- 目标：在机器人屏实现 GIF Adapter 的 `play`、`stop`、`showIdle`、`isPlaying`、开始事件、预计完成、播放失败和同一 GIF 重新播放。
- 非目标：不实现 WebSocket 业务消费，不实现 TTS 编排，不读取真实硬件。
- 前置依赖：`M3-004`。
- 输入文档：`docs/ROBOT_ANIMATION_INTEGRATION.md`、`shared/src/animations.ts`。
- 允许修改文件：机器人屏动画 adapter、机器人页面组件、前端测试。
- 禁止修改文件：后端判题规则、GIF 文件、真实 provider。
- 共享文件 Owner：robot-display owner。
- 实现步骤：实现基于 `<img>` 的 GIF 播放；使用 key/cache 参数或重新挂载实现同一 GIF 重播；按 manifest timer 产生完成；处理资源加载失败；保持 idle fallback；导出可测试纯逻辑。
- 测试要求：覆盖 play/stop/showIdle/isPlaying、同一动画重播、失败 fallback 和 timer 完成。
- 验收标准：机器人屏可本地播放 manifest 指定 GIF 或显示明确资源错误；不会把 Mock 播放描述为真实硬件播放。
- 验收命令：`npm run test:frontend`、`npm test`、`npm run build`、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：可与 `M3-006` 并行。
- 依赖任务：`M3-004`。
- 风险：浏览器 GIF 没有原生完成事件，只能依赖时长配置；自动化测试不能完全证明视觉播放质量。
- 回滚方式：恢复机器人页面和 adapter 文件。

## M3-006

- 任务编号：`M3-006`
- 标题：答题结果领域事件
- 目标：在不改变现有判题规则的前提下，发布 `ANSWER_SUBMITTED`、`ANSWER_EVALUATED`、`FEEDBACK_REQUESTED` 和 `ANIMATION_REQUESTED` 事件。
- 非目标：不实现完整事件数据库，不实现机器人播放，不改变答错反馈规则。
- 前置依赖：`M3-003`；领域事件契约已固定。
- 输入文档：`docs/DOMAIN_EVENTS.md`、`docs/INTERACTION_STATE_MACHINE.md`、`docs/API.md`。
- 允许修改文件：后端事件发布服务、答题 API 编排、事件测试、必要共享类型补充。
- 禁止修改文件：课程素材、GIF 文件、正式评分、真实 provider。
- 共享文件 Owner：domain-event owner。
- 实现步骤：在提交答案入口生成提交事件；判题后生成判题事件；映射温和反馈事件；生成动画请求事件；设置 correlationId/causationId/idempotencyKey；通过 WebSocket 推送给订阅客户端；保持 HTTP 响应兼容。
- 测试要求：覆盖正确答案、错误答案、重复提交、事件字段完整性和答错不默认 `sad`/`dissatisfied`。
- 验收标准：HTTP 判题仍返回原结果；WebSocket 订阅者能收到最小答题事件链。
- 验收命令：`npm run test:backend`、`npm run test:e2e`、`npm test`、`npm run build`、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：可与 `M3-005` 并行，但共享事件文件由本任务 Owner 修改。
- 依赖任务：`M3-003`。
- 风险：事件发布与 HTTP 响应顺序处理不当会造成重复或丢事件。
- 回滚方式：恢复答题入口、事件发布服务和测试。

## M3-007

- 任务编号：`M3-007`
- 标题：机器人屏事件驱动动画
- 目标：机器人屏接收 `ANIMATION_REQUESTED`，播放 GIF，并向后端返回开始、完成和失败事件，重复事件按 commandId 去重。
- 非目标：不实现语音播放，不推进下一题，不做真实机器人 SDK。
- 前置依赖：`M3-002`、`M3-004`、`M3-005`、`M3-006`。
- 输入文档：`docs/DOMAIN_EVENTS.md`、`docs/ROBOT_ANIMATION_INTEGRATION.md`。
- 允许修改文件：机器人屏事件订阅逻辑、动画 ACK 客户端、后端 ACK 接收逻辑、测试。
- 禁止修改文件：GIF 文件、真实 TTS、判题规则。
- 共享文件 Owner：robot-event-playback owner。
- 实现步骤：机器人屏订阅当前 session；过滤非动画事件；按 commandId 去重；调用 adapter；发送 started/finished/failed ACK；处理过期事件和资源缺失。
- 测试要求：覆盖正常播放、失败 ACK、重复 commandId、页面刷新后不重复播放旧完成事件。
- 验收标准：机器人屏由后端事件驱动播放动画，并将结果回传后端。
- 验收命令：`npm run test:frontend`、`npm run test:backend`、`npm test`、`npm run build`、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：可与 `M3-008` 并行。
- 依赖任务：`M3-002`、`M3-004`、`M3-005`、`M3-006`。
- 风险：客户端 ACK 丢失会卡住后端编排，需要后续 `M3-009` 加超时。
- 回滚方式：恢复机器人事件消费和 ACK 逻辑。

## M3-008

- 任务编号：`M3-008`
- 标题：Mock TTS 或预录音播放
- 目标：使用 Mock TTS 或本地预录音验证语音播放开始、结束、失败和浏览器自动播放限制处理，不调用外部服务。
- 非目标：不接真实云端 TTS，不生成新语音资源，不实现口型同步。
- 前置依赖：`M3-002`；Mock Provider 契约已固定。
- 输入文档：`docs/SPEECH_LLM_PIPELINE.md`、`docs/PROJECT_OWNER_DECISIONS.md`、`docs/INTERACTION_STATE_MACHINE.md`。
- 允许修改文件：机器人屏本地音频播放逻辑、Mock TTS 播放事件、后端语音播放 ACK 接收、测试。
- 禁止修改文件：真实 `.env`、OpenAI provider、儿童原始音频上传逻辑、GIF 文件。
- 共享文件 Owner：mock-tts-playback owner。
- 实现步骤：定义本地音频播放 command；实现“启用声音”交互状态；播放 Mock/预录音；发送 TTS started/finished/failed；自动播放被阻止时进入可恢复状态。
- 测试要求：覆盖无音频、播放成功、播放失败、未启用声音和不调用外部 provider。
- 验收标准：机器人屏可用本地资源完成语音播放回执；默认环境不访问外部网络。
- 验收命令：`npm run test:frontend`、`npm run test:backend`、`npm test`、`npm run build`、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：可与 `M3-007` 并行。
- 依赖任务：`M3-002`。
- 风险：浏览器自动播放限制导致人工验收步骤必不可少。
- 回滚方式：恢复音频播放逻辑和 ACK 接口。

## M3-009

- 任务编号：`M3-009`
- 标题：动画、语音与下一题时序编排
- 目标：后端编排动画和语音的开始条件、完成条件、超时、中断和下一题推进，防止重复推进。
- 非目标：不引入正式状态持久化数据库，不实现真实安全审核模型，不改变专业评分。
- 前置依赖：`M3-006`、`M3-007`、`M3-008`。
- 输入文档：`docs/INTERACTION_STATE_MACHINE.md`、`docs/DOMAIN_EVENTS.md`、`docs/SYSTEM_ARCHITECTURE_V2.md`。
- 允许修改文件：后端训练编排服务、状态机应用逻辑、事件 ACK 处理、前端轻量状态显示、测试。
- 禁止修改文件：GIF 文件、真实 provider、评分规则、报告定位。
- 共享文件 Owner：training-orchestrator owner。
- 实现步骤：定义每个答题反馈 turn 的 command 集；记录动画/TTS pending 状态；收到完成回执后推进；失败或超时采用降级推进；重复 ACK 幂等；发布下一题事件或完成事件。
- 测试要求：覆盖正确答案、错误答案、动画完成、TTS 完成、失败、超时、重复 ACK 和刷新恢复。
- 验收标准：答题后只有在动画/语音完成或超时降级后进入下一题；不会重复进入下一题。
- 验收命令：`npm run test:backend`、`npm run test:e2e`、`npm test`、`npm run build`、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：否，核心编排任务。
- 依赖任务：`M3-006`、`M3-007`、`M3-008`。
- 风险：状态推进与现有 HTTP 课程 flow 冲突；需要保持现有 Demo 行为和新双屏行为兼容。
- 回滚方式：恢复编排服务、ACK 状态和测试。

## M3-010

- 任务编号：`M3-010`
- 标题：双屏 E2E 测试
- 目标：覆盖两个页面连接、正确答案、错误答案、GIF 播放请求、Mock 音频、完成回执、下一题、页面刷新、WebSocket 重连和重复事件。
- 非目标：不依赖真实双主机，不依赖真实硬件，不访问外部网络。
- 前置依赖：`M3-009`。
- 输入文档：`docs/TEST_FIXTURES.md`、`docs/DEMO_RUNBOOK.md`、`docs/DOMAIN_EVENTS.md`。
- 允许修改文件：E2E 测试、测试 fixtures、必要测试钩子。
- 禁止修改文件：业务规则、GIF 文件、真实 provider、Lock 文件，除非明确批准测试依赖。
- 共享文件 Owner：m3-e2e owner。
- 实现步骤：启动后端和静态前端；模拟 child 与 robot 两个客户端；提交正确和错误答案；断言事件链、动画请求和 ACK；模拟刷新/重连和重复事件；清理进程。
- 测试要求：测试不残留进程；不使用外部 API；对随机题目顺序有稳定处理。
- 验收标准：M3 最小闭环可通过自动化重跑证明。
- 验收命令：`npm run test:e2e`、`npm test`、`npm run build`、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：否，依赖 M3 核心功能完成。
- 依赖任务：`M3-009`。
- 风险：没有浏览器级工具时 GIF 视觉播放只能通过 DOM/事件验证，需另有人工验收。
- 回滚方式：删除 M3 E2E 测试和测试钩子。

## M3-011

- 任务编号：`M3-011`
- 标题：局域网双主机验收
- 目标：在后端主机和机器人 Windows 主机上完成浏览器访问、双屏启动、网络中断与恢复、GIF/Mock TTS 回执和验收记录。
- 非目标：不做生产部署，不配置真实公网访问，不接真实外部服务。
- 前置依赖：`M3-010`。
- 输入文档：`docs/DEMO_RUNBOOK.md`、`docs/PROJECT_OWNER_DECISIONS.md`、`docs/SYSTEM_ARCHITECTURE_V2.md`。
- 允许修改文件：验收 runbook、验收记录文档、必要配置示例。
- 禁止修改文件：业务代码、GIF 文件、真实 `.env`、密钥。
- 共享文件 Owner：lan-acceptance owner。
- 实现步骤：记录后端主机 IP 和端口；配置 Windows 防火墙放行；机器人主机打开 `/child` 与 `/robot`；验证会话共享；拔网或阻断连接后恢复；记录失败和环境信息。
- 测试要求：自动化测试先全部通过；人工验收记录必须区分已验证和待确认。
- 验收标准：双主机局域网最小闭环可演示；断线恢复路径可复现；无外部 API 调用。
- 验收命令：`npm test`、`npm run build`、`git diff --check`，加人工 LAN 验收清单。
- 是否允许使用 Worktree：不建议。
- 是否可以并行：否，需要完整 M3。
- 依赖任务：`M3-010`。
- 风险：Windows 防火墙、端口占用、浏览器自动播放和双屏显示配置会影响验收。
- 回滚方式：撤回 runbook 变更；关闭防火墙临时规则；恢复本机 Demo 配置。

## 推荐第一个 M3 编码任务

建议唯一第一个编码任务为 `M3-001 局域网运行时配置`。

原因：

- 当前事实：代码仍硬编码 `127.0.0.1`，与 D-001 的局域网双主机决策直接冲突。
- 当前事实：该任务风险低、修改范围相对小，不依赖真实双主机设备、不依赖 GIF 精确时长，也不依赖 WebSocket 业务事件。
- 当前事实：它能为后续 WebSocket URL、CORS、资源访问和双主机验收建立统一配置基础。
- 当前事实：可用 `npm test`、`npm run build` 和配置单元测试自动验证。
