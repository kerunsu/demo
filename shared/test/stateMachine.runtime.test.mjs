import assert from "node:assert/strict";
import test from "node:test";

import {
  ALLOWED_STATE_TRANSITIONS,
  INTERACTION_STATES,
  applyStateTransition,
  getAllowedTransitions,
  isTransitionAllowed,
  validateStateTransition
} from "../dist/stateMachine.js";

test("interaction state list follows the documented state machine", () => {
  assert.deepEqual(INTERACTION_STATES, [
    "IDLE",
    "SESSION_STARTING",
    "QUESTION_PRESENTING",
    "WAITING_FOR_RESPONSE",
    "LISTENING",
    "TRANSCRIBING",
    "EVALUATING_ANSWER",
    "PLAYING_CORRECT_FEEDBACK",
    "PLAYING_INCORRECT_FEEDBACK",
    "GENERATING_REPLY",
    "SAFETY_REVIEWING",
    "SPEAKING",
    "TRANSITIONING",
    "SESSION_COMPLETED",
    "DEGRADED",
    "ERROR"
  ]);
});

test("core click-answer path permits only documented transitions", () => {
  const path = [
    ["IDLE", "SESSION_STARTING", "SESSION_START_REQUESTED"],
    ["SESSION_STARTING", "QUESTION_PRESENTING", "SESSION_STARTED"],
    ["QUESTION_PRESENTING", "WAITING_FOR_RESPONSE", "QUESTION_PRESENTED"],
    ["WAITING_FOR_RESPONSE", "EVALUATING_ANSWER", "ANSWER_SUBMITTED"],
    ["EVALUATING_ANSWER", "PLAYING_CORRECT_FEEDBACK", "ANSWER_EVALUATED"],
    ["PLAYING_CORRECT_FEEDBACK", "GENERATING_REPLY", "FEEDBACK_REQUESTED"],
    ["GENERATING_REPLY", "SAFETY_REVIEWING", "LLM_REPLY_GENERATED"],
    ["SAFETY_REVIEWING", "SPEAKING", "SAFETY_REVIEW_PASSED"],
    ["SPEAKING", "TRANSITIONING", "TTS_FINISHED"],
    ["TRANSITIONING", "QUESTION_PRESENTING", "QUESTION_PRESENTED"]
  ];

  for (const [from, to, trigger] of path) {
    assert.equal(isTransitionAllowed(from, to, trigger), true);
    assert.equal(applyStateTransition(from, to, trigger), to);
  }
});

test("voice fallback and safety failure paths are explicit", () => {
  assert.equal(isTransitionAllowed("WAITING_FOR_RESPONSE", "LISTENING", "LISTENING_STARTED"), true);
  assert.equal(isTransitionAllowed("LISTENING", "TRANSCRIBING", "LISTENING_FINISHED"), true);
  assert.equal(isTransitionAllowed("TRANSCRIBING", "DEGRADED", "STT_FAILED"), true);
  assert.equal(isTransitionAllowed("GENERATING_REPLY", "DEGRADED", "LLM_FAILED"), true);
  assert.equal(isTransitionAllowed("SAFETY_REVIEWING", "SPEAKING", "SAFETY_REVIEW_REJECTED"), true);
  assert.equal(isTransitionAllowed("SAFETY_REVIEWING", "DEGRADED", "TIMEOUT"), true);
});

test("invalid transitions return a reason and throw when applied", () => {
  const invalidTransition = validateStateTransition("IDLE", "SPEAKING", "TTS_STARTED");

  assert.deepEqual(invalidTransition, {
    from: "IDLE",
    to: "SPEAKING",
    trigger: "TTS_STARTED",
    reason: "Transition IDLE -> SPEAKING on TTS_STARTED is not allowed by the interaction state machine."
  });

  assert.throws(
    () => applyStateTransition("IDLE", "SPEAKING", "TTS_STARTED"),
    /Transition IDLE -> SPEAKING on TTS_STARTED is not allowed/
  );
});

test("all transitions reference known states and expose queryable outgoing edges", () => {
  const knownStates = new Set(INTERACTION_STATES);

  for (const transition of ALLOWED_STATE_TRANSITIONS) {
    assert.equal(knownStates.has(transition.from), true);
    assert.equal(knownStates.has(transition.to), true);
  }

  assert.deepEqual(
    getAllowedTransitions("SESSION_COMPLETED").map((transition) => transition.to),
    ["IDLE"]
  );
});

