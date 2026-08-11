# 交接收尾变更摘要

- **教师端目录**：`figma_teacher_test1/` 已重命名为 **`teacher_frontend/`**（npm 包名 `teacher-frontend`），文档与说明已同步。
- **路由**：`/sequencing`、`/matching` 改为重定向至 `static/resources/interactive/` 下对应 HTML，并保留查询参数；移除 `/test_audio`、`/simple_audio_test`。
- **测试代码**：删除仓库内仅用于本地试验的 `test_*.py`、`tests/`、`database/test_random_file.py`（若仍存在请核对本地分支）。
- **文档**：新增 `README.md`、`docs/ENVIRONMENT.md`、`docs/ARCHITECTURE.md`、`.env.example`；过程类 Markdown 迁至 `docs/archive/`，运维类说明置于 `docs/`。
- **临时文件**：根目录 `temp/` 内临时文件已清空；建议在 `.gitignore` 中忽略该目录。
