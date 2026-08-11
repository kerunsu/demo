# 部署对照：后端主机 vs 机器人端

## 三机拓扑（生产）

| 机器 | 运行内容 |
|------|----------|
| **后端主机** | `python app.py`（`:8080`）；分析器默认 **Real**；`CHILD_MEDIA_MODE=agent` |
| **机器人 Windows** | `RobotRuntime.exe`（采流 + OSC）；浏览器打开后端 `/child`、`/robot/emotion`（**不**用浏览器采麦） |
| **教师端** | 浏览器打开教师前端（可用安卓浏览器）连后端 `:8080` |

音视频主路径：`robot_runtime` → HTTP `POST /api/media/<sessionId>/frames|audio-chunks` → 服务端 Real 注意力/情绪/语音写入 behavior → 报告。

`/child` 在 agent 模式下只负责课程展示、触发本机 Runtime 录制、播语音；**不再**跑浏览器 C2 摄像头分析。

本机开发捷径：`CHILD_MEDIA_MODE=browser`（/child `getUserMedia` + 可选 C2），与生产正交。

## 一句话

- **后端主机**：整仓 `git pull`，跑 `python app.py`。
- **机器人 Windows 机**：**不要**整仓 pull；从局域网下载 exe 安装包即可。

## 后端主机

1. `git pull`
2. 创建/激活 venv，`pip install -r requirements.txt`
3. 若用 Real 视觉/语音：`pip install -r requirements-optional-analyzers.txt`，并准备 `models/` 下 MediaPipe 等模型
4. 配置 `.env`（至少）：
   - `ROBOT_CONTROL_MODE=robot_runtime`
   - `CHILD_MEDIA_MODE=agent`
   - （可选）无模型冒烟：`USE_REAL_ANALYZERS=false`
5. 确认 `config/analyzers.yaml` 中 `global.mode: real`（仓库默认）
6. 确保 `releases/robot/` 下有发布 zip（见下方「如何把包放到服务器」）
7. `python app.py`（默认 `:8080`）

下载页：`http://<后端IP>:8080/robot/download`

## 机器人端（推荐：exe 包）

1. 浏览器打开 `http://<后端IP>:8080/robot/download`
2. 下载 zip，解压到例如 `C:\EIArt\robot\`
3. 双击 `start.bat`
4. 在打开的 `/ui` 填写后端地址并「应用并注册」
5. 浏览器打开 `/child`、`/robot/emotion` 上课

可选运维：

- `/ui` 修改本地音视频保存路径（默认 `%LOCALAPPDATA%\EIArt\child_media`）
- `/ui`「检查更新 / 立即更新」：服务器换了新 zip 后，机器人机可只更新 `RobotRuntime.exe` 并自动重启（不必整包重下安装）

包内结构：

```text
EIArt-Robot/
  README.txt
  start.bat
  VERSION
  RobotRuntime.exe
  DollSer/bin/...
```

无需安装 Python。

## 如何把包放到服务器

在 **Windows 开发机**（有 DollSer 与 Python）执行。建议先建干净 venv 再打包，以免 Anaconda 环境把 matplotlib/PyQt 等打进 exe 导致体积过大：

```powershell
# 可选：干净环境
python -m venv .venv-robot
.\.venv-robot\Scripts\Activate.ps1
pip install -r robot_runtime\requirements.txt pyinstaller

# 仓库根目录
.\scripts\pack_robot_release.ps1
# 可选指定版本
$env:ROBOT_RELEASE_VERSION = "1.0.0"
.\scripts\pack_robot_release.ps1
```

产物：

- `releases/robot/EIArt-Robot-<version>.zip`
- `releases/robot/EIArt-Robot-latest.zip`
- `releases/robot/manifest.json`

将上述 zip + 更新后的 `manifest.json` 拷到服务器同路径（或在能访问该目录的机器上构建后 `git` 只提交 manifest，zip 用 scp/U 盘拷贝）。zip 默认被 `.gitignore` 忽略。

若已有 `dist\RobotRuntime.exe` 只想重打 zip：

```powershell
$env:SKIP_BUILD_EXE = "1"
.\scripts\pack_robot_release.ps1
```

## 验收清单

- [ ] 打包脚本在 Windows 上成功，生成 zip 与有效 manifest（含 VERSION）
- [ ] 解压后 `start.bat` 能拉起 DollSer + RobotRuntime，`http://127.0.0.1:19091/ui` 可开
- [ ] `/ui` 填后端地址后，`/api/robot/runtime/status` 显示在线
- [ ] `/ui` 可改本地媒体目录；录制中拒绝；重启后路径仍生效
- [ ] 服务器更新 zip 后，exe 机 `/ui` 检查更新 → 立即更新 → 重启后版本号变化
- [ ] 后端 `/robot/download` 可下载；无 zip 时页面提示清晰
- [ ] `CHILD_MEDIA_MODE=agent` + `ROBOT_CONTROL_MODE=robot_runtime` 下 `/child` 走本机 19091
- [ ] 后端日志可见 Real 注意力分析器启用（或明确回退 Mock 的告警）
- [ ] 整课后报告：注意力曲线非空、情绪 KPI 有样本（非仅 browser C2）
- [ ] 教师端实时注意力无「高分↔零分」双源跳变

## 开发机源码启动（非发布）

仍可用仓库内：

```text
robot_runtime\start.bat
```

该脚本走 `python -m robot_runtime.agent`，并查找仓库内 `doll\DollSer\bin\DollSer.exe`。课堂现场请用发布 zip。
