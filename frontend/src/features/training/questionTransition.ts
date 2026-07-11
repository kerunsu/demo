/**
 * Keep in sync with `.option-card-fun.correct` animation duration in styles.css
 * (`card-hop-flip-success`, 2s). Camera/video per-question streams switch when
 * `setQuestion` runs after this delay — i.e. when the next question appears.
 */
export const CORRECT_ANSWER_TRANSITION_MS = 2000;

export function waitForQuestionTransition() {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, CORRECT_ANSWER_TRANSITION_MS);
  });
}

export function isAnswerTransitionLocked(optionStates: Record<string, string>) {
  return Object.values(optionStates).some((state) => state === "correct");
}
