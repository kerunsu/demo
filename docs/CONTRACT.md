# Demo 接口与行为契约

本文是独立 Demo 仓库的现行外部契约。课程只有 `mimic`、`pairing`、`ordering`；机械动作、Robot Runtime 和完整版本表情固定禁用。历史字段名只作兼容，不扩大产品能力。

## 稳定身份字段

跨 HTTP、Socket、时间线和报告的正式行为必须携带并校验：

- `sessionId`：连续媒体会话。
- `trainingSessionId`：一次训练。
- `requestId`：一次客户端请求和幂等键。
- `behaviorId`：一次课程输出行为。
- `questionId`：一次题目窗口。
- `courseId`、`itemId`：课程和课点标识。

旧 snake_case 字段在明确兼容入口可读；新输出使用 camelCase。身份不匹配必须拒绝，不能回退到“当前全局会话”。

## 房间与安全

Socket 只投递到明确房间：

- `session_<sessionId>_child`
- `session_<sessionId>_teacher`

未解析儿童端、过期会话或错误训练 ID 不得变成全局广播。教师控制租约决定谁可操作；旁观页面保持只读。重复、晚到、断线重连和取消必须幂等或返回明确错误。

教师端、儿童端和 Server 同源运行在 8080。Demo 没有 19091 参与方，不接受 DollSer/OSC 或 Robot Runtime 心跳作为就绪证据。

## 主流程

正式流程：

```text
登录 -> 选学生/预设/课程 -> prepare_training -> readiness
-> play_resource/互动题 -> 对话与分析 -> 教师评分
-> finalize_training -> 报告生成与审核
```

`prepare_training` 建立训练和连续媒体身份，但不提前播放课程内容。readiness 完成后才进入正式课程。取消 prepare/readiness 必须释放准备态且不污染下一次训练。

同一训练中切换课点只追加时间线，不重启连续录制。刷新儿童端后，`client_presence` 和 `child_sync_request` 用持久绑定恢复最后已提交内容。

## 课程范围

唯一有效课型来自 `config/demo_course_scope.json`：

- `mimic`：图片动作模仿与姿态识别。
- `pairing`：相同/配对互动。
- `ordering`：大小、长短、高矮、多少等规则排序。

课程目录、预设、配置 API、首次数据库、教师端选择、分析投影和新报告都必须按同一范围过滤。旧数据库其他课程行可保留用于历史数据，不得进入新训练或报告。

非法、缺失或尝试扩大的范围配置安全回退到上述三类。

## 课程资源与原子切换

`play_resource` 必须精确定向，并返回 `play_resource_ack`。儿童端使用 staging/commit 切换：

1. 在隐藏 staging 媒体加载和解码。
2. 成功后提交新内容并发送 `resource_ready`。
3. 失败发送 `resource_transition_failed`，旧内容保持可见。
4. 过期 token、旧会话或旧 request 不得覆盖已提交内容。

视频、图片、互动 iframe 和儿童屏动画遵守同一身份相关规则。互动 iframe 只能通过授权父页面桥接发送题目/点击事件。

## 模仿识别

模仿课展示动作图片，由真实姿态分析器和 matcher 比对。当前部署默认阈值为 0.50，允许镜像。问题开始、稳定命中、自动表扬和教师评分必须绑定同一 training/question/item 身份。

模仿话术只能引导儿童观察图片并完成身体动作，不得退化为命名、跟读或拟声，也不得声称机器人会示范动作。

## 配对与排序

配对/排序题目通过稳定 question ID 保持幂等。答案反馈不得截断正在朗读的题目；正确反馈完成后才能进入相应教师评分流程。

配对提问使用对应话术池。排序问题优先使用八类规则句，规则未知时才使用通用兜底。互动页面反馈、Server 状态、教师端评分和报告统计必须使用同一题目身份。

## 语音与对话

生产路径：

- 儿童回答：浏览器 SpeechRecognition 发送文本。
- 课程问题/反馈：浏览器 TTS。
- 服务端对话：规则或配置 provider 生成回复。
- 旧本地 WAV/STT 服务不在生产启动链中。

`robot_speak_text` 与 `robot_speak_ended` 是历史事件名，Demo 中含义是浏览器朗读，不代表机器人或硬件输出。语音命令携带 session/request/behavior/speech 身份；重复语音返回 duplicate/busy，不能覆盖活动语音。

教师可在当前精确会话中唤醒、关闭或查询儿童对话状态。命令不得改变录制状态，不得影响其他房间。儿童端持续回报浏览器麦克风、识别和 voice 状态。

## 儿童屏动画

`static/resources/Animations/*.mp4` 是允许的儿童鼓励动画。兼容 API：

- `GET /api/robot/animations`
- `POST /api/robot/animations/upload`
- `PUT /api/robot/animations/<name>/rename`
- `DELETE /api/robot/animations/<name>`

这些路径只管理儿童屏动画。引用中的动画拒绝普通删除；重命名同时更新 `course_map.json` 引用。随机回退只选择通过有界 MP4 检查的素材。

`course_map.json` 的 Demo 发布结构只允许 `animation` 和音频偏移，不允许 motion/emotion/expression。

## 禁用硬件契约

`config/demo_deployment.json` 中：

- `robotMotion=false`
- `robotExpression=false`
- `robotRuntime=false`
- `childAnimation=true`
- `browserSpeech=true`

代码对前三项 fail-closed；修改 JSON 不能启用。机械动作、完整版本表情、Runtime 下载/控制等兼容 HTTP 路径返回 HTTP 410 和：

```json
{
  "success": false,
  "error": "demo_capability_disabled"
}
```

`/robot`、`/robot/emotion`、`/robot/download` 同样不可用。机械和表情 Socket 装饰器不注册，`app/sockets/robot_events.py` 不进入 Demo。

`GET /api/robot/control/status` 可返回只读禁用状态，便于旧客户端识别能力；它不会暴露或连接硬件。

## 浏览器设备与录制

儿童摄像头/麦克风由浏览器持有。Server 的 `POST /api/v2/control/devices/check` 在无法代替浏览器授权时返回 `browser_permission_required`，不得误报 Robot Runtime 离线或伪造连接成功。

录制保持兼容文件名：

- `video.avi`
- `audio.wav`
- `timeline.csv`
- `session_meta.json`
- `archive_meta.json`

完整交互审计写入 `full_interaction_timeline.jsonl`，行为审计写入 `interaction_timeline.jsonl`。存储校验只读；上传、配置和元数据写入采用临时文件、`fsync`、原子替换。

## 报告

报告只按三课型计算并显示：

- 注意力 `attention`
- 配对 `matching`
- 排序 `ordering`

默认权重 34/33/33。缺失数据保持 null/数据不足，不把缺失当 0。报告生成是幂等读取准备；教师提交审核后状态稳定，不因轮询重复生成。

配对/排序的完成反馈进入评分；模仿使用姿态识别和教师评分证据。旧课程历史数据可以读，但不进入 Demo 新报告维度或课程列表。

## 现行 HTTP 面

主要接口：

- `/api/teacher/*`：登录和教师身份。
- `/api/students`、`/api/course-types`：学生与过滤后的课程目录。
- `/api/media/*`：连续媒体上行和状态。
- `/api/monitor/*`：连接、采集、分析和录制监控。
- `/api/server/status`：包含 `deployment=demo-machine` 与固定 Demo 能力集合，供启动脚本防止误复用完整版进程。
- `/api/config/*`：三课程、课点、预设、话术和内容配置；旧课型话术写入返回 400，旧文件音频条目配置返回 410。
- `/api/server/config/*`：分析器与报告配置文件。
- `/api/v2/capture/*`：额外 Server 设备配置。
- `/api/v2/control/*`：浏览器设备提示、录制目录和安全运维动作。
- `/api/v2/interaction/*`：InteractionProfileV2 草稿、发布和解析预览；未发布/非法/未命中回退 legacy。
- `/api/v2/config/sync/*`：不含敏感/禁用内容的可审查配置清单和导出。
- `/api/v2/timeline/*`：交互时间线和延迟诊断。
- `/api/report/*`：三课程报告与审核。

机器可读快照位于 `tests/fixtures/contracts/`，与运行时 URL/Socket 注册交叉验证。

## 错误、幂等与兼容

错误响应至少包含 `success=false` 和稳定 `error` 代码；不得只返回操作系统异常文本。常见状态：

- 400：字段/schema/范围非法。
- 401/403：未登录、无控制权或本机限制。
- 404：资源/会话不存在。
- 409：busy、重复冲突或状态不允许。
- 410：Demo 明确禁用的硬件能力。
- 503：允许能力的依赖尚未就绪。

`requestId` 重放应返回同一已知结果或明确 duplicate；不得重复播放、重复写评分或重复 finalize。新增字段优先向后兼容；删除/改名需要迁移期和 fixture 更新。
