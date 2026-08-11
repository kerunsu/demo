# 21. Session 数据集契约

## 目录与历史名称

目录选择继续由现有 recording timeline registry 决定，历史兼容文件名不得修改：

| 语义 | 兼容文件 |
|---|---|
| 儿童主视频 | `video.avi` |
| 儿童/机器人定向主音频 | `audio.wav` |
| 第一条 primary environment 视频 | `video.environment.avi` |
| 第一条 primary environment 音频 | `audio.environment.wav` |
| 全场段落时间轴 | `timeline.csv` |
| 会话元数据 | `session_meta.json` |
| 晚到补传归档信息 | `archive_meta.json` |

新增环境轨使用 `video.environment.{trackId}.avi` 或 `audio.environment.{trackId}.wav`。`trackId` 来自稳定设备身份，必须经过文件名安全化；MP4 只能是完成后的派生导出，不能替换 AVI/WAV 兼容轨。

## `session_meta.json`

保留既有字段（`mediaSessionId`、`trainingSessionId`、`humanDirName`、`studentId`、`n`、`status`、`recordingStartedAt`、`recordingStartedAtUnix`、`durationSec`、`recordingMode`、`segCount`）。扩展字段使用 `tracks` 清单：

```json
{
  "trackId": "ambient-cam-a-<stable-hash>",
  "kind": "video",
  "role": "primary_environment",
  "deviceId": "ambient-cam-a",
  "runtimeId": null,
  "required": true,
  "filename": "video.environment.avi",
  "format": "avi",
  "clockDomain": "server.monotonic"
}
```

主/环境轨共享一个 media session 的相对时间轴；切题只追加 `timeline.csv` 段，不 stop/start 任何主轨。课程结果、行为、报告、评分和历史字段继续由原有实现写入，第三阶段不重命名或重排它们。

## 写入规则

新 repository 的 JSON/CSV 写入先写同目录临时文件、flush/fsync，再 `os.replace`；失败时清理临时文件但不删除已有有效文件。`FileMetadataRepository.merge` 在进程内加锁并保留未更新字段。`FileTimelineRepository` 拒绝倒退或结束早于开始的时间，追加新段时按旧语义闭合前一开放段。`FileRecordingRepository` 用单调时钟计算未闭合会话时长，避免 finalize 写出零时长。`validate_session_directory` 只读，并检查 manifest 类型、重复/不安全轨名、时间倒退与重叠；不修复、不删除、不创建目录。
