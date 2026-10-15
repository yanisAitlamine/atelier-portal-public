"""Temporary accounts and database; no production integrations."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from app import Store
from domain import SAMPLE, PortalError
from integration import IntegrationWorker, validate_result

HTML = '<!doctype html><html><head><style>body{color:#123}</style></head><body><h1>Fictional studio</h1>' + '<p>Design sample.</p>' * 20 + '</body></html>'


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'portal.sqlite3')
        token, _ = self.store.auth({'username':'test-user','password':'fictional-password-123','displayName':'Test'}, True, 'fixture')
        self.owner = self.store.authenticate(token)['id']
        self.store.integration = True
        self.project = self.store.create(self.owner, {'brief':copy.deepcopy(SAMPLE)})
        self.calls = []
        self.worker = IntegrationWorker(self.store, self.transport)

    def tearDown(self):
        self.temp.cleanup()

    def transport(self, payload):
        self.calls.append(payload)
        return {**{k:payload[k] for k in ('schemaVersion','requestId','projectId','revision')},
            'reply':'Votre projet fictif est prêt à examiner.', 'html':HTML if payload['action']=='generate_preview' else ''}

    def mutate(self, kind='message', **data):
        p = self.store.list_projects(self.owner)[0]
        return self.store.update(self.owner, p['id'], {'revision':p['revision'],'action':{'type':kind, **data}})

    def test_durable_queue_exactly_one_claim_and_refresh_no_repeat(self):
        p = self.mutate(text='Conseil sur les couleurs de mon site ?')
        self.assertEqual(p['integration']['status'],'queued')
        for _ in range(3): self.store.list_projects(self.owner)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.worker.once(), range(2)))
        self.assertEqual(sum(results),1)
        self.assertEqual(len(self.calls),1)
        self.assertFalse(self.worker.once())
        p = self.store.list_projects(self.owner)[0]
        self.assertEqual(p['integration']['status'],'succeeded')
        self.assertIsNone(p['preview'])
        self.assertEqual(p['subscription'],'not_started')

    def test_pending_blocks_other_mutations_and_wrong_owner(self):
        p = self.mutate(text='Bonjour, quelles couleurs ?')
        for owner in (self.owner,'other-owner'):
            with self.assertRaises(PortalError):
                self.store.update(owner,p['id'],{'revision':p['revision'],'action':{'type':'generate_preview'}})
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM integration_jobs').fetchone()[0],1)

    def test_immutable_artifacts_feedback_new_version_exact_approval(self):
        self.mutate('generate_preview'); self.worker.once()
        first = self.store.list_projects(self.owner)[0]
        self.assertEqual(first['preview']['version'],1)
        self.assertTrue(first['preview']['generated'])
        self.assertEqual(first['preview']['sha256'],hashlib.sha256(HTML.encode()).hexdigest())
        self.mutate('preview_feedback',previewVersion=1,text='Préférer un fond clair et du bleu.')
        self.mutate('generate_preview'); self.worker.once()
        with self.assertRaises(PortalError): self.mutate('approve_preview',previewVersion=1)
        p=self.mutate('approve_preview',previewVersion=2)
        self.assertEqual(p['preview']['status'],'approved_pending_connection')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM preview_artifacts').fetchone()[0],2)
        self.assertIn('fond clair',str(self.calls[-1]['messages']))
        self.assertEqual(p['initialQuote']['status'],'draft')

    def test_untrusted_response_and_script_never_become_preview(self):
        p = self.mutate('generate_preview')
        def invalid(payload):
            return {**self.transport(payload),'projectId':'other'}
        self.worker.transport=invalid
        self.worker.once()
        p=self.store.list_projects(self.owner)[0]
        self.assertEqual(p['integration']['status'],'failed')
        self.assertIsNone(p['preview'])
        payload=self.calls[0]; response=self.transport(payload)
        for html in (HTML.replace('</body>','<script>alert(1)</script></body>'), HTML.replace('<h1>','<h1 onclick="alert(1)">'),
                     HTML.replace('</head>','<meta http-equiv="refresh" content="0;url=https://example.test"></head>'),
                     HTML.replace('</body>','<a href="https://example.test">Outside</a></body>')):
            with self.assertRaises(ValueError): validate_result(payload,{**response,'html':html})

    def test_restart_and_transport_timeout_are_uncertain_without_retry(self):
        self.mutate('generate_preview')
        with self.store.connection() as db: db.execute("UPDATE integration_jobs SET status='running'")
        self.worker.recover()
        self.assertEqual(self.store.list_projects(self.owner)[0]['integration']['status'],'unknown')
        self.assertFalse(self.worker.once())
        self.mutate(text='Nouvelle demande explicite de conseils.')
        def timeout(payload): raise TimeoutError()
        self.worker.transport=timeout
        self.worker.once()
        self.assertEqual(self.store.list_projects(self.owner)[0]['integration']['status'],'unknown')
        self.assertFalse(self.worker.once())

    def test_failed_regeneration_preserves_existing_artifact_and_review(self):
        self.mutate('generate_preview'); self.worker.once()
        before=self.store.list_projects(self.owner)[0]['preview']
        self.mutate('generate_preview')
        self.worker.transport=lambda payload: {'invalid': True}
        self.worker.once()
        after=self.store.list_projects(self.owner)[0]
        self.assertEqual(after['integration']['status'],'failed')
        self.assertEqual(after['preview'],before)
        with self.store.connection() as db:
            rows=db.execute('SELECT version,html,sha256 FROM preview_artifacts').fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['html'],HTML)
        self.assertEqual(rows[0]['sha256'],before['sha256'])
        self.assertFalse(self.worker.once())

    def test_daily_quota_is_atomic_and_action_does_not_leak_into_job(self):
        with self.store.connection() as db:
            import time
            for i in range(30): db.execute('INSERT INTO integration_jobs VALUES (?,?,?,?,?,?)',(str(i),self.project['id'],self.owner,'succeeded',int(time.time()),'{}'))
        with self.assertRaises(PortalError) as e: self.mutate('generate_preview')
        self.assertEqual(e.exception.status,429)
        p=self.store.list_projects(self.owner)[0]
        self.assertNotIn('integration',p)
        self.assertEqual(p['revision'],1)

    def test_large_unicode_context_fits_workflow_and_keeps_latest_message(self):
        with self.store.connection() as db:
            p=self.store.list_projects(self.owner)[0]
            p['messages']=[{'id':str(i),'at':p['createdAt'],'role':'assistant','text':'😀"\\'*2000} for i in range(19)]
            db.execute('UPDATE projects SET data=? WHERE id=?',(json.dumps(p),p['id']))
        self.mutate(text='Dernière demande : conserver cette phrase entière.')
        self.worker.once()
        payload=self.calls[0]
        self.assertLessEqual(len(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-16-le'))//2,95000)
        self.assertLess(len(payload['messages']),20)
        self.assertEqual(payload['messages'][-1]['text'],'Dernière demande : conserver cette phrase entière.')

    def test_advanced_revision_cannot_replace_preview_or_approval(self):
        self.mutate('generate_preview');self.worker.once()
        self.mutate('generate_preview')
        with self.store.connection() as db:
            p=self.store.list_projects(self.owner)[0]
            p['revision']+=1
            p['preview']['status']='approved_pending_connection'
            before=copy.deepcopy(p)
            db.execute('UPDATE projects SET revision=?,data=? WHERE id=?',(p['revision'],json.dumps(p),p['id']))
        self.worker.once()
        after=self.store.list_projects(self.owner)[0]
        self.assertEqual(after['preview'],before['preview'])
        self.assertEqual(after['messages'],before['messages'])
        self.assertEqual(after['integration']['status'],'stale')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM preview_artifacts').fetchone()[0],1)
            self.assertTrue(all(r[0]=='{}' for r in db.execute('SELECT payload FROM integration_jobs')))

    def test_terminal_payloads_are_redacted_and_old_snapshots_scrubbed(self):
        self.mutate(text='Texte fictif privé qui ne doit pas rester dans le job.')
        with self.store.connection() as db:
            queued=db.execute('SELECT payload FROM integration_jobs').fetchone()[0]
            self.assertIn('Texte fictif',queued)
        self.worker.once()
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT payload FROM integration_jobs').fetchone()[0],'{}')
            db.execute('UPDATE integration_jobs SET payload=?',(queued,))
        Store(self.store.filename)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT payload FROM integration_jobs').fetchone()[0],'{}')

    def test_pricing_comes_from_canonical_quote_and_catalog(self):
        with self.store.connection() as db:
            p=self.store.list_projects(self.owner)[0]
            p['initialQuote'].update(cents=65000,monthlyCents=4500)
            db.execute('UPDATE projects SET data=? WHERE id=?',(json.dumps(p),p['id']))
        self.mutate(text='Quel est le tarif de mon devis ?');self.worker.once()
        self.assertEqual(self.calls[0]['pricing'],{'currency':'EUR','creationCents':65000,'monthlyCents':4500,'extraPageCents':9900})

    def test_preview_http_requires_owner_and_enforces_sandbox(self):
        import http.client
        import threading
        from app import PortalServer
        self.mutate('generate_preview'); self.worker.once()
        token, _ = self.store.auth({'username':'test-user','password':'fictional-password-123'},False,'fixture')
        server=PortalServer(('127.0.0.1',0),self.store,self.temp.name,'http://127.0.0.1')
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for prefix in ('','/portal'):
                path=f'{prefix}/api/projects/{self.project["id"]}/preview/1'
                for cookie,status in (('',401),(f'atelier_session={token}',200)):
                    connection=http.client.HTTPConnection('127.0.0.1',server.server_port)
                    connection.request('GET',path,headers={'Cookie':cookie})
                    response=connection.getresponse(); body=response.read()
                    self.assertEqual(response.status,status)
                    if status==200:
                        self.assertIn("sandbox; default-src 'none'",response.getheader('Content-Security-Policy'))
                        self.assertEqual(body.decode(),HTML)
                    connection.close()
            other, _ = self.store.auth({'username':'other-user','password':'fictional-password-456','displayName':'Other'},True,'fixture')
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port)
            connection.request('GET',f'/api/projects/{self.project["id"]}/preview/1',headers={'Cookie':f'atelier_session={other}'})
            response=connection.getresponse();response.read()
            self.assertEqual(response.status,404)
            connection.close()
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__': unittest.main()
