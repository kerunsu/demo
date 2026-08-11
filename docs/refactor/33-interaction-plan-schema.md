# InteractionPlan / BehaviorPlan schema

内部字段使用 snake_case；HTTP/Socket 仍由 facade 生成历史 camelCase 字段。当前 `BehaviorPlan.schema_version=1`，它是一次行为的不可变快照，不能在进入行为互斥锁后被后续控制端编辑覆盖。

```json
{
  "behavior_id": "behavior-course-1-q1",
  "request_id": "req-1",
  "context": {
    "course_id": "course-1",
    "course_type": "naming",
    "question_id": "q1",
    "event_key": "question.naming",
    "scene_key": "red",
    "line_id": "line-1",
    "profile_version": "v3"
  },
  "profile_version": "v3",
  "source": "v2.inherit",
  "speech": [{"command_id": "...", "text": "这是什么？", "pause_asr": true}],
  "motions": [{"assetId": "nod", "offsetMs": 120}],
  "expressions": [{"assetId": "happy.gif"}],
  "visual": [],
  "course_commands": [],
  "resolution_trace": ["profile=course-1:v3:event=question.naming/scene=red/line=line-1", "v2:inherit"]
}
```

## 解析规则

1. 先取 session 冻结的曾经 published `profile_version`（新版本发布后它可能标记为 archived，但仍可供已冻结 session 使用）；没有冻结版本时取 course published profile，再取 courseType/global published profile。draft 永不参与运行时。
2. 在 profile 内按 scene+line → scene → event+line → event → compact event binding 查找。
3. `inherit` 只覆盖 V2 明确提供的字段，其余沿用 legacy；`replace` 从空计划开始；`disabled` 明确使用 legacy。
4. 没命中、事件未登记、版本不是 published 或 profile 校验失败时，完整回到 legacy。

`resolution_trace` 用于控制端预览和 session 审计，不得包含绝对文件路径或敏感凭据。素材引用使用 `assetId/version`，物理 filename 由资源索引解析。
