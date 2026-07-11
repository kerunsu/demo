import type {
  BehaviorObservation,
  ObservationWindow,
  QuestionBehaviorSummary,
  SessionBehaviorSummary
} from "child-education-training-demo/shared/behavior-observations";
import {
  listPersistentBehaviorObservations,
  listPersistentBehaviorWindows,
  listPersistentQuestionSummaries,
  loadPersistentSessionSummary,
  savePersistentBehaviorObservation,
  savePersistentBehaviorWindow,
  savePersistentQuestionSummary,
  savePersistentSessionSummary
} from "./sqlitePersistenceService.js";

export interface BehaviorObservationRepository {
  saveObservation(observation: BehaviorObservation): BehaviorObservation;
  listObservations(sessionId: string): BehaviorObservation[];
  saveWindow(window: ObservationWindow): ObservationWindow;
  listWindows(sessionId: string): ObservationWindow[];
  saveQuestionSummary(summary: QuestionBehaviorSummary): QuestionBehaviorSummary;
  listQuestionSummaries(sessionId: string): QuestionBehaviorSummary[];
  saveSessionSummary(summary: SessionBehaviorSummary): SessionBehaviorSummary;
  getSessionSummary(sessionId: string): SessionBehaviorSummary | undefined;
  reset(): void;
}

export interface InMemoryBehaviorObservationRepositoryOptions {
  maxObservationsPerSession?: number;
  maxWindowsPerSession?: number;
  maxQuestionSummariesPerSession?: number;
}

const DEFAULT_MAX_OBSERVATIONS = 500;
const DEFAULT_MAX_WINDOWS = 200;
const DEFAULT_MAX_QUESTION_SUMMARIES = 200;

export class InMemoryBehaviorObservationRepository implements BehaviorObservationRepository {
  private observationsBySession = new Map<string, BehaviorObservation[]>();
  private windowsBySession = new Map<string, ObservationWindow[]>();
  private questionSummariesBySession = new Map<string, QuestionBehaviorSummary[]>();
  private sessionSummaries = new Map<string, SessionBehaviorSummary>();

  private readonly maxObservationsPerSession: number;
  private readonly maxWindowsPerSession: number;
  private readonly maxQuestionSummariesPerSession: number;

  constructor(options: InMemoryBehaviorObservationRepositoryOptions = {}) {
    this.maxObservationsPerSession = options.maxObservationsPerSession ?? DEFAULT_MAX_OBSERVATIONS;
    this.maxWindowsPerSession = options.maxWindowsPerSession ?? DEFAULT_MAX_WINDOWS;
    this.maxQuestionSummariesPerSession = options.maxQuestionSummariesPerSession ?? DEFAULT_MAX_QUESTION_SUMMARIES;
  }

  saveObservation(observation: BehaviorObservation) {
    const records = this.observationsBySession.get(observation.sessionId) ?? [];
    const existingIndex = records.findIndex((record) => record.observationId === observation.observationId);
    if (existingIndex >= 0) {
      records[existingIndex] = observation;
    } else {
      records.push(observation);
    }
    trim(records, this.maxObservationsPerSession);
    this.observationsBySession.set(observation.sessionId, records);
    return observation;
  }

  listObservations(sessionId: string) {
    return [...(this.observationsBySession.get(sessionId) ?? [])];
  }

  saveWindow(window: ObservationWindow) {
    const records = this.windowsBySession.get(window.sessionId) ?? [];
    const existingIndex = records.findIndex((record) => record.windowId === window.windowId);
    if (existingIndex >= 0) {
      records[existingIndex] = window;
    } else {
      records.push(window);
    }
    trim(records, this.maxWindowsPerSession);
    this.windowsBySession.set(window.sessionId, records);
    return window;
  }

  listWindows(sessionId: string) {
    return [...(this.windowsBySession.get(sessionId) ?? [])];
  }

  saveQuestionSummary(summary: QuestionBehaviorSummary) {
    const records = this.questionSummariesBySession.get(summary.sessionId) ?? [];
    const existingIndex = records.findIndex((record) => record.summaryId === summary.summaryId);
    if (existingIndex >= 0) {
      records[existingIndex] = summary;
    } else {
      records.push(summary);
    }
    trim(records, this.maxQuestionSummariesPerSession);
    this.questionSummariesBySession.set(summary.sessionId, records);
    return summary;
  }

  listQuestionSummaries(sessionId: string) {
    return [...(this.questionSummariesBySession.get(sessionId) ?? [])];
  }

  saveSessionSummary(summary: SessionBehaviorSummary) {
    this.sessionSummaries.set(summary.sessionId, summary);
    return summary;
  }

  getSessionSummary(sessionId: string) {
    return this.sessionSummaries.get(sessionId);
  }

  reset() {
    this.observationsBySession.clear();
    this.windowsBySession.clear();
    this.questionSummariesBySession.clear();
    this.sessionSummaries.clear();
  }
}

export class PersistentBehaviorObservationRepository implements BehaviorObservationRepository {
  private readonly memory: InMemoryBehaviorObservationRepository;

  constructor(options: InMemoryBehaviorObservationRepositoryOptions = {}) {
    this.memory = new InMemoryBehaviorObservationRepository(options);
  }

  saveObservation(observation: BehaviorObservation) {
    this.memory.saveObservation(observation);
    savePersistentBehaviorObservation(observation);
    return observation;
  }

  listObservations(sessionId: string) {
    const cached = this.memory.listObservations(sessionId);
    if (cached.length > 0) return cached;
    const persisted = listPersistentBehaviorObservations(sessionId);
    for (const observation of persisted) this.memory.saveObservation(observation);
    return persisted;
  }

  saveWindow(window: ObservationWindow) {
    this.memory.saveWindow(window);
    savePersistentBehaviorWindow(window);
    return window;
  }

  listWindows(sessionId: string) {
    const cached = this.memory.listWindows(sessionId);
    if (cached.length > 0) return cached;
    const persisted = listPersistentBehaviorWindows(sessionId);
    for (const window of persisted) this.memory.saveWindow(window);
    return persisted;
  }

  saveQuestionSummary(summary: QuestionBehaviorSummary) {
    this.memory.saveQuestionSummary(summary);
    savePersistentQuestionSummary(summary);
    return summary;
  }

  listQuestionSummaries(sessionId: string) {
    const cached = this.memory.listQuestionSummaries(sessionId);
    if (cached.length > 0) return cached;
    const persisted = listPersistentQuestionSummaries(sessionId);
    for (const summary of persisted) this.memory.saveQuestionSummary(summary);
    return persisted;
  }

  saveSessionSummary(summary: SessionBehaviorSummary) {
    this.memory.saveSessionSummary(summary);
    savePersistentSessionSummary(summary);
    return summary;
  }

  getSessionSummary(sessionId: string) {
    const cached = this.memory.getSessionSummary(sessionId);
    if (cached) return cached;
    const persisted = loadPersistentSessionSummary(sessionId);
    if (persisted) this.memory.saveSessionSummary(persisted);
    return persisted;
  }

  reset() {
    this.memory.reset();
  }
}

function trim<T>(records: T[], max: number) {
  while (records.length > max) {
    records.shift();
  }
}
