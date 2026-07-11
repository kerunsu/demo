import assert from "node:assert/strict";
import test from "node:test";

import { interpretPythonVoiceHealthBody } from "../dist/services/pythonVoiceHealthService.js";

test("interpretPythonVoiceHealthBody accepts healthy local providers", () => {
  const status = interpretPythonVoiceHealthBody(
    {
      status: "ok",
      sttProvider: "local-vosk",
      ttsProvider: "local-piper",
      sttProviderStatus: "READY",
      ttsProviderStatus: "READY"
    },
    { expectLocalStt: true, expectLocalTts: true }
  );
  assert.equal(status, "ok");
});

test("interpretPythonVoiceHealthBody flags mock providers when local is expected", () => {
  const status = interpretPythonVoiceHealthBody(
    {
      status: "ok",
      sttProvider: "mock",
      ttsProvider: "mock",
      sttProviderStatus: "READY",
      ttsProviderStatus: "READY"
    },
    { expectLocalStt: true, expectLocalTts: true }
  );
  assert.equal(status, "degraded:mock_providers");
});

test("interpretPythonVoiceHealthBody flags pending local models", () => {
  const status = interpretPythonVoiceHealthBody(
    {
      status: "ok",
      sttProvider: "local-vosk",
      ttsProvider: "local-piper",
      sttProviderStatus: "LOCAL_MODEL_PENDING",
      ttsProviderStatus: "READY"
    },
    { expectLocalStt: true, expectLocalTts: true }
  );
  assert.equal(status, "degraded:local_model_pending");
});
