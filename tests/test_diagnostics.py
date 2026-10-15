"""Operational traces are bounded metadata, never copies of customer inputs."""
from contextlib import closing, redirect_stderr, redirect_stdout
import io
import json
import http.client
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import diagnostics as log
from app import PortalServer, Store
from domain import PortalError, SAMPLE
from integration import IntegrationWorker
from pipeline_review import approve
from support import SupportWorker, create_ticket

OWNER = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
REQUEST = "44444444-4444-4444-8444-444444444444"


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        log.initialize(self.db)

    def tearDown(self):
        self.db.close()

    def test_event_correlates_owner_project_request_and_server_revision(self):
        identifier = log.emit(self.db, "generation.queued", owner_id=OWNER,
                              project_id=PROJECT, request_id=REQUEST, revision=3,
                              status="queued", job_id="a" * 32)
        row = log.query(self.db)[0]
        self.assertRegex(identifier, log.UUID)
        self.assertEqual(row["event_id"], identifier)
        self.assertEqual(row["request_id"], REQUEST)
        self.assertEqual(row["project_id"], PROJECT)
        self.assertEqual(row["revision"], 3)
        self.assertEqual(row["job_id"], "a" * 32)
        self.assertNotIn("reason", row)

    def test_free_text_credentials_addresses_and_payload_fields_are_rejected(self):
        for extra in ("prompt", "payload", "password", "token", "cookie", "ip", "username", "error", "filename", "folder_url"):
            with self.subTest(extra=extra), self.assertRaises(TypeError):
                log.emit(self.db, "auth.login", **{extra: "private fictional text"})
        cases = ({"event": "a customer prompt"}, {"reason": "Bearer private-token"},
                 {"reason": "CUSTOMER_PRIVATE_TEXT"}, {"status": "client@example.invalid"},
                 {"owner_id": "username"}, {"project_id": "192.0.2.1"},
                 {"request_id": "session-secret"}, {"job_id": "../../private"},
                 {"attempt_key_hash": "192.0.2.1:username"}, {"category": "copy all secrets"})
        for fields in cases:
            values = {"event": "auth.login", **fields}
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                log.emit(self.db, **values)
        self.assertEqual(log.query(self.db), [])

    def test_numbers_and_enums_are_bounded_before_insertion(self):
        for fields in ({"revision": True}, {"revision": 0}, {"revision": 2**53},
                       {"elapsed_ms": -1}, {"elapsed_ms": "a prompt"},
                       {"http_status": 999}, {"http_status": False}, {"event": None}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                log.emit(self.db, **{"event": "auth.login", **fields})
        log.emit(self.db, "auth.login", status="denied", reason="INVALID_CREDENTIALS",
                 http_status=401, attempt_key_hash="a" * 64)
        self.assertEqual(len(log.query(self.db)), 1)

    def test_initialize_and_emit_do_not_commit_business_transaction(self):
        self.db.execute("CREATE TABLE business(value TEXT)")
        self.db.commit()
        self.db.execute("INSERT INTO business VALUES ('fictional')")
        log.initialize(self.db)
        log.emit(self.db, "project.created", project_id=PROJECT, status="succeeded")
        self.db.rollback()
        self.assertEqual(self.db.execute("SELECT count(*) FROM business").fetchone()[0], 0)
        self.assertEqual(log.query(self.db), [])

    def test_retention_prunes_expired_events_on_write_and_bounds_row_count(self):
        with patch.object(log.time, "time", return_value=100):
            log.emit(self.db, "auth.login", status="denied")
        with patch.object(log.time, "time", return_value=100 + log.RETENTION_SECONDS + 1):
            log.emit(self.db, "auth.login", status="accepted")
        self.assertEqual([r["status"] for r in log.query(self.db)], ["accepted"])
        with patch.object(log, "MAX_EVENTS", 3):
            with patch.object(log.time, "time", return_value=100 + log.RETENTION_SECONDS + 2):
                for index in range(5):
                    log.emit(self.db, "message.accepted", revision=index + 1)
        self.assertEqual([r["revision"] for r in log.query(self.db)], [5, 4, 3])

    def test_filters_and_maximum_limit_do_not_expose_other_requests(self):
        with patch.object(log.time, "time", return_value=1000):
            log.emit(self.db, "generation.queued", owner_id=OWNER, project_id=PROJECT,
                     request_id=REQUEST, status="queued", job_id="a" * 32)
        with patch.object(log.time, "time", return_value=1010):
            log.emit(self.db, "generation.completed", owner_id=OWNER, project_id=PROJECT,
                     request_id=REQUEST, status="completed", job_id="a" * 32)
            log.emit(self.db, "message.accepted", project_id=OTHER, status="accepted")
        self.assertEqual(len(log.query(self.db, project_id=PROJECT, request_id=REQUEST)), 2)
        rows = log.query(self.db, owner_id=OWNER, event="generation.completed", status="completed",
                         job_id="a" * 32, since=1005, limit=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"], "generation.completed")
        self.assertEqual(len(log.query(self.db, since=1005)), 2)
        for fields in ({"event": "' OR 1=1 --"}, {"project_id": "' OR 1=1 --"},
                       {"limit": 0}, {"limit": 501}, {"limit": None}, {"limit": True}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                log.query(self.db, **fields)

    def test_reader_does_not_create_write_prune_or_select_runtime_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "portal.sqlite3"
            with closing(sqlite3.connect(filename)) as db, db:
                log.initialize(db)
                with patch.object(log.time, "time", return_value=100):
                    log.emit(db, "message.accepted", project_id=PROJECT)
                db.execute("CREATE TABLE private_payloads(secret TEXT)")
                db.execute("INSERT INTO private_payloads VALUES ('PRIVATE CUSTOMER PROMPT')")
            before = filename.read_bytes()
            with log.readonly(filename) as db:
                rows = log.query(db)
                self.assertEqual(len(rows), 1)  # A read never applies time retention.
                self.assertNotIn("PRIVATE", json.dumps(rows))
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute("DELETE FROM diagnostics")
            self.assertEqual(before, filename.read_bytes())
            missing = Path(directory) / "not-created.sqlite3"
            with self.assertRaises(sqlite3.OperationalError), log.readonly(missing):
                pass
            self.assertFalse(missing.exists())
            old = Path(directory) / "legacy.sqlite3"
            sqlite3.connect(old).close()
            with log.readonly(old) as db:
                self.assertEqual(log.query(db), [])
            with closing(sqlite3.connect(old)) as db:
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='diagnostics'").fetchone())

    def test_cli_outputs_only_filtered_metadata_and_generic_access_error(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "portal.sqlite3"
            with closing(sqlite3.connect(filename)) as db, db:
                log.initialize(db)
                log.emit(db, "generation.failed", project_id=PROJECT, request_id=REQUEST,
                         reason="TIMEOUT", status="unknown")
                log.emit(db, "auth.login", status="accepted")
            output = io.StringIO()
            with redirect_stdout(output):
                result = log.main(["--db", str(filename), "--request-id", REQUEST,
                                   "--since", "1970-01-01T00:00:00Z", "--limit", "1"])
            self.assertEqual(result, 0)
            parsed = json.loads(output.getvalue())
            self.assertEqual(parsed["reason"], "TIMEOUT")
            self.assertTrue(parsed["createdAt"].endswith("+00:00"))
            errors = io.StringIO()
            with redirect_stderr(errors):
                result = log.main(["--db", str(Path(directory) / "missing.sqlite3")])
            self.assertEqual(result, 2)
            self.assertNotIn(directory, errors.getvalue())
            self.assertIn("operator access", errors.getvalue())

    def test_fixed_database_reader_cannot_override_path_or_use_cli_abbreviations(self):
        with tempfile.TemporaryDirectory() as directory:
            fixed = Path(directory) / "fixed.sqlite3"
            other = Path(directory) / "other.sqlite3"
            with closing(sqlite3.connect(fixed)) as db, db:
                log.initialize(db)
                log.emit(db, "generation.queued", project_id=PROJECT, status="queued")
            with closing(sqlite3.connect(other)) as db, db:
                log.initialize(db)
                log.emit(db, "support.sent", project_id=OTHER, status="sent")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(log.main(["--event", "generation.queued", "--limit", "1"], fixed_db=fixed), 0)
            row = json.loads(output.getvalue())
            self.assertEqual(row["project_id"], PROJECT)
            for arguments in (["--db", str(other)], ["--db=" + str(other)],
                              ["--d", str(other)], ["--fixed-db", str(other)],
                              ["--limit", "1", "--db", str(other)], ["--", "--db", str(other)],
                              ["--event", "generation.queued", "--project-i", OTHER]):
                with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()), patch.object(log, "readonly") as opened:
                    with self.assertRaises(SystemExit) as error:
                        log.main(arguments, fixed_db=fixed)
                    self.assertEqual(error.exception.code, 2)
                    opened.assert_not_called()
            help_output = io.StringIO()
            with redirect_stdout(help_output), self.assertRaises(SystemExit) as help_exit:
                log.main(["--help"], fixed_db=fixed)
            self.assertEqual(help_exit.exception.code, 0)
            self.assertNotIn("--db", help_output.getvalue())
            with closing(sqlite3.connect(fixed)) as db:
                self.assertEqual(len(log.query(db)), 1)



class DiagnosticHooksTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "portal.sqlite3")
        self.credentials = {"username": "fictional-client", "password": "private-fixture-password-123"}
        self.token, _ = self.store.auth({**self.credentials, "displayName": "Fictional"}, True, "192.0.2.14")
        self.owner = self.store.authenticate(self.token)["id"]
        self.project = self.store.create(self.owner, {"brief": SAMPLE})

    def tearDown(self):
        self.directory.cleanup()

    def rows(self, **filters):
        with self.store.connection() as db:
            return log.query(db, **filters)

    def current(self):
        return self.store.list_projects(self.owner)[0]

    def mutate(self, action):
        project = self.current()
        return self.store.update(self.owner, project["id"],
            {"revision": project["revision"], "action": action})

    def test_auth_failures_survive_rollback_rate_limit_and_logout_are_private(self):
        with self.assertRaises(PortalError):
            self.store.auth({**self.credentials, "displayName": "Other"}, True, "192.0.2.14")
        with self.assertRaises(PortalError):
            self.store.auth({**self.credentials, "password": "wrong-fixture-password"}, False, "192.0.2.14")
        with self.assertRaises(PortalError):
            self.store.auth({"username": "malformed", "password": "short"}, False, "192.0.2.14")
        for _ in range(10):
            with self.assertRaises(PortalError):
                self.store.auth({**self.credentials, "password": "wrong-fixture-password"}, False, "192.0.2.14")
        failures = self.rows(event="auth.login")
        self.assertTrue(any(row.get("reason") == "RATE_LIMIT" for row in failures))
        self.assertTrue(any(row.get("reason") == "INVALID_CREDENTIALS" for row in failures))
        self.assertTrue(any(row.get("reason") == "INVALID_INPUT" for row in failures))
        self.assertTrue(all("owner_id" not in row for row in failures))
        self.assertEqual(self.rows(event="auth.register", status="denied")[0]["reason"], "USERNAME_TAKEN")
        server = PortalServer(("127.0.0.1", 0), self.store, self.directory.name, "http://127.0.0.1")
        server.origin = "http://127.0.0.1:" + str(server.server_port)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            connection.request("POST", "/portal/api/auth/logout", body="{}", headers={
                "Origin": server.origin, "Content-Type": "application/json",
                "Cookie": "atelier_session=" + self.token})
            response = connection.getresponse()
            response.read()
            connection.close()
            self.assertEqual(response.status, 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(self.rows(event="auth.logout")[0]["owner_id"], self.owner)
        stored = json.dumps(self.rows())
        for value in (*self.credentials.values(), "wrong-fixture-password", "192.0.2.14", self.token, "Fictional"):
            self.assertNotIn(value, stored)

    def test_build_poll_and_operator_delivery_correlate_without_poll_spam(self):
        from test_pipeline import Transport
        class RepeatedPoll(Transport):
            polls = 0
            def __call__(self, body):
                if body["action"] == "poll_preview" and self.polls < 2:
                    self.polls += 1
                    return {**{key: body[key] for key in ("schemaVersion", "requestId", "projectId", "revision")},
                        "reply": "Construction fictive en cours.", "private": body["context"],
                        "pipeline": {"state": "BUILDING", "build": {"jobId": "a" * 32, "status": "running"}}}
                return super().__call__(body)
        transport = RepeatedPoll()
        self.store.integration = transport
        worker = IntegrationWorker(self.store, transport)
        source_url = "https://drive.google.com/drive/folders/fictionalfolder123"
        self.mutate({"type": "message", "text": "Le cahier privé est dans " + source_url})
        worker.once()
        queued = self.mutate({"type": "generate_preview"})
        request_id = queued["integration"]["requestId"]
        worker.once()
        for _ in range(3):
            with self.store.connection() as db:
                db.execute("UPDATE integration_jobs SET created=0 WHERE status='building'")
            worker.once()
        self.assertEqual(self.current()["pipeline"]["state"], "REVIEW_REQUIRED")
        # Fictional approval exercises the command; it is not a real operator action.
        approve(self.store, transport, self.project["id"], "a" * 32, "b" * 64, "c" * 64)
        rows = self.rows(request_id=request_id)
        expected = {"generation.queued", "generation.started", "generation.completed", "generation.reviewed"}
        self.assertEqual({row["event"] for row in rows}, expected)
        self.assertEqual(len(rows), 4)
        completed = next(row for row in rows if row["event"] == "generation.completed")
        self.assertEqual(completed["status"], "review_required")
        self.assertEqual(completed["job_id"], "a" * 32)
        self.assertEqual(len(self.rows(event="source.requested")), 1)
        self.assertEqual(len(self.rows(event="message.accepted")), 1)
        self.assertEqual(len(self.rows(event="project.created")), 1)
        stored = json.dumps(self.rows())
        for private in (source_url, "cahier privé", "Fictional source-bound prompt", "mockups.example.invalid"):
            self.assertNotIn(private, stored)

    def test_failed_business_write_does_not_leave_orphaned_queued_event(self):
        self.store.integration = True  # v1, no external transport is called.
        with self.store.connection() as db:
            db.execute("CREATE TRIGGER reject_project_write BEFORE UPDATE ON projects BEGIN SELECT RAISE(ABORT,'fixture rollback'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.mutate({"type": "generate_preview"})
        self.assertEqual(self.rows(event="generation.queued"), [])
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM integration_jobs").fetchone()[0], 0)
        self.assertEqual(self.current()["revision"], 1)

    def test_timeout_and_restart_keep_uncertain_build_distinct_from_failure(self):
        self.store.integration = True
        self.mutate({"type": "generate_preview"})
        def timeout(body):
            raise TimeoutError("PRIVATE raw upstream content and token")
        worker = IntegrationWorker(self.store, timeout)
        worker.once()
        failed = self.rows(event="generation.failed")[0]
        self.assertEqual((failed["status"], failed["reason"]), ("unknown", "TIMEOUT"))
        self.assertFalse(worker.once())
        self.mutate({"type": "generate_preview"})
        with self.store.connection() as db:
            db.execute("UPDATE integration_jobs SET status='running' WHERE status='queued'")
        worker.recover()
        self.assertEqual(self.rows(event="generation.failed")[0]["reason"], "RESTART_RECOVERY")
        self.assertEqual(self.rows(event="pipeline.recovered")[0]["status"], "unknown")
        self.assertNotIn("PRIVATE", json.dumps(self.rows()))

    def test_support_receipts_recovery_and_duplicate_submission_log_once(self):
        self.store.support = True
        project = self.current()
        raw = {"requestId": REQUEST, "revision": project["revision"], "email": "fixture@example.invalid",
               "message": "PRIVATE fictional support content", "consent": True}
        create_ticket(self.store, self.owner, project["id"], raw, "https://portal.invalid", "/portal/")
        create_ticket(self.store, self.owner, project["id"], raw, "https://portal.invalid", "/portal/")
        self.assertEqual(len(self.rows(event="support.queued")), 1)
        def sent(body):
            return {"schemaVersion": 1, "ticketId": body["ticketId"], "status": "sent", "messageId": "private-mail-receipt"}
        worker = SupportWorker(self.store, sent)
        worker.once()
        self.assertFalse(worker.once())
        self.assertEqual(len(self.rows(event="support.sent")), 1)
        with self.store.connection() as db:
            db.execute("UPDATE support_tickets SET created=created-61")
        raw = {**raw, "requestId": OTHER}
        create_ticket(self.store, self.owner, project["id"], raw, "https://portal.invalid", "/portal/")
        with self.store.connection() as db:
            db.execute("UPDATE support_tickets SET status='running' WHERE id=?", (OTHER,))
        worker.recover()
        worker.recover()
        self.assertEqual(len(self.rows(event="support.unknown")), 1)
        self.assertEqual(self.rows(event="support.unknown")[0]["reason"], "RESTART_RECOVERY")
        stored = json.dumps(self.rows())
        for private in ("fixture@example.invalid", "PRIVATE", "private-mail-receipt", "portal.invalid"):
            self.assertNotIn(private, stored)


if __name__ == "__main__":
    unittest.main()
