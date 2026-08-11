# 22. 多源时间轴

## 统一表示

内部排序使用 session-relative monotonic 时间，单位为毫秒（DTO 同时可携带原始纳秒值）；墙上时间只用于审计和跨机器诊断，使用 ISO-8601。`TimebaseMapper.normalize(value, unit=...)` 显式接受 `ns`、`ms` 或 `s`，不猜单位。

来源约定：浏览器 `performance`/事件时间先转换为毫秒，Server `time.monotonic_ns()` 作为纳秒基准，Runtime 必须声明自己的时间单位和 `runtimeId`。每个 session 在 start barrier 处确定 `t=0`，随后映射为 `relative_ms`。跨进程无法直接比较的原始时钟不得覆盖 server 时间，而应保留在质量/审计字段中。

## 回拨与质量

若设备时钟回拨，映射器将值夹到上一个合法值并递增 `correction_count`；不会产生负相对时间。sequence、原始时间、映射时间和丢包/补传信息共同进入后续质量分析。相同 sequence 的重试由上层根据 checksum/idempotency 处理，不重复推进时间轴。

录制文件自身的容器时间戳仍由现有 recorder 产生；本契约只约束 session 事件、timeline 和 track manifest 的关联时间。任何未来替换 recorder 的改动必须用旧 AVI/WAV 文件、旧 CSV 列和 golden flow 做对照。
