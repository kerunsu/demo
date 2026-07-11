# M1/M2 工程任务拆分

当前事实：M1 先建立测试与契约基线，M2 再在测试保护下拆分热点文件。所有任务默认不调用真实外部 API，不写入密钥，不提交 Git commit。

## M1-001

- 任务编号：`M1-001`
- 标题：后端 API 自动化测试基线
- 工程目标：覆盖健康检查、创建会话、查询会话、获取当前题目、提交正确/错误答案、非法请求、不存在会话、默认规则聊天、报告生成和查询。
- 非目标：不拆分 `backend/src/index.ts`，不接入真实 LLM/TTS/STT，不修改前端。
- 前置依赖：M0 文档收口完成。
- 负责角色：backend-test implementer。
- Reviewer 角色：integration-test reviewer。
- 输入文档：`AGENTS.md`、`PROJECT_CONTEXT.md`、`docs/PROJECT_OWNER_DECISIONS.md`、`docs/API.md`、`docs/WORK_ITEMS_M1_M2.md`。
- 允许修改文件：`backend/**` 测试文件、后端测试配置、根级测试脚本中与后端测试相关的最小必要项。
- 禁止修改文件：`frontend/src/**`、`matching/**`、`paixu/**`、动画资源、真实 `.env`、package lock，除非安装测试依赖得到明确批准。
- 共享文件 Owner：backend-test owner。
- 实现步骤：确认现有后端启动方式；选择可重复的 API 测试方案；强制规则 Chat Provider 和 Noop TTS；编写不依赖随机题目顺序的测试；确保测试结束无残留进程。
- 测试要求：测试必须禁止真实外部 API 调用；覆盖成功、失败和边界路径。
- 验收标准：后端 API 基线稳定通过，默认 provider 为 rule/none，测试失败信息可定位。
- 验收命令：`npm run test:backend`、`npm run build`、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：否，首个编码任务独占后端测试边界。
- 依赖任务：无。
- 风险：当前后端 app/server 未分离时测试可能需要启动真实本地进程。
- 回滚方式：删除新增测试和测试配置，恢复脚本。

## M1-002

- 任务编号：`M1-002`
- 标题：前端构建与最小页面测试
- 工程目标：验证前端可构建，欢迎页可显示，课程选择页可进入，主要页面无启动级异常。
- 非目标：不重构 `App.tsx`，不改 UI 设计，不接双屏路由。
- 前置依赖：M1-001 可并行后置，但建议先完成后端测试基线。
- 负责角色：frontend-test implementer。
- Reviewer 角色：integration-test reviewer。
- 输入文档：`PROJECT_CONTEXT.md`、`docs/TARGET_PRODUCT_REQUIREMENTS.md`。
- 允许修改文件：`frontend/**` 测试文件、前端测试配置、必要的根级测试脚本。
- 禁止修改文件：`backend/src/**`、业务 UI 逻辑、素材、真实 `.env`、package lock，除非明确批准。
- 共享文件 Owner：frontend-test owner。
- 实现步骤：确认 Vite 构建；建立最小浏览器/组件测试；覆盖欢迎到选课；捕获启动异常。
- 测试要求：不得依赖外部网络；测试数据固定。
- 验收标准：前端最小测试和构建通过。
- 验收命令：`npm run test:frontend`、`npm run build`、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：可与 M1-004/M1-005 的纯契约设计并行，但不得共改根脚本。
- 依赖任务：无。
- 风险：测试框架引入可能影响依赖锁。
- 回滚方式：删除新增测试配置和测试文件。

## M1-003

- 任务编号：`M1-003`
- 标题：当前训练闭环 E2E 测试
- 工程目标：覆盖欢迎、选课、开始训练、获取题目、提交答案、反馈、完成训练、生成报告。
- 非目标：不实现双屏，不引入 WebSocket，不重写训练流程。
- 前置依赖：M1-001、M1-002。
- 负责角色：e2e-test implementer。
- Reviewer 角色：qa reviewer。
- 输入文档：`PROJECT_CONTEXT.md`、`docs/DEMO_RUNBOOK.md`、`docs/API.md`。
- 允许修改文件：E2E 测试目录、E2E 配置、必要测试 fixtures。
- 禁止修改文件：`frontend/src/App.tsx` 业务逻辑、`backend/src/index.ts` 业务逻辑、素材、真实 `.env`。
- 共享文件 Owner：integration-test owner。
- 实现步骤：启动前后端测试环境；使用稳定选择器或可观察文本；不依赖随机题目顺序；完成报告断言；清理进程。
- 测试要求：无残留进程；无真实外部 API；固定 provider。
- 验收标准：当前 Demo 主闭环可重复跑通。
- 验收命令：`npm run test:e2e`、`npm run build`、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：否，需等待 M1-001/M1-002。
- 依赖任务：M1-001、M1-002。
- 风险：当前页面缺少稳定测试标识，可能需要最小非业务测试钩子。
- 回滚方式：删除 E2E 测试和配置。

## M1-004

- 任务编号：`M1-004`
- 标题：领域事件 TypeScript 契约
- 工程目标：实现事件公共字段、事件类型、payload 类型、`schemaVersion` 和幂等字段的可编译契约。
- 非目标：不接 WebSocket，不发布真实事件，不改训练流程。
- 前置依赖：M0 决策收口。
- 负责角色：shared-contract owner。
- Reviewer 角色：architecture reviewer。
- 输入文档：`docs/DOMAIN_EVENTS.md`、`docs/PROJECT_OWNER_DECISIONS.md`。
- 允许修改文件：共享类型目录、契约测试、必要导出入口。
- 禁止修改文件：页面业务、后端路由业务、真实 provider。
- 共享文件 Owner：shared-contract owner。
- 实现步骤：选择共享类型位置；定义事件 union 和 payload；补契约测试；导出版本。
- 测试要求：TypeScript 编译和契约测试通过。
- 验收标准：事件类型可被前后端导入且不产生运行副作用。
- 验收命令：`npm run build`、相关契约测试、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：可与 M1-001/M1-002 并行，但不可与其他共享契约任务共改同文件。
- 依赖任务：无。
- 风险：共享目录位置选择会影响后续所有任务。
- 回滚方式：删除新增契约文件和导出。

## M1-005

- 任务编号：`M1-005`
- 标题：状态机类型与合法迁移
- 工程目标：定义状态类型、允许迁移表、非法迁移检测和单元测试。
- 非目标：不改造当前训练主流程，不驱动页面。
- 前置依赖：M1-004 可先行或并行协调。
- 负责角色：state-machine owner。
- Reviewer 角色：architecture reviewer。
- 输入文档：`docs/INTERACTION_STATE_MACHINE.md`、`docs/DOMAIN_EVENTS.md`。
- 允许修改文件：共享状态机类型、状态机测试。
- 禁止修改文件：`frontend/src/App.tsx`、`backend/src/services/sessionService.ts` 主流程。
- 共享文件 Owner：shared-contract owner。
- 实现步骤：定义状态枚举；编码合法迁移；实现纯函数校验；覆盖合法/非法迁移。
- 测试要求：单元测试覆盖主要状态和非法路径。
- 验收标准：状态机可独立测试，无业务副作用。
- 验收命令：状态机单元测试、`npm run build`、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：可与 M1-001/M1-002 并行。
- 依赖任务：无。
- 风险：状态命名与事件契约不一致。
- 回滚方式：删除状态机契约和测试。

## M1-006

- 任务编号：`M1-006`
- 标题：Provider 和 Mock 契约
- 工程目标：定义 STT、Chat/LLM、Safety Review、TTS、Attention Observation、Language Observation 接口和 Mock 实现边界。
- 非目标：不启用真实 STT/TTS/LLM，不发送外部请求。
- 前置依赖：M1-004 建议完成。
- 负责角色：provider-contract owner。
- Reviewer 角色：safety reviewer。
- 输入文档：`docs/PROJECT_OWNER_DECISIONS.md`、`docs/SPEECH_LLM_PIPELINE.md`、`docs/AI_CHILD_SAFETY_SPEC.md`。
- 允许修改文件：provider 接口、Mock provider、provider 契约测试。
- 禁止修改文件：真实 `.env`、OpenAI provider 行为、前端页面。
- 共享文件 Owner：provider-contract owner。
- 实现步骤：定义接口；实现 deterministic Mock；强制默认测试使用 rule/noop/mock；补超时和失败用例。
- 测试要求：无网络调用；Mock 输出固定。
- 验收标准：全部外部能力都有 Mock 边界。
- 验收命令：provider 契约测试、`npm run build`、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：接口固定后可拆 Mock 子任务；本任务本身由单 Owner 完成。
- 依赖任务：M1-004。
- 风险：接口过早绑定具体供应商。
- 回滚方式：删除新增 provider 契约和 Mock。

## M1-007

- 任务编号：`M1-007`
- 标题：Animation Adapter 契约
- 工程目标：定义 9 个 GIF 的 `animationId`、资源元数据、`play`、`stop`、`showIdle`、`isPlaying`、播放事件、`expectedDurationMs` 和 `loop`。
- 非目标：不实现真实双屏联动，不重新制作动画。
- 前置依赖：M1-004 建议完成。
- 负责角色：robot-display contract owner。
- Reviewer 角色：frontend reviewer。
- 输入文档：`docs/PROJECT_OWNER_DECISIONS.md`、`docs/ROBOT_ANIMATION_INTEGRATION.md`。
- 允许修改文件：动画契约、manifest、契约测试。
- 禁止修改文件：动画资源文件、训练业务流程。
- 共享文件 Owner：robot-display contract owner。
- 实现步骤：建立 `animationId` union；定义 manifest schema；定义 Adapter 接口；补播放事件类型测试。
- 测试要求：manifest 包含 9 个动画；不加载真实硬件。
- 验收标准：机器人页面后续可按契约实现 Adapter。
- 验收命令：动画契约测试、`npm run build`、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：可与 M1-006 并行，需共享事件字段对齐。
- 依赖任务：M1-004。
- 风险：GIF 实际路径和时长未最终确认。
- 回滚方式：删除动画契约和测试。

## M1-008

- 任务编号：`M1-008`
- 标题：根级测试命令与 Fixture 规范
- 工程目标：统一 `npm run test:backend`、`npm run test:frontend`、`npm run test:e2e`、`npm test` 和 fixture 目录规范。
- 非目标：不补写所有测试内容，不改业务逻辑。
- 前置依赖：M1-001、M1-002、M1-003 的实际脚本方案清晰。
- 负责角色：integration-test owner。
- Reviewer 角色：repo-maintainer reviewer。
- 输入文档：`docs/WORK_ITEMS_M1_M2.md`。
- 允许修改文件：根级/前端/后端 `package.json` 的测试脚本、测试 fixture 文档或目录。
- 禁止修改文件：package lock，除非明确安装依赖；业务代码。
- 共享文件 Owner：integration-test owner。
- 实现步骤：梳理已有测试脚本；统一命名；记录 fixture 规则；保证 `npm test` 可组合运行。
- 测试要求：脚本可本地重复执行。
- 验收标准：根级命令清晰，后续任务不再各自发明测试入口。
- 验收命令：`npm test`、`npm run build`、`git diff --check`。
- 是否允许使用 Worktree：允许。
- 是否可以并行：否，涉及共享脚本。
- 依赖任务：M1-001、M1-002、M1-003。
- 风险：脚本统一可能影响开发习惯。
- 回滚方式：恢复 package 脚本和 fixture 文档。

## M2-001

- 任务编号：`M2-001`
- 标题：Express App 与 Server 启动分离
- 工程目标：让 Express App 可在测试中直接导入，监听端口逻辑独立，API 行为不变。
- 非目标：不拆路由，不改业务服务。
- 前置依赖：M1-001。
- 负责角色：backend-orchestrator implementer。
- Reviewer 角色：backend-test reviewer。
- 输入文档：`docs/WORK_ITEMS_M1_M2.md`、`docs/API.md`。
- 允许修改文件：`backend/src/index.ts`、新增 app/server 入口、后端测试。
- 禁止修改文件：`frontend/src/**`、`sessionService.ts` 业务逻辑、素材。
- 共享文件 Owner：backend hotspot owner。
- 实现步骤：提取 app factory；保留原启动行为；更新测试导入方式；验证 API 响应不变。
- 测试要求：M1-001 全部通过。
- 验收标准：直接导入 app 可测，启动命令仍可运行。
- 验收命令：`npm run test:backend`、`npm run build`、`git diff --check`.
- 是否允许使用 Worktree：允许。
- 是否可以并行：否，独占 `backend/src/index.ts`。
- 依赖任务：M1-001。
- 风险：ESM 启动判断和端口监听处理不当。
- 回滚方式：恢复原入口文件。

## M2-002

- 任务编号：`M2-002`
- 标题：后端路由拆分
- 工程目标：将路由从 `backend/src/index.ts` 渐进拆出，保持 API 行为不变。
- 非目标：不重写核心业务，不改 API 字段。
- 前置依赖：M2-001。
- 负责角色：backend-orchestrator implementer。
- Reviewer 角色：backend-test reviewer。
- 输入文档：`docs/API.md`、`PROJECT_CONTEXT.md`。
- 允许修改文件：后端路由文件、`backend/src/index.ts` 最小连接代码、后端测试。
- 禁止修改文件：前端、`sessionService.ts` 业务规则、素材。
- 共享文件 Owner：backend hotspot owner。
- 实现步骤：按 health/session/course/report/chat 分组拆路由；保留错误 envelope；运行基线测试。
- 测试要求：M1-001 全部通过。
- 验收标准：路由职责清晰，外部 API 不变。
- 验收命令：`npm run test:backend`、`npm run build`、`git diff --check`.
- 是否允许使用 Worktree：允许。
- 是否可以并行：否，独占后端路由。
- 依赖任务：M2-001。
- 风险：错误处理顺序变化。
- 回滚方式：恢复原路由集中实现。

## M2-003

- 任务编号：`M2-003`
- 标题：Session 服务边界拆分
- 工程目标：从 `sessionService.ts` 提取会话生命周期边界，保持行为不变。
- 非目标：不拆 Course/Report/Chat，不引入数据库。
- 前置依赖：M1-001、M2-002。
- 负责角色：backend-service implementer。
- Reviewer 角色：backend-test reviewer。
- 输入文档：`PROJECT_CONTEXT.md`、`docs/API.md`。
- 允许修改文件：`backend/src/services/sessionService.ts`、新增 session 相关服务、后端测试。
- 禁止修改文件：前端、路由 API 字段、素材。
- 共享文件 Owner：sessionService hotspot owner。
- 实现步骤：识别会话创建/查询/状态字段；提取纯边界；保持公开方法兼容；跑测试。
- 测试要求：M1-001 覆盖通过。
- 验收标准：会话职责更清晰，训练行为不变。
- 验收命令：`npm run test:backend`、`npm run build`、`git diff --check`.
- 是否允许使用 Worktree：允许。
- 是否可以并行：否，独占 `sessionService.ts`。
- 依赖任务：M2-002。
- 风险：内存 Map 引用和 report 依赖耦合。
- 回滚方式：恢复原服务文件。

## M2-004

- 任务编号：`M2-004`
- 标题：Course 服务边界拆分
- 工程目标：提取课程题目生成、当前题目和答题判定边界。
- 非目标：不改变题目顺序、判题规则或素材扫描规则。
- 前置依赖：M2-003。
- 负责角色：backend-service implementer。
- Reviewer 角色：backend-test reviewer。
- 输入文档：`docs/API.md`、`PROJECT_CONTEXT.md`。
- 允许修改文件：`backend/src/services/sessionService.ts`、新增 course 服务、后端测试。
- 禁止修改文件：素材、前端、报告 UI。
- 共享文件 Owner：sessionService hotspot owner。
- 实现步骤：提取课程队列/题目访问逻辑；保持原公开 API；补回归测试。
- 测试要求：正确/错误答题、当前题、完成状态测试通过。
- 验收标准：课程职责可独立维护，行为不变。
- 验收命令：`npm run test:backend`、`npm run build`、`git diff --check`.
- 是否允许使用 Worktree：允许。
- 是否可以并行：否。
- 依赖任务：M2-003。
- 风险：随机题目顺序导致测试脆弱。
- 回滚方式：恢复原服务文件。

## M2-005

- 任务编号：`M2-005`
- 标题：Report 服务边界拆分
- 工程目标：提取报告生成和查询边界，保持当前报告 API 行为不变。
- 非目标：不新增正式评分，不修改专业报告文案。
- 前置依赖：M2-003。
- 负责角色：backend-service implementer。
- Reviewer 角色：backend-test reviewer。
- 输入文档：`docs/REPORT_SCHEMA.md`、`docs/PROJECT_OWNER_DECISIONS.md`。
- 允许修改文件：`backend/src/services/sessionService.ts`、新增 report 服务、后端测试。
- 禁止修改文件：前端报告页面、正式评估规则、外部 LLM。
- 共享文件 Owner：sessionService hotspot owner。
- 实现步骤：提取报告生成输入/输出；保留内存报告行为；测试生成和查询。
- 测试要求：报告生成、重复查询、不存在会话覆盖。
- 验收标准：报告边界独立，报告定位仍为教育辅助参考。
- 验收命令：`npm run test:backend`、`npm run build`、`git diff --check`.
- 是否允许使用 Worktree：允许。
- 是否可以并行：否。
- 依赖任务：M2-003。
- 风险：报告字段与前端类型不一致。
- 回滚方式：恢复原服务文件。

## M2-006

- 任务编号：`M2-006`
- 标题：Chat 服务边界拆分
- 工程目标：提取规则聊天和 voice orchestrator 调用边界，保持默认 rule/noop 行为。
- 非目标：不启用真实 LLM/TTS，不改儿童安全策略。
- 前置依赖：M1-006、M2-003。
- 负责角色：backend-service implementer。
- Reviewer 角色：safety reviewer。
- 输入文档：`docs/SPEECH_LLM_PIPELINE.md`、`docs/AI_CHILD_SAFETY_SPEC.md`。
- 允许修改文件：`backend/src/services/sessionService.ts`、chat/voice 边界文件、后端测试。
- 禁止修改文件：真实 `.env`、OpenAI provider 配置、前端语音 UI。
- 共享文件 Owner：sessionService hotspot owner。
- 实现步骤：隔离聊天历史和 provider 调用；强制测试使用 rule/noop；覆盖 provider 失败回退。
- 测试要求：无外部网络；规则回复稳定。
- 验收标准：聊天边界清晰且默认无 TTS。
- 验收命令：`npm run test:backend`、`npm run build`、`git diff --check`.
- 是否允许使用 Worktree：允许。
- 是否可以并行：否。
- 依赖任务：M1-006、M2-003。
- 风险：误启真实 provider。
- 回滚方式：恢复原服务文件。

## M2-007

- 任务编号：`M2-007`
- 标题：前端页面壳拆分
- 工程目标：建立欢迎、选课、训练、报告等清晰页面边界，保持当前功能行为。
- 非目标：不实现 `/child` 和 `/robot` 独立入口，不接 WebSocket。
- 前置依赖：M1-002、M1-003。
- 负责角色：child-ui implementer。
- Reviewer 角色：frontend-test reviewer。
- 输入文档：`PROJECT_CONTEXT.md`、`docs/TARGET_PRODUCT_REQUIREMENTS.md`。
- 允许修改文件：`frontend/src/App.tsx`、新增页面组件、前端测试。
- 禁止修改文件：后端、素材、API 字段。
- 共享文件 Owner：App.tsx hotspot owner。
- 实现步骤：按现有 `page` 状态提取页面壳；保持 props 明确；运行最小页面和 E2E。
- 测试要求：M1-002/M1-003 通过。
- 验收标准：页面边界清晰，用户流程不变。
- 验收命令：`npm run test:frontend`、`npm run test:e2e`、`npm run build`、`git diff --check`.
- 是否允许使用 Worktree：允许。
- 是否可以并行：否，独占 `App.tsx`。
- 依赖任务：M1-002、M1-003。
- 风险：拆 props 时破坏状态流。
- 回滚方式：恢复 `App.tsx` 和新增组件。

## M2-008

- 任务编号：`M2-008`
- 标题：`/child` 和 `/robot` 页面壳
- 工程目标：建立儿童屏和机器人表情屏入口及共享配置，不实现完整 WebSocket 和动画联动。
- 非目标：不实现真实双屏同步，不播放真实 TTS，不接硬件。
- 前置依赖：M1-004、M1-007、M2-007。
- 负责角色：frontend-shell implementer。
- Reviewer 角色：architecture reviewer。
- 输入文档：`docs/PROJECT_OWNER_DECISIONS.md`、`docs/SYSTEM_ARCHITECTURE_V2.md`。
- 允许修改文件：前端路由/入口、共享配置、页面壳测试。
- 禁止修改文件：后端业务、动画资源、真实 provider。
- 共享文件 Owner：frontend shell owner。
- 实现步骤：建立路由识别；`/child` 承载现有儿童流程；`/robot` 显示占位表情屏状态；共享 runtime config。
- 测试要求：两个入口可构建和打开，无启动异常。
- 验收标准：页面壳存在但不伪装为已完成双屏联动。
- 验收命令：`npm run test:frontend`、`npm run build`、`git diff --check`.
- 是否允许使用 Worktree：允许。
- 是否可以并行：否，涉及前端入口。
- 依赖任务：M1-004、M1-007、M2-007。
- 风险：路由改动影响现有 `/` Demo。
- 回滚方式：恢复前端入口和路由。

## M2-009

- 任务编号：`M2-009`
- 标题：前端课程逻辑拆分
- 工程目标：将课程选择、课程队列和答题流程从 `App.tsx` 逐步提取。
- 非目标：不改变课程行为、不改 API。
- 前置依赖：M2-007。
- 负责角色：child-ui implementer。
- Reviewer 角色：frontend-test reviewer。
- 输入文档：`PROJECT_CONTEXT.md`、`docs/API.md`。
- 允许修改文件：`frontend/src/App.tsx`、课程 hook/service、前端测试。
- 禁止修改文件：后端、素材、报告业务规则。
- 共享文件 Owner：App.tsx hotspot owner。
- 实现步骤：提取课程状态和动作；保持 UI 输出；跑 E2E。
- 测试要求：训练闭环通过。
- 验收标准：课程逻辑独立，行为不变。
- 验收命令：`npm run test:frontend`、`npm run test:e2e`、`npm run build`、`git diff --check`.
- 是否允许使用 Worktree：允许。
- 是否可以并行：否。
- 依赖任务：M2-007。
- 风险：课程队列和多课程报告合并耦合。
- 回滚方式：恢复 `App.tsx` 和新增文件。

## M2-010

- 任务编号：`M2-010`
- 标题：前端报告逻辑拆分
- 工程目标：将报告展示和报告派生逻辑从 `App.tsx` 逐步提取。
- 非目标：不修改报告定位，不新增正式评分。
- 前置依赖：M2-007。
- 负责角色：child-ui implementer。
- Reviewer 角色：report reviewer。
- 输入文档：`docs/REPORT_SCHEMA.md`、`docs/PROJECT_OWNER_DECISIONS.md`。
- 允许修改文件：`frontend/src/App.tsx`、报告组件/工具、前端测试。
- 禁止修改文件：后端报告生成、正式评估规则、LLM 文案。
- 共享文件 Owner：App.tsx hotspot owner。
- 实现步骤：提取报告展示组件；提取派生指标工具；保持文案边界；跑测试。
- 测试要求：报告页面和 E2E 完成态通过。
- 验收标准：报告逻辑更清晰，仍标记教育辅助参考边界。
- 验收命令：`npm run test:frontend`、`npm run test:e2e`、`npm run build`、`git diff --check`.
- 是否允许使用 Worktree：允许。
- 是否可以并行：否。
- 依赖任务：M2-007。
- 风险：演示指标被误改为正式结论。
- 回滚方式：恢复 `App.tsx` 和报告组件。

## M2-011

- 任务编号：`M2-011`
- 标题：前端语音逻辑拆分
- 工程目标：将浏览器语音识别、聊天发送和音频播放逻辑从 `App.tsx` 逐步提取。
- 非目标：不启用真实外部 STT/TTS/LLM，不实现机器人屏播放。
- 前置依赖：M1-006、M2-007。
- 负责角色：child-ui implementer。
- Reviewer 角色：safety reviewer。
- 输入文档：`docs/SPEECH_LLM_PIPELINE.md`、`docs/PROJECT_OWNER_DECISIONS.md`。
- 允许修改文件：`frontend/src/App.tsx`、语音 hook/service、前端测试。
- 禁止修改文件：后端 provider、真实 `.env`、外部 API 配置。
- 共享文件 Owner：App.tsx hotspot owner。
- 实现步骤：提取 speech recognition hook；提取 audio playback helper；保持默认聊天行为；跑测试。
- 测试要求：浏览器不支持语音时页面不崩溃；无外部网络。
- 验收标准：语音逻辑边界清晰，默认仍安全降级。
- 验收命令：`npm run test:frontend`、`npm run build`、`git diff --check`.
- 是否允许使用 Worktree：允许。
- 是否可以并行：否。
- 依赖任务：M1-006、M2-007。
- 风险：浏览器 API mock 不稳定。
- 回滚方式：恢复 `App.tsx` 和语音 helper。

## 推荐排序

1. `M1-001`
2. `M1-002`
3. `M1-003`
4. `M1-004`
5. `M1-005`
6. `M1-006`
7. `M1-007`
8. `M1-008`
9. `M2-001`
10. `M2-002`
11. `M2-003`
12. `M2-004`
13. `M2-005`
14. `M2-006`
15. `M2-007`
16. `M2-008`
17. `M2-009`
18. `M2-010`
19. `M2-011`

建议：唯一第一个编码任务为 `M1-001 后端 API 自动化测试基线`。当前文档和仓库事实没有显示该任务不能作为第一步。
