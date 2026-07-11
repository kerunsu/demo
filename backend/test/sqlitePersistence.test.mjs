import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";
import "./testEnv.mjs";

const projectRoot = path.resolve(fileURLToPath(new URL("../..", import.meta.url)));

function uniqueImport(relativePath) {
  return import(`../dist/${relativePath}.js?restart=${Date.now()}-${Math.random()}`);
}

test("SQLite persistence restores sessions, events, behavior, assessments, and reports after restart", async () => {
  const tempDir = await mkdtemp(path.join(os.tmpdir(), "demo-sqlite-"));
  const dbPath = path.join(tempDir, "demo.sqlite3");
  process.env.DEMO_STORAGE_PROVIDER = "sqlite";
  process.env.DEMO_SQLITE_DB_PATH = dbPath;

  try {
    const lifecycle = await uniqueImport("services/sessionLifecycleService");
    const domainEvents = await uniqueImport("services/domainEventService");
    const behaviorRepoModule = await uniqueImport("services/behaviorObservationRepository");
    const reportService = await uniqueImport("services/reportService");

    const questions = [
      {
        id: "q1",
        prompt: "Pick the matching card",
        target: "card",
        options: [
          { id: "o1", label: "one" },
          { id: "o2", label: "two" }
        ],
        correctOptionId: "o1",
        hint: "try one",
        errorTypeOnWrong: "mismatch"
      }
    ];
    const session = lifecycle.createTrainingSession({
      childName: "SQLite Test",
      courseType: "matching",
      questions
    });
    session.questionStats[0].attempts = 1;
    session.questionStats[0].correct = true;
    session.questionStats[0].responseTimeMs = 800;
    session.correctAnswers = 1;
    session.responseTimes.push(800);
    lifecycle.completeSession(session);

    const event = domainEvents.publishDomainEvent({
      eventType: "ANSWER_EVALUATED",
      sessionId: session.sessionId,
      source: "backend",
      payload: {
        questionId: "q1",
        correct: true,
        nextAction: "FINISH_COURSE"
      }
    });

    const repository = new behaviorRepoModule.PersistentBehaviorObservationRepository();
    const createdAt = "2026-06-14T00:00:00.000Z";
    const evidence = [{
      type: "observation",
      id: "obs1",
      sessionId: session.sessionId,
      questionId: "q1",
      provider: "local-attention",
      createdAt,
      redacted: true
    }];
    repository.saveObservation({
      observationId: "obs1",
      observationType: "attention",
      sessionId: session.sessionId,
      questionId: "q1",
      correlationId: event.correlationId,
      eventId: event.eventId,
      startedAt: createdAt,
      endedAt: createdAt,
      observedAt: createdAt,
      source: "camera",
      provider: "local-attention",
      algorithm: {
        schemaVersion: "m5-behavior-v1",
        algorithmVersion: "local-attention-dev-v1",
        providerVersion: "local-dev"
      },
      features: {
        kind: "screen_orientation",
        roughlyFacingScreen: true,
        durationMs: 1000,
        facePresent: true,
        faceCount: 1,
        imageQuality: "good"
      },
      confidence: 0.8,
      dataQuality: { status: "complete", confidence: 0.8 },
      degraded: false,
      evidence,
      createdAt
    });
    repository.saveWindow({
      windowId: "window1",
      sessionId: session.sessionId,
      questionId: "q1",
      correlationId: event.correlationId,
      windowType: "question",
      startedAt: createdAt,
      endedAt: createdAt,
      inputEventIds: [event.eventId],
      observationIds: ["obs1"],
      algorithm: {
        schemaVersion: "m5-behavior-v1",
        algorithmVersion: "question-window-v1"
      },
      dataQuality: { status: "complete" },
      createdAt
    });
    repository.saveQuestionSummary({
      summaryId: `question-summary:${session.sessionId}:q1`,
      sessionId: session.sessionId,
      questionId: "q1",
      windowId: "window1",
      correlationId: event.correlationId,
      attention: {
        observedMs: 1000,
        screenOrientedMs: 1000,
        orientationInterruptedMs: 0,
        unavailableMs: 0,
        quality: { status: "complete" }
      },
      evidence,
      algorithm: {
        schemaVersion: "m5-behavior-v1",
        algorithmVersion: "question-behavior-aggregation-v1"
      },
      dataQuality: { status: "complete" },
      createdAt
    });
    repository.saveSessionSummary({
      summaryId: `session-summary:${session.sessionId}`,
      sessionId: session.sessionId,
      courseType: "matching",
      questionSummaryIds: [`question-summary:${session.sessionId}:q1`],
      attention: {
        totalObservedMs: 1000,
        screenOrientedRatio: 1,
        unavailableRatio: 0,
        quality: { status: "complete" }
      },
      evidence,
      algorithm: {
        schemaVersion: "m5-behavior-v1",
        algorithmVersion: "session-behavior-aggregation-v1"
      },
      dataQuality: { status: "complete" },
      environmentPending: ["real_robot_camera"],
      ownerRequiredBeforeScoring: ["formal_attention_thresholds"],
      createdAt
    });

    const generated = await reportService.generateReport(session.sessionId);
    assert.equal(generated.status, "READY");

    const restartedLifecycle = await uniqueImport("services/sessionLifecycleService");
    const restartedDomainEvents = await uniqueImport("services/domainEventService");
    const restartedAssessment = await uniqueImport("services/assessmentService");
    const restartedReportService = await uniqueImport("services/reportService");
    const restoredSession = restartedLifecycle.getSession(session.sessionId);
    const restoredEvents = restartedDomainEvents.getSessionEvents(session.sessionId);
    const restoredAssessment = restartedAssessment.getAssessment(session.sessionId);
    const restoredReport = restartedReportService.getReport(session.sessionId);

    assert.equal(restoredSession.state, "TRAINING_FINISHED");
    assert.equal(restoredEvents.some((item) => item.eventId === event.eventId), true);
    assert.equal(restoredAssessment.algorithm.algorithmVersion, "m6-deterministic-assessment-v1");
    assert.equal(restoredAssessment.algorithm.ruleVersion, "OWNER_REQUIRED_BEFORE_SCORING");
    assert.equal(restoredReport.sessionId, session.sessionId);
    assert.equal(restoredReport.expandedReport.exportBoundary.containsRawAudio, false);
    assert.equal(restoredReport.expandedReport.exportBoundary.containsRawVideo, false);

    const migration = spawnSync("python", [
      path.join(projectRoot, "tools", "sqlite-store", "sqlite_store.py"),
      "--db",
      dbPath,
      "list",
      "--table",
      "schema_migrations"
    ], { encoding: "utf8" });
    assert.equal(migration.status, 0, migration.stderr);
    assert.equal(JSON.parse(migration.stdout).data[0].version, 1);

    const dbBytes = await readFile(dbPath);
    const dbText = dbBytes.toString("utf8");
    assert.equal(dbText.includes("raw-audio-bytes"), false);
    assert.equal(dbText.includes("raw-video-frame"), false);
    assert.equal(dbText.includes("data:audio/"), false);
  } finally {
    await rm(tempDir, { recursive: true, force: true });
  }
});
