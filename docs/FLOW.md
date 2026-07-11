# 儿童端页面流程与状态机（MVP）

## 1. 页面流程（固定闭环）

`欢迎页 -> 课程选择页 -> 课程进行页 -> 结果/报告页`

说明：

- 仅保留必要主路径，避免儿童迷失
- 每页主操作按钮明确且单一

## 2. 页面原型（低保真）

## 2.1 欢迎页（Welcome）

核心元素：

- 标题：欢迎来到训练小课堂
- 说明：简短一句如何开始
- 主按钮：`开始训练`

交互：

- 点击后进入课程选择页

## 2.2 课程选择页（Course Select）

核心元素：

- 两张课程卡片：`配对训练`、`排序训练`
- 每张卡片包含一句说明
- 主按钮：`开始所选课程`

交互：

- 默认选中第一门课程
- 选中课程后点击开始，进入课程页

## 2.3 课程进行页（Course Play）

核心元素：

- 题目区域（文本 + 选项/可操作项）
- 进度显示（第 N/M 题）
- 即时反馈区域（正确/错误 + 鼓励/提示）
- 轻量对话框（输入一句话，获取简短回复）

交互规则：

- 作答后立即判题
- 正确：鼓励并自动下一题
- 错误：显示错误反馈；累计错误达到阈值触发提示
- 单题完成后自动推进，无需额外按钮

## 2.4 报告页（Report）

核心元素：

- 完成时间
- 正确率与统计卡片
- 平均响应时长
- 错误类型统计
- 对话摘要
- 按钮：`再来一次`（返回选课）

## 3. 状态机定义

## 3.1 会话状态

- `IDLE`：未开始
- `WELCOME`：欢迎页
- `SELECTING_COURSE`：选课中
- `TRAINING_ACTIVE`：训练进行中
- `TRAINING_FINISHED`：题目完成，待生成报告
- `REPORT_READY`：报告可展示
- `ERROR`：异常状态（可回到选课重试）

## 3.2 关键事件

- `START_CLICKED`
- `COURSE_SELECTED`
- `COURSE_STARTED`
- `ANSWER_SUBMITTED`
- `QUESTION_ADVANCED`
- `COURSE_COMPLETED`
- `REPORT_GENERATED`
- `RETRY`
- `FAIL`

## 3.3 状态迁移

1. `IDLE -> WELCOME`（应用初始化）
2. `WELCOME --START_CLICKED--> SELECTING_COURSE`
3. `SELECTING_COURSE --COURSE_STARTED--> TRAINING_ACTIVE`
4. `TRAINING_ACTIVE --COURSE_COMPLETED--> TRAINING_FINISHED`
5. `TRAINING_FINISHED --REPORT_GENERATED--> REPORT_READY`
6. `REPORT_READY --RETRY--> SELECTING_COURSE`
7. 任意状态 --`FAIL`--> `ERROR`
8. `ERROR --RETRY--> SELECTING_COURSE`

## 4. 自动流程控制规则

## 4.1 提示规则

- 同一题错误次数 >= 2：触发提示语（例如“试试先看颜色/大小”）

## 4.2 鼓励规则

- 每次答对：随机返回简短鼓励（如“真棒！”）
- 连续答对 3 题：额外强化鼓励

## 4.3 节奏规则

- 判题反馈停留 0.8~1.2 秒后自动下一题
- 空操作超过阈值（如 20 秒）显示轻提醒

## 5. 异常与兜底

- 网络失败：提示“连接出了点小问题，请重试”
- 会话丢失：自动返回选课页重新开始
- 报告生成失败：支持重新生成，不丢失答题记录
