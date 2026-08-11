# Bug修复总结

## 🐛 已修复的问题

### 问题1：多次点击后儿童端无法加载图片（404错误）
**症状**：
- 多次点击课程项后，儿童端报错 `GET http://127.0.0.1:8080/static/resources/images/voice/205/ 404 (NOT FOUND)`
- 访问的是文件夹路径而不是具体文件路径

**根本原因**：
- PlayResourceHandler 在异常情况下返回 `None`
- events.py 处理 `None` 时没有正确传递 `resolvedFile`
- 前端 fallback 到 `item.file`，但这是文件夹路径（以 `/` 结尾）

**修复方案**：
1. ✅ 统一返回格式：所有情况都返回 `{session_id, resolved_file}` 字典
2. ✅ 处理非文件夹路径：当 `media_file` 不以 `/` 结尾时，直接使用该路径
3. ✅ 保存到Session：将 `resolved_file_path` 存储在 Session 对象中

### 问题2：点击提问/表扬时切换图片
**症状**：
- 同一个 item，只是点击提问或表扬按钮时，图片会重新随机选择
- 应该保持当前图片不变

**根本原因**：
- 每次 `play_resource` 事件都创建新会话并重新随机选择文件
- 没有检测是否是 aux 操作（只改变音频，不改变图片）

**修复方案**：
1. ✅ aux 操作检测：检查是否存在相同 `courseId` + `itemId` 的活动会话
2. ✅ 复用会话和文件：如果是 aux 操作，直接返回已有会话的 `resolved_file_path`
3. ✅ 标记 aux 操作：在返回数据中添加 `is_aux_operation` 标志

## 📝 修改的文件

### 1. `app/session/session_model.py`
```python
# 新增字段
resolved_file_path: Optional[str] = None  # 实际播放的文件路径（随机选择后的）
```

**作用**：存储随机选择的文件路径，供 aux 操作复用

### 2. `app/sockets/handlers.py`
#### 改动1：aux 操作检测
```python
# 检查是否是aux操作（同一个item，只是aux参数变化）
if course_id and item_id and aux:
    # 查找最近的相同courseId和itemId的活动会话
    all_sessions = session_manager.get_all_sessions()
    for sess in all_sessions:
        if (sess.course_id == course_id and 
            sess.course_item_id == item_id and 
            sess.is_active() and
            sess.resolved_file_path):
            # 复用已有会话
            return {
                'session_id': sess.session_id,
                'resolved_file': sess.resolved_file_path,
                'is_aux_operation': True
            }
```

#### 改动2：处理非文件夹路径
```python
if is_folder_path(media_path):
    resolved_file = get_random_file_from_folder(media_path)
else:
    # 不是文件夹路径，直接使用
    resolved_file = media_path
```

#### 改动3：保存到会话
```python
if resolved_file:
    session.resolved_file_path = resolved_file
    session_manager.update_session(session)
```

#### 改动4：统一返回格式
```python
# 成功情况
return {
    'session_id': session.session_id,
    'resolved_file': resolved_file
}

# 失败情况
return {
    'session_id': None,
    'resolved_file': None
}
```

### 3. `app/sockets/events.py`
```python
# 统一处理字典格式
session_id = result.get('session_id')
resolved_file = result.get('resolved_file')
is_aux_op = result.get('is_aux_operation', False)

if session_id:
    forward_data = data.copy()
    forward_data['sessionId'] = session_id
    if resolved_file:
        forward_data['resolvedFile'] = resolved_file
        logger.info(
            "转发%s: session_id=%s, file=%s",
            "aux操作" if is_aux_op else "新资源",
            session_id, resolved_file
        )
```

## 🧪 测试验证

### 测试场景1：正常播放命名课程
1. 教师端点击"猫"
2. 儿童端应显示 `resources/images/naming/001/` 中的随机图片
3. ✅ 不应该访问文件夹路径
4. ✅ 应该访问具体文件路径（如 `001/003.jpg`）

### 测试场景2：多次点击同一item
1. 教师端连续点击"猫"10次
2. 每次应显示不同的随机图片
3. ✅ 不应该出现404错误
4. ✅ 所有图片都应成功加载

### 测试场景3：aux操作（提问/表扬）
1. 教师端点击"猫"（显示图片A）
2. 点击"提问"按钮
3. 儿童端应**保持图片A不变**，只播放问题音频
4. 点击"表扬"按钮
5. 儿童端应**仍然保持图片A不变**，只播放表扬音频
6. ✅ 图片不应该切换

### 测试场景4：切换item
1. 教师端点击"猫"（显示图片A）
2. 点击"狗"
3. 儿童端应显示新的图片B（从狗文件夹随机选择）
4. ✅ 应该是新的会话和新的文件

## 🔍 日志检查点

启动应用后，在日志中应该看到：

**正常播放**：
```
随机选择资源: resources/images/naming/001/ -> resources/images/naming/001/003.jpg
转发新资源: session_id=xxx, file=resources/images/naming/001/003.jpg
```

**aux操作**：
```
检测到aux操作，复用会话: session_id=xxx, file=resources/images/naming/001/003.jpg
转发aux操作: session_id=xxx, file=resources/images/naming/001/003.jpg
```

**单个文件路径**：
```
使用单个文件: resources/images/mimic/pose_1.png
```

## ⚠️ 注意事项

1. **会话生命周期**：aux 操作依赖活动会话（`is_active()`），如果会话已结束，会创建新会话并重新随机选择
2. **并发问题**：如果同时有多个相同 item 的会话，会复用最先找到的那个
3. **向后兼容**：如果 CourseItem 的 `media_file` 不以 `/` 结尾，直接作为文件路径使用（支持旧数据）

## 🎯 预期效果

- ✅ **不再出现404错误**：所有文件路径都是具体文件，不是文件夹
- ✅ **aux操作不切换图片**：同一item的提问/表扬保持当前图片
- ✅ **随机性保持**：每次点击新item或不同item时，仍然随机选择
- ✅ **向后兼容**：支持单个文件路径和文件夹路径两种格式

---

## 🚀 启动测试

```bash
# 启动服务器
python app.py

# 访问
# 教师端: http://127.0.0.1:8080/therapist
# 儿童端: http://127.0.0.1:8080/child

# 测试步骤：
# 1. 教师端选择学生
# 2. 点击命名课程中的"猫"（多次点击，观察图片是否随机）
# 3. 点击"提问"按钮（观察图片是否保持不变）
# 4. 点击"表扬"按钮（观察图片是否保持不变）
# 5. 切换到"狗"（观察是否显示新图片）
# 6. 重复测试10次以上，确认无404错误
```

## 📊 技术细节

### aux操作判断逻辑
```python
is_aux_operation = (
    有相同courseId AND
    有相同itemId AND
    有aux参数（question/praise/hint） AND
    存在活动会话 AND
    会话已有resolved_file_path
)
```

### 返回数据结构
```python
{
    'session_id': str,           # 会话ID
    'resolved_file': str,        # 实际文件路径
    'is_aux_operation': bool     # 是否是aux操作（可选）
}
```

### 前端使用优先级
```javascript
const actualFile = payload.resolvedFile || item.file;
imageEl.src = "/static/" + actualFile;
```
