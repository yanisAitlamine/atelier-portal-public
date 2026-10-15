"""Bounded operational metadata. No customer text, secrets or HTTP bodies.

Writers use their existing SQLite transaction; this module never commits it.
The operator reader opens a separate mode=ro connection and cannot create tables.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
import uuid

RETENTION_SECONDS = 30 * 24 * 3600
MAX_EVENTS = 50_000
MAX_READ = 500
EVENTS = frozenset({
    "auth.register", "auth.login", "auth.logout", "project.created",
    "message.accepted", "classification.decided", "source.requested",
    "source.scan", "generation.queued", "generation.started",
    "generation.completed", "generation.failed", "generation.reviewed",
    "pipeline.failed", "pipeline.recovered", "support.queued", "support.sent",
    "support.unknown",
})
STATUSES = frozenset({
    "accepted", "succeeded", "denied", "rate_limited", "queued", "running",
    "building", "completed", "failed", "unknown", "stale", "sent", "clean",
    "rejected", "review_required", "CONTINUE", "READY", "BLOCKED", "BUILDING",
    "REVIEW_REQUIRED", "STOPPED", "DELIVERED",
})
REASONS = frozenset({
    "INVALID_INPUT", "INVALID_CREDENTIALS", "USERNAME_TAKEN", "RATE_LIMIT",
    "AUTH_REQUIRED", "FORBIDDEN", "NOT_FOUND", "REVISION_CONFLICT",
    "TIMEOUT", "TRANSPORT_ERROR", "INVALID_RESPONSE", "BINDING_MISMATCH",
    "SOURCE_INCOMPLETE", "SOURCE_REJECTED", "CONTEXT_LIMIT", "INJECTION_RISK",
    "BUILD_UNCONFIRMED", "BUILD_FAILED", "REVIEW_PENDING", "REVIEW_REJECTED",
    "STALE_RESULT", "RESTART_RECOVERY", "RECEIPT_UNCONFIRMED", "INTERNAL_ERROR",
    "PIPELINE_BLOCKED", "NO_CONFIGURATION",
})
CATEGORIES = frozenset({
    "create_site", "content_edit", "design_refresh", "add_page", "advanced",
    "general", "clarification", "small_edit", "extra_page", "redesign",
})
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
HEX64 = re.compile(r"[0-9a-f]{64}")
JOB = re.compile(r"[0-9a-f]{32}")
FIELDS = ("owner_id", "project_id", "request_id", "job_id", "revision", "status",
          "reason", "category", "elapsed_ms", "http_status", "attempt_key_hash")
COLUMNS = ("sequence", "event_id", "created", "event", *FIELDS)
SCHEMA = """
CREATE TABLE IF NOT EXISTS diagnostics(
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,
 event_id TEXT UNIQUE NOT NULL, created INTEGER NOT NULL, event TEXT NOT NULL,
 owner_id TEXT, project_id TEXT, request_id TEXT, job_id TEXT, revision INTEGER,
 status TEXT, reason TEXT, category TEXT, elapsed_ms INTEGER, http_status INTEGER,
 attempt_key_hash TEXT)
"""


def initialize(db):
    """Add tables without committing a caller's business transaction."""
    db.execute(SCHEMA)
    db.execute("CREATE INDEX IF NOT EXISTS diagnostics_created ON diagnostics(created)")
    db.execute("CREATE INDEX IF NOT EXISTS diagnostics_request ON diagnostics(request_id,sequence)")
    db.execute("CREATE INDEX IF NOT EXISTS diagnostics_project ON diagnostics(project_id,sequence)")


def _choice(value, values, field):
    if value is not None and (not isinstance(value, str) or value not in values):
        raise ValueError("Invalid diagnostic " + field)


def _pattern(value, pattern, field):
    if value is not None and (not isinstance(value, str) or not pattern.fullmatch(value)):
        raise ValueError("Invalid diagnostic " + field)


def _integer(value, minimum, maximum, field):
    if value is not None and (type(value) is not int or not minimum <= value <= maximum):
        raise ValueError("Invalid diagnostic " + field)


def emit(db, event, *, owner_id=None, project_id=None, request_id=None, job_id=None,
         revision=None, status=None, reason=None, category=None, elapsed_ms=None,
         http_status=None, attempt_key_hash=None):
    """Insert one allowlisted event and prune inside the current transaction.

    Identifiers must come from server records, never a raw header or chat field.
    Reasons/categories are codes: passing an exception message fails validation.
    attempt_key_hash, when necessary, is the caller's SHA-256 pseudonym for the
    existing rate-limit key; never pass its username, address, password or token.
    """
    _choice(event, EVENTS, "event")
    if event is None:
        raise ValueError("Invalid diagnostic event")
    for field, value in (("owner_id", owner_id), ("project_id", project_id), ("request_id", request_id)):
        _pattern(value, UUID, field)
    _pattern(job_id, JOB, "job_id")
    _pattern(attempt_key_hash, HEX64, "attempt_key_hash")
    _choice(status, STATUSES, "status")
    _choice(reason, REASONS, "reason")
    _choice(category, CATEGORIES, "category")
    _integer(revision, 1, 2**53 - 1, "revision")
    _integer(elapsed_ms, 0, 24 * 3600 * 1000, "elapsed_ms")
    _integer(http_status, 100, 599, "http_status")
    event_id, created = str(uuid.uuid4()), int(time.time())
    values = (event_id, created, event, owner_id, project_id, request_id, job_id,
              revision, status, reason, category, elapsed_ms, http_status, attempt_key_hash)
    db.execute("INSERT INTO diagnostics(" + ",".join(COLUMNS[1:]) + ") VALUES (" +
               ",".join("?" for _ in values) + ")", values)
    db.execute("DELETE FROM diagnostics WHERE created<?", (created - RETENTION_SECONDS,))
    threshold = db.execute("SELECT sequence FROM diagnostics ORDER BY sequence DESC LIMIT 1 OFFSET ?",
                           (MAX_EVENTS - 1,)).fetchone()
    if threshold:
        db.execute("DELETE FROM diagnostics WHERE sequence<?", (threshold[0],))
    return event_id


@contextmanager
def readonly(filename):
    """Open only an existing DB; no migrations, retention or credential reads."""
    target = Path(filename).resolve()
    db = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        yield db
    finally:
        db.close()


def query(db, *, event=None, owner_id=None, project_id=None, request_id=None,
          job_id=None, status=None, since=None, limit=100):
    """Return bounded metadata, newest first. All filters are parameterized."""
    _choice(event, EVENTS, "event")
    _choice(status, STATUSES, "status")
    for field, value in (("owner_id", owner_id), ("project_id", project_id), ("request_id", request_id)):
        _pattern(value, UUID, field)
    _pattern(job_id, JOB, "job_id")
    _integer(since, 0, 2**53 - 1, "since")
    _integer(limit, 1, MAX_READ, "limit")
    if limit is None:
        raise ValueError("Invalid diagnostic limit")
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='diagnostics'").fetchone():
        return []
    clauses, params = [], []
    for field, value in (("event", event), ("owner_id", owner_id), ("project_id", project_id),
                         ("request_id", request_id), ("job_id", job_id), ("status", status)):
        if value is not None:
            clauses.append(field + "=?")
            params.append(value)
    if since is not None:
        clauses.append("created>=?")
        params.append(since)
    sql = "SELECT " + ",".join(COLUMNS) + " FROM diagnostics"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    rows = db.execute(sql + " ORDER BY sequence DESC LIMIT ?", (*params, limit))
    # The reader also allowlists output fields: it never SELECTs a payload column.
    return [{field: row[index] for index, field in enumerate(COLUMNS) if row[index] is not None}
            for row in rows]


def _since(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timezone required")
        seconds = int(parsed.timestamp())
        if seconds < 0:
            raise ValueError("Invalid date")
        return seconds
    except ValueError:
        raise argparse.ArgumentTypeError("Use ISO 8601 with timezone, e.g. 2026-10-15T12:00:00Z") from None


def main(argv=None, *, fixed_db=None):
    # The root-owned delegated reader fixes its one database in code. Its parser
    # must not accept --db (or abbreviations), even when combined with filters.
    parser = argparse.ArgumentParser(description="Read private portal operational metadata; no customer text.",
                                     allow_abbrev=False)
    if fixed_db is None:
        parser.add_argument("--db", required=True)
    parser.add_argument("--event", choices=sorted(EVENTS))
    parser.add_argument("--status", choices=sorted(STATUSES))
    for field in ("owner-id", "project-id", "request-id", "job-id"):
        parser.add_argument("--" + field)
    parser.add_argument("--since", type=_since)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        with readonly(fixed_db if fixed_db is not None else args.db) as db:
            rows = query(db, event=args.event, status=args.status, owner_id=args.owner_id,
                         project_id=args.project_id, request_id=args.request_id,
                         job_id=args.job_id, since=args.since, limit=args.limit)
        for row in rows:
            row["createdAt"] = datetime.fromtimestamp(row["created"], timezone.utc).isoformat()
            print(json.dumps(row, ensure_ascii=True, separators=(",", ":")))
        return 0
    except ValueError as error:
        # These exceptions contain only fixed validation labels, never values.
        print(str(error), file=sys.stderr)
        return 2
    except sqlite3.Error:
        print("Cannot read portal diagnostics. Check the database path and operator access.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
