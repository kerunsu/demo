# M4-002 Voice Benchmark Harness

This directory contains a standalone benchmark harness for M4-002. It does not modify the production frontend or backend training flow.

## Commands

```powershell
node tools/voice-benchmark/benchmark.mjs
node --test tools/voice-benchmark/benchmark.test.mjs
```

For M4-002B real local validation, create the project-local venv and install benchmark-only Python packages:

```powershell
python -m venv tools\voice-benchmark\.venv
tools\voice-benchmark\.venv\Scripts\python.exe -m pip install -r tools\voice-benchmark\requirements-local.txt
```

The real local validation script expects these Git-ignored model paths:

```text
.runtime/models/vosk/vosk-model-small-cn-0.22
.runtime/models/piper/zh_CN-huayan-medium.onnx
.runtime/models/piper/zh_CN-huayan-medium.onnx.json
```

Run it directly when debugging:

```powershell
tools\voice-benchmark\.venv\Scripts\python.exe tools\voice-benchmark\real_local_benchmark.py
```

Outputs are written to Git-ignored `.runtime/` paths:

- `.runtime/voice-benchmark-results.json`
- `.runtime/voice-benchmark-report.md`
- `.runtime/voice-benchmark-fixtures/`
- `.runtime/voice-benchmark/real-local-validation.json`
- `.runtime/voice-benchmark/audio/`

## M4-002B Local Candidates

- STT: `local-vosk-small-cn`, `vosk-model-small-cn-0.22`, Apache 2.0 per Vosk model index, downloaded from `https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip`.
- TTS: `local-piper-zh-huayan`, `zh_CN-huayan-medium`, piper-voices repository metadata is MIT, downloaded from `https://huggingface.co/rhasspy/piper-voices/tree/main/zh/zh_CN/huayan/medium`.
- Runtime package note: `piper-tts` package metadata is GPL-3.0-or-later, so production packaging needs license review.
- Hardware note: current validation used CPU only; no CUDA/DirectML acceleration was used.

## Cloud Environment Variables

Cloud candidates are optional. Missing credentials must not fail local or mock benchmarks.

```text
VOICE_BENCHMARK_ENABLE_CLOUD=0
VOICE_BENCHMARK_OPENAI_API_KEY=
VOICE_BENCHMARK_OPENAI_BASE_URL=https://api.openai.com/v1
VOICE_BENCHMARK_OPENAI_STT_MODEL=whisper-1
VOICE_BENCHMARK_OPENAI_TTS_MODEL=gpt-4o-mini-tts
VOICE_BENCHMARK_OPENAI_TTS_VOICE=alloy
```

The harness also accepts the existing `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_TTS_MODEL`, and `OPENAI_TTS_VOICE` variables. No real key should be committed.

## Test Data

The default run generates synthetic non-child WAV fixtures at runtime. Test audio is not committed to Git.
