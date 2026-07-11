import {
  INTERACTION_STATES,
  type InteractionState,
  type StateMachineTrigger
} from "../src/stateMachine.js";

type Assert<T extends true> = T;
type Includes<TValue, TUnion> = TValue extends TUnion ? true : false;
type StateUnionMatchesConstants = Assert<Includes<(typeof INTERACTION_STATES)[number], InteractionState>>;
type StateUnionContainsIdle = Assert<Includes<"IDLE", InteractionState>>;
type TriggerUnionAcceptsDomainEvents = Assert<Includes<"ANSWER_EVALUATED", StateMachineTrigger>>;
type TriggerUnionAcceptsSystemSignals = Assert<Includes<"STT_FAILED", StateMachineTrigger>>;

const waitingState = "WAITING_FOR_RESPONSE" satisfies InteractionState;
const answerTrigger = "ANSWER_SUBMITTED" satisfies StateMachineTrigger;
const systemTrigger = "PROVIDER_RECOVERED" satisfies StateMachineTrigger;

void waitingState;
void answerTrigger;
void systemTrigger;

