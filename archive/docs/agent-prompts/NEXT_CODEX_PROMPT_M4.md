# NEXT CODEX PROMPT: M4-003 固定 STT/TTS Provider 契约

请执行 `M4-003 固定 STT/TTS Provider 契约`。

本轮只使用当前主 Agent：

- 不创建或调用任何子 Agent。
- 不进行多 Agent 委派。
- 不 Push。
- 不合并 main。
- 不擅自更换 M4-002B 已选择的默认模型方案。

## 开始前读取

按顺序阅读：

1. `AGENTS.md`
2. `backend/AGENTS.md`
3. `frontend/AGENTS.md`
4. `PROJECT_CONTEXT.md`
5. `docs/PROJECT_OWNER_DECISIONS.md`
6. `docs/M4_TECHNICAL_DECISIONS.md`
7. `docs/WORK_ITEMS_M4.md`
8. `docs/VOICE_STT_TTS_BENCHMARK_REPORT.md`
9. `docs/SPEECH_LLM_PIPELINE.md`
10. `docs/AI_CHILD_SAFETY_SPEC.md`
11. `docs/DOMAIN_EVENTS.md`
12. `docs/INTERACTION_STATE_MACHINE.md`
13. `docs/SYSTEM_ARCHITECTURE_V2.md`
14. `docs/DECISIONS_REQUIRED.md`
15. `tools/voice-benchmark/README.md`

## 基线验证

执行并记录：

```bash
git branch --show-current
git status --short
npm test
npm run build
```

如果存在本任务之前的无关修改，不覆盖、不删除；先记录并限定本轮范围。

## 当前阶段事实

- 当前开发服务器 baseline 为 `DEVELOPMENT_SERVER_BASELINE`。
- M4-001 状态为 `COMPLETE_FOR_DEVELOPMENT`。
- M4-002 Harness 状态为 `BENCHMARK_HARNESS_COMPLETE`。
- M4-002B 状态为 `PROVISIONAL_PROVIDER_DECISION`。
- 云端 STT/TTS 尚未实测，状态为 `CLOUD_STT_CREDENTIALS_PENDING` / `CLOUD_TTS_CREDENTIALS_PENDING`。
- 不得把云端未测试写成不可用；也不得把开发阶段云端测试理解为最终产品儿童数据上云已批准。

## 默认 Provider 路线

M4-003 必须以 M4-002B 的阶段性决定为输入：

```text
STT: LOCAL_PRIMARY_CLOUD_OPTIONAL
TTS: LOCAL_PRIMARY_CLOUD_OPTIONAL
```

默认 STT Provider：

```text
providerId: local-vosk-small-cn
providerType: local
modelId: vosk-model-small-cn-0.22
modelPath: .runtime/models/vosk/vosk-model-small-cn-0.22
externalNetworkCalled: false
hardwareAcceleration: CPU
```

默认 TTS Provider：

```text
providerId: local-piper-zh-huayan
providerType: local
modelId: zh_CN-huayan-medium
modelPath: .runtime/models/piper/zh_CN-huayan-medium.onnx
configPath: .runtime/models/piper/zh_CN-huayan-medium.onnx.json
externalNetworkCalled: false
hardwareAcceleration: CPUExecutionProvider
humanReview: HUMAN_REVIEW_PENDING
licenseReview: REQUIRED_BEFORE_PRODUCTION
```

推荐推理服务技术栈：

```text
Node.js 训练编排后端
-> Provider 接口
-> 独立 Python 语音推理服务
```

## Provider 替换能力

契约必须支持：

- `local`
- `cloud`
- `mock`

STT/TTS Provider 接口至少覆盖：

- 初始化；
- 健康检查；
- 请求；
- 取消；
- 超时；
- 错误；
- Provider 标识；
- 模型标识；
- 模型路径或供应商模型名；
- 耗时；
- 是否发生外部网络调用；
- 输入数据是否持久化；
- 降级路径；
- 资源指标；
- 数据安全声明；
- 人工复核状态。

业务编排不得直接绑定 Vosk、Piper、OpenAI 或任何具体 SDK。

## 云端未验证项

保留现有云端 Provider 槽位：

- `cloud-openai-stt`
- `cloud-openai-tts`

只有同时满足以下条件才允许实际调用：

1. 环境变量存在；
2. `VOICE_BENCHMARK_ENABLE_CLOUD=1` 或后续等效显式开关开启；
3. 测试资料为合成、开发人员授权或明确授权的非儿童数据；
4. 日志不输出 Key；
5. 不提交请求音频、响应音频或敏感文本。

缺少凭据时继续标记：

- `CLOUD_STT_CREDENTIALS_PENDING`
- `CLOUD_TTS_CREDENTIALS_PENDING`

不得询问用户在聊天中提供 Key。

## 何时允许重新 Benchmark

后续任务不得擅自更换默认 STT/TTS 模型方案。只有以下情况允许触发新的 Benchmark：

- 云端凭据存在且项目负责人明确允许云端 Benchmark；
- `HUMAN_REVIEW_PENDING` 试听失败；
- Piper 许可证复核不能满足生产部署；
- 新本地候选有明确普通话、许可证、部署或性能优势；
- 最终服务器硬件与当前 `DEVELOPMENT_SERVER_BASELINE` 明显不同；
- M4-003 契约实现发现当前 Provider 无法满足取消、超时或隔离恢复要求。

## 任务目标

将 STT/TTS Provider 契约固化为共享代码和测试：

- 定义 STT/TTS Provider metadata、request、response、error、health、timeout、cancel 和 metrics 类型。
- 覆盖 local/cloud/mock 的统一边界。
- 保留 M4-002B 默认 Provider 标识，但不在正式业务代码中直接运行模型推理。
- 为后续 M4-004 至 M4-009 提供稳定契约。

## 禁止范围

- 不实现完整语音产品链路。
- 不修改课程逻辑、报告逻辑或训练评分逻辑。
- 不提交 `.runtime/`、模型、venv、测试音频或真实 `.env`。
- 不启用真实云端 API。
- 不上传真实儿童音频。
- 不把 Piper 人工试听和许可证复核写成已完成。

## 验收命令

至少执行：

```bash
npm test
npm run build
git diff --check
git status --short
git diff --stat
```

Git 由 Codex 自行选择性暂存并创建本地 Commit；禁止 `git add .`。

最终回复需说明：

1. M4-003 状态；
2. 固化的 Provider 契约文件；
3. 默认 STT/TTS Provider 标识；
4. 云端未验证项；
5. Provider 替换和降级边界；
6. 测试和 Build 结果；
7. 本地 Commit；
8. 是否修改正式训练业务逻辑；
9. 是否调用子 Agent。
