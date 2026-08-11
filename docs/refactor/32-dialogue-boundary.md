# 语音对话边界

## 责任

语音对话块接收 `DialogueRequest`（文本或音频、session、课程/题目上下文和 requestId），输出 `DialogueResponse`（原始 transcript、回复文本、`SpeechCommand` 播报指令、provider、唤醒状态和降级原因）。它不读 DB，不写 sessions，不直接操作机器人。

`app/dialogue/boundary.py` 提供：

- `DialogueGateway`：ASR → 唤醒判断 → provider/LLM → 可选 TTS 的超时、取消和可关闭编排。
- `LegacyDialogueAdapter`：把现有 `DialogueService.generate_reply()` 映射到 DTO，不复制历史窗口、规则安全策略或随机话术池。
- `SpeechCommand.pause_asr=True` 默认保留，保证播报期间暂停 ASR；TTS 失败不生成伪造音频资产，浏览器文本播报仍可由旧 facade 处理。

现有 `app/dialogue/sockets.py` 仍是旧 transport 入口，继续维护原唤醒词、页面上下文切换、历史清理、儿童端事件和 browser TTS fallback。新 gateway 是可注入边界，未发布 provider 不会改变当前儿童端行为。

## 状态与失败

`status` 使用 `ok`、`awake`、`not_awake`、`degraded`、`cancelled`；provider 超时/异常只返回 degraded/error，不把错误当成儿童回复。每个请求必须携带 requestId 和 session，页面上下文变化应产生新的 context fingerprint。

## 替换步骤

1. 用 fake ASR/LLM/TTS 验证 DTO、唤醒、超时、取消和 ASR 暂停。
2. 用 `LegacyDialogueAdapter` 对比旧 Socket 的 text、provider、strategy、history 和安全回复。
3. 在 composition root 通过配置选择 provider；未配置或健康检查失败时继续 legacy adapter。
4. 通过字段级 characterization test 后，才允许把某一类 Socket 事件切到 gateway。
