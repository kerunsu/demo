# 项目上下文（交接版）

> 更新日期：2026-06-15  
> 本文描述**当前事实**与维护边界。历史审查快照见 `archive/docs/history/PROJECT_CONTEXT_AUDIT_2026-06-06.md`（大量内容已过时，勿作运行依据）。

**跑起来：** [`docs/ONBOARDING.md`](docs/ONBOARDING.md)  
**装依赖：** [`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md)  
**配环境：** [`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md)

---

## 1. 项目是什么

儿童教育互动训练 **本地 Web Demo**：一台或多台设备上同时运行儿童训练界面、机器人表情屏与监控台；后端为会话事实源，通过 HTTP + WebSocket 同步状态、动画与监控快照。

---

## 2. 当前已实现（当前事实）

| 能力 | 说明 |
|------|------|
| 三屏 SPA | `/child`、`/robot`、`/server` |
| 课程 | `matching`（配对）、`ordering`（排序），素材来自 `matching/`、`paixu/` |
| 会话状态机 | `shared/src/stateMachine.ts`，后端驱动 |
| 领域事件 | WebSocket 广播，契约见 `docs/DOMAIN_EVENTS.md` |
| 持久化 | 默认 SQLite（`.runtime/demo.sqlite3`） |
| 行为观测 | 注意力、表达性语言特征、答题统计等 |
| 报告 V2 | 结构化评分 + 叙事层（`REPORT_NARRATIVE_PROVIDER`） |
| 语音对话 | `rule` 内置 **或** `partner` 黑盒（`tools/voice-partner/`） |
| 原始媒体 | 默认不落盘；`RAW_MEDIA_PERSISTENCE=enabled` 可开启 |
| 自动化测试 | 根目录 `npm test` |

未完成或需现场验收的项见 `docs/FOUR_STAGE_PROGRESS_AND_NEXT_PLAN.md`（如 LAN 双机、真机表情屏、Python 语音服务健康探活等）。

---

## 3. 角色与黑盒边界

| 维护方 | 范围 |
|--------|------|
| **本仓** | 页面上下文采集、原始音频上传、浏览器 STT（仅表达性语言观测）、后端代理、三屏 UI、报告与监控 |
| **语音对方** | `tools/voice-partner/`：接收音频 + pageContext，返回 `replyText` + 可选 `replyAudio` |
| **可选** | `tools/voice-service/`：本机 Vosk/Piper STT/TTS |

`VOICE_DIALOG_PROVIDER=partner` 时，对方失败 **不回退** 规则（`VOICE_PARTNER_FALLBACK=none`）。浏览器 STT 结果 **不** 传给对方。

---

## 4. 热点文件（改动前请协调）

| 文件 | 职责 |
|------|------|
| `frontend/src/App.tsx` | 儿童端主流程与路由 |
| `backend/src/index.ts` | HTTP/WS 入口 |
| `backend/src/services/sessionService.ts` | 会话与训练状态 |
| `shared/src/voicePartnerContract.ts` | 语音黑盒请求/响应契约 |
| `backend/src/services/voicePartnerProxyService.ts` | 代理对方 HTTP |

同一开发波次中，每个热点文件建议单一 Owner（见 `AGENTS.md`）。

---

## 5. 技术栈

| 层 | 技术 |
|----|------|
| 前端 | React、Vite、TypeScript |
| 后端 | Node.js、Express、WebSocket、Zod |
| 共享 | `shared/` TypeScript 包 |
| 存储 | SQLite（开发/演示默认） |
| 语音服务 | Python（可选，`tools/voice-service/`） |

---

## 6. 目标架构文档（设计参考）

改架构或契约前建议阅读：

- `docs/TARGET_PRODUCT_REQUIREMENTS.md`
- `docs/SYSTEM_ARCHITECTURE_V2.md`
- `docs/DOMAIN_EVENTS.md`
- `docs/MULTI_AGENT_DEVELOPMENT_PLAN_V2.md`

文档中的「建议」「待确认」项不代表已实现；以代码与本节「当前已实现」为准。

---

## 7. 安全与合规约束（当前事实）

- 仓库 **禁止** 提交真实 API Key；使用 `.env.example` 模板。
- 未经评审 **不要** 启用外网 STT/TTS/LLM 或向外部发送儿童数据。
- 原始音视频默认关闭；启用需配置保留、同意与删除流程。

---

## 8. 归档说明

根目录早期静态 HTML 原型、Codex 自动化提示词已移至 `archive/`（见 `archive/README.md`）。课程素材 `matching/`、`paixu/`、`Emotions/` **仍在使用**，勿归档。

---

## 9. 验证基线

```bash
npm run build
npm test
git diff --check
```

交接前建议执行并通过。
