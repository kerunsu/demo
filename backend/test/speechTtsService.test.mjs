import assert from "node:assert/strict";
import test from "node:test";
import "./testEnv.mjs";

import { getSpeechTtsProviderStatus, synthesizeSpeech } from "../dist/services/speechTtsService.js";

test("speech TTS defaults to mock provider and returns reviewed audio", async () => {
  const status = getSpeechTtsProviderStatus();
  assert.equal(status.providerId, "mock-tts");
  assert.equal(status.externalNetworkCalled, false);

  const result = await synthesizeSpeech({
    sessionId: "session-tts",
    turnId: "turn-tts",
    correlationId: "corr-tts",
    text: "我们继续做题吧。"
  });

  assert.equal(result.ok, true);
  assert.equal(result.metadata.providerName, "mock-tts");
  assert.equal(result.data.turnId, "turn-tts");
  assert.equal(result.data.mimeType, "audio/wav");
  assert.equal(result.data.durationMs > 0, true);
});
