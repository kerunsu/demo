# 语音与大模型管线 V3

本文定义 M4 开发阶段的目标链路和 Provider 契约。当前阶段允许使用授权测试音频/文本横向比较本地与云端 STT/TTS；最终产品是否允许真实儿童音频上传云端仍待项目负责人和隐私流程确认。

## 1. 当前 Demo 能力

- 前端使用浏览器 `SpeechRecognition` / `webkitSpeechRecognition`。
- 识别到 final transcript 后调用 `POST /api/chat/:sessionId/message`。
- 后端 `voiceOrchestrator` 串行调用 Chat provider 和 TTS provider。
- 默认 `rule` Chat provider 和 `none` TTS provider。
- OpenAI Chat/TTS 代码存在但需要环境变量，正式训练业务不得默认启用真实外部调用。

## 2. M4 逻辑边界

即使当前所有服务都运行在同一台开发机，代码仍必须保持以下逻辑边界：

```text
浏览器采集端
  -> 媒体接入接口
  -> STT Provider
  -> 对话编排
  -> TTS Provider
  -> 机器人页面播放端
```

未来迁移到：

```text
机器人浏览器终端
  -> 局域网
  -> 高性能服务器
```

应主要通过配置和部署变化完成，不应重写 Provider 和业务编排。

## 3. 目标链路

```text
音频采集
  -> 媒体传输或本机媒体接入
  -> VAD / 端点检测
  -> STT Provider(local/cloud/mock)
  -> Transcript 规范化
  -> 输入审核和脱敏
  -> Rule/Mock Chat Provider
  -> 输出审核
  -> TTS Provider(local/cloud/mock)
  -> 音频播放
  -> 动画同步
  -> 观测和日志
```

## 4. Provider 接口

| Provider | 输入 | 输出 | 说明 |
| -- | -- | -- | -- |
| `AudioCaptureProvider` | 设备配置、权限 | 音频 chunk、设备事件 | 不做语义判断，不默认持久化原始音频。 |
| `MediaIngressProvider` | 音频 chunk、session/turn metadata | 本机或 LAN 传输结果 | 隔离浏览器采集端与服务器端处理位置。 |
| `VadProvider` | 音频 chunk | speech start/end、静音超时 | 可本地实现，也可由 STT provider 内置能力替代。 |
| `SttProvider` | 音频段、语言、turn metadata | transcript、confidence、timings、provider metadata | 必须支持 local/cloud/mock 可替换。 |
| `ConversationContextProvider` | session、题目、历史 | 脱敏上下文 | 控制上下文长度和隐私。 |
| `LlmProvider` | 安全上下文 | 候选回复 | M4 使用 Rule/Mock Chat，不接正式外部 LLM。 |
| `ChildSafetyProvider` | 输入或候选输出 | allow/block/rewrite/fallback | 主模型前后都调用。 |
| `TtsProvider` | 已审核文本、语言、voice config | audioRef/base64/stream、duration、format、marks、provider metadata | 必须支持 local/cloud/mock 可替换。 |
| `PlaybackSyncProvider` | 音频和 marks | 字幕、动画同步事件 | marks 缺失时用时长兜底。 |

STT/TTS Provider 必须覆盖：

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

## 5. Provider 类型

STT：

- `local`
- `cloud`
- `mock`

TTS：

- `local`
- `cloud`
- `mock`

建议：业务编排只依赖 Provider 契约，不直接依赖具体供应商 SDK。

## 6. 云端候选规则

- 开发阶段允许用开发人员录制的测试语音、合成音频和明确授权的非真实儿童测试音频测试云端 STT。
- 开发阶段允许用测试文本测试云端 TTS。
- 云端 Key 只从环境变量读取。
- `.env.example` 只记录变量名，不记录真实值。
- 云端测试必须可以通过配置关闭。
- 缺少云端 Key 时输出 `CLOUD_CREDENTIALS_PENDING`，不得阻塞本地 Benchmark、Provider 接口和测试框架。
- 日志不得输出 Key、完整敏感文本或长期保存完整音频。

## 7. 流式与非流式方案

| 方案 | 适用 | 风险 |
| -- | -- | -- |
| 非流式 | 当前 Demo、稳定性优先、审核前置简单 | 等待时间更长。 |
| 流式 STT + 非流式 LLM/TTS | 需要实时显示转写，但输出仍需审核 | interim 文本不能进入报告或模型事实。 |
| 端到端流式 | 低延迟对话 | 审核、打断、动画同步更复杂，需后续确认。 |

当前阶段建议先做可观测的非流式或半流式 Benchmark，再决定产品链路。

## 8. Benchmark 指标

STT 至少记录：初始化时间、模型加载时间、音频时长、partial 首次返回时间、final 返回时间、real-time factor、识别文本、基础准确性观察、普通话支持、噪声表现、CPU、GPU、内存、是否访问外部网络、失败类型、重试表现。

TTS 至少记录：初始化时间、首包时延、总合成时延、音频时长、音频格式、普通话可懂度、主观自然度记录、CPU、GPU、内存、是否访问外部网络、失败类型、重试表现。

端到端至少记录：采集到 transcript、transcript 到回复文本、回复文本到音频可播放、整体轮次时延、降级路径、网络断开表现。

## 9. 超时

建议初始预算，最终由 M4-002/M4-012 实测修正：

- VAD 静音端点：0.8-1.5s。
- STT：2-5s。
- 输入审核：300-800ms。
- Rule/Mock Chat：100-1000ms。
- 输出审核：300-800ms。
- TTS：2-6s。
- 全链路儿童可感知等待目标：先记录，不承诺；最终由项目负责人确认。

## 10. 重试

- 对网络错误、429、5xx 做有限重试。
- 每个 provider 最多 1-2 次。
- 使用指数退避和 jitter。
- 安全审核拒绝不重试。
- 同一 turn 重试不能重复写入聊天历史。
- Benchmark 必须记录重试次数和最终失败类型。

## 11. 取消

每次语音交互分配 `turnId`：

- 儿童停止录音时取消采集。
- 切题、退出、会话完成时取消 STT/LLM/TTS。
- Provider 必须暴露取消或超时边界。
- 取消后不得继续播放迟到的 TTS 或动画。

## 12. 幂等

- 客户端发送 `requestId`、`turnId`、`audioSegmentId`。
- 后端对最近请求去重。
- 连续模式 STT 的重复 final transcript 不应触发重复回复。
- TTS 对同一已审核文本可复用结果。

## 13. 降级

| 故障 | 降级 |
| -- | -- |
| 麦克风不可用 | 手动文本输入。 |
| 媒体传输失败 | 停止当前 turn，提示重试或切换文字/点击。 |
| 本地 STT 失败 | 云端 STT 候选或 Mock/文字降级，取决于配置和数据授权。 |
| 云端 STT 凭证缺失 | `CLOUD_CREDENTIALS_PENDING`，继续本地/mock。 |
| 云端 STT 网络失败 | 本地 STT 或文字降级。 |
| TTS 失败 | 显示已审核文本和简化动画。 |
| 云端 TTS 凭证缺失 | `CLOUD_CREDENTIALS_PENDING`，继续本地/mock。 |
| LLM 失败 | 规则 provider。 |
| 输出审核失败或超时 | 固定安全兜底。 |
| 动画同步 marks 缺失 | 使用音频时长切换 speaking/idle。 |

## 14. 可观测性

记录脱敏事件：

- turn 创建、取消、完成、失败。
- provider 名称、provider 类型、modelId、延迟、错误码、降级路径。
- 是否发生外部网络调用。
- 输入是否被 provider 持久化。
- 审核动作、策略版本、PII 类型，不默认保存原文。
- TTS 时长、播放开始和结束。

## 15. 成本控制

- 默认 Mock 或规则 provider。
- 云端 provider 需要显式配置启用。
- LLM 上下文裁剪。
- TTS 结果缓存。
- 限制每 session 语音 turn 数和最大文本长度。
- provider 超时熔断，避免连续失败产生费用。

## 16. 测试 Mock

必须支持：

- STT Mock：固定 transcript、空结果、超时、低置信度、partial、final。
- TTS Mock：返回短静音音频、失败、延迟、格式 metadata。
- Cloud STT/TTS Stub：无 Key 时返回 `CLOUD_CREDENTIALS_PENDING`。
- LLM Mock：成功、超时、429、空回复、不安全输出。
- Safety Mock：通过、拒绝、改写、超时。
- Animation Mock：播放成功、资源缺失、中断。
