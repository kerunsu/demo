import assert from "node:assert/strict";
import { test } from "node:test";
import { VOICE_PARTNER_TURN_SCHEMA } from "child-education-training-demo/shared/voice-partner-contract";

test("voice partner contract schema constants are stable", () => {
  assert.equal(VOICE_PARTNER_TURN_SCHEMA, "voice-partner-turn-v1");
});
