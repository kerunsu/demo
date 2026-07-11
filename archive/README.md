# 归档目录

本目录存放**已不再作为主入口**的历史原型、Agent 提示词与旧版审查文档。运行 Demo 不依赖此处文件。

## `prototypes/html/`

早期静态 HTML 页面原型（欢迎、选课、配对/排序、报告、监控台等），已被 `frontend/` 中的 React 页面取代。

| 文件 | 说明 |
|------|------|
| `realtime_monitor_dashboard_prototype_light.html` | `/server` 浅色监控台视觉参考（实现见 `frontend/src/pages/ServerDashboard.tsx`） |
| `realtime_monitor_dashboard_light_style_guide.md` | 监控台浅色主题样式说明 |
| `professional_report_ver2.html` | 报告 V2 视觉参考 |
| 其余 `*.html` | 历史流程/报告草稿 |

## `docs/history/`

| 文件 | 说明 |
|------|------|
| `PROJECT_CONTEXT_AUDIT_2026-06-06.md` | 2026-06-06 代码审查快照；大量结论已过时，请以根目录 `PROJECT_CONTEXT.md` 与 `docs/ONBOARDING.md` 为准 |

## `docs/agent-prompts/`

各里程碑的 Codex 自动化提示词与进度日志（`NEXT_CODEX_PROMPT*`、`AUTOMATION_PROGRESS*`），仅供追溯开发过程，非运行或交接必读。
