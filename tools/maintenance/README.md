# 维护用脚本（非应用运行时依赖）

以下脚本用于课程数据、音频清单、数据库等**一次性或低频维护**，已从仓库根目录移入此处。请在**项目根目录**执行：

```bash
python tools/maintenance/check_icons.py
```

脚本内已根据 `__file__` 解析仓库根目录，无需再 `cd` 到本文件夹。

| 文件 | 说明 |
|------|------|
| `check_icons.py` | 打印课程/课程项 icon 等字段 |
| `cleanup_old_courses.py` | 交互式删除指定旧课程 ID（慎用） |
| `debug_course_items.py` | 列出课程与项目，用于调试 |
| `fix_audio_yaml.py` / `fix_audio_yaml_v2.py` | 批量修正 `config/audio_manifest.yaml` 路径格式 |
| `organize_audio_files.py` | 重组 `static/resources/audios/` 下文件结构 |
| `开发想法.txt` | 历史开发备忘 |
