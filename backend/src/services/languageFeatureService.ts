import type {
  EvidenceReference,
  LanguageObservation
} from "child-education-training-demo/shared/behavior-observations";

const LOW_CONFIDENCE_THRESHOLD = 0.6;
const SENTENCE_SPLIT = /[。！？!?；;\n]+/u;
const WORD_SPLIT = /\s+/u;

export interface LanguageFeatureInput {
  observationId: string;
  sessionId: string;
  questionId?: string;
  turnId: string;
  eventId?: string;
  correlationId: string;
  windowId?: string;
  transcriptRedacted: string;
  confidence?: number;
  audioDurationMs?: number;
  responseStartedAt?: string;
  observedAt: string;
  promptCount?: number;
  duplicateOfTurnId?: string;
  evidence?: EvidenceReference[];
}

export function extractDeterministicLanguageFeatures(input: LanguageFeatureInput): LanguageObservation[] {
  const text = input.transcriptRedacted.trim();
  const transcriptLength = Array.from(text).length;
  const empty = transcriptLength === 0;
  const lowConfidence = (input.confidence ?? 1) < LOW_CONFIDENCE_THRESHOLD;
  const repeated = Boolean(input.duplicateOfTurnId);
  const baseQuality = empty ? "partial" : lowConfidence ? "low_confidence" : "complete";
  const providerStatus = empty || lowConfidence ? "degraded" : "ok";

  const observations: LanguageObservation[] = [
    createLanguageObservation(input, "speech_presence", !empty, {
      status: baseQuality,
      providerStatus,
      confidence: input.confidence
    }),
    createLanguageObservation(input, "transcript_length", transcriptLength, {
      status: baseQuality,
      providerStatus,
      confidence: input.confidence
    }),
    createLanguageObservation(input, "sentence_count", countSentences(text), {
      status: baseQuality,
      providerStatus,
      confidence: input.confidence
    }),
    createLanguageObservation(input, "empty_response", empty, {
      status: empty ? "partial" : "complete",
      providerStatus: empty ? "degraded" : "ok",
      confidence: input.confidence
    }),
    createLanguageObservation(input, "repeated_response", repeated, {
      status: repeated ? "partial" : "complete",
      providerStatus: repeated ? "degraded" : "ok",
      confidence: input.confidence
    }),
    createLanguageObservation(input, "stt_confidence", input.confidence ?? 0, {
      status: lowConfidence ? "low_confidence" : "complete",
      providerStatus: lowConfidence ? "degraded" : "ok",
      confidence: input.confidence
    })
  ];

  if (input.audioDurationMs !== undefined) {
    observations.push(
      createLanguageObservation(input, "audio_duration_ms", input.audioDurationMs, {
        status: "complete",
        providerStatus: "ok",
        confidence: input.confidence
      })
    );
  }

  if (input.promptCount !== undefined) {
    observations.push(
      createLanguageObservation(input, "prompt_count", input.promptCount, {
        status: "complete",
        providerStatus: "ok",
        confidence: input.confidence
      })
    );
  }

  return observations;
}

function createLanguageObservation(
  input: LanguageFeatureInput,
  kind: LanguageObservation["features"]["kind"],
  value: string | number | boolean,
  dataQuality: LanguageObservation["dataQuality"]
): LanguageObservation {
  const evidence = input.evidence ?? [
    {
      type: "transcript",
      id: `${input.turnId}:transcript`,
      sessionId: input.sessionId,
      questionId: input.questionId,
      turnId: input.turnId,
      eventId: input.eventId,
      windowId: input.windowId,
      createdAt: input.observedAt,
      redacted: true
    }
  ];

  return {
    observationId: `${input.observationId}:${kind}`,
    observationType: "language",
    sessionId: input.sessionId,
    questionId: input.questionId,
    turnId: input.turnId,
    eventId: input.eventId,
    correlationId: input.correlationId,
    windowId: input.windowId,
    startedAt: input.responseStartedAt ?? input.observedAt,
    endedAt: input.observedAt,
    observedAt: input.observedAt,
    source: "speech_pipeline",
    provider: "deterministic-language-feature-service",
    algorithm: {
      schemaVersion: "m5-behavior-v1",
      algorithmVersion: "deterministic-language-features-v1",
      ruleVersion: "deterministic-language-rules-v1"
    },
    features: {
      kind,
      value,
      audioDurationMs: input.audioDurationMs,
      transcriptLength: typeof value === "number" && kind === "transcript_length" ? value : undefined,
      sentenceCount: typeof value === "number" && kind === "sentence_count" ? value : undefined,
      sttConfidence: input.confidence,
      promptCount: input.promptCount
    },
    confidence: input.confidence ?? (kind === "empty_response" && value === true ? 0 : 1),
    dataQuality,
    degraded: dataQuality.status !== "complete",
    evidence,
    createdAt: input.observedAt
  };
}

function countSentences(text: string) {
  if (!text) return 0;
  if (text.includes(" ")) {
    return text.split(SENTENCE_SPLIT).filter(Boolean).length;
  }
  return text.split(SENTENCE_SPLIT).filter(Boolean).length || 1;
}

export function countWordsOrCharacters(text: string) {
  const trimmed = text.trim();
  if (!trimmed) return 0;
  if (trimmed.includes(" ")) {
    return trimmed.split(WORD_SPLIT).filter(Boolean).length;
  }
  return Array.from(trimmed).length;
}
