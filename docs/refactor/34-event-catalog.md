# 事件目录与状态机

默认目录固定包含 16 个事件：

`idle`、`sleepy`、`question.naming`、`question.vocal_imitation`、`question.ordering`、`question.pairing`、`praise`、`hint`、`call_child`、`retry`、`greeting`、`greeting_response`、`farewell`、`farewell_response`、`calm_speech.2s`、`calm_speech.3s`。

事件定义包含 key、label、kind（`state`/`instant`/`timed`）、duration、interruptible、priority、return_to_idle 和可选 `allowed_from` 转移白名单。没有声明白名单的旧事件保持兼容地允许转移；timed 事件必须有正 duration。

课程类型到旧 aux 的兼容推导在 `infer_event_key()`：naming → `question.naming`，明确的 onomatopoeia/发声模仿元数据 → `question.vocal_imitation`，ordering/sequencing → `question.ordering`，pairing/matching → `question.pairing`。generic `mimic` 在没有明确发声模仿元数据时不强行映射，保留 legacy。它只在 V2 未明确给出 `eventKey` 时使用。

控制端可通过 `/api/v2/interaction/events` 查看和新增事件。新增事件写入 `doll/data/event_catalog.json`，发布后 key 不可复用为另一种语义；事件目录文件损坏时只忽略可选扩展，不影响旧程序启动。

课程 profile 的 `events` 必须引用已登记事件，非法事件、非法 mode、非法 sequence 或自引用继承不能发布。新增状态的动作/表情/话术绑定应先做 draft、预览和 fake session 验证，再显式 publish。
