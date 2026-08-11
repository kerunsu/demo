# FEATURE_TRANSFER：注意力 / 表达性语言 / 报告 / Server 监控台迁移手册

> 来源仓库：`2026_DEMO_Robot/Project`（儿童教育互动训练本地 Web Demo）  
> 文档性质：`当前事实`（基于仓库代码与现有文档提炼，非未来设计）  
> 约束：本文仅描述迁移所需信息；**不修改业务代码**。  
> 目标读者：将同类能力迁入另一个独立项目的开发者 / AI Agent。

---

## 1. 功能目标

### 解决什么问题

在训练会话进行中与结束后，系统需要：

1. **注意力观测**：用摄像头低帧率视觉特征估计儿童是否面向屏幕（任务参与度代理指标，非临床注意力诊断）。
2. **表达性语言观测**：从语音转录文本特征 + 浏览器声学代理特征，估计表达活跃度与可听度（非语言障碍诊断）。
3. **分析 → 报告同步**：把题目窗口内的行为观测聚合为会话级指标，在课程完成后生成结构化报告。
4. **Server 监控台**：给运营/教师一个 `/server` 可视化界面，实时查看注意力、题目进度、语音管线、声学特征、摄像头预览等。
5. **实时同步**：监控台通过「WebSocket 事件触发 + HTTP Snapshot 轮询」保持与后端事实源一致。

### 最终用户看到 / 体验到什么

| 角色 | 体验 |
|------|------|
| 儿童端 `/child` | 训练时请求摄像头/麦克风；结束后看到报告页（五维雷达、注意力曲线、叙事文字等） |
| 运营端 `/server` | 输入 `sessionId` 后看到实时仪表盘：注意力环形表、折线、题目表现、语音流水线、声学条、摄像头预览；可跳转报告 |
| 机器人端 `/robot` | 本功能不依赖其展示报告；监控台仅显示其动画/说话状态摘要 |

**明确非声明（迁移时必须保留）：**

- 不做精确注视点追踪、临床注意力评分、表达性语言诊断、百分位或专业诊断结论。
- 报告边界为 `education_training_reference_only`。

---

## 2. 运行流程

### 2.1 总览链路

```text
[/child 训练]
  ├─ Camera: getUserMedia → MediaPipe/几何评分 → POST /behavior/.../camera/frames/:frameId
  │            → LocalAttentionObservationProvider → AttentionObservation 入库
  ├─ Mic/STT: 转录 → languageFeatureService → LanguageObservation(text_*) 入库
  ├─ Audio: Web Audio 特征 → POST /behavior/.../voice-turns/:tid/audio-features
  │            → LanguageObservation(audio_*) 入库
  ├─ Preview: 降采样 JPEG → POST /monitor/.../preview-frame（仅监控预览，不进评分）
  └─ 答题/出题域事件 → WebSocket 广播

[题目窗口编排]
  QUESTION_PRESENTED → 关闭上一题窗口 → aggregateQuestionBehavior → QuestionBehaviorSummary
  SESSION_ENDED / 报告前 finalize → aggregateSessionBehavior → SessionBehaviorSummary

[报告]
  POST /report/:sessionId/generate
    → finalizeSessionBehaviorBeforeReport
    → generateAssessmentForSession
    → buildExpandedAssessmentReport
    → computeReportDimensions (含 attention / expressiveLanguage)
    → ProfessionalReportV2 + narrative
    → SQLite / 内存持久化
  GET /report/:sessionId → 儿童端报告 UI

[/server 监控]
  useMonitorSession(sessionId)
    ├─ 每 1s GET /monitor/session/:sid/snapshot
    ├─ WS /ws?screenRole=operator → 收到任意 domain event 时立刻再拉 snapshot
    └─ useMonitorPreview → GET /monitor/.../preview/latest
```

### 2.2 注意力：用户操作 → UI

1. `/child` 开始训练后启动 `BrowserCameraCaptureController`。
2. 浏览器侧提取 `visualFeatures`（`facePresent`、`facingScore`、`headOrientation`、`imageQuality` 等），**默认不上传原始帧**（`rawFramePersisted: false`）。
3. `POST /api/behavior/:sessionId/camera/frames/:frameId`（schema `m5-frame-v1`）。
4. `receiveCameraFrameDescriptor` 做序列校验 → `ATTENTION_PROVIDER=local|mock` 观测 → `saveObservation`。
5. 监控台 `getMonitorSnapshot` 用 `deriveObservationAttentionScore` 填 `attention.currentScore` / `attentionSamples`。
6. 报告阶段用 `buildPerQuestionAttentionScores` + `computeReportDimensions` 得到 `dimensions.attention` 与 `attentionCurve`。

### 2.3 表达性语言：用户操作 → UI

三路汇入 `LanguageObservation`：

| 来源 | 触发 | 特征 kind 示例 |
|------|------|----------------|
| STT / 聊天脱敏文本 | `speechSttService` / `chatService` → `extractDeterministicLanguageFeatures` | `speech_presence`, `transcript_length`, `empty_response`, `stt_confidence`… |
| 浏览器声学 | `POST .../audio-features` | `audio_loudness_rms`, `audio_speech_ratio`, `audio_clarity_proxy`… |

聚合后进入 `ExpandedAssessmentReport.languageMetrics`；评分：

- 仅有文本：`computeTextExpressiveLanguageScore`
- 有声学信号：`0.5 * text + 0.5 * acoustic`（`EXPRESSIVE_TEXT_WEIGHT` / `EXPRESSIVE_ACOUSTIC_WEIGHT`）

### 2.4 分析 → 报告同步

| 时机 | 关键函数 | 结果 |
|------|----------|------|
| 下一题出现 | `onQuestionPresented` → `closeQuestionWindow` | 上一题 `QuestionBehaviorSummary` |
| 会话结束 / 生成报告前 | `finalizeSessionBehaviorBeforeReport` | 强制关窗 + 会话摘要 |
| `POST /report/:sid/generate` | `generateReport` | `TrainingReport`（含 `expandedReport` + `professionalReportV2`） |
| 前端完成课程 | `useCourseFlow` 调 generate + getReport | 跳转 `#report` |

**重要事实：** `ATTENTION_OBSERVATION_RECORDED` / `LANGUAGE_OBSERVATION_RECORDED` / `ASSESSMENT_UPDATED` / `REPORT_GENERATED` 在 `shared/src/domainEvents.ts` 与 `docs/DOMAIN_EVENTS.md` **有契约定义，但当前运行时未 publish**。报告同步走 **HTTP**，不走 WS 推送。

### 2.5 Server 界面与实时同步

1. 路由：pathname `/server` → `ServerDashboard`。
2. `sessionId`：URL `?sessionId=` 或 `localStorage.m3.activeSessionId`。
3. 数据：`MonitorSnapshot` 全量 HTTP 拉取；WS 只作「有事件就刷新」的触发器。
4. 摄像头画面：独立 preview 通道（TTL 约 3s），与行为评分 descriptor 分离。
5. WS 客户端：**无自动重连**；断线后仍靠 1s 轮询更新。

### 2.6 运行时实际会广播的域事件（与监控刷新相关）

`SESSION_STARTED`、`QUESTION_PRESENTED`、`ANSWER_SUBMITTED`、`ANSWER_EVALUATED`、`FEEDBACK_REQUESTED`、`ANIMATION_*`、`TTS_*`、`SESSION_ENDED` 等。  
注意力/语言观测本身**不**产生专用 WS 事件；监控台靠轮询看到新观测。

---

## 3. 涉及文件清单

### 3.1 shared（契约与可复用算法）

| 文件 | 作用 |
|------|------|
| `shared/src/behaviorObservations.ts` | Attention/Language/Emotion 观测与 summary 类型 |
| `shared/src/behaviorFrames.ts` | 摄像头帧 / 音频特征 descriptor |
| `shared/src/attentionScoring.ts` | `browser-attention-v2` 几何评分 |
| `shared/src/browserAudioFeatures.ts` | 浏览器声学特征提取 |
| `shared/src/assessments.ts` | 确定性评估结果类型 |
| `shared/src/domainEvents.ts` | 域事件类型（含未实现 publish 的观测/报告事件） |
| `shared/src/providers.ts` | Provider 接口与 Mock |
| `shared/src/monitorPreview.ts` | 监控预览帧 schema |
| `shared/src/emotionScoring.ts` | 情绪相关工具 |
| `shared/test/*attention*`, `*behavior*`, `*browserAudio*` | 契约/运行时测试 |

### 3.2 backend（采集、聚合、报告、监控 API）

| 文件 | 作用 |
|------|------|
| `backend/src/routes/behaviorRoutes.ts` | 行为帧 / 音频特征 HTTP |
| `backend/src/routes/monitorRoutes.ts` | snapshot + preview API |
| `backend/src/routes/reportRoutes.ts` | generate / get report / assessment |
| `backend/src/services/behaviorFrameIngressService.ts` | 帧 ingress + provider 选择 |
| `backend/src/services/localAttentionObservationProvider.ts` | 本地注意力 provider |
| `backend/src/services/languageFeatureService.ts` | 转录 → 语言特征 |
| `backend/src/services/audioFeatureService.ts` | 声学特征 → LanguageObservation |
| `backend/src/services/behaviorTimelineService.ts` | 题目观测窗口、去重 |
| `backend/src/services/behaviorTimelineOrchestratorService.ts` | 与课程生命周期绑定 |
| `backend/src/services/behaviorAggregationService.ts` | 题/会话级聚合 |
| `backend/src/services/behaviorObservationRepository.ts` | 观测仓储 |
| `backend/src/services/attentionScoreUtils.ts` | 观测→分数、逐题注意力 |
| `backend/src/services/assessmentService.ts` | 确定性评估 |
| `backend/src/services/reportService.ts` | 报告生成主流程 |
| `backend/src/services/reportScoringService.ts` | V2 五维评分（含 expressiveLanguage） |
| `backend/src/services/audioFeatureScoringUtils.ts` | 表达性语言声学子分 |
| `backend/src/services/reportNarrativeService.ts` | 叙事层 |
| `backend/src/services/reportNarrativeLlmProvider.ts` | 可选 LLM 叙事 |
| `backend/src/services/emotionAggregationService.ts` | 报告情绪摘要 |
| `backend/src/services/monitorSnapshotService.ts` | MonitorSnapshot 构建 |
| `backend/src/services/monitorPreviewFrameService.ts` | 预览帧 TTL 存储 |
| `backend/src/services/domainEventService.ts` | 事件持久化 + WS 广播 |
| `backend/src/services/realtimeHub.ts` | WebSocket hub |
| `backend/src/services/sessionService.ts` | 会话编排（热点；与课程强耦合） |
| `backend/src/services/speechSttService.ts` / `chatService.ts` | 语言观测写入入口 |
| `backend/src/services/sqlitePersistenceService.ts` | 报告/观测持久化 |
| `backend/src/config/runtime.ts` | 环境变量解析 |
| `backend/src/types.ts` | `TrainingReport` / `ProfessionalReportV2` / `ExpandedAssessmentReport` |
| `backend/src/index.ts` | HTTP/WS 入口（热点） |

### 3.3 frontend（采集、监控 UI、报告 UI）

| 文件 | 作用 |
|------|------|
| `frontend/src/pages/ServerDashboard.tsx` | `/server` 主界面布局 |
| `frontend/src/hooks/useMonitorSession.ts` | snapshot 轮询 + WS 触发刷新 |
| `frontend/src/hooks/useMonitorPreview.ts` | 预览轮询 |
| `frontend/src/services/monitorService.ts` | `MonitorSnapshot` 类型与 GET |
| `frontend/src/services/realtimeClient.ts` | WS 连接/心跳 |
| `frontend/src/services/monitorPreviewClient.ts` | 预览上传/读取 |
| `frontend/src/features/monitor/*` | 摄像头面板、注意力表/图、题目图、语音管线、声学条等 |
| `frontend/src/features/camera/browserCameraCapture.ts` | 摄像头采集控制器 |
| `frontend/src/features/camera/cameraFrameClient.ts` | 帧 POST |
| `frontend/src/features/camera/mediapipeFaceDetector.ts` | MediaPipe 人脸检测 |
| `frontend/src/features/camera/mediapipeFaceLandmarker.ts` | MediaPipe 情绪 landmarks |
| `frontend/src/features/voice/browserAudioCapture.ts` / `behaviorAudioClient.ts` | 声学采集与 POST |
| `frontend/src/features/report/ProfessionalReportV2Content.tsx` | 报告 V2 展示 |
| `frontend/src/features/report/CapabilityRadarChart.tsx` | 五维雷达 |
| `frontend/src/features/report/AttentionCurveChart.tsx` | 报告注意力曲线 |
| `frontend/src/features/report/mergeProfessionalReport.ts` | 多课程报告合并（本项目特有） |
| `frontend/src/hooks/useCourseFlow.ts` | 训练完成触发报告（业务包装） |
| `frontend/src/App.tsx` | 路由与摄像头接线（热点） |
| `frontend/src/styles.css` | `.server-dashboard` 等样式 |
| `frontend/src/types/index.ts` | 前端报告类型镜像 |

### 3.4 docs / 原型 / 测试

| 文件 | 作用 |
|------|------|
| `docs/BEHAVIOR_ASSESSMENT_DATA_MODEL.md` | 行为评估分层模型 |
| `docs/DOMAIN_EVENTS.md` | 事件契约（含未实现项） |
| `docs/REPORT_SCHEMA.md` | 报告 schema（偏 MVP v1） |
| `docs/API.md` / `docs/ENVIRONMENT.md` | API 与环境变量 |
| `docs/M5_ATTENTION_TECH_SPIKE.md` | 注意力技术说明 |
| `archive/prototypes/html/realtime_monitor_dashboard_*` | 监控台视觉参考 |
| `backend/test/behavior*.test.mjs`, `report*.test.mjs`, `monitor*.test.mjs`, `attention*.test.mjs`, `assessment*.test.mjs`, `realtime.test.mjs`, `api.test.mjs` | 后端单测/集成 |
| `e2e/training-loop.test.mjs` | 训练+报告+WS E2E |
| `frontend/test/page-smoke.test.mjs` | 页面 smoke |

---

## 4. 核心数据结构

### 4.1 行为观测（`shared/src/behaviorObservations.ts`）

- `BehaviorSchemaVersion = "m5-behavior-v1"`
- `AttentionObservation`：`observationType: "attention"`，features 含 `facePresent`、`facingScore`、`roughlyFacingScreen`、`headOrientation`、`imageQuality` 等；带 `dataQuality`、`algorithm`、`evidence`
- `LanguageObservation`：`observationType: "language"`，`features.kind` ∈ `LANGUAGE_FEATURE_KINDS`，`value: string | number | boolean`
- 聚合：`QuestionBehaviorSummary` / `SessionBehaviorSummary`（含 attention + language 子结构）

### 4.2 帧 / 音频 descriptor

**摄像头帧**（`behaviorRoutes` Zod，`m5-frame-v1`）：

```ts
{
  schemaVersion: "m5-frame-v1",
  sessionId, streamId, frameId, sequence, capturedAt, correlationId,
  questionId?, width, height, downsampled: true,
  frameHash, byteLength, mimeType, rawFramePersisted: false,
  visualFeatures?: { facePresent, faceCount, headOrientation, facingScore?, ... },
  emotionFeatures?: { positiveScore, focusedScore, frustratedScore, ... }
}
```

**音频特征**（`m5-audio-features-v1`）：

```ts
{
  schemaVersion: "m5-audio-features-v1",
  sessionId, turnId, correlationId, questionId?, observedAt, audioDurationMs,
  provider: "browser-web-audio" | "server-merged-audio",
  features: { loudnessRms, loudnessDb, speechRatio, clarityProxy, sampleCount, algorithmVersion, degraded }
}
```

### 4.3 报告

**API：**

- `POST /api/report/:sessionId/generate` → `{ reportId, sessionId, status: "READY" | "NARRATIVE_PENDING" }`
- `GET /api/report/:sessionId` → 完整 `TrainingReport`
- `GET /api/assessment/:sessionId` → `DeterministicAssessmentResult`

**`ProfessionalReportV2` 关键字段**（`backend/src/types.ts`）：

- `schemaVersion: "professional-report-v2"`
- `formulaVersion: "education-training-index-v1"`
- `scoreBoundary: "education_training_reference_only"`
- `dimensions`: `{ ordering, matching, receptiveLanguage, attention, expressiveLanguage }`
- `attentionCurve[]`, `attentionSummary`, `languageSummary`, `emotionSummary`
- `narrative`: `{ status: PENDING|READY|FAILED, analysis, recommendations, ... }`
- `dataQuality.limitations[]`, `versions.*`

**`ExpandedAssessmentReport`：** `answerMetrics` / `attentionMetrics` / `languageMetrics` / `safeExplanations` / `exportBoundary` / `degradation` 等。

### 4.4 MonitorSnapshot（`frontend/src/services/monitorService.ts`）

顶层：`session`, `course`, `attention`, `voice`, `emotion`, `robot`, `health`, `media`, `events`, `preview?`。

注意力区关键：`currentScore`, `currentQuality: VALID|DEGRADED|MISSING`, `features`, `questionWindows[]`, `attentionSamples[]`。

### 4.5 WebSocket 消息

```ts
// 连接: ws://host/ws?sessionId=&screenRole=operator&clientId=
{ type: "hello" | "heartbeat" | "event" | "error", ... }
// event.payload 为 DomainEvent
```

统一 HTTP 包装：`{ success, data, error }`（`backend/src/routes/response.ts`）。

### 4.6 配置项 / 环境变量

| 变量 | 作用 |
|------|------|
| `ATTENTION_PROVIDER` | `local` \| `mock` |
| `EMOTION_PROVIDER` | `local` \| `heuristic` \| `none` |
| `REPORT_NARRATIVE_PROVIDER` | `rule` \| `mock` \| `openai` \| `deepseek` |
| `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` 及对应 `*_REPORT_MODEL` | LLM 叙事（可选，需审批） |
| `MONITOR_PREVIEW_ENABLED` | 默认 true |
| `MONITOR_PREVIEW_MAX_FPS/WIDTH/HEIGHT/TTL_MS/MAX_BYTES/JPEG_QUALITY` | 预览参数 |
| `RAW_MEDIA_PERSISTENCE` | 影响报告注意力曲线是否排除无视频题 |
| `DEMO_STORAGE_PROVIDER` / `DEMO_SQLITE_DB_PATH` | 持久化 |
| `VITE_API_BASE_URL` / `VITE_WS_URL` | 前端 API/WS |

---

## 5. 核心组件 / 函数 / 类

### 5.1 可复用核心（优先迁移）

| 符号 | 位置 | 职责 |
|------|------|------|
| `scoreAttentionFromFaceGeometry` / `normalizeAttentionVisualFeatures` | `shared/src/attentionScoring.ts` | 面部几何 → 朝向分 |
| `extractBrowserTurnAudioFeatures` | `shared/src/browserAudioFeatures.ts` | 声学代理特征 |
| `extractDeterministicLanguageFeatures` | `languageFeatureService.ts` | 转录 → 多条 LanguageObservation |
| `aggregateQuestionBehavior` / `aggregateSessionBehavior` | `behaviorAggregationService.ts` | 窗口聚合 |
| `createQuestionObservationWindow` / `dedupeObservations` | `behaviorTimelineService.ts` | 时间窗与去重 |
| `deriveObservationAttentionScore` / `buildPerQuestionAttentionScores` | `attentionScoreUtils.ts` | 注意力数值化 |
| `computeDeterministicAssessment` / `generateAssessmentForSession` | `assessmentService.ts` | 评估 |
| `computeReportDimensions` / `computeExpressiveLanguageScore` | `reportScoringService.ts` | V2 评分 |
| `computeAcousticExpressiveScore` | `audioFeatureScoringUtils.ts` | 声学表达分 |
| `generateReport` / `buildExpandedAssessmentReport` | `reportService.ts` | 报告装配 |
| `generateReportNarrative` | `reportNarrativeService.ts` | 叙事 |
| `getMonitorSnapshot` | `monitorSnapshotService.ts` | 监控聚合视图 |
| `RealtimeHub` / `publishDomainEvent` | `realtimeHub.ts` / `domainEventService.ts` | 实时广播 |
| `connectRealtime` | `realtimeClient.ts` | 前端 WS |
| `useMonitorSession` | `useMonitorSession.ts` | 轮询+事件刷新模式 |
| Monitor 图表组件 + `monitorChartUtils` | `features/monitor/*` | 可视化 |
| Report 图表组件 | `features/report/*` | 报告可视化 |
| `BrowserCameraCaptureController` | `browserCameraCapture.ts` | 浏览器采集管线 |

### 5.2 当前项目特有包装（需适配，勿机械复制）

| 符号 | 原因 |
|------|------|
| `sessionService.ts` 课程状态机、matching/ordering 题库 | 业务课程绑定 |
| `behaviorTimelineOrchestratorService` 与 `QUESTION_PRESENTED` 绑定 | 依赖本项目事件名与题目 ID |
| `useCourseFlow` / `App.tsx` 接线 | 儿童端 UI 与路由特有 |
| `mergeProfessionalReportV2` | 多课程队列合并逻辑 |
| `inferQuestionCourseType`（`matching_`/`ordering_` 前缀） | 题 ID 约定特有 |
| Server 顶栏「打开 /child /robot」链接 | 三屏 Demo 产品形态 |
| `localStorage.m3.activeSessionId` | 本 Demo 会话键名 |
| 机器人动画 ACK 相关 monitor 字段 | 非报告核心，可裁剪 |

---

## 6. 可复用边界

### 可直接复制（小改 import/包名即可）

- `shared` 中 behavior / attention-scoring / browser-audio-features / assessments / monitor-preview 类型与算法
- 后端：ingress → provider → repository → timeline → aggregation → assessment → reportScoring → reportService 主链
- 前端：`useMonitorSession` 的「1s poll + WS 触发 refresh」模式
- Monitor / Report 纯展示组件（去掉本项目文案与路由后）
- 对应 `backend/test/*` 中不依赖课程素材的单测

### 需要重写或适配

- 会话生命周期：新项目用自己的 session/state machine 触发「开窗/关窗/finalize」
- HTTP 路由前缀、鉴权、CORS、API 包装格式
- 前端路由（不一定叫 `/server`、`#report`）
- MediaPipe CDN/模型 URL（离线环境需本地托管 wasm + tflite/task）
- SQLite schema / 持久化实现（可换成新项目存储）
- 报告叙事 LLM（默认用 `rule`/`mock`；外网需安全评审）
- 类型双份：`backend/src/types.ts` ↔ `frontend/src/types/index.ts` 应改为单一 shared 导出
- 域事件：若新项目要「观测/报告 WS 推送」，需**新实现 publish**，不能假设本仓已有

### 建议不要原样搬迁

- 整份 `App.tsx` / `sessionService.ts`
- 课程资源 `matching/`、`paixu/`、机器人 GIF
- 语音 partner 黑盒、Vosk/Piper（表达性语言文本特征可接任意 STT，但本仓接线是特有的）

---

## 7. 依赖项

### npm

| 包 | 用途 |
|----|------|
| `react`, `vite`, `typescript` | 前端 |
| `express`, `zod`, `dotenv` | 后端 API/校验 |
| `ws` 或 Node 原生 `WebSocket`（本仓 `realtimeHub`） | 实时 |
| SQLite 相关（本仓经 persistence 服务） | 报告/观测持久化 |
| `@mediapipe/tasks-vision` | 浏览器人脸/情绪 |
| workspace `child-education-training-demo/shared` | 共享契约（迁移时改为新包名） |

### 模型 / 静态资源 / CDN

- MediaPipe WASM：`cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@.../wasm`
- Face Detector：`storage.googleapis.com/mediapipe-models/face_detector/...`
- Face Landmarker：`.../face_landmarker/...`
- 监控/报告样式：主要在 `frontend/src/styles.css`；视觉参考见 `archive/prototypes/html/realtime_monitor_dashboard_light_style_guide.md`

### 浏览器权限

- **Camera**：注意力 + 监控预览
- **Microphone**：STT 与声学特征（表达性语言）

### 系统要求

- Node.js（前后端）
- 现代 Chromium 系浏览器（getUserMedia + Web Audio + WebSocket）
- 可选：本机 Python 语音服务（仅当沿用本仓 STT；迁移表达性语言文本路径时可替换）
- 局域网双机时注意 CORS / 防火墙 / `VITE_WS_URL`

---

## 8. 迁移步骤

1. **阅读新项目结构**：确认是否已有 session、WS、报告页、摄像头采集；标出插入点。
2. **先迁契约层**：拷贝/移植 `behaviorObservations`、`behaviorFrames`、`attentionScoring`、`browserAudioFeatures`、报告类型到新项目 shared。
3. **实现观测存储与时间窗**：repository + question window（开窗时机对齐新项目「题目开始/结束」事件，注意本仓「答完不关窗、下一题才关」）。
4. **接摄像头 ingress**：前端 descriptor 提取 → POST → local/mock attention provider → 入库。
5. **接语言特征**：至少接通文本路径；声学路径按需 POST audio-features。
6. **接评估与报告**：`finalize` → assessment → expanded → `computeReportDimensions` → 持久化 → GET API。
7. **接监控 Snapshot API**：从 session + observations + voice metrics 组装与本仓同构或精简的 snapshot。
8. **接 `/server` UI**：复用 monitor 组件 + `useMonitorSession` 模式；预览通道可选。
9. **接报告 UI**：雷达图、注意力曲线、narrative pending 轮询。
10. **配置环境变量**与权限提示；默认 `ATTENTION_PROVIDER=local`、`REPORT_NARRATIVE_PROVIDER=mock|rule`。
11. **移植/改写测试**：优先搬 scoring、aggregation、ingress、monitor snapshot 单测，再补新项目 E2E。
12. **安全审查**：禁止默认外发儿童音视频；报告文案避免诊断措辞。

---

## 9. 风险点

1. **契约已写、运行时未发**：不要假设 `ATTENTION_OBSERVATION_RECORDED` / `REPORT_GENERATED` 会推到 `/server`。
2. **题目窗口边界**：`onAnswerEvaluated` 不关窗；过早关窗会丢相机过渡帧、summary 偏短。
3. **表达性语言双路径**：漏传 audio-features 会改变 `expressiveLanguage`（纯文本 vs 50/50）。
4. **`RAW_MEDIA_PERSISTENCE=enabled` 时**：无视频捕获的题会从 `attentionCurve` 排除（`excluded_no_video`），与 monitor 实时曲线口径不同。
5. **叙事异步**：LLM provider 首次返回 `NARRATIVE_PENDING`，前端必须轮询至 `READY/FAILED`。
6. **WS 无自动重连**：仅靠轮询兜底；若新项目去掉轮询会「假死」。
7. **帧序列校验**：乱序/重复 `sequence` 会被 drop；多 tab 同 session 易踩坑。
8. **题 ID 前缀**：`matching_` / `ordering_` 影响维度拆分；新题 ID 需改 `inferQuestionCourseType`。
9. **前后端类型双份漂移**：`ProfessionalReportV2` 两处定义不一致会导致 UI 静默缺字段。
10. **MediaPipe 外网模型**：离线/内网环境加载失败 → 注意力降级，需本地镜像。
11. **session 键名**：`m3.activeSessionId` 是 Demo 约定，新项目勿硬依赖。
12. **Provider=mock**：报告 `limitations` 会出现 `ATTENTION_PROVIDER_DEGRADED_OR_MOCK`，验收时勿当真实信号。
13. **路径/挂载**：API 是否带 `/api` 前缀、WS 路径 `/ws`、静态资源 base，迁移时最易 404。
14. **热点文件冲突**：本仓 `App.tsx` / `index.ts` / `sessionService.ts` 多 Agent 易冲突；新项目也应划清 Owner。

---

## 10. 测试方法

### 单元 / 契约

```bash
# 本仓参考命令（迁移后改为新项目等价命令）
npm run test:contracts
node --test backend/test/behaviorFrameIngressService.test.mjs
node --test backend/test/behaviorTimelineAggregation.test.mjs
node --test backend/test/languageFeatureService.test.mjs
node --test backend/test/attentionScoreUtils.test.mjs
node --test backend/test/reportScoringService.test.mjs
node --test backend/test/monitorSnapshotService.test.mjs
node --test backend/test/realtime.test.mjs
```

覆盖点：无脸/多人脸/离屏/低质量；空转录/重复回答；有无声学混合评分；snapshot 字段完整性。

### 手动测试

1. 开 `/child` 授权摄像头+麦克风，同时开 `/server?sessionId=...`。
2. 确认监控台：注意力分数变化、samples 增长、预览非 stale、WS badge 在线、刷新来源在 poll/ws 间切换。
3. 完成课程 → generate report → 报告页五维与注意力曲线有值；关闭摄像头再跑一局，确认 `MISSING/DEGRADED` 与 limitations 可见。
4. 断网/关 WS：确认 1s 轮询仍更新（若保留该模式）。

### 端到端

- 参考 `e2e/training-loop.test.mjs`：训练 → 事件 → 报告 READY。
- 新项目应至少有一条：采集 → 观测入库 → snapshot 含 attention → generate → GET report 含 `dimensions.attention` 与 `expressiveLanguage`。

### 异常场景

| 场景 | 期望 |
|------|------|
| 拒摄像头 | dataQuality / currentQuality 降级，不把孩子标成「不专心」 |
| MediaPipe CDN 失败 | fallback 检测或 mock，报告带 limitation |
| 仅文本无声学 | expressiveLanguage 走纯文本公式 |
| 课程未完成 generate | API 错误 `Course not completed yet` |
| 重复 generate | 幂等/返回已有报告（按新项目策略实现） |
| 帧 sequence 乱序 | drop，不污染窗口 |
| LLM 叙事失败 | `narrative.status=FAILED` 或 rule_fallback，分数仍可用 |
| 预览 TTL 过期 | `preview.stale=true` |

### 迁移验收基线建议

```bash
npm run build
# 再跑与注意力/报告/monitor 相关的测试子集
git diff --check
```

---

## 给另一个项目 AI 使用的迁移 Prompt

将下方整段复制给目标仓库中的 AI Agent：

```text
你是代码迁移 Agent。任务：在【当前打开的新项目】中实现与源项目同类的能力：
（1）注意力观测与分析
（2）表达性语言特征分析
（3）行为分析到结构化报告的同步与报告生成
（4）运营监控台（数据可视化界面）
（5）监控台实时同步（WebSocket 事件触发 + HTTP Snapshot 轮询）

源项目已提供迁移手册：请先读取源仓库中的 `FEATURE_TRANSFER.md`（若用户附上了全文，以全文为准）。

【硬性流程——必须遵守】
1. 先只读探索【新项目】目录结构、技术栈、已有 session/API/WS/前端路由、状态管理与测试方式；输出简短「新项目现状摘要」与「插入点列表」。
2. 对照 FEATURE_TRANSFER.md 的「可复用边界」：能复用的算法/类型/模式按新项目包名与目录适配；不要整文件机械复制 App/sessionService/课程资源。
3. 不要假设源项目未实现的域事件（如 ATTENTION_OBSERVATION_RECORDED、REPORT_GENERATED）已经在推送；监控实时性优先复用「snapshot 轮询 + 任意 WS event 触发刷新」。
4. 报告必须保留教育训练参考边界，禁止临床/诊断措辞；默认不要启用外网 LLM/STT/TTS，不要上传儿童原始音视频，除非用户明确批准。
5. 实现顺序建议：shared 契约与评分算法 → 观测入库与题目时间窗 → 摄像头/语言 ingress API → assessment/report API → MonitorSnapshot API → 监控 UI → 报告 UI → 测试。
6. 每完成一个垂直切片就跑新项目既有的 build/test；补齐至少：评分单测、ingress/聚合单测、手动验收清单（摄像头拒绝、无声学、课程未完成生成报告）。
7. 若新项目已有冲突的数据模型或事件名，先提出适配方案再改代码，不要静默覆盖。
8. 输出时用中文，列出：改动文件、API/事件契约、环境变量、如何验证、以及相对源项目的刻意差异。

【功能验收标准】
- 训练过程中监控台能显示注意力分数/质量/样本趋势（允许约 1s 延迟）。
- 会话完成后可生成报告，包含 attention 与 expressiveLanguage 维度及数据质量 limitations。
- 关闭摄像头或 MediaPipe 失败时系统降级可见，而不是崩溃或给出诊断结论。
- 实时同步在 WS 断开时仍有 HTTP 轮询兜底（除非新项目明确改用纯 push 并实现重连+快照补差）。
```

---

## 附录：源项目快速定位

| 能力 | 入口 |
|------|------|
| 注意力采集 | `frontend/src/features/camera/browserCameraCapture.ts` |
| 注意力 ingress | `backend/src/services/behaviorFrameIngressService.ts` |
| 语言特征 | `backend/src/services/languageFeatureService.ts` |
| 报告生成 | `backend/src/services/reportService.ts` |
| V2 评分 | `backend/src/services/reportScoringService.ts` |
| 监控 Snapshot | `backend/src/services/monitorSnapshotService.ts` |
| 监控 UI | `frontend/src/pages/ServerDashboard.tsx` |
| 实时刷新 | `frontend/src/hooks/useMonitorSession.ts` |
