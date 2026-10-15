"""Support journey with real HTTP/storage and an isolated mail transport."""
import base64
import copy
import hashlib
import json
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from e2e_portal import Client, fixture_transport
from app import PortalServer, Store
from domain import PortalError, SAMPLE
from integration import IntegrationWorker
from support import SupportWorker, create_ticket, list_tickets


class SupportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'portal.sqlite3')
        token, _ = self.store.auth({'username': 'client-test', 'password': 'fictional-password-123', 'displayName': 'Client fictif'}, True, 'fixture')
        self.owner = self.store.authenticate(token)['id']
        self.store.support = True
        self.project = self.store.create(self.owner, {'brief': copy.deepcopy(SAMPLE)})
        self.calls = []
        def transport(payload):
            self.calls.append(payload)
            return {'schemaVersion': 1, 'ticketId': payload['ticketId'], 'status': 'sent', 'messageId': 'fixture-receipt'}
        self.worker = SupportWorker(self.store, transport)

    def tearDown(self):
        self.temp.cleanup()

    def raw(self, **values):
        return {**{'requestId': str(uuid.uuid4()), 'revision': self.project['revision'], 'email': 'client@example.test',
            'message': 'La génération échoue toujours, pouvez-vous regarder ?', 'consent': True}, **values}

    def send(self, raw=None, owner=None, project=None):
        return create_ticket(self.store, owner or self.owner, project or self.project['id'], raw or self.raw(), 'https://portal.example.test', '/portal/')

    def test_snapshot_includes_generated_artifact_and_is_immutable(self):
        self.store.integration = True
        self.project = self.store.update(self.owner, self.project['id'], {'revision': 1, 'action': {'type': 'generate_preview'}})
        IntegrationWorker(self.store, fixture_transport).once()
        self.project = self.store.list_projects(self.owner)[0]
        raw = self.raw()
        ticket = self.send(raw)
        before = copy.deepcopy(self.project)
        self.store.update(self.owner, self.project['id'], {'revision': self.project['revision'], 'action': {'type': 'message', 'text': 'Message postérieur au signalement.'}})
        self.worker.once()
        payload = self.calls[0]
        context = json.loads(base64.b64decode(payload['attachments'][0]['data']))
        self.assertEqual(context['messages'], before['messages'])
        self.assertEqual(context['brief'], before['brief'])
        self.assertEqual(context['previewSha256'], before['preview']['sha256'])
        self.assertTrue(context['previewUrl'].endswith('/preview/1'))
        self.assertIn('<html>', base64.b64decode(payload['attachments'][1]['data']).decode())
        attachment = base64.b64decode(payload['attachments'][1]['data'])
        self.assertIn(b"default-src 'none'", attachment[:300])
        self.assertEqual(context['attachmentSha256'], hashlib.sha256(attachment).hexdigest())
        self.assertNotIn('Message postérieur', str(payload))
        self.assertNotIn('owner_id', payload)
        self.assertEqual(list_tickets(self.store, self.owner, self.project['id'])[0]['status'], 'sent')
        self.assertEqual(self.send(raw)['id'], ticket['id'])  # Same request after a project change.
        self.assertFalse(self.worker.once())

    def test_support_works_during_generation_and_without_preview(self):
        self.store.integration = True
        self.project = self.store.update(self.owner, self.project['id'], {'revision': 1, 'action': {'type': 'generate_preview'}})
        self.send(); self.worker.once()
        payload = self.calls[0]
        self.assertEqual(len(payload['attachments']), 1)
        context = json.loads(base64.b64decode(payload['attachments'][0]['data']))
        self.assertIsNone(context['previewUrl'])
        self.assertEqual(context['generation']['status'], 'queued')
        self.assertEqual(self.store.list_projects(self.owner)[0]['integration']['status'], 'queued')

    def test_concurrent_duplicate_submission_and_claim_send_once(self):
        raw = self.raw()
        with ThreadPoolExecutor(2) as pool:
            tickets = list(pool.map(lambda _: self.send(raw), range(2)))
        self.assertEqual(tickets[0]['id'], tickets[1]['id'])
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sum(pool.map(lambda _: self.worker.once(), range(2))), 1)
        self.assertEqual(len(self.calls), 1)
        with self.assertRaises(PortalError): self.send({**raw, 'message': 'Un autre problème modifié.'})

    def test_timeout_receipt_mismatch_and_restart_do_not_resend(self):
        self.send()
        self.worker.transport = lambda _: {'schemaVersion': 1, 'ticketId': str(uuid.uuid4()), 'status': 'sent', 'messageId': 'receipt'}
        self.worker.once()
        self.assertEqual(list_tickets(self.store, self.owner, self.project['id'])[0]['status'], 'unknown')
        self.assertFalse(self.worker.once())
        with self.store.connection() as db: db.execute("UPDATE support_tickets SET status='running'")
        self.worker.recover()
        self.assertFalse(self.worker.once())
        with self.store.connection() as db: db.execute("UPDATE support_tickets SET status='queued'")
        def timeout(_): raise TimeoutError('Synthetic lost receipt')
        self.worker.transport = timeout
        self.worker.once()
        self.assertFalse(self.worker.once())
        self.assertEqual(list_tickets(self.store, self.owner, self.project['id'])[0]['status'], 'unknown')

    def test_ownership_strict_schema_consent_and_headers(self):
        for changes in ({'recipient': 'attacker@example.test'}, {'previewUrl': 'https://evil.test'}, {'messages': []},
                        {'consent': False}, {'consent': 1}, {'revision': True}, {'email': 'a@example.test\r\nBcc: x@example.test'},
                        {'email': 'a@example.test,b@example.test'}, {'message': 'short'}):
            with self.assertRaises(PortalError): self.send(self.raw(**changes))
        for operation in (lambda: self.send(owner='other-account'), lambda: list_tickets(self.store, 'other-account', self.project['id'])):
            with self.assertRaises(PortalError) as e: operation()
            self.assertEqual(e.exception.status, 404)
        with self.assertRaises(PortalError) as e: self.send(self.raw(revision=42))
        self.assertEqual(e.exception.status, 409)
        self.assertEqual(list_tickets(self.store, self.owner, self.project['id']), [])

    def test_rate_limit_and_disabled_delivery(self):
        self.store.support = None
        with self.assertRaises(PortalError) as e: self.send()
        self.assertEqual(e.exception.status, 503)
        self.store.support = True
        self.send()
        with self.assertRaises(PortalError) as e: self.send()
        self.assertEqual(e.exception.status, 429)
        self.assertEqual(len(list_tickets(self.store, self.owner, self.project['id'])), 1)

    def test_daily_limit_and_old_pending_ticket_remain_blocking(self):
        self.send()
        with self.store.connection() as db: db.execute('UPDATE support_tickets SET created=created-90000')
        with self.assertRaises(PortalError) as e: self.send()
        self.assertEqual(e.exception.status, 429)
        self.worker.once()
        for _ in range(5):
            self.send(); self.worker.once()
            with self.store.connection() as db: db.execute('UPDATE support_tickets SET created=created-61')
        with self.assertRaises(PortalError) as e: self.send()
        self.assertEqual(e.exception.status, 429)

    def test_complete_http_customer_support_journey(self):
        server = PortalServer(('127.0.0.1', 0), self.store, self.temp.name, 'http://127.0.0.1')
        server.origin = f'http://127.0.0.1:{server.server_port}'
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        client, outsider = Client(server.origin + '/portal/'), Client(server.origin + '/portal/')
        try:
            client.register(); outsider.register()
            p = client.create()
            path = f'/api/projects/{p["id"]}/support'
            outsider.call(path, expected=404)
            raw = self.raw(revision=p['revision'])
            client.call(path, 'POST', raw, 403, origin='https://evil.test')
            ticket = client.call(path, 'POST', raw, 202)[0]['ticket']
            self.assertEqual(ticket['status'], 'queued')
            self.worker.once()
            data = client.call(path)[0]
            self.assertEqual(data['tickets'][0]['status'], 'sent')
            self.assertEqual(set(data['tickets'][0]), {'id', 'status', 'created'})
            self.assertEqual(client.call(path, 'POST', raw, 202)[0]['ticket']['id'], ticket['id'])
            self.assertEqual(len(self.calls), 1)
            outsider.call(path, 'POST', self.raw(), 404)
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
