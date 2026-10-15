"""Repeatable HTTP journeys. Default: ephemeral app + deterministic transport.

--live-url explicitly opts into real test accounts and bounded model calls.
No passwords, session cookies or response bodies are included in the report.
"""
import argparse
import copy
import hashlib
import http.client
import json
import secrets
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from app import PortalServer, Store
from domain import SAMPLE
from integration import IntegrationWorker


class UnexpectedStatus(AssertionError):
    def __init__(self, method, path, actual, expected):
        self.actual = actual
        super().__init__(f'{method} {path.split("/")[1]}: HTTP {actual}, expected {expected}')


class Client:
    def __init__(self, base):
        self.base = urlsplit(base)
        self.origin = f'{self.base.scheme}://{self.base.netloc}'
        self.cookie = ''
        self.username = 'e2e-' + secrets.token_hex(7)
        self.password = secrets.token_urlsafe(24)

    def call(self, path, method='GET', data=None, expected=200, origin=None):
        cls = http.client.HTTPSConnection if self.base.scheme == 'https' else http.client.HTTPConnection
        connection = cls(self.base.hostname, self.base.port, timeout=25)
        headers = {'Origin': self.origin if origin is None else origin, 'Cookie': self.cookie}
        body = None
        if data is not None:
            headers['Content-Type'] = 'application/json'
            body = json.dumps(data).encode()
        connection.request(method, self.base.path.rstrip('/') + path, body, headers)
        response = connection.getresponse()
        raw, status, result_headers = response.read(), response.status, dict(response.getheaders())
        connection.close()
        if status != expected:
            raise UnexpectedStatus(method, path, status, expected)
        cookie = result_headers.get('Set-Cookie')
        if cookie is not None:
            self.cookie = cookie.split(';', 1)[0]
        value = json.loads(raw) if 'application/json' in result_headers.get('Content-Type', '') else raw
        return value, result_headers

    def register(self):
        _, headers = self.call('/api/auth/register', 'POST', {'username': self.username,
            'password': self.password, 'displayName': 'Client fictif E2E'})
        for flag in ('HttpOnly', 'SameSite=Strict', 'Path=/portal/'):
            assert flag in headers['Set-Cookie']
        if self.base.scheme == 'https':
            assert '; Secure' in headers['Set-Cookie']

    def projects(self):
        return self.call('/api/projects')[0]['projects']

    def project(self, project_id):
        return next(p for p in self.projects() if p['id'] == project_id)

    def create(self, name='Studio fictif E2E'):
        brief = {**copy.deepcopy(SAMPLE), 'businessName': name}
        return self.call('/api/projects', 'POST', {'brief': brief}, 201)[0]['project']

    def update(self, p, action, expected=200):
        value = self.call('/api/projects/' + p['id'], 'PATCH',
            {'revision': p['revision'], 'action': action}, expected)[0]
        return value.get('project')

    def wait(self, project_id, expected='succeeded'):
        deadline = time.monotonic() + 260
        while time.monotonic() < deadline:
            p = self.project(project_id)
            state = p.get('integration', {}).get('status')
            if state not in ('queued', 'running'):
                assert state == expected, f'Integration ended {state}, expected {expected}'
                return p
            time.sleep(.1 if self.base.scheme == 'http' else 2)
        raise AssertionError('Integration deadline exceeded')


def fixture_transport(payload):
    name = payload['brief']['businessName']
    if name.startswith('Fixture timeout'):
        raise TimeoutError('Synthetic timeout')
    if name.startswith('Fixture invalid'):
        return {'invalid': True}
    time.sleep(.2)
    html = ('<!doctype html><html><head><meta name="viewport" content="width=device-width">'
        '<style>body{color:#142d4e;background:#faf7ef}</style></head><body>'
        '<h1>Studio fictif</h1>' + '<p>Maquette de controle.</p>' * 20 + '</body></html>')
    return {**{k: payload[k] for k in ('schemaVersion', 'requestId', 'projectId', 'revision')},
        'reply': 'Voici une proposition pour votre projet fictif.',
        'html': html if payload['action'] == 'generate_preview' else ''}


def journey(base, isolated=False):
    checks = []
    def passed(name):
        checks.append(name)
        print('PASS ' + name, flush=True)
    alice, bob = Client(base), Client(base)
    alice.call('/api/projects', expected=401)
    alice.register(); bob.register()
    passed('registration_and_cookie_flags')
    old_cookie = alice.cookie
    alice.call('/api/auth/logout', 'POST', {})
    alice.call('/api/projects', expected=401)
    alice.cookie = old_cookie
    alice.call('/api/projects', expected=401)
    alice.cookie = ''
    alice.call('/api/auth/login', 'POST', {'username': alice.username, 'password': alice.password})
    passed('logout_revokes_session_and_login_recovers_account')
    first, second = alice.create(), alice.create('Second site fictif E2E')
    bob.update(first, {'type': 'generate_preview'}, 404)
    alice.call('/api/projects/' + first['id'], 'PATCH', {'revision': first['revision'],
        'action': {'type': 'message', 'text': 'Bonjour', 'ownerId': 'forged'}}, 400)
    alice.call('/api/projects', 'POST', {'sample': True}, 403, origin='https://other.example')
    passed('owner_identity_and_origin_enforced')
    action = {'type': 'message', 'serviceCategory': 'extra_page', 'text': 'Une page fictive pour les ateliers.'}
    def concurrent():
        try:
            alice.update(first, action)
            return 'accepted'
        except UnexpectedStatus as error:
            if error.actual != 409:
                raise
            return 'conflict'
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(lambda _: concurrent(), range(2))) == ['accepted', 'conflict']
    first = alice.project(first['id'])
    assert len(first['requests']) == 1 and first['requests'][0]['cents'] == 9900
    assert alice.project(second['id'])['revision'] == 1
    passed('concurrent_revision_and_separate_websites')
    first = alice.update(first, {'type': 'message', 'text': 'Bonjour. Comment presenter ce studio artisanal sans vente en ligne ? Palette bleu nuit et ivoire.'})
    assert first['integration']['status'] == 'queued'
    alice.update(first, {'type': 'generate_preview'}, 409)
    first = alice.wait(first['id'])
    assert first['preview'] is None
    passed('real_chat_or_fixture_transport_and_pending_guard')
    first = alice.update(first, {'type': 'generate_preview'})
    first = alice.wait(first['id'])
    assert first['preview']['generated'] and first['preview']['version'] == 1
    preview_path = '/api/projects/' + first['id'] + '/preview/1'
    html, headers = alice.call(preview_path)
    assert hashlib.sha256(html).hexdigest() == first['preview']['sha256']
    assert "sandbox; default-src 'none'" in headers['Content-Security-Policy']
    bob.call(preview_path, expected=404)
    Client(base).call(preview_path, expected=401)
    passed('private_generated_artifact_hash_and_sandbox')
    first = alice.update(first, {'type': 'preview_feedback', 'previewVersion': 1,
        'text': 'Pour la prochaine version, un titre court et une galerie plus visible. Aucun lien externe.'})
    first = alice.update(first, {'type': 'generate_preview'})
    first = alice.wait(first['id'])
    assert first['preview']['version'] == 2
    assert alice.call(preview_path)[0] == html
    alice.update(first, {'type': 'approve_preview', 'previewVersion': 1}, 409)
    passed('feedback_immutable_versions_and_stale_approval_rejected')
    if isolated:
        first = alice.update(first, {'type': 'approve_preview', 'previewVersion': 2})
        assert first['preview']['status'] == 'approved_pending_connection'
        alice.update(first, {'type': 'approve_preview', 'previewVersion': 2}, 409)
        passed('isolated_exact_version_approval_cannot_replay')
        for name, status in (('Fixture invalid result', 'failed'), ('Fixture timeout result', 'unknown')):
            broken = alice.create(name)
            alice.update(broken, {'type': 'generate_preview'})
            broken = alice.wait(broken['id'], expected=status)
            assert broken['preview'] is None
            assert alice.project(broken['id'])['integration']['requestId'] == broken['integration']['requestId']
        passed('synthetic_failures_never_create_preview_or_retry')
    assert first['subscription'] == 'not_started' and first['initialQuote']['status'] == 'draft'
    alice.call('/api/auth/logout', 'POST', {})
    alice.call('/api/auth/login', 'POST', {'username': alice.username, 'password': alice.password})
    assert alice.project(first['id'])['preview']['version'] == 2
    passed('persistence_after_relogin_and_no_payment')
    return {'checks': checks, 'passed': len(checks), 'realModel': not isolated,
        'productionApprovalSimulated': False, 'modelCallsRequested': 0 if isolated else 3}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-url', help='Explicitly run against a private HTTPS portal; creates fictional accounts, 3 model requests.')
    parser.add_argument('--output', help='Write a report without account credentials or customer content.')
    args = parser.parse_args()
    if args.live_url:
        url = urlsplit(args.live_url)
        if url.scheme != 'https' or url.path.rstrip('/') != '/portal' or url.username or url.password or url.query or url.fragment:
            parser.error('Expected a private HTTPS origin with /portal/ and no credentials or query.')
        report = journey(args.live_url)
    else:
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'portal.sqlite3'); store.integration = True
            server = PortalServer(('127.0.0.1', 0), store, directory, 'http://127.0.0.1')
            server.origin = f'http://127.0.0.1:{server.server_port}'
            worker = IntegrationWorker(store, fixture_transport)
            threads = [threading.Thread(target=server.serve_forever, daemon=True), threading.Thread(target=worker.run, daemon=True)]
            for thread in threads: thread.start()
            try:
                report = journey(server.origin + '/portal/', isolated=True)
            finally:
                worker.stop.set(); server.shutdown(); server.server_close()
                for thread in threads: thread.join(timeout=5)
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
