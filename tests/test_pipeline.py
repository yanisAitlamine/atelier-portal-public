"""Web pipeline HTTP journeys with fictional sources and no external effects."""
import copy
import base64
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from app import Store, PortalServer
from domain import SAMPLE, PortalError
from integration import IntegrationWorker, initialize
from pipeline_review import approve
from e2e_portal import Client
import pipeline
from support import create_ticket, SupportWorker


class Transport:
    protocol = 2
    drive_account = "reader@fixture.example"
    def __init__(self):
        self.calls = []
        self.mode = "ready"
    def __call__(self, body):
        self.calls.append(copy.deepcopy(body))
        if self.mode == "timeout":
            raise TimeoutError("Fictional transport interruption")
        public = {"state": "READY", "questions": [], "missingFields": [], "facts": []}
        private = {"analysis": {"context": {"source": "fictional"}}, "prompt": "Fictional source-bound prompt"}
        reply = "Le brief fictif est prêt à être relu."
        if body["action"] == "generate_preview":
            public = {"state": "BUILDING", "build": {"jobId": "a" * 32, "status": "queued"}}
            private = {**body["context"], "buildJob": {"jobId": "a" * 32, "revision": "b" * 64}}
            reply = "Construction fictive en cours."
        elif body["action"] == "poll_preview":
            public = {"state": "REVIEW_REQUIRED", "build": {"jobId": "a" * 32, "status": "completed_review_required"}}
            private = {**body["context"], "buildProof": {"job_id": "a" * 32, "revision": "b" * 64,
                "project_id": "web_" + body["projectId"], "state": "completed_review_required",
                "proof_status": "proof_verified", "artifact_sha256": "c" * 64,
                "preview_url": "https://mockups.example.invalid/maquettes/" + "a" * 32 + "/index.html"}}
            reply = "Maquette fictive en attente de validation."
        elif self.mode == "incomplete":
            public = {"state": "BLOCKED", "questions": [], "missingFields": [], "reasonCodes": ["DOCUMENT_PAGE_COVERAGE_INCOMPLETE"]}
            private = {}
            reply = "Les sources fictives sont incomplètes. Aucune construction ne sera lancée."
        result = {**{k: body[k] for k in ("schemaVersion", "requestId", "projectId", "revision")},
            "reply": reply, "pipeline": public, "private": private}
        if self.mode == "wrong_project":
            result["projectId"] = "00000000-0000-0000-0000-000000000000"
        return result


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "portal.sqlite3")
        self.transport = Transport()
        self.store.integration = self.transport
        self.worker = IntegrationWorker(self.store, self.transport)
        self.server = PortalServer(("127.0.0.1", 0), self.store,
            Path(__file__).resolve().parents[1] / "dist", "http://127.0.0.1:1")
        self.server.origin = "http://127.0.0.1:" + str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = Client(self.server.origin + "/portal/")
        self.client.register()
        self.other = Client(self.server.origin + "/portal/")
        self.other.register()
        self.project = self.client.call("/api/projects", "POST", {"brief": SAMPLE}, expected=201)[0]["project"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def current(self):
        return next(p for p in self.client.projects() if p["id"] == self.project["id"])

    def mutate(self, action, expected=200):
        p = self.current()
        return self.client.call("/api/projects/" + p["id"], "PATCH", {"revision": p["revision"], "action": action}, expected=expected)[0]

    def ready(self):
        self.mutate({"type": "message", "text": "Voici le brief fictif, sans paiement."})
        self.worker.once()
        self.assertEqual(self.current()["pipeline"]["state"], "READY")

    def test_full_http_journey_sources_analysis_build_poll_and_operator_delivery(self):
        capabilities = self.client.call("/api/pipeline")[0]
        self.assertEqual(capabilities, {"available": True, "driveAccount": self.transport.drive_account})
        self.mutate({"type": "set_sources", "folderUrl": "https://drive.google.com/drive/folders/fictionalfolder123", "consent": True})
        self.worker.once()
        p = self.current()
        self.assertEqual(p["pipeline"]["state"], "READY")
        self.assertNotIn("private", json.dumps(p))
        self.assertNotIn("analysis", p["pipeline"])
        self.assertEqual(self.transport.calls[-1]["source"]["messageId"], next(m["id"] for m in p["messages"] if m["role"] == "user"))
        self.mutate({"type": "generate_preview"})
        self.worker.once()
        p = self.current()
        self.assertEqual(p["integration"]["status"], "building")
        self.assertIsNone(p["preview"])
        with self.store.connection() as db:
            db.execute("UPDATE integration_jobs SET created=0 WHERE status='building'")
        self.worker.once()
        p = self.current()
        self.assertEqual(p["pipeline"]["state"], "REVIEW_REQUIRED")
        self.assertNotIn("test.syscom", json.dumps(p))
        with self.store.connection() as db:
            db.execute("INSERT INTO preview_artifacts VALUES (?,?,?,?,?)", (p["id"], 1, "OLD HTML", "d" * 64, "old-request"))
        # This exercises the operator command with a test double, not a real approval.
        approve(self.store, self.transport, p["id"], "a" * 32, "b" * 64, "c" * 64)
        p = self.current()
        self.assertEqual(p["pipeline"]["state"], "DELIVERED")
        self.assertEqual(p["preview"]["sha256"], "c" * 64)
        self.assertEqual(p["preview"]["version"], 2)
        self.assertIsNone(p["preview"]["approvalAt"])
        self.store.support = True
        with self.store.connection() as db:
            owner = db.execute("SELECT owner_id FROM projects WHERE id=?", (p["id"],)).fetchone()[0]
        calls = []
        create_ticket(self.store, owner, p["id"], {"requestId": "99999999-9999-4999-8999-999999999999", "revision": p["revision"],
            "email": "client@fixture.example", "message": "Demande fictive de suivi de cette maquette.", "consent": True}, self.server.origin, "/portal/")
        SupportWorker(self.store, lambda body: calls.append(body) or {"schemaVersion":1,"ticketId":body["ticketId"],"status":"sent","messageId":"fixture-receipt"}).once()
        snapshot = json.loads(base64.b64decode(calls[0]["attachments"][0]["data"]))
        self.assertEqual(snapshot["previewUrl"], p["preview"]["externalUrl"])
        self.assertEqual(snapshot["previewSha256"], "c" * 64)
        self.assertEqual(len(calls[0]["attachments"]), 1)
        self.mutate({"type": "approve_preview", "previewVersion": p["preview"]["version"]})
        self.assertEqual(self.current()["preview"]["status"], "approved_pending_connection")
        self.assertEqual(len([c for c in self.transport.calls if c["action"] == "generate_preview"]), 1)

    def test_another_account_cannot_change_sources_or_fetch_private_project(self):
        self.other.call("/api/projects/" + self.project["id"], "PATCH", {"revision": 1,
            "action": {"type": "set_sources", "folderUrl": "https://drive.google.com/drive/folders/fictionalfolder123", "consent": True}}, expected=404)
        self.assertEqual(self.transport.calls, [])

    def test_preview_feedback_reanalyzes_before_another_generation(self):
        self.ready()
        p = self.current()
        with self.store.connection() as db:
            p["preview"] = {"version": 1, "status": "awaiting_review", "approvalAt": None, "feedback": ""}
            p["pipeline"]["state"] = "DELIVERED"
            db.execute("UPDATE projects SET data=? WHERE id=?", (json.dumps(p), p["id"]))
        self.mutate({"type": "preview_feedback", "previewVersion": 1, "text": "Remplacer le menu par trois rubriques claires."})
        self.assertEqual(self.current()["pipeline"]["state"], "CONTINUE")
        self.worker.once()
        self.assertEqual(self.current()["pipeline"]["state"], "READY")
        self.assertIn("trois rubriques", self.transport.calls[-1]["history"][-1]["text"])
        self.assertEqual(self.transport.calls[-1]["action"], "message")
        self.assertFalse(any(c["action"] == "generate_preview" for c in self.transport.calls))

    def test_source_requires_explicit_consent_and_fixed_google_folder_url(self):
        for url in ("http://127.0.0.1/admin", "https://drive.google.com.evil.example/drive/folders/fictionalfolder123", "https://drive.google.com/drive/folders/fictionalfolder123?resourcekey=secret"):
            self.mutate({"type": "set_sources", "folderUrl": url, "consent": True}, expected=400)
        self.mutate({"type": "set_sources", "folderUrl": "https://drive.google.com/drive/folders/fictionalfolder123", "consent": False}, expected=400)
        self.assertEqual(self.current()["revision"], 1)

    def test_drive_link_sent_in_chat_uses_the_actual_client_source_event(self):
        self.mutate({"type": "message", "text": "Voici mon cahier des charges et mes images : https://drive.google.com/drive/folders/fictionalfolder123"})
        self.worker.once()
        body = self.transport.calls[-1]
        self.assertEqual(body["source"]["messageId"], body["latestMessageId"])
        self.assertEqual(body["source"]["folderUrl"], "https://drive.google.com/drive/folders/fictionalfolder123")

    def test_quoted_drive_link_does_not_authorize_its_import(self):
        self.mutate({"type": "message", "text": "Une simple citation :\n> https://drive.google.com/drive/folders/fictionalfolder123"})
        self.worker.once()
        self.assertIsNone(self.transport.calls[-1]["source"])

    def test_generation_requires_ready_and_browser_cannot_supply_evidence(self):
        self.mutate({"type": "generate_preview"}, expected=409)
        self.mutate({"type": "message", "text": "Projet fictif", "context": {"state": "READY"}}, expected=400)
        self.assertEqual(self.transport.calls, [])

    def test_new_message_invalidates_previous_ready_even_if_analysis_fails(self):
        self.ready()
        self.transport.mode = "timeout"
        self.mutate({"type": "message", "text": "Modification importante du brief et des contraintes."})
        self.worker.once()
        self.assertEqual(self.current()["pipeline"]["state"], "BLOCKED")
        self.mutate({"type": "generate_preview"}, expected=409)

    def test_incomplete_documents_block_without_template_preview(self):
        self.transport.mode = "incomplete"
        self.mutate({"type": "message", "text": "Documents incomplets du projet fictif."})
        self.worker.once()
        self.assertEqual(self.current()["pipeline"]["state"], "BLOCKED")
        self.assertIsNone(self.current()["preview"])
        self.mutate({"type": "generate_preview"}, expected=409)

    def test_unknown_build_cannot_launch_another_job(self):
        self.ready()
        self.transport.mode = "timeout"
        self.mutate({"type": "generate_preview"})
        self.worker.once()
        self.assertEqual(self.current()["integration"]["status"], "unknown")
        self.mutate({"type": "generate_preview"}, expected=409)
        self.transport.mode = "ready"
        self.mutate({"type": "message", "text": "Je précise le brief après cette interruption."})
        self.worker.once()
        self.assertEqual(self.current()["pipeline"]["state"], "READY")
        self.mutate({"type": "generate_preview"}, expected=409)
        self.assertEqual(len([c for c in self.transport.calls if c["action"] == "generate_preview"]), 1)

    def test_stop_requires_explicit_resume_and_preserves_identity(self):
        self.ready()
        self.mutate({"type": "stop_pipeline"})
        self.assertEqual(self.current()["pipeline"]["state"], "STOPPED")
        self.mutate({"type": "message", "text": "Ne doit pas partir."}, expected=409)
        self.mutate({"type": "resume_pipeline"})
        self.assertEqual(self.current()["id"], self.project["id"])
        self.assertEqual(self.current()["pipeline"]["state"], "CONTINUE")
        self.mutate({"type": "generate_preview"}, expected=409)

    def test_wrong_project_result_and_stale_approval_are_rejected(self):
        self.transport.mode = "wrong_project"
        self.mutate({"type": "message", "text": "Fictional project source."})
        self.worker.once()
        self.assertEqual(self.current()["integration"]["status"], "failed")
        with self.assertRaises(PortalError):
            approve(self.store, self.transport, self.project["id"], "a" * 32, "b" * 64, "c" * 64)

    def test_private_pipeline_tables_remain_private_on_restart(self):
        self.ready()
        with self.store.connection() as db:
            self.assertTrue(pipeline.private_context(db, self.project["id"]))
        again = Store(Path(self.directory.name) / "portal.sqlite3")
        with again.connection() as db:
            self.assertTrue(pipeline.private_context(db, self.project["id"]))
        self.assertNotIn("prompt", json.dumps(self.current()))

    def test_build_polling_survives_restart_without_new_submission(self):
        self.ready()
        self.mutate({"type": "generate_preview"})
        self.worker.once()
        again = Store(Path(self.directory.name) / "portal.sqlite3")
        with again.connection() as db:
            row = db.execute("SELECT * FROM integration_jobs WHERE status='building'").fetchone()
            self.assertEqual(json.loads(row["payload"])["action"], "poll_preview")
            db.execute("UPDATE integration_jobs SET status='running',created=0 WHERE status='building'")
        worker = IntegrationWorker(again, self.transport)
        worker.recover()
        with again.connection() as db:
            db.execute("UPDATE integration_jobs SET created=0 WHERE status='building'")
        worker.once()
        self.assertEqual(self.current()["pipeline"]["state"], "REVIEW_REQUIRED")
        self.assertEqual(len([c for c in self.transport.calls if c["action"] == "generate_preview"]), 1)

    def test_operator_cannot_deliver_a_changed_artifact(self):
        self.ready()
        self.mutate({"type": "generate_preview"})
        self.worker.once()
        with self.store.connection() as db:
            db.execute("UPDATE integration_jobs SET created=0 WHERE status='building'")
        self.worker.once()
        with self.assertRaises(PortalError):
            approve(self.store, self.transport, self.project["id"], "a" * 32, "b" * 64, "d" * 64)
        self.assertIsNone(self.current()["preview"])


if __name__ == "__main__":
    unittest.main()
