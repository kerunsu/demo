# Demo 配置与内容管理

本文描述独立 Demo 仓库的现行配置。机械动作、Robot Runtime 和完整版本表情不是可配置选项；儿童屏鼓励动画是另一类资源，允许保留。

## 事实源与优先级

关键事实源：

| 文件 | 作用 |
|---|---|
| `config/demo_course_scope.json` | 唯一允许课型：`mimic`、`pairing`、`ordering` |
| `config/demo_deployment.json` | 机械动作、完整版本表情、Robot Runtime 固定关闭；儿童动画和浏览器语音开启 |
| `config/runtime_modes.yaml` | 儿童媒体固定 `browser`、机器人控制固定 `disabled`，以及浏览器语速/唤醒词 |
| `config/course_presets.json` | 评估与干预两套独立三课程预设 |
| `config/report_scoring.yaml` | 注意力、配对、排序三个报告维度及权重 |
| `config/analyzers.yaml` | 模仿姿态、注意力和分析器参数 |
| `doll/data/course_map.json` | 儿童屏动画与音频时间偏移；不得出现 motion/emotion/expression |
| `static/courses.json`、`doll/data/courses.json` | 随仓库发布的三课程目录 |

课程范围或能力文件缺失、格式错误、尝试扩大范围时，代码必须安全收紧到 Demo 边界，不得启用上游能力。

一般配置优先级为：明确请求/会话值、持久化 YAML/JSON、环境变量、代码默认值。Demo 硬边界不参与覆盖；环境变量也不能重新启用机器人能力。

## 课程与预设

课程目录只发布：

- `mimic`：模仿识别
- `pairing`：配对
- `ordering`：排序

配置 API、教师端选择器、预设、首次数据库播种和新报告都会按相同范围过滤。旧数据库中的其他课程行为兼容历史数据，不会被删除，但不会出现在 Demo 新训练入口或新报告投影中。

`config/course_presets.json` 使用 schema v3。评估和干预预设各自保存选择状态；条目以稳定的课程/课点标识引用，不依赖本机数据库自增 ID。增删课程时必须同步两份静态目录、预设、数据库迁移和测试。

## 儿童媒体与语音

儿童媒体固定为浏览器模式。首次进入 `/child` 时浏览器必须允许摄像头和麦克风。Server 端设备页不能替浏览器授权，因此未连接儿童端时返回 `browser_permission_required`。

`config/runtime_modes.yaml` 可配置：

- `dialogue_wake_word_enabled`
- `browser_speech_rate`（范围 `0.5..2.0`，默认 `0.88`）

课程提问和反馈使用浏览器 TTS；儿童回答使用浏览器 SpeechRecognition。生产启动不自动拉起旧本地语音服务。

实时话术来自：

- `config/dialogue_phrases.yaml`
- `config/dialogue_phrase_selection.yaml`

Demo 运行时只消费模仿、配对、排序以及全局注意力/奖励话术。话术写接口会拒绝命名、拟声、社交等旧课型；旧文件音频条目接口固定返回 410。配对、排序的规则句与反馈池变更时要同步互动页面和自动化测试。

## 模仿识别与分析

`config/analyzers.yaml` 和示例文件共同记录可审查默认值。当前模仿姿态匹配阈值为 `0.50`，允许镜像动作。Windows 模型路径通过字节路径兼容处理，仓库内 `models/pose_landmarker_lite.task` 必须随发布存在。

配置中心算法页可编辑允许的分析器和报告参数。保存采用同目录临时文件、`fsync` 和原子替换；非法权重、阈值或 schema 返回明确错误，不部分写入。

儿童情绪/注意力观测属于分析数据，可进入监控和报告 KPI。它与完整版本的机器人表情素材、页面、协议和播放事件无关。

## 报告评分

`config/report_scoring.yaml` 只定义：

- `attention`
- `matching`
- `ordering`

默认权重为 34/33/33，总和必须为 100。课程权重只含 `mimic`、`pairing`、`ordering`。报告计算、叙事、教师端展示和 Server 报告编辑器必须保持同一范围。

配置更新不能改变已冻结历史报告；新计算使用新配置，并记录版本/来源。教师报告审核仍是幂等流程。

## 儿童屏动画

允许目录为 `static/resources/Animations/`，格式为 MP4。它用于儿童端全屏鼓励反馈，不属于机器人表情。

动画管理 API 由于兼容原因仍位于 `/api/robot/animations*`，但只读写儿童动画目录。课程映射中只允许 `animation` 与音频偏移；任何 `motions`、`emotion`、`expression` 输入在 Demo 生产路径都会被丢弃或拒绝。

以下内容不得进入 Demo 发布：

- `doll/Pose/`
- `doll/data/motions.json`
- `doll/data/emotions_meta.json`
- `static/resources/Emotions/`
- 机器人控制/表情页面和脚本
- 机械/表情 Socket 注册
- Robot Runtime 下载、启动和健康门禁
- DollSer 程序、动作工作台及硬件发布脚本

## 配置同步包

`GET /api/v2/config/sync/manifest` 和 `GET /api/v2/config/sync/export` 生成可审查配置清单/ZIP。Demo 导出包含：

- YAML/JSON/CSV 配置
- 三课程目录和课程预设
- 过滤后的 `course_map.json`
- 允许的课程媒体
- 儿童屏动画

导出明确排除数据库、学生个人数据、录制、报告、日志、环境密钥、机械动作、Robot Runtime 和完整版本表情。导入或从完整版本同步前，必须按 `docs/DEMO_SYNC.md` 人工复核边界。

## 数据库与环境变量

`database/app.db`、`.env`、录制和日志是部署数据，不是源码。首次没有数据库时标准播种创建三课程；已有数据库只原地迁移，不重置、不删除历史行。

常用环境变量（例如端口、对话 provider、是否自动构建教师端）继续按主项目兼容。以下变量在 Demo 不应作为部署配置使用：Robot Runtime 地址/密钥、DollSer/OSC 端口、机械动作模式或完整版本表情目录。即使遗留环境中存在，Demo 能力层仍固定关闭。
