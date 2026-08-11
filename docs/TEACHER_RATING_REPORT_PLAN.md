# 教师逐题评分与报告计算调整方案

> 创建日期：2026-07-12  
> 当前阶段：核心实现与自动验证完成，等待真实后端/Android 横屏人工验收  
> 本文用途：作为本批次唯一的实施、验证与变更记录；后续每完成一项就在本文更新状态与结果。

## 1. 本批次目标

在教师端每次真正离开当前课点、进入“下一个”之前，要求教师对儿童本课点表现给出 1～5 分评价。评分必须可靠保存，并参与训练报告的课程分、能力维度、综合得分、综合任务表现以及平均响应时长计算。

本批次包含：

1. 新增符合现有教师端视觉风格的逐题评分弹窗。
2. 统一拦截手动和自动的“下一个”路径，避免漏评、重复弹窗或跳两题。
3. 将评分写入现有训练会话的对应题目窗口，并支持幂等覆盖与报告刷新。
4. 调整配对、排序、命名、拟声、模仿五类课程的聚合方式。
5. 调整接受性语言、表达性语言、配对、排序、注意力及报告 KPI 的计算。
6. 为公式、数据契约和关键交互补测试，并完成前端构建与本地端到端冒烟验证。

## 2. 项目现状审查结论

### 2.1 当前“下一个”触发链

教师端的切题逻辑集中在 `teacher_frontend/components/ControlPage.tsx` 的 `handleNext`，当前至少存在以下入口：

| 入口 | 当前行为 | 本次需要的行为 |
|---|---|---|
| 教师点击“下一个” | 直接调用 `handleNext` | 打开评分弹窗，保存成功后再切题 |
| 配对游戏结束 | 收到 `matching_game_end`，延迟 2 秒调用 `handleNextRef.current()` | 延迟后打开同一个评分弹窗 |
| 排序游戏结束 | 收到 `sequencing_game_end`，延迟 2 秒调用 `handleNextRef.current()` | 延迟后打开同一个评分弹窗 |
| 非交互课表扬视频结束 | 收到 `praise_video_ended` 后调用 `handleNextRef.current()` | 打开同一个评分弹窗，评分后再切题并播放下一题提问 |
| 最后一个课点 | `handleNext` 打开课程完成确认框 | 先评分，保存成功后再打开完成确认框 |

配对/排序的表扬只播放音频，当前明确不会走“表扬视频结束 → 下一题”的路径；其自动下一步主要来自各自的 `game_end`。

### 2.2 当前可复用的数据链

现有行为记录已经具备完整的关联键：

- `training_session_id`：整次训练 UUID。
- `question_id`：当前课点 ID，由 `course_id + item_id + question_index` 组成。
- `QuestionWindow.task_metrics`：当前课点的任务指标容器。
- `BehaviorStore`：按 `static/recordings/behavior/{training_session_id}/windows/{question_id}.json` 持久化。
- `BehaviorTimeline.reaggregate()`：从所有窗口重新汇总会话数据。
- `ReportService.refresh()`：重算并覆盖报告，同时保留首次生成时间。

配对和排序已经通过 Socket 事件把正确数、总题数、正确率和响应时长写入 `task_metrics`；晚到的 `game_end` 也能通过补丁窗口避免丢数据。

### 2.3 不采用旧 `AbilityItem.score` 的原因

`database/models.py` 中已有 `AbilityItem.score`，但它是“整次训练 × 能力类型”的最终整数汇总，并非逐课点评价；它关联的还是旧版整数 `TrainingSession.id`，而当前报告链使用行为模块的 UUID `training_session_id`。直接复用会造成双会话 ID、逐题覆盖和报告同步问题。

因此本次不新增独立评分数据库，也不直接写 `AbilityItem`。教师评分应作为当前 `QuestionWindow.task_metrics.teacher_rating` 的一部分保存，报告聚合完成后如未来确需同步旧能力表，再另做兼容层。

### 2.4 已发现的现有计算限制

1. 当前配对分和排序分只等于正确率，尚未结合响应时长和教师评分。
2. 当前接受性语言主要取配对、排序正确率及响应时长；命名只有在语音匹配产出 `receptive_pass_rate` 时才偶尔加入，拟声未正式纳入。
3. 当前表达性语言主要依赖语音占比、词数和清晰度代理，并未按命名、拟声课程分别聚合。
4. 当前报告“任务正确率”只平均配对、排序及可能存在的命名通过率。
5. 当前平均响应时长只来自配对/排序，命名、拟声、模仿没有统一的课点完成时长。
6. `COURSE_TYPE_EXPECTATIONS` 尚未正式识别 `onomatopoeia`；课程数据库实际英文类型为 `mimic / naming / onomatopoeia / pairing / ordering`。
7. 仓库当前没有覆盖本报告公式的自动化测试目录，需要本批次补建最小测试集。

## 3. 交互设计

### 3.1 弹窗结构

弹窗使用现有 Radix Dialog 能力和教师端 Tailwind 风格：

- 半透明深色遮罩并轻度模糊背景，确保操作焦点明确。
- 白色圆角卡片，桌面宽度约 760～860 px；Android 横屏下保持一屏可见。
- 顶部显示“请评价本题表现”、当前课程类别和课点名称。
- 中部横排 5 个大号评分按钮，窄屏时允许自适应为 5 列紧凑布局，不出现纵向长列表。
- 每个按钮包含大号数字、短标签和能力描述；触控目标不小于 72 px。
- 色彩从柔和的暖灰/琥珀过渡到靛蓝/青绿，但不使用刺眼的纯红纯绿，保持教育场景的中性与尊重。
- 选中项使用靛蓝描边、浅色背景、轻微上浮和勾选标记；其他项降低阴影，不只依赖颜色表达状态。
- 底部主按钮为“记录评分并继续”，保存中显示 loading，失败时原地提示并允许重试。
- 次按钮为“返回当前题”，它只关闭弹窗并取消本次切题，不允许跳过评分后继续。
- 点击遮罩和 Esc 不直接关闭，避免误触丢失评分。

### 3.2 五档描述

| 分数 | 短标签 | 儿童能力描述 | 归一化分 |
|---:|---|---|---:|
| 1 | 需要大量协助 | 尚未理解或完成任务，需要持续示范、分步提示和直接协助 | 20 |
| 2 | 需要较多提示 | 能部分参与，但需要多次提示、重复指令或明显协助 | 40 |
| 3 | 基本完成 | 在少量提示下能够完成，理解与反应基本稳定 | 60 |
| 4 | 独立完成 | 基本可以独立、准确地完成，反应较流畅 | 80 |
| 5 | 熟练完成 | 独立、准确且反应迅速，并表现出主动表达或迁移能力 | 100 |

采用 `rating * 20` 而不是把 1 分映射为 0 分，是为了保持五级量表直观，也避免“需要大量协助”被解释成完全没有能力。

### 3.3 统一切题状态机

现有 `handleNext` 拆成两个职责：

1. `requestAdvance(source)`：记录触发来源和当前课点快照，只负责请求切题并打开弹窗。
2. `commitAdvance(snapshot)`：评分保存成功后才执行索引变化、最后一题完成确认和下一题自动提问。

状态建议为：

```text
当前课点
  -> requestAdvance(manual | matching_end | ordering_end | praise_end)
  -> 评分弹窗（单实例，冻结当前课点快照）
  -> 保存 teacher_rating
  -> 收到成功 ACK
  -> commitAdvance
  -> 下一课点 / 完成确认
```

必须满足以下保护：

- 弹窗已打开或正在保存时，后续 `requestAdvance` 只被忽略或合并，不重复弹窗、不重复切题。
- 快照必须包含 `trainingSessionId`、`questionId`、`courseId`、`courseItemId`、`courseType`、课程/课点名称和原始索引，不能在异步保存完成后读取已经变化的 React 状态。
- `play_resource` 回应除现有 `sessionId/trainingSessionId` 外，还要在前端保存后端已返回的 `questionId`。
- 表扬按钮点击时可以先记录“儿童完成时刻”；表扬视频结束后再弹窗，避免表扬视频播放时间被计入儿童响应时长。
- 手动下一题以点击时刻作为完成时刻；配对/排序优先使用游戏自身的响应时长数据。
- 保存失败时不切题；用户可重试或返回当前题。

## 4. 数据契约与持久化

### 4.1 Socket 请求

新增教师端事件 `teacher_rating_submit`：

```json
{
  "trainingSessionId": "uuid",
  "questionId": "6_14_0",
  "runtimeSessionId": "uuid-or-null",
  "courseId": 6,
  "courseItemId": 14,
  "courseType": "naming",
  "rating": 4,
  "responseMs": 4200,
  "advanceSource": "manual",
  "clientRecordedAt": "2026-07-12T12:00:00.000Z"
}
```

服务端返回 `teacher_rating_ack`：

```json
{
  "success": true,
  "trainingSessionId": "uuid",
  "questionId": "6_14_0",
  "rating": 4,
  "normalizedScore": 80,
  "updatedAt": "2026-07-12T12:00:00.100Z"
}
```

### 4.2 服务端校验

- `rating` 必须为整数 1～5。
- `trainingSessionId` 和 `questionId` 必须能关联到同一窗口；若前端未传 `questionId`，只允许回退到该训练当前窗口并记录 warning。
- 前端传入的课程 ID/类型仅用于一致性检查，真正课程信息以窗口为准。
- `responseMs` 必须为非负有限数，并设置合理上限；异常值不写入统计但不影响评分保存。
- 同一 `trainingSessionId + questionId` 重复提交采用覆盖更新，不追加重复样本，保证重试幂等。
- 服务端生成 `updated_at`，客户端时间只作为审计字段。

### 4.3 窗口内保存结构

评分写入原窗口的 `task_metrics.teacher_rating`，不覆盖 `matching`、`sequencing` 或 `receptive` 桶：

```json
{
  "task_metrics": {
    "matching": {
      "accuracy": 86.7,
      "avg_response_ms": 2800
    },
    "teacher_rating": {
      "rating": 4,
      "normalized_score": 80,
      "response_ms": 2800,
      "response_source": "game_metrics",
      "advance_source": "matching_end",
      "client_recorded_at": "...",
      "updated_at": "...",
      "schema_version": "teacher-rating-v1"
    }
  }
}
```

实现上新增专用 `BehaviorService.record_teacher_rating()`，不要把 `type=teacher_rating` 直接平铺到顶层，以免覆盖现有旧格式的 `task_metrics.type`。

评分写入后：

1. 保存窗口 JSON。
2. 若训练已生成 summary，则执行 `reaggregate()`。
3. 若报告已存在，则执行 `ReportService.refresh()`。
4. 返回 ACK；前端只有收到成功 ACK 才继续切题。

## 5. 报告计算方案

### 5.1 基本原则

- 所有计算统一转为 0～100 分。
- 先“课点 → 课程类型”，再“课程类型 → 能力维度/总分”，避免某类课程因为题目数量多而不成比例地支配结果。
- 同一课程类型内部按有效课点平均；跨课程类型按配置权重平均，并对实际存在的数据重新归一化权重。
- 配对和排序保留客观数据为主，教师评价为辅。
- 命名、拟声、模仿本批次以教师评分作为稳定主分；现有语音/姿态代理仍保留在报告原始数据中，不在数据质量不稳定时强行混入。
- 缺少教师评分的旧训练报告仍可生成，使用已有客观数据并显示 `TEACHER_RATING_MISSING`，不能因升级后无法查看历史报告。

### 5.2 课点与课程类型得分

记教师评分归一化值为：

```text
T = rating × 20
```

配对/排序的响应速度分：

```text
RT = clamp(100 × (slow_sec - response_sec) / (slow_sec - ideal_sec), 0, 100)
默认 ideal_sec = 3，slow_sec = 12
```

配对/排序客观分：

```text
O = 0.75 × accuracy + 0.25 × RT
若响应时长缺失，则 O = accuracy，不额外扣分
```

配对/排序最终课点分：

```text
P = 0.70 × O + 0.30 × T
若教师评分缺失（兼容历史数据），P = O
```

命名、拟声、模仿最终课点分：

```text
P = T
```

每类课程得分为该类型所有有效课点 `P` 的平均值。配对和排序虽然内部包含多道游戏题，在行为时间线中各自是一个课程窗口，因此使用该窗口最终游戏指标与一次教师评分组合。

### 5.3 五个能力维度

| 报告维度 | 新公式 |
|---|---|
| 配对 | 配对课程类型得分 |
| 排序 | 排序课程类型得分 |
| 接受性语言 | 配对、排序、命名、拟声四类课程得分的等权平均；缺项时对已有类型重新归一化 |
| 表达性语言 | 命名与拟声课程得分各 50%；只有一类时使用该类并标注数据不完整 |
| 注意力 | 自动注意力分 70% + 模仿教师分 30%；任一项缺失时使用另一项，不因缺失直接记 0 |

接受性语言加入命名和拟声，符合“理解指令/刺激并形成正确对应或反应”的训练目标；表达性语言只综合命名和拟声，避免配对/排序的客观正确率重复进入表达维度。

### 5.4 综合得分

为了真正体现“五类课程都参与”，综合得分不再简单平均存在重叠的五个能力维度，而是直接对五类课程得分做类型平衡加权：

```text
Overall = weighted_mean(
  mimic_course_score,
  naming_course_score,
  onomatopoeia_course_score,
  pairing_course_score,
  ordering_course_score
)
```

默认五类课程权重均为 1；缺少某类课程时，只对本次实际训练且有有效分数的课程重新归一化。这样命名/拟声不会因为课点多而压过配对/排序，配对/排序也不会因为同时出现在接受性语言维度而被重复计算。

报告仍显示五维雷达图；综合得分旁增加简短说明“按本次参与课程类型平衡计算”。公式版本升级为 `education-training-index-v2-teacher-rating`。

### 5.5 综合任务表现（原“任务正确率”）

纯粹的“正确率”只适用于配对/排序。为了满足所有课程参与，同时避免误导，建议把 UI 标签从“任务正确率”改为“综合任务表现”；API 暂时保留 `kpi.taskAccuracy` 兼容字段，并新增语义清晰的 `kpi.taskPerformance`。

计算方式：

- 配对、排序使用各自实际正确率。
- 命名、拟声、模仿使用教师评分归一化值 `T` 作为完成质量代理。
- 先在课程类型内部求平均，再对五类课程类型等权平均。
- 兼容字段 `taskAccuracy` 暂时返回同一数值，并在后续大版本移除。

### 5.6 全课程平均响应时长

- 配对、排序优先使用儿童端上报的每题响应数据；若只有 `avg_response_ms`，使用该窗口平均值。
- 命名、拟声、模仿使用“当前非 aux 课点开始播放/收到确认 → 教师首次请求下一步”的时长。
- 点击表扬时先冻结完成时刻，表扬视频时长和评分弹窗停留时长不计入儿童响应。
- 手动下一步使用点击时刻；自动游戏结束使用游戏指标，不使用 2 秒延迟。
- 先按课程类型求平均，再对有有效时长的课程类型等权平均。
- 报告同时返回 `sampleCount` 和 `coveredCourseTypes`；部分课程没有时长时显示覆盖情况，不把缺失值当 0 秒。

## 6. 配置调整

在 `config/report_scoring.yaml` 中新增并集中维护：

```yaml
schema_version: education-training-index-v2-teacher-rating

teacher_rating:
  min: 1
  max: 5
  scale: 20

interactive_course:
  accuracy_weight: 0.75
  response_weight: 0.25
  objective_weight: 0.70
  teacher_weight: 0.30
  ideal_response_sec: 3.0
  slow_response_sec: 12.0

dimension_weights:
  receptive:
    pairing: 1
    ordering: 1
    naming: 1
    onomatopoeia: 1
  expressive:
    naming: 1
    onomatopoeia: 1
  attention:
    automatic: 0.70
    mimic_teacher: 0.30

course_weights:
  mimic: 1
  naming: 1
  onomatopoeia: 1
  pairing: 1
  ordering: 1
```

代码提供相同默认值，配置缺字段时安全回退；旧的 `weights` 暂时保留一版用于历史兼容和回滚，但 v2 综合得分以 `course_weights` 为准。

## 7. 预计修改文件

| 文件 | 计划修改 |
|---|---|
| `teacher_frontend/components/ControlPage.tsx` | 保存 `questionId`；新增评分状态机、课点快照、响应时长冻结、统一切题入口和 ACK 处理 |
| `teacher_frontend/components/TeacherRatingDialog.tsx` | 新增独立评分弹窗组件与五档描述 |
| `app/sockets/events.py` | 注册 `teacher_rating_submit`，校验、调用服务并返回 ACK |
| `app/behavior/service.py` | 新增幂等的 `record_teacher_rating()`，触发摘要和报告刷新 |
| `app/behavior/timeline.py` | 聚合教师评分、五类课程得分、分层响应时长和数据质量标记 |
| `app/report/scoring.py` | 实现 v2 公式、缺失值重归一化和历史报告回退 |
| `app/report/service.py` | 输出课程分、`taskPerformance`、全课程响应 KPI 和覆盖信息 |
| `config/report_scoring.yaml` | 新增教师/客观权重、课程权重和 v2 公式版本 |
| `teacher_frontend/components/ReportPage.tsx` | 更新 KPI 标签/说明，必要时展示课程覆盖和评分来源 |
| `tests/test_teacher_rating.py` | 评分校验、幂等覆盖、窗口关联和持久化测试 |
| `tests/test_report_scoring_v2.py` | 五类课程、缺失项、历史数据、权重和响应时长公式测试 |
| `docs/TEACHER_RATING_REPORT_PLAN.md` | 持续更新实施状态、偏差、验证结果与最终变更记录 |

实际实施时如果无需拆出独立弹窗组件，可保留在 `ControlPage.tsx`，但数据状态机和视觉组件应保持逻辑分离。

## 8. 分阶段实施顺序

### P0：建立测试基线

- [x] 补最小 Python 测试目录和报告公式 fixtures。
- [x] 用行为窗口结构构造五类课程样例。
- [x] 固化旧报告缺少教师评分时仍可生成的兼容测试。

### P1：评分持久化

- [x] 实现 `record_teacher_rating()`。
- [x] 实现 Socket 请求、校验、ACK 和幂等覆盖。
- [x] 自动测试验证窗口 JSON 不覆盖 matching/sequencing/receptive 指标。
- [x] 评分写入后按“已有报告 refresh / 已有摘要 reaggregate”自动刷新。

### P2：教师端弹窗与统一切题

- [x] 保存 `questionId` 和课点开始时间。
- [x] 拆分 `requestAdvance` / `commitAdvance`。
- [x] 接入手动下一题、配对结束、排序结束、表扬视频结束、最后一题。
- [x] 实现重复事件合并、保存中禁用和失败重试。
- [x] 实现弹窗视觉、Esc 防误关和 Android 横屏五列布局；真实设备观感仍需人工验收。

### P3：报告公式 v2

- [x] 聚合五类课程教师评分和响应时长。
- [x] 配对/排序接入客观分与教师分加权。
- [x] 调整接受性语言和表达性语言。
- [x] 调整注意力维度、综合得分和 KPI。
- [x] 增加 `formulaVersion`、课程覆盖和缺失数据标记。

### P4：报告界面与回归

- [x] 更新报告 KPI 文案、响应覆盖和综合得分说明。
- [x] 评分刷新继续复用原有 PARTIAL/READY 报告生成与轮询契约。
- [x] 前端生产构建通过，横/竖版代码布局未出现类型或编译错误。
- [x] Python 测试、前端构建、Python 编译与差异检查通过。
- [ ] 连接真实 Flask-SocketIO 后端完成五条端到端人工冒烟（见 §9.1）。

## 9. 验收清单

### 9.1 教师端交互

- [ ] 手动点击“下一个”时不立即切题，只出现一个评分弹窗。
- [ ] 配对结束、排序结束和表扬视频结束均出现同一弹窗。
- [ ] 重复 `game_end/praise_video_ended` 不重复弹窗、不跳两题。
- [ ] 未选择分数不能继续；返回当前题不会切题。
- [ ] 保存成功后准确进入下一课点；最后一题保存后才出现完成确认。
- [ ] 保存失败时保留选择并可重试，不丢当前题。
- [ ] Android 横屏下五个选项完整可见且易于触控。

### 9.2 数据

- [ ] 每个已离开的课点都有唯一 `teacher_rating`。
- [ ] 重试同一课点只更新该评分，不产生重复记录。
- [ ] 配对/排序原有 accuracy、response time 不被评分写入覆盖。
- [ ] 表扬视频和评分停留时间不进入儿童响应时长。
- [ ] finalize 前后到达的评分都能 reaggregate 并刷新报告。

### 9.3 报告

- [ ] 配对/排序分同时受正确率、响应时长和教师评分影响。
- [ ] 接受性语言包含配对、排序、命名、拟声。
- [ ] 表达性语言只综合命名和拟声。
- [ ] 五类课程均能进入综合得分和综合任务表现。
- [ ] 平均响应时长按课程类型平衡，且展示有效覆盖。
- [ ] 缺少某类课程时权重重新归一化，不把缺失当 0。
- [ ] 旧训练没有教师评分时仍可查看报告，并显示限制说明。

### 9.4 自动化与本地验证命令

```powershell
python -m pytest tests/test_teacher_rating.py tests/test_report_scoring_v2.py
npm --prefix teacher_frontend run build
git diff --check
```

端到端冒烟至少各跑一次：命名/拟声的“表扬 → 评分 → 下一题”、手动下一题、配对自动结束、排序自动结束和最后一题完成报告。

## 10. 风险与处理

| 风险 | 处理 |
|---|---|
| 自动事件在弹窗期间重复到达 | 单实例 advance lock + 冻结快照 + ACK 后仅提交一次 |
| 评分时当前窗口已被下一题关闭 | 严格先保存后切题，并显式携带 questionId |
| `task_metrics.type` 被覆盖 | 使用独立 `teacher_rating` 桶和专用服务方法 |
| 旧报告没有评分 | 客观指标回退 + 缺失标记，不阻断历史报告 |
| 命名/拟声时长包含表扬视频 | 在表扬点击时冻结完成时刻 |
| 网络抖动导致教师无法继续 | ACK 超时提示、保留选择、一键重试；不静默跳题 |
| 不同课程题量差异导致偏置 | 两级聚合：类型内平均，类型间配置加权 |
| “正确率”用于主观评分语义不严谨 | UI 改为“综合任务表现”，保留兼容 API 字段 |

## 11. 实施状态与更新日志

| 日期 | 阶段 | 状态 | 说明 |
|---|---|---|---|
| 2026-07-12 | 审查与规划 | 已完成 | 核对切题入口、行为窗口持久化、旧能力分表、报告聚合与前端展示；确定 v2 公式和实施顺序 |
| 2026-07-12 | 评分持久化 | 已完成 | 新增 `teacher_rating_submit/ack`、逐窗口幂等评分、响应时长校验、摘要/报告自动刷新 |
| 2026-07-12 | 教师端交互 | 已完成 | 新增五级评分弹窗；统一手动、配对结束、排序结束、表扬结束切题状态机；ACK 后才切题 |
| 2026-07-12 | 报告公式 v2 | 已完成 | 五类课程类型平衡；配对/排序客观与教师加权；重算接受/表达/注意力、总分、任务表现和响应时长 |
| 2026-07-12 | 自动验证 | 已完成 | `pytest` 10 项通过；前端 Vite 生产构建通过；Python 编译与 `git diff --check` 通过 |
| 2026-07-12 | 浏览器视觉核查 | 受环境限制 | Codex 内置浏览器被本机策略阻止访问 localhost；未声称完成真实界面目测，保留 Android 横屏与真实 Socket 人工验收 |

### 11.1 本次实际修改文件

- `app/behavior/service.py`
- `app/behavior/timeline.py`
- `app/report/scoring.py`
- `app/report/service.py`
- `app/sockets/events.py`
- `config/report_scoring.yaml`
- `teacher_frontend/components/ControlPage.tsx`
- `teacher_frontend/components/TeacherRatingDialog.tsx`
- `teacher_frontend/components/ReportPage.tsx`
- `tests/conftest.py`
- `tests/test_teacher_rating.py`
- `tests/test_report_scoring_v2.py`
- `docs/TEACHER_RATING_REPORT_PLAN.md`

### 11.2 自动验证结果

```text
python -m pytest -q
10 passed

npm --prefix teacher_frontend run build
2495 modules transformed; build succeeded

python -m py_compile <本批次后端文件>
passed

git diff --check <本批次文件>
passed
```

已知非阻塞警告：现有 `app/behavior/models.py` 使用 `datetime.utcnow()` 产生弃用提示；Tailwind 现有 styles glob、Browserslist 数据版本和 Vite 大 chunk 警告均为本批次前已存在的构建提示。

## 12. 2026-07-12 首次进入重复音频与评分后断线修复

### 12.1 用户现场现象

- 教师端首次进入控制页，儿童端连续播放多次提问，随后还可能自动播放表扬。
- 点击下一题完成评分后，Flask 后端自动重启，Vite 报 `ws proxy error: read ECONNRESET`，教师端断线且无法完成切题。
- FunASR 报 `DefaultCPUAllocator: not enough memory`，单次尝试申请约 74GB。

### 12.2 根因

1. 初始自动播放先发送非 aux 内容，随后定时发送问题；非 aux ACK 更新 `trainingSessionId` 后使 React effect 再执行，形成第二次问题播放。
2. 真实语音分析器错误读取 `analyzers.yaml` 的 `sample_rate: 1` 作为 WAV 音频采样率。该字段实际是分析抽样频率，真实音频 Hz 应读取 `sample_rate_audio: 16000`；1Hz WAV 使 FunASR 推算出极长序列并申请巨型矩阵。
3. ASR 对每个 4096 样本短块独立启动一次 Paraformer，且缺少串行化与累积，容易并发堆积。
4. `RealSpeechMatcher` 旧逻辑直接把通用 ASR confidence 当作目标词匹配分；任意较长识别文本都可能超过阈值，误触发表扬。
5. 系统问题/提示/表扬音频被麦克风回采后仍进入 ASR，存在“系统自己回答自己”的反馈环。
6. `app.py` 固定 `debug=True`，Werkzeug reloader 在 FunASR/torchaudio 延迟导入时将 site-packages 误判为变化并重启；Vite `ECONNRESET` 是后端重启结果。

### 12.3 已落地修复

- [x] 当前课点的非 aux 内容请求按 `courseId/itemId/index` 幂等，只发送一次。
- [x] 问题语音改为只由首次 `play_resource_ack(questionId, isAux=false)` 触发一次。
- [x] ASR 音频采样率读取 `sample_rate_audio`，并限制在 8kHz～48kHz，异常配置回退 16kHz。
- [x] PCM 短块先累计约 2 秒再识别；推理锁保证同一模型串行执行；缓存最长 5 秒。
- [x] 真实语音匹配改为比较识别文本与当前目标文本，不再使用通用 confidence 直接判定成功。
- [x] 系统问题、提示、表扬播放期间暂停音频分析，播放结束后保留 0.75 秒尾音退避并清空 ASR 缓冲。
- [x] Flask debug 与 reloader 分离；默认两者关闭。调试可设 `FLASK_DEBUG=1`，热重载必须额外显式设 `FLASK_USE_RELOADER=1`。
- [x] 新增 `tests/test_audio_startup_regressions.py` 覆盖采样率、音频累积、真实文本匹配与 reloader 默认值。

### 12.4 验证

```text
python -m pytest tests/test_audio_startup_regressions.py tests/test_teacher_rating.py tests/test_report_scoring_v2.py -q
15 passed

npm --prefix teacher_frontend run build
2495 modules transformed; build succeeded

python -m py_compile <本次后端修复文件>
passed

git diff --check <本次修改文件>
passed
```

仍需真实设备确认：首次进入每个课点只播放一次问题；系统播音不会触发表扬；评分 ACK 后稳定切题且后端 PID 不变化。

后续每次实施必须在此表追加：修改文件、公式偏差、自动测试结果、手工验收结果及仍未完成项。
