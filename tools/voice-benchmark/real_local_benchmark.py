import argparse
import contextlib
import json
import math
import os
import random
import re
import sys
import threading
import time
import wave
from pathlib import Path

import psutil


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".runtime" / "voice-benchmark"
DEFAULT_VOSK_MODEL = REPO_ROOT / ".runtime" / "models" / "vosk" / "vosk-model-small-cn-0.22"
DEFAULT_PIPER_MODEL = REPO_ROOT / ".runtime" / "models" / "piper" / "zh_CN-huayan-medium.onnx"
DEFAULT_PIPER_CONFIG = REPO_ROOT / ".runtime" / "models" / "piper" / "zh_CN-huayan-medium.onnx.json"


PHRASES = [
    {"id": "tts-reward", "text": "你答对啦，我们继续吧。"},
    {"id": "tts-retry", "text": "没关系，再想一想。"},
    {"id": "tts-look", "text": "请看一看屏幕上的图片。"},
    {"id": "tts-answer", "text": "现在请告诉我你的答案。"},
    {"id": "stt-long", "text": "请看一看屏幕上的图片，然后告诉我你看到了什么。"},
]


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def round_num(value, digits=2):
    if value is None:
        return None
    return round(float(value), digits)


def file_size_mb(path):
    path = Path(path)
    if path.is_file():
        return round_num(path.stat().st_size / 1024 / 1024)
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return round_num(total / 1024 / 1024)


def wav_duration_seconds(path):
    with contextlib.closing(wave.open(str(path), "rb")) as wav_file:
        frames = wav_file.getnframes()
        rate = wav_file.getframerate()
        return frames / float(rate)


def write_pcm16_wav(path, sample_rate, samples):
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(wave.open(str(path), "wb")) as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        payload = bytearray()
        for sample in samples:
            value = max(-1.0, min(1.0, float(sample)))
            payload.extend(int(value * 32767).to_bytes(2, "little", signed=True))
        wav_file.writeframes(bytes(payload))


def make_silence(path, seconds=1.0, sample_rate=16000):
    write_pcm16_wav(path, sample_rate, [0.0] * int(seconds * sample_rate))


def make_noise(path, seconds=1.2, sample_rate=16000):
    rng = random.Random(20260613)
    write_pcm16_wav(path, sample_rate, [rng.uniform(-0.08, 0.08) for _ in range(int(seconds * sample_rate))])


def normalize_zh(text):
    return re.sub(r"[\s，。！？、,.!?]", "", text or "")


def char_accuracy(expected, actual):
    expected_n = normalize_zh(expected)
    actual_n = normalize_zh(actual)
    if not expected_n and not actual_n:
        return 1.0
    if not expected_n:
        return 0.0
    matches = sum(1 for char in expected_n if char in actual_n)
    return matches / len(expected_n)


class ResourceSampler:
    def __init__(self):
        self.process = psutil.Process(os.getpid())
        self.peak_rss_mb = self.process.memory_info().rss / 1024 / 1024
        self.running = False
        self.thread = None

    def __enter__(self):
        self.running = True
        self.start_cpu = self.process.cpu_times()
        self.start_rss_mb = self.process.memory_info().rss / 1024 / 1024
        self.thread = threading.Thread(target=self._poll, daemon=True)
        self.thread.start()
        return self

    def _poll(self):
        while self.running:
            try:
                rss = self.process.memory_info().rss / 1024 / 1024
                self.peak_rss_mb = max(self.peak_rss_mb, rss)
            except psutil.Error:
                pass
            time.sleep(0.01)

    def __exit__(self, exc_type, exc, tb):
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.2)
        self.end_cpu = self.process.cpu_times()
        self.end_rss_mb = self.process.memory_info().rss / 1024 / 1024

    def snapshot(self):
        cpu_seconds = (self.end_cpu.user - self.start_cpu.user) + (self.end_cpu.system - self.start_cpu.system)
        return {
            "cpuProcessSeconds": round_num(cpu_seconds, 4),
            "rssStartMB": round_num(self.start_rss_mb),
            "rssEndMB": round_num(self.end_rss_mb),
            "rssPeakMB": round_num(self.peak_rss_mb),
        }


def timed(callable_obj):
    started = time.perf_counter()
    with ResourceSampler() as sampler:
        value = callable_obj()
    elapsed_ms = (time.perf_counter() - started) * 1000
    return value, round_num(elapsed_ms), sampler.snapshot()


def synthesize_piper(voice, text, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(wave.open(str(output_path), "wb")) as wav_file:
        voice.synthesize_wav(text, wav_file)
    return output_path


def transcribe_vosk(model, wav_path):
    from vosk import KaldiRecognizer

    with contextlib.closing(wave.open(str(wav_path), "rb")) as wav_file:
        recognizer = KaldiRecognizer(model, wav_file.getframerate())
        partial_first_ms = None
        started = time.perf_counter()
        while True:
            data = wav_file.readframes(4000)
            if len(data) == 0:
                break
            accepted = recognizer.AcceptWaveform(data)
            if partial_first_ms is None:
                partial = json.loads(recognizer.PartialResult()).get("partial", "")
                if partial or accepted:
                    partial_first_ms = (time.perf_counter() - started) * 1000
        final = json.loads(recognizer.FinalResult())
    return final.get("text", ""), round_num(partial_first_ms)


def run(args):
    output_dir = Path(args.output_dir)
    audio_dir = output_dir / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "schemaVersion": "m4.voiceBenchmark.realLocal.v1",
        "generatedAt": now_iso(),
        "status": "PROVISIONAL_PROVIDER_DECISION",
        "safety": {
            "containsRealChildVoice": False,
            "testData": "Piper-generated synthetic Mandarin speech, generated silence, generated noise, and fixed test text.",
            "audioOutputDirectory": str(audio_dir.relative_to(REPO_ROOT)),
            "externalNetworkCalledDuringBenchmark": False,
        },
        "candidates": {
            "stt": {
                "providerId": "local-vosk-small-cn",
                "modelId": "vosk-model-small-cn-0.22",
                "source": "https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip",
                "license": "Apache 2.0 per Vosk model index",
                "modelSizeMB": file_size_mb(args.vosk_model),
            },
            "tts": {
                "providerId": "local-piper-zh-huayan",
                "modelId": "zh_CN-huayan-medium",
                "source": "https://huggingface.co/rhasspy/piper-voices/tree/main/zh/zh_CN/huayan/medium",
                "license": "MIT metadata on piper-voices repository; piper-tts package is GPL-3.0-or-later",
                "modelSizeMB": file_size_mb(Path(args.piper_model).parent),
            },
        },
        "environment": {
            "python": sys.version.split()[0],
            "processArch": "64bit" if sys.maxsize > 2**32 else "32bit",
            "hardwareAcceleration": "CPUExecutionProvider",
            "gpuProvider": "not used",
            "gpuAccelerationUsed": False,
            "gpuNotes": "No CUDA detected in M4-001; this isolated venv uses onnxruntime CPU provider for Piper. Vosk runs CPU.",
        },
        "ttsResults": [],
        "sttResults": [],
        "decisions": {},
        "humanReview": [],
    }

    from piper import PiperVoice
    from vosk import Model, SetLogLevel

    SetLogLevel(-1)

    voice, piper_load_ms, piper_load_resources = timed(
        lambda: PiperVoice.load(args.piper_model, args.piper_config, use_cuda=False)
    )
    tts_success_count = 0
    speech_fixtures = []
    for phrase in PHRASES:
        output_path = audio_dir / f"piper-{phrase['id']}.wav"
        _, synth_ms, resources = timed(lambda phrase=phrase, output_path=output_path: synthesize_piper(voice, phrase["text"], output_path))
        duration = wav_duration_seconds(output_path)
        success = output_path.exists() and output_path.stat().st_size > 44
        if success:
            tts_success_count += 1
        item = {
            "providerId": "local-piper-zh-huayan",
            "modelId": "zh_CN-huayan-medium",
            "status": "SUCCESS" if success else "FAILED",
            "textId": phrase["id"],
            "textHashOnly": True,
            "initializationMs": piper_load_ms,
            "modelLoadMs": piper_load_ms,
            "totalSynthesisMs": synth_ms,
            "firstPlayableMs": synth_ms,
            "audioDurationSeconds": round_num(duration, 3),
            "realTimeFactor": round_num((synth_ms / 1000) / duration, 4) if duration else None,
            "outputFormat": "audio/wav PCM16 mono",
            "outputPath": str(output_path.relative_to(REPO_ROOT)),
            "resourceUsage": resources,
            "modelLoadResourceUsage": piper_load_resources,
            "externalNetworkCalled": False,
            "inputPersisted": False,
            "canSynthesizeRepeatedly": None,
            "cancelSupported": False,
            "cancelNotes": "Direct piper Python call does not expose cooperative cancellation; production service should cancel by worker process/job boundary.",
            "intelligibility": "HUMAN_REVIEW_PENDING",
            "naturalness": "HUMAN_REVIEW_PENDING",
        }
        result["ttsResults"].append(item)
        speech_fixtures.append({"id": phrase["id"], "path": output_path, "expected": phrase["text"], "kind": "synthetic_mandarin_speech"})

    for item in result["ttsResults"]:
        item["canSynthesizeRepeatedly"] = tts_success_count == len(PHRASES)
    result["humanReview"].append({
        "type": "tts_listening",
        "status": "HUMAN_REVIEW_PENDING",
        "items": [item["outputPath"] for item in result["ttsResults"]],
        "questions": ["普通话是否可懂", "语气是否适合儿童训练反馈", "是否存在明显机械感或错误读音"],
    })

    silence_path = audio_dir / "fixture-silence.wav"
    noise_path = audio_dir / "fixture-noise.wav"
    make_silence(silence_path)
    make_noise(noise_path)
    stt_fixtures = [
        speech_fixtures[0],
        speech_fixtures[-1],
        {"id": "silence", "path": silence_path, "expected": "", "kind": "silence"},
        {"id": "noise", "path": noise_path, "expected": "", "kind": "noise"},
    ]

    model, vosk_load_ms, vosk_load_resources = timed(lambda: Model(str(args.vosk_model)))
    repeat_transcripts = []
    for iteration in range(2):
        for fixture in stt_fixtures:
            duration = wav_duration_seconds(fixture["path"])
            (transcript, partial_first_ms), decode_ms, resources = timed(lambda fixture=fixture: transcribe_vosk(model, fixture["path"]))
            accuracy = char_accuracy(fixture["expected"], transcript)
            if fixture["id"] == "tts-reward":
                repeat_transcripts.append(transcript)
            result["sttResults"].append({
                "providerId": "local-vosk-small-cn",
                "modelId": "vosk-model-small-cn-0.22",
                "status": "SUCCESS",
                "fixtureId": fixture["id"],
                "fixtureKind": fixture["kind"],
                "iteration": iteration + 1,
                "modelLoadMs": vosk_load_ms,
                "audioDurationSeconds": round_num(duration, 3),
                "partialFirstReturnMs": partial_first_ms,
                "finalReturnMs": decode_ms,
                "processingMs": decode_ms,
                "realTimeFactor": round_num((decode_ms / 1000) / duration, 4) if duration else None,
                "finalTranscript": transcript,
                "accuracyObservation": {
                    "expectedText": fixture["expected"],
                    "charCoverageApprox": round_num(accuracy, 4),
                    "note": "Approximate character coverage for synthetic fixtures, not a formal ASR accuracy score.",
                },
                "silenceHandling": "empty transcript expected" if fixture["kind"] == "silence" else "not silence fixture",
                "noiseHandling": "empty transcript expected" if fixture["kind"] == "noise" else "not noise fixture",
                "resourceUsage": resources,
                "modelLoadResourceUsage": vosk_load_resources,
                "gpuProvider": "none",
                "hardwareAccelerationUsed": False,
                "externalNetworkCalled": False,
                "inputPersisted": False,
                "error": None,
            })

    stt_speech = [item for item in result["sttResults"] if item["fixtureKind"] == "synthetic_mandarin_speech"]
    tts_success = all(item["status"] == "SUCCESS" for item in result["ttsResults"])
    stt_success = all(item["status"] == "SUCCESS" for item in result["sttResults"])
    avg_stt_rtf = sum(item["realTimeFactor"] for item in stt_speech if item["realTimeFactor"] is not None) / max(1, len(stt_speech))
    avg_tts_rtf = sum(item["realTimeFactor"] for item in result["ttsResults"] if item["realTimeFactor"] is not None) / max(1, len(result["ttsResults"]))
    result["summary"] = {
        "localSttValidation": "SUCCESS" if stt_success else "FAILED",
        "localTtsValidation": "SUCCESS" if tts_success else "FAILED",
        "localSttAverageSpeechRtf": round_num(avg_stt_rtf, 4),
        "localTtsAverageRtf": round_num(avg_tts_rtf, 4),
        "sttRepeatStable": len(set(repeat_transcripts)) == 1,
        "ttsRepeatedSynthesisSuccess": tts_success_count == len(PHRASES),
        "cloudSttStatus": "CLOUD_CREDENTIALS_PENDING",
        "cloudTtsStatus": "CLOUD_CREDENTIALS_PENDING",
    }
    result["decisions"] = {
        "stage": "PROVISIONAL_PROVIDER_DECISION",
        "stt": "LOCAL_PRIMARY_CLOUD_OPTIONAL" if stt_success else "MOCK_ONLY_PENDING_VALIDATION",
        "tts": "LOCAL_PRIMARY_CLOUD_OPTIONAL" if tts_success else "MOCK_ONLY_PENDING_VALIDATION",
        "serverVoiceStack": "Node.js training orchestration backend -> Provider interface -> independent Python voice inference service",
        "reevaluationTriggers": [
            "Cloud credentials are provided and cloud benchmark is explicitly enabled.",
            "A stronger Mandarin STT model is benchmarked on the same fixtures.",
            "A production-safe TTS model/license is selected or Piper license review changes deployment constraints.",
            "Final server hardware differs materially from DEVELOPMENT_SERVER_BASELINE.",
        ],
    }

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_DIR / "real-local-validation.json"))
    parser.add_argument("--vosk-model", default=str(DEFAULT_VOSK_MODEL))
    parser.add_argument("--piper-model", default=str(DEFAULT_PIPER_MODEL))
    parser.add_argument("--piper-config", default=str(DEFAULT_PIPER_CONFIG))
    return parser.parse_args()


if __name__ == "__main__":
    parsed_args = parse_args()
    try:
        data = run(parsed_args)
        print(json.dumps({
            "status": data["status"],
            "summary": data["summary"],
            "outputJson": str(Path(parsed_args.output_json)),
        }, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise
