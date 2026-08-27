# Demo 测试与发布门禁

Demo 发布必须同时证明三课程正常、硬件能力永久关闭、全新拉取可复现。单独通过主流程测试不足以发布。

## 自动化门禁

在仓库根目录运行：

```powershell
python -m pytest tests -q
python -m compileall -q app database scripts app.py
python scripts/bootstrap.py --check-only
git diff --check
```

对改动 JavaScript 逐个运行 `node --check`。教师端改动还需：

```powershell
Set-Location teacher_frontend
npm.cmd ci
npm.cmd run build
```

警告必须被审阅；不能通过删除断言、跳过既有用例或重置数据库获得“通过”。

## 必须覆盖的 Demo 边界

自动化至少证明：

- 有效课型精确等于 `mimic/pairing/ordering`，非法范围文件 fail-closed。
- 静态课程目录、课程预设、首次数据库和配置 API 只暴露三类课程。
- 报告只输出注意力、配对、排序三个维度和三课程投影。
- `robotMotion`、`robotExpression`、`robotRuntime` 始终 false。
- 机械/表情 HTTP 返回 410 `demo_capability_disabled`。
- 非 Demo 话术写入返回 400，旧文件音频条目配置返回 410。
- 机械/表情 Socket 未注册，机器人页面/脚本/素材不存在。
- `doll/Pose/`、`motions.json`、`emotions_meta.json`、`static/resources/Emotions/` 不进入发布。
- DollSer、动作工作台和 Robot Runtime 发布脚本不存在。
- `static/resources/Animations/` 仍可列举、上传、引用保护、重命名和播放。
- 儿童媒体固定 browser，设备检查使用 `browser_permission_required`，不依赖 19091。
- 配置同步包排除数据库、录制、个人数据、硬件和完整版本表情。

## 单元与契约测试

重点测试层：

- 配置：JSON/YAML schema、权重总和、原子写入、非法输入不部分保存。
- 课程：catalog 规范化、重复迁移幂等、旧 DB 历史行保留但新入口过滤。
- 互动：配对/排序 question ID 幂等、反馈不截断朗读、正确反馈进入评分。
- 模仿：Windows 模型路径、阈值 0.50、镜像允许、稳定命中和身份去重。
- 语音：浏览器识别文本、TTS busy/duplicate、朗读结束后恢复识别。
- 录制：连续会话、课点切换只追加 timeline、稳定文件名和路径遍历拒绝。
- 报告：三维评分、缺失值语义、叙事建议、生成/审核幂等。
- 房间隔离：未解析儿童端不广播，teacher ACK 只回请求方。
- 契约快照：源码装饰器、运行时 URL map、实际 Socket 注册和 emit 集合一致。

机器证据位于 `tests/fixtures/contracts/contracts.snapshot.json` 和 `traceability.matrix.json`。修改接口/事件时必须同步快照和事实文档。

## 全新数据库测试

必须在临时目录创建数据库，不操作部署 `database/app.db`。连续运行两次标准播种，验证：

- 只有模仿、配对、排序三类课程。
- canonical 课程 ID/类型稳定。
- 配对和排序内容可重复导入而不制造重复行。
- 预设引用可以解析。
- 不会自动补回命名、拟声或社交课程。

旧数据库升级测试必须证明保留历史行和报告，不允许以删库方式通过。

## 无硬件浏览器冒烟

在接近部署机器的 Windows/浏览器环境手工完成：

1. 运行 `.\start_server.ps1`，确认只启动 8080 Server。
2. 打开 `/teacher/`、`/child`、`/server`。
3. 在儿童端允许摄像头、麦克风和浏览器语音。
4. 教师端只看到三门课程和两套三课程预设。
5. 分别完成一轮模仿、配对、排序。
6. 检查问题朗读、互动反馈、儿童动画、教师评分和 finalize。
7. 生成报告，确认课程/维度范围并提交审核。
8. 刷新儿童端，确认能恢复当前会话且不会重复播放。
9. 断开/重连网络，确认精确房间恢复且无跨会话内容。
10. 检查录制目录和时间线文件完整。

## 禁用面冒烟

手工确认：

- `/robot`、`/robot/emotion`、`/robot/download` 不可用。
- 监控页无 Runtime 卡片或停止机器人按钮。
- 配置页无动作库、表情库、行为绑定或 Runtime 部署入口。
- 浏览器网络面板没有访问 19091、`/ui/open-emotion` 或 OSC 转发。
- 配置导出 ZIP 不含禁用文件。
- 儿童情绪分析图表若出现，只代表观测数据，不会触发表情输出。

## 性能与现场项

自动化不能替代：

- 实际浏览器摄像头/麦克风权限。
- MediaPipe 模型在目标 CPU 上的延迟。
- 浏览器 SpeechRecognition/TTS 可用性和中文 voice。
- 大尺寸课程视频/动画解码。
- 局域网抖动、断线重连和长时间连续录制。
- 外部对话 provider 的网络、配额和降级。

现场至少执行一次完整三课程流程和 30 分钟连续运行；记录浏览器版本、机器规格、日志和发现的问题。

## 同步回归

每次从完整版本吸收更新，按 `docs/DEMO_SYNC.md` 复核：

1. 完整版工作树只读。
2. 通用修复逐文件合并。
3. 三课程和硬件禁用边界重新施加。
4. 更新文档、fixture 和测试。
5. 运行完整门禁与浏览器冒烟。

任何机械动作、Robot Runtime 或完整版本表情相关变化都不能直接复制进 Demo 发布面。
