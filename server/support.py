"""Explicit, owner-scoped support snapshots and at-most-once mail dispatch."""
import base64
import hashlib
import json
import re
import threading
import time
from pathlib import Path

from domain import PortalError, exact, now, text
from integration import N8nTransport
import diagnostics

EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+", re.ASCII)
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
SCHEMA = """
CREATE TABLE IF NOT EXISTS support_tickets(
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, project_id TEXT NOT NULL,
 created INTEGER NOT NULL, status TEXT NOT NULL, fingerprint TEXT NOT NULL,
 payload TEXT NOT NULL, receipt TEXT);
CREATE INDEX IF NOT EXISTS support_owner ON support_tickets(owner_id,created);
"""


def email(value):
    if not isinstance(value, str) or len(value) > 254 or not EMAIL.fullmatch(value):
        raise PortalError("Indiquez une adresse e-mail de réponse valide.")
    return value


class SupportTransport(N8nTransport):
    def __init__(self, filename):
        super().__init__(filename)
        self.recipient = email(json.loads(Path(filename).read_text())["recipient"])
        if self.recipient.endswith(".invalid"):
            raise ValueError("Configure a real support recipient before enabling delivery")

    def __call__(self, payload):
        return super().__call__({**payload, "recipient": self.recipient})


def initialize(store):
    with store.connection() as db:
        db.executescript(SCHEMA)


def summary(row):
    return {"id": row["id"], "status": row["status"], "created": row["created"]}


def list_tickets(store, owner, project_id):
    with store.connection() as db:
        if not db.execute("SELECT 1 FROM projects WHERE id=? AND owner_id=?", (project_id, owner)).fetchone():
            raise PortalError("Site introuvable.", 404)
        return [summary(row) for row in db.execute(
            "SELECT id,status,created FROM support_tickets WHERE owner_id=? AND project_id=? ORDER BY created DESC,rowid DESC LIMIT 10",
            (owner, project_id))]


def create_ticket(store, owner, project_id, raw, origin, base_path):
    exact(raw, ("requestId", "revision", "email", "message", "consent"))
    request_id = raw["requestId"]
    if not isinstance(request_id, str) or not UUID.fullmatch(request_id):
        raise PortalError("Référence de demande invalide.")
    reply_to = email(raw["email"])
    message = text(raw["message"], 10, 4000)
    if raw["consent"] is not True or type(raw["revision"]) is not int or raw["revision"] < 1:
        raise PortalError("Confirmez le partage du contexte avec le support.")
    fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT revision,data FROM projects WHERE owner_id=? AND id=?", (owner, project_id)).fetchone()
        if not row:
            raise PortalError("Site introuvable.", 404)
        existing = db.execute("SELECT * FROM support_tickets WHERE id=?", (request_id,)).fetchone()
        if existing:
            if existing["owner_id"] != owner or existing["project_id"] != project_id or existing["fingerprint"] != fingerprint:
                raise PortalError("Cette référence est déjà utilisée pour une autre demande.", 409)
            return summary(existing)
        if not store.support:
            raise PortalError("Le formulaire de support n’est pas encore disponible. Réessayez plus tard.", 503)
        if row["revision"] != raw["revision"]:
            raise PortalError("Le site a évolué. Relisez le contexte actualisé avant l’envoi.", 409)
        current = int(time.time())
        recent = db.execute("SELECT created,status FROM support_tickets WHERE owner_id=? AND created>?", (owner, current - 86400)).fetchall()
        pending = db.execute("SELECT 1 FROM support_tickets WHERE owner_id=? AND status IN ('queued','running') LIMIT 1", (owner,)).fetchone()
        if len(recent) >= 5 or pending or any(r["created"] > current - 60 for r in recent):
            raise PortalError("Une demande est déjà en cours ou la limite d’envoi est atteinte. Patientez avant un nouvel envoi.", 429)
        project = json.loads(row["data"])
        preview = project.get("preview") or {}
        artifact = db.execute("SELECT version,html,sha256 FROM preview_artifacts WHERE project_id=? ORDER BY version DESC LIMIT 1", (project_id,)).fetchone()
        site_url = origin + base_path + "#/sites/" + project_id
        preview_url = origin + base_path + f"api/projects/{project_id}/preview/{artifact['version']}" if artifact else None
        external = preview.get("externalUrl")
        if external:
            from pipeline import PREVIEW
            if PREVIEW.fullmatch(external):
                preview_url = external
                artifact = None
            else:
                external = None
        context = {"capturedAt": now(), "site": project["name"], "projectId": project_id,
            "revision": row["revision"], "siteUrl": site_url, "previewUrl": preview_url,
            "previewVersion": preview.get("version") if external else artifact["version"] if artifact else None,
            "previewSha256": preview.get("sha256") if external else artifact["sha256"] if artifact else None,
            "previewStatus": preview.get("status"), "generation": project.get("integration"),
            "brief": project["brief"], "messages": project["messages"][-100:],
            "historyLimit": "Historique conservé : 100 derniers messages au maximum."}
        attachment_html = None
        if artifact:
            # Email attachments do not inherit the portal response's CSP.
            attachment_html = ('<!doctype html><meta charset="utf-8">'
                '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
                'style-src \'unsafe-inline\'; img-src data:; base-uri \'none\'; form-action \'none\'">'
                + artifact["html"])
            context["attachmentSha256"] = hashlib.sha256(attachment_html.encode()).hexdigest()
            context["attachmentProtection"] = "Politique CSP ajoutée en tête : scripts et ressources réseau interdits. previewSha256 identifie l’original conservé."
        transcript = json.dumps(context, ensure_ascii=False, indent=2)
        attachments = [{"name": "conversation.txt", "mime": "text/plain", "data": base64.b64encode(transcript.encode()).decode()}]
        if attachment_html:
            attachments.append({"name": "maquette.html", "mime": "text/html", "data": base64.b64encode(attachment_html.encode()).decode()})
        body = (f"Demande de support Atelier\nRéférence : {request_id}\nSite : {project['name']}\n"
                f"Réponse client : {reply_to}\n\n{message}\n\nSite : {site_url}\n"
                f"Maquette : {preview_url or 'Aucune maquette générée disponible'}\n"
                "Les liens du portail exigent le compte propriétaire et l’accès privé habituel. "
                "La copie de la maquette, lorsqu’elle existe, et la conversation conservée sont jointes.\n"
                f"État de génération : {(project.get('integration') or {}).get('status', 'non demandé')}\n")
        payload = {"schemaVersion": 1, "ticketId": request_id, "projectId": project_id,
            "revision": row["revision"], "replyTo": reply_to, "subject": f"[Atelier support] {request_id}",
            "message": body, "attachments": attachments}
        db.execute("INSERT INTO support_tickets VALUES (?,?,?,?,?,?,?,?)", (request_id, owner, project_id, current,
            "queued", fingerprint, json.dumps(payload), None))
        diagnostics.emit(db, "support.queued", owner_id=owner, project_id=project_id,
                         request_id=request_id, revision=row["revision"], status="queued")
        return {"id": request_id, "status": "queued", "created": current}


class SupportWorker:
    def __init__(self, store, transport):
        self.store, self.transport = store, transport
        self.stop = threading.Event()

    def recover(self):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            interrupted = db.execute("SELECT id,owner_id,project_id FROM support_tickets WHERE status='running'").fetchall()
            db.execute("UPDATE support_tickets SET status='unknown' WHERE status='running'")
            for row in interrupted:
                diagnostics.emit(db, "support.unknown", owner_id=row["owner_id"],
                    project_id=row["project_id"], request_id=row["id"],
                    status="unknown", reason="RESTART_RECOVERY")

    def once(self):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM support_tickets WHERE status='queued' ORDER BY created,rowid LIMIT 1").fetchone()
            if not row:
                return False
            db.execute("UPDATE support_tickets SET status='running' WHERE id=?", (row["id"],))
        status, receipt = "unknown", None
        try:
            result = self.transport(json.loads(row["payload"]))
            if (isinstance(result, dict) and set(result) == {"schemaVersion", "ticketId", "status", "messageId"}
                    and type(result["schemaVersion"]) is int and result["schemaVersion"] == 1
                    and result["ticketId"] == row["id"] and result["status"] == "sent"
                    and isinstance(result["messageId"], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", result["messageId"])):
                status, receipt = "sent", result["messageId"]
        except Exception:
            pass  # A lost receipt may follow a successful send. Never retry automatically.
        with self.store.connection() as db:
            changed = db.execute("UPDATE support_tickets SET status=?,receipt=? WHERE id=? AND status='running'", (status, receipt, row["id"]))
            if changed.rowcount:
                diagnostics.emit(db, "support.sent" if status == "sent" else "support.unknown",
                    owner_id=row["owner_id"], project_id=row["project_id"], request_id=row["id"],
                    status=status, reason="RECEIPT_UNCONFIRMED" if status == "unknown" else None)
        return True

    def run(self):
        self.recover()
        while not self.stop.is_set():
            if not self.once():
                self.stop.wait(1)
