import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { performance } from "node:perf_hooks";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const defaultOutputDir = path.join(repoRoot, ".runtime");
const defaultReportPath = path.join(repoRoot, "docs", "VOICE_STT_TTS_BENCHMARK_REPORT.md");
const realLocalPythonPath = path.join(__dirname, ".venv", "Scripts", "python.exe");
const realLocalScriptPath = path.join(__dirname, "real_local_benchmark.py");
const defaultVoskModelPath = path.join(repoRoot, ".runtime", "models", "vosk", "vosk-model-small-cn-0.22");
const defaultPiperModelPath = path.join(repoRoot, ".runtime", "models", "piper", "zh_CN-huayan-medium.onnx");
const defaultPiperConfigPath = path.join(repoRoot, ".runtime", "models", "piper", "zh_CN-huayan-medium.onnx.json");

const STATUS = {
  SUCCESS: "SUCCESS",
  FAILED: "FAILED",
  CLOUD_CREDENTIALS_PENDING: "CLOUD_CREDENTIALS_PENDING",
  CLOUD_DISABLED: "CLOUD_DISABLED",
  LOCAL_MODEL_PENDING: "LOCAL_MODEL_PENDING",
  NOT_APPLICABLE: "NOT_APPLICABLE"
};

function parseArgs(argv) {
  const args = {
    outputDir: defaultOutputDir,
    docsReportPath: defaultReportPath,
    selfTest: false,
    skipDocsReport: false
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--self-test") args.selfTest = true;
    if (arg === "--skip-docs-report") args.skipDocsReport = true;
    if (arg === "--output-dir") {
      args.outputDir = path.resolve(argv[index + 1]);
      index += 1;
    }
    if (arg === "--docs-report") {
      args.docsReportPath = path.resolve(argv[index + 1]);
      index += 1;
    }
  }
  return args;
}

function nowIso() {
  return new Date().toISOString();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function round(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  return Number(value.toFixed(digits));
}

function hashForDisplay(text) {
  let hash = 2166136261;
  for (const char of text) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function getResourceSnapshot() {
  const cpus = os.cpus();
  return {
    timestamp: nowIso(),
    cpu: {
      model: cpus[0]?.model ?? "unknown",
      logicalCores: cpus.length,
      processUserMicros: process.cpuUsage().user,
      processSystemMicros: process.cpuUsage().system,
      loadAverage: os.loadavg()
    },
    memory: {
      processRssMB: round(process.memoryUsage().rss / 1024 / 1024),
      processHeapUsedMB: round(process.memoryUsage().heapUsed / 1024 / 1024),
      systemTotalGB: round(os.totalmem() / 1024 / 1024 / 1024),
      systemFreeGB: round(os.freemem() / 1024 / 1024 / 1024)
    },
    gpu: {
      source: "M4-001 capability report if available",
      summary: "unknown"
    }
  };
}

async function loadGpuSummary(outputDir) {
  const capabilityPath = path.join(outputDir, "voice-capabilities.json");
  if (!existsSync(capabilityPath)) return "unknown";
  try {
    const parsed = JSON.parse(await readFile(capabilityPath, "utf8"));
    const names = parsed?.gpu?.controllers?.map((gpu) => gpu.name).filter(Boolean) ?? [];
    return names.length > 0 ? names.join("; ") : "unknown";
  } catch {
    return "unknown";
  }
}

function measureDelta(before, after) {
  return {
    cpuUserMicros: after.cpu.processUserMicros - before.cpu.processUserMicros,
    cpuSystemMicros: after.cpu.processSystemMicros - before.cpu.processSystemMicros,
    processRssDeltaMB: round(after.memory.processRssMB - before.memory.processRssMB),
    processHeapDeltaMB: round(after.memory.processHeapUsedMB - before.memory.processHeapUsedMB),
    before,
    after
  };
}

function createProviderMeta({ providerId, providerType, modelId, externalNetworkCalled, inputPersisted, fallbackPath }) {
  return {
    providerId,
    providerType,
    modelId,
    externalNetworkCalled,
    inputPersisted,
    fallbackPath
  };
}

function createBaseResult({ kind, provider, status, runId, fixtureId, startedAt }) {
  return {
    schemaVersion: "m4.voiceBenchmark.result.v1",
    kind,
    runId,
    fixtureId,
    startedAt,
    finishedAt: null,
    status,
    provider,
    metrics: {},
    output: {},
    error: null,
    notes: []
  };
}

function createErrorDetails(type, details = {}) {
  const error = {
    type: String(type || "UNKNOWN_ERROR")
  };
  if (details.message) error.message = String(details.message).slice(0, 500);
  if (details.stderr) error.stderr = String(details.stderr).slice(0, 500);
  if (details.stdout) error.stdout = String(details.stdout).slice(0, 500);
  if (details.exitCode !== undefined && details.exitCode !== null) error.exitCode = details.exitCode;
  return error;
}

function execFileJson(command, args, options = {}) {
  return new Promise((resolve) => {
    execFile(command, args, { timeout: 300000, windowsHide: true, ...options }, (error, stdout, stderr) => {
      resolve({ error, stdout, stderr });
    });
  });
}

function writePcm16Wav({ filePath, sampleRate, durationSeconds, generator }) {
  const sampleCount = Math.max(1, Math.floor(sampleRate * durationSeconds));
  const dataSize = sampleCount * 2;
  const buffer = Buffer.alloc(44 + dataSize);
  buffer.write("RIFF", 0);
  buffer.writeUInt32LE(36 + dataSize, 4);
  buffer.write("WAVE", 8);
  buffer.write("fmt ", 12);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * 2, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write("data", 36);
  buffer.writeUInt32LE(dataSize, 40);
  for (let i = 0; i < sampleCount; i += 1) {
    const value = Math.max(-1, Math.min(1, generator(i / sampleRate, i)));
    buffer.writeInt16LE(Math.round(value * 32767), 44 + i * 2);
  }
  return writeFile(filePath, buffer);
}

async function getWavDurationSeconds(filePath) {
  const buffer = await readFile(filePath);
  if (buffer.toString("ascii", 0, 4) !== "RIFF" || buffer.toString("ascii", 8, 12) !== "WAVE") {
    return null;
  }
  let offset = 12;
  let sampleRate = null;
  let channels = null;
  let bitsPerSample = null;
  let dataSize = null;
  while (offset + 8 <= buffer.length) {
    const id = buffer.toString("ascii", offset, offset + 4);
    const size = buffer.readUInt32LE(offset + 4);
    if (id === "fmt ") {
      channels = buffer.readUInt16LE(offset + 10);
      sampleRate = buffer.readUInt32LE(offset + 12);
      bitsPerSample = buffer.readUInt16LE(offset + 22);
    }
    if (id === "data") {
      dataSize = size;
      break;
    }
    offset += 8 + size + (size % 2);
  }
  if (!sampleRate || !channels || !bitsPerSample || !dataSize) return null;
  return dataSize / (sampleRate * channels * (bitsPerSample / 8));
}

async function prepareFixtures(outputDir) {
  const fixtureDir = path.join(outputDir, "voice-benchmark-fixtures");
  await mkdir(fixtureDir, { recursive: true });
  const shortPath = path.join(fixtureDir, "synthetic-zh-short.wav");
  const silencePath = path.join(fixtureDir, "synthetic-silence.wav");
  const noisePath = path.join(fixtureDir, "synthetic-noise.wav");

  await writePcm16Wav({
    filePath: shortPath,
    sampleRate: 16000,
    durationSeconds: 1.8,
    generator: (t) => 0.24 * Math.sin(2 * Math.PI * 440 * t)
  });
  await writePcm16Wav({
    filePath: silencePath,
    sampleRate: 16000,
    durationSeconds: 1,
    generator: () => 0
  });
  await writePcm16Wav({
    filePath: noisePath,
    sampleRate: 16000,
    durationSeconds: 1.2,
    generator: (_, i) => (((i * 1103515245 + 12345) >>> 16) % 65536) / 65536 * 0.08 - 0.04
  });

  return [
    {
      fixtureId: "synthetic-zh-short",
      kind: "synthetic_audio",
      language: "zh-CN",
      path: shortPath,
      transcriptExpected: "你好，这是M4语音基准测试",
      textForTts: "你好，这是M4语音基准测试。",
      containsRealChildVoice: false,
      license: "generated at runtime by benchmark harness; not committed",
      durationSeconds: round(await getWavDurationSeconds(shortPath), 3)
    },
    {
      fixtureId: "synthetic-silence",
      kind: "silence",
      language: "none",
      path: silencePath,
      transcriptExpected: "",
      textForTts: "",
      containsRealChildVoice: false,
      license: "generated at runtime by benchmark harness; not committed",
      durationSeconds: round(await getWavDurationSeconds(silencePath), 3)
    },
    {
      fixtureId: "synthetic-noise",
      kind: "noise",
      language: "none",
      path: noisePath,
      transcriptExpected: "",
      textForTts: "",
      containsRealChildVoice: false,
      license: "generated at runtime by benchmark harness; not committed",
      durationSeconds: round(await getWavDurationSeconds(noisePath), 3)
    }
  ];
}

async function runTimed(fn) {
  const before = getResourceSnapshot();
  const started = performance.now();
  const value = await fn();
  const ended = performance.now();
  const after = getResourceSnapshot();
  return {
    value,
    durationMs: round(ended - started),
    resources: measureDelta(before, after)
  };
}

const mockSttProvider = {
  meta: createProviderMeta({
    providerId: "mock-stt-fixture",
    providerType: "mock",
    modelId: "fixture-transcript-v1",
    externalNetworkCalled: false,
    inputPersisted: false,
    fallbackPath: "none"
  }),
  async initialize() {
    await sleep(5);
    return { status: STATUS.SUCCESS, durationMs: 5, modelLoadMs: 0 };
  },
  async healthCheck() {
    return { status: STATUS.SUCCESS };
  },
  async transcribe({ fixture }) {
    await sleep(15);
    return {
      status: STATUS.SUCCESS,
      transcript: fixture.transcriptExpected,
      transcriptHash: hashForDisplay(fixture.transcriptExpected),
      confidence: fixture.transcriptExpected ? 1 : 0,
      partialFirstMs: fixture.transcriptExpected ? 6 : null,
      finalMs: 15,
      accuracyObservation: fixture.transcriptExpected
        ? "fixture echo for harness validation; not a model accuracy measurement"
        : "silence/noise fixture returned empty transcript",
      language: fixture.language,
      noiseObservation: fixture.kind === "noise" ? "mock returned configured empty transcript" : "not measured"
    };
  }
};

const localSttProvider = {
  meta: createProviderMeta({
    providerId: "local-stt-adapter",
    providerType: "local",
    modelId: "not-configured",
    externalNetworkCalled: false,
    inputPersisted: false,
    fallbackPath: "mock-stt-fixture"
  }),
  async initialize() {
    return {
      status: STATUS.LOCAL_MODEL_PENDING,
      durationMs: 0,
      modelLoadMs: null,
      reason: "No local STT model or executable is configured in this repository; adapter retained for M4-003 contract work."
    };
  },
  async healthCheck() {
    return { status: STATUS.LOCAL_MODEL_PENDING };
  },
  async transcribe({ fixture }) {
    return {
      status: STATUS.LOCAL_MODEL_PENDING,
      transcript: null,
      transcriptHash: null,
      confidence: null,
      partialFirstMs: null,
      finalMs: null,
      audioDurationSeconds: fixture.durationSeconds,
      accuracyObservation: "not executed; no local STT model installed or configured",
      language: fixture.language,
      noiseObservation: "not executed"
    };
  }
};

function getCloudApiKey() {
  return process.env.VOICE_BENCHMARK_OPENAI_API_KEY || process.env.OPENAI_API_KEY || "";
}

function getCloudBaseUrl() {
  return (process.env.VOICE_BENCHMARK_OPENAI_BASE_URL || process.env.OPENAI_BASE_URL || "https://api.openai.com/v1").replace(/\/$/, "");
}

const openAiCloudSttProvider = {
  meta: createProviderMeta({
    providerId: "cloud-openai-stt",
    providerType: "cloud",
    modelId: process.env.VOICE_BENCHMARK_OPENAI_STT_MODEL || "whisper-1",
    externalNetworkCalled: false,
    inputPersisted: "provider_policy_unknown",
    fallbackPath: "local-stt-adapter or mock-stt-fixture"
  }),
  async initialize() {
    const apiKey = getCloudApiKey();
    if (!apiKey) {
      return { status: STATUS.CLOUD_CREDENTIALS_PENDING, durationMs: 0, modelLoadMs: null };
    }
    if (process.env.VOICE_BENCHMARK_ENABLE_CLOUD !== "1") {
      return { status: STATUS.CLOUD_DISABLED, durationMs: 0, modelLoadMs: null };
    }
    return { status: STATUS.SUCCESS, durationMs: 0, modelLoadMs: null };
  },
  async healthCheck() {
    const init = await this.initialize();
    return { status: init.status };
  },
  async transcribe({ fixture }) {
    const apiKey = getCloudApiKey();
    if (!apiKey) return { status: STATUS.CLOUD_CREDENTIALS_PENDING };
    if (process.env.VOICE_BENCHMARK_ENABLE_CLOUD !== "1") return { status: STATUS.CLOUD_DISABLED };

    const bytes = await readFile(fixture.path);
    const form = new FormData();
    form.set("model", this.meta.modelId);
    form.set("language", fixture.language === "zh-CN" ? "zh" : "en");
    form.set("file", new Blob([bytes], { type: "audio/wav" }), `${fixture.fixtureId}.wav`);
    const response = await fetch(`${getCloudBaseUrl()}/audio/transcriptions`, {
      method: "POST",
      headers: { Authorization: `Bearer ${apiKey}` },
      body: form
    });
    if (!response.ok) {
      return {
        status: STATUS.FAILED,
        errorType: `HTTP_${response.status}`,
        transcript: null
      };
    }
    const parsed = await response.json();
    const transcript = typeof parsed.text === "string" ? parsed.text : "";
    return {
      status: STATUS.SUCCESS,
      transcript,
      transcriptHash: hashForDisplay(transcript),
      confidence: null,
      partialFirstMs: null,
      finalMs: null,
      accuracyObservation: "cloud transcript captured; manual review required",
      language: fixture.language,
      noiseObservation: "manual review required"
    };
  }
};

const mockTtsProvider = {
  meta: createProviderMeta({
    providerId: "mock-tts-silence",
    providerType: "mock",
    modelId: "synthetic-silence-v1",
    externalNetworkCalled: false,
    inputPersisted: false,
    fallbackPath: "none"
  }),
  async initialize() {
    await sleep(5);
    return { status: STATUS.SUCCESS, durationMs: 5, modelLoadMs: 0 };
  },
  async healthCheck() {
    return { status: STATUS.SUCCESS };
  },
  async synthesize({ text, outputDir }) {
    const outputPath = path.join(outputDir, "voice-benchmark-fixtures", "mock-tts-silence.wav");
    await writePcm16Wav({
      filePath: outputPath,
      sampleRate: 16000,
      durationSeconds: 0.8,
      generator: () => 0
    });
    return {
      status: STATUS.SUCCESS,
      outputPath,
      audioDurationSeconds: round(await getWavDurationSeconds(outputPath), 3),
      format: "audio/wav",
      firstByteMs: 1,
      intelligibilityObservation: text ? "mock silence; not intelligibility evidence" : "empty text",
      naturalnessObservation: "not applicable to mock silence"
    };
  }
};

function runPowerShellSapi({ outputPath, text }) {
  const outputPathBase64 = Buffer.from(outputPath, "utf8").toString("base64");
  const textBase64 = Buffer.from(text, "utf8").toString("base64");
  const script = `
$ErrorActionPreference = "Stop"
$OutputPath = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String("${outputPathBase64}"))
$Text = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String("${textBase64}"))
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  try {
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo("zh-CN")
    $synth.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet, [System.Speech.Synthesis.VoiceAge]::NotSet, 0, $culture)
  } catch {
    # Use system default voice when zh-CN voice is unavailable.
  }
  $synth.SetOutputToWaveFile($OutputPath)
  $synth.Speak($Text)
} finally {
  $synth.Dispose()
}
`;
  const encodedCommand = Buffer.from(script, "utf16le").toString("base64");
  return new Promise((resolve) => {
    const child = execFile(
      "powershell",
      ["-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encodedCommand],
      { timeout: 20000, windowsHide: true },
      (error, stdout, stderr) => {
        resolve({ error, stdout, stderr });
      }
    );
    child.stdin?.end();
  });
}

const localWindowsTtsProvider = {
  meta: createProviderMeta({
    providerId: "local-windows-sapi-tts",
    providerType: "local",
    modelId: "windows-system-speech",
    externalNetworkCalled: false,
    inputPersisted: false,
    fallbackPath: "mock-tts-silence"
  }),
  async initialize() {
    return { status: process.platform === "win32" ? STATUS.SUCCESS : STATUS.LOCAL_MODEL_PENDING, durationMs: 0, modelLoadMs: 0 };
  },
  async healthCheck() {
    return { status: process.platform === "win32" ? STATUS.SUCCESS : STATUS.LOCAL_MODEL_PENDING };
  },
  async synthesize({ text, outputDir }) {
    if (process.platform !== "win32") {
      return {
        status: STATUS.LOCAL_MODEL_PENDING,
        errorType: "NOT_WINDOWS",
        intelligibilityObservation: "not executed",
        naturalnessObservation: "not executed"
      };
    }
    const outputPath = path.join(outputDir, "voice-benchmark-fixtures", "local-windows-sapi-tts.wav");
    const started = performance.now();
    const result = await runPowerShellSapi({ outputPath, text });
    const elapsed = round(performance.now() - started);
    if (result.error || !existsSync(outputPath)) {
      return {
        status: STATUS.FAILED,
        errorType: result.error?.code || "SAPI_FAILED",
        errorDetails: {
          message: "PowerShell SAPI synthesis failed or produced no output file.",
          stderr: result.stderr,
          stdout: result.stdout,
          exitCode: result.error?.code
        },
        outputPath: null,
        firstByteMs: null,
        totalSynthesisMs: elapsed,
        format: "audio/wav",
        intelligibilityObservation: "manual review required; synthesis failed",
        naturalnessObservation: "manual review required; synthesis failed"
      };
    }
    return {
      status: STATUS.SUCCESS,
      outputPath,
      audioDurationSeconds: round(await getWavDurationSeconds(outputPath), 3),
      format: "audio/wav",
      firstByteMs: elapsed,
      totalSynthesisMs: elapsed,
      intelligibilityObservation: "manual listening required; not scored by harness",
      naturalnessObservation: "manual listening required; not scored by harness"
    };
  }
};

const openAiCloudTtsProvider = {
  meta: createProviderMeta({
    providerId: "cloud-openai-tts",
    providerType: "cloud",
    modelId: process.env.VOICE_BENCHMARK_OPENAI_TTS_MODEL || process.env.OPENAI_TTS_MODEL || "gpt-4o-mini-tts",
    externalNetworkCalled: false,
    inputPersisted: "provider_policy_unknown",
    fallbackPath: "local-windows-sapi-tts or mock-tts-silence"
  }),
  async initialize() {
    const apiKey = getCloudApiKey();
    if (!apiKey) return { status: STATUS.CLOUD_CREDENTIALS_PENDING, durationMs: 0, modelLoadMs: null };
    if (process.env.VOICE_BENCHMARK_ENABLE_CLOUD !== "1") return { status: STATUS.CLOUD_DISABLED, durationMs: 0, modelLoadMs: null };
    return { status: STATUS.SUCCESS, durationMs: 0, modelLoadMs: null };
  },
  async healthCheck() {
    const init = await this.initialize();
    return { status: init.status };
  },
  async synthesize({ text, outputDir }) {
    const apiKey = getCloudApiKey();
    if (!apiKey) return { status: STATUS.CLOUD_CREDENTIALS_PENDING };
    if (process.env.VOICE_BENCHMARK_ENABLE_CLOUD !== "1") return { status: STATUS.CLOUD_DISABLED };

    const voice = process.env.VOICE_BENCHMARK_OPENAI_TTS_VOICE || process.env.OPENAI_TTS_VOICE || "alloy";
    const started = performance.now();
    const response = await fetch(`${getCloudBaseUrl()}/audio/speech`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        model: this.meta.modelId,
        voice,
        input: text,
        format: "wav"
      })
    });
    const firstByteMs = round(performance.now() - started);
    if (!response.ok) {
      return {
        status: STATUS.FAILED,
        errorType: `HTTP_${response.status}`,
        firstByteMs,
        format: "audio/wav"
      };
    }
    const arrayBuffer = await response.arrayBuffer();
    const outputPath = path.join(outputDir, "voice-benchmark-fixtures", "cloud-openai-tts.wav");
    await writeFile(outputPath, Buffer.from(arrayBuffer));
    return {
      status: STATUS.SUCCESS,
      outputPath,
      audioDurationSeconds: round(await getWavDurationSeconds(outputPath), 3),
      format: "audio/wav",
      firstByteMs,
      totalSynthesisMs: round(performance.now() - started),
      intelligibilityObservation: "manual listening required",
      naturalnessObservation: "manual listening required"
    };
  }
};

async function runSttProvider({ provider, fixture, runId }) {
  const startedAt = nowIso();
  const result = createBaseResult({
    kind: "stt",
    provider: { ...provider.meta },
    status: STATUS.FAILED,
    runId,
    fixtureId: fixture.fixtureId,
    startedAt
  });
  const init = await runTimed(() => provider.initialize());
  const health = await provider.healthCheck();
  result.metrics.initializationMs = init.durationMs;
  result.metrics.modelLoadMs = init.value.modelLoadMs ?? null;
  result.metrics.audioDurationSeconds = fixture.durationSeconds;
  result.metrics.resourceUsage = init.resources;
  result.output.healthStatus = health.status;
  try {
    const transcription = await runTimed(() => provider.transcribe({ fixture }));
    const value = transcription.value;
    result.status = value.status;
    result.finishedAt = nowIso();
    result.metrics.processingMs = transcription.durationMs;
    result.metrics.finalReturnMs = value.finalMs ?? transcription.durationMs;
    result.metrics.partialFirstReturnMs = value.partialFirstMs ?? null;
    result.metrics.realTimeFactor =
      fixture.durationSeconds && transcription.durationMs
        ? round(transcription.durationMs / 1000 / fixture.durationSeconds, 4)
        : null;
    result.metrics.resourceUsage = transcription.resources;
    result.output.transcript = value.transcript;
    result.output.transcriptHash = value.transcriptHash;
    result.output.confidence = value.confidence ?? null;
    result.output.language = value.language ?? fixture.language;
    result.output.accuracyObservation = value.accuracyObservation ?? "not measured";
    result.output.noiseObservation = value.noiseObservation ?? "not measured";
    result.error = value.errorType ? createErrorDetails(value.errorType, value.errorDetails) : null;
    if (value.status === STATUS.CLOUD_CREDENTIALS_PENDING) {
      result.notes.push("Cloud STT not executed because credentials are absent.");
    }
    if (value.status === STATUS.CLOUD_DISABLED) {
      result.notes.push("Cloud STT not executed because VOICE_BENCHMARK_ENABLE_CLOUD is not 1.");
    }
    if (value.status === STATUS.LOCAL_MODEL_PENDING) {
      result.notes.push("Local STT adapter retained, but no model is configured; no recognition was performed.");
    }
  } catch (error) {
    result.status = STATUS.FAILED;
    result.finishedAt = nowIso();
    result.error = createErrorDetails(error.name, { message: error.message });
  }
  return result;
}

async function runTtsProvider({ provider, text, fixtureId, outputDir, runId }) {
  const startedAt = nowIso();
  const result = createBaseResult({
    kind: "tts",
    provider: { ...provider.meta },
    status: STATUS.FAILED,
    runId,
    fixtureId,
    startedAt
  });
  const init = await runTimed(() => provider.initialize());
  const health = await provider.healthCheck();
  result.metrics.initializationMs = init.durationMs;
  result.metrics.modelLoadMs = init.value.modelLoadMs ?? null;
  result.metrics.resourceUsage = init.resources;
  result.output.healthStatus = health.status;
  try {
    const synthesis = await runTimed(() => provider.synthesize({ text, outputDir }));
    const value = synthesis.value;
    result.status = value.status;
    result.finishedAt = nowIso();
    result.metrics.processingMs = synthesis.durationMs;
    result.metrics.firstByteMs = value.firstByteMs ?? null;
    result.metrics.totalSynthesisMs = value.totalSynthesisMs ?? synthesis.durationMs;
    result.metrics.audioDurationSeconds = value.audioDurationSeconds ?? null;
    result.metrics.resourceUsage = synthesis.resources;
    result.output.audioRef = value.outputPath ? path.relative(repoRoot, value.outputPath) : null;
    result.output.audioFormat = value.format ?? null;
    result.output.textHash = hashForDisplay(text);
    result.output.intelligibilityObservation = value.intelligibilityObservation ?? "manual review required";
    result.output.naturalnessObservation = value.naturalnessObservation ?? "manual review required";
    result.error = value.errorType ? createErrorDetails(value.errorType, value.errorDetails) : null;
    if (value.status === STATUS.CLOUD_CREDENTIALS_PENDING) {
      result.notes.push("Cloud TTS not executed because credentials are absent.");
    }
    if (value.status === STATUS.CLOUD_DISABLED) {
      result.notes.push("Cloud TTS not executed because VOICE_BENCHMARK_ENABLE_CLOUD is not 1.");
    }
  } catch (error) {
    result.status = STATUS.FAILED;
    result.finishedAt = nowIso();
    result.error = createErrorDetails(error.name, { message: error.message });
  }
  return result;
}

function deriveEndToEndResults({ sttResults, ttsResults, runId }) {
  const combos = [
    ["local", "local"],
    ["local", "cloud"],
    ["cloud", "local"],
    ["cloud", "cloud"]
  ];
  return combos.map(([sttType, ttsType]) => {
    const stt = sttResults.find((item) => item.provider.providerType === sttType);
    const tts = ttsResults.find((item) => item.provider.providerType === ttsType);
    const status = stt?.status === STATUS.SUCCESS && tts?.status === STATUS.SUCCESS
      ? STATUS.SUCCESS
      : stt?.status === STATUS.CLOUD_CREDENTIALS_PENDING || tts?.status === STATUS.CLOUD_CREDENTIALS_PENDING
        ? STATUS.CLOUD_CREDENTIALS_PENDING
        : stt?.status === STATUS.CLOUD_DISABLED || tts?.status === STATUS.CLOUD_DISABLED
          ? STATUS.CLOUD_DISABLED
          : stt?.status === STATUS.LOCAL_MODEL_PENDING || tts?.status === STATUS.LOCAL_MODEL_PENDING
            ? STATUS.LOCAL_MODEL_PENDING
            : STATUS.FAILED;
    const transcriptMs = stt?.metrics.processingMs ?? null;
    const replyMs = 0;
    const audioReadyMs = tts?.metrics.processingMs ?? null;
    return {
      schemaVersion: "m4.voiceBenchmark.e2e.v1",
      runId,
      combinationId: `${sttType}-stt__${ttsType}-tts`,
      sttProviderId: stt?.provider.providerId ?? null,
      ttsProviderId: tts?.provider.providerId ?? null,
      status,
      metrics: {
        captureToTranscriptMs: transcriptMs,
        transcriptToReplyTextMs: replyMs,
        replyTextToPlayableAudioMs: audioReadyMs,
        totalTurnLatencyMs:
          typeof transcriptMs === "number" && typeof audioReadyMs === "number"
            ? round(transcriptMs + replyMs + audioReadyMs)
            : null
      },
      degradationPath: status === STATUS.SUCCESS ? "none" : "fallback to available local/mock provider or text interaction",
      networkDisconnectObservation:
        sttType === "cloud" || ttsType === "cloud"
          ? "requires M4-012/M4-014 network failure test; not exercised by this harness"
          : "not applicable to local/mock path"
    };
  });
}

function summarize(results) {
  const statuses = {};
  for (const item of [...results.sttResults, ...results.ttsResults, ...results.endToEndResults]) {
    statuses[item.status] = (statuses[item.status] ?? 0) + 1;
  }
  const localTts = results.ttsResults.find((item) => item.provider.providerId === "local-windows-sapi-tts");
  const localStt = results.sttResults.find((item) => item.provider.providerId === "local-stt-adapter");
  const cloudPending = [...results.sttResults, ...results.ttsResults].filter((item) => item.status === STATUS.CLOUD_CREDENTIALS_PENDING);
  const realLocal = results.realLocalValidation;
  const realDecision = realLocal?.decisions;
  return {
    statuses,
    testedLocalCandidates: results.sttResults.concat(results.ttsResults)
      .filter((item) => item.provider.providerType === "local")
      .map((item) => ({ providerId: item.provider.providerId, status: item.status })),
    testedCloudCandidates: results.sttResults.concat(results.ttsResults)
      .filter((item) => item.provider.providerType === "cloud" && item.status === STATUS.SUCCESS)
      .map((item) => ({ providerId: item.provider.providerId, status: item.status })),
    cloudCredentialsPending: cloudPending.map((item) => item.provider.providerId),
    realLocalValidationStatus: realLocal?.status ?? "LOCAL_VALIDATION_NOT_RUN",
    provisionalProviderDecision: realDecision ?? {
      stage: "LOCAL_STT_VALIDATION_PENDING",
      stt: "MOCK_ONLY_PENDING_VALIDATION",
      tts: "MOCK_ONLY_PENDING_VALIDATION"
    },
    recommendation: {
      providerCombination:
        realDecision?.stt && realDecision?.tts
          ? `${realDecision.stt} STT + ${realDecision.tts} TTS for the next integration spike; cloud remains optional until credentials are benchmarked.`
          : localStt?.status === STATUS.SUCCESS && localTts?.status === STATUS.SUCCESS
          ? "local STT + local TTS is viable for next integration spike"
          : localTts?.status === STATUS.SUCCESS
            ? "Use mock/local-STT adapter plus local Windows SAPI TTS for harness work; choose real STT after model or cloud credentials are available."
            : "Use mock providers until local STT/TTS or cloud credentials are available.",
      serverVoiceStack:
        realDecision?.serverVoiceStack ??
        "Node.js benchmark harness plus plugin-style providers now; evaluate Python service for real local STT models in M4-003/M4-006 if model ecosystem requires it.",
      manualReviewRequired: [
        "TTS intelligibility and naturalness",
        "Cloud STT transcript accuracy when credentials are available",
        "Local STT accuracy after a real model is configured",
        "Noise and classroom echo behavior"
      ]
    }
  };
}

function markdownTable(rows, columns) {
  const header = `| ${columns.map((column) => column.label).join(" | ")} |`;
  const sep = `| ${columns.map(() => "--").join(" | ")} |`;
  const body = rows.map((row) => `| ${columns.map((column) => String(column.value(row) ?? "")).join(" | ")} |`);
  return [header, sep, ...body].join("\n");
}

function renderMarkdownReport(results) {
  const sttTable = markdownTable(results.sttResults, [
    { label: "Provider", value: (row) => row.provider.providerId },
    { label: "Type", value: (row) => row.provider.providerType },
    { label: "Model", value: (row) => row.provider.modelId },
    { label: "Status", value: (row) => row.status },
    { label: "External Network", value: (row) => row.provider.externalNetworkCalled },
    { label: "Init ms", value: (row) => row.metrics.initializationMs },
    { label: "Process ms", value: (row) => row.metrics.processingMs },
    { label: "RTF", value: (row) => row.metrics.realTimeFactor },
    { label: "Transcript Hash", value: (row) => row.output.transcriptHash }
  ]);
  const ttsTable = markdownTable(results.ttsResults, [
    { label: "Provider", value: (row) => row.provider.providerId },
    { label: "Type", value: (row) => row.provider.providerType },
    { label: "Model", value: (row) => row.provider.modelId },
    { label: "Status", value: (row) => row.status },
    { label: "External Network", value: (row) => row.provider.externalNetworkCalled },
    { label: "Init ms", value: (row) => row.metrics.initializationMs },
    { label: "Process ms", value: (row) => row.metrics.processingMs },
    { label: "First byte ms", value: (row) => row.metrics.firstByteMs },
    { label: "Audio s", value: (row) => row.metrics.audioDurationSeconds }
  ]);
  const e2eTable = markdownTable(results.endToEndResults, [
    { label: "Combination", value: (row) => row.combinationId },
    { label: "Status", value: (row) => row.status },
    { label: "Transcript ms", value: (row) => row.metrics.captureToTranscriptMs },
    { label: "Reply ms", value: (row) => row.metrics.transcriptToReplyTextMs },
    { label: "Audio ready ms", value: (row) => row.metrics.replyTextToPlayableAudioMs },
    { label: "Total ms", value: (row) => row.metrics.totalTurnLatencyMs },
    { label: "Degradation", value: (row) => row.degradationPath }
  ]);
  const realLocal = results.realLocalValidation;
  const realLocalSection = realLocal?.candidates ? `
## M4-002B Real Local Validation

Status: ${realLocal.status}

State labels: BENCHMARK_HARNESS_COMPLETE, PROVISIONAL_PROVIDER_DECISION, CLOUD_STT_CREDENTIALS_PENDING, CLOUD_TTS_CREDENTIALS_PENDING.

### Candidate Selection

| Kind | Provider | Model | License | Model Size MB |
| -- | -- | -- | -- | -- |
| STT | ${realLocal.candidates.stt.providerId} | ${realLocal.candidates.stt.modelId} | ${realLocal.candidates.stt.license} | ${realLocal.candidates.stt.modelSizeMB} |
| TTS | ${realLocal.candidates.tts.providerId} | ${realLocal.candidates.tts.modelId} | ${realLocal.candidates.tts.license} | ${realLocal.candidates.tts.modelSizeMB} |

### Local STT Details

${markdownTable(realLocal.sttResults, [
  { label: "Fixture", value: (row) => `${row.fixtureId}#${row.iteration}` },
  { label: "Kind", value: (row) => row.fixtureKind },
  { label: "Audio s", value: (row) => row.audioDurationSeconds },
  { label: "Final ms", value: (row) => row.finalReturnMs },
  { label: "RTF", value: (row) => row.realTimeFactor },
  { label: "Transcript", value: (row) => row.finalTranscript },
  { label: "Peak RSS MB", value: (row) => row.resourceUsage?.rssPeakMB },
  { label: "GPU", value: (row) => row.gpuProvider }
])}

### Local TTS Details

${markdownTable(realLocal.ttsResults, [
  { label: "Text Id", value: (row) => row.textId },
  { label: "Synthesis ms", value: (row) => row.totalSynthesisMs },
  { label: "First playable ms", value: (row) => row.firstPlayableMs },
  { label: "Audio s", value: (row) => row.audioDurationSeconds },
  { label: "RTF", value: (row) => row.realTimeFactor },
  { label: "Peak RSS MB", value: (row) => row.resourceUsage?.rssPeakMB },
  { label: "Repeated", value: (row) => row.canSynthesizeRepeatedly },
  { label: "Review", value: (row) => row.naturalness }
])}

### M4-002B Decision

- STT: ${realLocal.decisions.stt}
- TTS: ${realLocal.decisions.tts}
- Stage: ${realLocal.decisions.stage}
- Server voice stack: ${realLocal.decisions.serverVoiceStack}
- Hardware acceleration: ${realLocal.environment.hardwareAcceleration}; GPU used: ${realLocal.environment.gpuAccelerationUsed}
- Human review: ${realLocal.humanReview.map((item) => item.status).join(", ")}
` : `
## M4-002B Real Local Validation

Status: LOCAL_STT_VALIDATION_PENDING / LOCAL_TTS_VALIDATION_PENDING

No real local validation result was attached to this run. Install the local benchmark dependencies and models, then run the harness again.
`;
  return `# M4-002 STT/TTS Benchmark Report

Generated: ${results.generatedAt}

Status: ${results.status}

Host baseline: ${results.environment.hostLabel}

## Safety

- Test data: synthetic non-child WAV generated at runtime.
- Audio files are written only under Git-ignored \`.runtime/\`.
- Cloud calls are disabled unless credentials exist and \`VOICE_BENCHMARK_ENABLE_CLOUD=1\`.
- No real API keys, full sensitive text, or test audio are committed.
- Formal training business logic was not modified.

## STT Results

${sttTable}

## TTS Results

${ttsTable}

## End-to-End Combination Results

${e2eTable}

${realLocalSection}

## Summary

\`\`\`json
${JSON.stringify(results.summary, null, 2)}
\`\`\`

## Recommendation

- Provider combination: ${results.summary.recommendation.providerCombination}
- Server voice stack: ${results.summary.recommendation.serverVoiceStack}
- Manual review still required: ${results.summary.recommendation.manualReviewRequired.join("; ")}.
`;
}

async function runRealLocalValidation(outputDir) {
  const missing = [];
  for (const [label, filePath] of [
    ["python", realLocalPythonPath],
    ["script", realLocalScriptPath],
    ["voskModel", defaultVoskModelPath],
    ["piperModel", defaultPiperModelPath],
    ["piperConfig", defaultPiperConfigPath]
  ]) {
    if (!existsSync(filePath)) missing.push(label);
  }
  if (missing.length > 0) {
    return {
      schemaVersion: "m4.voiceBenchmark.realLocal.v1",
      generatedAt: nowIso(),
      status: "LOCAL_STT_VALIDATION_PENDING",
      pendingReasons: missing,
      decisions: {
        stage: "LOCAL_STT_VALIDATION_PENDING",
        stt: "MOCK_ONLY_PENDING_VALIDATION",
        tts: "MOCK_ONLY_PENDING_VALIDATION",
        serverVoiceStack: "Node.js benchmark harness only until local Python voice dependencies and models are provisioned."
      }
    };
  }
  const realOutputDir = path.join(outputDir, "voice-benchmark");
  const outputJson = path.join(realOutputDir, "real-local-validation.json");
  const result = await execFileJson(realLocalPythonPath, [
    realLocalScriptPath,
    "--output-dir",
    realOutputDir,
    "--output-json",
    outputJson,
    "--vosk-model",
    defaultVoskModelPath,
    "--piper-model",
    defaultPiperModelPath,
    "--piper-config",
    defaultPiperConfigPath
  ]);
  if (result.error) {
    return {
      schemaVersion: "m4.voiceBenchmark.realLocal.v1",
      generatedAt: nowIso(),
      status: "FAILED",
      error: createErrorDetails(result.error.code || "REAL_LOCAL_VALIDATION_FAILED", {
        message: result.error.message,
        stderr: result.stderr,
        stdout: result.stdout,
        exitCode: result.error.code
      }),
      decisions: {
        stage: "LOCAL_STT_VALIDATION_PENDING",
        stt: "MOCK_ONLY_PENDING_VALIDATION",
        tts: "MOCK_ONLY_PENDING_VALIDATION",
        serverVoiceStack: "Node.js benchmark harness only until real local validation succeeds."
      }
    };
  }
  return JSON.parse(await readFile(outputJson, "utf8"));
}

async function runBenchmark(options = {}) {
  const outputDir = path.resolve(options.outputDir ?? defaultOutputDir);
  await mkdir(outputDir, { recursive: true });
  const runId = randomUUID();
  const generatedAt = nowIso();
  const fixtures = await prepareFixtures(outputDir);
  const primaryFixture = fixtures.find((fixture) => fixture.fixtureId === "synthetic-zh-short");
  const gpuSummary = await loadGpuSummary(outputDir);
  const environment = {
    hostLabel: "DEVELOPMENT_SERVER_BASELINE",
    node: process.version,
    platform: `${process.platform} ${os.release()} ${os.arch()}`,
    cpuModel: os.cpus()[0]?.model ?? "unknown",
    logicalCores: os.cpus().length,
    totalMemoryGB: round(os.totalmem() / 1024 / 1024 / 1024),
    gpuSummary
  };

  const sttProviders = [mockSttProvider, localSttProvider, openAiCloudSttProvider];
  const ttsProviders = [mockTtsProvider, localWindowsTtsProvider, openAiCloudTtsProvider];
  const sttResults = [];
  const ttsResults = [];
  for (const provider of sttProviders) {
    const result = await runSttProvider({ provider, fixture: primaryFixture, runId });
    if (provider.meta.providerType === "cloud" && result.status === STATUS.SUCCESS) {
      result.provider.externalNetworkCalled = true;
    }
    sttResults.push(result);
  }
  for (const provider of ttsProviders) {
    const result = await runTtsProvider({
      provider,
      text: primaryFixture.textForTts,
      fixtureId: primaryFixture.fixtureId,
      outputDir,
      runId
    });
    if (provider.meta.providerType === "cloud" && result.status === STATUS.SUCCESS) {
      result.provider.externalNetworkCalled = true;
    }
    ttsResults.push(result);
  }
  const endToEndResults = deriveEndToEndResults({ sttResults, ttsResults, runId });
  const realLocalValidation = await runRealLocalValidation(outputDir);
  const results = {
    schemaVersion: "m4.voiceBenchmark.v1",
    runId,
    generatedAt,
    status: "COMPLETE_FOR_DEVELOPMENT",
    safety: {
      noRealChildVoice: true,
      noCommittedAudio: true,
      apiKeysReadFromEnvironmentOnly: true,
      cloudExecutionRequiresExplicitEnable: true,
      formalBusinessLogicModified: false
    },
    environment,
    fixtures: fixtures.map((fixture) => ({
      fixtureId: fixture.fixtureId,
      kind: fixture.kind,
      language: fixture.language,
      durationSeconds: fixture.durationSeconds,
      containsRealChildVoice: fixture.containsRealChildVoice,
      license: fixture.license,
      path: path.relative(repoRoot, fixture.path)
    })),
    sttResults,
    ttsResults,
    endToEndResults,
    realLocalValidation,
    summary: null
  };
  results.summary = summarize(results);
  const jsonPath = path.join(outputDir, "voice-benchmark-results.json");
  const runtimeReportPath = path.join(outputDir, "voice-benchmark-report.md");
  const markdown = renderMarkdownReport(results);
  await writeFile(jsonPath, `${JSON.stringify(results, null, 2)}\n`, "utf8");
  await writeFile(runtimeReportPath, markdown, "utf8");
  if (!options.skipDocsReport) {
    await writeFile(path.resolve(options.docsReportPath ?? defaultReportPath), markdown, "utf8");
  }
  return {
    results,
    jsonPath,
    runtimeReportPath,
    docsReportPath: options.skipDocsReport ? null : path.resolve(options.docsReportPath ?? defaultReportPath)
  };
}

async function selfTest() {
  const tempDir = path.join(os.tmpdir(), `m4-voice-benchmark-${randomUUID()}`);
  const run = await runBenchmark({ outputDir: tempDir, skipDocsReport: true });
  const parsed = JSON.parse(await readFile(run.jsonPath, "utf8"));
  const checks = [
    { name: "json_parse", passed: parsed.schemaVersion === "m4.voiceBenchmark.v1" },
    { name: "mock_stt_success", passed: parsed.sttResults.some((item) => item.provider.providerId === "mock-stt-fixture" && item.status === STATUS.SUCCESS) },
    { name: "cloud_stt_not_blocking", passed: parsed.sttResults.some((item) => item.provider.providerId === "cloud-openai-stt" && [STATUS.CLOUD_CREDENTIALS_PENDING, STATUS.CLOUD_DISABLED, STATUS.SUCCESS, STATUS.FAILED].includes(item.status)) },
    { name: "cloud_tts_not_blocking", passed: parsed.ttsResults.some((item) => item.provider.providerId === "cloud-openai-tts" && [STATUS.CLOUD_CREDENTIALS_PENDING, STATUS.CLOUD_DISABLED, STATUS.SUCCESS, STATUS.FAILED].includes(item.status)) },
    { name: "no_committed_audio_paths", passed: parsed.fixtures.every((fixture) => fixture.path.startsWith(path.relative(repoRoot, tempDir))) },
    { name: "report_written", passed: (await stat(run.runtimeReportPath)).size > 0 }
  ];
  return {
    status: checks.every((check) => check.passed) ? "PASS" : "FAIL",
    outputDir: tempDir,
    checks
  };
}

if (import.meta.url === `file://${process.argv[1].replaceAll("\\", "/")}` || process.argv[1]?.endsWith("benchmark.mjs")) {
  const args = parseArgs(process.argv.slice(2));
  if (args.selfTest) {
    const result = await selfTest();
    console.log(JSON.stringify(result, null, 2));
    if (result.status !== "PASS") process.exit(1);
  } else {
    const result = await runBenchmark(args);
    console.log(JSON.stringify({
      status: result.results.status,
      jsonPath: path.relative(repoRoot, result.jsonPath),
      runtimeReportPath: path.relative(repoRoot, result.runtimeReportPath),
      docsReportPath: result.docsReportPath ? path.relative(repoRoot, result.docsReportPath) : null,
      summary: result.results.summary
    }, null, 2));
  }
}

export {
  STATUS,
  runBenchmark,
  selfTest,
  getWavDurationSeconds,
  prepareFixtures
};
