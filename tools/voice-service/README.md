# Voice Service（旧版手动诊断工具）

本地 HTTP 语音服务，仅保留给历史兼容和手动模型诊断使用。生产儿童端已经统一使用浏览器 `SpeechRecognition`，不会调用本服务。

源码自 DemoRobot `tools/voice-service/voice_service.py` 拷贝，可在本仓库独立运行。

## 手动启动（非生产路线）

`app.py` 不再自动安装模型或拉起本服务。如需排查历史模型，可手动运行：

```powershell
.\.venv\Scripts\python.exe scripts\start_voice_service.py
```

健康检查：`GET http://127.0.0.1:8765/health`

或直接：

```powershell
$env:VOICE_SERVICE_STT_PROVIDER='local-funasr'
$env:VOICE_SERVICE_TTS_PROVIDER='mock'
# 建议用 ExpertAnnotator ASD venv（已装 funasr）
& ..\ExpertAnnotator_ASD-main\asd_llm_agent\.venv\Scripts\python.exe tools\voice-service\voice_service.py
```

## 环境变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `START_VOICE_SERVICE` | 旧版 launcher 开关；`app.py` 不再调用 | 无生产作用 |
| `VOICE_SERVICE_PYTHON` | 运行本服务的 Python | ExpertAnnotator ASD `.venv`（若存在） |
| `VOICE_PYTHON_SERVICE_URL` | 后端调用地址 | `http://127.0.0.1:8765` |
| `VOICE_SERVICE_HOST` / `VOICE_SERVICE_PORT` | 监听地址 | `127.0.0.1` / `8765` |
| `VOICE_SERVICE_STT_PROVIDER` | STT 后端 | `local-funasr`（自动启动时） |
| `VOICE_SERVICE_AUTO_INSTALL` | 缺依赖时自动执行 pip 安装 | `true` |
| `VOICE_SERVICE_AUTO_DOWNLOAD` | 缺模型时自动下载到项目缓存 | `true` |
| `VOICE_SERVICE_MODEL_DOWNLOAD_RETRIES` | 模型下载尝试次数 | `2` |
| `VOICE_SERVICE_MODEL_DOWNLOAD_TIMEOUT` | 单次模型准备超时（秒） | `1800` |
| `VOICE_SERVICE_FUNASR_MODEL` | FunASR 主模型路径或名 | modelscope 本地缓存（若存在）否则 `paraformer-zh` |
| `VOICE_SERVICE_FUNASR_VAD_MODEL` | VAD 模型 | modelscope `speech_fsmn_vad_...` 或 `fsmn-vad` |
| `VOICE_SERVICE_FUNASR_PUNC_MODEL` | 标点模型 | modelscope `punc_ct-transformer_...` 或 `ct-punc` |

日志：`.runtime/logs/voice-service.log`（stdout/stderr）。

## 端点

- `GET /health`
- `POST /stt`
- `POST /tts`（默认 mock）

## 历史模型部署位置

生产儿童端不再采集或上传 WAV，只把浏览器识别后的文本通过
`child_dialogue_text` 发送给 Server。`app/dialogue/stt.py` 和本工具不在
生产对话链路中。
模型由手动运行 voice-service 的 Python 环境加载。准备脚本使用
`.runtime/models/voice/modelscope/`，解析后的三个本地目录记录在
`.runtime/models/voice/model_paths.json`。显式提供三个模型路径时仍优先使用它们。

当前服务是否真正可用可查看 `/api/v2/voice/health`。仅有 8765 端口或
`status=ok` 不代表模型可用，必须看到 `sttProviderStatus=READY` 或
`DEGRADED`。自动安装或下载失败时，启动日志会包含 pip/ModelScope 的原始错误，
voice-service 不会被误报为就绪；该状态仅供运维手动检查，儿童端不会读取。
