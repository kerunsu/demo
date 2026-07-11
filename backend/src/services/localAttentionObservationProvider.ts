import type { CameraFrameSampleDescriptor } from "child-education-training-demo/shared/behavior-frames";
import type { AttentionObservation } from "child-education-training-demo/shared/behavior-observations";
import {
  ATTENTION_ALGORITHM_V2,
  normalizeAttentionVisualFeatures
} from "child-education-training-demo/shared/attention-scoring";
import type {
  AttentionObservationInput,
  AttentionObservationProvider,
  ProviderMetadata,
  ProviderResult
} from "child-education-training-demo/shared/providers";

type LocalAttentionInput = AttentionObservationInput & {
  frameDescriptor?: CameraFrameSampleDescriptor;
};

export class LocalAttentionObservationProvider implements AttentionObservationProvider {
  metadata: ProviderMetadata & { providerKind: "attention_observation" } = {
    providerKind: "attention_observation",
    providerName: "local-browser-face-attention",
    providerId: "local-browser-face-attention",
    providerType: "local",
    mode: "local",
    version: "final-b-local-attention-v2",
    modelId: ATTENTION_ALGORITHM_V2,
    defaultEnabled: true,
    humanReview: "NOT_REQUIRED",
    licenseReview: "NOT_REQUIRED",
    dataSafety: {
      externalNetworkCalled: false,
      inputPersisted: false,
      rawAudioPersisted: false,
      sensitiveTextLogged: false,
      credentialsSource: "none",
      allowedData: ["synthetic", "developer_authorized", "authorized_non_child"],
      notes: "Local attention provider consumes low-frequency browser descriptors only. Raw frames are not stored or sent."
    },
    fallback: {
      fallbackProviderIds: ["mock-attention"],
      fallbackMode: "mock"
    }
  };

  async observe(input: LocalAttentionInput): Promise<ProviderResult<AttentionObservation>> {
    const descriptor = input.frameDescriptor;
    const features = normalizeAttentionVisualFeatures({
      frameWidth: descriptor?.width ?? 160,
      frameHeight: descriptor?.height ?? 120,
      visualFeatures: descriptor?.visualFeatures,
      byteLength: descriptor?.byteLength
    });
    const observedAt = input.observedAt;
    const imageQuality = features.imageQuality;
    const confidence = features.confidence;
    const missingDevice = imageQuality === "unavailable";
    const lowQuality = imageQuality === "low_light" || imageQuality === "blurred" || imageQuality === "occluded";
    const qualityStatus = missingDevice ? "missing_device" : lowQuality || confidence < 0.5 ? "low_confidence" : "complete";

    return {
      ok: true,
      metadata: this.metadata,
      latencyMs: 0,
      data: {
        observationId: input.observationId,
        observationType: "attention",
        sessionId: input.sessionId,
        questionId: input.questionId,
        turnId: input.turnId,
        eventId: input.eventId,
        correlationId: input.correlationId ?? input.observationId,
        windowId: input.windowId,
        startedAt: observedAt,
        endedAt: observedAt,
        observedAt,
        source: input.source ?? "camera",
        provider: this.metadata.providerId ?? this.metadata.providerName,
        algorithm: {
          schemaVersion: "m5-behavior-v1",
          algorithmVersion: features.algorithmVersion,
          providerVersion: this.metadata.version
        },
        features: {
          kind: missingDevice ? "camera_unavailable" : features.faceCount > 1 ? "face_count" : "screen_orientation",
          facePresent: features.facePresent,
          faceCount: features.faceCount,
          headOrientation: features.headOrientation,
          roughlyFacingScreen: features.roughlyFacingScreen,
          facingScore: features.facingScore,
          durationMs: 1000,
          imageQuality,
          cameraAvailable: !missingDevice
        },
        confidence,
        dataQuality: {
          status: qualityStatus,
          providerStatus: qualityStatus === "complete" ? "ok" : "degraded",
          confidence,
          reasonCode: missingDevice ? "CAMERA_UNAVAILABLE" : lowQuality ? "IMAGE_QUALITY_LIMITED" : undefined
        },
        degraded: qualityStatus !== "complete",
        evidence: [
          {
            type: "provider_result",
            id: `${input.observationId}:local-provider`,
            sessionId: input.sessionId,
            questionId: input.questionId,
            turnId: input.turnId,
            eventId: input.eventId,
            windowId: input.windowId,
            provider: this.metadata.providerId ?? this.metadata.providerName,
            createdAt: observedAt,
            redacted: true
          }
        ],
        createdAt: observedAt
      },
      metrics: {
        processLatencyMs: 0,
        gpuUsed: false,
        hardwareAcceleration: "CPU"
      }
    };
  }
}
