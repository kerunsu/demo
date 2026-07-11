export const EXPRESSIVE_TEXT_WEIGHT = 0.5;
export const EXPRESSIVE_ACOUSTIC_WEIGHT = 0.5;

export function mapLoudnessRmsToScore(rms?: number) {
  if (typeof rms !== "number") return 50;
  const normalized = Math.max(0, Math.min(1, (rms - 0.01) / 0.22));
  return Math.round(normalized * 100);
}

export function mapSpeechRatioToScore(ratio?: number) {
  if (typeof ratio !== "number") return 50;
  return Math.round(Math.max(0, Math.min(1, ratio)) * 100);
}

export function mapClarityProxyToScore(proxy?: number) {
  if (typeof proxy !== "number") return 50;
  return Math.round(Math.max(0, Math.min(1, proxy)) * 100);
}

export function computeAcousticExpressiveScore(input: {
  averageLoudnessRms?: number;
  averageSpeechRatio?: number;
  averageClarityProxy?: number;
}) {
  const loudness = mapLoudnessRmsToScore(input.averageLoudnessRms);
  const speech = mapSpeechRatioToScore(input.averageSpeechRatio);
  const clarity = mapClarityProxyToScore(input.averageClarityProxy);
  return clamp(Math.round(0.4 * loudness + 0.3 * speech + 0.3 * clarity));
}

export function hasAcousticLanguageSignals(input: {
  averageLoudnessRms?: number;
  averageSpeechRatio?: number;
  averageClarityProxy?: number;
  audioFeatureTurnCount?: number;
}) {
  return (
    typeof input.averageLoudnessRms === "number" ||
    typeof input.averageSpeechRatio === "number" ||
    typeof input.averageClarityProxy === "number" ||
    (input.audioFeatureTurnCount ?? 0) > 0
  );
}

function clamp(value: number) {
  return Math.max(0, Math.min(100, value));
}
