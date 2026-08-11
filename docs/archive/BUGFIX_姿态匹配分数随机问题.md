# 🐛 Bug修复：姿态匹配分数随机问题

## 问题描述

在我重构代码后，姿态匹配算法的分数变得不准，有点随机。

## 根本原因

**配置管理器的默认模式设置错误**：

1. **之前的代码**：
   ```python
   use_real = os.environ.get('USE_REAL_ANALYZERS', 'true').lower() == 'true'
   ```
   默认值为 `'true'`，即默认使用 **Real 模式**（真实 MediaPipe 模型）

2. **新配置管理器**（修复前）：
   ```python
   'global': {
       'mode': 'mock',  # 默认使用 Mock 模式 ❌
   }
   ```
   默认值为 `'mock'`，导致使用了 **Mock 分析器**（返回随机数据）

3. **环境变量处理**：
   ```python
   global_mode = os.environ.get('USE_REAL_ANALYZERS', '').lower()  # 默认为空
   ```
   如果环境变量未设置，默认为空字符串，导致判断为 Mock 模式

## 修复内容

### 1. 修改默认配置模式

**文件**: `app/core/config_manager.py`

```python
def _get_default_config(self) -> Dict[str, Any]:
    return {
        'global': {
            'mode': 'real',  # ✅ 改为默认使用 Real 模式（与之前的行为保持一致）
            ...
        },
        ...
    }
```

### 2. 修改环境变量默认值

```python
def _apply_env_overrides(self) -> None:
    # ✅ 改为默认 'true'，保持与之前代码的兼容性
    global_mode = os.environ.get('USE_REAL_ANALYZERS', 'true').lower()
    if global_mode == 'true':
        self._config['global']['mode'] = 'real'
    elif global_mode == 'false':
        self._config['global']['mode'] = 'mock'
```

### 3. 修改属性默认值

```python
@property
def global_mode(self) -> AnalyzerMode:
    mode_str = self._config.get('global', {}).get('mode', 'real')  # ✅ 默认 real
    return AnalyzerMode.REAL if mode_str == 'real' else AnalyzerMode.MOCK
```

## 修复后的行为

现在配置管理器的行为与之前的代码保持一致：

- ✅ **默认使用 Real 模式**（MediaPipe 真实模型）
- ✅ **环境变量 `USE_REAL_ANALYZERS=true`** 显式启用 Real 模式
- ✅ **环境变量 `USE_REAL_ANALYZERS=false`** 使用 Mock 模式
- ✅ **配置文件 `config/analyzers.yaml`** 可以覆盖默认设置

## 验证

修复后，应用应该能够：
- ✅ 默认使用真实的 MediaPipe 姿态分析器
- ✅ 返回准确的姿态匹配分数（不再是随机值）
- ✅ 保持与之前代码行为的兼容性

## 如何确认修复成功

1. **查看启动日志**：
   ```
   配置加载完成，全局模式: AnalyzerMode.REAL
   使用 Real 姿态分析器
   ```

2. **测试匹配分数**：
   - 应该返回稳定的、有意义的分数（如 0.85, 0.92 等）
   - 不再是随机值（如每次测试结果差异很大）

3. **检查使用的分析器**：
   ```python
   from app.core import get_config_manager
   config_mgr = get_config_manager()
   print(config_mgr.global_mode)  # 应该显示 AnalyzerMode.REAL
   ```

## 注意事项

1. **如果想使用 Mock 模式**，需要明确设置：
   ```bash
   USE_REAL_ANALYZERS=false python app.py
   ```
   或在 `config/analyzers.yaml` 中设置 `global.mode: mock`

2. **配置文件优先级**：
   - 环境变量 > 配置文件 > 默认配置
   - 可以通过 `config/analyzers.yaml` 灵活控制每个分析器的模式

3. **向后兼容**：
   - 修复后的行为与之前的代码完全一致
   - 不会影响现有的部署和配置

