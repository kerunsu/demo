# Servo Motion Workbench 项目结构与迁移说明

## 1. 控制端位置

动作设计控制端主要位于：

```text
doll/
```

该目录是一个 Node.js Web 服务，负责：

| 功能 | 说明 |
|---|---|
| Web 页面 | 提供动作轨道编辑、动作块参数编辑、播放预览、导入导出 JSON。 |
| HTTP API | 提供配置读取、预设保存、播放序列、停止序列等接口。 |
| OSC 转发 | 将 Web 控制端生成的动作指令发送给 `DollSer.exe`。 |
| 数据保存 | 保存动作预设、安全限制、表情媒体状态等数据。 |

底层舵机运行程序位于：

```text
bin/DollSer.exe
```

启动入口位于：

```text
bin/LaunchServoWorkbench.bat
```

该启动脚本会：

1. 检查本机是否安装 Node.js。
2. 如果 `DollSer.exe` 未运行，则启动 `bin/DollSer.exe`。
3. 在 `doll/` 目录下运行 `node server.js`。
4. 打开浏览器访问 `http://localhost:3000`。

## 2. 顶层目录结构

```text
BotCtrl/
├─ bin/
├─ docs/
├─ doll/
├─ dollOSCTest/
├─ example/
├─ bin.zip
├─ doll.zip
├─ dollOSCTest.zip
└─ DollSer.zip
```

| 路径 | 作用 |
|---|---|
| `bin/` | 底层运行程序、动态库、启动脚本、底层配置文件。 |
| `doll/` | 动作设计控制端主目录。 |
| `docs/` | 项目文档、JSON 格式说明、迁移说明。 |
| `example/` | 学长旧动作数据示例与旧格式说明。 |
| `dollOSCTest/` | 旧测试程序或历史 OSC 测试目录。 |
| `*.zip` | 历史压缩包或备份文件，不是控制端运行必需目录。 |

## 3. doll 目录结构

```text
doll/
├─ data/
├─ face-media/
├─ expressions/
├─ node_modules/
├─ public/
├─ package.json
├─ package-lock.json
├─ send-test.js
└─ server.js
```

| 路径 | 作用 |
|---|---|
| `doll/server.js` | 控制端后端主程序。提供 HTTP API、静态页面服务、OSC 指令发送、动作播放调度。 |
| `doll/public/index.html` | Servo Motion Workbench 主页面。 |
| `doll/public/script.js` | 前端主要逻辑。包含动作轨道编辑、导入导出 JSON、播放请求、预设管理。 |
| `doll/public/motion-standard.js` | 可在浏览器和 Node.js 共用的动作交付规范模块，负责统一 JSON 校验与问题说明。 |
| `doll/public/face.html` | 表情媒体页面。 |
| `doll/data/motion-presets.json` | 保存到文件的动作预设。 |
| `doll/data/workbench-safety.json` | 工作台安全限制配置，例如角度范围、最大角速度。 |
| `doll/face-media/` | 表情媒体文件目录。 |
| `doll/expressions/` | 推荐的表情素材目录；支持图片、GIF 和视频，动作 JSON 通过文件名引用。 |
| `doll/expressions/idle/` | 待机表情目录；无动作播放时自动循环，动作开始后自动让出显示。 |
| `doll/package.json` | Node.js 项目依赖声明。 |
| `doll/package-lock.json` | Node.js 依赖锁定文件。 |
| `doll/node_modules/` | 已安装的 Node.js 依赖。可迁移，也可在新机器上重新安装。 |
| `doll/send-test.js` | OSC 发送测试脚本。 |
| `doll/test/motion-standard.test.js` | 动作格式、范围、时长覆盖和同轴冲突的自动化测试。 |

## 3.1 推荐动作交付流程

工作台按以下四个阶段组织操作：

1. **编写动作**：设置动作名称、中位、动作块角度和时间。
2. **规范检查**：右侧“交付检查”会实时检查统一 JSON 格式、总时长和指令字段。
3. **测试动作**：先点“模拟测试”查看指令序列，再预览单个动作块，最后连接机器人整体播放。
4. **导出交付**：检查无错误后导出 `dollser-motion` version 2 JSON。导入方可直接用同一工作台复核和播放。

“模拟测试”不会向舵机发送任何指令，适合在没有连接硬件时检查交付文件。同轴指令在前一条尚未完成时开始会显示提醒；这不阻止导出，但交付前应确认该接管行为是否符合动作意图。

需要配合表情时，将素材放入 `doll/expressions/`，在预设信息下方的“序列表情”区域刷新目录并选择文件。每个动作序列只能选择一个表情，表情不再属于单个舵机动作块。动作轨道下方的表情轨道与舵机轨道共用时间刻度，可单独拖动开始位置和左右边缘。整体播放时服务端会同步调度动作和表情；“打开表情显示页”按钮用于在另一个窗口或机器人屏幕显示结果。

表情参数中的“相对动作序列偏移”使用毫秒：负数表示表情提前，正数表示延后。负偏移会自动生成表情预卷，并整体后移舵机指令。导出的 JSON 会同时保存 `time`、`motionStartTime`、`offsetMs`、`leadMs` 和 `leadSeconds`，方便接收方准确复现同步关系。

选择视频表情后，浏览器会读取媒体元数据并把表情显示时长设置为视频真实时长。系统只会把统一播放时间轴扩展到能够完整容纳舵机序列和表情，不会修改舵机序列时长，也不会修改任何动作块的开始、到位、保持或回位时间。表情提前时只增加播放预卷并整体平移舵机指令，其相对时序保持不变。选择图片时没有固有媒体时长，使用手动填写的显示时长。

待机表情放入 `doll/expressions/idle/`。系统会按文件名排序使用第一个有效素材，并在服务启动、动作结束或手动停止后自动循环显示；动作播放期间待机表情隐藏。建议该目录只保留一个正式待机素材，避免选择顺序产生歧义。

## 4. bin 目录结构

```text
bin/
├─ data/
├─ DollSer.exe
├─ fmod.dll
├─ fmodL.dll
├─ FreeImage.dll
├─ LaunchServoWorkbench.bat
├─ QuickGentleTest.bat
└─ QuickGentleTest.ps1
```

| 路径 | 作用 |
|---|---|
| `bin/DollSer.exe` | 底层舵机运行程序。 |
| `bin/fmod.dll` | `DollSer.exe` 运行所需动态库。 |
| `bin/fmodL.dll` | `DollSer.exe` 运行所需动态库。 |
| `bin/FreeImage.dll` | `DollSer.exe` 运行所需动态库。 |
| `bin/data/Settings.xml` | 底层配置文件，包含 COM 口、中位角、默认时间等。 |
| `bin/LaunchServoWorkbench.bat` | 推荐启动入口。 |
| `bin/QuickGentleTest.ps1` | PowerShell 版快速舵机测试脚本。 |
| `bin/QuickGentleTest.bat` | 快速测试脚本入口。 |

`DollSer.exe` 与三个 DLL 应保持在同一目录下。

### 启动与中位配置

启动脚本会在启动 `DollSer.exe` 前确认 `bin/data/Settings.xml` 存在，并检查 `Pitch`、`Yaw`、`ArmL`、`ArmR` 均为 `0..359` 的有效整数。`DollSer.exe` 会固定以 `bin/` 为工作目录启动，避免从 IDE、快捷方式或其他目录运行时找不到相对路径 `data/Settings.xml`。

`Settings.xml` 保存底层启动参数，`doll/data/workbench-safety.json` 保存工作台实际标定的中心、方向和安全行程。两者不会在启动时自动互相覆盖。当前工作台标定中心为：

```text
Pitch 200 / Yaw 160 / ArmL 320 / ArmR 50
```

Web 服务启动不会主动发送 OSC 姿态。重新标定前应记录原值并进行低速、单轴验证，不要根据另一份配置自动推断或覆盖中位。

## 5. 主要运行链路

```text
浏览器页面
  ↓
doll/public/index.html
doll/public/script.js
  ↓ HTTP 请求
doll/server.js
  ↓ OSC UDP
bin/DollSer.exe
  ↓
舵机底层控制
```

默认访问地址：

```text
http://localhost:3000
```

默认 OSC 目标：

```text
127.0.0.1:12000
```

默认底层配置文件：

```text
bin/data/Settings.xml
```

## 6. Node.js 依赖项

`doll/package.json` 中声明的依赖：

| 依赖 | 当前声明版本 | 作用 |
|---|---|---|
| `express` | `^5.2.1` | Web 服务和 HTTP API。 |
| `node-osc` | `^11.1.1` | 向 `DollSer.exe` 发送 OSC UDP 指令。 |
| `socket.io` | `^4.8.3` | 当前依赖中存在，控制端主流程暂未强依赖其核心功能。 |

运行环境依赖：

| 依赖 | 说明 |
|---|---|
| Node.js | 必须安装，并确保 `node` 在系统 `PATH` 中。 |
| Windows | 当前启动脚本、`DollSer.exe`、PowerShell 测试脚本均面向 Windows。 |
| 浏览器 | 用于访问 Web 控制端。 |

运行自动化测试：

```powershell
cd doll
npm.cmd test
```

Windows PowerShell 如果禁止执行 `npm.ps1`，应使用上面的 `npm.cmd`，不需要修改系统执行策略。

## 7. 端口与环境变量

控制端 Web 服务默认端口：

```text
3000
```

可通过环境变量修改：

| 环境变量 | 默认值 | 作用 |
|---|---|---|
| `DOLL_WEB_PORT` | `3000` | Web 控制端 HTTP 端口。 |
| `DOLL_OSC_HOST` | `127.0.0.1` | OSC 目标主机。 |
| `DOLL_OSC_PORT` | `12000` | OSC 目标端口，即 `DollSer.exe` 监听端口。 |

示例：

```powershell
$env:DOLL_WEB_PORT='3001'
node doll/server.js
```

## 8. 数据文件

| 文件 | 是否建议迁移 | 说明 |
|---|---:|---|
| `doll/data/motion-presets.json` | 是 | 已保存动作预设。 |
| `doll/data/workbench-safety.json` | 是 | 工作台安全限制。 |
| `bin/data/Settings.xml` | 是 | 底层 COM 口、中位角、默认时间配置。 |
| `doll/face-media/` | 按需 | 表情媒体资源。 |
| `doll/expressions/` | 是 | 与动作 JSON 配套交付的图片、GIF、视频表情素材。 |
| 浏览器 localStorage | 按需 | 暂存动作和本地偏好存在浏览器中，跨机器不会自动迁移。 |

注意：未点击“保存到预设文件”的临时动作可能只存在浏览器 localStorage 中，不一定写入 `doll/data/motion-presets.json`。

## 9. 迁移可行性

该控制端可以迁移。

建议整体迁移以下目录：

```text
bin/
doll/
docs/
example/
```

最小迁移集合：

```text
bin/DollSer.exe
bin/fmod.dll
bin/fmodL.dll
bin/FreeImage.dll
bin/data/Settings.xml
bin/LaunchServoWorkbench.bat
doll/server.js
doll/package.json
doll/package-lock.json
doll/public/
doll/data/
```

如果迁移时不携带 `doll/node_modules/`，需要在新机器上执行：

```powershell
cd doll
npm install
```

## 10. 迁移步骤

1. 在目标机器安装 Node.js。
2. 复制项目目录，建议保持原有相对目录结构：

```text
BotCtrl/
├─ bin/
└─ doll/
```

3. 如果没有复制 `doll/node_modules/`，执行：

```powershell
cd BotCtrl\doll
npm install
```

4. 确认 `bin/DollSer.exe` 与 DLL 文件在同一目录。
5. 确认 `bin/data/Settings.xml` 中 COM 口与目标机器一致。
6. 双击运行：

```text
bin/LaunchServoWorkbench.bat
```

7. 浏览器打开：

```text
http://localhost:3000
```

## 11. 手动启动方式

启动 `DollSer.exe`：

```powershell
Start-Process .\bin\DollSer.exe
```

启动 Web 控制端：

```powershell
cd doll
node server.js
```

访问：

```text
http://localhost:3000
```

## 12. 常见问题

| 问题 | 检查项 |
|---|---|
| 双击启动失败，提示找不到 Node.js | 安装 Node.js，并确认 `node` 在 `PATH` 中。 |
| 页面打不开 | 检查 `node server.js` 是否启动成功，检查端口 `3000` 是否被占用。 |
| 舵机没有动作 | 检查 `DollSer.exe` 是否运行，检查 OSC 端口是否为 `12000`，检查 `Settings.xml` 中 COM 口。 |
| 动作预设丢失 | 检查是否复制了 `doll/data/motion-presets.json`，以及是否曾点击“保存到预设文件”。 |
| 安全角度限制丢失 | 检查是否复制了 `doll/data/workbench-safety.json`。 |
| 换机器后串口不对 | 修改 `bin/data/Settings.xml` 中的 `<COM>`。 |
| 启动后转到异常角度 | 立即停止程序并断开舵机供电；检查 `Settings.xml` 四轴中位，确认通过 `bin/LaunchServoWorkbench.bat` 启动，不要直接从未知工作目录运行 `DollSer.exe`。 |

## 13. 相关文档

| 文档 | 说明 |
|---|---|
| `docs/DollSerMotionJson说明.md` | 动作 JSON 格式说明。 |
| `example/动作保存当前结构json格式说明.txt` | 学长旧动作格式说明，仅作历史参考。 |
