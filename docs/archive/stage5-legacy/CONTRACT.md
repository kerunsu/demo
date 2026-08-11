# 接口契约（Socket.IO 事件字典）— v0（初稿）

> 来源：根据当前代码自动整理（服务端 `app/sockets/*`、儿童端 `static/js/child.js`、教师端 `teacher_frontend/components/ControlPage.tsx`、儿童端音频 `static/js/audio_player.js`）。
>
> 目的：作为你与协作同学的**共同维护接口规范**（Single Source of Truth）。后续如有事件变更，务必先更新本文。

---

## 0. 术语与角色

- **Teacher**：教师端（`teacher_frontend/`）
- **Child**：儿童端（`/child`，`templates/child.html` + `static/js/child.js`）
- **Server**：Flask + Socket.IO（`app.py` + `app/sockets/*`）

---

## 1. 房间（Room）与会话隔离规则

服务端在 `join_session` 中使用三类房间（见 `app/sockets/events.py`）：

- **通用房间**：`{sessionId}`（直接使用 sessionId 字符串作为 room 名）
- **角色房间（建议使用）**
  - Child：`session_{sessionId}_child`
  - Teacher：`session_{sessionId}_teacher`

### 1.1 加入房间

Teacher/Child 都应在拿到 `sessionId` 后调用：

```json
{
  "event": "join_session",
  "data": { "sessionId": "xxx", "role": "teacher|child" }
}
```

服务端回包事件：`joined_session`。

---

## 2. 字段命名约定（当前现状 + 建议）

当前代码存在两种风格并存：

- **前端上行/控制类事件**：多为 `camelCase`（如 `sessionId`, `studentId`）
- **分析/语音状态回传与反馈**：部分为 `snake_case`（如 `session_id`）

### 2.1 建议（后续逐步统一）

- **对外契约统一**：优先统一为 **camelCase**（更贴近 TS/JS）。
- 但在统一完成前：本文档会按“当前实际发送字段”写示例，并在必要处标注别名。

---

## 3. 事件字典（Event Dictionary）

每条事件包含：
- **方向**
- **用途**
- **Payload 示例**
- **房间/广播规则**

### 3.1 连接管理

#### `connect`（系统事件）
- **方向**：Client → Server
- **用途**：建立连接

#### `connected`
- **方向**：Server → Client
- **用途**：连接成功确认

Payload 示例：

```json
{ "status": "ok", "sid": "socket_id" }
```

---

### 3.2 会话房间

#### `join_session`
- **方向**：Teacher/Child → Server
- **用途**：加入会话房间（通用 + 角色房间）

Payload 示例：

```json
{ "sessionId": "S123", "role": "teacher" }
```

#### `joined_session`
- **方向**：Server → Teacher/Child

Payload 示例：

```json
{ "sessionId": "S123", "role": "teacher", "status": "ok" }
```

#### `leave_session`
- **方向**：Teacher/Child → Server

Payload 示例：

```json
{ "sessionId": "S123" }
```

---

### 3.3 教师进入/离开控制界面（影响儿童端待机图）

#### `teacher_enter_control`
- **方向**：Teacher → Server → (broadcast) → Child

Payload 示例：

```json
{ "status": "enter" }
```

#### `teacher_leave_control`
- **方向**：Teacher → Server → (broadcast) → Child

Payload 示例：

```json
{ "status": "leave" }
```

> 备注：当前实现为 broadcast；如果未来需要“按会话隔离”，可改为带 `sessionId` 并 room 转发。

---

### 3.4 播放资源（核心控制事件）

#### `play_resource`

- **方向（请求）**：Teacher → Server
- **方向（转发/回包）**：Server → (broadcast) → Child + Teacher
- **用途**：开始播放某课程/子项，并可携带 aux（提问/表扬/提示）与分析用的辅助信息。

Teacher 发送示例（来自 `ControlPage.tsx`）：

```json
{
  "action": "play",
  "studentId": 1,
  "courseId": 101,
  "itemId": 1001,
  "courseType": "naming",
  "aux": {
    "question": true,
    "praise": false,
    "hint": false,
    "targetImage": "resources/images/xxx.png",
    "targetText": "苹果"
  }
}
```

Server 转发增强字段（来自 `app/sockets/events.py`）：

```json
{
  "action": "play",
  "studentId": 1,
  "courseId": 101,
  "itemId": 1001,
  "sessionId": "S123",
  "trainingSessionId": "T456",
  "questionId": "101_1001_0",
  "resolvedFile": "resources/images/xxx.png",
  "mediaMode": "agent",
  "recordingMode": "continuous",
  "humanDirName": "张小明-6-20260713-1"
}
```

- `sessionId`：整场 **media session**（与 `prepare_training` 相同；切题不换）
- `recordingMode`：`continuous`（方案 B）；儿童端切题不得 `/record/stop`→`/record/start`
- `humanDirName`：落盘目录名 `姓名-年龄-日期-N`
- aux 操作：复用同一 `sessionId`，不新建时间轴段、不启停录制
- `resolvedFile`：当课程项指向文件夹时，服务端随机挑选出的真实文件路径（用于 Teacher 展示缩略图、用于 Child 实际播放）
- `praiseVideo`：表扬时可选视频（Child 播放后应上报 `praise_video_ended`）

落盘（方案 B）：

- 目录：`static/recordings/sessions/{姓名-年龄-YYYYMMDD-N}/`
- 文件：`video.avi`、`audio.wav`、`timeline.csv`、`session_meta.json`
- 对照表：`static/recordings/course_type_lookup.csv`、`course_item_lookup.csv`（`python -m tools.export_recording_lookups`）
- 详设：[`CONTINUOUS_RECORDING_TIMELINE_PLAN.md`](CONTINUOUS_RECORDING_TIMELINE_PLAN.md)

---

### 3.5 媒体采集上行（儿童端录制）

支持两种模式（`CHILD_MEDIA_MODE` / `play_resource.mediaMode`）：

| 模式 | 采集端 | 上行路径 |
|------|--------|----------|
| `browser`（默认） | 儿童页 `getUserMedia` | Socket.IO `video_frame` / `audio_chunk` |
| `agent` | 本机 Robot Runtime 独占设备 | HTTP `POST /api/media/<sessionId>/frames` 与 `/audio-chunks`；结束后 `/upload` 补传 |

机械臂跨机控制请使用 `ROBOT_CONTROL_MODE=robot_runtime`（后端直连 Runtime `/osc/*`），见 [ROBOT_RUNTIME.md](ROBOT_RUNTIME.md)。

详见 [CHILD_MEDIA_AGENT.md](CHILD_MEDIA_AGENT.md) / [ROBOT_RUNTIME.md](ROBOT_RUNTIME.md)。

#### `video_frame`
- **方向**：Child → Server（仅 browser 模式）
- **用途**：上传视频帧（base64 JPEG）

Payload 示例（来自 `child.js`）：

```json
{
  "sessionId": "S123",
  "frame": "BASE64_JPEG_NO_PREFIX",
  "timestamp": 1710000000000
}
```

#### `audio_chunk`
- **方向**：Child → Server（仅 browser 模式）
- **用途**：上传音频块（base64 PCM/Int16 buffer）

Payload 示例：

```json
{
  "sessionId": "S123",
  "chunk": "BASE64_PCM_INT16",
  "timestamp": 1710000000000
}
```

#### HTTP 实时上行（agent 模式）

- `POST /api/media/<sessionId>/frames` — `{ frame, seq?, timestamp? }` 或 `{ frames: [...] }` → `{ ok, accepted, lastSeq }`
- `POST /api/media/<sessionId>/audio-chunks` — `{ chunk, seq?, timestamp? }` 或 `{ chunks: [...] }` → `{ ok, accepted, lastSeq }`
- 可选请求头：`X-Child-Media-Agent-Key`（当服务端配置了 `CHILD_MEDIA_AGENT_KEY`）

#### HTTP 会话补传（agent 模式）

- `POST /api/media/<sessionId>/upload` — multipart：`video` / `audio` 文件；可选 `sha256_video` / `sha256_audio` / `duration`
- 服务端将已有实时落盘文件改名为 `*.realtime.*`，以补传文件为归档权威，并写 `archive_meta.json`（`source=agent_local`）

#### `child_media_agent_heartbeat`
- **方向**：Child → Server
- **用途**：上报本机 Media Agent 在线状态（供 `/server` 展示）

```json
{ "agentOnline": true, "detail": {}, "ts": 1710000000000 }
```

---

### 3.6 停止录制

#### `stop_recording`
- **方向（请求）**：Teacher 或 Child → Server
- **方向（转发）**：Server → (broadcast) → Child

Payload 示例（推荐）：

```json
{ "sessionId": "S123" }
```

兼容旧格式（服务端注释中存在）：

```json
{ "action": "stop", "studentId": 1, "courseId": 101, "itemId": 1001 }
```

Child 收到后会执行本地 `stopRecording()`。

---

### 3.7 语音系统（播放/停止/状态回传）

#### `play_audio`
- **方向（正常流程）**：Server → Child
- **用途**：让 Child 播放一条语音资源（由 `AudioPlayer` 管理队列）

Payload 示例（见 `app/sockets/audio_events.py` 注释与 `audio_player.js`）：

```json
{
  "entry_id": "system.greeting.greeting_hello",
  "file_path": "resources/audios/011/001.mp3",
  "priority": 0,
  "interrupt": false
}
```

> 备注：`audio_events.py` 中也允许“测试用客户端 emit play_audio”并转发，但交接收尾后建议不要依赖该测试通道。

#### `stop_audio`
- **方向（请求）**：Teacher → Server
- **方向（下发）**：Server → Child（由 controller 触发）

Teacher 请求示例（来自 `ControlPage.tsx`）：

```json
{ "session_id": "S123", "immediate": true }
```

Child 收到示例（`audio_player.js`）：

```json
{ "immediate": true, "timestamp": 1710000000.0 }
```

#### `audio_status`
- **方向**：Child → Server
- **用途**：Child 端 `AudioPlayer` 上报播放状态（进度、错误等）

Payload 示例（来自 `audio_player.js`）：

```json
{
  "session_id": "S123",
  "status": "playing",
  "entry_id": "system.greeting.greeting_hello",
  "file_path": "resources/audios/011/001.mp3",
  "current_time": 1.0,
  "duration": 2.3
}
```

#### `audio_status_update`
- **方向**：Server → Teacher
- **用途**：服务端将 `audio_status` 转成 UI 友好的进度，推给 Teacher 控制台

Payload 示例（来自 `audio_events.py`）：

```json
{
  "session_id": "S123",
  "status": "playing",
  "entry_id": "system.greeting.greeting_hello",
  "progress": 43.5
}
```

---

### 3.8 分析/比对/触发（服务端反馈事件）

> 这些事件由 `FeedbackService` 等服务端逻辑发出；`events.py` 中仅以注释形式说明 schema。

#### `match_result`
- **方向**：Server → Teacher（Teacher 端监听并展示分数）

Payload 示例（来自 `events.py` 注释与 `ControlPage.tsx` interface）：

```json
{
  "session_id": "S123",
  "matcher_type": "pose",
  "score": 0.91,
  "passed": true,
  "threshold": 0.85,
  "timestamp": 1710000000.0,
  "details": {}
}
```

#### `attention_update`
- **方向**：Server → Teacher

Payload 示例：

```json
{
  "session_id": "S123",
  "score": 0.72,
  "state": "high",
  "trend": "stable",
  "timestamp": 1710000000.0
}
```

#### `session_summary`
- **方向**：Server → Teacher

Payload 示例（结构较大，示意）：

```json
{
  "session_id": "S123",
  "summary": {
    "duration": 12.3,
    "total_frames": 300,
    "total_chunks": 80,
    "vision_summary": [],
    "audio_summary": [],
    "statistics": { "average_attention": 0.6 }
  },
  "timestamp": 1710000000.0
}
```

#### `analysis_result`
- **方向**：Server → Teacher

Payload 示例（示意）：

```json
{
  "session_id": "S123",
  "analyzer_type": "pose|speech|attention|face",
  "data": {},
  "confidence": 0.9,
  "timestamp": 1710000000.0
}
```

#### `trigger_action`
- **方向**：Server → Child（Teacher 端也可能监听用于提示）

Payload 示例（来自 `events.py` 注释 + `child.js` 解包方式）：

```json
{
  "session_id": "S123",
  "action_type": "play_audio|play_praise|show_message",
  "target": "child|teacher|both",
  "data": { "message": "做得很好！" },
  "timestamp": 1710000000.0
}
```

---

### 3.9 互动课：配对（matching）事件

> 服务端在 `events.py` 里基本做“转发”，状态由互动页/儿童端产生后回传。

#### `matching_set_difficulty`
- **方向**：Teacher → Server → room(sessionId) → Child

```json
{ "sessionId": "S123", "difficulty": 3 }
```

#### `matching_start`
- **方向**：Teacher → Server → Child

```json
{ "sessionId": "S123" }
```

#### `matching_next`
- **方向**：Teacher → Server → Child

```json
{ "sessionId": "S123" }
```

#### `matching_hint`
- **方向**：Teacher → Server → Child

```json
{ "sessionId": "S123" }
```

#### `matching_status_update`
- **方向**：Child → Server → Teacher

```json
{
  "sessionId": "S123",
  "difficulty": 3,
  "questionIndex": 5,
  "isCorrect": true,
  "accuracy": 0.8,
  "isFinished": false
}
```

#### `matching_game_end`
- **方向**：Child → Server → Teacher

```json
{ "sessionId": "S123", "accuracy": 0.85, "total": 15, "correct": 13 }
```

---

### 3.10 互动课：排序（sequencing）事件

#### `sequencing_set_config`
- **方向**：Teacher → Server → Child

```json
{
  "sessionId": "S123",
  "autoMode": true,
  "category": "size",
  "difficulty": 2,
  "rule": "bigger"
}
```

#### `sequencing_start`
- **方向**：Teacher → Server → Child

```json
{ "sessionId": "S123" }
```

#### `sequencing_next`
- **方向**：Teacher → Server → Child

```json
{ "sessionId": "S123" }
```

#### `sequencing_hint`
- **方向**：Teacher → Server → Child

```json
{ "sessionId": "S123" }
```

#### `sequencing_status_update`
- **方向**：Child → Server → Teacher

```json
{
  "sessionId": "S123",
  "category": "size",
  "rule": "bigger",
  "isCorrect": true,
  "questionIndex": 3,
  "totalQuestions": 15,
  "stats": { "size": { "correct": 2, "wrong": 1 } }
}
```

#### `sequencing_game_end`
- **方向**：Child → Server → Teacher

```json
{
  "sessionId": "S123",
  "totalStats": { "size": { "correct": 10, "wrong": 5 } },
  "totalQuestions": 15
}
```

---

### 3.11 表扬视频结束回执

#### `praise_video_ended`
- **方向**：Child → Server → Teacher

```json
{ "sessionId": "S123" }
```

---

### 3.12 机械臂（robot）事件（可选）

#### `robot_pose_data`
- **方向**：Client → Server

```json
{ "pitch": 0.1, "yaw": -0.2, "armL": 0.3, "armR": 0.4 }
```

#### `robot_start_recording`
- **方向**：Client → Server

#### `robot_stop_recording`
- **方向**：Client → Server

```json
{ "motionName": "wave_hand" }
```

服务端回：`robot_recording_status`

#### `robot_play_motion`
- **方向**：Client → Server

```json
{ "motionName": "wave_hand" }
```

服务端回：`robot_playback_status`

#### `robot_stop_playback`
- **方向**：Client → Server

#### `robot_emotion_auto_random`
- **方向**：Server 内触发或 Client → Server
- **服务端广播**：`robot_emotion_change`

```json
{ "emotionName": "happy" }
```

---

## 4. 兼容与演进规则（建议从现在开始执行）

1. **新增字段**：只能新增为可选字段，并保证旧端缺失该字段时仍可工作。
2. **删除/改名字段或事件**：必须先在本文标注 deprecate，至少保留一个迭代周期。
3. **字段风格统一**：优先统一为 `camelCase`；在统一前，允许 snake_case 仅用于内部/历史遗留，但必须在本文写明。
4. **会话隔离优先**：涉及控制/反馈的事件，优先携带 `sessionId` 并 room 转发，避免 broadcast 造成串台风险。

