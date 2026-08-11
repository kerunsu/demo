# DollSer Motion JSON 字段说明

## 文件结构

```json
{
  "version": 2,
  "format": "dollser-motion",
  "armBaselineVersion": 2,
  "updatedAt": "2026-05-01T10:00:00.000Z",
  "name": "点头确认",
  "durationMs": 1900,
  "initialPose": {
    "pitch": 180,
    "yaw": 180,
    "armL": 270,
    "armR": 270
  },
  "commands": [
    {
      "actionId": "action-1",
      "time": 200,
      "axis": "pitch",
      "angle": 196,
      "moveMs": 220,
      "label": "点头 1",
      "phase": "move"
    }
  ],
  "motionStartTime": 200,
  "motionDurationMs": 1700,
  "expression": {
    "scope": "sequence",
    "mediaId": "confirm.png",
    "time": 0,
    "motionStartTime": 200,
    "offsetMs": -200,
    "leadMs": 200,
    "leadSeconds": 0.2,
    "durationMs": 480,
    "loop": true
  }
}
```

## 顶层字段

| 字段 | 类型 | 必填 | 取值/范围 | 作用 |
|---|---|---:|---|---|
| `version` | number | 是 | `2` | JSON 格式版本。 |
| `format` | string | 是 | `"dollser-motion"` | JSON 格式标识。 |
| `armBaselineVersion` | number | 否 | `2` | 手臂电机角度基准版本；缺省按旧版导入并自动前移 90 度。 |
| `updatedAt` | string | 是 | ISO 8601 时间字符串 | 文件导出或更新时间。 |
| `name` | string | 是 | 非空字符串 | 动作名称。 |
| `durationMs` | number | 是 | `>= 0` | 动作总时长，单位毫秒。 |
| `initialPose` | object | 是 | 见 `initialPose` | 动作初始姿态。 |
| `commands` | array | 是 | 见 `commands` | 动作指令列表。 |
| `motionStartTime` | number | 否 | `>= 0` | 舵机动作在统一播放时间轴中的开始时间；表情提前时该值大于 0。 |
| `motionDurationMs` | number | 否 | `>= 0` | 不含表情预卷的原始舵机动作时长。 |
| `expression` | object | 否 | 见 `expression` | 整个动作序列唯一的表情配置。 |

## expression

| 字段 | 类型 | 必填 | 取值/范围 | 作用 |
|---|---|---:|---|---|
| `scope` | string | 是 | `"sequence"` | 表示表情属于整个动作序列。 |
| `mediaId` | string | 是 | 表情文件名 | 对应 `doll/expressions/` 中的素材。 |
| `time` | number | 是 | `>= 0` | 表情开始显示时间，单位毫秒。 |
| `motionStartTime` | number | 是 | `>= 0` | 舵机动作序列开始时间，单位毫秒。 |
| `offsetMs` | number | 是 | 可为负数 | 表情相对动作的偏移；负数表示提前，正数表示延后。 |
| `leadMs` | number | 是 | `>= 0` | 表情比动作提前的毫秒数；未提前时为 `0`。 |
| `leadSeconds` | number | 是 | `>= 0` | `leadMs` 的秒数表示，便于人工交接。 |
| `durationMs` | number | 是 | `100..30000` | 表情显示时长，单位毫秒。 |
| `loop` | boolean | 否 | `true` / `false` | 视频或 GIF 是否在表情块结束前循环。 |

## initialPose

| 字段 | 类型 | 必填 | 取值/范围 | 作用 |
|---|---|---:|---|---|
| `pitch` | number | 是 | `0..359` | 头部俯仰初始角度。 |
| `yaw` | number | 是 | `0..359` | 头部水平初始角度。 |
| `armL` | number | 是 | `0..359` | 左臂初始角度。 |
| `armR` | number | 是 | `0..359` | 右臂初始角度。 |

## commands

`commands` 为数组。每一项表示一条动作指令。

| 字段 | 类型 | 必填 | 取值/范围 | 作用 |
|---|---|---:|---|---|
| `actionId` | string | 否 | 任意字符串 | 动作块标识，用于导入时匹配同一动作的 `move` 与 `return`。 |
| `time` | number | 是 | `>= 0` | 指令触发时间，单位毫秒，从动作开始计时。 |
| `axis` | string | 是 | `pitch` / `yaw` / `armL` / `armR` | 指令作用轴。 |
| `angle` | number | 是 | `0..359` | 目标角度。 |
| `moveMs` | number | 是 | `50..5000` | 到达目标角度所需时间，单位毫秒。 |
| `label` | string | 否 | 任意字符串 | 指令名称或备注。 |
| `phase` | string | 否 | `move` / `return` / 自定义字符串 | 指令阶段标记。 |

## 轴名映射

| `axis` | 含义 | DollSer 地址 |
|---|---|---|
| `pitch` | 头部俯仰 | `/pitch` |
| `yaw` | 头部水平 | `/yaw` |
| `armL` | 左臂 | `/arml` |
| `armR` | 右臂 | `/armr` |

## 播放字段关系

| 字段 | 播放含义 |
|---|---|
| `commands[].time` | 何时执行该指令。 |
| `commands[].actionId` | 哪些指令属于同一个动作块。 |
| `commands[].axis` | 控制哪个轴。 |
| `commands[].angle` | 转到哪个角度。 |
| `commands[].moveMs` | 用多长时间转到目标角度。 |

## 最小示例

```json
{
  "version": 2,
  "format": "dollser-motion",
  "armBaselineVersion": 2,
  "updatedAt": "2026-05-01T10:00:00.000Z",
  "name": "点头确认",
  "durationMs": 480,
  "initialPose": {
    "pitch": 180,
    "yaw": 180,
    "armL": 270,
    "armR": 270
  },
  "commands": [
    {
      "actionId": "action-1",
      "time": 0,
      "axis": "pitch",
      "angle": 196,
      "moveMs": 220,
      "phase": "move"
    },
    {
      "actionId": "action-1",
      "time": 260,
      "axis": "pitch",
      "angle": 180,
      "moveMs": 220,
      "phase": "return"
    }
  ]
}
```

## 交付前检查

工作台导入和导出时会使用 `doll/public/motion-standard.js` 执行同一套检查：

- `format`、`version`、动作名称和四轴初始姿态必须完整。
- `commands` 至少包含一条指令。
- 角度必须在 `0..359`，到位时间必须在 `50..5000 ms`。
- `durationMs` 必须覆盖最后一条指令的结束时间。
- 缺少 `actionId` 或 `label`、未声明手臂基准版本、指令未按时间排序会产生提醒。
- 同一轴的新指令在上一条到位前开始会产生“提前接管”提醒，交付前应人工确认。
- 每个动作序列最多包含一个 `expression`，不再与单个动作块绑定。
- 表情结束时间必须包含在顶层 `durationMs` 内。
- `time - motionStartTime` 应等于 `offsetMs`。例如 `offsetMs: -600`、`leadSeconds: 0.6` 表示表情比整个动作序列提前 0.6 秒播放。

推荐在交付 JSON 前依次完成“模拟测试”和实机播放测试。模拟测试只检查与打印指令，不会控制机器人。

交付包含表情的动作时，应同时发送 JSON 和它引用的表情文件。接收方把素材放入 `doll/expressions/` 后，在工作台点击“刷新表情目录”。
