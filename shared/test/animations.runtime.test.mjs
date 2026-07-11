import assert from "node:assert/strict";
import test from "node:test";

import {
  MockRobotAnimationAdapter,
  ROBOT_ANIMATION_IDS,
  ROBOT_ANIMATION_MANIFEST,
  createRobotAnimationCommand,
  findRobotAnimationById,
  resolveRobotAnimationForIntent
} from "../dist/animations.js";

test("robot animation manifest contains the nine confirmed GIF animation ids", () => {
  assert.deepEqual(ROBOT_ANIMATION_IDS, [
    "eye",
    "curious",
    "happy",
    "excited",
    "look_down",
    "sad",
    "yawn",
    "dissatisfied",
    "open_eyes"
  ]);
  assert.equal(ROBOT_ANIMATION_MANIFEST.length, 9);
  assert.equal(new Set(ROBOT_ANIMATION_MANIFEST.map((item) => item.animationId)).size, 9);

  for (const item of ROBOT_ANIMATION_MANIFEST) {
    assert.equal(item.assetType, "gif");
    assert.match(item.resourceRef, /^\/Emotions\/\d{3}_.+\.gif$/);
    assert.equal(item.durationSource, "pending_verification");
    assert.equal(Object.hasOwn(item, "expectedDurationMs"), true);
    assert.equal(typeof item.loop, "boolean");
  }
});

test("manifest encodes product-safe default intent mapping", () => {
  assert.equal(resolveRobotAnimationForIntent("idle").animationId, "eye");
  assert.equal(resolveRobotAnimationForIntent("listening").animationId, "curious");
  assert.equal(resolveRobotAnimationForIntent("correct_praise").animationId, "happy");
  assert.equal(resolveRobotAnimationForIntent("course_complete").animationId, "excited");
  assert.equal(resolveRobotAnimationForIntent("thinking").animationId, "look_down");
  assert.equal(resolveRobotAnimationForIntent("greeting").animationId, "open_eyes");

  const discouragedDefaults = new Set(["sad", "dissatisfied"]);
  for (const intent of ["wrong_encourage", "hint", "idle"]) {
    assert.equal(discouragedDefaults.has(resolveRobotAnimationForIntent(intent).animationId), false);
  }
});

test("animation commands resolve ids, loop flags, and interrupt policy without loading resources", () => {
  const command = createRobotAnimationCommand({
    commandId: "animation-command-1",
    sessionId: "session-1",
    sourceEventId: "event-1",
    intent: "course_complete"
  });

  assert.equal(command.animationId, "excited");
  assert.equal(command.priority, "high");
  assert.equal(command.loop, false);
  assert.equal(command.interruptPolicy, "replace_same_intent");

  const explicit = createRobotAnimationCommand({
    commandId: "animation-command-2",
    sessionId: "session-1",
    sourceEventId: "event-1",
    animationId: "eye",
    intent: "idle",
    expectedDurationMs: 1800,
    loop: false,
    interruptPolicy: "interrupt"
  });

  assert.equal(explicit.animationId, "eye");
  assert.equal(explicit.expectedDurationMs, 1800);
  assert.equal(explicit.loop, false);
  assert.equal(explicit.interruptPolicy, "interrupt");
});

test("mock adapter emits start, stop, idle, and status events", async () => {
  const adapter = new MockRobotAnimationAdapter();
  await adapter.preload(ROBOT_ANIMATION_MANIFEST);

  const started = await adapter.play({
    commandId: "animation-command-3",
    sessionId: "session-1",
    sourceEventId: "event-3",
    intent: "listening"
  });
  assert.equal(started.eventType, "ANIMATION_STARTED");
  assert.equal(started.animationId, "curious");
  assert.equal(adapter.isPlaying(), true);

  const status = await adapter.getStatus();
  assert.equal(status.currentCommandId, "animation-command-3");
  assert.equal(status.currentAnimationId, "curious");

  const stopped = await adapter.stop("animation-command-3");
  assert.equal(stopped.eventType, "ANIMATION_FINISHED");
  assert.equal(stopped.status, "interrupted");
  assert.equal(adapter.isPlaying(), false);

  const idle = await adapter.showIdle("session-1", "event-idle");
  assert.equal(idle.animationId, "eye");
  assert.equal(idle.loop, true);
});

test("unknown animation ids fail loudly through manifest lookup", () => {
  assert.throws(() => findRobotAnimationById("missing"), /Unknown robot animationId/);
});
