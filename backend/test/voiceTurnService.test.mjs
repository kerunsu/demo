import assert from "node:assert/strict";
import test from "node:test";

import {
  completeVoiceTurn,
  getVoiceTurnSnapshot,
  markRobotSpeaking,
  resetVoiceTurnsForTests,
  retryVoiceTurn,
  startListeningTurn,
  stopListeningForTranscription
} from "../dist/services/voiceTurnService.js";

test("voice turn control enforces half-duplex listening and robot speaking", () => {
  resetVoiceTurnsForTests();
  const sessionId = "session-turn-1";

  const listening = startListeningTurn({ sessionId, turnId: "turn-1", timeoutMs: 8000 });
  assert.equal(listening.state, "LISTENING");
  assert.equal(listening.listeningAllowed, true);
  assert.equal(listening.bargeInReserved, true);
  assert.ok(listening.deadlineAt);

  const transcribing = stopListeningForTranscription(sessionId);
  assert.equal(transcribing.state, "TRANSCRIBING");
  assert.equal(transcribing.listeningAllowed, false);

  const speaking = markRobotSpeaking({ sessionId, turnId: "turn-1", speaking: true, reason: "tts_started" });
  assert.equal(speaking.state, "ROBOT_SPEAKING");
  assert.equal(speaking.robotSpeaking, true);
  assert.equal(speaking.listeningAllowed, false);

  const blockedListening = startListeningTurn({ sessionId, turnId: "turn-2" });
  assert.equal(blockedListening.state, "DEGRADED");
  assert.equal(blockedListening.lastReason, "ROBOT_SPEAKING_LISTENING_PAUSED");

  const completed = completeVoiceTurn(sessionId, "tts_finished");
  assert.equal(completed.state, "COMPLETED");
  assert.equal(completed.listeningAllowed, true);
  assert.equal(completed.robotSpeaking, false);
});

test("voice turn retry degrades after max retries", () => {
  resetVoiceTurnsForTests();
  const sessionId = "session-turn-retry";
  startListeningTurn({ sessionId, turnId: "turn-1", maxRetries: 1 });

  const firstRetry = retryVoiceTurn(sessionId, "empty_transcript");
  assert.equal(firstRetry.state, "IDLE");
  assert.equal(firstRetry.listeningAllowed, true);
  assert.equal(firstRetry.retryCount, 1);

  const secondRetry = retryVoiceTurn(sessionId, "empty_transcript");
  assert.equal(secondRetry.state, "DEGRADED");
  assert.equal(secondRetry.listeningAllowed, false);
  assert.equal(secondRetry.lastReason, "MAX_RETRIES_EXCEEDED");

  const snapshot = getVoiceTurnSnapshot(sessionId);
  assert.equal(snapshot.state, "DEGRADED");
});
