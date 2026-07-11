import type { CameraFrameSampleDescriptor } from "child-education-training-demo/shared/behavior-frames";
import type { EmotionObservation } from "child-education-training-demo/shared/behavior-observations";
import {
  EMOTION_ALGORITHM_V1,
  normalizeEmotionDescriptorFeatures
} from "child-education-training-demo/shared/emotion-scoring";
import type {
  ProviderMetadata,
  ProviderResult
} from "child-education-training-demo/shared/providers";

export interface EmotionObservationInput {
  observationId: string;
  sessionId: string;
  questionId?: string;
  correlationId?: string;
  eventId?: string;
  source?: "camera";
  observedAt: string;
  frameDescriptor?: CameraFrameSampleDescriptor;
}

export class LocalEmotionObservationProvider {
  metadata: ProviderMetadata & { providerKind: "emotion_observation" } = {
    providerKind: "emotion_observation",
    providerName: "local-browser-face-emotion",
    providerId: "local-browser-face-emotion",
    providerType: "local",
    mode: "local",
    version: "final-b-local-emotion-v1",
    modelId: EMOTION_ALGORITHM_V1,
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
      notes: "Local emotion provider consumes browser blendshape descriptors only. Raw frames are not stored or sent."
    },
    fallback: {
      fallbackProviderIds: [],
      fallbackMode: "none"
    }
  };

  async observe(input: EmotionObservationInput): Promise<ProviderResult<EmotionObservation>> {
    const descriptor = input.frameDescriptor;
    const emotionFeatures = normalizeEmotionDescriptorFeatures(descriptor?.emotionFeatures);
    const observedAt = input.observedAt;

    if (!emotionFeatures) {
      const missingDevice = descriptor?.visualFeatures?.imageQuality === "unavailable";
      return {
        ok: true,
        metadata: this.metadata,
        latencyMs: 0,
        data: {
          observationId: input.observationId,
          observationType: "emotion",
          sessionId: input.sessionId,
          questionId: input.questionId,
          eventId: input.eventId,
          correlationId: input.correlationId ?? input.observationId,
          startedAt: observedAt,
          endedAt: observedAt,
          observedAt,
          source: input.source ?? "camera",
          provider: this.metadata.providerId ?? this.metadata.providerName,
          algorithm: {
            schemaVersion: "m5-behavior-v1",
            algorithmVersion: EMOTION_ALGORITHM_V1,
            providerVersion: this.metadata.version
          },
          features: {
            kind: missingDevice ? "emotion_unavailable" : "face_absent",
            facePresent: false,
            durationMs: 1000
          },
          confidence: 0.2,
          dataQuality: {
            status: missingDevice ? "missing_device" : "insufficient",
            providerStatus: "degraded",
            confidence: 0.2,
            reasonCode: missingDevice ? "CAMERA_UNAVAILABLE" : "FACE_OR_BLENDSHAPE_MISSING"
          },
          degraded: true,
          evidence: [
            {
              type: "provider_result",
              id: `${input.observationId}:local-emotion-provider`,
              sessionId: input.sessionId,
              questionId: input.questionId,
              eventId: input.eventId,
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

    const qualityStatus = emotionFeatures.degraded || emotionFeatures.confidence < 0.45 ? "low_confidence" : "complete";
    return {
      ok: true,
      metadata: this.metadata,
      latencyMs: 0,
      data: {
        observationId: input.observationId,
        observationType: "emotion",
        sessionId: input.sessionId,
        questionId: input.questionId,
        eventId: input.eventId,
        correlationId: input.correlationId ?? input.observationId,
        startedAt: observedAt,
        endedAt: observedAt,
        observedAt,
        source: input.source ?? "camera",
        provider: this.metadata.providerId ?? this.metadata.providerName,
        algorithm: {
          schemaVersion: "m5-behavior-v1",
          algorithmVersion: emotionFeatures.algorithmVersion,
          providerVersion: this.metadata.version,
          modelVersion: EMOTION_ALGORITHM_V1
        },
        features: {
          kind: "frame_emotion_scores",
          positiveScore: emotionFeatures.positiveScore,
          focusedScore: emotionFeatures.focusedScore,
          frustratedScore: emotionFeatures.frustratedScore,
          facePresent: true,
          durationMs: 1000
        },
        confidence: emotionFeatures.confidence,
        dataQuality: {
          status: qualityStatus,
          providerStatus: qualityStatus === "complete" ? "ok" : "degraded",
          confidence: emotionFeatures.confidence,
          reasonCode: qualityStatus === "complete" ? undefined : "LOW_BLENDSHAPE_CONFIDENCE"
        },
        degraded: qualityStatus !== "complete",
        evidence: [
          {
            type: "provider_result",
            id: `${input.observationId}:local-emotion-provider`,
            sessionId: input.sessionId,
            questionId: input.questionId,
            eventId: input.eventId,
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
