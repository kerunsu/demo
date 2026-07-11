export const ROBOT_ANIMATION_IDS = [
  "eye",
  "curious",
  "happy",
  "excited",
  "look_down",
  "sad",
  "yawn",
  "dissatisfied",
  "open_eyes"
] as const;

export const ROBOT_ANIMATION_INTENTS = [
  "idle",
  "greeting",
  "question_presented",
  "listening",
  "thinking",
  "speaking",
  "correct_praise",
  "wrong_encourage",
  "hint",
  "course_complete",
  "error_recovering",
  "special_state"
] as const;

export type RobotAnimationId = (typeof ROBOT_ANIMATION_IDS)[number];
export type RobotAnimationIntent = (typeof ROBOT_ANIMATION_INTENTS)[number];
export type RobotAnimationPriority = "low" | "normal" | "high";
export type RobotAnimationAssetType = "gif" | "css" | "video" | "lottie" | "image_sequence" | "robot_sdk";
export type RobotAnimationInterruptPolicy = "queue" | "replace_same_intent" | "interrupt" | "ignore_if_playing";
export type RobotAnimationDurationSource = "verified" | "estimated" | "pending_verification";
export type RobotAnimationPlaybackStatus = "started" | "completed" | "interrupted" | "failed";
export type RobotAnimationEventType =
  | "ANIMATION_PRELOAD_REQUESTED"
  | "ANIMATION_PRELOADED"
  | "ANIMATION_REQUESTED"
  | "ANIMATION_STARTED"
  | "ANIMATION_FINISHED"
  | "ANIMATION_FAILED";

export interface RobotAnimationManifestItem {
  animationId: RobotAnimationId;
  fileName: string;
  resourceRef: string;
  assetType: RobotAnimationAssetType;
  intent: RobotAnimationIntent;
  expectedDurationMs: number | null;
  durationSource: RobotAnimationDurationSource;
  loop: boolean;
  priority: RobotAnimationPriority;
  interruptible: boolean;
  preloadRequired: boolean;
  fallbackAnimationId?: RobotAnimationId;
  notes: string;
}

export type RobotAnimationManifest = readonly RobotAnimationManifestItem[];

export interface RobotAnimationPlayOptions {
  commandId: string;
  sessionId: string;
  sourceEventId: string;
  animationId?: RobotAnimationId;
  intent: RobotAnimationIntent;
  priority?: RobotAnimationPriority;
  expectedDurationMs?: number;
  loop?: boolean;
  interruptPolicy?: RobotAnimationInterruptPolicy;
  speechTurnId?: string;
}

export interface RobotAnimationCommand {
  commandId: string;
  sessionId: string;
  sourceEventId: string;
  animationId: RobotAnimationId;
  intent: RobotAnimationIntent;
  priority: RobotAnimationPriority;
  expectedDurationMs: number | null;
  loop: boolean;
  interruptPolicy: RobotAnimationInterruptPolicy;
  speechTurnId?: string;
}

export interface RobotAnimationAdapterStatus {
  online: boolean;
  currentCommandId?: string;
  currentAnimationId?: RobotAnimationId;
  isPlaying: boolean;
  lastEventId?: string;
}

export interface RobotAnimationPlaybackEvent {
  eventId: string;
  eventType: RobotAnimationEventType;
  commandId: string;
  sessionId: string;
  animationId: RobotAnimationId;
  intent: RobotAnimationIntent;
  status: RobotAnimationPlaybackStatus;
  timestamp: string;
  expectedDurationMs: number | null;
  loop: boolean;
  errorCode?: "ANIMATION_NOT_FOUND" | "RESOURCE_MISSING" | "PLAYBACK_FAILED" | "INTERRUPTED";
}

export interface RobotAnimationAdapter {
  preload(manifest: RobotAnimationManifest): Promise<void>;
  play(options: RobotAnimationPlayOptions): Promise<RobotAnimationPlaybackEvent>;
  stop(commandId?: string): Promise<RobotAnimationPlaybackEvent | null>;
  showIdle(sessionId: string, sourceEventId: string): Promise<RobotAnimationPlaybackEvent>;
  isPlaying(): boolean;
  getStatus(): Promise<RobotAnimationAdapterStatus>;
}

export const ROBOT_ANIMATION_MANIFEST = [
  {
    animationId: "eye",
    fileName: "001_Eye.gif",
    resourceRef: "/Emotions/001_Eye.gif",
    assetType: "gif",
    intent: "idle",
    expectedDurationMs: null,
    durationSource: "pending_verification",
    loop: true,
    priority: "low",
    interruptible: true,
    preloadRequired: true,
    notes: "Default idle animation; actual duration and loop behavior need verification."
  },
  {
    animationId: "curious",
    fileName: "002_Curious.gif",
    resourceRef: "/Emotions/002_Curious.gif",
    assetType: "gif",
    intent: "listening",
    expectedDurationMs: null,
    durationSource: "pending_verification",
    loop: true,
    priority: "normal",
    interruptible: true,
    preloadRequired: true,
    fallbackAnimationId: "eye",
    notes: "Curious/listening animation; preferred gentle fallback for wrong answers."
  },
  {
    animationId: "happy",
    fileName: "003_Happy.gif",
    resourceRef: "/Emotions/003_Happy.gif",
    assetType: "gif",
    intent: "correct_praise",
    expectedDurationMs: null,
    durationSource: "pending_verification",
    loop: false,
    priority: "normal",
    interruptible: true,
    preloadRequired: true,
    fallbackAnimationId: "eye",
    notes: "General correct-answer praise animation."
  },
  {
    animationId: "excited",
    fileName: "004_Excited.gif",
    resourceRef: "/Emotions/004_Excited.gif",
    assetType: "gif",
    intent: "course_complete",
    expectedDurationMs: null,
    durationSource: "pending_verification",
    loop: false,
    priority: "high",
    interruptible: false,
    preloadRequired: true,
    fallbackAnimationId: "happy",
    notes: "High-energy praise or course completion animation."
  },
  {
    animationId: "look_down",
    fileName: "005_LookDown.gif",
    resourceRef: "/Emotions/005_LookDown.gif",
    assetType: "gif",
    intent: "thinking",
    expectedDurationMs: null,
    durationSource: "pending_verification",
    loop: true,
    priority: "normal",
    interruptible: true,
    preloadRequired: true,
    fallbackAnimationId: "curious",
    notes: "Thinking or short attention-shift animation."
  },
  {
    animationId: "sad",
    fileName: "006_Sad.gif",
    resourceRef: "/Emotions/006_Sad.gif",
    assetType: "gif",
    intent: "special_state",
    expectedDurationMs: null,
    durationSource: "pending_verification",
    loop: false,
    priority: "low",
    interruptible: true,
    preloadRequired: false,
    fallbackAnimationId: "eye",
    notes: "Special expression; not part of the default wrong-answer flow."
  },
  {
    animationId: "yawn",
    fileName: "007_Yawn.gif",
    resourceRef: "/Emotions/007_Yawn.gif",
    assetType: "gif",
    intent: "special_state",
    expectedDurationMs: null,
    durationSource: "pending_verification",
    loop: false,
    priority: "low",
    interruptible: true,
    preloadRequired: false,
    fallbackAnimationId: "eye",
    notes: "Special or demo-only expression."
  },
  {
    animationId: "dissatisfied",
    fileName: "008_Dissatisfied.gif",
    resourceRef: "/Emotions/008_Dissatisfied.gif",
    assetType: "gif",
    intent: "special_state",
    expectedDurationMs: null,
    durationSource: "pending_verification",
    loop: false,
    priority: "low",
    interruptible: true,
    preloadRequired: false,
    fallbackAnimationId: "eye",
    notes: "Special expression; not part of the default wrong-answer flow."
  },
  {
    animationId: "open_eyes",
    fileName: "009_OpenEyes.gif",
    resourceRef: "/Emotions/009_OpenEyes.gif",
    assetType: "gif",
    intent: "greeting",
    expectedDurationMs: null,
    durationSource: "pending_verification",
    loop: false,
    priority: "normal",
    interruptible: true,
    preloadRequired: true,
    fallbackAnimationId: "eye",
    notes: "Wake-up, training start, or attention recovery animation."
  }
] as const satisfies RobotAnimationManifest;

function createEventId(commandId: string, eventType: RobotAnimationEventType): string {
  return `${commandId}:${eventType.toLowerCase()}`;
}

function nowIso(): string {
  return new Date().toISOString();
}

export function findRobotAnimationById(animationId: RobotAnimationId): RobotAnimationManifestItem {
  const item = ROBOT_ANIMATION_MANIFEST.find((animation) => animation.animationId === animationId);
  if (!item) {
    throw new Error(`Unknown robot animationId: ${animationId}`);
  }
  return item;
}

export function resolveRobotAnimationForIntent(intent: RobotAnimationIntent): RobotAnimationManifestItem {
  return (
    ROBOT_ANIMATION_MANIFEST.find((animation) => animation.intent === intent) ??
    findRobotAnimationById("eye")
  );
}

export function createRobotAnimationCommand(options: RobotAnimationPlayOptions): RobotAnimationCommand {
  const manifestItem = options.animationId
    ? findRobotAnimationById(options.animationId)
    : resolveRobotAnimationForIntent(options.intent);

  return {
    commandId: options.commandId,
    sessionId: options.sessionId,
    sourceEventId: options.sourceEventId,
    animationId: manifestItem.animationId,
    intent: options.intent,
    priority: options.priority ?? manifestItem.priority,
    expectedDurationMs: options.expectedDurationMs ?? manifestItem.expectedDurationMs,
    loop: options.loop ?? manifestItem.loop,
    interruptPolicy: options.interruptPolicy ?? "replace_same_intent",
    speechTurnId: options.speechTurnId
  };
}

export class MockRobotAnimationAdapter implements RobotAnimationAdapter {
  private manifest: RobotAnimationManifest = ROBOT_ANIMATION_MANIFEST;
  private currentCommand: RobotAnimationCommand | null = null;
  private lastEventId: string | undefined;

  async preload(manifest: RobotAnimationManifest): Promise<void> {
    this.manifest = manifest;
  }

  async play(options: RobotAnimationPlayOptions): Promise<RobotAnimationPlaybackEvent> {
    const command = createRobotAnimationCommand(options);
    const exists = this.manifest.some((animation) => animation.animationId === command.animationId);

    if (!exists) {
      const fallback = findRobotAnimationById("eye");
      const event = this.createEvent(command, "ANIMATION_FAILED", "failed", "ANIMATION_NOT_FOUND", fallback.animationId);
      this.lastEventId = event.eventId;
      return event;
    }

    this.currentCommand = command;
    const event = this.createEvent(command, "ANIMATION_STARTED", "started");
    this.lastEventId = event.eventId;
    return event;
  }

  async stop(commandId?: string): Promise<RobotAnimationPlaybackEvent | null> {
    if (!this.currentCommand) return null;
    if (commandId && this.currentCommand.commandId !== commandId) return null;

    const stoppedCommand = this.currentCommand;
    this.currentCommand = null;
    const event = this.createEvent(stoppedCommand, "ANIMATION_FINISHED", "interrupted", "INTERRUPTED");
    this.lastEventId = event.eventId;
    return event;
  }

  async showIdle(sessionId: string, sourceEventId: string): Promise<RobotAnimationPlaybackEvent> {
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

  isPlaying(): boolean {
    return this.currentCommand !== null;
  }

  async getStatus(): Promise<RobotAnimationAdapterStatus> {
    return {
      online: true,
      currentCommandId: this.currentCommand?.commandId,
      currentAnimationId: this.currentCommand?.animationId,
      isPlaying: this.isPlaying(),
      lastEventId: this.lastEventId
    };
  }

  private createEvent(
    command: RobotAnimationCommand,
    eventType: RobotAnimationEventType,
    status: RobotAnimationPlaybackStatus,
    errorCode?: RobotAnimationPlaybackEvent["errorCode"],
    animationId = command.animationId
  ): RobotAnimationPlaybackEvent {
    return {
      eventId: createEventId(command.commandId, eventType),
      eventType,
      commandId: command.commandId,
      sessionId: command.sessionId,
      animationId,
      intent: command.intent,
      status,
      timestamp: nowIso(),
      expectedDurationMs: command.expectedDurationMs,
      loop: command.loop,
      errorCode
    };
  }
}
