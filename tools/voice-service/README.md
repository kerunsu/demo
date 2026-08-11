# Voice Service（FunASR STT）

本地 HTTP 语音服务，供儿童对话 STT 使用（`VOICE_PYTHON_SERVICE_URL`，默认 `http://127.0.0.1:8765`）。

源码自 DemoRobot `tools/voice-service/voice_service.py` 拷贝，可在本仓库独立运行。

## 一键（推荐）

后端启动时会按需拉起本服务（对话开启且 `START_VOICE_SERVICE` 未关闭时）。
首次运行会在 voice-service 实际使用的 Python 中自动安装依赖，并把主模型、
VAD 和标点模型下载到项目的 `.runtime/models/voice/`；后续启动校验后复用：

```powershell
.\.venv\Scripts\python.exe app.py
```

健康检查：`GET http://127.0.0.1:8765/health`

## 单独启动

```powershell
.\.venv\Scripts\python.exe scripts\start_voice_service.py
```

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
| `START_VOICE_SERVICE` | 随 `app.py` 自动拉起 | `true`（当 `DIALOGUE_ENABLED=true`） |
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

## 模型部署位置

FunASR 不运行在儿童端浏览器。儿童端只采集 WAV 并通过 Socket 发给
Server；Server 的 `app/dialogue/stt.py` 优先尝试本进程 FunASR，随后调用
`tools/voice-service/voice_service.py` 的 `http://127.0.0.1:8765/stt`。
模型由运行 voice-service 的 Python 环境加载。`app.py` 自动准备时使用
`.runtime/models/voice/modelscope/`，解析后的三个本地目录记录在
`.runtime/models/voice/model_paths.json`。显式提供三个模型路径时仍优先使用它们。

当前服务是否真正可用可查看 `/api/v2/voice/health`。仅有 8765 端口或
`status=ok` 不代表模型可用，必须看到 `sttProviderStatus=READY` 或
`DEGRADED`。自动安装或下载失败时，启动日志会包含 pip/ModelScope 的原始错误，
voice-service 不会被误报为就绪；儿童端会显示缺失依赖和服务状态。
