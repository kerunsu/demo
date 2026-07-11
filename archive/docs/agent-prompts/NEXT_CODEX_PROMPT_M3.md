# NEXT_CODEX_PROMPT_M3

请执行 `M3-001 局域网运行时配置`。

本轮只使用当前主 Agent：

- 不创建或调用任何子 Agent；
- 不进行并行委派；
- 不使用多 Agent 工作流；
- 可以运行本地命令和测试；
- 不写入真实密钥，不调用真实外部 API。

## 开始前必须阅读

按顺序阅读：

1. `AGENTS.md`
2. `frontend/AGENTS.md`
3. `backend/AGENTS.md`
4. `docs/PROJECT_OWNER_DECISIONS.md`
5. `docs/SYSTEM_ARCHITECTURE_V2.md`
6. `docs/DOMAIN_EVENTS.md`
7. `docs/WORK_ITEMS_M3.md`
8. `docs/DEMO_RUNBOOK.md`
9. `docs/API.md`

## 开始前验证

执行：

```bash
git branch --show-current
git status --short
npm test
npm run build
git log --oneline -5
```

若出现测试失败、Build 失败、除已确认的 `Emotions/` 外存在来源不明修改，先停止并报告，不要为了通过检查而修改业务代码。

## 当前事实

- 当前分支应为 `codex/overnight-m1-m2`。
- `Emotions/` 已由项目负责人确认为正式 GIF 资源目录，包含 9 个 GIF，但不要移动、重命名、重新编码或删除这些 GIF。
- 当前前端 API 和后端启动配置仍存在 `127.0.0.1` 硬编码。
- 当前尚无 WebSocket 服务，本任务只准备 WebSocket URL 配置，不实现 WebSocket 连接。
- 当前后端 CORS 使用默认开放配置，本任务需要给出可配置且测试可控的 CORS 行为。

## 目标

让本机 Demo 和局域网双主机运行都能通过配置工作：

1. 前端 API Base URL 可配置；
2. 前端 WebSocket URL 可配置，但不实现 WebSocket；
3. 后端 Host 和 Port 可配置；
4. 后端 CORS Origin 可配置；
5. 后端静态素材 URL 生成不硬编码 `127.0.0.1`；
6. 默认无环境变量时，本机 Demo 和现有测试仍可通过；
7. 配置错误要有明确失败信息；
8. 不调用真实外部 API；
9. 不改变判题、报告、Provider、状态机或领域事件语义。

## 非目标

- 不实现 WebSocket 服务；
- 不实现双屏事件同步；
- 不实现 GIF 播放；
- 不移动或修改 `Emotions/`；
- 不接真实 STT/TTS/LLM；
- 不新增真实密钥或真实 `.env`；
- 不改变当前训练闭环业务行为。

## 建议实现范围

允许修改：

- `frontend/src/config/**`
- `frontend/src/services/api.ts`
- `frontend/test/**`
- `backend/src/config/**`
- `backend/src/index.ts`
- `backend/src/app.ts`
- `backend/src/services/courseService.ts`
- `backend/test/**`
- 必要的运行说明文档，例如 `docs/DEMO_RUNBOOK.md`

禁止修改：

- `frontend/src/App.tsx`，除非证明配置注入无法避开，且只做最小改动；
- `backend/src/services/sessionService.ts`，除非证明配置注入无法避开，且只做最小改动；
- `package.json` 和 lock 文件，除非无需新增依赖无法完成并先说明原因；
- `Emotions/**`
- `matching/**`
- `paixu/**`
- 真实 `.env`
- 领域事件、状态机、Provider 和动画契约语义。

## 实现要求

1. 梳理并消除业务运行路径中的后端地址硬编码：
   - `frontend/src/services/api.ts`
   - `frontend/src/App.tsx` 中图片 URL 相关常量，如能通过已有服务或配置隔离则不要扩大改动；
   - `backend/src/index.ts`
   - `backend/src/services/courseService.ts`
2. 前端配置建议支持：
   - `VITE_API_BASE_URL`
   - `VITE_WS_URL`
   - 默认 `http://127.0.0.1:3001/api`
   - 默认 `ws://127.0.0.1:3001/ws`
3. 后端配置建议支持：
   - `BACKEND_HOST`
   - `PORT` 或 `BACKEND_PORT`
   - `CORS_ORIGIN`
   - `PUBLIC_BACKEND_ORIGIN` 或等价配置，用于生成课程图片绝对 URL
4. 配置解析需可测试：
   - 空配置返回本机默认值；
   - LAN 配置能返回指定 host/origin；
   - 无效 URL 或端口给出明确错误。
5. CORS：
   - 测试环境和默认本机 Demo 不应被破坏；
   - 支持逗号分隔 origin；
   - 不写入真实域名或密钥。
6. 保持现有 HTTP API 响应字段兼容。

## 测试要求

至少运行：

```bash
npm run test:backend
npm run test:frontend
npm test
npm run build
git diff --check
```

建议补充或更新测试以覆盖：

- 前端默认 API/WS 配置；
- 前端环境变量覆盖；
- 后端默认 host/port/CORS/public origin；
- 后端 LAN 配置覆盖；
- 课程图片 URL 不再固定为 `http://127.0.0.1:3001`。

## 验收标准

- `npm test` 通过；
- `npm run build` 通过；
- `git diff --check` 通过；
- 不修改 GIF 资源；
- 不调用真实外部 API；
- 默认本机 Demo 配置仍可用；
- 可通过环境变量配置局域网后端地址；
- 最终回复列出修改文件、测试结果、是否存在未提交的 `Emotions/` 资源目录、是否修改了业务逻辑。

## 回滚方式

若任务失败，恢复新增配置文件、API 客户端、后端启动配置、CORS 改动和相关测试；不要删除或移动 `Emotions/`。
