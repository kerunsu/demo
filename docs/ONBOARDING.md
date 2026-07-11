# 工程快速上手

> 更新日期：2026-06-15  
> 面向接手本仓库的开发、运维与语音对接方。

---

## 1. 五分钟跑起来

### 环境要求

| 项 | 版本/说明 |
|----|-----------|
| Node.js | **20+**（建议 LTS） |
| npm | 随 Node 安装 |
| Python | **3.10+**（仅本地语音服务 `tools/voice-service/` 需要；纯规则对话可不装） |
| 操作系统 | Windows / macOS / Linux；双屏演示以 Windows 为主 |

### 安装与启动

完整说明见 **[`docs/DEPENDENCIES.md`](DEPENDENCIES.md)**（Node / Python / 语音模型分场景安装）。

```bash
# 在项目根目录
npm install
npm --prefix backend install
npm --prefix frontend install

# 复制后端环境（首次必做）
cp backend/.env.example backend/.env   # Windows: copy backend\.env.example backend\.env

# 一键启动：后端 + 前端 + 本地语音服务
npm run dev
```

默认地址（建议用 `127.0.0.1`，避免部分环境 `localhost` 解析异常）：

| 服务 | 地址 |
|------|------|
| 儿童端 | http://127.0.0.1:5173/child |
| 机器人表情屏 | http://127.0.0.1:5173/robot |
| 监控/工程台 | http://127.0.0.1:5173/server |
| 后端 API | http://127.0.0.1:3001/api |
| WebSocket | ws://127.0.0.1:3001/ws |

### 验证

```bash
npm run build
npm test
```

停止开发进程占用端口：`npm run dev:stop`（释放 3001、5173）。

---

## 2. 三屏演示流程

1. 打开 **儿童端** `/child`，输入昵称并开始训练。
2. 另开窗口打开 **机器人屏** `/robot`（全屏表情，WebSocket 驱动 GIF）。
3. 训练过程中可在 **监控台** `/server` 查看注意力、语音流水线、题目统计等快照。
4. 完成课程后查看报告（含 V2 专业叙事，默认可用 mock 规则生成）。

详细演示步骤见 `docs/DEMO_RUNBOOK.md`。

---

## 3. 角色与维护边界

| 角色 | 维护范围 | 必读文档 |
|------|----------|----------|
| **本仓主开发** | `frontend/`、`backend/`、`shared/`、会话/课程/报告/监控 | 本文、`PROJECT_CONTEXT.md`、`docs/ENVIRONMENT.md` |
| **语音黑盒对接方** | 仅 `tools/voice-partner/`（STT/LLM/TTS） | `tools/voice-partner/一页交接说明.md`、`CONTRACT.md` |
| **本地语音服务** | `tools/voice-service/`（Vosk/Piper 等） | `tools/voice-service/README.md` |
| **现场运维** | 局域网部署、备份、日志 | `docs/DEPLOYMENT_OPERATIONS_M7.md`、`deploy/*.env.example` |

**当前事实：** 儿童端在 `VOICE_DIALOG_PROVIDER=partner` 时，将音频 + 页面上下文发给本仓后端，由后端代理至对方 HTTP 服务；对方失败时 **不回退** 内置规则（`VOICE_PARTNER_FALLBACK=none`）。

---

## 4. 环境配置（摘要）

完整变量说明见 **`docs/ENVIRONMENT.md`**。

### 最小可运行（默认）

```bash
# backend/.env — 从 backend/.env.example 复制即可，默认：
VOICE_DIALOG_PROVIDER=rule
DEMO_STORAGE_PROVIDER=sqlite
RAW_MEDIA_PERSISTENCE=disabled
```

### 启用语音黑盒对接

**本仓 `backend/.env`：**

```env
VOICE_DIALOG_PROVIDER=partner
VOICE_PARTNER_BASE_URL=http://127.0.0.1:9876
VOICE_PARTNER_API_KEY=dev-partner-key
```

**对方 `tools/voice-partner/partner.env`：**

```env
PARTNER_API_KEY=dev-partner-key
CONTEXT_INPUT_MODE=text_and_screenshot   # 或 text_only / screenshot_only
```

启动对方参考服务后，在儿童端训练页使用语音输入即可联调。

### 本地真实 STT/TTS（可选）

```bash
npm run dev:vosk   # 使用 Vosk + Piper 本地模型（需按 tools/voice-service/README.md 准备模型）
```

---

## 5. 仓库结构

```text
frontend/          React 三屏 SPA（child / robot / server）
backend/           Express API、WebSocket、会话与报告服务
shared/            前后端共享契约（领域事件、状态机、语音 partner 契约等）
tools/voice-partner/   语音黑盒对接方工作区（对方维护）
tools/voice-service/   Python 本地 STT/TTS 服务
matching/ paixu/   课程素材（后端扫描生成题目）
Emotions/          机器人表情 GIF 资源
docs/              产品、架构、运维与进度文档
deploy/            生产/LAN 环境模板
archive/           历史原型与过时文档（不参与构建）
.runtime/          本地 SQLite、媒体、日志（gitignore，勿提交）
```

---

## 6. 文档索引

| 文档 | 用途 |
|------|------|
| `README.md` | 仓库概览与入口链接 |
| `PROJECT_CONTEXT.md` | 当前能力与边界（交接用短版） |
| `docs/ENVIRONMENT.md` | 全部环境变量说明 |
| `docs/DEPENDENCIES.md` | Node / Python / 语音模型依赖安装 |
| `docs/FOUR_STAGE_PROGRESS_AND_NEXT_PLAN.md` | 四阶段完成度与待验收项 |
| `docs/WAVE3_VOICE_PARTNER_HANDOFF_PLAN.md` | 波次 3 语音黑盒实施说明 |
| `docs/TARGET_PRODUCT_REQUIREMENTS.md` | 产品需求 |
| `docs/SYSTEM_ARCHITECTURE_V2.md` | 目标架构 |
| `docs/DOMAIN_EVENTS.md` | 领域事件契约 |
| `AGENTS.md` | AI Agent 协作规则 |

---

## 7. 常见问题

**Q: 改了 `backend/.env.example` 为什么不生效？**  
A: 运行时只读 `backend/.env`，修改 example 后需复制并重启 backend。

**Q: 前端连不上后端？**  
A: 确认 `npm run dev` 已启动 backend（3001）；开发模式前端通过 Vite 代理，勿单独改端口除非同步 `vite.config.ts`。

**Q: 语音对方要改儿童端代码吗？**  
A: 不需要。只需实现 `tools/voice-partner/CONTRACT.md` 中的 HTTP 接口，并由本仓配置 `VOICE_PARTNER_BASE_URL`。

**Q: `.runtime/` 里是什么？**  
A: 本地 SQLite 数据库、可选原始音视频、模型缓存；已在 `.gitignore`，交接时勿当作源码提交。
