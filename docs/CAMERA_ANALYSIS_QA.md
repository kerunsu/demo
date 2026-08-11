# 摄像头 / 注意力·情绪验收清单

配置：`config/camera_analysis.yaml`、`config/analyzers.yaml`。

## 生产路径（推荐）：`CHILD_MEDIA_MODE=agent`

1. 后端 `.env`：`CHILD_MEDIA_MODE=agent`，`ROBOT_CONTROL_MODE=robot_runtime`。
2. 机器人机运行 `RobotRuntime`，浏览器打开后端 `/child`（**不要**期望本页 `getUserMedia`）。
3. 上课后后端应对上行帧做 **Real 窗口注意力**，并写入 `record_attention(provider=server)` + `record_emotion(provider=server)`。
4. 儿童端控制台应出现「Agent 模式跳过浏览器摄像头分析」，**不应**依赖 `[camera_analysis] 已启动`。
5. 报告：注意力曲线有分；情绪三色条在有人脸时有样本（≥ `emotion_min_samples`）。
6. 教师端实时注意力为 0–100，且不应与无效 0 分交替跳变。

## 联调捷径：`CHILD_MEDIA_MODE=browser`

仅本机单机测试：

1. 重启后端，儿童端强制刷新。
2. 控制台可出现 `[camera_analysis] 已启动`（C2 JS，参考计分）。
3. 正中单脸：浏览器描述符可进 behavior；仅当 `prefer_browser_when_media_mode_browser: true`（默认）时报告优先有效 browser 样本。
4. 关闭摄像头：情绪「数据不足」，页面不崩溃。

## 策略说明

| 项 | 生产 agent | 联调 browser |
|----|------------|--------------|
| 采流 | robot_runtime | /child getUserMedia |
| 注意力/情绪 | 服务端 Real + `server-emotion-v1` | 可选 C2 JS |
| `prefer_browser_for_report` | 默认 `false` | 由 mediaMode 动态优先 browser |
| Mock | 保留；Real 创建失败回退并打日志 | 可用 `USE_REAL_ANALYZERS=false` |

## 降级

- agent 下不再向 behavior 刷 `missing_device` browser 观测。
- face 分析器无 Real 实现 → Registry 回退 Mock。
- Real 注意力/语音模型缺失 → 创建失败回退 Mock，日志含「回退 Mock」。
