# 儿童教育互动训练 Demo

本仓库是可本地运行的 **Web Demo**：儿童训练屏、机器人表情屏、监控工程台三屏联动，含课程训练、行为观测、报告生成与语音对话（规则或黑盒对接）。

**新同事请先读：** [`docs/ONBOARDING.md`](docs/ONBOARDING.md)（五分钟跑起来）  
**依赖安装：** [`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md)  
**环境变量：** [`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md)  
**语音黑盒对方：** [`tools/voice-partner/一页交接说明.md`](tools/voice-partner/一页交接说明.md)

---

## 当前能力（2026-06）

| 模块 | 状态 |
|------|------|
| 儿童端 `/child` | 欢迎 → 选课 → 配对/排序训练 → 报告 |
| 机器人屏 `/robot` | 全屏 GIF 表情，WebSocket + ACK |
| 监控台 `/server` | 会话快照、注意力/语音流水线、双屏预览 |
| 会话与报告 | SQLite 持久化；报告 V2（规则/mock/可选 LLM 叙事） |
| 语音 | 规则对话 **或** `VOICE_DIALOG_PROVIDER=partner` 黑盒 HTTP |
| 原始媒体 | 可选受控落盘（默认关闭） |
| 测试 | `npm test`（契约、后端、前端、e2e） |

进度与待验收项：`docs/FOUR_STAGE_PROGRESS_AND_NEXT_PLAN.md`。

---

## 快速启动

```bash
npm install && npm --prefix backend install && npm --prefix frontend install
cp backend/.env.example backend/.env    # Windows: copy backend\.env.example backend\.env
npm run dev
```

- 儿童端：http://127.0.0.1:5173/child  
- 机器人：http://127.0.0.1:5173/robot  
- 监控台：http://127.0.0.1:5173/server  
- API：http://127.0.0.1:3001/api  

```bash
npm run build && npm test    # 交接前建议执行
```

---

## 目录结构

```text
frontend/              React 三屏 SPA
backend/               API、WebSocket、会话/报告/监控服务
shared/                前后端共享类型与契约
tools/voice-partner/   语音黑盒对接方工作区（对方维护）
tools/voice-service/   Python 本地 STT/TTS
matching/  paixu/      课程素材
Emotions/              机器人 GIF
docs/                  产品、架构、运维、上手文档
deploy/                生产/LAN 环境模板
archive/               历史 HTML 原型与过时文档（不参与构建）
```

---

## 主要文档

| 文档 | 说明 |
|------|------|
| [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) | 交接用：边界、热点文件、事实标签 |
| [`docs/ONBOARDING.md`](docs/ONBOARDING.md) | 快速上手 |
| [`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md) | 依赖安装（Node / Python / 语音模型） |
| [`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md) | 环境变量全集 |
| [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md) | 演示手册 |
| [`docs/DEPLOYMENT_OPERATIONS_M7.md`](docs/DEPLOYMENT_OPERATIONS_M7.md) | 生产/LAN 运维 |
| [`AGENTS.md`](AGENTS.md) | AI Agent 协作规则 |

历史 2026-06-06 审查报告已移至 `archive/docs/history/PROJECT_CONTEXT_AUDIT_2026-06-06.md`。
