import type { ProviderResult, SttTranscript } from "child-education-training-demo/shared/providers";
import { getVoiceDegradationPlan } from "./voiceDegradationService.js";
import { providerMetricDefaults, recordVoiceMetric } from "./voiceObservabilityService.js";

const LOW_CONFIDENCE_THRESHOLD = 0.6;
const recentTranscriptBySession = new Map<string, { turnId: string; normalizedText: string }>();

export interface TranscriptNormalizationInput {
  sessionId: string;
  turnId: string;
  audioSegmentId: string;
  transcript: string;
  confidence: number;
  language: string;
  startedAtMs: number;
  endedAtMs: number;
}

export interface TranscriptNormalizationResult {
  transcript: SttTranscript;
  empty: boolean;
  duplicate: boolean;
}

export function normalizeTranscript(input: TranscriptNormalizationInput): TranscriptNormalizationResult {
  const redacted = redactTranscript(input.transcript);
  const text = collapseWhitespace(redacted.text);
  const previous = recentTranscriptBySession.get(input.sessionId);
  const duplicate = Boolean(text && previous?.normalizedText === text);
  if (text) {
    recentTranscriptBySession.set(input.sessionId, { turnId: input.turnId, normalizedText: text });
  }

  return {
    empty: text.length === 0,
    duplicate,
    transcript: {
      turnId: input.turnId,
      audioSegmentId: input.audioSegmentId,
      transcriptRedacted: text,
      confidence: input.confidence,
      language: input.language,
      startedAtMs: input.startedAtMs,
      endedAtMs: input.endedAtMs,
      isFinal: true,
      normalized: {
        text,
        duplicateOfTurnId: duplicate ? previous?.turnId : undefined,
        lowConfidence: input.confidence < LOW_CONFIDENCE_THRESHOLD,
        piiTypes: redacted.piiTypes
      }
    }
  };
}

export function applyTranscriptNormalization(
  sessionId: string,
  result: ProviderResult<SttTranscript>
): ProviderResult<SttTranscript> {
  if (!result.ok) return result;
  const normalized = normalizeTranscript({
    sessionId,
    turnId: result.data.turnId,
    audioSegmentId: result.data.audioSegmentId,
    transcript: result.data.transcriptRedacted,
    confidence: result.data.confidence,
    language: result.data.language,
    startedAtMs: result.data.startedAtMs,
    endedAtMs: result.data.endedAtMs
  });
  if (normalized.empty) {
    const degradation = getVoiceDegradationPlan("STT_EMPTY_RESULT");
    const emptyResult: ProviderResult<SttTranscript> = {
      ok: false,
      metadata: result.metadata,
      latencyMs: result.latencyMs,
      error: {
        code: "EMPTY_RESULT",
        message: "Final transcript is empty."
      },
      fallbackText: degradation.childSafeText,
      metrics: result.metrics
    };
    recordVoiceMetric({
      sessionId,
      turnId: result.data.turnId,
      correlationId: result.data.audioSegmentId,
      stage: "transcript_available",
      status: "degraded",
      errorCode: "EMPTY_RESULT",
      degradedProvider: true,
      ...providerMetricDefaults(result.metadata),
      audioDurationMs: result.metrics?.audioDurationMs,
      textForHash: normalized.transcript.transcriptRedacted,
      metadata: {
        audioSegmentId: result.data.audioSegmentId,
        empty: true,
        duplicate: false,
        lowConfidence: false,
        piiTypeCount: 0
      }
    });
    return emptyResult;
  }
  recordVoiceMetric({
    sessionId,
    turnId: normalized.transcript.turnId,
    correlationId: normalized.transcript.audioSegmentId,
    stage: "transcript_available",
    status: normalized.duplicate || normalized.transcript.normalized?.lowConfidence ? "degraded" : "success",
    errorCode: normalized.duplicate ? "DUPLICATE_TRANSCRIPT" : normalized.transcript.normalized?.lowConfidence ? "LOW_CONFIDENCE" : undefined,
    degradedProvider: normalized.duplicate || Boolean(normalized.transcript.normalized?.lowConfidence),
    ...providerMetricDefaults(result.metadata),
    audioDurationMs: result.metrics?.audioDurationMs,
    textForHash: normalized.transcript.transcriptRedacted,
    metadata: {
      audioSegmentId: normalized.transcript.audioSegmentId,
      empty: false,
      duplicate: normalized.duplicate,
      lowConfidence: normalized.transcript.normalized?.lowConfidence ?? false,
      piiTypeCount: normalized.transcript.normalized?.piiTypes.length ?? 0
    }
  });
  return {
    ...result,
    data: normalized.transcript
  };
}

export function resetTranscriptNormalizationForTests() {
  recentTranscriptBySession.clear();
}

function collapseWhitespace(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function redactTranscript(value: string): { text: string; piiTypes: string[] } {
  const piiTypes = new Set<string>();
  let text = value;
  text = text.replace(/\b1[3-9]\d{9}\b/g, () => {
    piiTypes.add("phone");
    return "[redacted-phone]";
  });
  text = text.replace(/\b\d{6,}\b/g, () => {
    piiTypes.add("number");
    return "[redacted-number]";
  });
  text = text.replace(/[\u4e00-\u9fa5A-Za-z0-9_-]{2,24}(学校|小学|幼儿园)/g, () => {
    piiTypes.add("school");
    return "[redacted-school]";
  });
  return { text, piiTypes: Array.from(piiTypes).sort() };
}
