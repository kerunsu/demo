# 第一阶段：渐进迁移施工图

## 1. 总原则

采用 strangler 路线：旧入口继续提供服务，新能力先以 adapter/shadow/feature flag 接入，任何新路径异常都回退旧实现；每个切片均有测试、日志、开关、回滚点和文档。禁止一次性重写 `app.py`、`events.py`、`handlers.py`、`analysis_service.py` 或 `robot_service.py`。

执行顺序固定为：

```text
现状基线 → contracts/装配骨架 → 门面单切片 → 采集/存储接口
→ readiness/preflight → 计算/对话端口 → 交互配置/资源库
→ 控制端可视化 → 灰度/回滚 → 清理冗余 → 交付验收
```

## 2. 阶段路线

| 阶段 | 目标 | 允许修改 | 退出条件 |
|---|---|---|---|
| P0 基线 | 固化 route、Socket、session、线程、关键行为 | 测试和 docs/refactor | 根 tests 通过；旧契约快照可追踪 |
| P1 contracts | 定义最小 DTO/Protocol、错误和事件 envelope | 新 contracts、适配器、测试 | 旧入口仍工作；无业务逻辑迁移 |
| P2 facade 切片 | 从一条低风险 route/event 开始接 use case | 单条 adapter + fixture | 新旧响应逐字段一致；开关可回退 |
| P3 采集/存储 | 抽 RecordingLifecycle、MediaIngest、Timeline、Track ports | 适配器和测试 | 主轨文件名/时间轴/补传一致 |
| P4 严格 preflight | 设备/模块 required 预检、原子开录、首帧/首块门禁 | 新 gate + flag | required 失败不开正式录制；旧模式可关闭 |
| P5 计算/对话 | 抽模型 registry、DialogueUseCase、SpeechCommand | provider adapter、shadow | 原有评分/话术/ASR/TTS 行为一致 |
| P6 交互资源 | EventCatalog、InteractionProfileV2、批量素材库 | 新 API/UI、legacy adapter | V2 未命中完整回退旧 course_map |
| P7 控制端/交付 | 设备、session/轨道、素材、交互四面板和文档 | 增量 UI/契约 | 三端旧呈现不变，新增能力可见可回滚 |

## 3. Preflight 迁移方案

当前 `prepare_training` 会启动 warmup，不能直接删除。新增 `PreflightOrchestrator` 时采用双模式：

- `legacy`：保持当前 warmup/就绪行为，作为默认回退和旧部署兼容路径。
- `strict`：先生成 training/media 标识和内存计划，不创建有效主媒体；发现/锁定所有 enabled+required 设备和模块，执行连接、格式、权限、磁盘、模型、ASR/TTS、课程资源检查及诊断缓冲首帧/首音频块验证；全部成功后通过 start barrier 原子启动正式轨道。

若 strict 预检、启动或首帧确认失败，必须释放已经打开的设备/线程，向教师端返回设备级错误，并且不发送成功的 readiness/课程开始信号。optional 设备可跳过但必须写入原因；required 设备不能降级为 optional。strict 只在部署开关打开且契约测试/真机验证通过后逐步灰度。

## 4. 动态设备与多轨施工方案

引入 `DeviceRegistry`、`DeviceDiscoveryPort`、`DeviceBroker`、`DeviceProfileSnapshot`，先包住当前 ambient 单例和 Runtime 注册，不改旧 `/api/monitor/ambient/*`。控制端新增设备配置 API 时，旧 API 继续返回旧字段。

- 设备有稳定 `deviceId`，session 轨道有稳定 `trackId`；角色包含 primary/child/environment/other，状态包含 enabled/required/optional/disabled。
- 开课时冻结 profile；训练中增删只对下一场生效；设备释放、重连、占用和权限错误可单设备定位。
- 主轨继续 `video.avi`、`audio.wav`；第一路 `primary_environment` 继续 `video.environment.avi`、`audio.environment.wav`；额外轨道只有在兼容测试确认后才采用 `trackId` 文件名。
- `session_meta.json` 增加版本化 `tracks[]`，记录设备、所有者、角色、文件、格式、时钟映射、首帧/首块、质量、缺口、结束状态；旧读取器忽略新增字段仍可工作。

## 5. 交互绑定和旧逻辑迁移方案

以课程为根建立 `CourseInteractionProfile`：`courseId → eventKey → sceneKey → lineId → speech/motion/expression/timing`。旧输入不改：`aux.question + courseType=naming` 由唯一 `LegacyInteractionAdapter` 归一化为 `question.naming`，同时先调用原 MappingResolver 得到真实 legacy candidate。

合成规则固定：

```text
legacy candidate
  + V2 disabled   = 完整 legacy
  + V2 inherit    = legacy 基础上只覆盖明确字段
  + V2 replace    = 通过完整校验后的 V2 全量替换
```

无 V2、草稿未发布、资源缺失、版本错误、解析异常都回到当前 legacy。每场 session 冻结 profile version；新增控制端只对草稿、预览和已发布新 session 生效。灰度顺序为 `legacy_only → shadow → draft_preview → 单课程 canary → published`。

## 6. 分析模型和语音端口

- 模型先实现 `ModelDescriptor/health/analyze/close` adapter，保留 mock/real 配置和原结果字段；错误输出 `degraded/no-data`，不伪造分数。
- 语音先统一 `DialogueRequest/DialogueResponse/SpeechCommand`，固定语音和 TTS 走同一原子行为命令，但保留当前 `robot_speak_text`、浏览器 TTS、文件音频、唤醒和 ASR pause 行为。
- 任何 provider/模型超时都有 timeout/cancel/health；新 provider 不可用时优先使用原 provider，无法回退时按 required/optional 明确阻断或降级。

## 7. 文档、开关与回滚

每一切片必须记录：开关名、旧路径、新路径、输入/输出差异、依赖、指标、日志字段、测试、启用范围和回滚方式。发布配置不可原地修改；运行 session 保存实际 profile/model/asset version。回滚只切回版本或关闭开关，不改写旧 `course_map.json`、旧 DB 或历史 session。

## 8. 下一阶段准确入口

下一阶段从 `shared contracts` 最小骨架和一个不改变响应的 facade adapter 开始，建议优先选择只读 `GET /api/server/status` 或 `GET /api/monitor/snapshot`。不要先改 `prepare_training`、`play_resource`、`robot_service` 或课程映射；这些必须在完整基线 fixture 和生命周期测试后再迁移。

## 9. 本阶段交付检查

- `tests/test_phase1_contract_surface.py` 已冻结关键 HTTP/Socket 表面、timeline 列和 MappingResolver 优先级。
- `tests/test_phase1_upload_contracts.py` 已冻结补传 checksum、archive_meta、session 路径 registry、重复 finalize 和晚到补传行为。
- `tests/test_phase1_http_contract_fixtures.py` 已冻结 8 条关键 HTTP 路由的成功字段及指定错误/边界形态；其中 course-types 的异常现状是 Flask HTML 500，并非统一 JSON envelope。
- `tests/test_phase1_runtime_contracts.py` 已交叉验证运行时 URL map、Socket handler 注册集合和服务端 literal emit 集合。
- `tests/test_phase1_golden_flow_and_isolation.py` 已串联教师登录、选生/选课、prepare warmup、真实 M1~M7 服务端检查、play/rating/finalize、报告生成/审核状态和 cancel，并冻结连续录制、child 定向、`teacher_rating_ack` 仅回请求者及课程行为 busy 时动作/表情不泄漏。
- 第一阶段新增测试无 `xfail`/skip；原 `tests/` 未删除、未放宽断言；最终交付命令结果记录在 `00-current-state.md`。
- 未移动业务代码、未迁移数据库、未改文件名、未更改现有产品行为。
- 任何下一阶段发现的基线差异先停止该切片，补充证据或回退，不得带病推进。
