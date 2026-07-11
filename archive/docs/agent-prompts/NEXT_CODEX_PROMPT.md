# NEXT_CODEX_PROMPT

请使用当前主 Agent 单独执行 `M1-001 后端 API 自动化测试基线`。默认不要调用子 Agent；为了节省额度，默认也不要调用只读 `repo_explorer`。只有在无法确认后端 API 边界时，最多允许调用一个只读 `repo_explorer`，且不得委派实现。

## 任务目标

为当前后端建立可重复执行的 API 自动化测试基线，覆盖：

1. `GET /api/health` 健康检查；
2. `POST /api/session/start` 创建会话；
3. `GET /api/session/:sessionId` 查询会话；
4. `GET /api/course/:sessionId/current` 获取当前题目；
5. `POST /api/course/:sessionId/answer` 提交正确答案；
6. `POST /api/course/:sessionId/answer` 提交错误答案；
7. 非法请求；
8. 不存在的会话；
9. 默认规则聊天；
10. `POST /api/report/:sessionId/generate` 报告生成；
11. `GET /api/report/:sessionId` 报告查询。

## 必须阅读

按顺序阅读：

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `docs/PROJECT_OWNER_DECISIONS.md`
4. `docs/API.md`
5. `docs/WORK_ITEMS_M1_M2.md`
6. 根目录和 `backend/` 的 `package.json`
7. 仅为确认测试边界，阅读 `backend/src/index.ts`、`backend/src/services/sessionService.ts`、`backend/src/services/voice/`、`backend/src/config/runtime.ts`

不要做全仓库宽泛审查。

## 允许修改

- 后端测试文件；
- 后端测试配置；
- 根级或后端 `package.json` 中与 `npm run test:backend` 相关的最小必要脚本；
- 若必须新增测试 fixture，只能新增测试 fixture 文件。

## 禁止修改

- `frontend/src/**`
- `matching/**`
- `paixu/**`
- 动画资源；
- 真实 `.env`；
- 业务代码的大规模重构；
- Package Lock，除非用户明确批准安装测试依赖；
- 任何真实 API Key、token、credential；
- Git commit。

## Provider 与安全约束

- 强制使用规则 Chat Provider。
- 强制使用 Noop TTS。
- 禁止调用外部网络和真实外部 API。
- 不得启用真实 STT、TTS、LLM 或 Safety Review provider。
- 不得发送儿童原始音频、视频、图像或聊天原文到外部服务。

## 测试要求

- 测试不得依赖随机题目顺序。应从当前题目的返回数据中读取可用选项，并基于返回字段选择正确/错误答案。
- 测试必须覆盖成功路径和错误路径。
- 测试结束后不得残留后端进程或占用端口。
- 如果当前架构导致测试必须启动真实本地后端进程，测试脚本必须负责启动、等待健康检查和关闭进程。
- 如果发现现有构建或测试环境问题，不得为了修复它而修改前端或无关业务代码；先报告具体阻塞。

## 验收命令

完成后运行：

```bash
npm run test:backend
npm run build
git diff --check
git status --short
```

不要创建 Git commit。

## 最终回复

最终只汇报：

1. 修改的文件；
2. 覆盖的 API 场景；
3. 是否强制 rule Chat Provider 和 Noop TTS；
4. 是否存在残留进程；
5. 测试、构建和 Git 检查结果；
6. 是否修改了前端或业务代码；
7. 未解决阻塞项。
