# Servo Motion Workbench 交接说明

动作工作台位于 `doll/DollSer/doll/`，用于编写、规范检查、模拟/实机测试并导出带序列表情的 `dollser-motion` version 2 JSON。

## 启动

Windows 下运行：

```text
doll/DollSer/bin/LaunchServoWorkbench.bat
```

首次使用如果没有安装 Node 依赖：

```powershell
cd doll/DollSer/doll
npm.cmd install
npm.cmd test
```

启动器会从 `doll/DollSer/bin/` 运行现有 `DollSer.exe`，并打开 `http://localhost:3000`。不要从未知工作目录直接启动底层程序。

## 数据与素材

- 动作预设：`doll/DollSer/doll/data/motion-presets.json`
- 工作台标定与安全范围：`doll/DollSer/doll/data/workbench-safety.json`
- 动作表情：`doll/DollSer/doll/expressions/`
- 待机表情：`doll/DollSer/doll/expressions/idle/`
- 底层串口与启动参数：`doll/DollSer/bin/data/Settings.xml`

工作台标定与 `Settings.xml` 是不同层级的配置，禁止根据其中一份自动覆盖另一份。调整舵机参数前先备份并进行低速、单轴验证。

## JSON 迁移约定

接收程序应使用一个统一时钟：

- 按 `expression.time` 播放序列表情。
- 按 `commands[].time` 发送舵机指令。
- 每条指令持续 `commands[].moveMs`。
- 以顶层 `durationMs` 和最后一条指令实际结束时间为播放结束依据。
- JSON 只引用 `expression.mediaId`，交接时必须同时提供对应媒体文件。

完整字段见 `doll/DollSer/docs/DollSerMotionJson说明.md`。

## 验证

```powershell
cd doll/DollSer/doll
npm.cmd test
node --check server.js
node --check public/script.js
```

当前自动化测试覆盖格式版本、角度与时长范围、指令覆盖、同轴重叠提醒、序列表情与预卷时间轴。
