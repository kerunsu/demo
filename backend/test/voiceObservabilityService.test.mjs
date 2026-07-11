import assert from "node:assert/strict";
import test from "node:test";

import {
  getVoiceMetricsForSession,
  getVoiceTurnSummary,
  recordVoiceMetric,
  recordVoiceTurnTotal,
  resetVoiceObservabilityForTests
} from "../dist/services/voiceObservabilityService.js";

test("voice observability deduplicates stage metrics and keeps transcript text private", () => {
  resetVoiceObservabilityForTests();
  const input = {
    sessionId: "sess_obs",
    turnId: "turn_obs",
    correlationId: "corr_obs",
    stage: "transcript_available",
    textForHash: "我的电话是13800000000",
    startedAt: "2026-06-13T08:00:00.000Z",
    completedAt: "2026-06-13T08:00:00.010Z",
    provider: "mock-stt",
    model: "fixture-transcript-v1"
  };

  const first = recordVoiceMetric(input);
  const duplicate = recordVoiceMetric(input);
  const metrics = getVoiceMetricsForSession("sess_obs");

  assert.ok(first);
  assert.equal(duplicate, null);
  assert.equal(metrics.length, 1);
  assert.equal(metrics[0].textLength, input.textForHash.length);
  assert.equal(metrics[0].textHash.length, 16);
  assert.equal(Object.values(metrics[0]).includes(input.textForHash), false);
  assert.equal(metrics[0].rawAudioPersisted, false);
  assert.equal(metrics[0].sensitiveTextLogged, false);
});

test("voice observability bounds memory and records total turn latency once", () => {
  resetVoiceObservabilityForTests();
  for (let index = 0; index < 1005; index += 1) {
    recordVoiceMetric({
      sessionId: "sess_many",
      turnId: `turn_${index}`,
      correlationId: `corr_${index}`,
      stage: "audio_capture_start"
    });
  }
  assert.equal(getVoiceMetricsForSession("sess_many").length, 1000);

  recordVoiceMetric({
    sessionId: "sess_total",
    turnId: "turn_total",
    correlationId: "corr_total",
    stage: "audio_capture_start",
    startedAt: "2026-06-13T08:00:00.000Z",
    completedAt: "2026-06-13T08:00:00.000Z"
  });
  recordVoiceMetric({
    sessionId: "sess_total",
    turnId: "turn_total",
    correlationId: "corr_total",
    stage: "tts_audio_ready",
    startedAt: "2026-06-13T08:00:01.000Z",
    completedAt: "2026-06-13T08:00:01.250Z"
  });

  assert.ok(
    recordVoiceTurnTotal({
      sessionId: "sess_total",
      turnId: "turn_total",
      correlationId: "corr_total",
      completedAt: "2026-06-13T08:00:02.000Z"
    })
  );
  assert.equal(
    recordVoiceTurnTotal({
      sessionId: "sess_total",
      turnId: "turn_total",
      correlationId: "corr_total",
      completedAt: "2026-06-13T08:00:03.000Z"
    }),
    null
  );

  const summary = getVoiceTurnSummary("sess_total", "turn_total");
  assert.equal(summary.metricCount, 3);
  assert.equal(summary.totalDurationMs, 2000);
  assert.equal(summary.stages.filter((metric) => metric.stage === "voice_turn_total").length, 1);
});
