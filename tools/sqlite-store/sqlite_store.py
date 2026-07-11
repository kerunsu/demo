#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def connect(db_path: str):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def migrate(conn):
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version INTEGER PRIMARY KEY,
          applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
          session_id TEXT PRIMARY KEY,
          state TEXT NOT NULL,
          course_type TEXT NOT NULL,
          started_at TEXT NOT NULL,
          completed_at TEXT,
          payload_json TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domain_events (
          event_id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          event_type TEXT NOT NULL,
          timestamp TEXT NOT NULL,
          source TEXT NOT NULL,
          correlation_id TEXT,
          causation_id TEXT,
          persist INTEGER NOT NULL,
          payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_domain_events_session_time
          ON domain_events(session_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_domain_events_type
          ON domain_events(event_type);
        CREATE TABLE IF NOT EXISTS behavior_observations (
          observation_id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          observation_type TEXT NOT NULL,
          provider TEXT NOT NULL,
          algorithm_version TEXT,
          data_quality_status TEXT NOT NULL,
          created_at TEXT NOT NULL,
          payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_behavior_observations_session
          ON behavior_observations(session_id, created_at);
        CREATE TABLE IF NOT EXISTS behavior_windows (
          window_id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          created_at TEXT NOT NULL,
          payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS behavior_question_summaries (
          summary_id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          question_id TEXT NOT NULL,
          algorithm_version TEXT,
          created_at TEXT NOT NULL,
          payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_behavior_question_summaries_session
          ON behavior_question_summaries(session_id, question_id);
        CREATE TABLE IF NOT EXISTS behavior_session_summaries (
          summary_id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL UNIQUE,
          algorithm_version TEXT,
          created_at TEXT NOT NULL,
          payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS assessments (
          assessment_id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL UNIQUE,
          metric_version TEXT NOT NULL,
          algorithm_version TEXT NOT NULL,
          rule_version TEXT,
          created_at TEXT NOT NULL,
          payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reports (
          report_id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL UNIQUE,
          generated_at TEXT NOT NULL,
          version TEXT NOT NULL,
          payload_json TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION, now_iso()),
    )
    conn.commit()


def read_stdin_json():
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def json_payload(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def put_session(conn, payload):
    session = payload["payload"]
    conn.execute(
        """
        INSERT INTO sessions(session_id, state, course_type, started_at, completed_at, payload_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
          state=excluded.state,
          course_type=excluded.course_type,
          started_at=excluded.started_at,
          completed_at=excluded.completed_at,
          payload_json=excluded.payload_json,
          updated_at=excluded.updated_at
        """,
        (
            session["sessionId"],
            session["state"],
            session["courseType"],
            session["startedAt"],
            session.get("completedAt"),
            json_payload(session),
            now_iso(),
        ),
    )


def put_domain_event(conn, payload):
    event = payload["payload"]
    if not event.get("persist", True):
        return
    conn.execute(
        """
        INSERT OR IGNORE INTO domain_events(
          event_id, session_id, event_type, timestamp, source, correlation_id, causation_id, persist, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event["eventId"],
            event["sessionId"],
            event["eventType"],
            event["timestamp"],
            event["source"],
            event.get("correlationId"),
            event.get("causationId"),
            1 if event.get("persist", True) else 0,
            json_payload(event),
        ),
    )


def put_behavior_observation(conn, payload):
    record = payload["payload"]
    algorithm = record.get("algorithm") or {}
    data_quality = record.get("dataQuality") or {}
    conn.execute(
        """
        INSERT INTO behavior_observations(
          observation_id, session_id, observation_type, provider, algorithm_version, data_quality_status, created_at, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(observation_id) DO UPDATE SET
          provider=excluded.provider,
          algorithm_version=excluded.algorithm_version,
          data_quality_status=excluded.data_quality_status,
          payload_json=excluded.payload_json
        """,
        (
            record["observationId"],
            record["sessionId"],
            record["observationType"],
            record.get("provider", "unknown"),
            algorithm.get("algorithmVersion"),
            data_quality.get("status", "unknown"),
            record.get("observedAt", now_iso()),
            json_payload(record),
        ),
    )


def put_behavior_window(conn, payload):
    record = payload["payload"]
    conn.execute(
        """
        INSERT INTO behavior_windows(window_id, session_id, created_at, payload_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(window_id) DO UPDATE SET payload_json=excluded.payload_json
        """,
        (
            record["windowId"],
            record["sessionId"],
            record.get("createdAt", now_iso()),
            json_payload(record),
        ),
    )


def put_question_summary(conn, payload):
    record = payload["payload"]
    algorithm = record.get("algorithm") or {}
    conn.execute(
        """
        INSERT INTO behavior_question_summaries(
          summary_id, session_id, question_id, algorithm_version, created_at, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(summary_id) DO UPDATE SET
          algorithm_version=excluded.algorithm_version,
          payload_json=excluded.payload_json
        """,
        (
            record["summaryId"],
            record["sessionId"],
            record["questionId"],
            algorithm.get("algorithmVersion"),
            record.get("createdAt", now_iso()),
            json_payload(record),
        ),
    )


def put_session_summary(conn, payload):
    record = payload["payload"]
    algorithm = record.get("algorithm") or {}
    conn.execute(
        """
        INSERT INTO behavior_session_summaries(
          summary_id, session_id, algorithm_version, created_at, payload_json
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
          summary_id=excluded.summary_id,
          algorithm_version=excluded.algorithm_version,
          created_at=excluded.created_at,
          payload_json=excluded.payload_json
        """,
        (
            record["summaryId"],
            record["sessionId"],
            algorithm.get("algorithmVersion"),
            record.get("createdAt", now_iso()),
            json_payload(record),
        ),
    )


def put_assessment(conn, payload):
    record = payload["payload"]
    algorithm = record.get("algorithm") or {}
    conn.execute(
        """
        INSERT INTO assessments(
          assessment_id, session_id, metric_version, algorithm_version, rule_version, created_at, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
          assessment_id=excluded.assessment_id,
          metric_version=excluded.metric_version,
          algorithm_version=excluded.algorithm_version,
          rule_version=excluded.rule_version,
          created_at=excluded.created_at,
          payload_json=excluded.payload_json
        """,
        (
            record["assessmentId"],
            record["sessionId"],
            record["metricVersion"],
            algorithm.get("algorithmVersion", "unknown"),
            algorithm.get("ruleVersion"),
            record["createdAt"],
            json_payload(record),
        ),
    )


def put_report(conn, payload):
    record = payload["payload"]
    conn.execute(
        """
        INSERT INTO reports(report_id, session_id, generated_at, version, payload_json)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
          report_id=excluded.report_id,
          generated_at=excluded.generated_at,
          version=excluded.version,
          payload_json=excluded.payload_json
        """,
        (
            record["reportId"],
            record["sessionId"],
            record["generatedAt"],
            record["version"],
            json_payload(record),
        ),
    )


PUTTERS = {
    "sessions": put_session,
    "domain_events": put_domain_event,
    "behavior_observations": put_behavior_observation,
    "behavior_windows": put_behavior_window,
    "behavior_question_summaries": put_question_summary,
    "behavior_session_summaries": put_session_summary,
    "assessments": put_assessment,
    "reports": put_report,
}


GET_QUERIES = {
    "sessions": ("SELECT payload_json FROM sessions WHERE session_id = ?", "session_id"),
    "assessments": ("SELECT payload_json FROM assessments WHERE session_id = ?", "session_id"),
    "reports": ("SELECT payload_json FROM reports WHERE session_id = ?", "session_id"),
    "behavior_session_summaries": ("SELECT payload_json FROM behavior_session_summaries WHERE session_id = ?", "session_id"),
}


LIST_QUERIES = {
    "domain_events": ("SELECT payload_json FROM domain_events WHERE session_id = ? ORDER BY timestamp, event_id", "session_id"),
    "behavior_observations": ("SELECT payload_json FROM behavior_observations WHERE session_id = ? ORDER BY created_at, observation_id", "session_id"),
    "behavior_windows": ("SELECT payload_json FROM behavior_windows WHERE session_id = ? ORDER BY created_at, window_id", "session_id"),
    "behavior_question_summaries": ("SELECT payload_json FROM behavior_question_summaries WHERE session_id = ? ORDER BY created_at, summary_id", "session_id"),
    "assessments": ("SELECT payload_json FROM assessments ORDER BY created_at, assessment_id", None),
}


def cmd_migrate(args):
    with connect(args.db) as conn:
        migrate(conn)
    return {"ok": True, "schemaVersion": SCHEMA_VERSION}


def cmd_put(args):
    payload = read_stdin_json()
    if args.table not in PUTTERS:
        raise SystemExit(f"Unsupported table: {args.table}")
    with connect(args.db) as conn:
        migrate(conn)
        PUTTERS[args.table](conn, payload)
        conn.commit()
    return {"ok": True}


def cmd_get(args):
    if args.table not in GET_QUERIES:
        raise SystemExit(f"Unsupported table: {args.table}")
    query, key = GET_QUERIES[args.table]
    with connect(args.db) as conn:
        migrate(conn)
        row = conn.execute(query, (args.key,)).fetchone()
    return {"ok": True, "data": json.loads(row["payload_json"]) if row else None}


def cmd_list(args):
    if args.table == "schema_migrations":
        with connect(args.db) as conn:
            migrate(conn)
            rows = conn.execute("SELECT version, applied_at FROM schema_migrations ORDER BY version").fetchall()
        return {"ok": True, "data": [dict(row) for row in rows]}
    if args.table not in LIST_QUERIES:
        raise SystemExit(f"Unsupported table: {args.table}")
    query, key = LIST_QUERIES[args.table]
    params = (args.session_id,) if key else ()
    with connect(args.db) as conn:
        migrate(conn)
        rows = conn.execute(query, params).fetchall()
    return {"ok": True, "data": [json.loads(row["payload_json"]) for row in rows]}


def cmd_backup(args):
    with connect(args.db) as conn:
        migrate(conn)
    source = Path(args.db)
    target = Path(args.target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return {"ok": True, "backupPath": str(target)}


def cmd_delete_before(args):
    cutoff = args.before
    with connect(args.db) as conn:
        migrate(conn)
        session_ids = [
            row["session_id"]
            for row in conn.execute(
                "SELECT session_id FROM sessions WHERE updated_at < ? AND (completed_at IS NULL OR completed_at < ?)",
                (cutoff, cutoff),
            ).fetchall()
        ]
        for session_id in session_ids:
            for table in [
                "domain_events",
                "behavior_observations",
                "behavior_windows",
                "behavior_question_summaries",
                "behavior_session_summaries",
                "assessments",
                "reports",
                "sessions",
            ]:
                conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
        conn.commit()
    return {"ok": True, "deletedSessions": session_ids}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    put = sub.add_parser("put")
    put.add_argument("--table", required=True)
    get = sub.add_parser("get")
    get.add_argument("--table", required=True)
    get.add_argument("--key", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--table", required=True)
    listing.add_argument("--session-id")
    backup = sub.add_parser("backup")
    backup.add_argument("--target", required=True)
    delete = sub.add_parser("delete-before")
    delete.add_argument("--before", required=True)
    args = parser.parse_args()

    commands = {
        "migrate": cmd_migrate,
        "put": cmd_put,
        "get": cmd_get,
        "list": cmd_list,
        "backup": cmd_backup,
        "delete-before": cmd_delete_before,
    }
    result = commands[args.command](args)
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
