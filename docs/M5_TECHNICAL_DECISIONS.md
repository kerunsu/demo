# M5 技术决策：行为观测与数据采集

本文记录 M5 第一版默认技术路线。状态标签：

- `CONFIRMED`：已由当前代码、既有文档或项目负责人决定确认。
- `DEFAULT_FOR_M5`：作为 M5 第一版默认方案，可在 Spike 后修订。
- `NEEDS_BENCHMARK`：需要实测或现场验证。
- `OWNER_REQUIRED_BEFORE_SCORING`：不阻塞采集，但阻塞 M6 正式评分。
- `CAN_DEFER`：可推迟，不阻塞 M5 主线。

## 决策表

| 主题 | 状态 | M5 决策 |
| -- | -- | -- |
| M4 进入 M5 条件 | `CONFIRMED` | M4 代码和自动化已完成，状态为 `COMPLETE_CODE_WITH_ENVIRONMENT_PENDING`；真实现场验收不阻塞 M5 规划和契约类实现。 |
| 摄像头采集方式 | `DEFAULT_FOR_M5` | 浏览器端负责摄像头权限、设备管理和低频采样；服务器端负责观测聚合与 Provider 编排。 |
| 图像或视频传输方式 | `DEFAULT_FOR_M5` | 第一版优先传输低帧率、低分辨率图像样本或 Mock frame descriptor；不传连续高清视频流。 |
| 采样帧率默认值 | `DEFAULT_FOR_M5` | 1-2 fps 起步，用于任务参与/朝向粗粒度观测；真实阈值需 benchmark。 |
| 分辨率默认值 | `DEFAULT_FOR_M5` | 160x120 或 320x240 起步，保留配置；不得以默认值承诺算法准确率。 |
| 行为推理服务部署位置 | `DEFAULT_FOR_M5` | 当前开发机暂视为高性能服务器；未来部署为机器人浏览器终端通过 LAN 访问服务器推理服务。 |
| 注意力定义 | `OWNER_REQUIRED_BEFORE_SCORING` | M5 使用“任务参与/粗粒度关注状态”工程语言；正式注意力能力定义和阈值需专业人员确认。 |
| 注意力候选算法 | `NEEDS_BENCHMARK` | 比较浏览器端轻量模型、低帧率图像到服务器、视频流、独立视觉推理服务；M5 不默认安装模型。 |
| 是否保存原始图像 | `CONFIRMED` | 默认不保存原始图像、连续视频帧或视频文件；调试短期缓存必须显式开启且不得进日志。 |
| 观测保存粒度 | `DEFAULT_FOR_M5` | 保存窗口化观测、题目级汇总、会话级汇总、数据质量、算法版本和证据引用；高频中间状态只进内存环形缓冲。 |
| 语言特征范围 | `DEFAULT_FOR_M5` | 优先确定性特征：是否回应、响应时延、音频时长、Transcript 长度、置信度、空响应、重复、提示前后变化。 |
| 是否保存 Transcript | `DEFAULT_FOR_M5` | 默认保存脱敏 normalized transcript、长度、hash、置信度和质量标记；是否长期保存完整脱敏文本需产品确认。 |
| 相关性分析方式 | `DEFAULT_FOR_M5` | 通过可替换 Provider 产生相关性/完整度等模型或规则特征；记录 provider/model/rule version、confidence、evidence 和降级状态。 |
| 数据窗口 | `DEFAULT_FOR_M5` | 至少支持语音 turn 窗口、题目窗口、提示前后窗口、课程/session 窗口。 |
| 数据质量阈值 | `OWNER_REQUIRED_BEFORE_SCORING` | 工程侧先记录 low confidence、missing device、partial、timeout、manual override；哪些质量可评分由专业人员确认。 |
| 算法版本 | `CONFIRMED` | 每条观测和汇总必须记录 `algorithmVersion`，规则类特征必须记录 `ruleVersion`。 |
| 专业评分边界 | `CONFIRMED` | M5 不输出正式能力分数、常模、百分位或诊断；这些进入 M6。 |
| 最大可接受处理延迟 | `NEEDS_BENCHMARK` | M5 先记录端到端行为管线延迟；第一版不承诺现场上限。 |
| 外部云视觉服务 | `CONFIRMED` | 禁止默认发送真实儿童原始图像、视频帧或视频流到外部云视觉服务。 |
| LLM 评分 | `CONFIRMED` | LLM 不得自由生成核心定量分数；M5 的模型类语言特征只作为可追溯输入。 |

## 注意力技术路线比较

| 方案 | M5 评价 | 默认用途 |
| -- | -- | -- |
| 浏览器内轻量人脸/头部检测 | 隐私强、低带宽，但浏览器 CPU 压力和模型分发复杂。 | Spike 候选，不作为默认主链路。 |
| 浏览器采集并发送低帧率图像到服务器 | 可测试、可控、便于服务器统一聚合；需严格不落盘。 | M5 v1 推荐骨架。 |
| 浏览器传输视频流到服务器 | 图像连续性好，但带宽、隐私和性能风险高。 | 暂缓，除非低帧率不足。 |
| 服务器独立视觉推理服务 | 最利于模型替换和多机器人扩展；部署复杂度更高。 | Provider 边界预留，真实模型进入 Spike。 |

第一版推荐：低帧率图像/Mock descriptor 到服务器侧 Provider，窗口化保存。升级到真实模型前必须完成 benchmark、隐私确认和现场光照/遮挡测试。

## 普通摄像头能力边界

建议：普通摄像头第一阶段只能可靠地支持人脸是否存在、人脸数量、粗粒度头部朝向、是否大致朝向交互屏、图像质量和置信度等工程观测。不得描述为精准眼动追踪，不得推断临床注意力障碍。

## 语言表达技术路线

确定性特征直接从 M4 数据获得：

- M4 media ingress：音频段、时长、turn metadata。
- M4 STT：Transcript、confidence、language、provider metadata。
- M4 transcript normalization：空结果、重复、低置信度、PII redaction。
- M4 voice observability：阶段耗时、provider、model、错误、降级。

模型/规则特征必须走 Provider：

- `LanguageFeatureProvider` 或等价接口。
- 输入为脱敏 transcript、题目上下文、提示事件和最小必要证据。
- 输出为 feature、value、confidence、rule/model version、evidence refs、quality。
- 失败时输出 degraded/missing，不伪造分数。

## 数据保留

进入数据库或未来 Repository：

- observation/window/summary。
- provider/model/rule/algorithm version。
- data quality。
- evidence references。
- hashed/redacted transcript metadata。

仅保存在内存：

- 高频逐帧状态。
- 短期图像质量估计中间值。
- 最近窗口缓冲。

不允许默认保存：

- 原始连续视频。
- 原始摄像头帧。
- 原始音频。
- 未脱敏敏感文本。
- 真实 API key 或外部 provider 完整错误响应。

## M6 前必须由专业人员确认

- 注意力/任务参与度定义和阈值。
- 语言表达正式维度、评分规则和年龄段差异。
- 题目相关性、表达完整度、信息丰富度等模型类特征是否可进入评分。
- 缺失摄像头、低置信度、多人干扰时的评分策略。
- 报告措辞、禁用词、常模/百分位来源。
