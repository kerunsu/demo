import type {
  AttentionObservation,
  BehaviorObservation,
  DataQualityStatus,
  EvidenceReference,
  LanguageObservation,
  ObservationWindow,
  QuestionBehaviorSummary,
  SessionBehaviorSummary
} from "../src/behaviorObservations.js";

type Assert<T extends true> = T;
type Extends<TValue, TBase> = TValue extends TBase ? true : false;

type AttentionIsBehaviorObservation = Assert<Extends<AttentionObservation, BehaviorObservation>>;
type LanguageIsBehaviorObservation = Assert<Extends<LanguageObservation, BehaviorObservation>>;

const quality: DataQualityStatus = "missing_device";

const evidence: EvidenceReference = {
  type: "domain_event",
  id: "event-1",
  sessionId: "session-1",
  questionId: "question-1",
  eventId: "event-1",
  createdAt: "2026-06-14T01:00:00.000+08:00",
  redacted: true
};

const window = undefined as unknown as ObservationWindow;
const questionSummary = undefined as unknown as QuestionBehaviorSummary;
const sessionSummary = undefined as unknown as SessionBehaviorSummary;

void quality;
void evidence;
void window;
void questionSummary;
void sessionSummary;
