import type { CameraFrameAck, CameraFrameSampleDescriptor } from "child-education-training-demo/shared/behavior-frames";
import type { AttentionObservation, EmotionObservation } from "child-education-training-demo/shared/behavior-observations";
import { MockAttentionObservationProvider } from "child-education-training-demo/shared/providers";
import { runtimeConfig } from "../config/runtime.js";
import { PersistentBehaviorObservationRepository } from "./behaviorObservationRepository.js";
import { LocalAttentionObservationProvider } from "./localAttentionObservationProvider.js";
import { LocalEmotionObservationProvider } from "./localEmotionObservationProvider.js";

type CameraFrameStreamRecord = {
  sessionId: string;
  streamId: string;
  expectedNextSequence: number;
  receivedFrameCount: number;
  droppedSequences: number[];
  descriptors: CameraFrameSampleDescriptor[];
};

const streams = new Map<string, CameraFrameStreamRecord>();
export const behaviorObservationRepository = new PersistentBehaviorObservationRepository();
const localAttentionProvider = new LocalAttentionObservationProvider();
const localEmotionProvider = new LocalEmotionObservationProvider();
const mockAttentionProvider = new MockAttentionObservationProvider("face_present");

function streamKey(sessionId: string, streamId: string) {
  return `${sessionId}:${streamId}`;
}

function missingSequences(expectedNextSequence: number, receivedSequence: number) {
  const missing: number[] = [];
  for (let sequence = expectedNextSequence; sequence < receivedSequence; sequence += 1) {
    missing.push(sequence);
  }
  return missing;
}

export async function receiveCameraFrameDescriptor(
  descriptor: CameraFrameSampleDescriptor,
  provider = runtimeConfig.attentionProvider === "local" ? localAttentionProvider : mockAttentionProvider
): Promise<{ ack: CameraFrameAck; observation: AttentionObservation; emotionObservation?: EmotionObservation }> {
  if (descriptor.rawFramePersisted !== false) {
    throw new Error("RAW_FRAME_PERSISTENCE_NOT_ALLOWED");
  }
  if (!descriptor.downsampled) {
    throw new Error("CAMERA_FRAME_MUST_BE_DOWNSAMPLED");
  }

  const key = streamKey(descriptor.sessionId, descriptor.streamId);
  const stream = streams.get(key) ?? {
    sessionId: descriptor.sessionId,
    streamId: descriptor.streamId,
    expectedNextSequence: 0,
    receivedFrameCount: 0,
    droppedSequences: [],
    descriptors: []
  };
  const newlyMissing = missingSequences(stream.expectedNextSequence, descriptor.sequence);
  const accepted = descriptor.sequence >= stream.expectedNextSequence;
  if (accepted) {
    stream.descriptors.push(descriptor);
    stream.receivedFrameCount += 1;
    stream.expectedNextSequence = descriptor.sequence + 1;
    stream.droppedSequences = Array.from(new Set([...stream.droppedSequences, ...newlyMissing])).sort((left, right) => left - right);
  }
  streams.set(key, stream);

  const observationInput = {
    observationId: `attention:${descriptor.frameId}`,
    sessionId: descriptor.sessionId,
    questionId: descriptor.questionId,
    correlationId: descriptor.correlationId,
    eventId: descriptor.frameId,
    source: "camera" as const,
    observedAt: descriptor.capturedAt,
    frameDescriptor: descriptor
  };
  const result = await provider.observe(observationInput);
  if (!result.ok) {
    throw new Error(result.error.code);
  }
  behaviorObservationRepository.saveObservation(result.data);

  let emotionObservation: EmotionObservation | undefined;
  if (runtimeConfig.emotionProvider === "local") {
    const emotionResult = await localEmotionProvider.observe({
      observationId: `emotion:${descriptor.frameId}`,
      sessionId: descriptor.sessionId,
      questionId: descriptor.questionId,
      correlationId: descriptor.correlationId,
      eventId: descriptor.frameId,
      source: "camera",
      observedAt: descriptor.capturedAt,
      frameDescriptor: descriptor
    });
    if (emotionResult.ok) {
      behaviorObservationRepository.saveObservation(emotionResult.data);
      emotionObservation = emotionResult.data;
    }
  }

  return {
    ack: {
      sessionId: descriptor.sessionId,
      streamId: descriptor.streamId,
      frameId: descriptor.frameId,
      sequence: descriptor.sequence,
      accepted,
      expectedNextSequence: stream.expectedNextSequence,
      receivedFrameCount: stream.receivedFrameCount,
      droppedSequences: stream.droppedSequences,
      rawFramePersisted: false
    },
    observation: result.data,
    emotionObservation
  };
}

export function getCameraFrameStreamSummary(sessionId: string, streamId: string) {
  const stream = streams.get(streamKey(sessionId, streamId));
  if (!stream) return null;
  return {
    sessionId: stream.sessionId,
    streamId: stream.streamId,
    expectedNextSequence: stream.expectedNextSequence,
    receivedFrameCount: stream.receivedFrameCount,
    droppedSequences: [...stream.droppedSequences],
    rawFramePersisted: false
  };
}

export function resetBehaviorFrameIngressForTests() {
  streams.clear();
  behaviorObservationRepository.reset();
}
