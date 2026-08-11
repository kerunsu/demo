# 报告评分公式与调参说明

> 配置文件：[`config/report_scoring.yaml`](../config/report_scoring.yaml)  
> 计算实现：`app/report/scoring.py`  
> 详细设计背景：[`TEACHER_RATING_REPORT_PLAN.md`](TEACHER_RATING_REPORT_PLAN.md)

## 1. 公式版本（formulaVersion）

- yaml 中的 `schema_version` 会在生成报告时写入快照字段 `formulaVersion`。
- **只影响之后新生成的报告**；已落盘的旧报告保留生成时的版本与分数，不会因改 yaml 而重写。
- 教师端报告页会展示当前报告的 `formulaVersion`，便于对照调参。

## 2. 中途改权重的运营约定

| 场景 | 建议 |
|------|------|
| 训练进行中改 yaml | 运行时下次 `compute_dimensions` / `generate` 会读新配置；**已写入的报告文件不自动重算** |
| 需要旧场次用新权重 | 对该 `trainingSessionId` 显式调用报告 refresh（会覆盖报告内容，但应保留首次 `generatedAt` 若服务支持） |
| 日常运营 | **建议下一场训练再生效**，避免同场前后课点用不同权重导致解释困难 |

## 3. 权重含义与调参范围

### 3.1 五维综合权重 `weights`

`attention` / `expressiveLanguage` / `receptiveLanguage` / `matching` / `ordering`，和应为 **100**。  
缺维时按已有维度重新归一化，并在 `dataQuality.limitations` 中记录原因码。

调参建议：单维不宜长期低于 10 或高于 40，以免某一维噪声主导综合分。

### 3.2 课型平衡 `course_weights`

五类课程（mimic / naming / onomatopoeia / pairing / ordering）相对权重，默认均为 1。  
题量不均时靠此避免某一课型刷高综合任务表现。

### 3.3 配对/排序 `interactive_course`

- `accuracy_weight` / `response_weight`：客观正确率与反应时合成。
- `objective_weight` / `teacher_weight`：客观分与教师 1–5 评分合成。
- `ideal_response_sec` / `slow_response_sec`：反应时映射到 100→0 的区间。

### 3.4 维度内部 `dimension_weights`

接受性/表达性/注意力内部子源权重；缺项时重新归一化。

### 3.5 表达/接受代理 `expressive` / `receptive`

语音占比、词数上限、清晰度代理等；无语音活动时表达维应 `available=false` 并写入 limitations，**禁止伪造高分**。

### 3.6 等级阈值 `grade_thresholds`

`excellent` / `good` / `fair` / `needs_support` 对应综合分档。

## 4. 叙事 provider

- `narrative_provider: rule`（默认）— 规则模板，禁止临床诊断措辞。
- `narrative_provider: mock` — 固定占位文案，仅演示。
- 其他值（含 LLM）一律回落 `rule` 并打日志；**默认不开 LLM**。

## 5. 数据质量 limitations

报告与监控对同一套原因码做中文展示。典型码：

| 码 | 含义 |
|----|------|
| `TEACHER_RATING_MISSING` | 缺少教师逐题评分 |
| `ATTENTION_DATA_MISSING` | 注意力有效样本不足 |
| `DIMENSION_*_UNAVAILABLE` | 某维度无可用数据 |
| Mock / 演示相关 | 分析器为 Mock 时标明「演示/占位数据」 |

无人脸 / `quality=MISSING`：**不得**把孩子标成「低注意力/分散」。

## 6. 打印抽检清单

教师端报告支持横竖屏与 `window.print()`。改版或发版前抽检：

1. 竖屏：雷达图、综合分圆环、叙事块完整可见，页脚版权不被裁切。  
2. 横屏：双栏布局关键 KPI / 曲线不重叠、不溢出页面。  
3. 浏览器打印预览：边距正常，关键数字与 limitations 条文可读。  
4. 有 limitations / PARTIAL 时琥珀色说明条完整打印。  
5. 页眉「公式版本」一行可见（若有）。

## 7. 验收一句

只改 `report_scoring.yaml` → **新生成**报告权重变化，旧报告 `formulaVersion` 与分数保持生成时快照。
