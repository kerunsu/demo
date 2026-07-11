import assert from "node:assert/strict";
import { access, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(fileURLToPath(new URL("../..", import.meta.url)));

async function loadService() {
  process.env.RAW_MEDIA_PERSISTENCE = process.env.RAW_MEDIA_PERSISTENCE ?? "enabled";
  process.env.RAW_MEDIA_ROOT = process.env.RAW_MEDIA_ROOT ?? path.join(projectRoot, ".runtime", "media");
  const module = await import("../backend/dist/services/rawMediaPersistenceService.js");
  return module;
}

const sessionId = process.argv[2];
const command = process.argv[3] ?? "diagnose";

if (command === "diagnose") {
  const { getRawMediaDiagnostics } = await loadService();
  const diagnostics = await getRawMediaDiagnostics();
  console.log(JSON.stringify(diagnostics, null, 2));
  assert.ok(typeof diagnostics.rootPath === "string");
  process.exit(0);
}

if (command === "purge") {
  const { purgeExpiredSessionMedia } = await loadService();
  const result = await purgeExpiredSessionMedia();
  console.log(JSON.stringify(result, null, 2));
  process.exit(0);
}

if (command === "delete" && sessionId) {
  const { deleteSessionMedia } = await loadService();
  await deleteSessionMedia(sessionId);
  console.log(JSON.stringify({ deletedSessionId: sessionId }, null, 2));
  process.exit(0);
}

if (command === "prepare-test-fixture" && sessionId) {
  const root = process.env.RAW_MEDIA_ROOT ?? path.join(projectRoot, ".runtime", "media");
  const sessionDir = path.join(root, sessionId);
  await mkdir(sessionDir, { recursive: true });
  const staleDate = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();
  await writeFile(
    path.join(sessionDir, "manifest.json"),
    `${JSON.stringify(
      {
        schemaVersion: "raw-media-manifest-v1",
        sessionId,
        createdAt: staleDate,
        updatedAt: staleDate,
        audio: {},
        video: {}
      },
      null,
      2
    )}\n`
  );
  await access(path.join(sessionDir, "manifest.json"));
  console.log(JSON.stringify({ preparedSessionId: sessionId, updatedAt: staleDate }, null, 2));
  process.exit(0);
}

console.error("Usage: node tools/media-persistence/manage.mjs [sessionId] [diagnose|purge|delete|prepare-test-fixture]");
process.exit(1);
