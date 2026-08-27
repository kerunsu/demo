# Demo 环境与配置

Demo 版只运行 Flask 后端、同源教师端、儿童端和 Server 控制台。儿童摄像头与麦克风由 `/child` 页面直接采集；不启动 Robot Runtime，不连接 DollSer/OSC，也不使用完整版表情目录。

## 首次拉取

Windows 机器需要 Git、Python 3.10+ 和 Node.js LTS。克隆后在仓库根目录执行：

```powershell
Copy-Item .env.example .env
.\start_server.ps1
```

启动脚本会安装缺失依赖、构建教师端，并在数据库不存在时创建只含模仿、配对、排序的标准数据。`.env`、`database/app.db`、录制、日志、`.runtime/`、`node_modules/` 和构建压缩包均为本机数据，不得提交。

## 可配置项

- `SECRET_KEY`：生产环境必须替换。
- `EIART_DATABASE_PATH`：可选 SQLite 文件路径；默认 `database/app.db`。
- `USE_REAL_ANALYZERS`：覆盖分析器真实/模拟模式。
- `VIDEO_FPS`、`VIDEO_WIDTH`、`VIDEO_HEIGHT`：浏览器视频写盘参数。
- `AUDIO_SAMPLE_RATE`、`AUDIO_CHANNELS`：浏览器音频写盘参数。
- `BROWSER_JPEG_QUALITY`：儿童端 JPEG 上行质量。
- `MEDIA_UPLOAD_SHARED_KEY`：需要保护浏览器媒体上传时设置的共享密钥。
- `POSE_ESTIMATION_ENABLED`、`FACE_ANALYSIS_ENABLED`、`AUDIO_ANALYSIS_ENABLED`：分析开关。
- `DIALOGUE_ENABLED`、`DIALOGUE_WAKE_WORD_ENABLED`、`BROWSER_SPEECH_RATE`：浏览器语音交互。
- `AI_CHAT_PROVIDER`、`ASD_AGENT_ENV_FILE`：可选对话模型配置；密钥只存本机文件。
- `START_TEACHER_FRONTEND`：是否检查/构建教师端生产包。
- `START_VOICE_SERVICE`、`VOICE_PYTHON_SERVICE_URL`：可选本地语音服务诊断能力。
- `ENABLE_HTTPS`、`SSL_CERTFILE`、`SSL_KEYFILE`：局域网安全上下文。
- `LOG_LEVEL`：日志级别。

`CHILD_MEDIA_MODE` 与 `ROBOT_CONTROL_MODE` 即使由旧环境变量传入，也会分别收敛为 `browser` 和 `disabled`。任何环境变量都不能开启机械动作、Robot Runtime 或完整版表情。

## 页面地址

- 教师端：`http://<server-ip>:8080/teacher/`
- 儿童端：`http://<server-ip>:8080/child`
- Server：`http://<server-ip>:8080/server`

局域网 HTTP 下若浏览器拒绝麦克风/摄像头权限，优先配置 HTTPS；临时现场部署可运行 `scripts/Open-ChildLanMic.ps1 -LanHost <后端IP>` 打开受限儿童端窗口。

环境检查使用：

```powershell
.\start_server.ps1 -CheckOnly
```

该检查不创建数据库。全新机器第一次正式使用应执行正常启动命令。
