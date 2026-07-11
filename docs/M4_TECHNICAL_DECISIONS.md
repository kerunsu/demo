# M4 Technical Decisions

本文记录 M4 真实语音交互链路的开发阶段决策、默认值和待确认项。状态含义：

- `CONFIRMED`：已由项目负责人确认，或由当前代码/探测结果验证。
- `DEFAULT_FOR_M4`：M4 可先采用的可逆默认方案。
- `NEEDS_BENCHMARK`：必须由 M4-002 或后续 Spike 数据决定。
- `OWNER_REQUIRED_BEFORE_PRODUCTION`：最终产品或真实儿童数据使用前需要负责人、隐私或安全流程确认。
- `CAN_DEFER`：不阻塞 M4 近期开发。

## 最新阶段边界

当前事实：当前项目处于开发阶段，所有开发和自动化测试暂时在当前本机完成。

当前事实：当前本机暂时视为高性能服务器开发环境，M4-001 探测结果重新标记为 `DEVELOPMENT_SERVER_BASELINE`，M4-001 状态为 `COMPLETE_FOR_DEVELOPMENT`。

当前事实：当前阶段暂不要求探测真实机器人主机性能，Codex 无法访问机器人设备不阻塞 M4 开发。

当前事实：未来实际部署时，机器人设备只负责 `/child`、`/robot`、麦克风和摄像头采集、GIF 动画与音频播放；机器人端不承担 VAD、STT、TTS、视觉分析或大模型等高性能计算。

建议：M4 代码必须保持逻辑边界：

```text
浏览器采集端
-> 媒体接入接口
-> STT Provider
-> 对话编排
-> TTS Provider
-> 机器人页面播放端
```

建议：未来迁移到“机器人浏览器终端 -> 局域网 -> 高性能服务器”时，应主要通过配置和部署变化完成，不应重写 Provider 和业务编排。

## 开发阶段语音数据规则

当前事实：开发阶段允许使用开发人员录制的测试语音、合成音频、明确授权的非真实儿童测试音频，并允许将这些测试音频发送给云端 STT、将测试文本发送给云端 TTS，用于横向比较本地与云端性能、准确率、稳定性和成本。

当前事实：开发阶段禁止默认使用真实儿童语音、未经授权上传真实儿童音频、将真实 API Key 写入仓库、在日志中长期保存完整音频或敏感文本。

待确认：最终产品是否允许真实儿童音频上传云端，仍需项目负责人和隐私流程确认。开发阶段允许测试云端服务，不等于最终产品已批准儿童数据上云。

## 决策表

| 项目 | 状态 | 当前值或默认值 | 说明 |
| -- | -- | -- | -- |
| M4-001 状态 | `CONFIRMED` | `COMPLETE_FOR_DEVELOPMENT` | 现有能力报告作为开发服务器 baseline；未来正式服务器硬件确定后可复跑脚本。 |
| 当前硬件标签 | `CONFIRMED` | `DEVELOPMENT_SERVER_BASELINE` | 不再等待机器人主机探测。 |
| 机器人端职责 | `CONFIRMED` | 浏览器页面、采集、播放、动画。 | 不承担高性能模型推理。 |
| 高性能计算位置 | `DEFAULT_FOR_M4` | 当前开发服务器；未来高性能服务器。 | 通过 LAN 与机器人浏览器终端连接。 |
| M4-002 定义 | `CONFIRMED` | 本地与云端 STT/TTS 技术 Spike 和横向 Benchmark。 | 不预设只采用本地方案。 |
| STT Provider 类型 | `CONFIRMED` | `local`、`cloud`、`mock`。 | 云端候选仅环境变量存在时执行。 |
| TTS Provider 类型 | `CONFIRMED` | `local`、`cloud`、`mock`。 | 本地和云端同一接口，不绑定业务逻辑。 |
| 云端 STT/TTS 开发测试 | `CONFIRMED` | 允许使用授权测试音频/文本。 | 禁止真实儿童音频默认上云。 |
| API Key 管理 | `CONFIRMED` | 只读环境变量；`.env.example` 只记录变量名。 | 禁止提交真实 Key。 |
| 真实儿童音频上云 | `OWNER_REQUIRED_BEFORE_PRODUCTION` | 未批准。 | 最终产品需隐私和负责人流程。 |
| VAD 候选 | `NEEDS_BENCHMARK` | 本地 WebRTC VAD、Silero VAD、能量阈值等。 | 云端 STT 也可能内置端点检测，需记录边界。 |
| 本地 STT 候选 | `NEEDS_BENCHMARK` | Whisper/FunASR/Vosk/其他普通话本地引擎。 | M4-002 可先少量代表性候选。 |
| 云端 STT 候选 | `NEEDS_BENCHMARK` | 由环境变量和已批准供应商配置决定。 | 缺 Key 时标记 `CLOUD_CREDENTIALS_PENDING`，不阻塞本地 Benchmark。 |
| 本地 TTS 候选 | `NEEDS_BENCHMARK` | Windows 本地 TTS、浏览器 Speech Synthesis、本地模型 TTS。 | 优先验证可听、可 ACK、可配置。 |
| 云端 TTS 候选 | `NEEDS_BENCHMARK` | 由环境变量和已批准供应商配置决定。 | 只发送测试文本，不发送敏感数据。 |
| Provider 契约 | `DEFAULT_FOR_M4` | 初始化、健康检查、请求、取消、超时、错误、provider/model 标识、耗时、外部网络调用、持久化声明、降级路径。 | M4-002 先搭 Benchmark Harness 和插件式接口。 |
| 数据持久化 | `DEFAULT_FOR_M4` | Benchmark 输出保存结构化指标；测试音频默认不提交 Git。 | 原始音频和敏感文本不长期保存。 |
| 最大轮次延迟 | `OWNER_REQUIRED_BEFORE_PRODUCTION` | 开发阶段先记录，不承诺。 | M4-002 用实测数据支持后续决策。 |
| 真实外部 LLM | `CAN_DEFER` | 不属于 M4-002。 | M4 仍使用 Rule/Mock Chat Provider。 |

## M4-002B 真实候选验证结论

当前事实：M4-002B 在 `DEVELOPMENT_SERVER_BASELINE` 上完成真实本地候选验证，状态为 `PROVISIONAL_PROVIDER_DECISION`。现有 M4-002 Harness 状态保持 `BENCHMARK_HARNESS_COMPLETE`，不删除或否定首轮结果。

当前事实：本地 STT 候选 `local-vosk-small-cn` 使用 `vosk-model-small-cn-0.22`，模型来源为 Vosk 官方模型索引，索引记录大小 42M、许可证 Apache 2.0；本地解压后约 65.13 MB。该候选在 Piper 合成普通话短句、较长句、静音和噪声 fixture 上实际运行，CPU 推理成功，未调用外部网络。

当前事实：本地 TTS 候选 `local-piper-zh-huayan` 使用 Piper voice `zh_CN-huayan-medium`，voice 仓库 metadata 为 MIT；本地 voice 文件约 60.28 MB。`piper-tts` Python 包 metadata 为 GPL-3.0-or-later，因此生产采用前需要许可证复核和部署边界确认。该候选实际连续合成固定普通话文本，输出 WAV 到 Git 忽略的 `.runtime/voice-benchmark/audio/`。

当前事实：Windows SAPI 在当前开发服务器安全上下文下不可用，不再作为唯一默认 TTS 方案。

当前事实：云端 OpenAI STT/TTS Provider 仍因缺少凭据未执行，状态保持 `CLOUD_STT_CREDENTIALS_PENDING` / `CLOUD_TTS_CREDENTIALS_PENDING`；这不表示云端不可用，也不构成最终产品儿童数据上云批准。

建议：M4-003 之后的默认阶段性路线为：

```text
Node.js 训练编排后端
-> Provider 接口
-> 独立 Python 语音推理服务
```

建议：STT 阶段性决定为 `LOCAL_PRIMARY_CLOUD_OPTIONAL`，默认本地候选为 `local-vosk-small-cn`；云端 STT 仅在凭据存在、显式启用、测试资料授权时作为可选 Benchmark 和后续对照。

建议：TTS 阶段性决定为 `LOCAL_PRIMARY_CLOUD_OPTIONAL`，默认本地候选为 `local-piper-zh-huayan`；在许可证复核和人工试听前，不把该 voice 宣称为最终产品音色。

待确认：TTS 普通话可懂度、自然度和儿童适宜性需要人工试听，状态为 `HUMAN_REVIEW_PENDING`。

待确认：如后续提供云端凭据并显式启用云端 Benchmark，应重新比较云端 STT/TTS 的延迟、准确率、稳定性、成本和数据边界，再决定是否从 `PROVISIONAL_PROVIDER_DECISION` 升级为 `FINAL_PROVIDER_DECISION`。

## M4-002 比较矩阵

M4-002 至少覆盖以下组合，允许先选少量代表性候选，不要求一次测试所有市场方案：

| 编号 | STT | TTS |
| -- | -- | -- |
| 1 | 本地 STT | 不测 TTS |
| 2 | 云端 STT | 不测 TTS |
| 3 | 不测 STT | 本地 TTS |
| 4 | 不测 STT | 云端 TTS |
| 5 | 本地 STT | 本地 TTS |
| 6 | 本地 STT | 云端 TTS |
| 7 | 云端 STT | 本地 TTS |
| 8 | 云端 STT | 云端 TTS |

云端候选无凭证时，结果标记 `CLOUD_CREDENTIALS_PENDING`；不得让缺少云端 Key 阻塞本地 harness、Provider 接口和本地 Benchmark。

## Benchmark 指标

STT 至少记录：初始化时间、模型加载时间、音频时长、partial 首次返回时间、final 返回时间、real-time factor、识别文本、基础准确性观察、普通话支持、噪声表现、CPU、GPU、内存、是否访问外部网络、失败类型、重试表现。

TTS 至少记录：初始化时间、首包时延、总合成时延、音频时长、音频格式、普通话可懂度、主观自然度记录、CPU、GPU、内存、是否访问外部网络、失败类型、重试表现。

端到端至少记录：采集到 transcript、transcript 到回复文本、回复文本到音频可播放、整体轮次时延、降级路径、网络断开表现。

## 输出要求

M4-002 Benchmark Harness 应输出：

- 结构化 JSON，供后续机器读取。
- Markdown 报告，供负责人比较路线。
- 未执行云端候选的 `CLOUD_CREDENTIALS_PENDING` 记录。
- 每个 Provider 的 `externalNetworkCalled`、`inputPersisted`、`providerId`、`modelId`、`durationMs`、`errorType`。

## 当前禁止

- 默认上传真实儿童语音。
- 未经授权上传真实儿童音频。
- 提交真实 API Key、真实 `.env`、测试音频大文件或敏感响应。
- 把开发阶段云端测试解释为最终产品云端儿童数据已获批。
- 把业务逻辑直接绑定某个供应商 SDK。
- 在 M4-002 中修改正式训练业务逻辑。
