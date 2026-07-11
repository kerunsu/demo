# 波次 3：语音对话黑盒对接 — 我方开发规划

> 更新日期：2026-06-15  
> 状态：**已实施**（波次 3 黑盒对接）  
> 关联：`docs/四个波次开发计划.md` § 波次 3、`docs/FOUR_STAGE_PROGRESS_AND_NEXT_PLAN.md`

---

## 1. 对你方最新答复的评估：规划影响是否很大？

**结论：方向性调整较大，但实现范围更收敛、更清晰。**

| 原规划倾向 | 你方最新要求 | 影响 |
|------------|--------------|------|
| 扩展 `tools/voice-service`，STT/LLM/TTS 走 Python 一体服务 | 对方可部署**任意独立 HTTP 服务**，我方不限制 | **解耦**：我方不再绑定 Python voice-service 作为对话主路径 |
| 建议 `VOICE_STT_SOURCE=server`，交接以服务端 STT 为准 | **我方 STT 保持浏览器**，仅服务表达性语言分析 | **双轨并行**：评估管线与对话管线彻底分开 |
| 页面上下文 `text` 默认，`image` 可选（我方 env 控制采集） | **文本与截图我方始终采集并传递**；**用哪种由对方配置决定** | **采集与消费分离**：我方 payload 固定齐全，对方 config 选读 |
| 对方改 `partner_handlers.py` + 可能接 Node `voiceServiceChatProvider` | **双方黑盒**：我方只「出音频+页面描述、入回复文本+语音」 | **契约单一化**：一个 HTTP turn 接口替代多条内部 Provider 链 |

**不变的部分：**

- 原始音频落盘、`browserAudioCapture` 声学标量、报告表达性语言评分 —— 仍是我方职责（波次 2 已落地）。
- 儿童安全：我方对**对方返回的文本**仍可做输出审查（对方无感知）；默认 demo 仍可 `VOICE_DIALOG_PROVIDER=rule` 降级。
- 默认不启用真实外部对话，不改变现有 `AI_CHAT_PROVIDER=rule` 行为，直至显式切换。

---

## 2. 黑盒原则（双方共识）

```text
┌─────────────────────────────────────────────────────────────────┐
│ 我方（儿童端 + 后端代理）                                          │
│  输出给黑盒：merged 音频 + pageContext.text + pageContext.screenshot │
│  输入自黑盒：replyText + replyAudio（+ 可选 metadata）              │
│  不关心：对方 STT/LLM/TTS 实现、模型、是否多服务                      │
└───────────────────────────┬─────────────────────────────────────┘
                            │  HTTP（契约固定）
┌───────────────────────────▼─────────────────────────────────────┐
│ 对方维护区 tools/voice-partner/                                    │
│  只改 1–3 个配置/实现文件                                           │
│  不关心：我方课程 UI、监控、报告、浏览器 STT 细节                      │
└─────────────────────────────────────────────────────────────────┘
```

**我方并行、且不进入黑盒的内部管线（对方不可见）：**

```text
浏览器 STT（Web Speech）──► 转写文本 ──► languageFeatureService / 报告表达性语言（文本 50%）
浏览器 Web Audio        ──► 声学标量 ──► audioFeatureService / 报告表达性语言（声学 50%）
mediaIngress            ──► 原始音频持久化（RAW_MEDIA，可选）
```

---

## 3. 对方维护区（我方只搭架子，不替对方实现）

目录：**`tools/voice-partner/`**（与 `tools/voice-service/` 并列；后者保留为历史 STT/TTS 参考，**不是**对话黑盒的必选依赖）。

| 文件 | 谁维护 | 作用 |
|------|--------|------|
| `README.md` | 我方写 | 对方 5 分钟上手 |
| `CONTRACT.md` | 我方写 | HTTP 请求/响应、错误码、示例 curl |
| `partner.env.example` | 我方写 | 对方复制为 `partner.env` |
| `partner.config.yaml` | 对方改（可选） | 与 `.env` 二选一或并存 |
| `reference_server.py` | 我方写 mock | 零模型联调；对方可删 |
| 对方真实服务 | 对方 | 任意语言/框架/多进程，只要满足 CONTRACT |

**对方典型只改：**

1. `partner.env` — `PARTNER_SERVICE_URL`、鉴权、`CONTEXT_INPUT_MODE`、`STT_MODE` 等  
2. （若用我方 reference 壳）`partner_impl.py` — 三个钩子或一次 `process_turn`  
3. （可选）`prompts/system.txt`

---

## 4. HTTP 契约（黑盒唯一接口）

### 4.1 我方调用对方

`POST {VOICE_PARTNER_BASE_URL}/v1/voice-turn`

**Request（我方始终尽量填满，对方配置决定使用哪些字段）：**

```json
{
  "schemaVersion": "voice-partner-turn-v1",
  "sessionId": "sess_xxx",
  "turnId": "turn_xxx",
  "correlationId": "voice:sess_xxx:turn_xxx",
  "capturedAt": "2026-06-15T12:00:00.000Z",
  "audio": {
    "base64": "...",
    "mimeType": "audio/webm",
    "durationMs": 3200
  },
  "pageContext": {
    "text": {
      "schemaVersion": "voice-page-context-v1",
      "courseType": "matching",
      "questionIndex": 1,
      "totalQuestions": 5,
      "prompt": "请找出相同的水果",
      "target": "苹果",
      "options": [
        { "id": "a", "label": "苹果" },
        { "id": "b", "label": "香蕉" }
      ],
      "interaction": {
        "selectedOptionIds": [],
        "wrongAttempts": 0,
        "elapsedMs": 12000
      },
      "narrative": "当前是配对题第 2/5 题。题目：请找出相同的水果。目标：苹果。选项：苹果、香蕉。儿童尚未选择。"
    },
    "screenshot": {
      "mimeType": "image/jpeg",
      "base64": "...",
      "width": 800,
      "height": 600
    }
  },
  "history": [
    { "role": "user", "text": "..." },
    { "role": "assistant", "text": "..." }
  ],
  "locale": "zh-CN"
}
```

**对方配置示例（`partner.env`，我方文档写明，对方自选）：**

```env
# 使用页面上下文的哪些部分（我方始终上传全部）
CONTEXT_INPUT_MODE=both          # text | image | both

# 对方内部 STT 策略（与我方浏览器 STT 无关）
STT_MODE=audio                     # audio | text_only_fallback | none

# 对方 LLM / TTS 可指向任意 URL（我方不限制）
LLM_HTTP_URL=https://internal/v1/chat
TTS_HTTP_URL=https://internal/v1/tts
```

**Response（我方只消费这些）：**

```json
{
  "ok": true,
  "replyText": "好的，我们看看苹果是哪个选项。",
  "replyAudio": {
    "base64": "...",
    "mimeType": "audio/mpeg"
  },
  "metadata": {
    "provider": "partner-acme",
    "latencyMs": 840,
    "sttModeUsed": "audio"
  }
}
```

失败时：`ok: false` + `error.code` / `error.message`；我方 UI 降级文案，**不**向儿童暴露对方技术细节。

### 4.2 我方为何用后端代理，不让孩子端直连对方

- 对方 URL、API Key 不暴露给浏览器  
- 统一超时、审计、输出安全审查  
- CORS / 隐私合规由我方网关控制  

儿童端只调：`POST /api/voice-partner/:sessionId/turn`（我方新增）。

---

## 5. 我方开发任务清单

### 阶段 A：契约与文档（0.5 天）

| # | 任务 | 产出 |
|---|------|------|
| A1 | 定义共享类型 | `shared/src/voicePartnerContract.ts` |
| A2 | 对方维护区脚手架 | `tools/voice-partner/README.md`、`CONTRACT.md`、`partner.env.example` |
| A3 | Mock 参考服务 | `tools/voice-partner/reference_server.py`（固定 echo 回复，便于 CI） |
| A4 | 交接总览（给对方） | `tools/voice-partner/HANDOFF.md`（从 CONTRACT 链过去，避免对方读前端） |

### 阶段 B：页面上下文采集（1 天）

| # | 任务 | 产出 | 说明 |
|---|------|------|------|
| B1 | 结构化文本 | `frontend/src/features/voice/buildPageContext.ts` | 纯函数：入参 `CourseQuestion` + 交互 state，出 `pageContext.text` + `narrative` |
| B2 | 截图 | 同上模块 `captureTrainingScreenshot()` | **始终尝试**生成 `pageContext.screenshot`；失败时字段为 `null` 并带 `screenshotUnavailableReason`，不阻断 turn |
| B3 | 采集根节点 | 训练页根元素 `data-voice-context-root` | 仅一处 DOM 约定，写在 CONTRACT 供截图参考 |
| B4 | 与录音生命周期绑定 | 改 `useVoiceCapture` | 增加 `getPageContext: () => Promise<PageContextPayload>` 回调；在 `finalizeActiveMediaTurn` 拿到 merged 音频元数据后调用 |

**原则：** `text` 与 `screenshot` **每次都采集、每次都进 payload**；不做「我方 env 关掉截图」——控制权在对方 `CONTEXT_INPUT_MODE`。

### 阶段 C：黑盒代理 API（1 天）

| # | 任务 | 产出 |
|---|------|------|
| C1 | 运行时配置 | `backend/src/config/runtime.ts` 增加 `voiceDialogProvider: rule \| partner`、`voicePartnerBaseUrl`、`voicePartnerApiKey`、`voicePartnerTimeoutMs` |
| C2 | 代理服务 | `backend/src/services/voicePartnerProxyService.ts`：组装 turn 请求、读 merged 音频（复用 `mediaIngressService`）、转发 HTTP、解析响应 |
| C3 | 路由 | `backend/src/routes/voicePartnerRoutes.ts`：`POST /api/voice-partner/:sessionId/turn` |
| C4 | 注册路由 | `backend/src/index.ts` |
| C5 | 健康检查 | `GET /api/voice-partner/health` → 探测对方 `/health`（可选，配置 `VOICE_PARTNER_BASE_URL` 时启用） |

### 阶段 D：前端对话路径切换（0.5–1 天）

| # | 任务 | 说明 |
|---|------|------|
| D1 | `partnerVoiceClient.ts` | 调我方 `POST /api/voice-partner/:sessionId/turn` |
| D2 | 拆分 `handleVoiceFinal` | **浏览器 STT 结果**：仅更新儿童字幕 + 触发语言观测（已有 `sendChatMessage` 内 persist 逻辑需抽出为 `persistChildTranscriptObservations`，**不**再默认走 rule/openai LLM） |
| D3 | 录音结束主路径 | `finalizeActiveMediaTurn` 完成后：若有 training session 且 `VOICE_DIALOG_PROVIDER=partner`，发起 partner turn；用返回的 `replyText` / `replyAudio` 更新 `voiceLogs` 与 `playChatReplyAudio` |
| D4 | 降级 | `partner` 失败时：可选回退 `AI_CHAT_PROVIDER=rule`（env `VOICE_PARTNER_FALLBACK=rule`），默认仅提示「对话暂时不可用」 |
| D5 | `/server` 监控 | snapshot 增加 `voice.dialogProvider`、`voice.partnerLastLatencyMs`、`voice.partnerLastError`（不含音频/base64） |

### 阶段 E：安全与合规（0.5 天）

| # | 任务 | 说明 |
|---|------|------|
| E1 | 输出审查 | 对方 `replyText` 经 `reviewAssistantResult` 或等价薄封装后再展示/播放 |
| E2 | 日志 | 不记录 `audio.base64`、`screenshot.base64`、完整儿童对话；仅 turnId、latency、error.code |
| E3 | 默认配置 | `backend/.env.example`：`VOICE_DIALOG_PROVIDER=rule`；文档说明启用 partner 需负责人批准 |

### 阶段 F：测试与验收（0.5 天）

| # | 内容 |
|---|------|
| F1 | 单测：`buildPageContext` 文本结构、截图失败降级 |
| F2 | 单测：`voicePartnerProxyService` mock HTTP |
| F3 | 集成：`reference_server.py` + `VOICE_DIALOG_PROVIDER=partner` E2E 片段 |
| F4 | 回归：`VOICE_DIALOG_PROVIDER=rule` 时行为与现网一致 |
| F5 | 基线：`npm run build && npm test && git diff --check` |

---

## 6. 录音结束时序（目标态）

```text
儿童松开麦克风 / 超时结束
        │
        ├─► [我方] 音频 chunk 收尾 → finishMediaStream
        ├─► [我方] sendBrowserAudioFeatures（表达性语言·声学）
        ├─► [我方] buildPageContext() → text + screenshot
        │
        ├─► [我方·并行] 浏览器 STT onresult(final)
        │         └─► persistChildTranscriptObservations（表达性语言·文本）
        │             （不调用 rule/openai chat）
        │
        └─► [我方] POST /api/voice-partner/.../turn
                  └─► 后端转发 → 对方黑盒 HTTP
                        └─► replyText + replyAudio
                              └─► 安全审查 → UI 字幕 + 播放 + /robot TTS 若适用
```

**要点：**

- 我方**传给对方的只有**：合并音频 + `pageContext.text` + `pageContext.screenshot`（+ 可选 history/locale）。  
- 我方**不**向对方传递浏览器 STT 转写（除非日后契约扩展为可选 hint；**当前版本不传**，避免对方依赖我方 STT）。  
- 对方 STT 用音频自建，或在 `STT_MODE=none` 时仅用页面文字 —— **对方 config 自定**，与我方无关。

---

## 7. 环境变量（我方）

| 变量 | 默认 | 说明 |
|------|------|------|
| `VOICE_DIALOG_PROVIDER` | `rule` | `rule`：现有 `sendChatMessage`；`partner`：黑盒 HTTP |
| `VOICE_PARTNER_BASE_URL` | 空 | 对方服务根 URL，如 `http://127.0.0.1:9876` |
| `VOICE_PARTNER_API_KEY` | 空 | 我方后端 → 对方鉴权（Header 名在 CONTRACT 固定） |
| `VOICE_PARTNER_TIMEOUT_MS` | `30000` | 单 turn 超时 |
| `VOICE_PARTNER_FALLBACK` | `none` | `none` \| `rule`：对方失败是否回退规则回复 |

**不再新增（相对旧规划）：**

- ~~`VOICE_STT_SOURCE=server`~~  
- ~~`VOICE_PAGE_CONTEXT_MODE`~~（我方始终采集 text+screenshot）  
- ~~`AI_CHAT_PROVIDER=voice-service`~~（对话与旧 ChatProvider 解耦；报告叙事 `REPORT_NARRATIVE_PROVIDER` 仍独立）

现有 `VOICE_STT_PROVIDER` / `tools/voice-service`：保留给媒体转写、基准测试；**不**作为波次 3 对方必选路径。

---

## 8. 文件改动一览（我方）

| 层级 | 新增 | 修改 |
|------|------|------|
| shared | `voicePartnerContract.ts` | — |
| frontend | `buildPageContext.ts`、`partnerVoiceClient.ts` | `useVoiceCapture.ts`、`App.tsx`、训练页根 `data-voice-context-root` |
| backend | `voicePartnerProxyService.ts`、`voicePartnerRoutes.ts` | `runtime.ts`、`index.ts`、`chatService.ts`（抽出观测）、`monitorSnapshotService.ts` |
| tools | `voice-partner/*` | — |
| docs | 本文档 | `四个波次开发计划.md`、`FOUR_STAGE_PROGRESS_AND_NEXT_PLAN.md`（状态勾选） |
| tests | `voicePartner*.test.mjs`、`buildPageContext.test.ts` | 必要时 e2e 补 partner mock |

**刻意不改（对方零接触）：** `reportScoringService`、`emotionAggregationService`、`browserAudioCapture` 特征算法、`llmSafetyGateway` 核心规则（仅多一条 partner 输出入口）。

---

## 9. 工期与依赖

| 阶段 | 工期 | 依赖 |
|------|------|------|
| A 契约 | 0.5d | 无 |
| B 页面上下文 | 1d | A1 |
| C 后端代理 | 1d | A1 |
| D 前端切换 | 0.5–1d | B、C |
| E 安全 | 0.5d | C、D |
| F 测试 | 0.5d | D |

**合计：约 3.5–4 个工作日（我方）**。对方可在 A1/A2 完成后并行阅读 CONTRACT、搭建独立 HTTP 服务。

---

## 10. 验收标准（我方）

1. `VOICE_DIALOG_PROVIDER=rule`：全量测试通过，与当前 demo 行为一致。  
2. `VOICE_DIALOG_PROVIDER=partner` + `reference_server`：一轮训练录音后，儿童端展示对方回复文本并播放返回音频。  
3. 同一 turn：`/server` 可见声学条带；报告表达性语言仍受浏览器 STT + 声学特征影响（**不依赖**对方返回）。  
4. payload 中同时存在 `pageContext.text` 与 `pageContext.screenshot`（截图失败时 screenshot 为 null 且有 reason）。  
5. 对方仅修改 `tools/voice-partner/partner.env`（及可选实现文件）即可完成联调，**无需**阅读 `App.tsx` / `useCourseFlow`。  
6. 日志与 snapshot **无** base64 音频/图片泄露。

---

## 11. 风险与待确认

| 项 | 说明 | 标记 |
|----|------|------|
| 浏览器 STT 与黑盒 turn 时序 | STT final 可能早于或晚于 merged 音频；表达性语言观测与 partner turn **解耦**，互不强依赖 | `当前事实`：可接受 |
| 截图体积 | 每次 turn 上传 JPEG；由我方后端转发，需限制 `maxScreenshotBytes`（建议 500KB） | `建议` |
| 对方返回音频格式 | CONTRACT 约定优先 `audio/mpeg` / `audio/wav`；前端 `audioPlayback` 需兼容 | 实施时验证 |
| 是否向对方传 `history` | **已确认：传** 最近 N 轮 | `当前事实` |
| partner 失败是否 fallback rule | **已确认：none** | `当前事实` |

---

## 12. 下一步执行顺序

1. 合并 §6 工作区 manifest 修复（若仍未提交）— 波次 0 收尾。  
2. 实施 **阶段 A**（契约 + `tools/voice-partner` 脚手架）— 可立即发给对方预览。  
3. **阶段 B + C** 并行。  
4. **阶段 D** 切换对话路径。  
5. 联调 → 更新 `FOUR_STAGE_PROGRESS_AND_NEXT_PLAN.md` 波次 3 为 ✅。

---

## 13. 事实标签

- **当前事实**：波次 0/1/2/情绪 Provider 已落地；对话默认 `AI_CHAT_PROVIDER=rule`；浏览器 STT + 声学特征已接入报告。  
- **建议**：本文档全部实施项。  
- **待确认**：§11 中 history 传递、partner fallback 策略。
