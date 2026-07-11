# 环境变量说明

> 更新日期：2026-06-15  
> 模板文件：`backend/.env.example`、`deploy/production.env.example`、`deploy/frontend.env.example`、`tools/voice-partner/partner.env.example`

**重要：** 后端运行时读取 **`backend/.env`**（从 `backend/.env.example` 复制）。仅修改 example 不会生效。

---

## 1. 后端 `backend/.env`

### 1.1 服务与网络

| 变量 | 默认 | 说明 |
|------|------|------|
| `NODE_ENV` | `development` | 生产部署设为 `production` |
| `BACKEND_HOST` | `0.0.0.0` | 监听地址 |
| `BACKEND_PORT` | `3001` | HTTP/WebSocket 端口 |
| `PUBLIC_BACKEND_ORIGIN` | — | 对外可访问的后端 Origin（LAN/生产必填） |
| `CORS_ORIGIN` | — | 允许的前端 Origin（多值逗号分隔） |

### 1.2 对话与 TTS（内置路径）

| 变量 | 可选值 | 说明 |
|------|--------|------|
| `AI_CHAT_PROVIDER` | `rule` \| `openai` | 训练页**文字**聊天（非语音黑盒主路径） |
| `AI_TTS_PROVIDER` | `none` \| `openai` | 内置 TTS |
| `OPENAI_API_KEY` | — | `openai` 时必填 |
| `OPENAI_BASE_URL` | OpenAI 默认 | API 基址 |
| `OPENAI_CHAT_MODEL` | `gpt-4o-mini` | 聊天模型 |
| `OPENAI_TTS_MODEL` / `OPENAI_TTS_VOICE` | — | TTS 模型与音色 |

### 1.3 语音对话黑盒（波次 3）

| 变量 | 可选值 | 说明 |
|------|--------|------|
| `VOICE_DIALOG_PROVIDER` | `rule` \| `partner` | `partner` 时走外部 HTTP 黑盒 |
| `VOICE_PARTNER_BASE_URL` | — | 对方服务根 URL，如 `http://127.0.0.1:9876` |
| `VOICE_PARTNER_API_KEY` | — | 与本仓代理请求头 `x-voice-partner-key` 一致 |
| `VOICE_PARTNER_TIMEOUT_MS` | `30000` | 单轮超时 |
| `VOICE_PARTNER_FALLBACK` | `none` | 失败是否回退规则；**当前约定为 `none`** |

契约：`shared/src/voicePartnerContract.ts`、`tools/voice-partner/CONTRACT.md`。

### 1.4 本地语音服务（STT/TTS/注意力）

| 变量 | 可选值 | 说明 |
|------|--------|------|
| `VOICE_STT_PROVIDER` | `mock` \| `local` \| … | 后端 STT 路由 |
| `VOICE_TTS_PROVIDER` | `mock` \| `local` \| … | 后端 TTS 路由 |
| `VOICE_PYTHON_SERVICE_URL` | `http://127.0.0.1:8765` | `tools/voice-service` 地址 |
| `ATTENTION_PROVIDER` | `mock` \| `local` | 注意力特征来源 |

Python 进程侧变量见 `tools/voice-service/README.md`（如 `VOICE_SERVICE_STT_PROVIDER=local-vosk`）。

### 1.5 报告叙事 LLM

| 变量 | 可选值 | 说明 |
|------|--------|------|
| `REPORT_NARRATIVE_PROVIDER` | `rule` \| `mock` \| `openai` \| `deepseek` | 报告 V2 解释性文字 |
| `OPENAI_REPORT_MODEL` | — | OpenAI 报告模型 |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_REPORT_MODEL` | — | DeepSeek 路径 |

### 1.6 持久化与原始媒体

| 变量 | 默认 | 说明 |
|------|------|------|
| `DEMO_STORAGE_PROVIDER` | `sqlite` | 会话/报告存储 |
| `DEMO_SQLITE_DB_PATH` | `.runtime/demo.sqlite3` | SQLite 路径 |
| `RAW_MEDIA_PERSISTENCE` | `disabled` | 设为 `enabled` 才落盘原始音视频 |
| `RAW_MEDIA_ROOT` | `.runtime/media` | 媒体根目录 |
| `RAW_MEDIA_RETENTION_DAYS` | `7` | 保留天数 |
| `RAW_MEDIA_REQUIRE_CONSENT` | `true` | 是否要求同意标记 |
| `RAW_MEDIA_ENCRYPTION` | `optional` | 加密策略占位 |

### 1.7 运维（生产）

| 变量 | 说明 |
|------|------|
| `DEMO_LOG_DIR` | 日志目录 |
| `DEMO_BACKUP_DIR` | 备份目录 |
| `DEMO_RETENTION_DAYS` | 数据保留天数 |

完整生产模板：`deploy/production.env.example`。

---

## 2. 前端构建时变量

文件：`deploy/frontend.env.example` → 复制为 `frontend/.env.production` 或在构建主机导出。

| 变量 | 说明 |
|------|------|
| `VITE_API_BASE_URL` | 后端 REST 基址，如 `http://192.168.1.10:3001/api` |
| `VITE_WS_URL` | WebSocket 地址，如 `ws://192.168.1.10:3001/ws` |

开发模式通常无需配置，Vite 代理至本机 3001。

---

## 3. 语音黑盒对方 `tools/voice-partner/partner.env`

从 `partner.env.example` 复制。与对方实现相关，本仓主工程**不读取**此文件。

| 变量 | 说明 |
|------|------|
| `PARTNER_API_KEY` | 与 `VOICE_PARTNER_API_KEY` 一致 |
| `CONTEXT_INPUT_MODE` | `text_only` \| `screenshot_only` \| `text_and_screenshot` |
| 内部 STT/LLM/TTS 地址 | 由对方自行配置 |

详见 `tools/voice-partner/一页交接说明.md`。

---

## 4. 按场景的配置清单

### 场景 A：新人本地 Demo（零外部密钥）

1. `cp backend/.env.example backend/.env`
2. 保持 `VOICE_DIALOG_PROVIDER=rule`、`REPORT_NARRATIVE_PROVIDER=mock`
3. `npm run dev`

### 场景 B：联调语音黑盒对方

1. 对方启动 `tools/voice-partner/reference_server.py`（或自建服务）
2. 本仓 `backend/.env` 设置 `VOICE_DIALOG_PROVIDER=partner` 与 `VOICE_PARTNER_*`
3. 重启 backend，`GET /api/voice-partner/health` 应返回可达

### 场景 C：局域网双机（儿童屏 + 机器人屏）

1. 按 `deploy/production.env.example` 配置后端 `PUBLIC_BACKEND_ORIGIN`、`CORS_ORIGIN`
2. 按 `deploy/frontend.env.example` 构建前端并静态托管
3. 参阅 `docs/DEPLOYMENT_OPERATIONS_M7.md`

### 场景 D：启用原始音视频落盘（需隐私评审）

1. `RAW_MEDIA_PERSISTENCE=enabled`
2. 确认 `RAW_MEDIA_REQUIRE_CONSENT` 与现场同意流程
3. 定期清理 `.runtime/media` 或配置 `RAW_MEDIA_RETENTION_DAYS`

---

## 5. 勿提交的文件

- `backend/.env`（含密钥）
- `tools/voice-partner/partner.env`
- `.runtime/` 下所有运行时数据
- 任何含真实 API Key 的本地配置
