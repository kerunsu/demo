# Demo 运维、发布与回滚

本文只描述无机械结构 Demo 机的现行运维流程。屏幕表情属于本仓库；机械动作和 Robot Runtime 不属于 Demo 能力，同步规则见 [Demo 同步规范](DEMO_SYNC.md)。

## 运行边界

- 课程固定为命名、排序。
- 儿童端固定使用浏览器摄像头、麦克风、语音识别和 TTS。
- 允许儿童屏鼓励动画 `static/resources/Animations/`。
- 不启动或探测 19091，不连接 DollSer/OSC，不下载机器人包。
- 发布 `emotions_meta.json` 和 `static/resources/Emotions/`，不发布 `doll/Pose/` 或 `motions.json`。
- 报告只展示命名、排序两门 Demo 课程及注意力、表达性语言、接收性语言、排序四个评分维度；儿童情绪观测与屏幕表情输出是两套独立数据。

这些边界由 `config/demo_course_scope.json`、`config/demo_deployment.json` 和代码中的 fail-closed 校验共同保证。编辑 JSON 也不能启用被禁止的硬件能力。

## 首次部署

Windows 机器安装 Git、Python 3.10+ 和 Node.js LTS 后，克隆独立 Demo 仓库并在根目录运行：

```powershell
.\start_server.ps1
```

引导程序会检查 Python/npm 依赖、教师端依赖和课程资源；首次没有 `database/app.db` 时创建仅含两门课程的数据库。它不会覆盖已有 `.env`、数据库、录制或日志。

启动脚本只复用 `/api/server/status` 明确返回 `deployment=demo-machine` 的 8080 服务。若端口被完整版或其他项目占用，脚本会停止并提示；两版不能连接到同一个后端进程。

启动后验证：

1. `http://127.0.0.1:8080/teacher/` 可登录。
2. `/child` 可打开并允许摄像头和麦克风。
3. `/server` 可查看浏览器端连接、录制和分析状态。
4. 课程选择、预设和配置目录只出现命名、排序。
5. `/robot/emotion` 可打开并显示默认表情；`/robot`、`/robot/download` 明确返回 Demo 能力禁用。
6. 完成两类课程后可以评分、生成报告并提交审核。

只读环境检查：

```powershell
.\start_server.ps1 -CheckOnly
```

`-CheckOnly` 不创建首次数据库，因此新机器的第一次部署应运行正常启动命令。

## 摄像头、麦克风与录制

默认摄像头和麦克风由儿童端浏览器持有。Server 不能替浏览器授予权限；设备页显示“等待儿童端浏览器授权”是未开儿童端时的正常状态，不是 Robot Runtime 故障。

正式训练使用一个连续媒体会话。切换课点只追加 `timeline.csv`，不会重启录像。稳定文件名和目录规则见 [数据格式](DATA_SCHEMA.md)：

- `video.avi`
- `audio.wav`
- `timeline.csv`
- `session_meta.json`
- `archive_meta.json`
- `interaction_timeline.jsonl`
- `full_interaction_timeline.jsonl`

不要手工改名、移动或自动修复历史会话。控制台的本机打开、上锁和删除操作仍受路径校验与本机访问限制。

## 健康检查与发布门禁

每次发布运行：

```powershell
python -m pytest tests -q
python -m compileall -q app database scripts app.py
python scripts/bootstrap.py --check-only
Set-Location teacher_frontend
npm.cmd ci
npm.cmd run build
```

同时执行 `git diff --check`，检查所有改动 JavaScript 的 `node --check`，并按 [测试指南](TESTING.md) 完成无硬件浏览器冒烟。

发布前还要确认：

- 全新临时数据库重复播种后仍只有两类课程。
- `config/course_presets.json` 的评估/干预预设只引用两类课程。
- 配置同步 ZIP 不含数据库、录制、日志、机械动作或 Robot Runtime；包含屏幕表情。
- 机械 Socket 未注册，禁用 HTTP 路径不会返回伪成功；表情四个回执事件已注册。
- 命名、排序训练中的浏览器采集与注意力分析可用。
- 教师端生产构建产物能够由 Flask 同源提供。

## 安全升级

1. 备份 `database/app.db`、`.env`、课程自定义配置和 `static/recordings/sessions/`。
2. 确认当前没有训练、录制或报告审核正在进行。
3. 拉取独立 Demo 分支；不要从完整版本目录整树覆盖。
4. 运行测试、构建和 `-CheckOnly`。
5. 启动唯一一个 8080 服务实例并完成两课程冒烟。
6. 只使用现有迁移原地升级数据库，绝不通过删库解决结构差异。

从完整版本同步时必须逐文件审查，重新应用 Demo 课程和能力边界，详见 [Demo 同步规范](DEMO_SYNC.md)。

## 备份与回滚

备份至少包含：

- `database/app.db`
- `.env`
- `config/` 中部署配置
- `static/recordings/sessions/`
- 经审核的课程媒体和儿童动画

回滚代码时同时恢复与该版本匹配的配置；数据库只能使用兼容迁移或经验证的备份，不重置历史数据。存储校验器保持只读。

## 故障定位

应用日志为 `logs/app.log`。按 `sessionId`、`trainingSessionId`、`requestId`、`behaviorId` 关联以下证据：

- `play_resource 收到`、`play_resource_ack`：课程投递和回执。
- `resource_ready`、`resource_transition_failed`：儿童端原子切换。
- `teacher_rating_submit`：教师评分。
- `finalize_training`、报告审核状态：结束与报告流程。
- 浏览器控制台的权限错误：摄像头、麦克风或浏览器语音问题。

不要把儿童情绪分析日志当成屏幕表情事件。表情回执只有 `robot_emotion_ready/started/ended/auto_random`；机械动作不存在播放回执。接口和事件的现行约束见 [契约](CONTRACT.md)。

## 多进程与数据安全

教师控制租约和课程行为锁仍用于避免重复操作。多主机部署需要共享协调后端；本地文件锁只覆盖同一台 Server。所有配置写入使用同目录临时文件、`fsync` 和原子替换，数据库/录制/日志不进入源码提交。
