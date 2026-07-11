# 依赖安装说明

> 更新日期：2026-06-15  
> 环境变量配置见 [`ENVIRONMENT.md`](ENVIRONMENT.md)；跑通 Demo 见 [`ONBOARDING.md`](ONBOARDING.md)。

---

## 1. 总览：你需要装什么？

| 场景 | Node.js | npm 三包 | Python | 语音模型 |
|------|---------|----------|--------|----------|
| **A. 最小 Demo**（规则对话、mock 语音） | ✅ 20+ | ✅ | ❌ 可不装 | ❌ |
| **B. 完整 `npm run dev`** | ✅ | ✅ | ✅ 3.10+（仅启动 voice-service，默认 mock） | ❌ |
| **C. 本地 Vosk/Piper 真 STT/TTS** | ✅ | ✅ | ✅ + pip 包 | ✅ 需下载到 `.runtime/models/` |
| **D. 语音黑盒对方** | ❌ | ❌ | ✅（或任意语言自建 HTTP） | 由对方自定 |

---

## 2. Node.js 与 npm（必做）

### 2.1 版本

- **Node.js 20+**（LTS 推荐；`docs/DEMO_RUNBOOK.md` 写 18+ 亦可，以 20+ 为准）
- **npm** 随 Node 安装即可

验证：

```bash
node -v
npm -v
```

### 2.2 为何要在三个目录各装一次？

本仓库是 **monorepo 式布局**，根目录、`backend/`、`frontend/` 各有独立 `package.json`：

| 目录 | 作用 |
|------|------|
| 根目录 | 编排脚本（`concurrently`）、`shared/` 构建与测试入口 |
| `backend/` | Express API、WebSocket、会话服务 |
| `frontend/` | React + Vite 三屏 SPA |

`backend` 与 `frontend` 通过 `child-education-training-demo: file:..` 引用根目录的 `shared/` 契约。

### 2.3 安装命令

在项目**根目录**依次执行：

```bash
npm install
npm --prefix backend install
npm --prefix frontend install
```

Windows PowerShell 同上。

### 2.4 安装后验证

```bash
npm run build
npm test
```

通过即表示 Node 依赖完整。

### 2.5 常见问题

| 现象 | 处理 |
|------|------|
| `npm install` 很慢 | 可配置国内 npm 镜像，或仅对本次安装使用 `npm config set registry ...`（勿提交到仓库） |
| `EACCES` / 权限错误 | Windows 用管理员终端或换到用户目录；勿用 `sudo npm` 装项目依赖 |
| `backend` 找不到 `shared` 类型 | 先执行根目录 `npm run build:shared` 或 `npm run build` |
| 锁文件冲突 | 以仓库内 `package-lock.json`（根/backend/frontend 各有）为准，勿手改 |

---

## 3. Python（可选，语音相关）

### 3.1 何时需要？

- 执行 **`npm run dev`** 时会自动拉起 `tools/voice-service/voice_service.py`（默认 **mock**，仅用标准库）。
- 需要 **本地 Vosk STT / Piper TTS** 时才必须安装 Python 与 pip 包。
- **语音黑盒对方**（`tools/voice-partner/`）需 Python 跑参考服务，或对方用其他语言实现同一 HTTP 契约。

### 3.2 版本

- **Python 3.10+**
- 命令名一般为 `python`（Windows 安装时勾选 “Add to PATH”）

验证：

```bash
python --version
```

### 3.3 参考服务（语音黑盒对方）

```powershell
# Windows
copy tools\voice-partner\partner.env.example tools\voice-partner\partner.env
python tools\voice-partner\reference_server.py
```

仅需标准库 + 本目录 `partner_impl.py`，**无额外 pip 依赖**（除非你在 `partner_impl.py` 里自行引入）。

### 3.4 本地 STT/TTS（Vosk + Piper）

**方式一：项目推荐 venv**（与 benchmark 共用依赖清单）

```powershell
python -m venv tools\voice-benchmark\.venv
tools\voice-benchmark\.venv\Scripts\python.exe -m pip install -r tools\voice-benchmark\requirements-local.txt
```

`requirements-local.txt` 含：`vosk`、`piper-tts`、`psutil`。

**方式二：安装到 `.runtime/python-site`**（`npm run dev` 启动 voice-service 时会 prepend 该路径到 `PYTHONPATH`）

```powershell
python -m pip install --target .runtime\python-site -r tools\voice-benchmark\requirements-local.txt
```

### 3.5 语音模型文件（Git 未跟踪，需自行下载）

解压/放置到以下路径（目录需自行创建）：

```text
.runtime/models/vosk/vosk-model-small-cn-0.22/     # Vosk 解压后的目录
.runtime/models/piper/zh_CN-huayan-medium.onnx
.runtime/models/piper/zh_CN-huayan-medium.onnx.json
```

| 模型 | 来源 |
|------|------|
| Vosk small 中文 | https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip |
| Piper huayan medium | https://huggingface.co/rhasspy/piper-voices/tree/main/zh/zh_CN/huayan/medium |

模型体积约数十 MB，**不要提交到 Git**（已在 `.gitignore`）。

### 3.6 启用本地语音后启动

```bash
npm run dev:vosk
```

或手动设置环境变量后启动 voice-service，详见 `tools/voice-service/README.md`。

---

## 4. 系统与其他依赖

| 项 | 说明 |
|----|------|
| **Git** | 克隆与版本管理 |
| **浏览器** | Chrome/Edge 推荐；语音输入、摄像头注意力需 HTTPS 或 localhost |
| **ffmpeg** | 非必须；部分媒体合并场景可由运行时处理，现场运维见 `docs/DEPLOYMENT_OPERATIONS_M7.md` |
| **课程素材** | `matching/`、`paixu/`、`Emotions/` 已随仓库提供，无需安装 |

---

## 5. 按角色速查

### 本仓主开发（第一天）

```bash
npm install && npm --prefix backend install && npm --prefix frontend install
copy backend\.env.example backend\.env
npm run dev
```

### 仅验收 UI / 规则对话

同上即可，无需 Python、无需模型。

### 语音黑盒对接方

只需 Python 3.10+ 与 `tools/voice-partner/`，见 [`tools/voice-partner/一页交接说明.md`](../tools/voice-partner/一页交接说明.md)。

### 现场运维 / LAN 部署

Node 依赖同上；生产环境变量见 `deploy/production.env.example` 与 [`DEPLOYMENT_OPERATIONS_M7.md`](DEPLOYMENT_OPERATIONS_M7.md)。

---

## 6. 相关文档

| 文档 | 内容 |
|------|------|
| [`ONBOARDING.md`](ONBOARDING.md) | 五分钟跑起来 |
| [`ENVIRONMENT.md`](ENVIRONMENT.md) | `.env` 变量 |
| [`tools/voice-service/README.md`](../tools/voice-service/README.md) | Python 语音服务端点 |
| [`tools/voice-benchmark/README.md`](../tools/voice-benchmark/README.md) | 模型路径与 benchmark venv |
