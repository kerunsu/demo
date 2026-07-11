import { once } from "node:events";
import assert from "node:assert/strict";
import { after, before, test } from "node:test";

let server;
let baseUrl;
let wsUrl;
let realtimeHubRef;

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

function waitForEvent(socket, eventType, predicate = () => true) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`Timed out waiting for ${eventType}`)), 4000);
    function onMessage(raw) {
      const message = JSON.parse(String(raw.data));
      if (message.type === "event" && message.event.eventType === eventType && predicate(message.event)) {
        clearTimeout(timer);
        socket.removeEventListener("message", onMessage);
        resolve(message.event);
      }
    }
    socket.addEventListener("message", onMessage);
  });
}

function createAckEvent(sessionId, eventType, payload) {
  return {
    eventId: `${eventType.toLowerCase()}_${Math.random().toString(36).slice(2, 8)}`,
    eventType,
    sessionId,
    timestamp: new Date().toISOString(),
    source: "robot_screen",
    correlationId: `corr_${Math.random().toString(36).slice(2, 8)}`,
    causationId: null,
    schemaVersion: "v1",
    persist: false,
    payload
  };
}

before(async () => {
  process.env.AI_CHAT_PROVIDER = "rule";
  process.env.AI_TTS_PROVIDER = "none";
  process.env.OPENAI_API_KEY = "";

  const { createApp } = await import("../dist/app.js");
  const { startServer } = await import("../dist/server.js");
  const { realtimeHub } = await import("../dist/services/realtimeHub.js");
  const { handleClientDomainEvent } = await import("../dist/services/domainEventService.js");
  realtimeHubRef = realtimeHub;
  realtimeHub.onClientEvent((event) => handleClientDomainEvent(event));
  server = startServer(createApp({ enableRequestLogging: false }), {
    port: 0,
    host: "127.0.0.1",
    realtimeHub
  });
  await once(server, "listening");
  const address = server.address();
  assert.ok(address && typeof address === "object");
  baseUrl = `http://127.0.0.1:${address.port}/api`;
  wsUrl = `ws://127.0.0.1:${address.port}/ws`;
});

after(async () => {
  realtimeHubRef?.closeAll();
  if (!server?.listening) return;
  server.close();
  await once(server, "close");
});

test("websocket publishes answer feedback events and accepts robot ACKs before next question event", async () => {
  const started = await request("/session/start", {
    method: "POST",
    body: JSON.stringify({ childName: "Realtime Child", courseType: "matching" })
  });
  assert.equal(started.response.status, 200);
  const { sessionId } = started.body.data;

  const socket = new WebSocket(`${wsUrl}?sessionId=${sessionId}&screenRole=robot&clientId=test-robot`);
  await once(socket, "open");

  const snapshot = await request(`/session/${sessionId}/snapshot`);
  assert.equal(snapshot.response.status, 200);
  assert.ok(snapshot.body.data.events.some((event) => event.eventType === "SESSION_STARTED"));
  assert.ok(snapshot.body.data.events.some((event) => event.eventType === "QUESTION_PRESENTED"));

  const current = await request(`/course/${sessionId}/current`);
  const question = current.body.data;
  const session = await request(`/session/${sessionId}`);
  const correctOptionId = session.body.data.questions[session.body.data.currentQuestionIndex].correctOptionId;
  assert.ok(correctOptionId);

  const animationRequestedPromise = waitForEvent(socket, "ANIMATION_REQUESTED");
  const answer = await request(`/course/${sessionId}/answer`, {
    method: "POST",
    body: JSON.stringify({
      questionId: question.questionId,
      answer: { selectedOptionId: correctOptionId },
      responseTimeMs: 900
    })
  });
  assert.equal(answer.response.status, 200);
  assert.equal(answer.body.data.correct, true);

  const animationRequested = await animationRequestedPromise;
  assert.notEqual(animationRequested.payload.animationId, "sad");
  assert.notEqual(animationRequested.payload.animationId, "dissatisfied");
  const nextQuestionEventPromise = waitForEvent(
    socket,
    "QUESTION_PRESENTED",
    (event) => event.payload.questionId !== question.questionId
  );

  const turnId = `tts_${animationRequested.causationId}`;
  socket.send(
    JSON.stringify({
      type: "event",
      event: createAckEvent(sessionId, "ANIMATION_STARTED", {
        commandId: animationRequested.payload.commandId,
        animationId: animationRequested.payload.animationId,
        startedAt: new Date().toISOString()
      })
    })
  );
  socket.send(
    JSON.stringify({
      type: "event",
      event: createAckEvent(sessionId, "TTS_STARTED", {
        turnId,
        provider: "mock_local",
        textHash: `mock:${turnId}`,
        voice: "local-demo"
      })
    })
  );
  socket.send(
    JSON.stringify({
      type: "event",
      event: createAckEvent(sessionId, "ANIMATION_FINISHED", {
        commandId: animationRequested.payload.commandId,
        status: "completed",
        durationMs: 1200
      })
    })
  );
  socket.send(
    JSON.stringify({
      type: "event",
      event: createAckEvent(sessionId, "TTS_FINISHED", {
        turnId,
        audioRef: "mock://local-feedback",
        durationMs: 800,
        mimeType: "audio/mock"
      })
    })
  );

  const nextQuestion = await nextQuestionEventPromise;
  assert.equal(nextQuestion.eventType, "QUESTION_PRESENTED");
  assert.notEqual(nextQuestion.payload.questionId, question.questionId);
  socket.close();
});
