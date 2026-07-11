# 机器人表情动画集成规范

本文只定义调用和适配要求，不创建或修改动画资源。

## 1. 现有资源边界

当前仓库中 `matching/` 和 `paixu/` 是课程图片素材，不是机器人表情资源。`frontend/src/styles.css` 中的 CSS 动效可作为 Web 模拟器参考，但不能假设真实机器人动画已经以该形式存在。

## 2. 动画 manifest 要求

每个动画资源需要提供：

| 字段 | 说明 |
| -- | -- |
| `animationId` | 稳定 ID，例如 `robot.idle.loop.v1`. |
| `intent` | 业务意图，如 `idle`, `listening`, `thinking`, `correct_praise`. |
| `durationMs` | 固定动画时长；循环动画可为空。 |
| `priority` | `low`、`normal`、`high`。 |
| `interruptible` | 是否可被新命令中断。 |
| `loop` | 是否循环。 |
| `preloadRequired` | 是否需要预加载。 |
| `assetType` | CSS、video、lottie、image_sequence、robot_sdk 等。 |
| `resourceRef` | 资源路径或硬件动作名。 |
| `fallbackAnimationId` | 缺失或失败时的替代动画。 |

## 3. 命令接口草案

```ts
export type RobotAnimationIntent =
  | "idle"
  | "greeting"
  | "question_presented"
  | "listening"
  | "thinking"
  | "speaking"
  | "correct_praise"
  | "wrong_encourage"
  | "hint"
  | "course_complete"
  | "error_recovering";

export interface RobotAnimationCommand {
  commandId: string;
  sessionId: string;
  sourceEventId: string;
  animationId?: string;
  intent: RobotAnimationIntent;
  priority: "low" | "normal" | "high";
  durationMs?: number;
  interruptPolicy: "queue" | "replace_same_intent" | "interrupt";
  loop?: boolean;
  speechTurnId?: string;
}

export interface RobotAnimationAdapter {
  preload(manifest: AnimationManifest): Promise<void>;
  play(command: RobotAnimationCommand): Promise<{ commandId: string; status: "started" }>;
  stop(commandId?: string): Promise<void>;
  getStatus(): Promise<{ online: boolean; currentCommandId?: string; lastEventId?: string }>;
}
```

## 4. 状态映射

| 领域状态 | 动画 intent | 说明 |
| -- | -- | -- |
| `IDLE` | `idle` | 可循环，可被任意高优先级事件打断。 |
| `QUESTION_PRESENTING` | `question_presented` | 短动画，表示关注题目。 |
| `WAITING_FOR_RESPONSE` | `idle` 或 `listening` | 有语音模式时倾听，否则待机。 |
| `LISTENING` | `listening` | 循环动画，语音结束后停止。 |
| `TRANSCRIBING` / `EVALUATING_ANSWER` | `thinking` | 可循环，直到结果事件到达。 |
| `SPEAKING` | `speaking` | 与 TTS 时长或 viseme marks 同步。 |
| 答对 | `correct_praise` | 优先级 normal/high，可打断 idle。 |
| 答错 | `wrong_encourage` | 鼓励，不包含羞辱或负面标签。 |
| 提示 | `hint` | 与提示语音或字幕同步。 |
| 完成课程 | `course_complete` | 庆祝动画。 |
| 错误/降级 | `error_recovering` | 固定安抚或回到 idle。 |

## 5. 播放完成回调

机器人屏或适配层应在开始和完成时发事件：

- `ANIMATION_STARTED`
- `ANIMATION_FINISHED`

完成 payload 包含 `commandId`、`animationId`、`status`、`durationMs`、`errorCode`。后端不能只依赖本地 timer 推进跨屏状态。

## 6. 错误和资源缺失

- 找不到 `animationId` 时使用 `fallbackAnimationId` 或 `idle`。
- 高优先级安全兜底可中断正在播放的普通动画。
- 已过期事件不能覆盖新题或新语音 turn。
- 重复 `commandId` 必须幂等。

## 7. 动画模拟器需求

在真实动画资源或机器人 SDK 不确定前，需要 Web 动画模拟器：

- 支持所有 intent。
- 支持排队、中断和循环。
- 支持手动触发失败、延迟、资源缺失。
- 支持显示当前 `sessionId`、`eventId`、`commandId`。
- 不依赖真实外部 API 或硬件。

## 8. 仍需提供的信息

1. 动画资源清单和技术形态。
2. 每个动画的时长、是否循环、是否可中断。
3. 机器人屏是否需要 ACK、心跳或硬件状态回传。
4. 语音播放由儿童屏、机器人屏还是两者之一负责。
5. 是否有口型、字幕、动作 marks。
6. 资源缺失时允许使用的兜底动画。
