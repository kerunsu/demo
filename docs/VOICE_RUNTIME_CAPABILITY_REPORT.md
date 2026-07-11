# M4-001 Voice Runtime Capability Report

生成时间：2026-06-13 13:04 China Standard Time  
任务状态：`COMPLETE_FOR_DEVELOPMENT`  
主机结果标签：`DEVELOPMENT_SERVER_BASELINE`

## 1. 主机身份

当前事实：本轮探测运行在 `LAPTOP-HFG76DEO`，仓库路径为 `D:\For Study\MyProjectRelated\Project\2026_DEMO_Robot\Project`。

当前事实：项目负责人最新确认当前处于开发阶段，所有开发和自动化测试暂时在当前本机完成，当前本机可以暂时视为高性能服务器开发环境。

当前事实：未来实际部署时，机器人设备只负责 `/child`、`/robot`、麦克风和摄像头采集、GIF 动画与音频播放；机器人端不承担 VAD、STT、TTS、视觉分析或大模型等高性能计算。

当前事实：当前 Codex 无法访问机器人设备不阻塞 M4 开发；当前阶段暂不要求探测真实机器人主机性能。

建议：未来正式服务器硬件确定后，可以再次执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\voice-runtime\Collect-VoiceRuntimeCapabilities.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\voice-runtime\Collect-VoiceRuntimeCapabilities.ps1 -SelfTest
```

输出文件：

- `.runtime/voice-capabilities.json`
- `.runtime/voice-capabilities.txt`

## 2. 已实测范围

当前事实：本轮脚本只读取系统能力和设备枚举，不录音、不保存音频、不读取 API Key、不安装软件、不下载模型、不访问外部网络、不修改系统设置。

当前事实：脚本实际输出已写入 `.runtime/voice-capabilities.json` 和 `.runtime/voice-capabilities.txt`，该目录已加入 `.gitignore`。

## 3. 操作系统

当前开发服务器基线：

| 字段 | 结果 |
| -- | -- |
| Windows | Microsoft Windows 11 家庭版 中文版 |
| 版本 | 10.0.26200, build 26200 |
| 架构 | 64 位 |
| PowerShell | 5.1.26100.8655 |
| 时区 | China Standard Time |
| 主机厂商/型号 | HONOR / FMB-P |
| 磁盘 | C: 300 GB total, 31.46 GB free; D: 625.66 GB total, 122.17 GB free |

待确认：未来正式高性能服务器硬件确定后，可复跑脚本形成部署 baseline。

## 4. CPU 与内存

当前开发服务器基线：

| 字段 | 结果 |
| -- | -- |
| CPU | Intel(R) Core(TM) Ultra 9 285H |
| 物理核心 | 16 |
| 逻辑核心 | 16 |
| 总内存 | 31.5 GB |
| 当前可用内存 | 16.75 GB |

当前事实：这些数值代表当前开发阶段服务器 baseline，不代表未来机器人浏览器终端，也不代表最终部署服务器。

## 5. GPU 与加速条件

当前开发服务器基线：

| 项目 | 结果 |
| -- | -- |
| 主要 GPU | Intel(R) Arc(TM) 140T GPU (16GB) |
| 厂商 | Intel Corporation |
| 驱动版本 | 32.0.101.6554 |
| 当前分辨率 | 3120x2080 |
| 集成 GPU | `likely` |
| 独立 GPU | 未确认；虚拟显示设备未计入独显 |
| CUDA | `nvidia-smi` 未找到；`nvcc` 未找到；不可判定为 CUDA 可用 |
| ONNX Runtime | Python 环境中存在 `onnxruntime` 1.23.2，providers 为 `AzureExecutionProvider,CPUExecutionProvider` |
| DirectML | `unknown`，未安装或执行 DirectML probe |

当前事实：不得仅凭 GPU 名称声称本地 STT/TTS 一定实时。M4-002 仍需做 CPU、ONNX CPU、DirectML 或其他候选路径的最小 Benchmark。

## 6. 音频输入与输出

当前开发服务器基线：

当前事实：脚本只做设备枚举，没有启动录音。

| 类别 | 结果 |
| -- | -- |
| 活动输入 | `麦克风阵列`，stateCode `1` |
| 其他输入 | 多个耳机输入、`立体声混音`、`麦克风`，均为 inactive/unknown |
| 活动输出 | `扬声器`，stateCode `1` |
| 其他输出 | 多个耳机、显示器/电视/投影音频设备，均为 inactive/unknown |
| 声卡/驱动 | Realtek High Definition Audio、Intel Smart Sound Technology、Nahimic 设备，状态 `OK` |
| 默认麦克风 | `unknown`，脚本未调用交互式 Windows audio API |
| 默认扬声器 | `unknown`，脚本未调用交互式 Windows audio API |
| 采样率/声道 | `unknown`，需后续人工或 Windows audio API 验证 |

需要人工验证：最终机器人浏览器终端上的目标麦克风、目标扬声器、默认输入/输出设备、采样率、声道、回声环境和浏览器权限。

## 7. 显示与浏览器

当前开发服务器基线：

| 字段 | 结果 |
| -- | -- |
| 显示设备数量 | 3 |
| 已枚举分辨率 | 3120x2080；部分显示为 unknown |
| 默认浏览器 | `MSEdgeHTM` |
| Edge | present, version 149.0.4022.62 |
| Chrome | present, version 149.0.7827.103 |
| Web Audio | 现代 Edge/Chrome 预期支持，仍需浏览器实际权限测试 |
| MediaDevices | localhost 或 HTTPS + 用户授权条件下可测，本脚本未调用 |
| WebSocket | 现代 Edge/Chrome 预期支持；仓库 E2E 已覆盖应用层 WebSocket |

当前事实：当前开发服务器满足双显示器枚举条件，但这不是最终机器人浏览器终端验收结果。

## 8. 开发与运行环境

当前开发服务器基线：

| 工具 | 状态 |
| -- | -- |
| Node.js | present, v22.16.0 |
| npm | present, 10.9.2 |
| Python | present, Python 3.12.7 |
| pip | present, pip 24.2 |
| ffmpeg | present, 7.1.1 essentials build |
| Git | present, 2.49.0.windows.1 |
| Visual C++ Runtime | x64 v14.44.35211.00；x86 unknown |
| CUDA | not detected |
| ONNX Runtime | present in Python, CPU/Azure providers only |
| DirectML | unknown |

## 9. 初步能力分级

当前开发服务器基线分级：

- `INTEGRATED_GPU_AVAILABLE`
- `READY_FOR_M4_SPIKE`

分级依据：

- 当前事实：有可用 CPU、31.5 GB 内存、Node/npm/Python/ffmpeg/Git。
- 当前事实：有活动麦克风阵列和活动扬声器枚举。
- 当前事实：有 Intel Arc 140T 集成 GPU，但 CUDA 不可用，DirectML 未确认。
- 当前事实：现代 Edge/Chrome 存在，浏览器 API 仍需权限和实际页面验证。
- 当前事实：M4-001 视为开发阶段完成，不再等待机器人主机性能探测。

未使用的分级：

- `DISCRETE_GPU_AVAILABLE`：未确认真实独显；虚拟显示设备不计入。
- `AUDIO_DEVICE_INCOMPLETE`：当前开发机枚举到活动输入和活动输出。
- `CPU_ONLY_BASELINE`：当前有集成 GPU，但 M4-002 仍必须保留 CPU baseline。
- `UNKNOWN`：核心开发服务器字段已采集。

## 10. 当前适合执行的语音技术 Spike

建议：M4-002 可在当前开发服务器执行本地与云端 STT/TTS Benchmark；所有结果应标注为开发阶段 baseline，最终部署仍需复测。

可测试候选类别：

- 本地 STT：CPU/ONNX/DirectML 或其他本地候选的初始化、延迟、资源和普通话表现。
- 云端 STT：仅在环境变量 Key 存在且测试音频授权明确时执行；缺 Key 标记 `CLOUD_CREDENTIALS_PENDING`。
- 本地 TTS：Windows 本地 TTS、浏览器 Speech Synthesis 或本地模型候选。
- 云端 TTS：仅发送测试文本；缺 Key 标记 `CLOUD_CREDENTIALS_PENDING`。
- 端到端组合：本地 STT + 本地 TTS、本地 STT + 云端 TTS、云端 STT + 本地 TTS、云端 STT + 云端 TTS。

待 M4-002 Benchmark 才能确认：

- STT 普通话识别准确率、实时倍率、内存峰值、冷启动时间和云端网络表现。
- TTS 合成延迟、自然度、音频播放回执精度和云端成本/稳定性。
- CPU、DirectML、CUDA、云端 provider 或其他 provider 的真实可用性。
- Provider 降级路径和网络断开表现。

## 11. 明显性能风险

- 当前开发机没有 CUDA 工具链；不能规划 CUDA-first 路线。
- DirectML 仍为 `unknown`；需要 M4-002 单独 probe。
- ONNX Runtime 当前只显示 CPU/Azure providers；未显示 DirectML provider。
- C: 盘剩余约 31.46 GB，后续模型文件和缓存要避免压满系统盘。
- 默认麦克风/扬声器和采样率未知；真实设备选择需要人工确认。
- 当前探测没有任何模型推理 Benchmark，不能承诺实时 STT。

## 12. M4-002 所需输入

当前事实：M4-002 可以使用本报告作为 `DEVELOPMENT_SERVER_BASELINE`，机器人主机性能不再是当前 M4 前置输入。

M4-002 开始前至少需要：

- Provider 插件式接口草案。
- 测试 fixture 规范：合成音频、开发人员显式录制语音、明确授权非真实儿童音频、静音、噪声、短句、长句、无意义音频。
- 云端 Key 环境变量命名；缺失时输出 `CLOUD_CREDENTIALS_PENDING`。
- Benchmark JSON schema 和 Markdown 报告模板。
- 是否保存转写文本、音频片段和云端响应的开发阶段日志策略。

## 13. 安全结论

当前事实：本轮没有安装或下载任何内容。

当前事实：本轮没有调用外部 API，也没有发送硬件信息到外部服务。

当前事实：本轮没有修改 `frontend/src/`、`backend/src/` 或训练业务逻辑。

当前事实：本轮没有录制麦克风、没有保存音频、没有采集真实儿童语音。

当前事实：M4 后续开发阶段允许用授权测试音频/文本测试云端 STT/TTS；这不代表最终产品真实儿童数据上云已获批。
