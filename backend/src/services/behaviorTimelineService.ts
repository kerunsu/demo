import type {
  BehaviorObservation,
  ObservationWindow
} from "child-education-training-demo/shared/behavior-observations";

export interface QuestionTimelineInput {
  sessionId: string;
  questionId: string;
  correlationId: string;
  questionPresentedEventId: string;
  startedAt: string;
  completedAt: string;
  observations: BehaviorObservation[];
  additionalEventIds?: string[];
}

export function createQuestionObservationWindow(input: QuestionTimelineInput): ObservationWindow {
  const observations = dedupeObservations(input.observations).filter((observation) => {
    if (observation.sessionId !== input.sessionId) return false;
    if (observation.questionId && observation.questionId !== input.questionId) return false;
    return withinRange(observation.observedAt, input.startedAt, input.completedAt);
  });

  return {
    windowId: `window:${input.sessionId}:${input.questionId}`,
    sessionId: input.sessionId,
    questionId: input.questionId,
    correlationId: input.correlationId,
    windowType: "question",
    startedAt: input.startedAt,
    endedAt: input.completedAt,
    inputEventIds: Array.from(new Set([input.questionPresentedEventId, ...(input.additionalEventIds ?? [])])),
    observationIds: observations.map((observation) => observation.observationId),
    algorithm: {
      schemaVersion: "m5-behavior-v1",
      algorithmVersion: "question-window-alignment-v1"
    },
    dataQuality: observations.length > 0 ? { status: "complete" } : { status: "insufficient", reasonCode: "NO_OBSERVATIONS" },
    createdAt: new Date().toISOString()
  };
}

export function dedupeObservations<TObservation extends Pick<BehaviorObservation, "observationId">>(observations: TObservation[]) {
  const byId = new Map<string, TObservation>();
  for (const observation of observations) {
    if (!byId.has(observation.observationId)) {
      byId.set(observation.observationId, observation);
    }
  }
  return Array.from(byId.values());
}

function withinRange(value: string, startedAt: string, endedAt: string) {
  const timestamp = Date.parse(value);
  return timestamp >= Date.parse(startedAt) && timestamp <= Date.parse(endedAt);
}
