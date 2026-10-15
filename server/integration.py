"""Private, durable portal transport. No model or administrative key in the browser."""
import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from domain import CATALOG, PortalError, now, uid
import diagnostics
import pipeline

SCHEMA = """
CREATE TABLE IF NOT EXISTS integration_jobs(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner_id TEXT NOT NULL,
 status TEXT NOT NULL, created INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS integration_jobs_pending ON integration_jobs(status, created);
CREATE TABLE IF NOT EXISTS preview_artifacts(
 project_id TEXT NOT NULL, version INTEGER NOT NULL, html TEXT NOT NULL,
 sha256 TEXT NOT NULL, request_id TEXT UNIQUE NOT NULL,
 PRIMARY KEY(project_id, version));
"""
PENDING = ("queued", "running", "building")


class ArtifactParser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'iframe', 'object', 'embed', 'base', 'form', 'link', 'frame', 'frameset'):
            raise ValueError('Unsupported HTML element')
        for name, value in attrs:
            value = (value or '').strip()
            if name.startswith('on') or name in ('srcdoc', 'action', 'formaction', 'srcset', 'http-equiv'):
                raise ValueError('Unsafe HTML attribute')
            if name in ('href', 'xlink:href', 'src', 'poster', 'data') and not (value.startswith('#') or value.startswith('data:image/')):
                raise ValueError('External artifact URL')

    handle_startendtag = handle_starttag


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class N8nTransport:
    def __init__(self, filename):
        config = json.loads(Path(filename).read_text())
        # Only a fixed local endpoint; customer URLs can never become destinations.
        if not re.fullmatch(r"http://127\.0\.0\.1:5678/webhook/[a-z0-9-]{8,100}", config["url"]):
            raise ValueError("Invalid private n8n endpoint")
        self.url, self.token = config["url"], config["token"]
        self.protocol = config.get("protocol", 1)
        if self.protocol not in (1, 2):
            raise ValueError("Invalid integration protocol")
        self.drive_account = config.get("driveAccount", "") if self.protocol == 2 else ""
        if not isinstance(self.token, str) or len(self.token) < 40:
            raise ValueError("Invalid integration credential")

    def __call__(self, payload):
        request = urllib.request.Request(self.url, json.dumps(payload).encode(),
            {"Content-Type": "application/json", "X-Atelier-Integration": self.token}, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=240) as response:
            maximum = 2000000 if self.protocol == 2 else 200000
            raw = response.read(maximum + 1)
            if len(raw) > maximum or response.status != 200:
                raise ValueError("Invalid integration response")
            return json.loads(raw)


def initialize(store):
    with store.connection() as db:
        db.executescript(SCHEMA)
        pipeline.initialize(db)
        db.execute("UPDATE integration_jobs SET payload='{}' WHERE status NOT IN ('queued','running','building') AND payload!='{}'")


def enqueue(db, owner, previous, project, action, protocol=1):
    if previous.get("integration", {}).get("status") in PENDING:
        raise PortalError("Une réponse est en cours. Attendez sa fin avant de continuer.", 409)
    count = db.execute("SELECT count(*) FROM integration_jobs WHERE owner_id=? AND created>?",
        (owner, int(time.time()) - 86400)).fetchone()[0]
    if count >= 30:
        raise PortalError("La limite de test de 30 demandes par jour est atteinte.", 429)
    request_id = uid()
    if action["type"] == "generate_preview":
        project["preview"] = previous["preview"]
        project["activity"][0]["text"] = "Génération de la maquette demandée"
    project["messages"][-1]["text"] = "Préparation de votre maquette…" if action["type"] == "generate_preview" else "Je prépare votre réponse…"
    project["integration"] = {"requestId": request_id, "status": "queued", "kind": action["type"],
        "messageId": project["messages"][-1]["id"]}
    if protocol == 2:
        body = pipeline.payload(db, previous, project, action, request_id)
        if action["type"] != "generate_preview":
            state = project.setdefault("pipeline", {})
            state.update(state="CONTINUE", questions=[], missingFields=[])
            if state.get("sources"):
                state["sources"]["status"] = "queued"
            pipeline.save_context(db, project["id"], {})
            if project.get("preview"):
                project["preview"].update(status="changes_requested", approvalAt=None)
        db.execute("INSERT INTO integration_jobs VALUES (?,?,?,?,?,?)", (request_id, project["id"], owner,
            "queued", int(time.time()), json.dumps(body)))
        if action["type"] == "generate_preview":
            diagnostics.emit(db, "generation.queued", owner_id=owner, project_id=project["id"],
                             request_id=request_id, revision=project["revision"], status="queued")
        return
    payload = {"schemaVersion": 1, "requestId": request_id, "projectId": project["id"],
        "revision": project["revision"], "action": action["type"], "brief": project["brief"],
        "pricing": {"currency": "EUR", "creationCents": project["initialQuote"]["cents"],
            "monthlyCents": project["initialQuote"]["monthlyCents"], "extraPageCents": CATALOG["extra_page"][1]},
        "messages": [{"role": m["role"], "text": m["text"]} for m in previous["messages"][-19:]]}
    if action["type"] == "message":
        payload["messages"].append({"role": "user", "text": action["text"]})
    # Match JavaScript JSON.stringify's UTF-16 size limit, with headroom. Preserve
    # the newest complete message rather than truncating the customer's request.
    while len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-16-le')) // 2 > 95000:
        if len(payload["messages"]) <= 1:
            raise PortalError("Le contexte du site est trop volumineux.", 413)
        payload["messages"].pop(0)
    db.execute("INSERT INTO integration_jobs VALUES (?,?,?,?,?,?)", (request_id, project["id"], owner,
        "queued", int(time.time()), json.dumps(payload)))
    if action["type"] == "generate_preview":
        diagnostics.emit(db, "generation.queued", owner_id=owner, project_id=project["id"],
                         request_id=request_id, revision=project["revision"], status="queued")


def validate_result(payload, result):
    if payload.get("schemaVersion") == 2:
        return pipeline.validate_result(payload, result)
    expected = {"schemaVersion", "requestId", "projectId", "revision", "reply", "html"}
    if not isinstance(result, dict) or set(result) != expected:
        raise ValueError("Invalid response schema")
    if any(type(result[k]) is not type(payload[k]) or result[k] != payload[k]
           for k in ("schemaVersion", "requestId", "projectId", "revision")):
        raise ValueError("Response binding mismatch")
    if not isinstance(result["reply"], str) or not 3 <= len(result["reply"]) <= 8000:
        raise ValueError("Invalid reply")
    html = result["html"]
    if not isinstance(html, str) or len(html) > 150000:
        raise ValueError("Invalid artifact")
    if payload["action"] == "message" and html:
        raise ValueError("Unrequested artifact")
    if payload["action"] == "generate_preview" and (len(html) < 300 or not re.search(r"<html\b", html, re.I)
            or not re.search(r"</html\s*>", html, re.I) or re.search(r"<\s*(script|iframe|object|embed|base|form)\b|\bon\w+\s*=|javascript:", html, re.I)):
        raise ValueError("Unsafe or incomplete artifact")
    if html:
        ArtifactParser().feed(html)
    return result


class IntegrationWorker:
    def __init__(self, store, transport):
        self.store, self.transport = store, transport
        self.stop = threading.Event()

    def finish(self, row, result=None, status="succeeded", reason=None):
        payload = json.loads(row["payload"])
        if result is not None:
            validate_result(payload, result)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            stored = db.execute("SELECT data FROM projects WHERE id=? AND owner_id=?",
                (row["project_id"], row["owner_id"])).fetchone()
            project = json.loads(stored[0]) if stored else None
            current = db.execute("SELECT status FROM integration_jobs WHERE id=?", (row["id"],)).fetchone()
            if not current or current[0] not in (*PENDING, "building"):
                return
            if not project or project.get("integration", {}).get("requestId") != row["id"]:
                db.execute("UPDATE integration_jobs SET status='stale',payload='{}' WHERE id=?", (row["id"],))
                self.trace_outcome(db, row, payload, status="stale", reason="STALE_RESULT")
                return
            if project and project.get("integration", {}).get("requestId") == row["id"] and project["revision"] != payload["revision"]:
                # A previous release may have allowed edits while this job was
                # pending. Clear the pending marker without touching the newer
                # conversation, artifact or its approval.
                project["integration"]["status"] = "stale"
                project["revision"] += 1
                project["updatedAt"] = now()
                db.execute("UPDATE projects SET revision=?,data=?,updated_at=? WHERE id=? AND owner_id=?",
                    (project["revision"], json.dumps(project), project["updatedAt"], project["id"], row["owner_id"]))
                db.execute("UPDATE integration_jobs SET status='stale',payload='{}' WHERE id=?", (row["id"],))
                self.trace_outcome(db, row, payload, status="stale", reason="STALE_RESULT")
                return
            if project and project.get("integration", {}).get("requestId") == row["id"]:
                is_v2 = payload.get("schemaVersion") == 2
                if result and is_v2:
                    pipeline.apply_result(db, project, payload, result)
                elif is_v2:
                    state = project.setdefault("pipeline", {})
                    state.update(state="BLOCKED", questions=[], missingFields=[], reasonCodes=["PIPELINE_RESPONSE_UNCONFIRMED" if status == "unknown" else "PIPELINE_RESPONSE_FAILED"])
                    if state.get("sources", {}).get("status") == "queued":
                        state["sources"]["status"] = "REVIEW_REQUIRED"
                message = next((m for m in project["messages"] if m["id"] == project["integration"]["messageId"]), None)
                if message:
                    message["text"] = result["reply"] if result else "La demande n’a pas abouti. Aucun résultat n’est annoncé. Vous pouvez soumettre une nouvelle demande ; aucune relance automatique n’a lieu."
                    if not result and is_v2:
                        message["text"] = "Le résultat du traitement n’a pas été confirmé. Aucun nouveau résultat n’est annoncé. Contactez le support en cas d’échec persistant ; une construction incertaine doit être vérifiée avant d’en lancer une autre."
                if result and not is_v2 and payload["action"] == "generate_preview":
                    version = db.execute("SELECT coalesce(max(version),0)+1 FROM preview_artifacts WHERE project_id=?", (project["id"],)).fetchone()[0]
                    version = max(version, (project.get("preview") or {}).get("version", 0) + 1)
                    digest = hashlib.sha256(result["html"].encode()).hexdigest()
                    db.execute("INSERT INTO preview_artifacts VALUES (?,?,?,?,?)", (project["id"], version, result["html"], digest, row["id"]))
                    project["preview"] = {"version": version, "status": "awaiting_review", "at": now(),
                        "approvalAt": None, "feedback": "", "generated": True, "sha256": digest}
                project["integration"]["status"] = status
                project["revision"] += 1
                project["updatedAt"] = now()
                if result and is_v2 and result["pipeline"]["state"] == "BUILDING":
                    count = payload.get("pollCount", 0) + 1
                    if count > 360:
                        raise ValueError("Build polling limit reached; manual reconciliation required")
                    polling = {"schemaVersion": 2, "requestId": row["id"], "projectId": project["id"],
                        "revision": project["revision"], "action": "poll_preview", "pollCount": count,
                        "context": result["private"]}
                    project["integration"]["status"] = "building"
                    db.execute("UPDATE projects SET revision=?,data=?,updated_at=? WHERE id=? AND owner_id=?",
                        (project["revision"], json.dumps(project), project["updatedAt"], project["id"], row["owner_id"]))
                    db.execute("UPDATE integration_jobs SET status='building',created=?,payload=? WHERE id=?",
                        (int(time.time()) + 5, json.dumps(polling), row["id"]))
                    return
                db.execute("UPDATE projects SET revision=?,data=?,updated_at=? WHERE id=? AND owner_id=?",
                    (project["revision"], json.dumps(project), project["updatedAt"], project["id"], row["owner_id"]))
            db.execute("UPDATE integration_jobs SET status=?,payload='{}' WHERE id=?", (status, row["id"]))
            self.trace_outcome(db, row, payload, result, status, reason)

    def trace_outcome(self, db, row, payload, result=None, status="succeeded", reason=None):
        """Terminal transitions only; never copy transport explanations."""
        build = payload.get("action") in ("generate_preview", "poll_preview")
        summary = (result or {}).get("pipeline", {}).get("build")
        job_id = summary.get("jobId") if isinstance(summary, dict) else None
        if not job_id:
            context = payload.get("context")
            saved_job = context.get("buildJob") if isinstance(context, dict) else None
            job_id = saved_job.get("jobId") if isinstance(saved_job, dict) else None
        if not isinstance(job_id, str) or not diagnostics.JOB.fullmatch(job_id):
            job_id = None
        fields = {"owner_id": row["owner_id"], "project_id": row["project_id"],
                  "request_id": row["id"], "job_id": job_id, "revision": payload["revision"]}
        if result is None:
            diagnostics.emit(db, "generation.failed" if build else "pipeline.failed", **fields,
                status=status, reason=reason or ("BUILD_UNCONFIRMED" if status == "unknown" and build else "INVALID_RESPONSE"))
        elif result.get("pipeline", {}).get("state") == "BLOCKED":
            diagnostics.emit(db, "generation.failed" if build else "pipeline.failed", **fields,
                             status="failed", reason="PIPELINE_BLOCKED")
        elif build:
            needs_review = result.get("pipeline", {}).get("state") == "REVIEW_REQUIRED"
            diagnostics.emit(db, "generation.completed", **fields,
                             status="review_required" if needs_review else "completed")

    def recover(self):
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM integration_jobs WHERE status='running'").fetchall()
        for row in rows:
            resumed = self.retry_poll(row)
            if not resumed:
                self.finish(row, status="unknown", reason="RESTART_RECOVERY")
            with self.store.connection() as db:
                diagnostics.emit(db, "pipeline.recovered", owner_id=row["owner_id"],
                    project_id=row["project_id"], request_id=row["id"],
                    status="building" if resumed else "unknown", reason="RESTART_RECOVERY")

    def retry_poll(self, row):
        body = json.loads(row["payload"])
        if body.get("schemaVersion") != 2 or body.get("action") != "poll_preview" or body.get("pollCount", 360) >= 360:
            return False
        body["pollCount"] += 1
        with self.store.connection() as db:
            db.execute("UPDATE integration_jobs SET status='building',created=?,payload=? WHERE id=? AND status='running'",
                (int(time.time()) + 5, json.dumps(body), row["id"]))
        return True

    def once(self):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM integration_jobs WHERE status='queued' OR (status='building' AND created<=?) ORDER BY created,rowid LIMIT 1", (int(time.time()),)).fetchone()
            if not row:
                return False
            db.execute("UPDATE integration_jobs SET status='running' WHERE id=? AND status=?", (row["id"], row["status"]))
            body = json.loads(row["payload"])
            if body.get("action") == "generate_preview":
                diagnostics.emit(db, "generation.started", owner_id=row["owner_id"],
                    project_id=row["project_id"], request_id=row["id"],
                    revision=body["revision"], status="running")
        try:
            self.finish(row, self.transport(json.loads(row["payload"])))
        except (TimeoutError, OSError, urllib.error.URLError) as error:
            if not self.retry_poll(row):
                self.finish(row, status="unknown", reason="TIMEOUT" if isinstance(error, TimeoutError) else "TRANSPORT_ERROR")
        except Exception:
            body = json.loads(row["payload"])
            uncertain_build = body.get("schemaVersion") == 2 and body.get("action") == "generate_preview"
            self.finish(row, status="unknown" if uncertain_build else "failed", reason="INVALID_RESPONSE")
        return True

    def run(self):
        self.recover()
        while not self.stop.is_set():
            if not self.once():
                self.stop.wait(1)
