# 下一阶段实施规划：实时监控、报告 V2、媒体保存与机器人表情屏

## 背景

当前项目已经完成真实 Provider 主流程、注意力观察、SQLite 持久化、真实 Provider 产品流验证等阶段性工作。下一阶段目标不是重新设计架构，而是在现有前后端、WebSocket、Provider、SQLite、评估报告和双屏机制基础上，补齐四个面向现场演示和产品验收的前端与数据闭环：

1. 新增 `/server` 实时监控与分析控制台；
2. 将评估报告展示升级到 `professional_report_ver2.html` 的视觉风格，并接入真实分析结果；
3. 设计并实现源视频、音频的受控采集与服务端保存；
4. 重构 `/robot` 为纯全屏表情屏，并把当前工程状态界面迁移到 `/server`。

本规划用于交给新对话继续实施。新对话应先审查现有代码和文档，再按本文件分阶段执行。

## 重要边界

- 不重新设计整体架构，沿用现有 Node 后端、React 前端、Python Voice Service、SQLite、WebSocket、Vosk、Piper、Local Attention Provider 的能力边界。
- 不添加真实 API key、token 或付费外部服务调用。
- 不默认保存儿童原始音视频；raw media 保存必须通过显式配置开关、同意记录、保留策略和删除机制。
- 不把缺失 Provider 的模拟结果描述成真实能力通过。
- 评分、诊断和教育建议必须标明公式版本、模型版本、Provider、数据质量和降级状态。
- 医疗/临床判断不能越界，报告措辞保持“教育训练参考”，除非项目负责人另行提供正式临床规范和审查意见。

## 参考文件

- `professional_report_ver2.html`
- `realtime_monitor_dashboard_light_style_guide.md`
- `archive/prototypes/html/realtime_monitor_dashboard_prototype_light.html`
- `docs/FINAL_CAPABILITY_MATRIX.md`
- `docs/LOCAL_REAL_PROVIDER_ACCEPTANCE.md`
- `docs/DEPLOYMENT_OPERATIONS_M7.md`
- `docs/STABILITY_FIELD_ACCEPTANCE_M7.md`
- `docs/BEHAVIOR_ASSESSMENT_DATA_MODEL.md`
- `docs/REPORT_SCHEMA.md`
- `docs/SPEECH_LLM_PIPELINE.md`
- `docs/VOICE_MODEL_INTEGRATION.md`
- `docs/ROBOT_ANIMATION_INTEGRATION.md`

## 当前能力与缺口

### 已有能力

- 前端已有儿童端、机器人端、报告页和课程训练流程。
- 后端已有 session、course、report、assessment、behavior、media、voice metrics、voice turn 等 API 边界。
- 已有 WebSocket 实时事件和机器人 ACK 机制。
- 已有注意力 descriptor / observation / aggregation 基础。
- 已有语音链路、Vosk/Piper 接入方向、voice metrics 和降级状态基础。
- 已有 SQLite 持久化能力。
- 已有报告数据结构和 deterministic assessment，但现有报告还不是 `professional_report_ver2.html` 风格，也没有完整接入五维能力、情绪、注意力曲线和 LLM 文本生成。

### 关键缺口

- `/server` 缺少统一的实时监控页面和聚合数据接口。
- 现有 `/robot` 仍偏工程状态页，不适合作为面向儿童/用户的机器人表情屏。
- 报告 V2 缺少后端数据契约、综合评分公式、五维能力计算、情绪识别接入、LLM 诊断文本生成和数据质量标注。
- 当前媒体入口倾向于不持久化原始音频/视频；如果要保存源音视频，需要显式改变隐私边界。
- 真实摄像头画面如果要显示在 `/server`，需要明确是本机预览、机器人端推流，还是服务端接收转发。

## 阶段 1：`/robot` 纯表情屏

### 目标

把 `/robot` 改成面向用户/机器人本体的全屏表情页，只显示中间表情，不显示工程状态、按钮或诊断信息。

### 实现要点

- 默认显示 `001_Eye.gif`。
- 收到表情切换事件时：
  - 切换到目标 GIF；
  - 按 manifest 中的 `expectedDurationMs` 播放一次；
  - 播放完成后自动回到 `001_Eye.gif`。
- 每 60 秒随机播放一个非 idle 表情，播放完回到 idle。
- 保留 WebSocket ACK：动画开始、播放完成、回 idle。
- 当前 `/robot` 中适合工程查看的内容迁移到 `/server`。

### 主要代码位置

- `frontend/src/pages/RobotScreen.tsx`
- `frontend/src/features/robot/gifAnimationAdapter.ts`
- `shared/src/animations.ts`
- 相关 CSS 文件

### 验收

- 打开 `/robot` 首屏只有全屏表情。
- 默认是 `001_Eye.gif`。
- 正确/错误/鼓励等事件触发表情后能自动回 idle。
- 60 秒随机表情不会覆盖正在播放的关键反馈动画。
- e2e 双屏同步测试仍通过。

## 阶段 2：`/server` 实时监控与分析控制台

### 目标

按 `archive/prototypes/html/realtime_monitor_dashboard_light_style_guide.md` 和 `archive/prototypes/html/realtime_monitor_dashboard_prototype_light.html` 实现 `/server` 页面，用于服务端设备或教师/工程人员查看实时分析过程。

### 页面内容

- 实时摄像头画面或安全预览；
- 实时注意力分数、数据质量、Provider 置信度；
- 双屏状态预览：儿童端课程状态、机器人端表情状态；
- 语音流水线：VAD/STT/脱敏/生成/Safety/TTS；
- 实时识别文本、脱敏后的输入、最终回答；
- 课程实时正确率、题号、响应时长、课程时长；
- 注意力变化曲线、逐题正确率与响应时延、语音流水线耗时；
- 事件时间线、告警、服务健康状态；
- Provider、模型、降级状态、SQLite/WebSocket/Voice Service 健康。

### 后端数据契约建议

新增或完善一个聚合接口：

```text
GET /api/monitor/session/:sessionId/snapshot
```

建议包含：

```ts
type MonitorSnapshot = {
  session: {
    sessionId: string;
    childAlias?: string;
    courseType?: string;
    startedAt?: string;
    state: string;
  };
  course: {
    currentQuestionIndex: number;
    totalQuestions: number;
    accuracy: number;
    averageResponseTimeMs: number;
    currentQuestionElapsedMs?: number;
  };
  attention: {
    currentScore?: number;
    currentQuality: "VALID" | "DEGRADED" | "MISSING";
    currentProvider?: string;
    questionWindows: Array<{
      questionId: string;
      score?: number;
      quality: string;
      startedAt: string;
      endedAt?: string;
    }>;
  };
  voice: {
    currentPipeline: Array<{
      stage: string;
      status: "pending" | "running" | "done" | "failed" | "degraded";
      latencyMs?: number;
      provider?: string;
      textPreview?: string;
      safetyStatus?: string;
    }>;
    latestTranscriptPreview?: string;
    latestModelInputPreview?: string;
    latestReplyPreview?: string;
  };
  robot: {
    currentAnimationId: string;
    isSpeaking: boolean;
    lastAckAt?: string;
  };
  health: {
    backend: string;
    pythonVoiceService: string;
    sqlite: string;
    websocket: string;
    vosk: string;
    piper: string;
    attentionProvider: string;
  };
  events: Array<{
    id: string;
    at: string;
    type: string;
    severity: "info" | "warn" | "error";
    message: string;
    detail?: string;
  }>;
};
```

### 实现步骤

1. 添加 `/server` 路由和 `ServerDashboard` 页面。
2. 抽取浅色主题 CSS 变量，按原型还原布局。
3. 后端先提供 snapshot REST 接口，再用 WebSocket 增量事件刷新。
4. 把当前 `/robot` 的工程状态、Provider 状态、事件时间线迁移到 `/server`。
5. 摄像头画面先做两档：
   - `MANUAL_ACCEPTANCE_REQUIRED`: 真实机器人端摄像头画面推送到服务端；
   - 默认安全模式：仅展示本机预览或 descriptor 状态，不持久化、不截图。
6. 增加页面 smoke/e2e 测试。

### 验收

- `/server` 在 LAN 服务端设备可访问。
- 页面无暗色控制中心风格，符合浅色医疗/教育管理视觉规范。
- 关键服务健康状态可见。
- attention、voice、course、robot、events 至少有真实数据或明确降级标记。
- 不把模拟数据伪装成真实数据。

## 阶段 3：评估报告 V2

### 目标

将现有报告展示升级为 `professional_report_ver2.html` 风格，并真正接入训练、注意力、语音、情绪和诊断建议结果。

### 报告必须呈现

- 综合得分；
- 五维能力分布图：
  - 排序；
  - 配对；
  - 接受性语言；
  - 注意力；
  - 表达性语言；
- 任务正确率；
- 平均响应时长；
- 主要情绪状态三类占比；
- 训练期间注意力波动曲线；
- 深度诊断报告；
- 教育干预建议；
- Provider、模型、数据质量、降级状态、公式版本。

### 评分建议

先实现可解释的教育训练指数，不声称临床常模或医学诊断。

```text
accuracyScore = correctRate * 100
responseScore = clamp(100 - normalizedLatencyPenalty, 0, 100)

排序能力 = 0.65 * 排序正确率得分 + 0.35 * 排序响应时长得分
配对能力 = 0.65 * 配对正确率得分 + 0.35 * 配对响应时长得分
接受性语言 = 0.45 * 全任务正确率得分 + 0.55 * 全任务响应时长得分
注意力 = 平均注意力分数 * 数据质量系数
表达性语言 = 语音有效性/相关性/完整度/安全通过率综合

综合得分 = 0.15 * 排序能力
        + 0.15 * 配对能力
        + 0.20 * 接受性语言
        + 0.25 * 注意力
        + 0.25 * 表达性语言
```

响应时长归一化建议从项目历史数据或产品负责人给出的合理阈值开始，未确认前必须在报告中标记 `待确认：响应时长评分阈值`。

### 情绪识别

新增 Emotion Provider 接口，输出至少三类占比：

- 愉悦/积极；
- 平静/专注；
- 急躁/挫败。

没有真实 provider 时，报告必须显示 `情绪识别：DEGRADED / MANUAL_ACCEPTANCE_REQUIRED`，不能用模拟值冒充真实结果。

### 注意力曲线

注意力分析窗口按题目对齐：

- 题目展示时打开 attention window；
- 答题完成或题目结束时关闭 window；
- 每题生成一个注意力 score；
- 报告曲线的 X 轴为题序，Y 轴为题目窗口 attention score；
- 缺失或低质量窗口要在曲线上标记。

### LLM 诊断与建议

深度诊断报告和教育干预建议通过语言模型生成，但必须经过安全网关：

- 输入只包含结构化指标，不传原始儿童隐私文本；
- 输出必须为模板化 JSON 或受控字段；
- 记录 provider、model、promptTemplateVersion、safetyReviewStatus；
- 失败时使用规则模板 fallback；
- 文案保持教育建议，不输出医学诊断结论。

### 实现步骤

1. 定义 `professionalReportV2` schema 和公式版本。
2. 后端聚合训练结果、attention windows、voice/language features、emotion summary。
3. 实现 scoring service，输出五维能力、综合得分和数据质量。
4. 实现 LLM report text generator，带 safety gateway 和 fallback。
5. 前端将 `professional_report_ver2.html` 改造成 React 组件，使用项目内 CSS 和图标，不依赖外部 CDN。
6. 保留打印/横竖版切换。
7. 增加报告 API 测试、公式单元测试、前端 smoke 测试。

### 验收

- 报告内容来自真实 session 数据，而不是静态模板。
- 五维能力、综合得分、注意力曲线、情绪占比、诊断建议均可追溯。
- 数据缺失时显示降级和缺失原因。
- 不出现“超过同龄段百分位”等未验证常模表述，除非有正式常模规则。

## 阶段 4：源视频和音频保存

### 推荐决策

保存到服务端设备，不保存在机器人前端本体。原因：

- 机器人端通常只运行前端页面，浏览器本地文件保存不稳定且难统一管理；
- LAN 服务端更适合做权限、索引、备份、删除、审计；
- 报告和验收日志也在服务端聚合，媒体 manifest 应与 session 数据同源。

### 推荐路径

```text
.runtime/media/{sessionId}/manifest.json
.runtime/media/{sessionId}/audio/{turnId}/chunk-0001.webm
.runtime/media/{sessionId}/audio/{turnId}/merged.webm
.runtime/media/{sessionId}/video/{streamId}/segment-0001.webm
.runtime/media/{sessionId}/video/{streamId}/thumbnail.jpg
```

`.runtime/media` 必须保持 git ignored。

### 配置建议

```text
RAW_MEDIA_PERSISTENCE=disabled|enabled
RAW_MEDIA_ROOT=.runtime/media
RAW_MEDIA_RETENTION_DAYS=7
RAW_MEDIA_REQUIRE_CONSENT=true
RAW_MEDIA_ENCRYPTION=optional
```

### 实现步骤

1. 扩展 media ingress，支持 raw audio/video persistence 开关。
2. 增加 session media manifest。
3. 前端 robot/child 页面按 session 建立音视频 stream。
4. 后端接收 chunk，写入服务端 `.runtime/media`。
5. 增加删除脚本、诊断脚本、验收日志字段。
6. 在 `/server` 和报告中只显示媒体存在性、路径摘要和数据质量，不直接暴露敏感文件。

### 验收

- 默认配置下不保存原始音视频。
- 开启配置并记录同意后，音视频保存到服务端路径。
- 断线重连后 manifest 能标记缺失 chunk。
- 诊断脚本能检查媒体路径、可写性、保留策略。
- 删除脚本能按 session 删除媒体。

## 建议执行顺序

1. `/robot` 表情屏重构。
2. `/server` 页面 shell 和当前工程状态迁移。
3. `/server` monitor snapshot API 和 WebSocket 增量刷新。
4. attention per-question window 对齐。
5. 报告 V2 schema 和评分公式。
6. 报告 V2 前端样式迁移。
7. 情绪识别 Provider 接口和降级显示。
8. LLM 诊断/建议生成和 safety fallback。
9. raw media persistence 配置、服务端保存、manifest、删除策略。
10. 统一测试、build、现场验收文档更新。

## 测试与验收要求

每个阶段至少运行：

```bash
npm test
npm run build
git diff --check
```

涉及页面的阶段需要额外进行浏览器可视化检查：

- `/robot`
- `/server`
- 儿童端训练流程；
- 报告 V2 页面；
- 双主机 LAN 访问。

不能自动完成的真实硬件项标记为：

```text
MANUAL_ACCEPTANCE_REQUIRED
```

## 可直接交给新对话的 Prompt

```text
请继续在仓库 D:\For Study\MyProjectRelated\Project\2026_DEMO_Robot\Project 中实现下一阶段功能。

请先阅读：
- AGENTS.md
- PROJECT_CONTEXT.md
- docs/TARGET_PRODUCT_REQUIREMENTS.md
- docs/SYSTEM_ARCHITECTURE_V2.md
- docs/DOMAIN_EVENTS.md
- docs/MULTI_AGENT_DEVELOPMENT_PLAN_V2.md
- docs/NEXT_STAGE_MONITOR_REPORT_MEDIA_ROBOT_PLAN.md
- professional_report_ver2.html
- realtime_monitor_dashboard_light_style_guide.md
- archive/prototypes/html/realtime_monitor_dashboard_prototype_light.html

上下文：
- 前一轮已经修复两个问题：
  1. 排序课程英文提示已改为中文；
  2. FINAL-B 后图标变问号的问题已修复，并给相机采样增加延迟以减少训练首帧卡顿。
- 前一轮已通过 npm test、npm run build、git diff --check。
- 当前有若干未跟踪的实时监控原型文件，请先确认状态，不要误删。

本轮目标：
按 docs/NEXT_STAGE_MONITOR_REPORT_MEDIA_ROBOT_PLAN.md 分阶段实施，优先顺序为：
1. 重构 /robot 为纯全屏表情页；
2. 新增 /server 实时监控页面 shell，并迁移当前 /robot 的工程状态信息；
3. 补齐 /server 所需的 monitor snapshot 数据接口；
4. 设计并实现报告 V2 的后端数据契约、评分公式和前端展示；
5. 再规划或实现 raw media persistence，注意默认不保存原始音视频。

边界：
- 不重新设计整体架构；
- 不添加真实 API key 或外部付费服务调用；
- 不把 mock/provider degraded 结果描述成真实硬件通过；
- raw media 默认 disabled，开启保存必须有配置、同意、保留和删除策略；
- 诊断/建议保持教育训练参考，不输出医学诊断结论；
- 每个阶段运行 npm test、npm run build、git diff --check；
- 不 push，不合并 main；如需要 commit，只做本地 commit。

请先检查当前 git 状态和相关文件，然后按阶段 1 开始实现。遇到真实设备或权限无法自动验证的项目，标记 MANUAL_ACCEPTANCE_REQUIRED。
```
