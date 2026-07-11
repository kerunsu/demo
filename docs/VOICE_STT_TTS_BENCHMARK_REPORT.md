# M4-002 STT/TTS Benchmark Report

Generated: 2026-06-13T07:30:10.135Z

Status: COMPLETE_FOR_DEVELOPMENT

Host baseline: DEVELOPMENT_SERVER_BASELINE

## Safety

- Test data: synthetic non-child WAV generated at runtime.
- Audio files are written only under Git-ignored `.runtime/`.
- Cloud calls are disabled unless credentials exist and `VOICE_BENCHMARK_ENABLE_CLOUD=1`.
- No real API keys, full sensitive text, or test audio are committed.
- Formal training business logic was not modified.

## STT Results

| Provider | Type | Model | Status | External Network | Init ms | Process ms | RTF | Transcript Hash |
| -- | -- | -- | -- | -- | -- | -- | -- | -- |
| mock-stt-fixture | mock | fixture-transcript-v1 | SUCCESS | false | 20.02 | 29.76 | 0.0165 | 1d54f897 |
| local-stt-adapter | local | not-configured | LOCAL_MODEL_PENDING | false | 0.09 | 0.06 | 0 |  |
| cloud-openai-stt | cloud | whisper-1 | CLOUD_CREDENTIALS_PENDING | false | 0.07 | 0.1 | 0.0001 |  |

## TTS Results

| Provider | Type | Model | Status | External Network | Init ms | Process ms | First byte ms | Audio s |
| -- | -- | -- | -- | -- | -- | -- | -- | -- |
| mock-tts-silence | mock | synthetic-silence-v1 | SUCCESS | false | 9.3 | 1.97 | 1 | 0.8 |
| local-windows-sapi-tts | local | windows-system-speech | FAILED | false | 0.06 | 1642.64 |  |  |
| cloud-openai-tts | cloud | gpt-4o-mini-tts | CLOUD_CREDENTIALS_PENDING | false | 0.05 | 0.14 |  |  |

## End-to-End Combination Results

| Combination | Status | Transcript ms | Reply ms | Audio ready ms | Total ms | Degradation |
| -- | -- | -- | -- | -- | -- | -- |
| local-stt__local-tts | LOCAL_MODEL_PENDING | 0.06 | 0 | 1642.64 | 1642.7 | fallback to available local/mock provider or text interaction |
| local-stt__cloud-tts | CLOUD_CREDENTIALS_PENDING | 0.06 | 0 | 0.14 | 0.2 | fallback to available local/mock provider or text interaction |
| cloud-stt__local-tts | CLOUD_CREDENTIALS_PENDING | 0.1 | 0 | 1642.64 | 1642.74 | fallback to available local/mock provider or text interaction |
| cloud-stt__cloud-tts | CLOUD_CREDENTIALS_PENDING | 0.1 | 0 | 0.14 | 0.24 | fallback to available local/mock provider or text interaction |


## M4-002B Real Local Validation

Status: PROVISIONAL_PROVIDER_DECISION

State labels: BENCHMARK_HARNESS_COMPLETE, PROVISIONAL_PROVIDER_DECISION, CLOUD_STT_CREDENTIALS_PENDING, CLOUD_TTS_CREDENTIALS_PENDING.

### Candidate Selection

| Kind | Provider | Model | License | Model Size MB |
| -- | -- | -- | -- | -- |
| STT | local-vosk-small-cn | vosk-model-small-cn-0.22 | Apache 2.0 per Vosk model index | 65.13 |
| TTS | local-piper-zh-huayan | zh_CN-huayan-medium | MIT metadata on piper-voices repository; piper-tts package is GPL-3.0-or-later | 60.28 |

### Local STT Details

| Fixture | Kind | Audio s | Final ms | RTF | Transcript | Peak RSS MB | GPU |
| -- | -- | -- | -- | -- | -- | -- | -- |
| tts-reward#1 | synthetic_mandarin_speech | 2.171 | 993.82 | 0.4578 | 你 答对 来 我们 继续 吧 | 384.98 | none |
| stt-long#1 | synthetic_mandarin_speech | 4.412 | 1333.11 | 0.3022 | 请 看一看 屏幕 上 的 图片 然后 告诉 我 你 看到 了 什么 | 393.73 | none |
| silence#1 | silence | 1 | 688.49 | 0.6885 |  | 371.91 | none |
| noise#1 | noise | 1.2 | 324.67 | 0.2706 |  | 367.19 | none |
| tts-reward#2 | synthetic_mandarin_speech | 2.171 | 932.59 | 0.4296 | 你 答对 来 我们 继续 吧 | 385.73 | none |
| stt-long#2 | synthetic_mandarin_speech | 4.412 | 1340.49 | 0.3038 | 请 看一看 屏幕 上 的 图片 然后 告诉 我 你 看到 了 什么 | 393.78 | none |
| silence#2 | silence | 1 | 648.53 | 0.6485 |  | 372.64 | none |
| noise#2 | noise | 1.2 | 335.33 | 0.2794 |  | 367.46 | none |

### Local TTS Details

| Text Id | Synthesis ms | First playable ms | Audio s | RTF | Peak RSS MB | Repeated | Review |
| -- | -- | -- | -- | -- | -- | -- | -- |
| tts-reward | 155.94 | 155.94 | 2.171 | 0.0718 | 198.41 | true | HUMAN_REVIEW_PENDING |
| tts-retry | 90.92 | 90.92 | 1.683 | 0.054 | 199.62 | true | HUMAN_REVIEW_PENDING |
| tts-look | 111.75 | 111.75 | 2.067 | 0.0541 | 201.59 | true | HUMAN_REVIEW_PENDING |
| tts-answer | 74.49 | 74.49 | 2.055 | 0.0362 | 201.6 | true | HUMAN_REVIEW_PENDING |
| stt-long | 130.46 | 130.46 | 4.412 | 0.0296 | 245.66 | true | HUMAN_REVIEW_PENDING |

### M4-002B Decision

- STT: LOCAL_PRIMARY_CLOUD_OPTIONAL
- TTS: LOCAL_PRIMARY_CLOUD_OPTIONAL
- Stage: PROVISIONAL_PROVIDER_DECISION
- Server voice stack: Node.js training orchestration backend -> Provider interface -> independent Python voice inference service
- Hardware acceleration: CPUExecutionProvider; GPU used: false
- Human review: HUMAN_REVIEW_PENDING


## Summary

```json
{
  "statuses": {
    "SUCCESS": 2,
    "LOCAL_MODEL_PENDING": 2,
    "CLOUD_CREDENTIALS_PENDING": 5,
    "FAILED": 1
  },
  "testedLocalCandidates": [
    {
      "providerId": "local-stt-adapter",
      "status": "LOCAL_MODEL_PENDING"
    },
    {
      "providerId": "local-windows-sapi-tts",
      "status": "FAILED"
    }
  ],
  "testedCloudCandidates": [],
  "cloudCredentialsPending": [
    "cloud-openai-stt",
    "cloud-openai-tts"
  ],
  "realLocalValidationStatus": "PROVISIONAL_PROVIDER_DECISION",
  "provisionalProviderDecision": {
    "stage": "PROVISIONAL_PROVIDER_DECISION",
    "stt": "LOCAL_PRIMARY_CLOUD_OPTIONAL",
    "tts": "LOCAL_PRIMARY_CLOUD_OPTIONAL",
    "serverVoiceStack": "Node.js training orchestration backend -> Provider interface -> independent Python voice inference service",
    "reevaluationTriggers": [
      "Cloud credentials are provided and cloud benchmark is explicitly enabled.",
      "A stronger Mandarin STT model is benchmarked on the same fixtures.",
      "A production-safe TTS model/license is selected or Piper license review changes deployment constraints.",
      "Final server hardware differs materially from DEVELOPMENT_SERVER_BASELINE."
    ]
  },
  "recommendation": {
    "providerCombination": "LOCAL_PRIMARY_CLOUD_OPTIONAL STT + LOCAL_PRIMARY_CLOUD_OPTIONAL TTS for the next integration spike; cloud remains optional until credentials are benchmarked.",
    "serverVoiceStack": "Node.js training orchestration backend -> Provider interface -> independent Python voice inference service",
    "manualReviewRequired": [
      "TTS intelligibility and naturalness",
      "Cloud STT transcript accuracy when credentials are available",
      "Local STT accuracy after a real model is configured",
      "Noise and classroom echo behavior"
    ]
  }
}
```

## Recommendation

- Provider combination: LOCAL_PRIMARY_CLOUD_OPTIONAL STT + LOCAL_PRIMARY_CLOUD_OPTIONAL TTS for the next integration spike; cloud remains optional until credentials are benchmarked.
- Server voice stack: Node.js training orchestration backend -> Provider interface -> independent Python voice inference service
- Manual review still required: TTS intelligibility and naturalness; Cloud STT transcript accuracy when credentials are available; Local STT accuracy after a real model is configured; Noise and classroom echo behavior.
