import { spawnSync } from "node:child_process";
import path from "node:path";
import type { DomainEvent } from "child-education-training-demo/shared/domain-events";
import type {
  BehaviorObservation,
  ObservationWindow,
  QuestionBehaviorSummary,
  SessionBehaviorSummary
} from "child-education-training-demo/shared/behavior-observations";
import type { DeterministicAssessmentResult } from "child-education-training-demo/shared/assessments";
import type { Session, TrainingReport } from "../types.js";

export const SQLITE_SCHEMA_VERSION = 1;

type PersistableTable =
  | "sessions"
  | "domain_events"
  | "behavior_observations"
  | "behavior_windows"
  | "behavior_question_summaries"
  | "behavior_session_summaries"
  | "assessments"
  | "reports";

type JsonResult<T> = {
  ok: boolean;
  data?: T;
  schemaVersion?: number;
};

type PendingPut = {
  table: PersistableTable;
  payload: unknown;
};

const pendingPuts: PendingPut[] = [];
let drainTimer: NodeJS.Timeout | null = null;
let draining = false;

function projectRoot() {
  const cwd = process.cwd();
  return path.basename(cwd).toLowerCase() === "backend" ? path.resolve(cwd, "..") : cwd;
}

function sqliteScriptPath() {
  return path.join(projectRoot(), "tools", "sqlite-store", "sqlite_store.py");
}

function defaultDbPath() {
  return path.join(projectRoot(), ".runtime", "demo.sqlite3");
}

function pythonCommand() {
  return process.env.PYTHON ?? process.env.PYTHON_EXE ?? "python";
}

export function getSqliteDbPath() {
  return process.env.DEMO_SQLITE_DB_PATH ?? process.env.SQLITE_DB_PATH ?? defaultDbPath();
}

export function isSqlitePersistenceEnabled() {
  return (process.env.DEMO_STORAGE_PROVIDER ?? "sqlite") === "sqlite";
}

function runSqlite<T>(args: string[], input?: unknown): JsonResult<T> {
  if (!isSqlitePersistenceEnabled()) {
    return { ok: false };
  }
  const result = spawnSync(
    pythonCommand(),
    [sqliteScriptPath(), "--db", getSqliteDbPath(), ...args],
    {
      encoding: "utf8",
      input: input === undefined ? undefined : JSON.stringify(input)
    }
  );
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(result.stderr.trim() || `SQLite persistence command failed: ${args.join(" ")}`);
  }
  return JSON.parse(result.stdout || "{}") as JsonResult<T>;
}

function runSqlitePut(table: PersistableTable, payload: unknown) {
  runSqlite(["put", "--table", table], { payload });
}

function schedulePendingDrain() {
  if (drainTimer || !isSqlitePersistenceEnabled()) return;
  drainTimer = setTimeout(() => {
    drainTimer = null;
    flushPendingSqliteWrites();
  }, 250);
  drainTimer.unref();
}

export function flushPendingSqliteWrites() {
  if (!isSqlitePersistenceEnabled() || draining) return;
  if (drainTimer) {
    clearTimeout(drainTimer);
    drainTimer = null;
  }
  draining = true;
  try {
    while (pendingPuts.length > 0) {
      const next = pendingPuts.shift();
      if (!next) continue;
      runSqlitePut(next.table, next.payload);
    }
  } finally {
    draining = false;
  }
}

export function migrateSqlitePersistence() {
  flushPendingSqliteWrites();
  return runSqlite("migrate".split(" "));
}

function put(table: PersistableTable, payload: unknown) {
  if (!isSqlitePersistenceEnabled()) return;
  pendingPuts.push({ table, payload });
  schedulePendingDrain();
}

function get<T>(table: string, key: string) {
  flushPendingSqliteWrites();
  return runSqlite<T>(["get", "--table", table, "--key", key]).data;
}

function list<T>(table: string, sessionId?: string) {
  flushPendingSqliteWrites();
  const args = ["list", "--table", table];
  if (sessionId) args.push("--session-id", sessionId);
  return runSqlite<T[]>(args).data ?? [];
}

process.once("beforeExit", () => {
  flushPendingSqliteWrites();
});

export function savePersistentSession(session: Session) {
  put("sessions", session);
}

export function loadPersistentSession(sessionId: string) {
  return get<Session>("sessions", sessionId);
}

export function savePersistentDomainEvent(event: DomainEvent) {
  put("domain_events", event);
}

export function listPersistentDomainEvents(sessionId: string) {
  return list<DomainEvent>("domain_events", sessionId);
}

export function savePersistentBehaviorObservation(observation: BehaviorObservation) {
  put("behavior_observations", observation);
}

export function listPersistentBehaviorObservations(sessionId: string) {
  return list<BehaviorObservation>("behavior_observations", sessionId);
}

export function savePersistentBehaviorWindow(window: ObservationWindow) {
  put("behavior_windows", window);
}

export function listPersistentBehaviorWindows(sessionId: string) {
  return list<ObservationWindow>("behavior_windows", sessionId);
}

export function savePersistentQuestionSummary(summary: QuestionBehaviorSummary) {
  put("behavior_question_summaries", summary);
}

export function listPersistentQuestionSummaries(sessionId: string) {
  return list<QuestionBehaviorSummary>("behavior_question_summaries", sessionId);
}

export function savePersistentSessionSummary(summary: SessionBehaviorSummary) {
  put("behavior_session_summaries", summary);
}

export function loadPersistentSessionSummary(sessionId: string) {
  return get<SessionBehaviorSummary>("behavior_session_summaries", sessionId);
}

export function savePersistentAssessment(assessment: DeterministicAssessmentResult) {
  put("assessments", assessment);
}

export function loadPersistentAssessment(sessionId: string) {
  return get<DeterministicAssessmentResult>("assessments", sessionId);
}

export function listPersistentAssessments() {
  return list<DeterministicAssessmentResult>("assessments");
}

export function savePersistentReport(report: TrainingReport) {
  put("reports", report);
}

export function loadPersistentReport(sessionId: string) {
  return get<TrainingReport>("reports", sessionId);
}
