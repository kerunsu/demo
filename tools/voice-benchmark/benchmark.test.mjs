import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { STATUS, runBenchmark, selfTest } from "./benchmark.mjs";

test("voice benchmark self-test passes", async () => {
  const result = await selfTest();
  assert.equal(result.status, "PASS");
});

test("benchmark emits parseable JSON and required provider states", async () => {
  const run = await runBenchmark({ skipDocsReport: true });
  const parsed = JSON.parse(await readFile(run.jsonPath, "utf8"));

  assert.equal(parsed.schemaVersion, "m4.voiceBenchmark.v1");
  assert.equal(parsed.safety.noRealChildVoice, true);
  assert.equal(parsed.safety.formalBusinessLogicModified, false);
  assert.ok(parsed.sttResults.some((item) => item.provider.providerType === "mock" && item.status === STATUS.SUCCESS));
  assert.ok(parsed.sttResults.some((item) => item.provider.providerId === "local-stt-adapter" && item.status === STATUS.LOCAL_MODEL_PENDING));
  assert.ok(parsed.ttsResults.some((item) => item.provider.providerType === "mock" && item.status === STATUS.SUCCESS));
  assert.ok(parsed.ttsResults.some((item) => item.provider.providerId === "cloud-openai-stt" || item.provider.providerId === "cloud-openai-tts"));
  assert.ok(parsed.endToEndResults.length >= 4);
});
