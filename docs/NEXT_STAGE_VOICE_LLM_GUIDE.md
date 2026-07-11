# 下一阶段：真实语音交流接入指南

本文档汇总“语音转文字 + 大模型对话 + 语音合成”的接入建议与落地步骤，便于下一阶段开发直接执行。

## 1. 当前代码基础（已具备）

项目已经完成可插拔框架，不需要推倒重来：

- **Chat Provider 抽象**（`rule` / `openai`）
- **TTS Provider 抽象**（`none` / `openai`）
- **统一编排器**：`voiceOrchestrator`
- **运行时配置**：`.env` + 配置校验
- **状态检查接口**：`/api/voice/providers`、`/api/health`
- **前端音频回放**：后端返回 `audioBase64` + `audioMimeType` 时自动播放

## 2. 关键代码位置

- 运行配置：
  - `backend/src/config/runtime.ts`
  - `backend/.env.example`
- 语音/模型编排：
  - `backend/src/services/voice/voiceOrchestrator.ts`
  - `backend/src/services/voice/types.ts`
- Chat Provider：
  - `backend/src/services/voice/providers/ruleChatProvider.ts`
  - `backend/src/services/voice/providers/openAiChatProvider.ts`
- TTS Provider：
  - `backend/src/services/voice/providers/noopTtsProvider.ts`
  - `backend/src/services/voice/providers/openAiTtsProvider.ts`
- 业务接入点：
  - `backend/src/services/sessionService.ts`（`sendChatMessage`）
  - `backend/src/index.ts`（chat 路由、provider 状态路由）
- 前端接收与播放：
  - `frontend/src/types/index.ts`
  - `frontend/src/App.tsx`

## 3. 推荐接入顺序（最稳）

### Step 1：先接真实 LLM（不接 TTS）

`.env` 配置：

```env
AI_CHAT_PROVIDER=openai
AI_TTS_PROVIDER=none
OPENAI_API_KEY=你的key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_CHAT_MODEL=gpt-4o-mini
```

目标：先保证“识别文本 -> 大模型回复文本”稳定。

### Step 2：再开启 TTS

`.env` 增补：

```env
AI_TTS_PROVIDER=openai
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TTS_VOICE=alloy
```

目标：实现“回复文本 -> 播放语音”。

### Step 3：最后做稳定性增强

- 请求超时
- 失败重试
- 熔断与降级（OpenAI失败时回退 rule）
- 结构化日志与链路追踪

## 4. 环境配置说明

复制：

- `backend/.env.example` -> `backend/.env`

常用参数：

- `AI_CHAT_PROVIDER`：`rule | openai`
- `AI_TTS_PROVIDER`：`none | openai`
- `OPENAI_API_KEY`：OpenAI key
- `OPENAI_BASE_URL`：默认 `https://api.openai.com/v1`
- `OPENAI_CHAT_MODEL`：如 `gpt-4o-mini`
- `OPENAI_TTS_MODEL`：如 `gpt-4o-mini-tts`
- `OPENAI_TTS_VOICE`：如 `alloy`

## 5. 联调与验收检查

### 5.1 基础启动

```bash
npm run dev
```

### 5.2 检查 Provider 状态

- `GET /api/health`
- `GET /api/voice/providers`

观察：

- `chatProvider` 是否为目标值
- `ttsProvider` 是否为目标值
- `configIssues` 是否为空

### 5.3 功能闭环

1. 前端语音输入（浏览器 STT）
2. 后端返回 LLM 文本
3. （可选）返回 TTS 音频并自动播放
4. 报告页对话摘要正常统计

## 6. 推荐增强项（下一阶段优先）

## P1（高优先）

- **超时与重试**
  - Chat/TTS 请求都应设置超时
  - 网络抖动时采用有限重试（例如 2 次）
- **失败降级**
  - OpenAI 失败时自动回退 `rule` 回复
- **结构化日志**
  - 记录 provider、耗时、状态码、失败原因

## P2（中优先）

- **音频传输优化**
  - 从 `base64` 改为文件 URL（减少响应体）
- **安全与合规**
  - 儿童场景回复安全过滤
- **上下文策略**
  - 会话历史裁剪 + 课程状态拼接

## P3（后续）

- 后端统一 STT（替代浏览器 Web Speech，提升跨端稳定性）
- 支持更多模型提供方（新增 provider 即可）
- 音色/语速个性化策略

## 7. 常见问题排查

1. **有文本无语音**
   - `AI_TTS_PROVIDER` 是否为 `openai`
   - `OPENAI_API_KEY` 是否有效
   - TTS 模型与 voice 是否可用

2. **provider 没切换成功**
   - 检查 `backend/.env` 是否生效
   - 重启后端进程
   - 看 `/api/voice/providers` 的 `configIssues`

3. **持续模式偶发中断**
   - 浏览器 Web Speech API 限制导致
   - 后续建议接入后端 STT 服务

## 8. 一句话结论

当前项目已具备真实语音交流的框架基础。下一阶段只需按本文配置 provider 与 key，即可平滑进入“STT -> LLM -> TTS”的完整链路，并可逐步增强稳定性与体验。
