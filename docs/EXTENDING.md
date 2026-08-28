# Demo 扩展指南

所有扩展必须先满足 `config/demo_course_scope.json` 与 `config/demo_deployment.json`。这两个事实源固定 Demo 只启用命名、排序，开启屏幕表情，并永久关闭机械动作和 Robot Runtime；不得通过环境变量、接口或新配置绕过。

## 同步主项目改进

先按 `DEMO_SYNC.md` 判断改动是否适用于两门课程或通用平台。同步顺序是事实源/迁移、后端处理、前端消费方、测试与文档。不能整目录覆盖 `app.py`、`app/robot/`、课程目录、报告配置或教师端控制页。

## 新增课程内容

Demo 不新增第三类课程。命名或排序新增课点时，需要同时更新数据库种子、`static/courses.json`、`doll/data/courses.json`、课程预设、资源引用和自动化测试。旧数据库只做原地兼容升级，不能通过删库发布。

## 新增儿童屏动画

儿童屏鼓励动画放在 `static/resources/Animations/`，通过 `/api/robot/animations` 这一兼容路径管理。这里的 `robot` 只是历史 API 前缀；动画只在儿童浏览器中播放，不得添加机械动作、DollSer 或 Runtime 依赖。上传、重命名、删除必须保留引用保护和 MP4 校验。

## 新增屏幕表情

表情 MP4 放在 `static/resources/Emotions/`，元数据位于 `doll/data/emotions_meta.json`，并通过 `/api/robot/emotions*` 管理。从完整版同步时可保留播放、样式、滤镜、闲时池和对话规则，但必须删除 motion 绑定、19091 预热和 Robot Runtime 依赖。

## 新增分析模型

实现分析端口并提供描述、健康状态、超时/取消、降级和无数据语义。模型层不得依赖 Flask、SocketIO、具体录制器或硬件。Windows 路径和模型加载必须使用仓库内可复现路径，并补真实/模拟两种测试。

## 修改命名或排序交互

题目身份、左右/先后呈现、反馈、教师评分与报告窗口必须使用同一请求和题目标识。修改互动页时同步 `interactive_question_state.js`、对应 HTML、Socket 处理、报告解析和回归测试。

## 修改话术

可修改全局注意力/奖励，以及命名、排序的提问、提示、表扬和排序八类规则句。配置接口会拒绝模仿、配对、拟声、社交等旧课型写入；旧音频条目接口固定返回 410。浏览器语音事件名属于兼容契约。

每项扩展都必须更新契约或数据事实文档，并通过 `docs/TESTING.md` 的发布门禁。
