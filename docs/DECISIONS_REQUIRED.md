# M0 决策收口清单

当前事实：本文件按 `docs/PROJECT_OWNER_DECISIONS.md` 对 M0-M4 决策状态做收口。除 C 类问题外，未决事项不得阻止 M1/M2/M3 的测试、契约、Mock、热点文件渐进拆分和 M4 的开发服务器探测、本地/云端 STT/TTS Benchmark。

## A. 已关闭决定

| 决定编号 | 最终决定摘要 | 影响模块 | 后续执行阶段 |
| -- | -- | -- | -- |
| D-001 | 机器人 Windows 主机连接两个屏幕，运行 `/child` 和 `/robot`；后端运行在另一台局域网主机。 | frontend、backend、deploy、runtime config | M2/M3 |
| D-002 | 第一阶段继续使用一个 Vite + React 工程，提供两个独立页面，共享类型、事件契约、API/WebSocket 客户端和运行时配置。 | frontend、shared contracts | M1/M2 |
| D-003 | 后端训练会话是跨屏状态唯一事实源；HTTP 负责命令和查询，WebSocket 负责实时事件同步。 | backend、frontend、domain events、state machine | M1/M3 |
| D-004 | 现有 9 个 GIF 资源不重新制作；通过 `AnimationAdapter`、manifest、预期时长和循环配置统一播放。 | robot screen、animation adapter | M1/M3 |
| D-005 | 儿童屏采集语音；机器人表情屏播放 TTS；后端编排对话、安全审核、TTS 任务和播放事件。 | speech、robot screen、backend orchestration | M1/M3 |
| D-006 | 初始正式持久化方案为后端主机 SQLite，通过 Repository 接口隔离。 | backend、storage、report、events | M4 以后 |
| D-007 | 最终产品原始音视频外发仍受限；开发阶段允许用开发人员录制、合成或明确授权的非真实儿童测试音频/文本测试云端 STT/TTS。 | speech、behavior、privacy、LLM safety | M1/M4 |
| D-008 | 当前报告定位为训练表现分析和教育辅助参考，不作为临床诊断或正式医学评估。 | report、assessment、safety copy | M1/M6 |
| D-009 | 近期允许实现观测接口、Mock 注意力/语言观测和聚合框架；不实现未经确认的正式评分。 | behavior、assessment、report | M1/M5 |
| D-010 | 第一阶段目标是测试基线、共享契约、热点拆分、双屏页面结构和 Mock 双屏闭环。 | all engineering tracks | M1/M3 |
| D-011 | M4-001 当前结果标记为 `DEVELOPMENT_SERVER_BASELINE`，M4-001 状态为 `COMPLETE_FOR_DEVELOPMENT`，当前阶段不等待机器人主机性能探测。 | speech、runtime、benchmark | M4 |
| D-012 | M4 必须横向比较本地和云端 STT/TTS；Provider 支持 local/cloud/mock；云端 Key 缺失时标记 `CLOUD_CREDENTIALS_PENDING`。 | speech、provider、benchmark | M4 |

## B. 尚未决定但不阻塞 M1/M2

| 待确认事项 | 当前处理方式 | 不阻塞原因 | 后续需要确认阶段 |
| -- | -- | -- | -- |
| 正式 STT 模型 | M1/M2 只定义 `SttProvider` 与 Mock。 | 测试和接口可先固定，不需要真实供应商。 | 真实语音开发前 |
| 正式 TTS 模型 | M1/M2 只定义 `TtsProvider` 与 Noop/Mock。 | 双屏时序可用 Mock 或预录音验证。 | M3/M4 |
| 正式 LLM 供应商 | M1/M2 强制规则 Chat Provider 或 Mock LLM。 | API 测试和 provider 契约不依赖真实 LLM。 | 真实 LLM 接入前 |
| 安全审核正式供应商 | M1/M2 只定义 Safety Review 接口和 Mock。 | 安全边界可先作为契约和测试约束。 | M4/M7 |
| 注意力正式评分规则 | 只允许 Mock 观测、结构化事件和数据质量字段。 | 不影响测试、事件类型和拆分任务。 | M5/M6 |
| 语言表达正式评分规则 | 只允许 Mock 语言观测和描述性特征接口。 | 不影响 provider、事件和页面壳任务。 | M5/M6 |
| 正式报告标准 | 当前报告保持教育辅助参考，核心分数不得由 LLM 生成。 | M1/M2 不改正式评分和报告结论。 | M6 |
| GIF 精确播放时长 | M1 先建立 manifest 字段和默认值。 | Adapter 契约可先测试 `expectedDurationMs` 与 `loop` 字段。 | M3 动画集成前 |
| 是否允许儿童打断机器人语音 | 先定义取消事件和中断策略字段，不实现真实打断。 | 不影响 M1/M2 测试和结构拆分。 | M3/M4 |
| 最大交互时延 | 先在契约中保留超时字段和默认测试预算。 | 自动化测试可使用 Mock 固定时序。 | M3/M4 |
| 数据保留期限和删除策略 | M1/M2 不实现正式持久化；只保留接口边界说明。 | 当前阶段不落地 SQLite 生产策略。 | 存储实现前 |
| 语音服务技术栈 | M4-002 先搭 Benchmark Harness 横向比较 local/cloud/mock。 | 当前阶段不需要绑定模型或供应商。 | M4-002 后 |
| VAD/STT/TTS 具体本地或云端候选 | 先建立评价矩阵和 Benchmark，不在规划轮下载模型或写 Key。 | 不影响 M4-002 Harness 和 Provider 契约。 | M4-002 后 |
| 是否允许儿童打断机器人 | M4 第一版默认半双工，机器人说话时暂停识别，保留 barge-in 事件。 | 不阻塞基础语音链路。 | Barge-in 开发前 |

## C. 真正阻塞近期任务的问题

| 阻塞项 | 阻塞任务 | 原因 | 解除条件 |
| -- | -- | -- | -- |
| 领域事件契约未实现为可编译 TypeScript 类型 | M3 双屏实时同步实现 | 跨屏同步依赖统一事件字段、payload、幂等和版本。 | 完成 `M1-004` 并通过契约测试。 |
| 状态机合法迁移未实现为可测试规则 | M3 后端驱动双屏时序 | 动画、语音和下一题推进不能由两个屏幕各自决定。 | 完成 `M1-005` 并通过非法迁移测试。 |
| Provider/Mock 契约未固定 | 任何真实 STT/TTS/LLM/Safety 接入 | 未固定接口前接入真实 provider 会扩大隐私和回归风险。 | 完成 `M1-006` 并通过 Mock 契约测试。 |
| Animation Adapter 契约和 GIF manifest 未固定 | M3 机器人动画联动 | 没有统一 `animationId`、播放事件和预期完成机制时无法稳定同步。 | 完成 `M1-007` 并通过 Adapter 契约测试。 |
| 当前 Demo 行为缺少自动化测试基线 | M2 热点文件拆分 | 在没有 API/前端/E2E 基线前拆分 `index.ts`、`sessionService.ts` 或 `App.tsx` 风险过高。 | 完成 `M1-001`、`M1-002`、`M1-003` 的对应测试基线。 |

## D. M4 后续必须由项目负责人补充的信息

| 信息 | 阻塞范围 | 默认处理 |
| -- | -- | -- |
| 正式高性能服务器硬件 | 阻塞最终部署 sizing，不阻塞当前开发服务器 M4-002。 | 当前用 `DEVELOPMENT_SERVER_BASELINE`。 |
| 麦克风型号和现场噪声条件 | 阻塞 VAD 阈值和最终验收，不阻塞 Benchmark Harness。 | 先用可配置阈值和测试 fixture。 |
| 最终产品是否允许真实儿童音频上传云端 | 阻塞真实儿童数据云端 STT，不阻塞开发阶段授权测试音频 Benchmark。 | 默认最终产品未批准。 |
| 是否保存转写文本及保留期限 | 阻塞正式持久化，不阻塞脱敏摘要和临时 turn。 | 默认只保存脱敏摘要或指标。 |
| 最大可接受语音轮次延迟 | 阻塞最终验收阈值，不阻塞 M4-002。 | M4-002 先记录实测。 |
| 本地模型许可证和云端服务条款 | 阻塞最终 Provider 定稿，不阻塞候选评价。 | M4-002 记录许可证、费用和数据边界风险。 |

## E. M5 前后需要补充确认的信息

| 信息 | 阻塞范围 | 默认处理 |
| -- | -- | -- |
| 注意力/任务参与度的正式定义、阈值和报告措辞 | 阻塞 M6 正式注意力评分，不阻塞 M5 采集、Mock、窗口和质量标记。 | M5 使用“任务参与/粗粒度关注状态”，不写诊断性结论。 |
| 普通摄像头可接受的观测能力 | 阻塞真实注意力算法定稿，不阻塞 M5 Provider skeleton。 | 仅记录人脸存在、人数、粗粒度头部朝向、图像质量和置信度。 |
| 是否允许短期缓存低帧率图像样本 | 阻塞真实视觉调试缓存，不阻塞默认不保存原始图像的实现。 | 默认不保存原始图像、视频帧或视频文件。 |
| 真实机器人摄像头型号、安装角度、光照和遮挡场景 | 阻塞现场准确性验收，不阻塞开发机 Mock 和契约。 | `ENVIRONMENT_PENDING`，先用 fixture 和 Mock。 |
| 语言表达正式维度、权重、年龄段差异和禁用措辞 | 阻塞 M6 语言评分，不阻塞 M5 确定性特征。 | M5 只输出描述性特征和 Provider evidence。 |
| 题目相关性/表达完整度是否可进入评分 | 阻塞 M6 规则组合，不阻塞 M5 Provider 接口。 | M5 记录 provider、rule/model version、confidence、evidence 和降级状态。 |
| Transcript 长期保存策略 | 阻塞正式持久化策略，不阻塞脱敏摘要、长度、hash 和短期 turn 处理。 | 默认保存脱敏 normalized transcript 或最小必要 metadata。 |
