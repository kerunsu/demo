import type {
  DomainEvent,
  DomainEventOf
} from "child-education-training-demo/shared/domain-events";
import type {
  InteractionState,
  StateMachineTrigger
} from "child-education-training-demo/shared/state-machine";
import type {
  MockProviderSet,
  ProviderResult,
  SttTranscript
} from "child-education-training-demo/shared/providers";
import type {
  RobotAnimationAdapter,
  RobotAnimationId,
  RobotAnimationManifest
} from "child-education-training-demo/shared/animations";
import type { MediaChunkAck, MediaStreamStartRequest } from "child-education-training-demo/shared/media";
import type {
  AttentionObservation,
  DataQualityStatus,
  EvidenceReference,
  QuestionBehaviorSummary,
  SessionBehaviorSummary
} from "child-education-training-demo/shared/behavior-observations";
import type {
  CameraDeviceState,
  CameraFrameAck,
  CameraFrameSampleDescriptor
} from "child-education-training-demo/shared/behavior-frames";

const reportEvent: DomainEventOf<"REPORT_GENERATED"> = {
  eventId: "event-report-1",
  eventType: "REPORT_GENERATED",
  sessionId: "session-1",
  timestamp: "2026-06-07T00:22:00.000+08:00",
  source: "backend",
  correlationId: "corr-report-1",
  causationId: null,
  schemaVersion: "v1",
  persist: true,
  payload: {
    reportId: "report-1",
    reportVersion: "v1",
    generatedAt: "2026-06-07T00:22:00.000+08:00"
  }
};

const importedThroughRootPackage: DomainEvent = reportEvent;
const importedStateThroughRootPackage: InteractionState = "WAITING_FOR_RESPONSE";
const importedTriggerThroughRootPackage: StateMachineTrigger = "ANSWER_SUBMITTED";
const importedProviderResultThroughRootPackage: ProviderResult<SttTranscript> = {
  ok: false,
  metadata: {
    providerKind: "stt",
    providerName: "mock-stt",
    mode: "mock",
    version: "mock-v1"
  },
  latencyMs: 0,
  error: {
    code: "TIMEOUT",
    message: "timeout"
  }
};
const importedMockSetThroughRootPackage = undefined as unknown as MockProviderSet;
const importedAnimationIdThroughRootPackage: RobotAnimationId = "eye";
const importedAnimationManifestThroughRootPackage = [] as unknown as RobotAnimationManifest;
const importedAnimationAdapterThroughRootPackage = undefined as unknown as RobotAnimationAdapter;
const importedMediaStartThroughRootPackage: MediaStreamStartRequest = {
  sessionId: "session-1",
  streamId: "stream-1",
  turnId: "turn-1",
  correlationId: "corr-1",
  startedAt: "2026-06-13T08:00:00.000Z",
  format: {
    codec: "webm_opus",
    mimeType: "audio/webm;codecs=opus",
    sampleRateHz: 48000,
    channels: 1,
    chunkDurationMs: 250
  },
  maxTurnDurationMs: 10000
};
const importedMediaAckThroughRootPackage = undefined as unknown as MediaChunkAck;
const importedDataQualityStatus: DataQualityStatus = "missing_device";
const importedEvidenceReference = undefined as unknown as EvidenceReference;
const importedAttentionObservation = undefined as unknown as AttentionObservation;
const importedQuestionBehaviorSummary = undefined as unknown as QuestionBehaviorSummary;
const importedSessionBehaviorSummary = undefined as unknown as SessionBehaviorSummary;
const importedCameraDeviceState = undefined as unknown as CameraDeviceState;
const importedCameraFrameDescriptor = undefined as unknown as CameraFrameSampleDescriptor;
const importedCameraFrameAck = undefined as unknown as CameraFrameAck;

void importedThroughRootPackage;
void importedStateThroughRootPackage;
void importedTriggerThroughRootPackage;
void importedProviderResultThroughRootPackage;
void importedMockSetThroughRootPackage;
void importedAnimationIdThroughRootPackage;
void importedAnimationManifestThroughRootPackage;
void importedAnimationAdapterThroughRootPackage;
void importedMediaStartThroughRootPackage;
void importedMediaAckThroughRootPackage;
void importedDataQualityStatus;
void importedEvidenceReference;
void importedAttentionObservation;
void importedQuestionBehaviorSummary;
void importedSessionBehaviorSummary;
void importedCameraDeviceState;
void importedCameraFrameDescriptor;
void importedCameraFrameAck;
