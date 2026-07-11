import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(fileURLToPath(new URL("../..", import.meta.url)));

async function readProjectFile(relativePath) {
  return readFile(path.join(projectRoot, relativePath), "utf8");
}

test("M7-A deployment operations files define safe production defaults", async () => {
  const backendEnv = await readProjectFile("deploy/production.env.example");
  const frontendEnv = await readProjectFile("deploy/frontend.env.example");
  const runbook = await readProjectFile("docs/DEPLOYMENT_OPERATIONS_M7.md");

  assert.ok(backendEnv.includes("BACKEND_HOST=0.0.0.0"));
  assert.ok(backendEnv.includes("AI_CHAT_PROVIDER=rule"));
  assert.ok(backendEnv.includes("AI_TTS_PROVIDER=none"));
  assert.ok(backendEnv.includes("VOICE_STT_PROVIDER=mock"));
  assert.ok(backendEnv.includes("VOICE_TTS_PROVIDER=mock"));
  assert.ok(backendEnv.includes("ATTENTION_PROVIDER=mock"));
  assert.ok(backendEnv.includes("DEMO_STORAGE_PROVIDER=sqlite"));
  assert.ok(backendEnv.includes("VOICE_SERVICE_STT_PROVIDER=local-vosk"));
  assert.ok(backendEnv.includes("VOICE_SERVICE_TTS_PROVIDER=local-piper"));
  assert.ok(frontendEnv.includes("VITE_API_BASE_URL=http://SERVER_LAN_IP:3001/api"));
  assert.ok(frontendEnv.includes("VITE_WS_URL=ws://SERVER_LAN_IP:3001/ws"));
  assert.ok(runbook.includes("ENVIRONMENT_PENDING"));
  assert.equal(/OPENAI_API_KEY\s*=\s*["']?sk-/.test(`${backendEnv}\n${frontendEnv}\n${runbook}`), false);
});

test("M7-A operations scripts cover start, stop, health, backup, deletion, and diagnostics", async () => {
  const start = await readProjectFile("scripts/ops/Start-DemoProduction.ps1");
  const stop = await readProjectFile("scripts/ops/Stop-DemoProduction.ps1");
  const health = await readProjectFile("scripts/ops/Test-DemoHealth.ps1");
  const backup = await readProjectFile("scripts/ops/Backup-DemoRuntime.ps1");
  const clear = await readProjectFile("scripts/ops/Clear-DemoRuntimeData.ps1");
  const diagnostics = await readProjectFile("scripts/ops/Collect-DemoDiagnostics.ps1");

  assert.ok(start.includes("Start-Process"));
  assert.ok(start.includes("-WindowStyle Hidden"));
  assert.ok(start.includes('$Name.pid'));
  assert.ok(start.includes("StartVoiceService"));
  assert.ok(start.includes("StartFrontend"));
  assert.ok(start.includes("VOICE_SERVICE_STT_PROVIDER"));
  assert.ok(start.includes("VOICE_SERVICE_TTS_PROVIDER"));
  assert.ok(start.includes("ATTENTION_PROVIDER"));
  assert.ok(start.includes("DEMO_SQLITE_DB_PATH"));
  assert.ok(stop.includes("Stop-Process"));
  assert.ok(stop.includes("voice-service.pid"));
  assert.ok(stop.includes("frontend.pid"));
  assert.ok(health.includes("/api/health"));
  assert.ok(backup.includes("Compress-Archive"));
  assert.ok(backup.includes("demo.sqlite3"));
  assert.ok(clear.includes("SupportsShouldProcess"));
  assert.ok(clear.includes("StartsWith($resolvedRoot"));
  assert.ok(clear.includes("RetentionDays"));
  assert.ok(clear.includes("delete-before"));
  assert.ok(diagnostics.includes("git -C $resolvedRoot rev-parse --short HEAD"));
  assert.ok(diagnostics.includes("python_voice_service_health"));
  assert.ok(diagnostics.includes("websocket_connect"));
  assert.ok(diagnostics.includes("MANUAL_ACCEPTANCE_REQUIRED"));
  assert.equal(/OPENAI_API_KEY\s*=\s*["']?sk-/.test(`${start}\n${stop}\n${health}\n${backup}\n${clear}\n${diagnostics}`), false);
});

test("M7-B field acceptance materials cover long-run, recovery, privacy, license, and release gates", async () => {
  const longRun = await readProjectFile("scripts/ops/Invoke-LongRunSmoke.ps1");
  const acceptance = await readProjectFile("docs/STABILITY_FIELD_ACCEPTANCE_M7.md");

  assert.ok(longRun.includes("DurationMinutes"));
  assert.ok(longRun.includes("MaxLogMegabytes"));
  assert.ok(longRun.includes("/api/health"));
  assert.ok(longRun.includes("long-run"));
  for (const required of [
    "Recovery Drills",
    "Multi-Session Checks",
    "Privacy And Retention",
    "License And Human Review",
    "Release Checklist",
    "Stop Conditions",
    "ENVIRONMENT_PENDING",
    "DEMO_RETENTION_DAYS=30"
  ]) {
    assert.ok(acceptance.includes(required), `missing ${required}`);
  }
  assert.equal(/sk-[A-Za-z0-9]/.test(`${longRun}\n${acceptance}`), false);
});
