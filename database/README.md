# 数据库使用说明

## 概述

本项目使用SQLite数据库存储教师账户信息。数据库文件位于 `database/app.db`。

## 初始化数据库

首次使用前，需要初始化数据库。交接推荐直接播种标准库：

```bash
python database/seed_standard.py
```

或使用引导脚本（无 `app.db` 时会自动调用上述播种）：

```bash
python scripts/bootstrap.py
```

仅建表与字典 / 默认账号：

```bash
python database/init_db.py
```

`init_db` 将：
1. 创建数据库表
2. 初始化课程类型字典表
3. 初始化能力类型字典表
4. 创建默认管理员账户
   - 用户名: `admin`
   - 密码: `admin123`

**注意：** 生产环境请务必修改默认密码！  
`app.db` 不进 Git；同学机器上靠 `seed_standard` / `bootstrap` 重建。

## 迁移课程数据

如果之前使用 `courses.json` 文件存储课程数据，需要将其迁移到数据库：

```bash
python database/migrate_courses.py
# 非交互覆盖：
python database/migrate_courses.py --force
```

这将：
1. 读取 `static/courses.json` 文件
2. 将课程数据导入到 `Course` 和 `CourseItem` 表
3. 自动映射课程类型（英文 -> 中文）

**注意：** 
- 如果数据库中已存在课程数据，迁移脚本会提示是否覆盖
- 迁移完成后，`/courses` API 将从数据库读取数据，而不是 JSON 文件

## 数据库模型

### Teacher（教师账户表）

字段说明：
- `id`: 主键，自增
- `username`: 用户名（唯一）
- `password_hash`: 密码哈希值（加密存储）
- `real_name`: 真实姓名
- `email`: 邮箱
- `phone`: 手机号
- `is_active`: 是否激活
- `created_at`: 创建时间
- `updated_at`: 更新时间
- `last_login`: 最后登录时间

### Student（学生基本信息表）

字段说明：
- `id`: 主键，自增
- `name`: 姓名
- `avatar`: 头像URL
- `age`: 年龄
- `preference`: 偏好
- `teacher`: 任课老师
- `screening`: 初步筛查或简介
- `created_at`: 创建时间
- `updated_at`: 更新时间

### CourseType（课程类型字典表）

存储固定的5类课程：
1. 命名
2. 拟声
3. 模仿
4. 配对
5. 排序

字段说明：
- `id`: 主键，自增
- `name`: 课程类型名称（唯一）

### Course（课程主表）

存储课程的基本信息。

字段说明：
- `id`: 主键，自增
- `course_type_id`: 课程类型ID（外键，关联course_type表）
- `title`: 显示标题
- `icon`: 课程图标路径（可选）
- `question_audio`: 问题音频路径
- `praise_audio`: 表扬音频路径
- `entry_file`: HTML入口文件（仅交互课有，可选）
- `created_at`: 创建时间
- `updated_at`: 更新时间

### CourseItem（课程具体内容项表）

存储每个课程的具体内容项。

字段说明：
- `id`: 主键，自增
- `course_id`: 课程ID（外键，关联course表，级联删除）
- `name`: 条目名称
- `icon`: 该条目图标路径（可选）
- `type`: 类型（image/interactive）
- `media_file`: 资源文件（图片/音频路径，可选）
- `hint_audio`: 提示音频路径（可选）
- `difficulty`: 难度（easy/medium/hard，可选）
- `config`: 特殊配置（JSON格式，cardCount, timeLimit等，可选）
- `created_at`: 创建时间
- `updated_at`: 更新时间

### AbilityType（能力类型字典表）

存储固定的6类能力：
1. 注意力
2. 模仿
3. 配对
4. 排序
5. 表达性语言
6. 接收性语言

字段说明：
- `id`: 主键，自增
- `name`: 能力类型名称（唯一）

### TrainingSession（训练事件表）

记录一次完整的训练事件。

字段说明：
- `id`: 主键，自增
- `student_id`: 学生ID（外键，关联students表）
- `date`: 训练日期
- `start_time`: 开始时间
- `end_time`: 结束时间
- `created_at`: 创建时间

### TrainingDetail（训练详情表）

记录某次训练中每种课程的训练量。

字段说明：
- `id`: 主键，自增
- `training_session_id`: 训练事件ID（外键，关联training_session表，级联删除）
- `course_type_id`: 课程类型ID（外键，关联course_type表，限制删除）
- `count`: 本课程训练的次数

唯一约束：同一训练事件中，每种课程类型只能有一条记录。

**设计说明：**
- 字典表使用 `RESTRICT` 删除策略，防止误删字典数据

### AbilityItem（能力项表）

记录每次训练后更新的每个能力项。

字段说明：
- `id`: 主键，自增
- `training_session_id`: 训练事件ID（外键，关联training_session表，级联删除）
- `ability_type_id`: 能力类型ID（外键，关联ability_type表，限制删除）
- `score`: 分数

唯一约束：同一训练事件中，每种能力类型只能有一条记录。

**设计说明：**
- 使用外键关联 `ability_type` 表，保证数据一致性和完整性
- 字典表使用 `RESTRICT` 删除策略，防止误删字典数据

## API接口

### 1. 教师登录
- **URL**: `/api/teacher/login`
- **方法**: `POST`
- **请求体**:
  ```json
  {
    "username": "admin",
    "password": "admin123"
  }
  ```
- **成功响应** (200):
  ```json
  {
    "success": true,
    "message": "登录成功",
    "teacher": {
      "id": 1,
      "username": "admin",
      "real_name": "管理员",
      ...
    }
  }
  ```
- **失败响应** (401/400/500):
  ```json
  {
    "error": "错误信息"
  }
  ```

### 2. 教师注册（可选）
- **URL**: `/api/teacher/register`
- **方法**: `POST`
- **请求体**:
  ```json
  {
    "username": "teacher1",
    "password": "password123",
    "real_name": "张老师",
    "email": "teacher1@example.com",
    "phone": "13800138000"
  }
  ```

### 3. 获取教师列表（可选）
- **URL**: `/api/teacher/list`
- **方法**: `GET`
- **响应**:
  ```json
  {
    "success": true,
    "teachers": [...]
  }
  ```

## 使用示例

### Python代码示例

```python
from database.models import db, Teacher

# 创建新教师
teacher = Teacher(username='teacher1', real_name='张老师')
teacher.set_password('password123')
db.session.add(teacher)
db.session.commit()

# 验证密码
teacher = Teacher.query.filter_by(username='teacher1').first()
if teacher and teacher.check_password('password123'):
    print("密码正确")
```

### 前端调用示例（JavaScript）

```javascript
// 登录
fetch('/api/teacher/login', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    username: 'admin',
    password: 'admin123'
  })
})
.then(response => response.json())
.then(data => {
  if (data.success) {
    console.log('登录成功', data.teacher);
  } else {
    console.error('登录失败', data.error);
  }
});
```

## 注意事项

1. 密码使用 `werkzeug.security.generate_password_hash` 加密存储
2. 数据库文件 `app.db` 应添加到 `.gitignore`（如果包含敏感数据）
3. 生产环境建议使用更强大的数据库（如PostgreSQL）
4. 定期备份数据库文件

