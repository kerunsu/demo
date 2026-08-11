# 「社交」课程接入规划（打招呼 / 再见）

> 状态：已实现（P0–P3）  
> 目标：新增课型「社交」及两个课点「打招呼」「再见」；控制页特殊排序与专用语音按钮；`/server` 行为绑定全局槽位扩展为可配置四键。

### 落地摘要

| 层 | 改动 |
|----|------|
| DB | `import_social_course.py`；`社交↔social` 映射；init_db 幂等补齐 |
| 教师端 | 选课/控制页 `courseTypeMap`；`normalizeSocialOrder`；社交双语音键 +「下一个」 |
| 语音 | `audio_manifest` 四 entry；`AudioService` / handlers / child aux |
| 行为绑定 | `course_map` defaults 四槽；config.html + robot_mapping / emotion；`parse_aux_type` + routes 白名单 |

---

## 1. 需求理解

| 项 | 内容 |
|----|------|
| 课型 | 社交（建议英文 key：`social`） |
| 课点 | ① 打招呼 ② 再见 |
| 图标 | 暂用配对课点同款默认占位（教师端 `DEFAULT_ITEM_IMAGE` / Unsplash 回退即可） |
| 控制页排序 | 若勾选「打招呼」→ **整场训练序列最前**；若勾选「再见」→ **整场序列最后**（与选课勾选顺序无关） |
| 控制按钮 | 进入对应课点时，**不走**常规「提问/提示/表扬/下一个」四键语义，改为该课点专用双语音键 |
| 打招呼键 | 「初见打招呼」：仅播语音（文案：你好啊，我叫迈迈，你叫什么名字） |
| 打招呼键 | 「一起玩耍吧」：仅播语音（文案：好的，那我们一起来玩游戏吧） |
| 再见键 | 「再见」「回应」：同样仅播语音（文案可先占位，后续配置页改） |
| 配置 | `/server` 行为绑定「全局通用配置」需能配置这 **4 个新按钮** 对应的机器人动作/表情（与语音可分开） |

语音文件：首期可挂任意现有 mp3 占位，后续在配置中心 / `audio_manifest` 调整。

---

## 2. 现状审查：是否「改数据库就够」？

### 2.1 结论（先给判断）

**不够。**  
只往 SQLite 插 `course_type` / `course` / `course_item`，教师选课列表**有可能**出现新类别（`GET /courses` 动态读库），但：

1. 英文 `type` 不会稳定变成 `social`（`Course.to_dict()` 映射表只有现有 5 类）；  
2. 控制页**不会**自动变成「打招呼双键 / 再见双键」；  
3. **不会**自动把打招呼顶到最前、再见沉到最后；  
4. `/server` 行为绑定全局槽位仍硬编码为 `praise/question/hint/silent` 四个，**不会**出现你要的四个社交按钮；  
5. 儿童端能「播图」取决于 item 是 image 还是 interactive；纯语音按钮还依赖 `play_resource` + Audio 管道扩展。

| 你的预期 | 与现状 |
|----------|--------|
| 改 DB 后教师端能显示 | **部分成立**：列表可能可见，图标/中文名可能 fallback |
| 儿童端能播放 | **部分成立**：若做成 image 课点可换图；专用语音按钮需改教师端 + Socket + audio |
| `/server` 配置页能改 | **课程库**可读新课型；**行为绑定四槽**目前不能自动多出四个社交按钮 |
| 特殊排序与专用控制键 | **必须改代码**，DB 表达不了 |

### 2.2 关键架构事实

```
选课: CourseSelectionPage → GET /courses → DB course/course_item
控制: ControlPage 固定四键 → play_resource(aux: question|praise|hint)
儿童: child.js 换内容 + AudioPlayer 播 play_audio
行为绑定: course_map.json defaults.{praise,question,hint,silent}
          ← /server/config/content?view=binding
语音: audio_manifest.yaml + AudioService 按 aux 选 entry
```

ControlPage **不会**按课型切换整套按钮 UI；课型差异主要在 hint/pairing/ordering 分支。社交课需要**显式新增控制 UI 分支**。

行为绑定「全局通用配置」四槽与教师端四键是对齐的；新增四个社交按钮意味着：

- 要么扩展 `aux` 类型 + `course_map.defaults` + 绑定 UI 槽位（推荐，与你说的「全局通用配置新增四个按钮」一致）；  
- 要么只做语音、机器人不联动（不满足你对绑定页的要求）。

---

## 3. 推荐产品语义（规划默认）

### 3.1 课点形态

- `course_type.name = 社交`，英文 `social`  
- 一门 `course`（如「社交课程」），两个 `course_item`：打招呼、再见  
- `item.type = image`（无互动 HTML）；`icon/file` 可空，前端用配对同款 `DEFAULT_ITEM_IMAGE`  
- 不挂 `entry_file`，不进 pairing/ordering 游戏逻辑  

### 3.2 训练序列重排（选课结果进入控制页时）

在 ControlPage 读取 `selectedCourseItems` 后做一次规范化：

1. 抽出所有 `social` 且课点名为「打招呼」（或约定 item 标记 `role=greeting`）的项 → 插到序列头部（保持多门课其它相对顺序）。  
2. 抽出「再见」→ 接到序列尾部。  
3. 中间保持用户原选课顺序。  

建议在 DB 或 item.config JSON 增加稳定标记，例如：

```json
{ "socialRole": "greeting" }  // 或 "farewell"
```

避免仅靠中文名匹配。

### 3.3 控制页 UI（当当前课点为 social）

| 当前课点 | 主操作区 |
|----------|----------|
| 打招呼 | 「初见打招呼」「一起玩耍吧」；保留「下一个」以进入后续课程 |
| 再见 | 「再见」「回应」；保留「下一个」（末课则走现有结束评分流程） |
| 其它课型 | 维持现有提问/提示/表扬/下一个 |

说明：

- 社交课点上建议**隐藏或禁用**提问/提示/表扬（避免误触常规四键语义）。  
- 「下一个」仍走现有评分门禁（若产品希望社交课免评分，需另开决策；默认与其它课点一致）。  

### 3.4 四个按钮的双轨配置

每个社交按钮同时有：

| 轨道 | 存哪儿 | 作用 |
|------|--------|------|
| 语音 | `audio_manifest.yaml`（+ 后续配置中心语音页） | 儿童端听到的内容 |
| 机器人动作/表情 | `course_map.json` → `defaults` 新槽 | `/server` 行为绑定「全局通用」可配 |

aux 建议键名（稳定英文，与 UI 文案解耦）：

| UI 文案 | aux 标志 | 建议 binding 槽名 |
|---------|----------|-------------------|
| 初见打招呼 | `socialGreetingIntro` | `social_greeting_intro` |
| 一起玩耍吧 | `socialGreetingPlay` | `social_greeting_play` |
| 再见 | `socialFarewellBye` | `social_farewell_bye` |
| 回应 | `socialFarewellReply` | `social_farewell_reply` |

---

## 4. 需要改动的模块清单（按层）

### 4.1 数据库（必要，但不充分）

| 动作 | 说明 |
|------|------|
| `course_type` 插入「社交」 | 或 `init_db.py` 种子同步 |
| `course` 插入「社交课程」 | 无 `entry_file` |
| `course_item` ×2 | 打招呼 / 再见；`config` 含 `socialRole`；icon 可空 |
| 可选脚本 | `database/import_social_course.py`（对齐 pairing/排序导入脚本风格） |

**仅此步：选课列表可能可见；控制/绑定/语音专键不会自动出现。**

### 4.2 课型英文映射（必要）

| 文件 | 改动 |
|------|------|
| `database/models.py` | `type_mapping` 增加 `社交 → social` |
| `app/routes/config_content.py` | `TYPE_EN_TO_CN` / `TYPE_CN_TO_EN` |
| `database/migrate_courses.py` | 若仍用 JSON 迁移则同步 |
| `database/init_db.py` | 新环境种子含社交 |

配置中心课程库：映射补齐后可用英文 `social` 创建/筛选。

### 4.3 教师端（核心体验）

| 文件 | 改动 |
|------|------|
| `CourseSelectionPage.tsx` | `courseTypeMap` 增加社交图标/中文名 |
| `ControlPage.tsx` | ① 进入控制页时序列重排；② 当前为 social 时渲染专用双键；③ emit `play_resource` 带新 aux；④ 隐藏常规三键 |

### 4.4 语音管道（必要）

| 文件 | 改动 |
|------|------|
| `config/audio_manifest.yaml` | 新增 4 个 entry + 占位 mp3（可先复用 `greeting_hello` / `greeting_bye` 等现有文件） |
| `app/audio/service.py` | `process_play_resource` 增加 4 个 `elif aux.get(...)` |
| `app/sockets/handlers.py` | `has_aux_flag` 识别新 aux（走 aux 分支：不换课点内容，只播语音） |
| （可选）配置中心语音页 | 后续把 4 entry 做成可配；首期改 yaml 即可 |

### 4.5 行为绑定 / 机器人（你明确要求）

| 文件 | 改动 |
|------|------|
| `static/robot/js/robot_mapping.js` | 全局通用配置槽位数组由 4 扩到 **8**（原四槽 + 社交四槽），带中文标签 |
| `app/robot/mapping_resolver.py` | `parse_aux_type` 识别新 aux → 对应槽名 |
| `app/robot/routes.py` | `aux_type` 白名单扩展 |
| `doll/data/course_map.json` | `defaults` 预置四槽空/默认动作（可先拷贝 silent/question 占位） |

运行时：`play_resource` 已会 `trigger_course_event`；扩展 `parse_aux_type` 后全局绑定即可生效。

### 4.6 儿童端

| 文件 | 改动 |
|------|------|
| `static/js/child.js` | `isAuxOperation` 包含新 aux；一般**无需**为 social 做 iframe；非 aux 时展示占位图即可 |

社交课点「切到该课点」时仍走一次无 aux 的 `play_resource`（加载占位图）；点专用按钮只发 aux，不重载内容。

### 4.7 报告 / 训练统计（建议分期）

首期可不进独立评分维：

- `scoring.py` / `archive_sync.py` / `StudentInfoPage` 柱图：社交课点可记入 training_detail 计数，或暂不计入 5 课型堆叠柱。  
- 规划建议：**训练记录可统计「社交」次数**；能力雷达**暂不新增维度**。  

若跳过，需在报告/archive 映射里把 `social` 忽略或归入「其它」，避免未知课型报错。

---

## 5. 前端交互设计要点

### 5.1 选课页

- 左侧出现「社交」类别；两个课点可单独勾选。  
- 文案提示（可选）：「打招呼将自动排在训练最前，再见将自动排在最后」。

### 5.2 控制页布局（社交课点）

```
┌─────────────────────────────────────────┐
│ 当前：社交 · 打招呼（或 再见）            │
│ [占位图]                                 │
│                                         │
│  [初见打招呼]  [一起玩耍吧]   （打招呼时） │
│  [再见]        [回应]         （再见时）   │
│                                         │
│  [下一个]  （保留；末课走评分结束）        │
└─────────────────────────────────────────┘
```

### 5.3 `/server` 行为绑定 · 全局通用

在现有四槽下方或同级增加分组「社交课点」：

- 初见打招呼 / 一起玩耍吧 / 再见 / 回应  
- 每槽仍配：动作列表 + 表情（与现 UI 一致）

课程级 / 学生级 / 课点级覆盖：首期可只做 **defaults 全局**；课点级覆盖可二期再做（再见课点可单独覆盖）。

---

## 6. 技术实现阶段（建议）

| 阶段 | 内容 | 验收 |
|------|------|------|
| **P0 数据** | DB 课型+课程+课点；CN↔EN 映射；选课页可见 | 教师端能勾选社交两项 |
| **P1 排序** | ControlPage 序列规范化 | 有打招呼必第一、有再见必最后 |
| **P2 语音键** | 四按钮 UI + aux + AudioService + manifest 占位音 | 点按钮儿童端出声、不换课 |
| **P3 行为绑定** | 全局四槽扩展 + parse_aux + course_map | `/server` 可配四键机器人动作，训练时触发 |
| **P4 收尾** | 报告/柱图对 social 的兼容；配置中心语音可改路径 | 无报错；可后续换正式录音 |

---

## 7. 决策点（实现前建议确认）

| # | 问题 | 规划默认 |
|---|------|----------|
| 1 | 社交课点是否仍要「教师 1–5 评分」再下一个？ | **要**（与现流程一致） |
| 2 | 未勾选打招呼但勾选了再见？ | 再见仍置尾；序列无强制开头 |
| 3 | 只勾选打招呼？ | 打招呼置首，其后为其它课 |
| 4 | 行为绑定首期是否只要全局 defaults？ | **是** |
| 5 | 报告柱图是否增加「社交」系列？ | 首期 **增加 count 统计**，能力维不扩 |
| 6 | item 识别靠中文名还是 `socialRole`？ | **`socialRole` 优先** |

---

## 8. 一页纸结论

- **不能只改 `database`。** DB 负责「有这门课」；显示名映射、控制页排序/专用键、语音管道、行为绑定四槽扩展都必须改代码/配置。  
- **教师端**需要改：选课展示 + 控制页排序与专用按钮。  
- **儿童端**以复用现有 `play_audio` 为主，扩展 aux 识别即可。  
- **`/server`**：课程库映射补齐后可管课点；你点名的「行为绑定 · 全局通用」必须**新增 4 个槽位**，与四键 aux 对齐。  
- **下一步**：确认 §7 决策点后，按 P0→P3 开工；**当前阶段不改代码**。
