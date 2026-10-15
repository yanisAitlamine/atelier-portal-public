"""Browser failure fixture, loopback only; never used by the production service."""
import argparse
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from app import PortalServer, Store
from integration import IntegrationWorker
from support import SupportWorker
from e2e_portal import fixture_transport


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--port', type=int, default=4182)
    parser.add_argument('--pipeline-v2', action='store_true', help='Use fictional Drive/build proof responses, with no external calls')
    args = parser.parse_args()
    directory = Path(args.directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    mode_file = directory / 'mode.json'
    if not mode_file.exists():
        mode_file.write_text('{"mode":"normal"}')
    from test_pipeline import Transport
    pipeline_transport = Transport() if args.pipeline_v2 else None
    def transport(payload):
        mode = json.loads(mode_file.read_text())['mode']
        if mode == 'invalid':
            return {'invalid': True}
        if mode == 'timeout':
            raise TimeoutError('Synthetic browser fixture timeout')
        if pipeline_transport:
            pipeline_transport.mode = 'incomplete' if mode == 'incomplete' else 'ready'
            result = pipeline_transport(payload)
            if payload['action'] == 'message':
                result['pipeline']['facts'] = [{'field': 'goal', 'value': 'Présenter un atelier fictif',
                    'quote': 'Présenter un atelier fictif', 'source': 'Cahier des charges fictif · page 30'}]
                if payload.get('source'):
                    result['pipeline']['sources'] = {'status': 'REVIEW_REQUIRED' if mode == 'incomplete' else 'READ', 'files': [
                        {'name': 'Cahier des charges fictif.pdf', 'mimeType': 'application/pdf', 'version': '1'},
                        {'name': 'Image fictive.png', 'mimeType': 'image/png', 'version': '1'}], 'pages': 30, 'characters': 16000}
            return result
        return fixture_transport(payload)
    if pipeline_transport:
        transport.protocol = 2
        transport.drive_account = pipeline_transport.drive_account
    store = Store(directory / 'portal.sqlite3'); store.integration = transport
    worker = IntegrationWorker(store, transport)
    def support_transport(payload):
        if json.loads(mode_file.read_text()).get('support') == 'timeout':
            raise TimeoutError('Synthetic support timeout')
        (directory / 'support-capture.json').write_text(json.dumps(payload), encoding='utf-8')
        return {'schemaVersion': 1, 'ticketId': payload['ticketId'], 'status': 'sent', 'messageId': 'fixture-receipt'}
    store.support = True
    support_worker = SupportWorker(store, support_transport)
    server = PortalServer(('127.0.0.1', args.port), store,
        Path(__file__).resolve().parents[1] / 'dist', f'http://127.0.0.1:{args.port}')
    threading.Thread(target=worker.run, daemon=True).start()
    threading.Thread(target=support_worker.run, daemon=True).start()
    print(f'Isolated browser fixture http://127.0.0.1:{args.port}/portal/', flush=True)
    try:
        server.serve_forever()
    finally:
        worker.stop.set(); server.server_close()
        support_worker.stop.set()


if __name__ == '__main__':
    main()
