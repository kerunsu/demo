import type { DomainEventType } from "./domainEvents.js";

export const INTERACTION_STATES = [
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
] as const;

export type InteractionState = (typeof INTERACTION_STATES)[number];

export type StateMachineCommand =
  | "SESSION_START_REQUESTED"
  | "VOICE_CANCELLED"
  | "SPEECH_INTERRUPTED"
  | "RETRY_REQUESTED";

export type StateMachineSystemSignal =
  | "ERROR_OCCURRED"
  | "TIMEOUT"
  | "VOICE_ERROR"
  | "STT_FAILED"
  | "LLM_FAILED"
  | "PROVIDER_RECOVERED"
  | "CLIENT_RECONNECTED"
  | "FEEDBACK_COMPLETED"
  | "SESSION_COMPLETED";

export type StateMachineTrigger = DomainEventType | StateMachineCommand | StateMachineSystemSignal;

export type TriggerSource = "domain_event" | "command" | "system_signal";

export interface StateTransition {
  from: InteractionState;
  to: InteractionState;
  trigger: StateMachineTrigger;
  triggerSource: TriggerSource;
  description: string;
}

export interface InvalidStateTransition {
  from: InteractionState;
  to: InteractionState;
  trigger: StateMachineTrigger;
  reason: string;
}

export const ALLOWED_STATE_TRANSITIONS = [
  {
    from: "IDLE",
    to: "SESSION_STARTING",
    trigger: "SESSION_START_REQUESTED",
    triggerSource: "command",
    description: "child screen requests a new training session"
  },
  {
    from: "IDLE",
    to: "DEGRADED",
    trigger: "CLIENT_DISCONNECTED",
    triggerSource: "domain_event",
    description: "a required screen disconnects before a session starts"
  },
  {
    from: "SESSION_STARTING",
    to: "QUESTION_PRESENTING",
    trigger: "SESSION_STARTED",
    triggerSource: "domain_event",
    description: "backend created the session and is ready to present a question"
  },
  {
    from: "SESSION_STARTING",
    to: "ERROR",
    trigger: "ERROR_OCCURRED",
    triggerSource: "system_signal",
    description: "session creation failed"
  },
  {
    from: "QUESTION_PRESENTING",
    to: "WAITING_FOR_RESPONSE",
    trigger: "QUESTION_PRESENTED",
    triggerSource: "domain_event",
    description: "question presentation reached both screens or the available screen"
  },
  {
    from: "QUESTION_PRESENTING",
    to: "ERROR",
    trigger: "ERROR_OCCURRED",
    triggerSource: "system_signal",
    description: "question presentation cannot recover from the current error"
  },
  {
    from: "WAITING_FOR_RESPONSE",
    to: "LISTENING",
    trigger: "LISTENING_STARTED",
    triggerSource: "domain_event",
    description: "voice input starts for the current question"
  },
  {
    from: "WAITING_FOR_RESPONSE",
    to: "EVALUATING_ANSWER",
    trigger: "ANSWER_SUBMITTED",
    triggerSource: "domain_event",
    description: "child submitted a click or resolved text answer"
  },
  {
    from: "WAITING_FOR_RESPONSE",
    to: "DEGRADED",
    trigger: "TIMEOUT",
    triggerSource: "system_signal",
    description: "the response window timed out and the flow needs a degraded prompt"
  },
  {
    from: "LISTENING",
    to: "TRANSCRIBING",
    trigger: "LISTENING_FINISHED",
    triggerSource: "domain_event",
    description: "voice capture ended and can be transcribed"
  },
  {
    from: "LISTENING",
    to: "WAITING_FOR_RESPONSE",
    trigger: "VOICE_CANCELLED",
    triggerSource: "command",
    description: "child or operator cancelled voice capture"
  },
  {
    from: "LISTENING",
    to: "DEGRADED",
    trigger: "VOICE_ERROR",
    triggerSource: "system_signal",
    description: "voice capture failed and text fallback is required"
  },
  {
    from: "TRANSCRIBING",
    to: "EVALUATING_ANSWER",
    trigger: "TRANSCRIPT_READY",
    triggerSource: "domain_event",
    description: "final redacted transcript is ready to evaluate"
  },
  {
    from: "TRANSCRIBING",
    to: "DEGRADED",
    trigger: "STT_FAILED",
    triggerSource: "system_signal",
    description: "transcription failed and text fallback is required"
  },
  {
    from: "EVALUATING_ANSWER",
    to: "PLAYING_CORRECT_FEEDBACK",
    trigger: "ANSWER_EVALUATED",
    triggerSource: "domain_event",
    description: "answer was evaluated as correct"
  },
  {
    from: "EVALUATING_ANSWER",
    to: "PLAYING_INCORRECT_FEEDBACK",
    trigger: "ANSWER_EVALUATED",
    triggerSource: "domain_event",
    description: "answer was evaluated as incorrect"
  },
  {
    from: "PLAYING_CORRECT_FEEDBACK",
    to: "GENERATING_REPLY",
    trigger: "FEEDBACK_REQUESTED",
    triggerSource: "domain_event",
    description: "correct-answer feedback requires a robot reply or speech step"
  },
  {
    from: "PLAYING_CORRECT_FEEDBACK",
    to: "TRANSITIONING",
    trigger: "FEEDBACK_COMPLETED",
    triggerSource: "system_signal",
    description: "feedback completed without an additional generated reply"
  },
  {
    from: "PLAYING_INCORRECT_FEEDBACK",
    to: "GENERATING_REPLY",
    trigger: "FEEDBACK_REQUESTED",
    triggerSource: "domain_event",
    description: "incorrect-answer feedback requires a robot reply or speech step"
  },
  {
    from: "PLAYING_INCORRECT_FEEDBACK",
    to: "WAITING_FOR_RESPONSE",
    trigger: "FEEDBACK_COMPLETED",
    triggerSource: "system_signal",
    description: "incorrect-answer feedback completed and the same question can be retried"
  },
  {
    from: "GENERATING_REPLY",
    to: "SAFETY_REVIEWING",
    trigger: "LLM_REPLY_GENERATED",
    triggerSource: "domain_event",
    description: "candidate reply is ready for safety review"
  },
  {
    from: "GENERATING_REPLY",
    to: "DEGRADED",
    trigger: "LLM_FAILED",
    triggerSource: "system_signal",
    description: "reply generation failed and rule fallback is required"
  },
  {
    from: "SAFETY_REVIEWING",
    to: "SPEAKING",
    trigger: "SAFETY_REVIEW_PASSED",
    triggerSource: "domain_event",
    description: "candidate reply passed safety review"
  },
  {
    from: "SAFETY_REVIEWING",
    to: "SPEAKING",
    trigger: "SAFETY_REVIEW_REJECTED",
    triggerSource: "domain_event",
    description: "unsafe candidate was replaced with fixed fallback text"
  },
  {
    from: "SAFETY_REVIEWING",
    to: "DEGRADED",
    trigger: "TIMEOUT",
    triggerSource: "system_signal",
    description: "safety review timed out and candidate output must not be used"
  },
  {
    from: "SPEAKING",
    to: "TRANSITIONING",
    trigger: "TTS_FINISHED",
    triggerSource: "domain_event",
    description: "approved speech or fallback playback finished"
  },
  {
    from: "SPEAKING",
    to: "TRANSITIONING",
    trigger: "SPEECH_INTERRUPTED",
    triggerSource: "command",
    description: "approved speech was interrupted and flow can continue"
  },
  {
    from: "TRANSITIONING",
    to: "QUESTION_PRESENTING",
    trigger: "QUESTION_PRESENTED",
    triggerSource: "domain_event",
    description: "next question is available"
  },
  {
    from: "TRANSITIONING",
    to: "SESSION_COMPLETED",
    trigger: "SESSION_COMPLETED",
    triggerSource: "system_signal",
    description: "all questions are finished"
  },
  {
    from: "TRANSITIONING",
    to: "SESSION_COMPLETED",
    trigger: "SESSION_ENDED",
    triggerSource: "domain_event",
    description: "backend ended the session after the last question"
  },
  {
    from: "SESSION_COMPLETED",
    to: "IDLE",
    trigger: "SESSION_ENDED",
    triggerSource: "domain_event",
    description: "completed session is closed and screens may return to idle"
  },
  {
    from: "DEGRADED",
    to: "WAITING_FOR_RESPONSE",
    trigger: "PROVIDER_RECOVERED",
    triggerSource: "system_signal",
    description: "fallback condition recovered while the current question is still active"
  },
  {
    from: "DEGRADED",
    to: "QUESTION_PRESENTING",
    trigger: "CLIENT_RECONNECTED",
    triggerSource: "system_signal",
    description: "a disconnected screen recovered and can restore from snapshot"
  },
  {
    from: "DEGRADED",
    to: "IDLE",
    trigger: "SESSION_ENDED",
    triggerSource: "domain_event",
    description: "session ended while degraded"
  },
  {
    from: "ERROR",
    to: "QUESTION_PRESENTING",
    trigger: "RETRY_REQUESTED",
    triggerSource: "command",
    description: "operator or client requested a retry from a recoverable snapshot"
  },
  {
    from: "ERROR",
    to: "IDLE",
    trigger: "SESSION_ENDED",
    triggerSource: "domain_event",
    description: "unrecoverable session ended"
  }
] as const satisfies readonly StateTransition[];

export function getAllowedTransitions(from: InteractionState): StateTransition[] {
  return ALLOWED_STATE_TRANSITIONS.filter((transition) => transition.from === from);
}

export function isTransitionAllowed(
  from: InteractionState,
  to: InteractionState,
  trigger: StateMachineTrigger
): boolean {
  return ALLOWED_STATE_TRANSITIONS.some(
    (transition) => transition.from === from && transition.to === to && transition.trigger === trigger
  );
}

export function validateStateTransition(
  from: InteractionState,
  to: InteractionState,
  trigger: StateMachineTrigger
): InvalidStateTransition | null {
  if (isTransitionAllowed(from, to, trigger)) {
    return null;
  }

  return {
    from,
    to,
    trigger,
    reason: `Transition ${from} -> ${to} on ${trigger} is not allowed by the interaction state machine.`
  };
}

export function applyStateTransition(
  from: InteractionState,
  to: InteractionState,
  trigger: StateMachineTrigger
): InteractionState {
  const invalidTransition = validateStateTransition(from, to, trigger);
  if (invalidTransition) {
    throw new Error(invalidTransition.reason);
  }
  return to;
}

