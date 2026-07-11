import {
  aggregateTurnAudioFeaturesFromPcm16,
  parseWavPcm16LE,
  SERVER_AUDIO_FEATURE_ALGORITHM_VERSION
} from "child-education-training-demo/shared/browser-audio-features";
import { behaviorObservationRepository } from "./behaviorFrameIngressService.js";
import { receiveBrowserAudioFeatures } from "./audioFeatureService.js";
import { transcodeToWav16kMono } from "./audioTranscodeService.js";

export async function persistMergedAudioFeaturesIfMissing(input: {
  sessionId: string;
  turnId: string;
  correlationId: string;
  audioBuffer: Buffer;
  mimeType: string;
  audioDurationMs: number;
}) {
  const existing = behaviorObservationRepository
    .listObservations(input.sessionId)
    .some(
      (observation) =>
        observation.observationType === "language" &&
        observation.turnId === input.turnId &&
        observation.features.kind === "audio_loudness_rms"
    );
  if (existing || input.audioBuffer.byteLength === 0) return { persisted: false as const, reason: "ALREADY_PRESENT_OR_EMPTY" };

  try {
    const wav = await transcodeToWav16kMono(input.audioBuffer, input.mimeType);
    const pcm = parseWavPcm16LE(wav);
    if (!pcm) return { persisted: false as const, reason: "PCM_PARSE_FAILED" };
    const features = aggregateTurnAudioFeaturesFromPcm16(
      pcm.samples,
      pcm.sampleRateHz,
      input.audioDurationMs > 0 ? input.audioDurationMs : Math.round((pcm.samples.length / pcm.sampleRateHz) * 1000)
    );
    receiveBrowserAudioFeatures({
      descriptor: {
        schemaVersion: "m5-audio-features-v1",
        sessionId: input.sessionId,
        turnId: input.turnId,
        correlationId: input.correlationId,
        observedAt: new Date().toISOString(),
        audioDurationMs: features.audioDurationMs,
        provider: "server-merged-audio",
        features: {
          loudnessRms: features.loudnessRms,
          loudnessDb: features.loudnessDb,
          speechRatio: features.speechRatio,
          clarityProxy: features.clarityProxy,
          sampleCount: features.sampleCount,
          algorithmVersion: SERVER_AUDIO_FEATURE_ALGORITHM_VERSION,
          degraded: features.degraded
        }
      }
    });
    return { persisted: true as const, reason: "MERGED_AUDIO_ANALYZED" };
  } catch {
    return { persisted: false as const, reason: "MERGED_AUDIO_ANALYZE_FAILED" };
  }
}
