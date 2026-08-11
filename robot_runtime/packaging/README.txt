EIArt 机器人端安装包
====================

本包包含：
  - RobotRuntime.exe   媒体采集 + DollSer OSC 桥 + 向后端注册
  - DollSer\           机械臂/表情执行程序
  - start.bat          一键启动（互斥、健康轮询、日志）
  - restart.bat        一键重启（先清掉所有 RobotRuntime/DollSer 实例，再完整启动）

三步上手
--------
1. 解压到任意目录，例如 C:\EIArt\robot\
2. 双击 start.bat
   - 会同时检查 DollSer 进程和 OSC 端口，必要时启动 DollSer
   - 同版本会复用兼容的 RobotRuntime，避免连续双击产生两个实例
   - 不同版本会精确结束旧 RobotRuntime，并重启 DollSer 后由当前包接管
   - 新启动时等待 /ready，确认 Server 注册及协议兼容后才打开本机运维页
3. 安装包已包含打包时的后端地址；首次配置后也会持久保存，无需每次填写

机器人不动 / 出问题时：
  - 双击 restart.bat 一键重启（会停掉所有 RobotRuntime 和 DollSer 进程，
    等全部退出后再重新拉起，避免多开互相干扰）
  - 查看 logs\restart.log、logs\startup.log 确认过程

运维页还可：
- 修改本地音视频保存路径（默认 %LOCALAPPDATA%\EIArt\child_media）
- 「检查更新 / 立即更新」：服务器发布新包后，无需整包重装，只替换 RobotRuntime.exe 并自动重启

上课时
------
- 运维页点「打开 /child」：会运行同目录 Open-ChildLanMic.ps1，用带 insecure-origin
  标志的 Edge/Chrome 打开 LAN 上的 /child（麦克风可用）。脚本缺失时退回普通浏览器。
- 表情页仍可直接打开：http://<后端IP>:8080/robot/emotion
- 手动打开儿童页：http://<后端IP>:8080/child（LAN HTTP 下麦克风通常被浏览器拦截）

注意
----
- 无需安装 Python。
- 防火墙需允许本机 19091 端口被后端主机访问（课堂局域网）。
- 摄像头/麦克风请允许 RobotRuntime 使用。
- 当前发布包的 DollSer 串口配置为 COM3；更换硬件端口后需同步修改 Settings.xml。
- 启动失败时查看 logs\startup.log、logs\runtime.stdout.log 和 logs\runtime.stderr.log。
- 首次安装仍可到 http://<后端IP>:8080/robot/download 下载完整包；日常升级优先用 /ui 热更新。
