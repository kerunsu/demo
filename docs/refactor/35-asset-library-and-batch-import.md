# 动作/表情资源库与批量导入

旧单文件接口保持不变。新增版本化控制端接口：

- `POST /api/v2/assets/batch-import`：multipart `kind=motions|emotions` 和 `files`，默认只 staging。
- `GET /api/v2/assets/batch-import/<staging_id>`：查看不含 bytes 的预览。
- `POST /api/v2/assets/batch-import/<staging_id>/commit`：显式提交，冲突策略 `skip`（默认）、`rename`、`overwrite`。
- `POST /api/v2/assets/batch-import/<staging_id>/rollback`：丢弃 staging，不改资源库。

动作必须是 DollSer motion JSON，校验 format、JSON、axis、角度范围和大小；表情必须是 GIF magic。文件名只允许安全扩展名，拒绝路径穿越、空文件和超过单项/批次上限。坏文件只标记该项 failed，不污染同批 ready 项；提交后的重复请求在进程内返回同一结果，避免重试重复写入。

资源引用与物理文件分离：`assetId`/`version` 由 checksum 派生，`physicalFilename` 记录现有 `motions.json` 或 `resources/Emotions/<name>`。`doll/data/asset_index.json` 使用原子 JSON 写入，供后续 `AssetLibrary`/`ResourceResolver` 查找；旧动作名和 GIF 路径仍作为兼容字段保留。

提交失败不应暴露内部 bytes 或绝对路径。若需要更强事务语义，下一阶段将把媒体文件和索引纳入同一个 repository 事务；当前单文件旧库仍由原有 writer 负责，批量入口不删除或重命名旧文件。
