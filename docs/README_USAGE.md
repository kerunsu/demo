# E.I.Art Doll - RobotMoveManager V3.0 使用指南

## 📋 系统概述

教育互动艺术玩偶系统，支持通过姿态检测控制机械臂，具备完整的动作录制、四级课程映射和外部系统集成功能。

## 🚀 启动服务

```bash
cd doll
node server.js
```

访问：http://localhost:3000

## 📖 V3.0 新特性

### ✨ 多视图界面
- **实时控制**：姿态检测、动作录制
- **动作库**：管理已录制动作
- **课程映射**：四级动作映射配置

### 🎯 四级映射系统
查找优先级（高→低）：
1. **项目级**：特定学生+课程+项目
2. **学生-课程级**：特定学生+课程
3. **课程级**：特定课程
4. **默认级**：通用动作（表扬/提示/提问/仅展示）

### 🔄 自动回归
动作播放完成后自动返回静态姿势（延迟500ms）

### 🎲 多动作随机选择
每个映射可配置多个动作，系统随机选择播放

## 快速开始

### 1️⃣ 录制动作
1. 切换到"实时控制"标签
2. 点击"START SYSTEM"，允许摄像头访问
3. 按 `T` 键校准姿态
4. 点击"START RECORDING"，执行动作
5. 点击"STOP & SAVE"，输入名称保存

### 2️⃣ 配置映射
1. 切换到"课程映射"标签
2. 在"通用动作设置"中：
   - 设置静态姿势
   - 为4种动作类型添加动作
3. 根据需要配置课程级/学生级/项目级动作

### 3️⃣ 外部集成
发送HTTP POST请求触发动作：

```python
import requests

requests.post('http://localhost:3000/api/course-event', json={
    "action": "play",
    "studentId": 101,
    "courseId": 1,      # 1=模仿 2=命名 3=拟声 4=配对 5=排序
    "itemId": 1,        # 可选
    "aux": {
        "praise": True,  # 表扬
        "hint": False,   # 提示
        "question": False # 提问
    }                    # 全false=仅展示
})
```

## API消息格式

### 课程触发请求
```json
{
    "action": "play",
    "studentId": 101,
    "courseId": 1,
    "itemId": 1,
    "aux": {
        "question": false,
        "praise": true,
        "hint": false
    }
}
```

### 响应
```json
{
    "success": true,
    "message": "Playing motion \"wave_hand\" (from 3 options)",
    "motion": "wave_hand",
    "auxType": "praise"
}
```

## 数据文件

### `data/course_map.json` - 映射配置
```json
{
  "defaults": {
    "idle": "static_pose",
    "praise": ["motion_praise_1", "motion_praise_2"],
    "hint": ["motion_hint_1"]
  },
  "courses": {
    "1": { "praise": ["course1_praise"] }
  },
  "students": {
    "101": {
      "1": {
        "praise": ["student101_course1_praise"],
        "items": {
          "1": { "praise": ["s101_c1_i1_praise"] }
        }
      }
    }
  }
}
```

### `data/students.json` - 学生列表
```json
[
  { "id": 101, "name": "张小明", "age": 6, "grade": "一年级" }
]
```

### `data/courses.json` - 课程信息
从主项目根目录的`courses.json`复制，包含课程和项目列表。

### `data/motions.json` - 录制的动作
存储时间序列帧数据。

## 主要API端点

### 动作管理
- `GET /api/motions` - 列出所有动作
- `POST /api/motions` - 保存动作
- `DELETE /api/motions/:name` - 删除动作
- `POST /api/play/:name` - 播放动作

### 映射配置
- `GET /api/mapping/full` - 获取完整配置
- `PUT /api/mapping/idle` - 设置静态姿势
- `PUT /api/mapping/defaults/:auxType` - 更新通用动作
- `PUT /api/mapping/course/:courseId/:auxType` - 更新课程级
- `PUT /api/mapping/student/:sid/course/:cid/:auxType` - 更新学生-课程级
- `PUT /api/mapping/item/:sid/:cid/:iid/:auxType` - 更新项目级

### 基础数据
- `GET /api/students` - 学生列表
- `GET /api/courses` - 课程列表

### 课程触发
- `POST /api/course-event` - **主要集成端点**

## 配置示例

### 场景：为课程1（模仿）配置动作

1. **通用动作**（所有学生共用）
   - 通用表扬：`praise_clap`, `praise_thumbup`
   - 静态姿势：`idle_pose`

2. **课程级**（课程1专属）
   - 表扬：`mimic_praise_1`, `mimic_praise_2`

3. **学生级**（学生101在课程1）
   - 表扬：`student101_special_praise`

4. **项目级**（学生101,课程1,项目1）
   - 表扬：`s101_c1_i1_excellent`

**触发效果**：
```python
# 项目1表扬 → 播放 s101_c1_i1_excellent
trigger_robot(101, 1, 1, praise=True)

# 项目2表扬（未单独配置）→ 播放 student101_special_praise  
trigger_robot(101, 1, 2, praise=True)

# 其他学生项目1表扬 → 播放 mimic_praise_1 或 mimic_praise_2
trigger_robot(102, 1, 1, praise=True)
```

## 常见问题

**Q: 提示"No motion mapped"？**  
A: 至少需要配置defaults级别的通用动作。

**Q: 动作不播放？**  
A: 确认DollSer程序正在运行，监听端口12000。

**Q: 如何查看当前配置？**  
A: 访问 `GET /api/mapping/full` 或在前端"课程映射"标签查看。

**Q: 多个动作如何选择？**  
A: 系统随机选择列表中的一个动作播放。

## 技术架构

```
浏览器(TensorFlow.js)  →  Socket.io  →  Node.js服务器
                                            ↓
                                    MappingResolver
                                            ↓
                                      OSC协议
                                            ↓
                                DollSer(C++硬件控制)
                                            ↓
                                        舵机控制
```

## 开发测试

```bash
# 启动服务器
node server.js

# 测试API
python test_simple.py

# 完整测试
node test-api.js
```

## 注意事项

1. 动作名称使用英文+数字，如 `praise_wave_01`
2. 高优先级配置完全覆盖低优先级
3. 建议至少配置默认级的4种动作类型
4. 静态姿势应设置为自然姿态
5. DollSer必须运行才能控制硬件
