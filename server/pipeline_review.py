"""Operator-only delivery approval for an exact independently reviewed artifact.

No customer HTTP endpoint invokes this command. Read the artifact and ask the
human before running --approve. A fresh status read verifies unchanged proof.
"""
import argparse
import json
from pathlib import Path

from app import Store
from domain import PortalError, now, uid
from integration import N8nTransport
import diagnostics
import pipeline


def approve(store, transport, project_id, job_id, revision, sha256):
    with store.connection() as db:
        row = db.execute("SELECT owner_id,data FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise PortalError("Projet introuvable.", 404)
        project = json.loads(row["data"])
        if project.get("pipeline", {}).get("state") != "REVIEW_REQUIRED":
            raise PortalError("Ce projet n’attend pas de validation de livraison.", 409)
        private = pipeline.private_context(db, project_id)
        before = pipeline.validate_proof(project_id, private)
        if (before["job_id"], before["revision"], before["artifact_sha256"]) != (job_id, revision, sha256):
            raise PortalError("L’approbation ne correspond pas à l’artefact exact.", 409)
        saved_revision = project["revision"]
    body = {"schemaVersion": 2, "requestId": uid(), "projectId": project_id,
            "revision": saved_revision, "action": "poll_preview", "pollCount": 1, "context": private}
    result = transport(body)
    pipeline.validate_result(body, result)
    fresh = pipeline.validate_proof(project_id, result["private"])
    if fresh != before or result["pipeline"]["state"] != "REVIEW_REQUIRED":
        raise PortalError("La preuve fraîche a changé. Une nouvelle revue est nécessaire.", 409)
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT owner_id,data FROM projects WHERE id=?", (project_id,)).fetchone()
        project = json.loads(row["data"]) if row else {}
        if project.get("revision") != saved_revision or project.get("pipeline", {}).get("state") != "REVIEW_REQUIRED" or pipeline.private_context(db, project_id) != private:
            raise PortalError("Le projet a changé pendant la vérification.", 409)
        db.execute("INSERT INTO pipeline_reviews VALUES (?,?,?,?,?,?)",
                   (project_id, job_id, revision, sha256, "APPROVED", now()))
        maximum = db.execute("SELECT coalesce(max(version),0) FROM preview_artifacts WHERE project_id=?", (project_id,)).fetchone()[0]
        version = max(maximum, (project.get("preview") or {}).get("version", 0)) + 1
        project["preview"] = {"version": version, "status": "awaiting_review", "at": now(),
            "approvalAt": None, "feedback": "", "generated": True, "sha256": sha256,
            "externalUrl": fresh["preview_url"], "jobId": job_id, "buildRevision": revision}
        project["pipeline"]["state"] = "DELIVERED"
        project["revision"] += 1
        project["updatedAt"] = now()
        project["messages"].append({"id": uid(), "projectId": project_id, "kind": "status",
            "role": "assistant", "at": now(), "text": "Votre maquette de test a été revue et sa livraison validée. Vous pouvez l’ouvrir et donner votre avis. Elle ne constitue pas une publication commerciale."})
        project["messages"] = project["messages"][-100:]
        db.execute("UPDATE projects SET revision=?,data=?,updated_at=? WHERE id=? AND owner_id=? AND revision=?",
            (project["revision"], json.dumps(project), project["updatedAt"], project_id, row["owner_id"], saved_revision))
        diagnostics.emit(db, "generation.reviewed", owner_id=row["owner_id"], project_id=project_id,
            request_id=project.get("integration", {}).get("requestId"), job_id=job_id,
            revision=project["revision"], status="DELIVERED")
    return {"projectId": project_id, "version": version, "status": "delivered"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--integration-config")
    parser.add_argument("--project-id")
    parser.add_argument("--job-id")
    parser.add_argument("--build-revision")
    parser.add_argument("--artifact-sha256")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--approve", action="store_true")
    choice.add_argument("--list", action="store_true", help="Read pending delivery proofs without approving them")
    args = parser.parse_args()
    if not Path(args.db).is_file():
        parser.error("La base existante est requise.")
    if args.list:
        # Read-only mode must not initialize or migrate the live database.
        import sqlite3
        with sqlite3.connect(Path(args.db).resolve().as_uri() + "?mode=ro", uri=True) as db:
            rows = db.execute("SELECT id,data FROM projects").fetchall()
            proofs = []
            for project_id, raw in rows:
                if json.loads(raw).get("pipeline", {}).get("state") == "REVIEW_REQUIRED":
                    proof = pipeline.validate_proof(project_id, pipeline.private_context(db, project_id))
                    proofs.append({"projectId": project_id, **proof})
        print(json.dumps(proofs))
        return
    if not all((args.integration_config, args.project_id, args.job_id, args.build_revision, args.artifact_sha256)):
        parser.error("Une approbation exige la configuration et les quatre références exactes de la preuve.")
    transport = N8nTransport(args.integration_config)
    if transport.protocol != 2:
        parser.error("Le pipeline web v2 est requis.")
    print(json.dumps(approve(Store(args.db), transport, args.project_id, args.job_id, args.build_revision, args.artifact_sha256)))


if __name__ == "__main__":
    main()
