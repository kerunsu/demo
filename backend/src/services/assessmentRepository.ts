import type { DeterministicAssessmentResult } from "child-education-training-demo/shared/assessments";
import {
  listPersistentAssessments,
  loadPersistentAssessment,
  savePersistentAssessment
} from "./sqlitePersistenceService.js";

export interface AssessmentRepository {
  saveAssessment(assessment: DeterministicAssessmentResult): DeterministicAssessmentResult;
  getAssessment(sessionId: string): DeterministicAssessmentResult | undefined;
  listAssessments(): DeterministicAssessmentResult[];
  reset(): void;
}

export class InMemoryAssessmentRepository implements AssessmentRepository {
  private readonly assessmentsBySession = new Map<string, DeterministicAssessmentResult>();

  saveAssessment(assessment: DeterministicAssessmentResult) {
    this.assessmentsBySession.set(assessment.sessionId, assessment);
    return assessment;
  }

  getAssessment(sessionId: string) {
    return this.assessmentsBySession.get(sessionId);
  }

  listAssessments() {
    return [...this.assessmentsBySession.values()];
  }

  reset() {
    this.assessmentsBySession.clear();
  }
}

export class PersistentAssessmentRepository implements AssessmentRepository {
  private readonly memory = new InMemoryAssessmentRepository();

  saveAssessment(assessment: DeterministicAssessmentResult) {
    this.memory.saveAssessment(assessment);
    savePersistentAssessment(assessment);
    return assessment;
  }

  getAssessment(sessionId: string) {
    const cached = this.memory.getAssessment(sessionId);
    if (cached) return cached;
    const persisted = loadPersistentAssessment(sessionId);
    if (persisted) this.memory.saveAssessment(persisted);
    return persisted;
  }

  listAssessments() {
    const persisted = listPersistentAssessments();
    for (const assessment of persisted) {
      this.memory.saveAssessment(assessment);
    }
    const byId = new Map([
      ...persisted.map((assessment) => [assessment.assessmentId, assessment] as const),
      ...this.memory.listAssessments().map((assessment) => [assessment.assessmentId, assessment] as const)
    ]);
    return [...byId.values()];
  }

  reset() {
    this.memory.reset();
  }
}

export const assessmentRepository = new PersistentAssessmentRepository();
