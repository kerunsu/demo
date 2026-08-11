# 语音系统问题修复验证清单

## 问题列表

### ✅ 问题3: YAML文件名格式错误
**问题**: 文件名应该是 `001.mp3` 而不是 `1.mp3`
**修复**: 使用 `tools/maintenance/fix_audio_yaml.py` 批量修复了142个文件路径
**验证**: 检查 `config/audio_manifest.yaml` 中的路径格式

### ✅ 问题4: trigger_action 空音频字段
**问题**: `_execute_play_audio` 只查找 `audio` 字段，但 `play_interest_content` 使用 `content` 字段
**修复**: 修改 `app/core/actions.py:381` 同时支持 `audio` 和 `content` 字段
```python
audio_path = action.payload.get('audio') or action.payload.get('content', '')
```

### ✅ 问题5: 教师端按钮应直接触发语音
**问题**: 教师点击"提问"、"表扬"按钮应该自动播放对应语音
**修复**: 
1. 创建新的 WebSocket 事件 `trigger_audio` (`app/sockets/audio_events.py`)
2. 修改教师端按钮，添加语音触发逻辑 (`teacher_frontend/components/ControlPage.tsx`)
3. 从 PlayResourceHandler 中移除语音播放逻辑（因为应该由按钮触发）

### ⚠️ 问题1: 教师端音频控制面板不可见
**状态**: 代码已添加（ControlPage.tsx:1050），需要验证
**检查项**:
- [ ] React前端是否已重新编译 (`npm run dev`)
- [ ] `audioStatus.isPlaying` 状态是否正确更新
- [ ] 是否收到 `audio_status_update` 事件

### ⚠️ 问题2: 音频没有成功播放
**状态**: 需要测试新的 trigger_audio 流程
**检查项**:
- [ ] 后端是否收到 `trigger_audio` 事件
- [ ] 是否发送 `play_audio` 到儿童端
- [ ] 儿童端 AudioPlayer 是否收到事件
- [ ] 浏览器控制台是否有错误

## 测试流程

### 测试1: 验证YAML文件格式
```powershell
# 检查YAML中的文件路径
Select-String -Path "config\audio_manifest.yaml" -Pattern 'path: ".*/\d\.mp3"'
# 应该没有任何匹配（所有路径都应该是3位数）
```

### 测试2: 验证trigger_action音频字段
1. 启动后端: `python app.py`
2. 打开儿童端: `http://127.0.0.1:8080/`
3. 观察控制台，注意力触发器应该显示音频路径而不是空字符串

### 测试3: 验证教师端按钮语音触发
1. 启动后端: `python app.py`
2. 启动React前端: `cd teacher_frontend && npm run dev`
3. 登录 → 选择学生 → 选择课程 → 开始训练
4. **教师端操作**: 点击"提问"按钮
5. **预期结果**: 
   - 教师端控制台: `emit trigger_audio {session_id, action: 'question', course_type}`
   - 儿童端收到 `play_audio` 事件
   - 儿童端播放问题语音（根据课程类型从 course_defaults 查找）
6. **教师端操作**: 点击"表扬"按钮
7. **预期结果**: 播放表扬语音

### 测试4: 验证音频控制面板显示
1. 执行测试3，点击提问或表扬按钮
2. **预期结果**: 教师端界面顶部出现音频控制面板
3. **面板内容**: 显示当前播放的语音ID和进度条
4. **停止按钮**: 点击应该立即停止儿童端播放

## 调试命令

### 检查WebSocket事件流
**教师端浏览器控制台**:
```javascript
// 监听发送的事件
socket.on('connect', () => console.log('已连接'));
socket.on('trigger_audio', data => console.log('发送trigger_audio:', data));
socket.on('audio_status_update', data => console.log('收到状态更新:', data));
```

**儿童端浏览器控制台**:
```javascript
// 监听接收的事件
socket.on('play_audio', data => console.log('收到play_audio:', data));
socket.on('stop_audio', data => console.log('收到stop_audio:', data));
```

**后端日志**:
```powershell
# 查看最新日志
Get-Content logs\app.log -Tail 50 -Wait
```

### 手动测试trigger_audio事件
在教师端浏览器控制台:
```javascript
socket.emit('trigger_audio', {
  session_id: 'your_session_id_here',
  action: 'question',
  course_type: 'naming'  // 或 'onomatopoeia', 'mimic', 'pairing', 'ordering'
});
```

## 预期日志输出

### 后端 (logs/app.log)
```
[audio_events] 教师触发语音播放 - 会话: xxx, 动作: question, 课程类型: naming
[audio_events] 已发送语音播放指令到儿童端: question
[audio_emitter] 为课程选择语音 - 课程类型: naming, 动作: question
[audio_emitter] 发送语音播放事件 - 房间: session_xxx_child, 条目: attention_whats_this
```

### 教师端控制台
```
发送 trigger_audio: {session_id: "xxx", action: "question", course_type: "naming"}
收到 audio_status_update: {session_id: "xxx", status: "playing", entry_id: "attention_whats_this", progress: 0}
```

### 儿童端控制台
```
收到 play_audio: {entry_id: "attention_whats_this", file_path: "resources/audios/016/001.mp3", priority: 5}
[AudioPlayer] 开始播放: resources/audios/016/001.mp3
[AudioPlayer] 播放成功，时长: 2.5s
```

## 下一步计划

1. ✅ 完成所有修复
2. ⏳ 测试验证（进行中）
3. 📝 Phase 5: 完善 audio_manifest.yaml（添加更多语音）
4. 📝 Phase 6: 性能优化和文档

## 相关文件

- 后端事件处理: `app/sockets/audio_events.py`
- 动作执行器: `app/core/actions.py`
- 教师端UI: `teacher_frontend/components/ControlPage.tsx`
- 儿童端播放器: `static/js/audio_player.js`
- 语音清单: `config/audio_manifest.yaml`
- 修复脚本: `tools/maintenance/fix_audio_yaml.py`
