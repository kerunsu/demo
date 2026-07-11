import {
  MockChildSafetyProvider,
  MockLlmProvider,
  MockSttProvider,
  MockTtsProvider,
  type ChildSafetyProvider,
  type LlmProvider,
  type SafetyReviewDecision,
  type SttProvider,
  type TtsProvider
} from "../src/providers.js";

type Assert<T extends true> = T;
type Extends<TValue, TBase> = TValue extends TBase ? true : false;

type MockSttSatisfiesProvider = Assert<Extends<MockSttProvider, SttProvider>>;
type MockLlmSatisfiesProvider = Assert<Extends<MockLlmProvider, LlmProvider>>;
type MockSafetySatisfiesProvider = Assert<Extends<MockChildSafetyProvider, ChildSafetyProvider>>;
type MockTtsSatisfiesProvider = Assert<Extends<MockTtsProvider, TtsProvider>>;

const reviewedText = {
  requestId: "review-1",
  target: "output",
  action: "allow",
  approvedText: "我们继续当前题目。",
  piiTypes: [],
  reasonCodes: [],
  policyVersion: "mock-policy-v1"
} satisfies SafetyReviewDecision;

void reviewedText;
