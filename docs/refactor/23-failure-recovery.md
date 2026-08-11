# 23. 采集与存储故障恢复

| 故障 | 门禁行为 | 数据行为 | 恢复 |
|---|---|---|---|
| optional 环境设备缺失 | 允许继续并标记 optional/degraded | 不生成假轨，manifest 记录 disabled/missing | 控制端重新 discover/test；下一 session 生效 |
| required 设备缺失/自检失败 | 阻止 start barrier | 不写有效媒体内容 | 修复设备后重新 readiness；旧 session 可 cancel |
| required 轨无首帧/首音频 | 回滚 capture start，释放已预留设备 | 保留已有历史文件，不提交新轨为有效 | 重试 start 或重新准备 |
| Runtime 掉线 | readiness/健康检查失败；不静默降级 required | 已接收数据保持；late upload 走旧 checksum/meta 契约 | reconnect、补传、校验后 finalize |
| 浏览器断线 | 维持已有 session 状态，等待既有重连规则 | 不 stop/start 连续主轨，重复请求按 requestId 幂等 | 重连后重新绑定精确 child owner |
| timeline 写失败 | 不覆盖旧 CSV | 报错并保留旧文件；新 repository 原子替换 | 运维检查磁盘/权限后重试 |
| JSON/meta 写失败 | 不宣布 finalize 完成 | 已有 meta 不被截断 | 重试原子写入；只读 validator 报 invalid |
| 重复 start/stop/finalize | 返回幂等结果 | 不重复创建轨道或段 | 客户端可安全重试 |

任何“降级”都必须来自 DeploymentProfile 的 `optional` 或 `disabled` 配置；硬件不存在不能通过 monkeypatch 或空文件伪装成功。旧 `/api/media` 的晚到补传行为继续由既有实现和 phase1 characterization tests 冻结。
