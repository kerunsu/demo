# 文档索引

协作规范的唯一入口是根目录 [`AGENTS.md`](../AGENTS.md)。本文只负责索引当前事实文档。

根目录以 `README.md` 作为项目介绍入口、以 `AGENTS.md` 作为协作入口。运行所需的 `.env`、依赖清单、
`pytest.ini`、`start_server.ps1` 和 `RobotRuntime.spec` 仍必须位于根目录，移动它们会破坏
一键启动、测试或机器人打包。

## 当前有效文档

- `ARCHITECTURE.md`：模块边界与依赖方向。
- `COLLABORATION.md`：旧链接兼容入口，规则以根目录 `AGENTS.md` 为准。
- `CONTRACT.md`：HTTP、Socket、Runtime 契约。
- `CONFIGURATION.md` / `ENVIRONMENT.md`：配置和部署。
- `OPERATIONS.md`：启动、监控、备份、升级与排障。
- `TESTING.md`：测试与发布门禁。
- `current/三端协同稳定性根因与分阶段整改方案.md`：当前稳定性整改主记录。
- `current/教师端开课与机器人多模态同步重构需求.md`：教师端与多模态同步需求。
- `current/Server控制端代码审查与优化说明.md`：控制端真值和交互状态说明。

历史阶段、迁移和验收过程由 Git 历史保存，不在当前工作树保留。动作编辑器的 JSON
格式和示例位于 `doll/DollSer/docs/` 与 `doll/DollSer/example/`。
