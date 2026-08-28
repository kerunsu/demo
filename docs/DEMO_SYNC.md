# Demo 版同步、部署与验收规范

## 产品边界

本仓库是可独立克隆、安装、运行和升级的 Demo 机版本，不是完整版本目录中的一个子文件夹。当前永久边界如下：

| 能力 | Demo 规则 | 事实源 |
|---|---|---|
| 课程 | 只启用命名、排序 | `config/demo_course_scope.json` |
| 分析与报告 | 课程投影只统计和展示上述两类课程 | 同上；`app/report/` |
| 机械动作 | 不支持、不注册、不出现在配置或发布资源中 | `config/demo_deployment.json` |
| 屏幕表情 | 支持，与完整版本保持同步；只播放屏幕表情，不带机械动作 | 同上；`doll/data/emotions_meta.json` |
| Robot Runtime | 不启动、不作为健康门禁或部署步骤 | 同上 |
| 儿童屏幕动画 | 保留，用于儿童端鼓励反馈 | `static/resources/Animations/` |
| 语音 | 保留浏览器识别和浏览器 TTS | `config/runtime_modes.yaml` |

`app/robot/` 和若干带 `robot` 字样的字段属于既有课程输出契约兼容层，不表示 Demo 有机器人硬件。机械控制固定为 `disabled`，课程执行计划中只能出现音频/浏览器语音、儿童屏幕动画和屏幕表情。

## 从完整版本同步更新

完整版本与 Demo 必须在两个平级、独立 Git 工作树中维护。完整版本只作为只读参考；任何同步都在 Demo 分支完成，禁止整目录复制、重置数据库或覆盖录制数据。

通常可以同步：通用缺陷修复、采集和存储兼容、命名/排序交互、屏幕表情、浏览器语音、儿童页面、教师端通用体验、报告审核、数据库兼容迁移和安全修复。

必须人工合并并重施 Demo 约束：`app.py`、`app/sockets/events.py`、`app/robot/`、`app/routes/config_content.py`、`app/routes/config_sync.py`、`app/report/`、`teacher_frontend/components/ControlPage.tsx`、课程预设和课程目录。

禁止同步到 Demo 发布面：机械动作播放器和 Socket 注册、DollSer/OSC 输出、Robot Runtime 启动/下载/健康门禁、动作姿态 JSON 和 `motions.json`，以及配对、拟声、社交等非 Demo 课程的选择、统计与报告内容。表情文件可同步，但必须剔除其中的 motion/机械执行、19091 预热和 Runtime 依赖。

每次同步按以下顺序执行：

1. 分别检查两个工作树状态，记录完整版本基线；完整版本保持只读。
2. 对比最近更新，按文件和功能挑选与两门课程或通用平台相关的变更。
3. 先同步事实源和数据迁移，再同步后端处理，最后同步教师端/儿童端。
4. 重新核对两个 Demo JSON 事实源、固定 `disabled` 机械运行模式、两课程预设和无 motion 的 `course_map.json`。
5. 确认机械/Runtime 路由为禁用响应且机械 Socket 未注册；表情页面、素材 API、三级表情绑定、表扬随机池、四个回执事件和资产可用，配置导出包含表情但不包含动作。
6. 执行本文末尾全部自动化和人工验收；失败时不得发布。

## 全新拉取与运行

Windows 机器需要 Git、Python 和 Node.js LTS。克隆后进入仓库根目录，直接运行：

```powershell
.\start_server.ps1
```

引导脚本会补齐依赖、安装教师端依赖、在缺少 `database/app.db` 时运行 `database/seed_standard.py`，并创建仅含命名和排序的标准库。数据库、录制、日志和 `node_modules` 不进入 Git；课程目录、浏览器交互页面、语音配置和儿童动画必须随仓库提交。

启动后检查：教师端 `/teacher/`、儿童端 `/child`、Server `/server` 和表情屏 `/robot/emotion` 可打开；课程只显示命名、排序；教师端可以完成选课、互动、评分、报告审核；机械动作和 Robot Runtime 页面不可用。默认管理员仅用于首次本地进入，部署前必须修改默认密码。

## 发布验收

```powershell
python -m pytest tests -q
python -m py_compile app.py
python scripts/bootstrap.py --check-only
Set-Location teacher_frontend
npm.cmd ci
npm.cmd run build
```

还必须核对：

- 全新临时数据库可幂等播种，重复启动不会补回其他课程；旧数据库只原地升级，不删除历史记录。
- `/courses`、课程预设、配置目录和新报告课程投影只含 `naming/ordering`。
- 机械动作和 Runtime HTTP 入口返回明确的禁用状态，机械 Socket 未注册；旧音频条目接口返回 410。
- `static/resources/Emotions/`、`doll/data/emotions_meta.json`、表情页面/脚本与 `static/resources/Animations/` 进入发布并可播放；`doll/Pose/` 和动作清单不进入发布。
- 命名/排序完整反馈后进入评分，两类课程均可生成并审核报告。
- `git diff --check`、Python 编译、JavaScript 语法、教师端生产构建和完整测试集全部通过。
- 完整版本工作树状态与同步前记录一致，Demo 不引用完整版本的绝对路径、数据库、录制目录或构建产物。

Demo 不保留机械硬件输出、非活动课程或阶段性整改说明。少量为上游协议回归测试保留的兼容源码不进入启动、配置或发布链路；屏幕表情是 Demo 正式能力。本文件与 `AGENTS.md` 的 Demo 边界优先。
