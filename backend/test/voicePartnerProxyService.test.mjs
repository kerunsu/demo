import assert from "node:assert/strict";
import { createServer } from "node:http";
import { test } from "node:test";
import "./testEnv.mjs";

function withMockPartnerServer(handler, run) {
  return new Promise((resolve, reject) => {
    const server = createServer(async (req, res) => {
      try {
        const chunks = [];
        for await (const chunk of req) chunks.push(chunk);
        const body = Buffer.concat(chunks).toString("utf-8");
        const payload = body ? JSON.parse(body) : {};
        const result = await handler(req, payload);
        res.writeHead(result.status ?? 200, { "content-type": "application/json" });
        res.end(JSON.stringify(result.body));
      } catch (error) {
        res.writeHead(500, { "content-type": "application/json" });
        res.end(JSON.stringify({ ok: false, error: { code: "MOCK_FAILURE", message: String(error) } }));
      }
    });
    server.listen(0, "127.0.0.1", async () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      try {
        await run(`http://127.0.0.1:${port}`);
        resolve();
      } catch (error) {
        reject(error);
      } finally {
        server.close();
      }
    });
  });
}

test("processPartnerVoiceTurn forwards audio and page context to partner service", async () => {
  process.env.VOICE_DIALOG_PROVIDER = "partner";
  process.env.VOICE_PARTNER_API_KEY = "test-key";
  process.env.VOICE_PARTNER_FALLBACK = "none";

  const { startSession } = await import("../dist/services/sessionService.js");
  const { startMediaStream, receiveMediaChunk, finishMediaStream, resetMediaIngressForTests } = await import(
    "../dist/services/mediaIngressService.js"
  );
  const { processPartnerVoiceTurn } = await import("../dist/services/voicePartnerProxyService.js");
  const { resetPartnerTurnStateForTests } = await import("../dist/services/voicePartnerTurnState.js");

  resetMediaIngressForTests();
  resetPartnerTurnStateForTests();

  const started = startSession("Partner Child", "matching");
  const streamId = "stream-partner-1";
  const turnId = "voice-turn-partner-1";
  const correlationId = "corr-partner-1";

  await startMediaStream({
    sessionId: started.sessionId,
    streamId,
    turnId,
    correlationId,
    startedAt: new Date().toISOString(),
    format: {
      codec: "webm_opus",
      mimeType: "audio/webm;codecs=opus",
      sampleRateHz: 48000,
      channels: 1,
      chunkDurationMs: 250
    },
    maxTurnDurationMs: 8000
  });

  const chunk = Buffer.from("fake-audio-chunk");
  await receiveMediaChunk(
    {
      sessionId: started.sessionId,
      streamId,
      turnId,
      correlationId,
      sequence: 0,
      capturedAt: new Date().toISOString(),
      durationMs: 250,
      byteLength: chunk.byteLength,
      format: {
        codec: "webm_opus",
        mimeType: "audio/webm;codecs=opus",
        sampleRateHz: 48000,
        channels: 1,
        chunkDurationMs: 250
      }
    },
    chunk
  );

  await finishMediaStream({
    sessionId: started.sessionId,
    streamId,
    turnId,
    correlationId,
    reason: "manual_stop",
    endedAt: new Date().toISOString()
  });

  let received = null;
  await withMockPartnerServer(
    (req, payload) => {
      received = payload;
      assert.equal(req.headers["x-voice-partner-key"], "test-key");
      assert.equal(payload.schemaVersion, "voice-partner-turn-v1");
      assert.ok(payload.audio?.base64);
      assert.equal(payload.pageContext.text.prompt, "找出相同图片");
      assert.ok(Array.isArray(payload.history));
      return {
        body: {
          ok: true,
          replyText: "好的，我们继续。",
          replyAudio: { base64: "", mimeType: "audio/wav" },
          metadata: { provider: "mock-partner", latencyMs: 12 }
        }
      };
    },
    async (baseUrl) => {
      process.env.VOICE_PARTNER_BASE_URL = baseUrl;
      const result = await processPartnerVoiceTurn({
        sessionId: started.sessionId,
        streamId,
        turnId,
        correlationId,
        pageContext: {
          text: {
            schemaVersion: "voice-page-context-v1",
            courseType: "matching",
            questionIndex: 1,
            totalQuestions: 3,
            prompt: "找出相同图片",
            target: "苹果",
            options: [{ id: "a", label: "苹果" }],
            interaction: { selectedOptionIds: [], wrongAttempts: 0, elapsedMs: 1000 },
            narrative: "测试叙事"
          },
          screenshot: null,
          screenshotUnavailableReason: "CAPTURE_FAILED"
        }
      });
      assert.match(result.reply, /继续/);
      assert.equal(result.provider, "mock-partner");
    }
  );

  assert.ok(received);
});

test("persistChildTranscriptObservations stores language features without chat reply", async () => {
  process.env.AI_CHAT_PROVIDER = "rule";
  const { startSession } = await import("../dist/services/sessionService.js");
  const { persistChildTranscriptObservations } = await import("../dist/services/chatService.js");

  const started = startSession("Obs Child", "matching");
  const result = await persistChildTranscriptObservations(started.sessionId, "我选择苹果");
  assert.equal(result.persisted, true);
});
