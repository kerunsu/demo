import assert from "node:assert/strict";
import test from "node:test";

import {
  CLOUD_STT_PROVIDER_METADATA,
  CLOUD_TTS_PROVIDER_METADATA,
  DEFAULT_STT_PROVIDER_METADATA,
  DEFAULT_TTS_PROVIDER_METADATA,
  M4_SPEECH_PROVIDER_REGISTRY,
  MockChildSafetyProvider,
  MockLlmProvider,
  MockSttProvider,
  MockTtsProvider,
  createDefaultMockProviderSet
} from "../dist/providers.js";

test("default mock providers produce deterministic local outputs", async () => {
  const providers = createDefaultMockProviderSet();

  const stt = await providers.stt.transcribe({
    turnId: "turn-1",
    audioSegmentId: "audio-1",
    audioRef: "local-mock-audio",
    languageHint: "zh-CN"
  });
  assert.equal(stt.ok, true);
  assert.equal(stt.data.transcriptRedacted, "我选择左边的图片");
  assert.equal(stt.data.isFinal, true);
  assert.equal(stt.data.normalized.lowConfidence, false);
  assert.equal(stt.metadata.mode, "mock");

  const llm = await providers.llm.generateReply({
    turnId: "turn-1",
    sessionId: "session-1",
    questionId: "question-1",
    childTextRedacted: stt.data.transcriptRedacted,
    historyRedacted: [],
    policyVersion: "mock-policy-v1"
  });
  assert.equal(llm.ok, true);
  assert.equal(llm.data.replyDraft, "做得好，我们继续看第 question-1 题。");

  const safety = await providers.safety.review({
    requestId: "review-1",
    target: "output",
    textRedacted: llm.data.replyDraft,
    policyVersion: "mock-policy-v1"
  });
  assert.equal(safety.ok, true);
  assert.equal(safety.data.action, "allow");

  const tts = await providers.tts.synthesize({
    turnId: "turn-1",
    text: safety.data.approvedText,
    safety: safety.data
  });
  assert.equal(tts.ok, true);
  assert.equal(tts.data.audioRef, "mock-audio:turn-1");
  assert.equal(tts.data.mimeType, "audio/wav");
  assert.equal(tts.data.sampleRateHz, 16000);

  const attention = await providers.attention.observe({
    observationId: "attention-1",
    sessionId: "session-1",
    questionId: "question-1",
    correlationId: "corr-1",
    observedAt: "2026-06-07T01:11:49.000+08:00"
  });
  assert.equal(attention.ok, true);
  assert.equal(attention.data.observationType, "attention");
  assert.equal(attention.data.features.kind, "screen_orientation");
  assert.equal(attention.data.dataQuality.status, "complete");

  const language = await providers.language.observe({
    observationId: "language-1",
    sessionId: "session-1",
    turnId: "turn-1",
    transcriptRedacted: stt.data.transcriptRedacted,
    confidence: stt.data.confidence,
    observedAt: "2026-06-07T01:11:49.000+08:00"
  });
  assert.equal(language.ok, true);
  assert.equal(language.data.observationType, "language");
  assert.equal(language.data.features.kind, "transcript_length");
  assert.equal(language.data.dataQuality.status, "complete");
});

test("M4 speech provider registry fixes default local STT and TTS without enabling cloud", () => {
  assert.equal(M4_SPEECH_PROVIDER_REGISTRY.defaultSttProviderId, "local-vosk-small-cn");
  assert.equal(M4_SPEECH_PROVIDER_REGISTRY.defaultTtsProviderId, "local-piper-zh-huayan");

  assert.equal(DEFAULT_STT_PROVIDER_METADATA.providerType, "local");
  assert.equal(DEFAULT_STT_PROVIDER_METADATA.modelId, "vosk-model-small-cn-0.22");
  assert.equal(DEFAULT_STT_PROVIDER_METADATA.modelPath, ".runtime/models/vosk/vosk-model-small-cn-0.22");
  assert.equal(DEFAULT_STT_PROVIDER_METADATA.dataSafety.externalNetworkCalled, false);
  assert.equal(DEFAULT_STT_PROVIDER_METADATA.dataSafety.rawAudioPersisted, false);

  assert.equal(DEFAULT_TTS_PROVIDER_METADATA.providerType, "local");
  assert.equal(DEFAULT_TTS_PROVIDER_METADATA.modelId, "zh_CN-huayan-medium");
  assert.equal(DEFAULT_TTS_PROVIDER_METADATA.modelPath, ".runtime/models/piper/zh_CN-huayan-medium.onnx");
  assert.equal(DEFAULT_TTS_PROVIDER_METADATA.configPath, ".runtime/models/piper/zh_CN-huayan-medium.onnx.json");
  assert.equal(DEFAULT_TTS_PROVIDER_METADATA.humanReview, "HUMAN_REVIEW_PENDING");
  assert.equal(DEFAULT_TTS_PROVIDER_METADATA.licenseReview, "REQUIRED_BEFORE_PRODUCTION");

  assert.equal(CLOUD_STT_PROVIDER_METADATA.providerId, "cloud-openai-stt");
  assert.equal(CLOUD_STT_PROVIDER_METADATA.defaultEnabled, false);
  assert.equal(CLOUD_TTS_PROVIDER_METADATA.providerId, "cloud-openai-tts");
  assert.equal(CLOUD_TTS_PROVIDER_METADATA.defaultEnabled, false);
  assert.equal(CLOUD_TTS_PROVIDER_METADATA.dataSafety.credentialsSource, "environment");
});

test("STT and TTS providers expose health and cancellation lifecycle hooks", async () => {
  const stt = new MockSttProvider();
  const sttHealth = await stt.healthCheck();
  assert.equal(sttHealth.providerId, "mock-stt");
  assert.equal(sttHealth.status, "READY");
  assert.equal(sttHealth.externalNetworkCalled, false);

  const sttCancel = await stt.cancel("stt-request-1");
  assert.equal(sttCancel.ok, true);
  assert.equal(sttCancel.data.cancelled, true);

  const tts = new MockTtsProvider();
  const ttsHealth = await tts.initialize();
  assert.equal(ttsHealth.providerId, "mock-tts");
  assert.equal(ttsHealth.inputPersisted, false);

  const ttsCancel = await tts.cancel("tts-request-1");
  assert.equal(ttsCancel.ok, true);
  assert.equal(ttsCancel.data.requestId, "tts-request-1");
});

test("mock providers expose timeout, failure, and safety fallback boundaries", async () => {
  const sttTimeout = await new MockSttProvider("timeout").transcribe({
    turnId: "turn-timeout",
    audioSegmentId: "audio-timeout",
    audioRef: "local-mock-audio"
  });
  assert.equal(sttTimeout.ok, false);
  assert.equal(sttTimeout.error.code, "TIMEOUT");

  const llmFailure = await new MockLlmProvider("failure").generateReply({
    turnId: "turn-failure",
    sessionId: "session-1",
    childTextRedacted: "hello",
    historyRedacted: [],
    policyVersion: "mock-policy-v1"
  });
  assert.equal(llmFailure.ok, false);
  assert.equal(llmFailure.fallbackText, "我们先继续当前题目。");

  const safetyFallback = await new MockChildSafetyProvider("unsafe").review({
    requestId: "review-unsafe",
    target: "output",
    textRedacted: "unsafe candidate",
    policyVersion: "mock-policy-v1"
  });
  assert.equal(safetyFallback.ok, true);
  assert.equal(safetyFallback.data.action, "fallback");
  assert.equal(safetyFallback.data.fallbackText, "这个内容我不能继续聊。我们回到当前题目吧。");
});

test("mock TTS refuses text that has not passed safety review", async () => {
  const tts = await new MockTtsProvider().synthesize({
    turnId: "turn-unreviewed",
    text: "未经审核的文本",
    safety: {
      requestId: "review-blocked",
      target: "output",
      action: "block",
      piiTypes: [],
      reasonCodes: ["blocked"],
      policyVersion: "mock-policy-v1"
    }
  });

  assert.equal(tts.ok, false);
  assert.equal(tts.error.code, "UNREVIEWED_TEXT");
});
