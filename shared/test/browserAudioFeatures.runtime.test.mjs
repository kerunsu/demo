import assert from "node:assert/strict";
import test from "node:test";

import {
  aggregateTurnAudioFeatures,
  aggregateTurnAudioFeaturesFromPcm16,
  computeClarityProxy,
  computeZeroCrossingRate,
  rmsFromByteTimeDomain
} from "../dist/browserAudioFeatures.js";

function sineWaveBytes(amplitude, frequency, length = 256) {
  const samples = new Uint8Array(length);
  for (let index = 0; index < length; index += 1) {
    const value = 128 + Math.sin((index / length) * Math.PI * 2 * frequency) * 127 * amplitude;
    samples[index] = Math.max(0, Math.min(255, Math.round(value)));
  }
  return samples;
}

function flatSilence(length = 256) {
  return new Uint8Array(length).fill(128);
}

function noisySignal(length = 256) {
  const samples = new Uint8Array(length);
  for (let index = 0; index < length; index += 1) {
    samples[index] = index % 2 === 0 ? 200 : 56;
  }
  return samples;
}

test("browser audio features distinguish loud clear speech from quiet and noisy frames", () => {
  const loudClear = aggregateTurnAudioFeatures(
    Array.from({ length: 12 }, () => ({
      rms: rmsFromByteTimeDomain(sineWaveBytes(0.8, 4)),
      zcr: computeZeroCrossingRate(sineWaveBytes(0.8, 4))
    })),
    1200
  );
  const quiet = aggregateTurnAudioFeatures(
    Array.from({ length: 12 }, () => ({
      rms: rmsFromByteTimeDomain(flatSilence()),
      zcr: computeZeroCrossingRate(flatSilence())
    })),
    1200
  );
  const noisy = aggregateTurnAudioFeatures(
    Array.from({ length: 12 }, () => ({
      rms: rmsFromByteTimeDomain(noisySignal()),
      zcr: computeZeroCrossingRate(noisySignal())
    })),
    1200
  );

  assert.ok(loudClear.loudnessRms > quiet.loudnessRms);
  assert.ok(loudClear.speechRatio > quiet.speechRatio);
  assert.ok(loudClear.clarityProxy > noisy.clarityProxy);
  assert.equal(loudClear.degraded, false);
  assert.equal(quiet.degraded, true);
});

test("clarity proxy peaks near moderate zero-crossing rate", () => {
  assert.ok(computeClarityProxy(0.12) > computeClarityProxy(0.45));
  assert.ok(computeClarityProxy(0.12) > computeClarityProxy(0.01));
});

test("pcm16 aggregation produces loud vs quiet discrimination", () => {
  const sampleRateHz = 16000;
  const frameSize = 320;
  const loud = new Int16Array(frameSize * 12);
  const quiet = new Int16Array(frameSize * 12);
  for (let index = 0; index < loud.length; index += 1) {
    loud[index] = Math.round(Math.sin(index / 6) * 20000);
    quiet[index] = Math.round(Math.sin(index / 40) * 200);
  }
  const loudFeatures = aggregateTurnAudioFeaturesFromPcm16(loud, sampleRateHz, 1200);
  const quietFeatures = aggregateTurnAudioFeaturesFromPcm16(quiet, sampleRateHz, 1200);
  assert.ok(loudFeatures.loudnessRms > quietFeatures.loudnessRms);
});
