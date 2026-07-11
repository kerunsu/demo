import { once } from "node:events";
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import "./testEnv.mjs";

let server;
let baseUrl;

async function request(path, options = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: {
      "content-type": "application/json",
      ...(options.headers ?? {})
    }
  });
  const body = await response.json();
  return { response, body };
}

before(async () => {
  process.env.AI_CHAT_PROVIDER = "rule";
  process.env.AI_TTS_PROVIDER = "none";
  process.env.OPENAI_API_KEY = "";
  process.env.REPORT_NARRATIVE_PROVIDER = "mock";
  process.env.DEEPSEEK_API_KEY = "";

  const { createApp } = await import("../dist/app.js");
  const app = createApp({ enableRequestLogging: false });
  server = app.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.ok(address && typeof address === "object");
  baseUrl = `http://127.0.0.1:${address.port}/api`;
});

after(async () => {
  if (!server?.listening) return;
  server.close();
  await once(server, "close");
});

test("backend API baseline covers training, chat, report, and error paths", async () => {
  const health = await request("/health");
  assert.equal(health.response.status, 200);
  assert.equal(health.body.success, true);
  assert.equal(health.body.data.voice.chatProvider, "rule");
  assert.equal(health.body.data.voice.ttsProvider, "none");
  assert.equal(health.body.data.voice.sttProvider.providerId, "mock-stt");
  assert.equal(health.body.data.voice.sttProvider.externalNetworkCalled, false);
  assert.equal(health.body.data.voice.speechTtsProvider.providerId, "mock-tts");
  assert.equal(health.body.data.voice.speechTtsProvider.externalNetworkCalled, false);
  assert.deepEqual(health.body.data.voice.configIssues, []);

  const invalidStart = await request("/session/start", {
    method: "POST",
    body: JSON.stringify({ childName: "Test Child" })
  });
  assert.equal(invalidStart.response.status, 400);
  assert.equal(invalidStart.body.success, false);
  assert.equal(invalidStart.body.error.code, "VALIDATION_ERROR");

  const started = await request("/session/start", {
    method: "POST",
    body: JSON.stringify({ childName: "Test Child", courseType: "matching" })
  });
  assert.equal(started.response.status, 200);
  assert.equal(started.body.success, true);
  assert.match(started.body.data.sessionId, /^sess_/);
  assert.equal(started.body.data.state, "TRAINING_ACTIVE");
  assert.equal(started.body.data.courseType, "matching");
  const { sessionId } = started.body.data;

  const latestSession = await request("/session/active/latest");
  assert.equal(latestSession.response.status, 200);
  assert.equal(latestSession.body.success, true);
  assert.equal(latestSession.body.data.sessionId, sessionId);
  assert.equal(latestSession.body.data.state, "TRAINING_ACTIVE");

  const session = await request(`/session/${sessionId}`);
  assert.equal(session.response.status, 200);
  assert.equal(session.body.data.sessionId, sessionId);
  assert.equal(session.body.data.state, "TRAINING_ACTIVE");

  const missingSession = await request("/session/not-a-session");
  assert.equal(missingSession.response.status, 404);
  assert.equal(missingSession.body.error.code, "SESSION_NOT_FOUND");

  const current = await request(`/course/${sessionId}/current`);
  assert.equal(current.response.status, 200);
  assert.equal(current.body.data.courseType, "matching");
  assert.ok(current.body.data.payload.options.length >= 2);

  const monitorSnapshot = await request(`/monitor/session/${sessionId}/snapshot`);
  assert.equal(monitorSnapshot.response.status, 200);
  assert.equal(monitorSnapshot.body.success, true);
  assert.equal(monitorSnapshot.body.data.session.sessionId, sessionId);
  assert.equal(monitorSnapshot.body.data.course.totalQuestions, current.body.data.total);
  assert.equal(monitorSnapshot.body.data.media.rawMediaPersistence, "disabled");
  assert.equal(monitorSnapshot.body.data.media.requiresConsent, true);
  assert.equal(monitorSnapshot.body.data.health.backend, "ok");
  assert.ok(
    monitorSnapshot.body.data.media.manualAcceptanceRequired.some((item) => item.includes("MANUAL_ACCEPTANCE_REQUIRED")),
    "real camera/raw media acceptance should stay manual"
  );

  const badAnswerShape = await request(`/course/${sessionId}/answer`, {
    method: "POST",
    body: JSON.stringify({ questionId: current.body.data.questionId, answer: {}, responseTimeMs: 100 })
  });
  assert.equal(badAnswerShape.response.status, 400);
  assert.equal(badAnswerShape.body.error.code, "VALIDATION_ERROR");

  const chat = await request(`/chat/${sessionId}/message`, {
    method: "POST",
    body: JSON.stringify({ text: "I need a hint" })
  });
  assert.equal(chat.response.status, 200);
  assert.equal(chat.body.success, true);
  assert.equal(chat.body.data.safetyStatus, "PASS");
  assert.equal(chat.body.data.audioBase64, undefined);

  const chatAudit = await request(`/chat/${sessionId}/audit`);
  assert.equal(chatAudit.response.status, 200);
  assert.equal(chatAudit.body.data.length, 1);
  assert.equal(chatAudit.body.data[0].inputLength, "I need a hint".length);
  assert.equal(JSON.stringify(chatAudit.body.data).includes("I need a hint"), false);

  const missingChat = await request("/chat/not-a-session/message", {
    method: "POST",
    body: JSON.stringify({ text: "hello" })
  });
  assert.equal(missingChat.response.status, 400);
  assert.equal(missingChat.body.error.code, "CHAT_FAILED");

  const earlyReport = await request(`/report/${sessionId}/generate`, { method: "POST" });
  assert.equal(earlyReport.response.status, 400);
  assert.equal(earlyReport.body.error.code, "REPORT_GENERATE_FAILED");

  let courseCompleted = false;
  for (let guard = 0; guard < 20 && !courseCompleted; guard += 1) {
    const question = await request(`/course/${sessionId}/current`);
    assert.equal(question.response.status, 200);
    const questionId = question.body.data.questionId;

    const wrong = await request(`/course/${sessionId}/answer`, {
      method: "POST",
      body: JSON.stringify({
        questionId,
        answer: { selectedOptionId: "__wrong_option__" },
        responseTimeMs: 1200
      })
    });
    assert.equal(wrong.response.status, 200);
    assert.equal(wrong.body.data.correct, false);
    assert.equal(wrong.body.data.nextAction, "RETRY_SAME_QUESTION");
    assert.match(wrong.body.data.correctOptionId, /^m_q\d+_o\d+$/);

    if (guard === 0) {
      const secondWrong = await request(`/course/${sessionId}/answer`, {
        method: "POST",
        body: JSON.stringify({
          questionId,
          answer: { selectedOptionId: "__wrong_option__" },
          responseTimeMs: 1300
        })
      });
      assert.equal(secondWrong.response.status, 200);
      assert.equal(secondWrong.body.data.correct, false);
      assert.equal(typeof secondWrong.body.data.hint, "string");
    }

    const correct = await request(`/course/${sessionId}/answer`, {
      method: "POST",
      body: JSON.stringify({
        questionId,
        answer: { selectedOptionId: wrong.body.data.correctOptionId },
        responseTimeMs: 1500
      })
    });
    assert.equal(correct.response.status, 200);
    assert.equal(correct.body.data.correct, true);
    assert.equal(correct.body.data.nextAction, "NEXT_QUESTION");
    courseCompleted = correct.body.data.courseCompleted;
  }

  assert.equal(courseCompleted, true);

  const noCurrentQuestion = await request(`/course/${sessionId}/current`);
  assert.equal(noCurrentQuestion.response.status, 404);
  assert.equal(noCurrentQuestion.body.error.code, "QUESTION_NOT_FOUND");

  const generated = await request(`/report/${sessionId}/generate`, { method: "POST" });
  assert.equal(generated.response.status, 200);
  assert.equal(generated.body.data.sessionId, sessionId);
  assert.equal(generated.body.data.status, "READY");

  const report = await request(`/report/${sessionId}`);
  assert.equal(report.response.status, 200);
  assert.equal(report.body.data.sessionId, sessionId);
  assert.equal(report.body.data.summary.totalQuestions, report.body.data.questionResults.length);
  assert.ok(report.body.data.errorStats.totalWrongAttempts >= report.body.data.summary.totalQuestions);
  assert.equal(report.body.data.assessment.metricVersion, "deterministic-assessment-v1");
  assert.equal(report.body.data.assessment.scoringStatus, "OWNER_REQUIRED_BEFORE_SCORING");
  assert.equal(report.body.data.expandedReport.schemaVersion, "m6-expanded-report-v1");
  assert.equal(report.body.data.expandedReport.metricVersion, "m6-expanded-report-metrics-v1");
  assert.equal(report.body.data.expandedReport.answerMetrics.totalQuestions, report.body.data.summary.totalQuestions);
  assert.equal(report.body.data.expandedReport.exportBoundary.containsRawAudio, false);
  assert.equal(report.body.data.expandedReport.exportBoundary.containsRawVideo, false);
  assert.equal(report.body.data.expandedReport.exportBoundary.containsRawChatText, false);
  assert.equal(report.body.data.expandedReport.safeExplanations.every((item) => item.reviewStatus === "PASS"), true);
  assert.equal(JSON.stringify(report.body.data.expandedReport).includes("percentile"), false);
  assert.equal(JSON.stringify(report.body.data.expandedReport).includes("diagnosis"), false);
  assert.equal(report.body.data.professionalReportV2.schemaVersion, "professional-report-v2");
  assert.equal(report.body.data.professionalReportV2.scoreBoundary, "education_training_reference_only");
  assert.equal(report.body.data.professionalReportV2.emotionSummary.status, "AVAILABLE");
  assert.ok(typeof report.body.data.professionalReportV2.emotionSummary.positiveRatio === "number");
  assert.equal(report.body.data.professionalReportV2.narrative.generator, "mock_llm");
  assert.ok(report.body.data.professionalReportV2.attentionCurve.length <= report.body.data.summary.totalQuestions);
  assert.equal(report.body.data.professionalReportV2.narrative.safetyReviewStatus, "PASS");
  assert.equal(report.body.data.professionalReportV2.dataQuality.degraded, true);
  assert.equal(JSON.stringify(report.body.data.professionalReportV2).includes("教育训练参考"), true);
  assert.equal(JSON.stringify(report.body.data.professionalReportV2).includes("percentile"), false);
  assert.equal(JSON.stringify(report.body.data.professionalReportV2).includes("rawAudioPersisted"), false);

  const assessment = await request(`/assessment/${sessionId}`);
  assert.equal(assessment.response.status, 200);
  assert.equal(assessment.body.data.sessionId, sessionId);
  assert.equal(assessment.body.data.sessionMetrics.totalQuestions, report.body.data.summary.totalQuestions);

  const missingReport = await request("/report/not-a-session");
  assert.equal(missingReport.response.status, 404);
  assert.equal(missingReport.body.error.code, "REPORT_NOT_FOUND");

  const missingAssessment = await request("/assessment/not-a-session");
  assert.equal(missingAssessment.response.status, 404);
  assert.equal(missingAssessment.body.error.code, "ASSESSMENT_NOT_FOUND");
});

test("media ingress accepts binary chunks without persisting raw audio", async () => {
  const sessionId = "sess_media_test";
  const streamId = "stream_media_test";
  const turnId = "turn_media_test";
  const correlationId = "corr_media_test";
  const format = {
    codec: "webm_opus",
    mimeType: "audio/webm;codecs=opus",
    sampleRateHz: 48000,
    channels: 1,
    chunkDurationMs: 250
  };

  const started = await request(`/media/${sessionId}/streams/${streamId}/start`, {
    method: "POST",
    body: JSON.stringify({
      sessionId,
      streamId,
      turnId,
      correlationId,
      startedAt: "2026-06-13T08:00:00.000Z",
      format,
      maxTurnDurationMs: 10000
    })
  });
  assert.equal(started.response.status, 200);
  assert.equal(started.body.data.status, "started");
  assert.equal(started.body.data.rawAudioPersisted, false);

  const chunkResponse = await fetch(`${baseUrl}/media/${sessionId}/streams/${streamId}/chunks/1`, {
    method: "POST",
    headers: {
      "content-type": "application/octet-stream",
      "x-turn-id": turnId,
      "x-correlation-id": correlationId,
      "x-captured-at": "2026-06-13T08:00:00.250Z",
      "x-duration-ms": "250",
      "x-audio-codec": "webm_opus",
      "x-audio-mime-type": "audio/webm;codecs=opus",
      "x-sample-rate-hz": "48000",
      "x-audio-channels": "1",
      "x-chunk-duration-ms": "250"
    },
    body: Buffer.from([1, 2, 3, 4])
  });
  const chunkBody = await chunkResponse.json();
  assert.equal(chunkResponse.status, 200);
  assert.equal(chunkBody.data.accepted, true);
  assert.deepEqual(chunkBody.data.missingSequences, [0]);
  assert.equal(chunkBody.data.receivedBytes, 4);
  assert.equal(chunkBody.data.rawAudioPersisted, false);

  const duplicateChunkResponse = await fetch(`${baseUrl}/media/${sessionId}/streams/${streamId}/chunks/1`, {
    method: "POST",
    headers: {
      "content-type": "application/octet-stream",
      "x-turn-id": turnId,
      "x-correlation-id": correlationId,
      "x-captured-at": "2026-06-13T08:00:00.500Z",
      "x-duration-ms": "250",
      "x-audio-codec": "webm_opus",
      "x-audio-mime-type": "audio/webm;codecs=opus",
      "x-sample-rate-hz": "48000",
      "x-audio-channels": "1",
      "x-chunk-duration-ms": "250"
    },
    body: Buffer.from([5, 6])
  });
  const duplicateChunkBody = await duplicateChunkResponse.json();
  assert.equal(duplicateChunkResponse.status, 200);
  assert.equal(duplicateChunkBody.data.accepted, false);
  assert.equal(duplicateChunkBody.data.receivedBytes, 4);

  const finished = await request(`/media/${sessionId}/streams/${streamId}/finish`, {
    method: "POST",
    body: JSON.stringify({
      sessionId,
      streamId,
      turnId,
      correlationId,
      reason: "manual_stop",
      endedAt: "2026-06-13T08:00:01.000Z"
    })
  });
  assert.equal(finished.response.status, 200);
  assert.equal(finished.body.data.status, "finished");
  assert.equal(finished.body.data.chunkCount, 1);
  assert.equal(finished.body.data.rawAudioPersisted, false);

  const transcript = await request(`/media/${sessionId}/streams/${streamId}/transcribe`, {
    method: "POST",
    body: JSON.stringify({
      turnId,
      correlationId,
      languageHint: "zh-CN"
    })
  });
  assert.equal(transcript.response.status, 200);
  assert.equal(transcript.body.data.ok, true);
  assert.equal(transcript.body.data.metadata.providerName, "mock-stt");
  assert.equal(transcript.body.data.metadata.dataSafety.externalNetworkCalled, false);
  assert.equal(transcript.body.data.data.turnId, turnId);
  assert.equal(transcript.body.data.data.isFinal, true);
  assert.equal(transcript.body.data.data.confidence > 0.9, true);

  const metrics = await request(`/voice-metrics/${sessionId}`);
  assert.equal(metrics.response.status, 200);
  assert.equal(metrics.body.data.some((metric) => metric.stage === "audio_capture_start"), true);
  assert.equal(metrics.body.data.some((metric) => metric.stage === "first_audio_chunk"), true);
  assert.equal(metrics.body.data.some((metric) => metric.stage === "stt_complete"), true);
  assert.equal(metrics.body.data.some((metric) => metric.stage === "transcript_available"), true);
  assert.equal(metrics.body.data.every((metric) => metric.rawAudioPersisted === false), true);
  assert.equal(metrics.body.data.every((metric) => metric.sensitiveTextLogged === false), true);
});

test("ordering course presents child-facing Chinese rule text", async () => {
  const started = await request("/session/start", {
    method: "POST",
    body: JSON.stringify({ childName: "Test Child", courseType: "ordering" })
  });
  assert.equal(started.response.status, 200);
  assert.equal(started.body.success, true);

  const current = await request(`/course/${started.body.data.sessionId}/current`);
  assert.equal(current.response.status, 200);
  assert.equal(current.body.data.courseType, "ordering");
  assert.match(current.body.data.prompt, /请根据规则选择正确的图片/);
  assert.match(current.body.data.payload.target, /^选更/);
  assert.equal(current.body.data.payload.target.length <= 5, true);
  assert.equal(/Choose|bigger|smaller|taller|shorter|longer|fewer|more/i.test(current.body.data.payload.target), false);
  assert.equal(current.body.data.payload.options.every((option) => /^选项 \d+$/.test(option.label)), true);
});

test("behavior camera frame API accepts descriptors without raw frame persistence", async () => {
  const sessionId = "sess_behavior_frame";
  const streamId = "camera_stream_behavior";
  const frameId = "camera_stream_behavior:frame-0";
  const descriptor = {
    schemaVersion: "m5-frame-v1",
    sessionId,
    streamId,
    frameId,
    sequence: 0,
    capturedAt: "2026-06-14T01:10:00.000Z",
    correlationId: "corr_behavior_frame",
    questionId: "question-1",
    width: 160,
    height: 120,
    downsampled: true,
    frameHash: "hash-behavior-frame",
    byteLength: 2048,
    mimeType: "mock/frame-descriptor",
    rawFramePersisted: false
  };

  const accepted = await request(`/behavior/${sessionId}/camera/frames/${encodeURIComponent(frameId)}`, {
    method: "POST",
    body: JSON.stringify(descriptor)
  });
  assert.equal(accepted.response.status, 200);
  assert.equal(accepted.body.data.accepted, true);
  assert.equal(accepted.body.data.rawFramePersisted, false);

  const summary = await request(`/behavior/${sessionId}/camera/streams/${streamId}`);
  assert.equal(summary.response.status, 200);
  assert.equal(summary.body.data.receivedFrameCount, 1);
  assert.equal(summary.body.data.rawFramePersisted, false);

  const rejected = await request(`/behavior/${sessionId}/camera/frames/${encodeURIComponent(frameId)}-bad`, {
    method: "POST",
    body: JSON.stringify({ ...descriptor, frameId: `${frameId}-bad`, rawFramePersisted: true })
  });
  assert.equal(rejected.response.status, 400);
  assert.equal(rejected.body.error.code, "VALIDATION_ERROR");
});

test("behavior camera frame API preserves attention v2 visual features", async () => {
  const sessionId = "sess_behavior_frame_v2";
  const streamId = "camera_stream_behavior_v2";
  const frameId = "camera_stream_behavior_v2:frame-0";
  const descriptor = {
    schemaVersion: "m5-frame-v1",
    sessionId,
    streamId,
    frameId,
    sequence: 0,
    capturedAt: "2026-06-15T04:32:17.664Z",
    correlationId: "corr_behavior_frame_v2",
    questionId: "matching_q_1",
    width: 160,
    height: 120,
    downsampled: true,
    frameHash: "hash-behavior-frame-v2",
    byteLength: 3500,
    mimeType: "image/jpeg",
    rawFramePersisted: false,
    visualFeatures: {
      facePresent: true,
      faceCount: 1,
      headOrientation: "screen",
      roughlyFacingScreen: true,
      facingScore: 0.82,
      centerOffsetX: 0.04,
      centerOffsetY: -0.03,
      faceAreaRatio: 0.16,
      imageQuality: "good",
      provider: "browser-mediapipe-face",
      algorithmVersion: "browser-attention-v2",
      confidence: 0.86
    }
  };

  const accepted = await request(`/behavior/${sessionId}/camera/frames/${encodeURIComponent(frameId)}`, {
    method: "POST",
    body: JSON.stringify(descriptor)
  });
  assert.equal(accepted.response.status, 200);
  assert.equal(accepted.body.data.accepted, true);
});
