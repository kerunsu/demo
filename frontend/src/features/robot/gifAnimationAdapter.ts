import {
  createRobotAnimationCommand,
  findRobotAnimationById,
  type RobotAnimationAdapterStatus,
  type RobotAnimationId,
  type RobotAnimationPlayOptions
} from "child-education-training-demo/shared/animations";
import { resolveBackendAssetUrl } from "../../config/runtime";

export type GifPlaybackEvent =
  | { type: "started"; commandId: string; animationId: RobotAnimationId; src: string }
  | {
      type: "finished";
      commandId: string;
      animationId: RobotAnimationId;
      status: "completed" | "failed" | "interrupted";
      durationMs: number;
      errorCode?: string;
    };

export class GifAnimationAdapter {
  private current: ReturnType<typeof createRobotAnimationCommand> | null = null;
  private timer: number | null = null;
  private replayNonce = 0;

  constructor(private emit: (event: GifPlaybackEvent) => void) {}

  play(options: RobotAnimationPlayOptions) {
    const command = createRobotAnimationCommand(options);
    if (command.interruptPolicy === "ignore_if_playing" && this.current) {
      return { command, src: null, skipped: true as const };
    }
    this.stop();
    const manifest = findRobotAnimationById(command.animationId);
    this.current = command;
    this.replayNonce += 1;
    const src = `${resolveBackendAssetUrl(manifest.resourceRef)}?replay=${this.replayNonce}`;
    this.emit({ type: "started", commandId: command.commandId, animationId: command.animationId, src });
    if (!command.loop) {
      const durationMs = command.expectedDurationMs ?? manifest.expectedDurationMs ?? 1200;
      this.timer = window.setTimeout(() => {
        this.timer = null;
        this.current = null;
        this.emit({
          type: "finished",
          commandId: command.commandId,
          animationId: command.animationId,
          status: "completed",
          durationMs
        });
      }, durationMs);
    }
    return { command, src };
  }

  failCurrent(errorCode = "RESOURCE_MISSING") {
    if (!this.current) return;
    const command = this.current;
    this.clearTimer();
    this.current = null;
    this.emit({
      type: "finished",
      commandId: command.commandId,
      animationId: command.animationId,
      status: "failed",
      durationMs: 0,
      errorCode
    });
  }

  stop() {
    if (!this.current) return;
    const command = this.current;
    this.clearTimer();
    this.current = null;
    this.emit({
      type: "finished",
      commandId: command.commandId,
      animationId: command.animationId,
      status: "interrupted",
      durationMs: 0,
      errorCode: "INTERRUPTED"
    });
  }

  showIdle(sessionId: string, sourceEventId: string) {
    return this.play({
      commandId: `idle:${sessionId}`,
      sessionId,
      sourceEventId,
      animationId: "eye",
      intent: "idle",
      loop: true,
      interruptPolicy: "interrupt"
    });
  }

  isPlaying() {
    return this.current !== null;
  }

  isIdleLoop() {
    return this.current?.animationId === "eye" && this.current.loop;
  }

  getStatus(): RobotAnimationAdapterStatus {
    return {
      online: true,
      currentCommandId: this.current?.commandId,
      currentAnimationId: this.current?.animationId,
      isPlaying: this.isPlaying()
    };
  }

  private clearTimer() {
    if (this.timer !== null) {
      window.clearTimeout(this.timer);
      this.timer = null;
    }
  }
}
