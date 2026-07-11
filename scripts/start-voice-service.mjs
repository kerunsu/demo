import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workspaceRoot = path.resolve(repoRoot, "..");
const scriptPath = path.join(repoRoot, "tools", "voice-service", "voice_service.py");
const expertAsdPython = path.join(
  workspaceRoot,
  "ExpertAnnotator_ASD-main",
  "asd_llm_agent",
  ".venv",
  "Scripts",
  "python.exe"
);
const expertVoskModel = path.join(
  workspaceRoot,
  "ExpertAnnotator_ASD-main",
  "asd_llm_agent",
  "models",
  "vosk-model-small-cn-0.22"
);
const runtimePythonSite = path.join(repoRoot, ".runtime", "python-site");
const pythonPath = process.env.PYTHONPATH
  ? `${runtimePythonSite}${path.delimiter}${process.env.PYTHONPATH}`
  : runtimePythonSite;
const useLocalVosk = process.argv.includes("--local-vosk") || process.argv.includes("--stt=local-vosk");
const useLocalFunasr = process.argv.includes("--local-funasr") || process.argv.includes("--stt=local-funasr");
const defaultSttProvider = useLocalFunasr ? "local-funasr" : useLocalVosk ? "local-vosk" : "mock";
const sttProvider = useLocalFunasr || useLocalVosk ? defaultSttProvider : process.env.VOICE_SERVICE_STT_PROVIDER ?? defaultSttProvider;
const pythonExecutable =
  process.env.VOICE_SERVICE_PYTHON ||
  ((useLocalFunasr || useLocalVosk) && fs.existsSync(expertAsdPython) ? expertAsdPython : "python");
const defaultVoskModel =
  useLocalVosk && !process.env.VOICE_SERVICE_VOSK_MODEL && fs.existsSync(expertVoskModel)
    ? expertVoskModel
    : process.env.VOICE_SERVICE_VOSK_MODEL;

const child = spawn(pythonExecutable, [scriptPath], {
  cwd: repoRoot,
  stdio: "inherit",
  env: {
    ...process.env,
    PYTHONPATH: pythonPath,
    VOICE_SERVICE_STT_PROVIDER: sttProvider,
    VOICE_SERVICE_TTS_PROVIDER: process.env.VOICE_SERVICE_TTS_PROVIDER ?? "mock",
    ...(defaultVoskModel ? { VOICE_SERVICE_VOSK_MODEL: defaultVoskModel } : {})
  }
});

child.on("exit", (code) => {
  process.exit(code ?? 0);
});
