# 真实语音交流接入说明（下一阶段）

本文件说明当前代码已具备的“模型与语音可插拔框架”以及如何接入真实服务。

## 1. 当前已实现的框架能力

## 1.1 Provider 抽象（后端）

已增加可替换接口层：

- 聊天模型接口：`ChatProvider`
- 语音合成接口：`TtsProvider`
- 统一编排器：`backend/src/services/voice/voiceOrchestrator.ts`

默认行为：

- `AI_CHAT_PROVIDER=rule`：走规则回复（现有可用）
- `AI_TTS_PROVIDER=none`：不返回音频

可切换行为：

- `AI_CHAT_PROVIDER=openai`：走 OpenAI Chat Completions
- `AI_TTS_PROVIDER=openai`：走 OpenAI TTS（返回 base64 音频）

## 1.2 关键文件

- 配置读取：`backend/src/config/runtime.ts`
- 聊天 Provider：
  - `backend/src/services/voice/providers/ruleChatProvider.ts`
  - `backend/src/services/voice/providers/openAiChatProvider.ts`
- TTS Provider：
  - `backend/src/services/voice/providers/noopTtsProvider.ts`
  - `backend/src/services/voice/providers/openAiTtsProvider.ts`
- 编排器：`backend/src/services/voice/voiceOrchestrator.ts`
- 对话入口（会话层）：`backend/src/services/sessionService.ts`
- API 路由：`backend/src/index.ts`

## 1.3 前端兼容

前端语音链路已支持后端返回音频字段：

- `audioBase64`
- `audioMimeType`

如果后端返回音频，前端会自动播放。

## 2. 如何切到真实模型（OpenAI 示例）

## 2.1 配置环境变量

1. 复制 `backend/.env.example` 为 `backend/.env`
2. 填入：

```env
AI_CHAT_PROVIDER=openai
AI_TTS_PROVIDER=openai
OPENAI_API_KEY=你的key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_CHAT_MODEL=gpt-4o-mini
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TTS_VOICE=alloy
```

如果你只想先接 LLM，不接 TTS：

```env
AI_CHAT_PROVIDER=openai
AI_TTS_PROVIDER=none
```

## 2.2 启动并检查

启动：

```bash
npm run dev
```

查看 provider 状态：

- `GET /api/health`
- `GET /api/voice/providers`

如果配置有问题，上述接口会在 `configIssues` 里提示。

## 3. 当前语音链路（阶段拆分）

目前链路是：

1. 前端 Web Speech API 做语音转文本（浏览器侧 STT）
2. 文本发给 `POST /api/chat/:sessionId/message`
3. 后端走 Chat Provider 生成回复
4. 若启用 TTS Provider，后端附带返回音频 base64
5. 前端自动播放音频

这已经满足“真实语音交流”的主要链路（STT -> LLM -> TTS）。

## 4. 如果后续更换其他模型平台（非 OpenAI）

只需要新增 Provider，不改业务流程：

1. 新建聊天 provider，例如 `backend/src/services/voice/providers/xxxChatProvider.ts`
2. 实现 `ChatProvider` 接口
3. 在 `voiceOrchestrator.ts` 中根据环境变量挂载
4. 新增对应 `.env` 配置项

TTS 也是同样方式：

1. 新建 `xxxTtsProvider.ts`
2. 实现 `TtsProvider` 接口
3. 在 orchestrator 中挂载

## 5. 代码改造建议（下一阶段）

## P1（建议立即做）

- 给 `POST /api/chat/:sessionId/message` 加超时与重试
- 给 Provider 调用加结构化日志（request id、latency、失败原因）
- 前端加入音频播放失败兜底提示（比如“语音播放失败，已显示文字”）

## P2

- 把 base64 音频改为对象存储 URL（减小响应体）
- 增加“儿童安全回复”内容过滤
- 会话上下文分层（短期上下文 + 课程状态上下文）

## P3

- 独立 STT 后端服务（替换浏览器 STT，统一跨端）
- 情绪识别/语速分析（可选）

## 6. 常见问题

1. `OPENAI_API_KEY 未配置`

- 检查 `backend/.env`
- 检查是否在后端目录启动

2. 有文本回复但无语音

- 检查 `AI_TTS_PROVIDER` 是否为 `openai`
- 检查 TTS 模型名与 voice 是否可用

3. 持续模式偶发中断

- 浏览器端语音识别限制导致，属于 Web Speech API 特性
- 可通过后端 STT 服务替代以提升稳定性
