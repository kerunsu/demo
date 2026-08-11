# Legacy interaction migration report

## 当前结论

旧 `MappingResolver` 的真实优先级是：项目级 → 学生课程级 → 课程级 → 默认级；旧 aux 主要是 `question/praise/hint/silent/social_*`。`question` 本身没有课程情境语义，因此 naming、拟声/模仿、排序、配对需要由 `courseType` 或显式 `eventKey` 补充。

## 安全迁移方式

`app/computation/interaction/migration.py` 只生成 draft 和 dry-run 报告，不写 `course_map.json`，不自动 publish。课程级旧 entry 可转换成 V2 `replace` binding，但由于它可能覆盖学生/项目级旧映射，必须人工审阅 precedence 后再发布；未发布期间旧逻辑完全不变。

报告包含 sourceEntryCount、convertedEventCount、warnings、errors、生成的 profile 和 `writes=[]`。未知旧 aux 不静默丢失，会列为 `unmapped_legacy_aux:*`。

## naming 例子

旧的 `aux.question` 在 `courseType=naming` 下解析为 `question.naming`。没有已发布 `question.naming` binding 时，V2 resolver 返回 legacy plan，动作、emotion、sequence 和 audio offset 逐字段沿用旧结果。只有控制端发布课程 profile 后，V2 的 inherit/replace 绑定才覆盖明确配置字段。

回滚是重新发布旧的 published profile version；若 V2 provider 或资源索引失败，运行时继续 legacy。新 profile 的 session 应记录 `profile_version`，同一场 session 中途不得随控制端修改切换版本。
