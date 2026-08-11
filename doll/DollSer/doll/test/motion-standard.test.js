'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { buildSequenceExpressionTiming, validateMotionDocument } = require('../public/motion-standard');

function validMotion(overrides = {}) {
  return {
    version: 2,
    format: 'dollser-motion',
    armBaselineVersion: 2,
    updatedAt: '2026-07-15T00:00:00.000Z',
    name: '点头确认',
    durationMs: 500,
    initialPose: { pitch: 180, yaw: 180, armL: 270, armR: 270 },
    commands: [
      { actionId: 'a-1', time: 0, axis: 'pitch', angle: 196, moveMs: 220, label: '点头', phase: 'move' },
      { actionId: 'a-1', time: 260, axis: 'pitch', angle: 180, moveMs: 220, label: '回中位', phase: 'return' },
    ],
    ...overrides,
  };
}

test('accepts a valid version 2 motion document', () => {
  const result = validateMotionDocument(validMotion());
  assert.equal(result.valid, true);
  assert.equal(result.errors.length, 0);
  assert.equal(result.stats.commandCount, 2);
});

test('rejects unsupported format and invalid command values', () => {
  const result = validateMotionDocument(validMotion({
    format: 'legacy-motion',
    commands: [{ time: -1, axis: 'head', angle: 400, moveMs: 20 }],
  }));
  assert.equal(result.valid, false);
  assert.ok(result.errors.some((item) => item.code === 'format'));
  assert.ok(result.errors.some((item) => item.code === 'command-axis'));
  assert.ok(result.errors.some((item) => item.code === 'command-angle'));
});

test('rejects a duration that cuts off the final command', () => {
  const result = validateMotionDocument(validMotion({ durationMs: 300 }));
  assert.equal(result.valid, false);
  assert.ok(result.errors.some((item) => item.code === 'duration-cover'));
});

test('warns when same-axis commands overlap without blocking delivery', () => {
  const motion = validMotion({
    commands: [
      { actionId: 'a', time: 0, axis: 'yaw', angle: 160, moveMs: 300, label: '左转', phase: 'move' },
      { actionId: 'b', time: 200, axis: 'yaw', angle: 180, moveMs: 300, label: '回正', phase: 'move' },
    ],
  });
  const result = validateMotionDocument(motion);
  assert.equal(result.valid, true);
  assert.ok(result.warnings.some((item) => item.code === 'axis-overlap'));
});

test('requires commands and all four initial pose axes', () => {
  const result = validateMotionDocument(validMotion({
    initialPose: { pitch: 180 },
    commands: [],
  }));
  assert.equal(result.valid, false);
  assert.ok(result.errors.some((item) => item.path === 'initialPose.armL'));
  assert.ok(result.errors.some((item) => item.code === 'commands'));
});

test('validates expression cues against the shared motion duration', () => {
  const result = validateMotionDocument(validMotion({
    durationMs: 1500,
    expression: { scope: 'sequence', mediaId: 'happy.png', time: 300, motionStartTime: 500, offsetMs: -200, leadMs: 200, leadSeconds: 0.2, durationMs: 900, loop: true },
  }));
  assert.equal(result.valid, true);
  assert.equal(result.stats.expressionCount, 1);

  const invalid = validateMotionDocument(validMotion({
    durationMs: 500,
    expression: { scope: 'sequence', mediaId: '', time: 300, motionStartTime: 500, offsetMs: -200, durationMs: 900 },
  }));
  assert.equal(invalid.valid, false);
  assert.ok(invalid.errors.some((item) => item.code === 'expression-media'));
  assert.ok(invalid.errors.some((item) => item.code === 'duration-cover'));
});

test('adds pre-roll when a sequence expression starts before robot motion', () => {
  const timing = buildSequenceExpressionTiming({ mediaId: 'happy.mp4', offsetMs: -600, durationMs: 1200 }, 2000);
  assert.deepEqual(timing, {
    offsetMs: -600,
    motionStartTime: 600,
    expressionTime: 0,
    expressionDurationMs: 1200,
    durationMs: 2600,
  });
});

test('extends the shared timeline without shortening the robot motion', () => {
  const robotMotionDuration = 2400;
  const timing = buildSequenceExpressionTiming({ mediaId: 'happy.mp4', offsetMs: -500, durationMs: 4249 }, robotMotionDuration);
  assert.equal(timing.motionStartTime, 500);
  assert.equal(timing.motionStartTime + robotMotionDuration, 2900);
  assert.equal(timing.durationMs, 4249);
});
