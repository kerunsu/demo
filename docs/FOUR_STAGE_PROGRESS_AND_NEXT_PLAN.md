# 四阶段任务进度与下一阶段规划

> 依据 `docs/NEXT_STAGE_MONITOR_REPORT_MEDIA_ROBOT_PLAN.md` 整理。  
> 更新日期：2026-06-14  
> 当前分支：`codex/overnight-m1-m2`（以实际 `git branch` 为准）

本文档用于新对话接续：先对照本文件与规划原文，再决定优先修复、验收或扩展。

---

## 1. 四阶段总览

| 阶段 | 目标 | 总体状态 | 主要 commit（参考） |
| -- | -- | -- | -- |
| 阶段 1 | `/robot` 纯全屏表情屏 | **基本完成** | `33c72ae`、`aa5055c` |
| 阶段 2 | `/server` 实时监控与分析控制台 | **基本完成** | `94fce61` |
| 阶段 3 | 评估报告 V2（数据 + 评分 + 前端） | **基本完成** | `15be80a`、`188bf9f`、`bb8dcdf`、`f05a5b7` |
| 阶段 4 | 源音视频受控保存与服务端 manifest | **基本完成** | `f80beee` |

**结论：** 四阶段主链路已在代码层打通，当前缺口集中在**现场验收**、**真实 Provider 替换降级路径**、**运维与隐私策略落地**，以及少量**稳定性修补**（见下文「工作区未提交」）。

---

## 2. 阶段 1：`/robot` 纯表情屏

### 2.1 已完成（当前事实）

- `frontend/src/pages/RobotScreen.tsx` 已重构为纯全屏表情页，仅渲染 `RobotGifStage`，无工程按钮/诊断面板。
- 默认 idle 为 `eye`（对应 `001_Eye.gif` 资源映射）。
- WebSocket 驱动表情切换，播放结束回 idle；保留 `ANIMATION_STARTED` / `ANIMATION_FINISHED` ACK。
- 60 秒环境随机表情逻辑已实现，且有关键反馈动画时不抢占的设计意图（`ambientTimerRef`、adapter 状态）。
- 原 `/robot` 工程态信息已迁移至 `/server`（机器人端仅保留 `data-*` 属性供调试，不对儿童展示）。
- `e2e/training-loop.test.mjs` 覆盖双屏训练与机器人 ACK 主路径。

### 2.2 尚未完成 / 待验收

| 项 | 说明 | 标记 |
| -- | -- | -- |
| 真机全屏观感 | 机器人实体屏分辨率、GIF 加载延迟、首帧卡顿 | `MANUAL_ACCEPTANCE_REQUIRED` |
| 随机表情与关键反馈优先级 | 代码已有，需在真实训练节奏下目测 | `MANUAL_ACCEPTANCE_REQUIRED` |
| 浏览器自动播放策略 | TTS/预录音在机器人端浏览器的 unlock 行为 | `MANUAL_ACCEPTANCE_REQUIRED` |
| LAN 双主机 `/robot` | 儿童端与机器人端分设备时的 session 绑定与 WS 稳定性 | `MANUAL_ACCEPTANCE_REQUIRED` |

### 2.3 关键文件

- `frontend/src/pages/RobotScreen.tsx`
- `frontend/src/features/robot/gifAnimationAdapter.ts`
- `frontend/src/features/robot/RobotGifStage.tsx`
- `shared/src/animations.ts`

---

## 3. 阶段 2：`/server` 实时监控与分析控制台

### 3.1 已完成（当前事实）

- 路由与页面：`frontend/src/pages/ServerDashboard.tsx`，浅色主题样式对齐 `archive/prototypes/html/realtime_monitor_dashboard_prototype_light.html`。
- 聚合接口：`GET /api/monitor/session/:sessionId/snapshot`（`backend/src/services/monitorSnapshotService.ts`）。
- 前端数据层：`frontend/src/hooks/useMonitorSession.ts` — WebSocket 事件触发刷新 + 轮询兜底。
- 监控组件：注意力仪表、注意力曲线、逐题统计图、语音流水线（`frontend/src/features/monitor/`）。
- Snapshot 已扩展：`course.questionStats`、`currentQuestionPrompt`、`sessionDurationMs`、`attention.features`、`voice.totalTurnLatencyMs` 等。
- 双屏预览区：儿童端课程状态、机器人表情状态、事件时间线、服务健康、raw media 摘要。
- 测试：`backend/test/monitorSnapshotService.test.mjs`；`frontend/test/page-smoke.test.mjs` 含 server 相关断言。

### 3.2 尚未完成 / 待验收

| 项 | 说明 | 标记 |
| -- | -- | -- |
| 真实机器人摄像头推流到服务端 | 当前以本机预览 / descriptor 状态为主；snapshot 中已标注 | `MANUAL_ACCEPTANCE_REQUIRED` |
| Python Voice Service 健康探测 | `health.pythonVoiceService` 固定为待验收，未做真实 HTTP 探活 | 待实现 |
| LAN 服务端设备访问 `/server` | 页面在局域网教师/工程屏的可用性与性能 | `MANUAL_ACCEPTANCE_REQUIRED` |
| manifest 并发损坏导致 Snapshot 失败 | 根因已定位，修复已在工作区，**尚未 commit** | 见 §6 |
| 告警规则与运维联动 | 仅有事件列表，无分级告警策略/通知 | 建议下一阶段 |

### 3.3 关键文件

- `backend/src/services/monitorSnapshotService.ts`
- `backend/src/routes/monitorRoutes.ts`
- `frontend/src/hooks/useMonitorSession.ts`
- `frontend/src/services/monitorService.ts`
- `frontend/src/pages/ServerDashboard.tsx`

---

## 4. 阶段 3：评估报告 V2

### 4.1 已完成（当前事实）

- Schema 与类型：`ProfessionalReportV2`（`frontend/src/types/index.ts`、`backend/src/types.ts`）。
- 评分服务：`backend/src/services/reportScoringService.ts`  
  - 公式版本 `education-training-index-v1`  
  - 五维能力（排序、配对、接受性语言、注意力、表达性语言）+ 综合得分  
  - 逐题注意力曲线 `buildQuestionAttentionCurve`
- 行为聚合接线：注意力窗口、语言特征进入报告（`15be80a`）。
- 情绪汇总：`backend/src/services/emotionAggregationService.ts`  
  - `emotionProvider=none` 时正确降级为 `DEGRADED / MANUAL_ACCEPTANCE_REQUIRED`  
  - 启用启发式时输出三类占比（非临床结论）
- 叙事生成：`backend/src/services/reportNarrativeService.ts` — 独立 `REPORT_NARRATIVE_PROVIDER`（mock/openai/rule）、结构化 JSON 输出（analysis + 3 条 recommendations）、安全网关审查与规则 fallback。
- 前端展示：`frontend/src/features/report/ProfessionalReportV2Content.tsx`  
  - 雷达图、情绪条、注意力曲线、诊断与建议、Provider/降级标注  
  - 浏览器打印入口（`window.print()`）
- 多课程合并：`frontend/src/features/report/mergeProfessionalReport.ts`
- 联调修复：STT 语言观测容错、测试环境隔离（`f05a5b7`）。

### 4.2 尚未完成 / 待确认

| 项 | 说明 | 标记 |
| -- | -- | -- |
| 响应时长评分阈值 | 代码中 `PENDING_CONFIRMATION:RESPONSE_TIME_THRESHOLDS`，需产品负责人确认 | `待确认` |
| 真实 Emotion Provider | 浏览器 MediaPipe blendshape → `browser-emotion-v1`（`EMOTION_PROVIDER=local`） | `MANUAL_ACCEPTANCE_REQUIRED`（真机表情变化目测） |
| 真实 LLM 诊断叙事 | 代码已支持 `REPORT_NARRATIVE_PROVIDER=openai` + `OPENAI_API_KEY`；默认 mock，启用外部 LLM 需产品批准与安全走查 | `MANUAL_ACCEPTANCE_REQUIRED` |
| 常模/百分位表述 | 规划要求禁止未验证常模；需持续审查文案 | 持续合规 |
| 报告打印版式 | 有打印按钮，横竖版与分页需在浏览器实测 | `MANUAL_ACCEPTANCE_REQUIRED` |
| 端到端「训练→报告 V2」现场走查 | 自动化有单元/smoke，完整视觉验收不足 | `MANUAL_ACCEPTANCE_REQUIRED` |

### 4.3 关键文件

- `backend/src/services/reportScoringService.ts`
- `backend/src/services/emotionAggregationService.ts`
- `backend/src/services/reportNarrativeService.ts`
- `backend/src/services/reportService.ts`
- `frontend/src/features/report/ProfessionalReportV2Content.tsx`
- `professional_report_ver2.html`（视觉参考原型）

---

## 5. 阶段 4：源视频与音频保存

### 5.1 已完成（当前事实）

- 配置项（`backend/src/config/runtime.ts`）：  
  `RAW_MEDIA_PERSISTENCE`、`RAW_MEDIA_ROOT`、`RAW_MEDIA_RETENTION_DAYS`、`RAW_MEDIA_REQUIRE_CONSENT`、`RAW_MEDIA_ENCRYPTION`
- 默认 `RAW_MEDIA_PERSISTENCE=disabled`；开启后需 consent（`recordSessionMediaConsent`）。
- 持久化服务：`backend/src/services/rawMediaPersistenceService.ts`  
  - manifest 路径 `.runtime/media/{sessionId}/manifest.json`  
  - 音频 chunk/merged、视频 segment/merged/thumbnail
- 接入层：`mediaIngressService.ts`、`videoIngressService.ts`
- 前端采集：`browserAudioCapture.ts`、`browserCameraCapture.ts`（MediaRecorder 分片上传）
- 运维脚本：`tools/media-persistence/manage.mjs`（`diagnose` / `purge` / `delete` / `prepare-test-fixture`）
- `/server` 展示媒体存在性、字节量、缺失 chunk 数（不直接暴露敏感文件 URL）
- 测试：`backend/test/rawMediaPersistence.test.mjs`

### 5.2 尚未完成 / 待验收

| 项 | 说明 | 标记 |
| -- | -- | -- |
| manifest 并发写入损坏 | 高并发 chunk 写入可能导致 JSON 尾部重复；修复已在工作区 | 见 §6 |
| `RAW_MEDIA_ENCRYPTION` | 配置存在，**未实现**可选加密 | 待实现 |
| 保留策略现场演练 | `purge` 脚本已有，未做定期任务与验收记录 | `MANUAL_ACCEPTANCE_REQUIRED` |
| 按 session 删除审计 | `delete` 脚本已有，需与 SQLite session 生命周期对齐文档 | 待完善 |
| 机器人端 vs 儿童端采集分工 | 视频流来源策略需在双主机环境确认 | `MANUAL_ACCEPTANCE_REQUIRED` |
| 断线重连缺失 chunk | manifest 可标记 `missingSequences`，需现场断网复测 | `MANUAL_ACCEPTANCE_REQUIRED` |

### 5.3 关键文件

- `backend/src/services/rawMediaPersistenceService.ts`
- `shared/src/rawMedia.ts`
- `tools/media-persistence/manage.mjs`
- `frontend/src/features/camera/browserCameraCapture.ts`
- `frontend/src/features/voice/browserAudioCapture.ts`

---

## 6. 工作区未提交改动（接续时优先处理）

截至 2026-06-14，以下修复**已实现但未 commit**：

| 文件 | 内容 |
| -- | -- |
| `backend/src/services/rawMediaPersistenceService.ts` | manifest 容错解析、原子写入、session 级锁、`updateManifest` 统一读写 |
| `backend/test/rawMediaPersistence.test.mjs` | 损坏 manifest 自动修复测试 |

**影响：** 开启 `RAW_MEDIA_PERSISTENCE=enabled` 时，`/server` Snapshot 可能因损坏 manifest 报错；合并此修复后应恢复。

**建议 commit 信息（供参考）：**

```text
修复 manifest 并发写入损坏，恢复 /server snapshot 读取
```

---

## 7. 测试与构建基线（当前事实）

```bash
npm run build
npm test          # contracts + backend + frontend + e2e
git diff --check
```

- 后端测试：约 49 项（含 monitor、raw media、report scoring 等）
- 前端 smoke：`frontend/test/page-smoke.test.mjs`
- E2E：`e2e/training-loop.test.mjs`

规划中的「每阶段浏览器目视检查」(`/robot`、`/server`、儿童训练、报告 V2、LAN) 仍依赖人工。

---

## 8. 下一阶段建议（使项目更完善）

以下按**推荐优先级**排列，供新对话选取一个「波次」执行。

### 波次 A：稳定性与收尾（建议最先做，1–2 天）

1. **提交 manifest 修复**（§6），重启后端验证 `/server` Snapshot 正常。
2. **补齐 Python Voice Service 健康检查**：`/server` 中对 `tools/voice-service` 做轻量 HTTP ping，替换固定 `MANUAL_ACCEPTANCE_REQUIRED`。
3. **统一现场验收清单**：更新 `docs/LOCAL_REAL_PROVIDER_ACCEPTANCE.md` 或新建 `docs/FIELD_ACCEPTANCE_CHECKLIST.md`，勾选四阶段 MANUAL 项。
4. **响应时长阈值**：与产品确认后更新 `reportScoringService.ts` 常量，移除 `PENDING_CONFIRMATION` 标记。

### 波次 B：现场与双主机验收（2–3 天）

1. LAN 部署：服务端跑 backend + 静态前端，儿童端/机器人端分 URL 访问。
2. 验证 `/robot` 全屏表情、ACK、TTS 播放、60s 随机表情不抢关键反馈。
3. 验证 `/server` 实时曲线、语音流水线、双屏预览与事件时间线。
4. 验证报告 V2 自真实 session 生成，降级项展示正确。
5. 记录无法自动化项为 `MANUAL_ACCEPTANCE_REQUIRED` 并附截图/日志路径。

### 波次 C：媒体与隐私运维（2–3 天）

1. 在启用 persistence 的环境跑通：`consent → 采集 → manifest → diagnose → delete → purge`。
2. 将 `purge` 纳入运维手册（cron 或 `tools/` 包装脚本），与 `RAW_MEDIA_RETENTION_DAYS` 对齐。
3. 评估是否实现 `RAW_MEDIA_ENCRYPTION`（若项目负责人要求）。
4. 断线重连、缺失 chunk 复测并写入验收文档。

### 波次 D：Provider 与报告深化（按需，3–5 天）

1. **Emotion Provider 接口**：在保持默认降级前提下，接入真实或经批准的本地情绪模型；报告与 `/server` 同步 provider 元数据。
2. **LLM 叙事**：在 safety gateway 通过后接批准 LLM；保留规则 fallback。
3. **监控增强**：告警阈值（注意力骤降、STT 连续失败、媒体缺失 chunk）、可选导出 session 诊断包（不含 raw 媒体）。
4. **报告打印**：CSS `@media print` 打磨，对齐 `professional_report_ver2.html` 打印版。

### 波次 E：产品扩展（四阶段之外，待单独立项）

以下**不在**原四阶段规划内，若继续演进需单独 PRD：

- 新课程类型（如记忆/配对扩展关卡）
- 教师/家长长期档案与多 session 对比
- 真实机器人硬件控制（非 Web GIF）
- 儿童数据上云与正式隐私合规流程

---

## 9. 新对话推荐起手 Prompt

```text
请继续在仓库中推进四阶段后续完善工作。

请先阅读：
- AGENTS.md
- docs/NEXT_STAGE_MONITOR_REPORT_MEDIA_ROBOT_PLAN.md
- docs/FOUR_STAGE_PROGRESS_AND_NEXT_PLAN.md

当前状态：
- 四阶段主功能已基本完成（robot / server / 报告 V2 / raw media）。
- 工作区可能有未提交的 manifest 修复，请先 git status 并优先合并或提交。
- 下一阶段优先：波次 A（稳定性收尾）+ 波次 B（现场验收文档）。

边界：
- 不重新设计整体架构；
- 不添加真实 API key 或未经批准的云端儿童数据；
- mock/degraded 不得写成真实硬件通过；
- 每轮至少 npm run build && npm test && git diff --check。
```

---

## 10. 相关文档索引

| 文档 | 用途 |
| -- | -- |
| `docs/NEXT_STAGE_MONITOR_REPORT_MEDIA_ROBOT_PLAN.md` | 四阶段原始规划与验收标准 |
| `docs/FINAL_CAPABILITY_MATRIX.md` | Provider 与能力矩阵 |
| `docs/LOCAL_REAL_PROVIDER_ACCEPTANCE.md` | 真实 Provider 验收 |
| `docs/DEPLOYMENT_OPERATIONS_M7.md` | 部署与运维 |
| `docs/STABILITY_FIELD_ACCEPTANCE_M7.md` | 稳定性现场验收 |
| `docs/REPORT_SCHEMA.md` | 报告数据结构 |
| `docs/BEHAVIOR_ASSESSMENT_DATA_MODEL.md` | 行为与注意力数据模型 |
| `realtime_monitor_dashboard_light_style_guide.md` | `/server` 视觉规范 |
| `professional_report_ver2.html` | 报告 V2 视觉参考 |

---

## 11. 事实标签说明

- **当前事实**：仓库代码或测试可印证。
- **建议**：架构或排期推荐，未全部落地。
- **待确认**：需产品负责人或现场决策。
- **MANUAL_ACCEPTANCE_REQUIRED**：无法仅靠 CI 证明，需人工/真机验收。

---

## 12. 波次开发进度（`docs/四个波次开发计划.md`）

| 波次 | 状态 | 说明 |
| -- | -- | -- |
| 波次 0 稳定性 | ✅ | manifest 修复、Voice Service 健康探测 |
| 波次 1 真实注意力 | ✅ | browser-attention-v2、监控曲线、报告注意力维 |
| 波次 2 表达性语言声学 | ✅ | browser-web-audio 标量特征、50/50 评分、`/server` 响度/清晰度条、报告 languageSummary |
| 波次 3 LLM 交接 | ✅ | 黑盒 HTTP 对接：`tools/voice-partner/`、`VOICE_DIALOG_PROVIDER=partner`、页面上下文 text+截图、默认仍 `rule` |
| 波次 D 情绪 Provider | ✅（MVP） | 浏览器 MediaPipe Face Landmarker blendshape → `browser-emotion-v1`；`EMOTION_PROVIDER=local` 聚合帧级观测；`none`/`heuristic` 明确降级 |

### 波次 D 情绪 Provider 已落地要点（当前事实）

- `EMOTION_FEATURE_KINDS` 新增 `frame_emotion_scores` / `face_absent` / `emotion_unavailable`
- `shared/emotion-scoring`：`browser-emotion-v1` 将 MediaPipe blendshape 映射为愉悦/专注/急躁三类分数
- 浏览器 `browserCameraCapture` 在有人脸时调用 Face Landmarker，descriptor 附带 `emotionFeatures`（仅标量，不上传原始帧）
- `behaviorFrameIngressService` + `localEmotionObservationProvider` 写入 `EmotionObservation`
- `emotionAggregationService`：`EMOTION_PROVIDER=local` 从观测聚合三类占比；`none` → DEGRADED；`heuristic` 保留旧路径并标注 `degraded`
- `/server` `MonitorEmotionFeatures` 展示 provider / algorithmVersion / 三类占比；报告 `EmotionSummaryCard` 同步 provider 元数据

**验收备注**：真机表情变化与占比目测需现场验收（`MANUAL_ACCEPTANCE_REQUIRED`）；CI 已覆盖 blendshape 映射、聚合归一化、不足信号降级单测。

### 波次 2 已落地要点（当前事实）

- `LANGUAGE_FEATURE_KINDS` 新增 `audio_loudness_rms` / `audio_loudness_db` / `audio_speech_ratio` / `audio_clarity_proxy`
- 浏览器 `browserAudioCapture` 在 voice turn 结束时用 Web Audio 计算 RMS、dB、语音活动占比、清晰度代理（ZCR）
- `POST /api/behavior/:sessionId/voice-turns/:turnId/audio-features` 上报标量 descriptor（不走原始音频分析接口）
- `audioFeatureService` 写入 `LanguageObservation`；`behaviorAggregationService` 汇总声学指标
- `computeExpressiveLanguageScore`：文本 50% + 声学 50%（`EXPRESSIVE_TEXT_WEIGHT` / `EXPRESSIVE_ACOUSTIC_WEIGHT`）
- `/server` `MonitorAudioFeatures` 展示响度/清晰度条；报告 V2 `languageSummary` 标注 provider / algorithmVersion / degraded

**验收备注**：大声清晰 vs 小声含糊的差异需真机麦克风现场目测（`MANUAL_ACCEPTANCE_REQUIRED`）；CI 已覆盖标量计算与评分区分单测。
