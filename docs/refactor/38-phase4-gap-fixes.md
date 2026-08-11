# 第四阶段缺口补强记录

本次补强针对第四阶段审查发现的八项问题，目标是保持 legacy 链路、HTTP/Socket 旧字段和录制生命周期不变。

## 已完成

1. `BehaviorPlan.speech` 已接入正式 `play_resource` 链路。V2 profile 明确配置 `speech` 时，服务端通过既有的 `robot_speak_text` 事件定向发送到 `session_<id>_child`，保留 `behaviorId/requestId/lineId/sessionId` 关联，并以同一行为互斥和音频提交门收口。未配置 V2 speech 时继续走旧音频链路。
2. 新增 `legacy_only`、`shadow`、`draft_preview`、`published_canary`、`published` 五阶段。`InteractionDeployment` 提供阶段校验、稳定 canary 选择和 motion/emotion/offset/duration/audioOffset/fallbackPath 对比；shadow 只双算和返回报告，不执行候选动作/表情/台词。
3. 首次真正处理课程 `play_resource` 时，服务端把解析出的 `activeProfileVersion` 写入 session metadata。之后即使前端提交另一个 `profileVersion` 也不覆盖；没有可用 V2 版本时也写入空值，明确冻结为 legacy。新增 `POST /api/v2/interaction/profiles/<course_id>/deploy` 负责阶段切换。
4. 发布校验增加显式逻辑资产引用检查、speech 文本/时长、声明时长范围、`requiredEvents` fallback、lineId 重复、声明 transitions 可达性和跨 binding inheritance 环检测；裸字符串动作/表情仍按旧物理名称兼容。
5. `robot_emotion_auto_random` 在全局行为 busy 时直接拒绝，不检查素材、不 emit `robot_emotion_change`，也不触碰既有 busy 所有权。
6. `/resolve` 复用 `RobotService.resolve_interaction_plan`，与 runtime 使用同一 resolver 构造入口；不存在 resolver 时返回可识别的降级错误，不再依赖无默认值的私有属性。
7. 批量上传只读到单文件/批次上限加一个 sentinel byte；motion 文件写入和 asset index upsert 失败时恢复两个提交前快照，emotion index 失败也恢复索引和媒体文件。上传进度事件仍属于下一阶段控制端工作，未伪造为已完成。
8. `mimic` 只有在 `isVocalImitation`、`eventKey`、`questionSubtype` 等元数据明确指向发声模仿时才映射 `question.vocal_imitation`，无法确认时保留 legacy 解析。

## 兼容边界

- 已有发布接口仍可发布只引用裸字符串的旧动作/表情名称；逻辑 `assetId/version` 对象引用必须通过 asset index 或对应资源库校验。
- `publish` 默认仍进入可用的 `published` 阶段，因此旧控制端无需新增字段即可保持原效果。分阶段试运行使用新增 deploy 端点。
- 影子候选的报告目前随本次行为结果返回并写入 plan metadata；正式的历史报告持久化和控制端可视化留给后续阶段。

## 验证

- `tests/test_phase4_gap_fixes.py` 覆盖 speech 定向投递、shadow diff、发布校验、mimic、session 冻结、busy 门禁和上传限读。
- `contracts.snapshot.json` 已同步新增 deploy 路由：源码 143 条，运行时含 implicit static 共 144 条；Socket 事件集合未改变。
