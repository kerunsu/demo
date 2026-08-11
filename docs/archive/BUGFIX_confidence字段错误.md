# 🐛 Bug修复：'confidence' 字段错误

## 问题描述

应用运行时出现错误：
```
pose_matcher - ERROR - 提取特征失败: 'confidence'
```

## 根本原因

**关键点格式不匹配**：

1. **Real 分析器**（MediaPipe）生成的关键点格式：
   ```python
   {
       'x': ...,
       'y': ...,
       'visibility': ...,  # ✅ 使用 'visibility'
       ...
   }
   ```

2. **Mock 分析器**生成的关键点格式：
   ```python
   {
       'x': ...,
       'y': ...,
       'confidence': ...,  # ✅ 使用 'confidence'
       ...
   }
   ```

3. **问题场景**：
   - 用户配置了 `pose` 分析器为 `'real'` 模式
   - 但 `pose` 比对器可能还是 `'mock'` 模式（继承 `global.mode`）
   - 当 `MockPoseMatcher` 处理 `RealPoseAnalyzer` 的结果时，试图访问 `kp['confidence']`
   - 但 Real 关键点只有 `'visibility'` 字段，导致 `KeyError: 'confidence'`

## 修复内容

### 1. 修复 `MockPoseNormalizer.normalize` 方法

**文件**: `app/core/vision/pose_analyzer.py`

```python
# 修复前
'confidence': kp['confidence']  # ❌ 如果关键点没有 confidence 会报错

# 修复后
# 兼容两种格式：Mock 使用 'confidence'，Real 使用 'visibility'
confidence = kp.get('confidence') or kp.get('visibility', 0.5)
'confidence': confidence  # ✅ 兼容两种格式
```

### 2. 修复 `MockPoseNormalizer.compute_similarity` 方法

```python
# 修复前
if kp1['confidence'] > 0.5 and kp2['confidence'] > 0.5:  # ❌

# 修复后
conf1 = kp1.get('confidence', kp1.get('visibility', 0))
conf2 = kp2.get('confidence', kp2.get('visibility', 0))
if conf1 > 0.5 and conf2 > 0.5:  # ✅
```

### 3. 修复 `MockPoseMatcher._get_match_details` 方法

**文件**: `app/core/matchers/pose_matcher.py`

```python
# 修复前
if child_kp.get('confidence', 0) > 0.5 and target_kp.get('confidence', 0) > 0.5:  # ❌

# 修复后
# 兼容两种格式：Mock 使用 'confidence'，Real 使用 'visibility'
conf1 = child_kp.get('confidence') or child_kp.get('visibility', 0)
conf2 = target_kp.get('confidence') or target_kp.get('visibility', 0)
if conf1 > 0.5 and conf2 > 0.5:  # ✅
```

### 4. 添加模式不匹配警告

**文件**: `app/core/pipelines/vision_pipeline.py`

在创建比对器时，如果比对器模式为 Mock 但分析器模式为 Real，会输出警告：

```python
if matcher_mode == AnalyzerMode.MOCK and pose_mode == AnalyzerMode.REAL:
    logger.warning(
        "姿态比对器模式为 Mock，但分析器为 Real，"
        "可能导致格式不匹配。建议设置比对器模式为 Real"
    )
```

## 修复后的行为

现在系统可以：
- ✅ **兼容两种关键点格式**：自动识别 `'confidence'` 或 `'visibility'` 字段
- ✅ **避免格式不匹配错误**：即使分析器和比对器模式不一致，也能正常工作
- ✅ **输出警告信息**：提醒用户模式不匹配可能导致的问题

## 最佳实践

**建议配置**：确保分析器和比对器使用相同的模式：

```yaml
# config/analyzers.yaml
analyzers:
  pose:
    mode: real  # ✅ 使用 Real 模式

matchers:
  pose:
    mode: real  # ✅ 也使用 Real 模式，保持一致
```

或者通过环境变量：
```bash
USE_REAL_ANALYZERS=true python app.py
```

## 验证

修复后，应用应该能够：
- ✅ 不再出现 `'confidence'` KeyError 错误
- ✅ 即使模式不匹配也能正常工作（但建议保持一致）
- ✅ 日志中会显示模式不匹配的警告（如果存在）

## 注意事项

1. **性能影响**：虽然修复后可以兼容两种格式，但建议保持分析器和比对器模式一致，以获得最佳性能
2. **数据准确性**：`'confidence'` 和 `'visibility'` 虽然语义相似，但数值范围可能不同，建议统一使用 Real 模式
3. **向后兼容**：修复后的代码向后兼容，不会影响现有的 Mock 模式使用

