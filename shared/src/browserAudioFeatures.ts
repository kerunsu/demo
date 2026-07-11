export const BROWSER_AUDIO_FEATURE_ALGORITHM_VERSION = "browser-audio-features-v1";
export const SPEECH_RMS_THRESHOLD = 0.02;
const OPTIMAL_ZCR = 0.12;
const ZCR_TOLERANCE = 0.15;

export interface AudioFrameMetric {
  rms: number;
  zcr: number;
}

export interface BrowserTurnAudioFeatures {
  loudnessRms: number;
  loudnessDb: number;
  speechRatio: number;
  clarityProxy: number;
  sampleCount: number;
  audioDurationMs: number;
  algorithmVersion: string;
  degraded: boolean;
}

export function rmsFromByteTimeDomain(samples: Uint8Array) {
  if (samples.length === 0) return 0;
  const sumSquares = samples.reduce((sum, sample) => {
    const centered = (sample - 128) / 128;
    return sum + centered * centered;
  }, 0);
  return Math.sqrt(sumSquares / samples.length);
}

export function computeZeroCrossingRate(samples: Uint8Array) {
  if (samples.length < 2) return 0;
  let crossings = 0;
  for (let index = 1; index < samples.length; index += 1) {
    const previous = samples[index - 1]! - 128;
    const current = samples[index]! - 128;
    if ((previous >= 0 && current < 0) || (previous < 0 && current >= 0)) {
      crossings += 1;
    }
  }
  return crossings / (samples.length - 1);
}

export function rmsToDecibels(rms: number) {
  const floor = 1e-4;
  return 20 * Math.log10(Math.max(rms, floor));
}

export function computeClarityProxy(meanZcr: number) {
  const distance = Math.abs(meanZcr - OPTIMAL_ZCR) / ZCR_TOLERANCE;
  return clamp01(1 - distance);
}

export function aggregateTurnAudioFeatures(frames: AudioFrameMetric[], audioDurationMs: number): BrowserTurnAudioFeatures {
  if (frames.length === 0) {
    return {
      loudnessRms: 0,
      loudnessDb: rmsToDecibels(0),
      speechRatio: 0,
      clarityProxy: 0,
      sampleCount: 0,
      audioDurationMs,
      algorithmVersion: BROWSER_AUDIO_FEATURE_ALGORITHM_VERSION,
      degraded: true
    };
  }

  const loudnessRms = round(frames.reduce((sum, frame) => sum + frame.rms, 0) / frames.length);
  const speechFrames = frames.filter((frame) => frame.rms >= SPEECH_RMS_THRESHOLD);
  const speechRatio = round(speechFrames.length / frames.length);
  const meanSpeechZcr =
    speechFrames.length > 0 ? speechFrames.reduce((sum, frame) => sum + frame.zcr, 0) / speechFrames.length : 0;
  const clarityProxy = round(computeClarityProxy(meanSpeechZcr));

  return {
    loudnessRms,
    loudnessDb: round(rmsToDecibels(loudnessRms)),
    speechRatio,
    clarityProxy,
    sampleCount: frames.length,
    audioDurationMs,
    algorithmVersion: BROWSER_AUDIO_FEATURE_ALGORITHM_VERSION,
    degraded: frames.length < 3 || speechRatio < 0.05
  };
}

function clamp01(value: number) {
  return Math.max(0, Math.min(1, value));
}

export const SERVER_AUDIO_FEATURE_ALGORITHM_VERSION = "server-merged-audio-features-v1";

export function parseWavPcm16LE(wav: Uint8Array) {
  const view = new DataView(wav.buffer, wav.byteOffset, wav.byteLength);
  const ascii = (offset: number, length: number) =>
    String.fromCharCode(...wav.subarray(offset, offset + length));
  if (wav.byteLength < 44 || ascii(0, 4) !== "RIFF" || ascii(8, 4) !== "WAVE") {
    return null;
  }
  let offset = 12;
  let sampleRateHz = 16000;
  let channels = 1;
  let bitsPerSample = 16;
  let dataOffset = -1;
  let dataSize = 0;
  while (offset + 8 <= wav.byteLength) {
    const chunkId = ascii(offset, 4);
    const chunkSize = view.getUint32(offset + 4, true);
    const chunkDataOffset = offset + 8;
    if (chunkId === "fmt ") {
      channels = view.getUint16(chunkDataOffset + 2, true);
      sampleRateHz = view.getUint32(chunkDataOffset + 4, true);
      bitsPerSample = view.getUint16(chunkDataOffset + 14, true);
    } else if (chunkId === "data") {
      dataOffset = chunkDataOffset;
      dataSize = chunkSize;
      break;
    }
    offset = chunkDataOffset + chunkSize + (chunkSize % 2);
  }
  if (dataOffset < 0 || bitsPerSample !== 16 || dataSize <= 0) return null;
  const sampleCount = Math.floor(dataSize / 2);
  const samples = new Int16Array(sampleCount);
  for (let index = 0; index < sampleCount; index += 1) {
    samples[index] = view.getInt16(dataOffset + index * 2, true);
  }
  if (channels > 1) {
    const mono = new Int16Array(Math.floor(sampleCount / channels));
    for (let index = 0; index < mono.length; index += 1) {
      mono[index] = samples[index * channels] ?? 0;
    }
    return { samples: mono, sampleRateHz };
  }
  return { samples, sampleRateHz };
}

export function aggregateTurnAudioFeaturesFromPcm16(
  samples: Int16Array,
  sampleRateHz: number,
  audioDurationMs: number,
  frameDurationMs = 20
) {
  const frameSize = Math.max(1, Math.round((sampleRateHz * frameDurationMs) / 1000));
  const frames: AudioFrameMetric[] = [];
  for (let offset = 0; offset < samples.length; offset += frameSize) {
    const frame = samples.subarray(offset, Math.min(samples.length, offset + frameSize));
    if (frame.length === 0) continue;
    let sumSquares = 0;
    let crossings = 0;
    for (let index = 0; index < frame.length; index += 1) {
      const normalized = frame[index]! / 32768;
      sumSquares += normalized * normalized;
      if (index > 0) {
        const previous = frame[index - 1]!;
        const current = frame[index]!;
        if ((previous >= 0 && current < 0) || (previous < 0 && current >= 0)) {
          crossings += 1;
        }
      }
    }
    frames.push({
      rms: Math.sqrt(sumSquares / frame.length),
      zcr: frame.length > 1 ? crossings / (frame.length - 1) : 0
    });
  }
  const features = aggregateTurnAudioFeatures(frames, audioDurationMs);
  return {
    ...features,
    algorithmVersion: SERVER_AUDIO_FEATURE_ALGORITHM_VERSION
  };
}

function round(value: number) {
  return Math.round(value * 1000) / 1000;
}
