# M4 工程任务拆分：开发阶段真实语音交互链路

当前事实：当前处于开发阶段，所有开发和自动化测试暂时在当前本机完成。当前本机暂时视为高性能服务器开发环境，M4-001 硬件结果标记为 `DEVELOPMENT_SERVER_BASELINE`。

当前事实：未来实际部署时，机器人设备只负责 `/child` 页面、`/robot` 页面、麦克风和摄像头采集、GIF 动画与音频播放。机器人端本身不承担 VAD、STT、TTS、视觉分析或大模型等高性能计算。

当前事实：当前 Codex 无法访问机器人设备，这不阻塞 M4 开发；当前阶段暂不要求探测真实机器人主机性能。

当前事实：开发阶段允许用开发人员录制的测试语音、合成音频和明确授权的非真实儿童测试音频横向测试本地和云端 STT/TTS。最终产品是否允许真实儿童音频上传云端，仍为待负责人和隐私流程确认的决策。

建议：M4 必须横向比较本地和云端 STT/TTS，而不是预设只采用本地方案。

## M4 产品目标

M4 的目标是建立真实、可运行、可测试、可替换 Provider 的语音交互链路：

```text
浏览器采集端
-> 媒体接入接口
-> STT Provider
-> 对话编排
-> TTS Provider
-> 机器人页面播放端
```

非目标：M4 不实现正式外部 LLM、正式儿童安全审核模型、正式注意力检测、语言能力正式评分、报告扩展、临床或专业评估、原始音视频长期持久化、M5 及后续功能。

## 开发阶段数据规则

允许：

- 使用开发人员录制的测试语音。
- 使用合成音频。
- 使用明确授权的非真实儿童测试音频。
- 将上述测试音频发送给云端 STT。
- 将测试文本发送给云端 TTS。
- 对比本地与云端性能、准确率、稳定性和成本。

禁止：

- 默认使用真实儿童语音。
- 未经授权上传真实儿童音频。
- 将真实 API Key 写入仓库。
- 在日志中长期保存完整音频或敏感文本。
- 将开发阶段允许上传理解为最终产品已经批准儿童数据上云。

## M3/M4 基线

| 检查项 | 当前结论 |
| -- | -- |
| 分支 | 当前事实：`codex/overnight-m1-m2`。 |
| M3 状态 | 当前事实：M3-001 至 M3-010 代码基线已提交并通过自动化；M3-011 真实部署验收仍为后续现场风险。 |
| M4-001 | 当前事实：开发服务器能力探测产物已生成，状态为 `COMPLETE_FOR_DEVELOPMENT`。 |
| M4-001 标签 | 当前事实：`DEVELOPMENT_SERVER_BASELINE`。 |
| 机器人主机探测 | 当前事实：当前阶段不再作为 M4 开发前置阻塞项。 |
| 业务代码 | 当前事实：M4-001/M4-002 文档和 Harness 准备不得修改正式训练业务逻辑。 |

## 技术路线比较

| 方案 | 优点 | 风险 | M4 建议 |
| -- | -- | -- | -- |
| A. 纯浏览器语音链路 | 与页面集成少；权限和状态可视化直接；适合浏览器能力对照。 | 浏览器 STT 不一定本地；刷新和权限影响模型生命周期；自动播放限制明显。 | 作为对照和降级，不作为唯一主链路。 |
| B. 开发服务器/未来高性能服务器语音服务 | 算力集中；适合统一管理 VAD/STT/TTS/视觉分析/模型生命周期；机器人端轻量。 | 需要媒体传输、局域网延迟、服务恢复、数据边界和部署配置。 | 当前主线之一，M4-002 必测。 |
| C. 本地 Provider | 可离线、隐私边界强、成本稳定。 | 模型体积、部署、普通话准确率、实时性和硬件加速不确定。 | 与云端 Provider 横向比较。 |
| D. 云端 Provider | 启动快、准确率/音质可能更好、维护成本低。 | 网络、费用、Key 管理、隐私审批和最终产品合规风险。 | 开发阶段允许用授权测试数据 Benchmark；最终儿童数据上云仍待确认。 |

## Provider 要求

STT Provider 类型：

- `local`
- `cloud`
- `mock`

TTS Provider 类型：

- `local`
- `cloud`
- `mock`

接口至少覆盖：

- 初始化；
- 健康检查；
- 请求；
- 取消；
- 超时；
- 错误；
- Provider 标识；
- 模型标识；
- 耗时；
- 是否发生外部网络调用；
- 输入数据是否持久化；
- 降级路径。

建议：业务编排只依赖 Provider 契约，不直接绑定某个供应商 SDK。

## 执行顺序总览

近期任务顺序调整为：

1. `M4-001` 开发服务器能力探测，视为开发阶段完成。
2. `M4-002` 本地与云端 STT/TTS Benchmark。
3. 固定 Provider 契约。
4. 浏览器音频采集。
5. 媒体传输。
6. STT 集成。
7. Transcript 处理。
8. 轮次控制。
9. TTS 集成。
10. 机器人屏播放与动画同步。
11. 降级。
12. 可观测性。
13. E2E。
14. 最终真实部署验收。

机器人硬件性能探测不再作为当前 M4 的前置阻塞项。

## M4-001

- 任务编号：`M4-001`
- 标题：开发服务器语音运行时与硬件能力探测
- 状态：`COMPLETE_FOR_DEVELOPMENT`
- 结果标签：`DEVELOPMENT_SERVER_BASELINE`
- 目标：保留并复用当前开发服务器能力探测，为 M4-002 本地/云端 Benchmark 提供运行环境基线。
- 非目标：不探测真实机器人性能；不安装语音模型；不录制真实儿童语音；不改训练流程。
- 产物：`tools/voice-runtime/Collect-VoiceRuntimeCapabilities.ps1`、`docs/VOICE_RUNTIME_CAPABILITY_REPORT.md`、`.runtime/` 忽略规则。
- 后续：未来正式服务器硬件确定后，可以再次运行同一探测脚本。

## M4-002

- 任务编号：`M4-002`
- 标题：本地与云端 STT/TTS 技术 Spike 和横向 Benchmark
- 目标：搭建可重复 Benchmark Harness，横向比较本地 STT、云端 STT、本地 TTS、云端 TTS及其端到端组合，形成后续 Provider 契约和集成路线输入。
- 非目标：不完成完整语音产品链路；不接真实儿童数据；不把任何云端候选设为最终产品默认；不修改正式训练业务逻辑。
- 前置依赖：`M4-001 COMPLETE_FOR_DEVELOPMENT`。
- 输入文档：`docs/M4_TECHNICAL_DECISIONS.md`、`docs/VOICE_RUNTIME_CAPABILITY_REPORT.md`、`docs/SPEECH_LLM_PIPELINE.md`、`docs/AI_CHILD_SAFETY_SPEC.md`。
- 负责模块：Benchmark Harness、Provider 插件式接口草案、测试 fixture 规范、Benchmark 报告。
- 允许修改文件：独立 Benchmark 工具目录、Benchmark 报告、M4 决策文档、测试 fixture 规范。
- 禁止修改文件：`frontend/src/`、`backend/src/` 正式业务代码、真实 `.env`、lock 文件、模型文件、未授权测试音频。
- 共享文件 Owner：m4-speech-benchmark owner。
- 实现步骤：
  1. 定义 STT/TTS Provider 插件式接口。
  2. 定义 Benchmark result JSON schema。
  3. 建立 mock/local/cloud 候选注册机制。
  4. 本地候选无 Key 即可运行；云端候选仅环境变量存在时运行。
  5. 云端 Key 缺失时输出 `CLOUD_CREDENTIALS_PENDING`，不阻塞本地 Benchmark。
  6. 输出 `.runtime/voice-benchmark-results.json` 和 Markdown 报告。
  7. 记录所有候选是否访问外部网络、是否持久化输入、失败和降级路径。
- 自动化测试：Harness schema、mock provider 成功/失败/超时、缺云端 Key 不失败、输出 JSON 可解析。
- 人工测试：开发人员授权语音或合成音频、云端 Key 存在时的可选云端测试。
- 验收标准：能决定后续本地/云端 Provider 优先级；缺少云端 Key 不阻塞接口和测试框架；不提交真实 Key 或测试音频。
- 验收命令：`npm test`、`npm run build`、`git diff --check`，加 Benchmark Harness 命令。
- 是否可使用 Worktree：允许。
- 是否可并行：本轮不并行；Provider 契约稳定后可拆分候选实现。
- 依赖任务：`M4-001`。
- 数据安全风险：误用真实儿童音频、日志保存敏感文本、Key 泄露；必须通过 fixture 规则和日志脱敏控制。
- 性能风险：短 Benchmark 不代表长时间运行；M4-014 最终部署验收补充。
- 回滚方式：删除独立 Harness 和报告，恢复决策文档。

### M4-002 Benchmark 指标

STT：

- 初始化时间；
- 模型加载时间；
- 音频时长；
- Partial 首次返回时间；
- Final 返回时间；
- Real-time Factor；
- 识别文本；
- 基础准确性观察；
- 普通话支持；
- 噪声表现；
- CPU；
- GPU；
- 内存；
- 是否访问外部网络；
- 失败类型；
- 重试表现。

TTS：

- 初始化时间；
- 首包时延；
- 总合成时延；
- 音频时长；
- 音频格式；
- 普通话可懂度；
- 主观自然度记录；
- CPU；
- GPU；
- 内存；
- 是否访问外部网络；
- 失败类型；
- 重试表现。

端到端：

- 采集到 Transcript；
- Transcript 到回复文本；
- 回复文本到音频可播放；
- 整体轮次时延；
- 降级路径；
- 网络断开表现。

## M4-003

- 任务编号：`M4-003`
- 标题：固定 STT/TTS Provider 契约
- 目标：将 M4-002 验证过的 Provider 接口固化为共享契约，覆盖 local/cloud/mock、metadata、超时、取消、错误、外部网络和持久化声明。
- 默认路线输入：M4-002B 阶段性决定为 `LOCAL_PRIMARY_CLOUD_OPTIONAL` STT + `LOCAL_PRIMARY_CLOUD_OPTIONAL` TTS。
- 默认 STT Provider：`local-vosk-small-cn`，模型路径 `.runtime/models/vosk/vosk-model-small-cn-0.22`，仅作为开发服务器本地候选默认值。
- 默认 TTS Provider：`local-piper-zh-huayan`，模型路径 `.runtime/models/piper/zh_CN-huayan-medium.onnx`，人工试听与许可证复核仍为后续门槛。
- 推荐技术栈：`Node.js 训练编排后端 -> Provider 接口 -> 独立 Python 语音推理服务`。
- 依赖任务：`M4-002`、`M4-002B`。

## M4-002B

- 任务编号：`M4-002B`
- 标题：真实 STT/TTS 候选验证与技术路线收口
- 状态：`PROVISIONAL_PROVIDER_DECISION`
- 目标：在 M4-002 Harness 上实际验证少量代表性本地 STT/TTS 候选，并为 M4-003 之后固定 Provider 契约提供默认路线。
- 当前事实：真实本地 STT `local-vosk-small-cn` 已运行；真实本地 TTS `local-piper-zh-huayan` 已运行；Windows SAPI 已实测失败；云端 OpenAI STT/TTS 因缺凭据仍为 `CLOUD_CREDENTIALS_PENDING`。
- 当前事实：测试资料为 Piper 合成普通话语音、生成静音、生成噪声和固定普通话测试文本；未使用真实儿童语音。
- 当前事实：模型、音频和 venv 均位于 Git 忽略目录，不进入仓库。
- 建议：后续不得擅自更换默认 STT/TTS 模型；只有在云端凭据可用、硬件变化、人工试听失败、许可证复核失败或新候选 Benchmark 明显优于当前候选时，才触发重新 Benchmark。
- 后续输入：`docs/VOICE_STT_TTS_BENCHMARK_REPORT.md` 和 `.runtime/voice-benchmark/real-local-validation.json`。

## M4-004

- 任务编号：`M4-004`
- 标题：浏览器音频采集
- 目标：建立权限、设备选择、开始/停止、设备断开、音频级别展示和不默认持久化原始音频的采集层。
- 依赖任务：`M4-003`。

## M4-005

- 任务编号：`M4-005`
- 标题：媒体传输
- 目标：定义浏览器采集端到开发服务器/未来高性能服务器的媒体传输接口，支持本地开发和未来 LAN 配置切换。
- 依赖任务：`M4-004`。

## M4-006

- 任务编号：`M4-006`
- 标题：STT 集成
- 目标：接入可替换 STT Provider，支持 local/cloud/mock、partial/final、置信度、取消、超时和错误。
- 依赖任务：`M4-003`、`M4-005`。

## M4-007

- 任务编号：`M4-007`
- 标题：Transcript 处理
- 目标：处理空文本、重复文本、低置信度、基础敏感信息检测、去标识化接口。
- 依赖任务：`M4-006`。

## M4-008

- 任务编号：`M4-008`
- 标题：语音轮次控制
- 目标：实现开始监听、停止监听、机器人说话时暂停识别、超时、重试、恢复和 barge-in 预留。
- 依赖任务：`M4-006`、`M4-007`。

## M4-009

- 任务编号：`M4-009`
- 标题：TTS 集成
- 目标：接入可替换 TTS Provider，支持 local/cloud/mock、文本输入、audio ready、开始/完成/失败回执。
- 依赖任务：`M4-003`、`M4-007`。

## M4-010

- 任务编号：`M4-010`
- 标题：机器人屏播放与动画同步
- 目标：处理 TTS ready、播放、说话动画、播放完成、播放失败、回到待机或倾听，并避免重复推进状态。
- 依赖任务：`M4-008`、`M4-009`。

## M4-011

- 任务编号：`M4-011`
- 标题：故障与降级
- 目标：覆盖麦克风不可用、媒体传输失败、STT/TTS provider 不可用、低置信度、WebSocket 断开、文字交互或固定音频降级。
- 依赖任务：`M4-010`。

## M4-012

- 任务编号：`M4-012`
- 标题：可观测性和延迟指标
- 目标：记录采集、传输、STT、回复生成、TTS、播放和总轮次延迟、错误类型，不默认记录原始音频或敏感文本。
- 依赖任务：`M4-010`。

## M4-013

- 任务编号：`M4-013`
- 标题：E2E 与测试 Fixture
- 目标：建立合成测试音频、授权非儿童测试音频、Mock 麦克风、Mock STT、Mock TTS、可关闭云端测试的 E2E 结构。
- 依赖任务：`M4-003` 至 `M4-012`。

## M4-014

- 任务编号：`M4-014`
- 标题：最终真实部署验收
- 目标：在真实机器人浏览器终端、局域网、高性能服务器、麦克风、扬声器和双屏环境中验收语音播放、动画同步和长时间运行。
- 依赖任务：`M4-013`。

## 推荐下一个编码任务

建议唯一下一任务为 `M4-002 本地与云端 STT/TTS 技术 Spike 和横向 Benchmark`。

原因：

- 当前事实：M4-001 已作为开发服务器 baseline 完成。
- 当前事实：M4 的关键未知从“机器人端硬件性能”变为“本地与云端 Provider 的准确率、延迟、稳定性、成本和安全边界”。
- 建议：先搭建可重复 Benchmark Harness，再固定 Provider 契约，避免业务逻辑绑定供应商 SDK。
