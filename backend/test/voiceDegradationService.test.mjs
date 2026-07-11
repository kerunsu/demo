import assert from "node:assert/strict";
import test from "node:test";

import {
  getVoiceDegradationPlan,
  mapProviderErrorToVoiceDegradation
} from "../dist/services/voiceDegradationService.js";

test("voice degradation plans cover child-safe fallback modes without raw persistence or external network", () => {
  for (const reason of [
    "MICROPHONE_UNAVAILABLE",
    "MEDIA_TRANSPORT_FAILED",
    "STT_PROVIDER_UNAVAILABLE",
    "STT_EMPTY_RESULT",
    "STT_LOW_CONFIDENCE",
    "TTS_PROVIDER_UNAVAILABLE",
    "TTS_SAFETY_REJECTED",
    "WEBSOCKET_DISCONNECTED",
    "ROBOT_AUDIO_PLAYBACK_FAILED"
  ]) {
    const plan = getVoiceDegradationPlan(reason);
    assert.equal(plan.reason, reason);
    assert.equal(typeof plan.childSafeText, "string");
    assert.ok(plan.childSafeText.length > 0);
    assert.equal(plan.rawAudioPersisted, false);
    assert.equal(plan.externalNetworkRequired, false);
  }
});

test("provider errors map to retryable voice degradation paths", () => {
  assert.equal(mapProviderErrorToVoiceDegradation("EMPTY_RESULT").reason, "STT_EMPTY_RESULT");
  assert.equal(mapProviderErrorToVoiceDegradation("LOW_CONFIDENCE").fallbackMode, "retry_voice");
  assert.equal(mapProviderErrorToVoiceDegradation("SAFETY_REJECTED").reason, "TTS_SAFETY_REJECTED");
  assert.equal(mapProviderErrorToVoiceDegradation("PROVIDER_FAILURE").reason, "STT_PROVIDER_UNAVAILABLE");
});
