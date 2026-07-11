import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const projectRoot = path.resolve(fileURLToPath(new URL("../..", import.meta.url)));

async function readDoc(relativePath) {
  return readFile(path.join(projectRoot, relativePath), "utf8");
}

test("M5 acceptance docs record code completion and environment pending without unsafe claims", async () => {
  const development = await readDoc("docs/M5_DEVELOPMENT_ACCEPTANCE.md");
  const field = await readDoc("docs/M5_FIELD_ACCEPTANCE_CHECKLIST.md");
  const fixtures = await readDoc("docs/TEST_FIXTURES.md");

  assert.ok(development.includes("COMPLETE_CODE_WITH_ENVIRONMENT_PENDING"));
  assert.ok(development.includes("Real child data used: no"));
  assert.ok(development.includes("External cloud vision/STT/TTS/LLM calls: none"));
  assert.ok(field.includes("ENVIRONMENT_PENDING"));
  assert.ok(field.includes("No raw frame upload to external cloud vision services"));
  assert.ok(fixtures.includes("rawFramePersisted: false"));
  assert.equal(development.includes("clinical diagnosis complete"), false);
  assert.equal(field.includes("| Robot camera permission | `COMPLETE`"), false);
});
