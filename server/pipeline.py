"""Web-native orchestration contract; browser data never supplies a source receipt.

The n8n adapter uses the same evidence engine, reader and builder as the mail
pipeline. This module keeps their private context out of customer API responses.
"""
import copy
import hashlib
import json
import re

from domain import PortalError, now, uid

SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_context(
 project_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pipeline_reviews(
 project_id TEXT NOT NULL, job_id TEXT NOT NULL, revision TEXT NOT NULL,
 artifact_sha256 TEXT NOT NULL, decision TEXT NOT NULL, at TEXT NOT NULL,
 PRIMARY KEY(project_id,job_id,revision,artifact_sha256));
CREATE TABLE IF NOT EXISTS pipeline_build_requests(
 request_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, revision INTEGER NOT NULL,
 prompt_sha256 TEXT NOT NULL, at TEXT NOT NULL);
"""
HEX = re.compile(r"[a-f0-9]{64}")
JOB = re.compile(r"[a-f0-9]{32}")
FOLDER = re.compile(r"https://drive\.google\.com/(?:drive/(?:u/[0-9]+/)?folders/|folders/)([A-Za-z0-9_-]{10,160})(?:\?[^#\s]*)?")
PREVIEW = re.compile(r"https://mockups\.example\.invalid/maquettes/([a-f0-9]{32})/index\.html")


def initialize(db):
    db.executescript(SCHEMA)


def private_context(db, project_id):
    row = db.execute("SELECT data FROM pipeline_context WHERE project_id=?", (project_id,)).fetchone()
    return json.loads(row[0]) if row else {}


def save_context(db, project_id, value):
    db.execute("INSERT INTO pipeline_context VALUES (?,?) ON CONFLICT(project_id) DO UPDATE SET data=excluded.data",
               (project_id, json.dumps(value, ensure_ascii=False)))


def message_sources(project, action):
    if action.get("type") != "message":
        return
    lines = []
    for line in action["text"].splitlines():
        if re.match(r"\s*(?:On .+wrote\s*:|Le .+écrit\s*:|From\s*:|De\s*:|Begin forwarded message\s*:|Début du message transféré\s*:)", line, re.I):
            break
        if not re.match(r"\s*>", line):
            lines.append(line)
    urls = [u.rstrip(").,;") for u in re.findall(r"https?://[^\s<>\"']+", "\n".join(lines), re.I)]
    drive = [u for u in urls if re.match(r"https?://drive\.google\.com(?:/|$)", u, re.I)]
    if not drive:
        return
    roots = {}
    for url in drive:
        match = FOLDER.fullmatch(url)
        if not match or re.search(r"[?&]resourcekey=", url, re.I):
            raise PortalError("Fournissez le lien HTTPS d’un dossier Google Drive partagé en privé, plutôt qu’un fichier ou un lien public.")
        roots[match[1]] = url
    if len(roots) != 1:
        raise PortalError("Fournissez un seul dossier Google Drive pour ce projet.")
    client = project["messages"][-2]
    project.setdefault("pipeline", {})["sources"] = {"folderUrl": next(iter(roots.values())),
        "messageId": client["id"], "text": client["text"], "consentAt": now(), "status": "queued", "files": []}


def prepare_action(previous, action):
    """Validate new actions before the legacy domain transition runs."""
    kind = action.get("type")
    if kind not in ("set_sources", "stop_pipeline", "resume_pipeline"):
        return None
    if kind == "set_sources":
        if set(action) != {"type", "folderUrl", "consent"} or action["consent"] is not True:
            raise PortalError("Confirmez que vous autorisez la lecture des fichiers de ce dossier.")
        value = action["folderUrl"]
        if not isinstance(value, str) or len(value) > 600 or not FOLDER.fullmatch(value) or re.search(r"[?&]resourcekey=", value, re.I):
            raise PortalError("Utilisez le lien HTTPS d’un dossier Google Drive partagé en privé avec le compte indiqué.")
        text = "Je fournis ce dossier Google Drive pour mon projet et autorise sa lecture : " + value
    else:
        if set(action) != {"type"}:
            raise PortalError("Action invalide.")
        if kind == "resume_pipeline" and previous.get("pipeline", {}).get("resumes", 0) >= 3:
            raise PortalError("La limite de trois reprises est atteinte. Contactez le support.", 409)
        text = "Je demande l’arrêt du traitement de ce projet." if kind == "stop_pipeline" else "Je demande la reprise de la discussion de ce projet."
    # Use the established conversation mutation to preserve IDs/history/revisions.
    from domain import transition
    project = transition(previous, {"type": "message", "text": text})
    client_message = project["messages"][-2]
    state = copy.deepcopy(previous.get("pipeline", {}))
    state.update(state="STOPPED" if kind == "stop_pipeline" else "CONTINUE", questions=[], missingFields=[])
    if kind == "set_sources":
        state["sources"] = {"folderUrl": action["folderUrl"], "messageId": client_message["id"],
                            "text": text, "consentAt": now(), "status": "queued", "files": []}
    if kind == "resume_pipeline":
        state["resumes"] = state.get("resumes", 0) + 1
    state.pop("build", None)
    project["pipeline"] = state
    if project.get("preview"):
        project["preview"]["status"] = "changes_requested"
        project["preview"]["approvalAt"] = None
    project["messages"][-1]["text"] = "Traitement arrêté. Aucune nouvelle construction ne sera lancée." if kind == "stop_pipeline" else "La discussion peut continuer. Les informations seront revérifiées avant toute génération."
    return project


def payload(db, previous, project, action, request_id):
    state = previous.get("pipeline", {})
    if state.get("state") == "STOPPED" and action["type"] not in ("resume_pipeline", "stop_pipeline"):
        raise PortalError("Ce projet est arrêté. Reprenez explicitement la discussion.", 409)
    private = private_context(db, project["id"])
    generation = action["type"] == "generate_preview"
    unresolved = db.execute("SELECT 1 FROM pipeline_build_requests b JOIN integration_jobs j ON j.id=b.request_id WHERE b.project_id=? AND j.status='unknown' LIMIT 1", (project["id"],)).fetchone() if generation else None
    if generation and (unresolved or previous.get("integration", {}).get("kind") == "generate_preview" and previous["integration"].get("status") == "unknown"):
        raise PortalError("La construction précédente n’est pas confirmée. Contactez le support pour retrouver son état avant d’en lancer une autre.", 409)
    if generation and (state.get("state") != "READY" or not private.get("analysis") or not private.get("prompt")):
        raise PortalError("Complétez d’abord le brief et les documents. La génération sera disponible après leur validation.", 409)
    # An actual persisted brief is a web source, not a fabricated mail.
    history = [{"id": "brief_" + project["id"], "role": "client", "kind": "web_brief",
                "text": json.dumps(project["brief"], ensure_ascii=False)}]
    messages = project["messages"][:-1]
    history += [{"id": m["id"], "role": "client" if m["role"] == "user" else "assistant", "text": m["text"]}
                for m in messages]
    latest = next((m for m in reversed(history) if m["role"] == "client"), history[0])
    source = project.get("pipeline", {}).get("sources")
    body = {"schemaVersion": 2, "requestId": request_id, "projectId": project["id"],
            "revision": project["revision"], "action": "generate_preview" if generation else "message",
            "history": history, "historyComplete": len(previous["messages"]) < 100,
            "latestMessageId": latest["id"], "brief": project["brief"],
            "pricing": project["initialQuote"], "resumes": state.get("resumes", 0),
            "source": source, "context": private if generation else {}}
    body["generationApproval"] = {"requestId": request_id, "projectId": project["id"],
        "revision": project["revision"], "action": "generate_preview"} if generation else None
    if generation:
        db.execute("INSERT INTO pipeline_build_requests VALUES (?,?,?,?,?)", (request_id, project["id"],
            project["revision"], hashlib.sha256(private["prompt"].encode()).hexdigest(), now()))
    if len(json.dumps(body, ensure_ascii=False).encode("utf-16-le")) // 2 > 95000:
        raise PortalError("Le contexte complet dépasse la limite de lecture. Contactez le support.", 413)
    return body


def validate_result(body, result):
    if not isinstance(result, dict) or set(result) != {"schemaVersion", "requestId", "projectId", "revision", "reply", "pipeline", "private"}:
        raise ValueError("Invalid pipeline response schema")
    for key in ("schemaVersion", "requestId", "projectId", "revision"):
        if type(result[key]) is not type(body[key]) or result[key] != body[key]:
            raise ValueError("Pipeline response binding mismatch")
    if not isinstance(result["reply"], str) or not 3 <= len(result["reply"]) <= 8000:
        raise ValueError("Invalid pipeline reply")
    public, private = result["pipeline"], result["private"]
    if not isinstance(public, dict) or not isinstance(private, dict) or public.get("state") not in ("CONTINUE", "READY", "BLOCKED", "BUILDING", "REVIEW_REQUIRED", "STOPPED"):
        raise ValueError("Invalid pipeline state")
    allowed_states = {"message": ("CONTINUE", "READY", "BLOCKED", "STOPPED"),
        "generate_preview": ("BUILDING", "BLOCKED"), "poll_preview": ("BUILDING", "REVIEW_REQUIRED", "BLOCKED")}
    if public["state"] not in allowed_states.get(body["action"], ()):
        raise ValueError("State does not match the requested action")
    if set(public) - {"state", "questions", "missingFields", "reasonCodes", "sources", "build", "facts", "classification", "sourceScan"}:
        raise ValueError("Unexpected public pipeline fields")
    for field in ("questions", "missingFields", "reasonCodes"):
        values = public.get(field, [])
        if not isinstance(values, list) or len(values) > 30 or any(not isinstance(x, str) or len(x) > 2000 for x in values):
            raise ValueError("Invalid pipeline explanation")
    if "facts" in public:
        facts = public["facts"]
        if not isinstance(facts, list) or len(facts) > 6:
            raise ValueError("Invalid brief facts")
        for fact in facts:
            if not isinstance(fact, dict) or set(fact) != {"field", "value", "quote", "source"} or any(not isinstance(v, str) or len(v) > 20000 for v in fact.values()):
                raise ValueError("Invalid brief fact")
    classification = public.get("classification")
    if classification is not None:
        if not isinstance(classification, dict) or set(classification) != {"kind", "messageId", "confidence", "probability", "reason"} or classification["kind"] not in ("general", "content_edit", "design_refresh", "add_page", "advanced", "clarification") or classification["messageId"] != body.get("latestMessageId"):
            raise ValueError("Invalid classification binding")
        if classification["reason"] not in ("CLASSIFICATION_VERIFIED", "CLASSIFICATION_UNCERTAIN", "MULTIPLE_REQUESTS") or any(type(classification[k]) not in (int, float) or not 0 <= classification[k] <= 1 for k in ("confidence", "probability")):
            raise ValueError("Invalid classification evidence")
        if classification["kind"] != "clarification" and (classification["confidence"] < .8 or classification["probability"] < .9):
            raise ValueError("Uncertain classification cannot create a request")
    scan = public.get("sourceScan")
    if scan is not None:
        if not isinstance(scan, dict) or set(scan) != {"policy", "status", "findingCount", "reasonCodes"} or scan["policy"] != "drive-source-admission-v1" or scan["status"] not in ("REVIEW_REQUIRED", "NO_BLOCKING_PATTERN_DETECTED") or type(scan["findingCount"]) is not int or not 0 <= scan["findingCount"] <= 100000:
            raise ValueError("Invalid source scan receipt")
        if not isinstance(scan["reasonCodes"], list) or len(scan["reasonCodes"]) > 64 or any(not isinstance(x, str) or not re.fullmatch(r"SOURCE_[A-Z_]{2,70}", x) for x in scan["reasonCodes"]):
            raise ValueError("Invalid source scan codes")
        if scan["status"] == "REVIEW_REQUIRED" and public["state"] != "BLOCKED":
            raise ValueError("A blocked source cannot reach the provider")
    if "sources" in public:
        source = public["sources"]
        if not isinstance(source, dict) or set(source) != {"status", "files", "pages", "characters"} or source["status"] not in ("READ", "REVIEW_REQUIRED"):
            raise ValueError("Invalid source receipt summary")
        if not isinstance(source["files"], list) or len(source["files"]) > 50:
            raise ValueError("Invalid source files")
        for file in source["files"]:
            if not isinstance(file, dict) or set(file) != {"name", "mimeType", "version"} or any(not isinstance(v, str) or len(v) > 300 for v in file.values()):
                raise ValueError("Invalid public file metadata")
        if any(type(source[x]) is not int or source[x] < 0 for x in ("pages", "characters")):
            raise ValueError("Invalid source usage")
    build = public.get("build")
    if build is not None:
        if not isinstance(build, dict) or set(build) != {"jobId", "status"} or not JOB.fullmatch(build.get("jobId", "")) or build.get("status") not in ("queued", "running", "completed_review_required", "blocked", "failed"):
            raise ValueError("Invalid build summary")
        if body["action"] not in ("generate_preview", "poll_preview"):
            raise ValueError("Unrequested build")
    if public["state"] == "READY" and (not isinstance(private.get("prompt"), str) or not private["prompt"] or not isinstance(private.get("analysis"), dict)):
        raise ValueError("READY without evidence")
    if public["state"] in ("BUILDING", "REVIEW_REQUIRED"):
        job = private.get("buildJob", {})
        if not isinstance(job, dict) or not JOB.fullmatch(job.get("jobId", "")) or not HEX.fullmatch(job.get("revision", "")) or not build or build["jobId"] != job["jobId"]:
            raise ValueError("Build state without an exact receipt")
    if public["state"] == "REVIEW_REQUIRED":
        proof = validate_proof(body["projectId"], private)
        if proof["job_id"] != job["jobId"] or proof["revision"] != job["revision"]:
            raise ValueError("Review proof differs from the submitted job")
    return result


def apply_result(db, project, body, result):
    validate_result(body, result)
    old = project.get("pipeline", {})
    public = copy.deepcopy(result["pipeline"])
    public["resumes"] = old.get("resumes", 0)
    if old.get("sources"):
        public["sources"] = {**old["sources"], **public.get("sources", {})}
    project["pipeline"] = public
    save_context(db, project["id"], result["private"])
    classification = public.get("classification")
    if classification:
        import diagnostics
        owner = db.execute("SELECT owner_id FROM projects WHERE id=?", (project["id"],)).fetchone()[0]
        diagnostics.emit(db, "classification.decided", owner_id=owner, project_id=project["id"], request_id=body["requestId"], revision=body["revision"], status=public["state"], category=classification["kind"])
        record_classified_request(project, classification)
    if public.get("sourceScan"):
        import diagnostics
        owner = db.execute("SELECT owner_id FROM projects WHERE id=?", (project["id"],)).fetchone()[0]
        rejected = public["sourceScan"]["status"] == "REVIEW_REQUIRED"
        diagnostics.emit(db, "source.scan", owner_id=owner, project_id=project["id"], request_id=body["requestId"], revision=body["revision"], status="rejected" if rejected else "clean", reason="SOURCE_REJECTED" if rejected else None)
    if public["state"] == "REVIEW_REQUIRED":
        # No delivery URL is exposed until an operator approves this exact proof.
        result["reply"] = "La maquette a été construite et revue. Elle attend maintenant la validation humaine avant sa livraison dans votre espace."


def record_classified_request(project, classification):
    from domain import CATALOG
    category = {"content_edit": "small_edit", "design_refresh": "redesign", "add_page": "extra_page", "advanced": "advanced"}.get(classification["kind"])
    if not category or project["pipeline"]["state"] in ("BLOCKED", "STOPPED"):
        return
    source = next((m for m in project["messages"] if m["id"] == classification["messageId"] and m["role"] == "user"), None)
    current = next((m for m in project["messages"] if m["id"] == project["integration"]["messageId"]), {})
    if not source or current.get("requestId") or any(r.get("sourceMessageId") == source["id"] for r in project["requests"]):
        return
    if sum(r["status"] != "cancelled" for r in project["requests"]) >= 20:
        return  # Existing requests stay intact; no hidden acceptance or work.
    title, cents = CATALOG[category]
    request_id = uid()
    project["requests"].insert(0, {"id": request_id, "category": category, "title": title,
        "description": source["text"], "assetUrl": "", "status": "quoted" if cents is not None else "needs_scope_review",
        "cents": cents, "at": now(), "quoteVersion": 1, "sourceMessageId": source["id"]})
    project["messages"].append({"id": uid(), "projectId": project["id"], "role": "assistant", "at": now(),
        "kind": "request", "requestId": request_id, "text": "Votre demande a été classée et un brouillon de devis ou de périmètre est disponible ici. Aucun accord, paiement ou travail n’est déclenché par cette classification."})
    project["messages"] = project["messages"][-100:]


def validate_proof(project_id, private):
    proof = private.get("buildProof")
    if not isinstance(proof, dict) or proof.get("project_id") != "web_" + project_id or proof.get("state") != "completed_review_required" or proof.get("proof_status") != "proof_verified":
        raise PortalError("La preuve de construction et de revue n’est pas validée.", 409)
    job_id, revision, sha = proof.get("job_id", ""), proof.get("revision", ""), proof.get("artifact_sha256", "")
    url = proof.get("preview_url", "")
    if not JOB.fullmatch(job_id) or not HEX.fullmatch(revision) or not HEX.fullmatch(sha) or not PREVIEW.fullmatch(url) or PREVIEW.fullmatch(url)[1] != job_id:
        raise PortalError("La preuve ne correspond pas à la maquette attendue.", 409)
    return proof
