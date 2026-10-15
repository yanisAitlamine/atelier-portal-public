"""Private portal HTTP service. Python 3.11+, standard library only."""
import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from domain import PortalError, create_project, exact, text, transition, uid
from integration import IntegrationWorker, N8nTransport, PENDING, enqueue, initialize
import diagnostics
import pipeline
import support

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires);
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), revision INTEGER NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS projects_owner ON projects(owner_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS attempts(key TEXT NOT NULL, attempted INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS attempts_key ON attempts(key, attempted);
"""
COOKIE = "atelier_session"
LIFETIME = 7 * 24 * 3600


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, maxmem=64 * 1024 * 1024).hex()


class Store:
    def __init__(self, filename):
        self.filename = str(filename)
        with self.connection() as db:
            db.executescript(SCHEMA)
            diagnostics.initialize(db)
        self.integration = None
        self.support = None
        initialize(self)
        support.initialize(self)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.filename, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def authenticate(self, token):
        if not token:
            return None
        with self.connection() as db:
            row = db.execute("SELECT users.id,users.display_name FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>?", (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
            return dict(row) if row else None

    def auth(self, raw, register, source):
        try:
            return self._auth(raw, register, source)
        except PortalError as error:
            # _auth's context managers have already rolled back. A rejected
            # login must remain visible without retaining its raw inputs.
            reason = {401: "INVALID_CREDENTIALS", 409: "USERNAME_TAKEN",
                      429: "RATE_LIMIT"}.get(error.status, "INVALID_INPUT")
            with self.connection() as db:
                diagnostics.emit(db, "auth.register" if register else "auth.login",
                    status="rate_limited" if error.status == 429 else "denied",
                    reason=reason, http_status=error.status)
            raise

    def _auth(self, raw, register, source):
        exact(raw, ("username", "password", "displayName") if register else ("username", "password"))
        username = text(raw["username"], 3, 40).lower()
        password = raw["password"]
        if not re.fullmatch(r"[a-z0-9._-]{3,40}", username) or not isinstance(password, str) or not 12 <= len(password) <= 128:
            raise PortalError("Use a valid username and a password of 12–128 characters.")
        key = hashlib.sha256(f"{source}:{username}".encode()).hexdigest()
        current = int(time.time())
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM attempts WHERE attempted<?", (current - 300,))
            if db.execute("SELECT count(*) FROM attempts WHERE key=?", (key,)).fetchone()[0] >= 10:
                raise PortalError("Too many attempts. Please wait five minutes.", 429)
            db.execute("INSERT INTO attempts VALUES (?,?)", (key, current))
        with self.connection() as db:
            if register:
                display = text(raw["displayName"], 2, 80)
                salt = secrets.token_hex(16)
                account = {"id": uid(), "display_name": display}
                try:
                    db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (account["id"], username, display, salt, password_hash(password, salt)))
                except sqlite3.IntegrityError:
                    raise PortalError("This username is already taken.", 409)
            else:
                row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
                salt = row["salt"] if row else "00" * 16
                candidate = password_hash(password, salt)
                if not row or not hmac.compare_digest(candidate, row["password_hash"]):
                    raise PortalError("Username or password is incorrect.", 401)
                account = dict(row)
            token = secrets.token_urlsafe(32)
            db.execute("DELETE FROM sessions WHERE expires<=?", (current,))
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), account["id"], current + LIFETIME))
            diagnostics.emit(db, "auth.register" if register else "auth.login",
                             owner_id=account["id"], status="succeeded", http_status=200)
        return token, {"displayName": account["display_name"]}

    def list_projects(self, owner):
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT data FROM projects WHERE owner_id=? ORDER BY updated_at DESC LIMIT 50", (owner,))]

    def create(self, owner, raw):
        project = create_project(raw)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT count(*) FROM projects WHERE owner_id=?", (owner,)).fetchone()[0] >= 50:
                raise PortalError("This preview supports up to 50 projects per account.", 409)
            db.execute("INSERT INTO projects VALUES (?,?,?,?,?)", (project["id"], owner, project["revision"], json.dumps(project), project["updatedAt"]))
            diagnostics.emit(db, "project.created", owner_id=owner, project_id=project["id"],
                             revision=project["revision"], status="succeeded", http_status=201)
        return project

    def update(self, owner, project_id, raw):
        exact(raw, ("revision", "action"))
        if type(raw["revision"]) is not int or raw["revision"] < 1:
            raise PortalError("Invalid revision.")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT revision,data FROM projects WHERE id=? AND owner_id=?", (project_id, owner)).fetchone()
            if not row:
                raise PortalError("Project not found.", 404)
            if row["revision"] != raw["revision"]:
                raise PortalError("Project changed in another tab. Your workspace has refreshed; review and try again.", 409)
            previous = json.loads(row["data"])
            protocol = getattr(self.integration, "protocol", 1)
            if previous.get("integration", {}).get("status") in (*PENDING, "building"):
                raise PortalError("Une réponse est en cours. Attendez sa fin avant de continuer.", 409)
            action = raw["action"]
            if not isinstance(action, dict):
                raise PortalError("Invalid action.")
            if action.get("type") in ("set_sources", "stop_pipeline", "resume_pipeline") and protocol != 2:
                raise PortalError("Le pipeline documentaire n’est pas configuré.", 409)
            project = pipeline.prepare_action(previous, action) or transition(previous, action)
            if protocol == 2:
                pipeline.message_sources(project, action)
            if protocol == 2 and previous.get("pipeline", {}).get("state") == "STOPPED" and action.get("type") not in ("resume_pipeline", "stop_pipeline"):
                raise PortalError("Reprenez explicitement ce projet avant de continuer.", 409)
            if self.integration and (action["type"] in ("generate_preview", "set_sources") or protocol == 2 and action["type"] == "preview_feedback" or action["type"] == "message" and (protocol == 2 or "serviceCategory" not in action)):
                enqueue(db, owner, previous, project, action, protocol)
            elif protocol == 2 and action["type"] in ("stop_pipeline", "resume_pipeline"):
                pipeline.save_context(db, project_id, {})
            result = db.execute("UPDATE projects SET revision=?,data=?,updated_at=? WHERE id=? AND owner_id=? AND revision=?", (project["revision"], json.dumps(project), project["updatedAt"], project_id, owner, raw["revision"]))
            if result.rowcount != 1:
                raise PortalError("Project changed in another tab. Your workspace has refreshed; review and try again.", 409)
            request_id = project.get("integration", {}).get("requestId")
            if request_id == previous.get("integration", {}).get("requestId"):
                request_id = None
            if action["type"] in ("message", "preview_feedback"):
                diagnostics.emit(db, "message.accepted", owner_id=owner, project_id=project_id,
                    request_id=request_id, revision=project["revision"], status="accepted")
            sources = project.get("pipeline", {}).get("sources", {})
            if action["type"] == "set_sources" or sources.get("messageId") != previous.get("pipeline", {}).get("sources", {}).get("messageId"):
                diagnostics.emit(db, "source.requested", owner_id=owner, project_id=project_id,
                    request_id=request_id, revision=project["revision"], status="accepted")
        return project


class Handler(BaseHTTPRequestHandler):
    server_version = "Atelier"
    sys_version = ""

    def route_path(self):
        path = urlsplit(self.path).path
        prefix = self.server.base_path.rstrip("/")
        return path[len(prefix):] or "/" if prefix and (path == prefix or path.startswith(prefix + "/")) else path

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format, *args):
        # Never log bodies, cookies, credentials or private project identifiers.
        pass

    def security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'")

    def send_json(self, value, status=200, cookie=None):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.security_headers()
        self.end_headers()
        self.wfile.write(data)

    def cookie(self, token, expiry=LIFETIME):
        secure = "; Secure" if self.server.origin.startswith("https:") else ""
        return f"{COOKIE}={token}; Path={self.server.base_path}; Max-Age={expiry}; HttpOnly; SameSite=Strict{secure}"

    def session_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            return cookie[COOKIE].value if COOKIE in cookie else ""
        except Exception:
            return ""

    def user(self):
        user = self.server.store.authenticate(self.session_token())
        if not user:
            raise PortalError("Sign in to access your workspace.", 401)
        return user

    def body(self):
        if self.headers.get("Origin") != self.server.origin:
            raise PortalError("This action must come from your portal.", 403)
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise PortalError("Expected JSON.", 415)
        if self.headers.get("Transfer-Encoding"):
            raise PortalError("Chunked requests are not supported.", 400)
        length = self.headers.get("Content-Length", "")
        if not length.isdigit():
            raise PortalError("Content length required.", 411)
        if int(length) > 262144:
            raise PortalError("Request too large.", 413)
        try:
            data = json.loads(self.rfile.read(int(length)))
        except (ValueError, UnicodeDecodeError):
            raise PortalError("Invalid JSON.")
        if not isinstance(data, dict):
            raise PortalError("Expected an object.")
        return data

    def do_GET(self):
        try:
            path = self.route_path()
            if path == "/api/health":
                with self.server.store.connection() as db:
                    db.execute("SELECT 1").fetchone()
                return self.send_json({"status": "ok", "mode": "n8n_test_frontend" if self.server.store.integration else "portal_only"})
            if path == "/api/session":
                return self.send_json({"user": {"displayName": self.user()["display_name"]}})
            if path == "/api/pipeline":
                self.user()
                transport = self.server.store.integration
                return self.send_json({"available": getattr(transport, "protocol", 1) == 2,
                    "driveAccount": getattr(transport, "drive_account", "")})
            if path == "/api/projects":
                return self.send_json({"projects": self.server.store.list_projects(self.user()["id"])})
            match = re.fullmatch(r"/api/projects/([0-9a-f-]{36})/support", path)
            if match:
                return self.send_json({"available": bool(self.server.store.support), "tickets": support.list_tickets(self.server.store, self.user()["id"], match[1])})
            match = re.fullmatch(r"/api/projects/([0-9a-f-]{36})/preview/([1-9][0-9]*)", path)
            if match:
                owner = self.user()["id"]
                with self.server.store.connection() as db:
                    artifact = db.execute("SELECT a.html FROM preview_artifacts a JOIN projects p ON p.id=a.project_id WHERE p.owner_id=? AND a.project_id=? AND a.version=?", (owner, match[1], int(match[2]))).fetchone()
                if not artifact:
                    raise PortalError("Maquette introuvable.", 404)
                data = artifact[0].encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'self'; form-action 'none'; base-uri 'none'")
                self.end_headers()
                self.wfile.write(data)
                return
            if path.startswith("/api/"):
                raise PortalError("Not found.", 404)
            target = (self.server.static / path.lstrip("/")).resolve()
            if not target.is_relative_to(self.server.static):
                raise PortalError("Not found.", 404)
            if not target.is_file():
                if Path(path).suffix:
                    raise PortalError("Not found.", 404)
                target = self.server.static / "index.html"
            if not target.is_file():
                raise PortalError("Build the frontend before starting the portal.", 503)
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(target)[0] or "application/octet-stream")
            self.send_header("Cache-Control", "public, max-age=31536000, immutable" if "/assets/" in path else "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.security_headers()
            self.end_headers()
            self.wfile.write(data)
        except PortalError as e:
            self.send_json({"error": str(e)}, e.status)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:
            self.send_json({"error": "The portal could not load this request."}, 500)

    def do_POST(self):
        self.mutate()

    def do_PATCH(self):
        self.mutate()

    def mutate(self):
        try:
            raw = self.body()
            path = self.route_path()
            if self.command == "POST" and path in ("/api/auth/login", "/api/auth/register"):
                source = self.headers.get("X-Forwarded-For", "").split(",")[-1].strip() or self.client_address[0]
                token, user = self.server.store.auth(raw, path.endswith("register"), source)
                return self.send_json({"user": user}, cookie=self.cookie(token))
            user = self.user()
            if self.command == "POST" and path == "/api/auth/logout":
                exact(raw, ())
                with self.server.store.connection() as db:
                    db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(self.session_token().encode()).hexdigest(),))
                    diagnostics.emit(db, "auth.logout", owner_id=user["id"], status="succeeded", http_status=200)
                return self.send_json({"ok": True}, cookie=self.cookie("", 0))
            if self.command == "POST" and path == "/api/projects":
                return self.send_json({"project": self.server.store.create(user["id"], raw)}, 201)
            match = re.fullmatch(r"/api/projects/([0-9a-f-]{36})/support", path)
            if self.command == "POST" and match:
                return self.send_json({"ticket": support.create_ticket(self.server.store, user["id"], match[1], raw, self.server.origin, self.server.base_path)}, 202)
            match = re.fullmatch(r"/api/projects/([0-9a-f-]{36})", path)
            if self.command == "PATCH" and match:
                return self.send_json({"project": self.server.store.update(user["id"], match[1], raw)})
            raise PortalError("Not found.", 404)
        except PortalError as e:
            self.send_json({"error": str(e)}, e.status)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:
            self.send_json({"error": "Your changes could not be saved. Please try again."}, 500)


class PortalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store, static, origin, base_path="/portal/"):
        self.store, self.static, self.origin, self.base_path = store, Path(static).resolve(), origin.rstrip("/"), base_path
        super().__init__(address, Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "::1"])
    parser.add_argument("--port", type=int, default=4180)
    parser.add_argument("--database", default=os.environ.get("PORTAL_DATABASE", ".data/portal.sqlite3"))
    parser.add_argument("--static", default=os.environ.get("PORTAL_STATIC", "dist"))
    parser.add_argument("--origin", default=os.environ.get("PORTAL_ORIGIN", "http://127.0.0.1:5173"))
    parser.add_argument("--integration-config", default=os.environ.get("PORTAL_INTEGRATION_CONFIG", ""))
    parser.add_argument("--support-config", default=os.environ.get("PORTAL_SUPPORT_CONFIG", ""))
    args = parser.parse_args()
    if urlsplit(args.origin).scheme not in ("http", "https") or urlsplit(args.origin).path not in ("", "/"):
        parser.error("Origin must be an HTTP(S) origin without a path.")
    os.umask(0o077)
    Path(args.database).resolve().parent.mkdir(parents=True, exist_ok=True)
    server = PortalServer((args.host, args.port), Store(args.database), args.static, args.origin)
    if args.integration_config:
        server.store.integration = N8nTransport(args.integration_config)
        worker = IntegrationWorker(server.store, server.store.integration)
        threading.Thread(target=worker.run, daemon=True).start()
    if args.support_config:
        server.store.support = support.SupportTransport(args.support_config)
        support_worker = support.SupportWorker(server.store, server.store.support)
        threading.Thread(target=support_worker.run, daemon=True).start()
    print(f"Atelier portal listening on loopback port {args.port}.", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
