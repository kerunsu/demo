# Demo 报告评分

事实源：`config/report_scoring.yaml`、`config/demo_course_scope.json`；实现：`app/report/scoring.py`。

## 新报告范围

新报告只包含：

- `attention`：配对/排序过程中的跨课程注意力证据，默认权重 34。
- `matching`：配对表现，默认权重 33。
- `ordering`：排序表现，默认权重 33。
- 课程分：`pairing`、`ordering`；注意力作为跨课程采集维度保留。

命名、拟声、社交和其他旧课型即使仍存在于历史数据库，也不会进入 Demo 新报告、教师端图表或 Server 审核字段。旧报告按落盘快照读取，不通过删库或重写历史记录处理。

## 计算与调参

- `schema_version` 写入 `formulaVersion`，只影响之后生成或显式刷新的报告。
- 三个维度权重合计必须为 100；缺失维度按可用项重新归一化，并写入数据质量限制。
- 配对/排序由客观正确率、反应时间与教师 1–5 评分合成；互动页反馈和评分必须对应同一题目身份。
- 配对、排序分别至少需要 5 道有效作答才进入综合分；不足时保留 `provisionalScore`、`validSampleCount` 和 `requiredSampleCount` 供审核，但正式 `score=null`，不按零分处理。
- 样本门槛由 `sample_sufficiency.minimum_effective_samples` 配置，Server“报告与评分”页面只暴露配对、排序两项；修改后只影响新报告并改变公式指纹。
- `course_goal_score` 是训练参考目标，不是临床常模或诊断阈值。
- `narrative_provider` 默认 `rule`；不输出临床诊断措辞。

## 审核与幂等

教师审核、刷新或重复提交同一报告时必须幂等。结构化建议分别保存“练什么、为什么、如何判断进步”；历史单段建议只展示一次。打印检查需覆盖课程范围、百分比柱、目标线、数据不足状态和分页裁切。

修改评分配置后必须运行报告测试与完整测试集，并在影响说明中明确公式版本和只影响新报告的范围。
