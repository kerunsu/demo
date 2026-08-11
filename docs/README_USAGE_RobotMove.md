# E.I.Art Doll - RobotMoveManager 使用指南

## 📋 系统概述

这个系统现在具备完整的机械臂动作录制、管理和课程集成功能。

## 🚀 启动服务

```bash
cd doll
node server.js
```

服务启动后访问：http://localhost:3000

## 📖 功能使用流程

### 1️⃣ 录制机械臂动作

1. **启动系统**
   - 点击 "Start System" 按钮
   - 允许浏览器访问摄像头
   - 等待 TensorFlow 姿态识别模型加载完成

2. **配置参数**（可选）
   - 调整 OSC 发送频率（Rate 滑块）
   - 勾选 "OSC SEND" 开关以启用实时控制
   - 按 'T' 键校准初始姿态

3. **录制动作**
   - 点击 "START RECORDING" 按钮（红色按钮）
   - 录制状态指示灯变红，开始捕捉动作
   - 在摄像头前做出机械臂需要学习的动作
   - 点击 "STOP & SAVE" 按钮停止录制
   - 在弹出对话框中输入动作名称（如 `wave_hand`、`nod_head`）
   - 点击 "Save" 保存到动作库

4. **注意事项**
   - 录制的是动作流（时间序列），不是单帧
   - 确保光线充足，姿态识别更准确
   - 动作时长建议 2-10 秒

### 2️⃣ 管理动作库

**查看已保存的动作**
- 在 "MOTION LIBRARY" 面板中查看所有动作
- 显示动作名称、帧数、时长

**预览播放动作**
- 点击动作旁的 "PLAY" 按钮
- 机械臂会重现录制的动作
- 需要确保 DollSer（C++服务端）在运行

**删除动作**
- 点击 "DELETE" 按钮
- 确认删除后动作从库中移除

### 3️⃣ 配置课程映射

在 "COURSE MAPPING" 面板中配置课程与动作的对应关系：

1. **添加映射**
   - 在 "COURSE ID" 输入框中输入课程标识（如 `lesson_001`）
   - 在 "MOTION" 下拉框中选择对应的动作
   - 点击 "ADD / UPDATE MAPPING" 保存

2. **测试映射**
   - 点击映射项旁的 "TEST" 按钮
   - 系统会立即播放对应的动作
   - 验证映射是否正确

3. **删除映射**
   - 点击 "DELETE" 按钮移除映射关系

### 4️⃣ 外部课程系统集成

您的课程系统可以通过 HTTP API 触发机械臂动作：

**API 端点**
```
POST http://localhost:3000/api/course-event
Content-Type: application/json

{
  "courseId": "lesson_001"
}
```

**响应示例**
```json
{
  "success": true,
  "message": "Triggered motion \"wave_hand\" for course \"lesson_001\""
}
```

**集成示例（Python）**
```python
import requests

def trigger_robot_motion(course_id):
    response = requests.post(
        'http://localhost:3000/api/course-event',
        json={'courseId': course_id}
    )
    return response.json()

# 在课程播放时调用
trigger_robot_motion('lesson_001')
```

**集成示例（JavaScript/Node.js）**
```javascript
async function triggerRobotMotion(courseId) {
    const response = await fetch('http://localhost:3000/api/course-event', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ courseId })
    });
    return await response.json();
}

// 在课程播放时调用
await triggerRobotMotion('lesson_001');
```

## 🔧 REST API 文档

### 动作管理 API

#### 获取动作列表
```
GET /api/motions
```

#### 获取单个动作详情
```
GET /api/motions/:name
```

#### 保存新动作
```
POST /api/motions
Content-Type: application/json

{
  "name": "wave_hand",
  "frames": [
    { "time": 0, "pose": { "pitch": 180, "yaw": 180, "armL": 90, "armR": 90 } },
    { "time": 100, "pose": { "pitch": 200, "yaw": 180, "armL": 120, "armR": 60 } }
  ]
}
```

#### 删除动作
```
DELETE /api/motions/:name
```

#### 播放动作
```
POST /api/play/:name
```

### 课程映射 API

#### 获取所有映射
```
GET /api/course-map
```

#### 添加/更新映射
```
POST /api/course-map
Content-Type: application/json

{
  "courseId": "lesson_001",
  "motionName": "wave_hand"
}
```

#### 删除映射
```
DELETE /api/course-map/:courseId
```

#### 触发课程事件（课程系统调用）
```
POST /api/course-event
Content-Type: application/json

{
  "courseId": "lesson_001"
}
```

## 📂 数据存储

所有数据存储在 `doll/data/` 目录：

- `motions.json` - 动作库数据
- `course_map.json` - 课程映射关系

数据格式为 JSON，可以手动编辑或备份。

## 🎯 典型使用场景

### 场景 1：为新课程创建互动
1. 录制 3 个动作：`greeting`、`encourage`、`celebrate`
2. 创建映射：
   - `lesson_start` → `greeting`
   - `task_completed` → `celebrate`
   - `answer_correct` → `encourage`
3. 在课程系统中调用 API 触发

### 场景 2：动作库管理
1. 定期录制新动作扩充库
2. 预览测试每个动作效果
3. 删除不再使用的旧动作
4. 导出 `data/motions.json` 备份

## ⚠️ 注意事项

1. **确保 DollSer 运行**：机械臂接收端必须启动并监听端口 12000
2. **网络配置**：如果课程系统在其他机器，需要修改 `WEB_PORT` 和防火墙设置
3. **动作时长**：过长的动作可能占用较多内存，建议单个动作不超过 30 秒
4. **并发控制**：同时只能播放一个动作，新的播放会覆盖之前的

## 🐛 故障排查

**问题：录制后动作不播放**
- 检查 DollSer 是否运行
- 查看浏览器控制台是否有错误
- 验证 OSC 端口 12000 是否被占用

**问题：摄像头无法启动**
- 检查浏览器权限设置
- 确认摄像头未被其他程序占用
- 尝试使用 HTTPS（某些浏览器要求）

**问题：课程触发无响应**
- 确认课程 ID 已正确映射到动作
- 检查网络连接和 API 地址
- 查看服务器日志输出

## 📞 技术支持

如有问题，请检查：
1. 服务器控制台日志
2. 浏览器开发者工具 Console
3. `data/` 目录下的 JSON 文件格式

---

**版本**: V2.0  
**更新日期**: 2026-01-10
