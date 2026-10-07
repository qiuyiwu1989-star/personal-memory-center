"""Actual LocalVault client/bridge against a disposable loopback MCP server.

Usage: .venv/bin/python scripts/check_localvault_compatibility.py EXTERNAL_SOURCE_ROOT
External code is read only. All documents, grants and databases are synthetic.
This reproduces incompatibilities; success does not certify a user installation.
"""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(source_root, patched=False):
    import uvicorn
    from pipeline.memory_center.core import Store
    from pipeline.memory_center.service import create_app
    from pipeline.memory_center.source_lifecycle import setup

    class NoModel:
        configured = False
        calls = 0
        def extract(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError('Model forbidden')

    external = Path(source_root).resolve()
    if not (external / 'mcp-server/lib/upstream/client.js').is_file():
        raise ValueError('Provide the read-only LocalVault source root')
    token = 'synthetic-localvault-loopback-only'
    scope = 'agent:synthetic-localvault-inbox'
    grant = {'id': 'synthetic-localvault', 'owner': 'synthetic-owner',
             'scopes': [scope], 'actions': ['read', 'write', 'source_read'],
             'archive_only': True, 'trusted_user': False,
             'token_sha256': hashlib.sha256(token.encode()).hexdigest()}
    model = NoModel()
    with tempfile.TemporaryDirectory(prefix='localvault-compatibility-') as directory:
        store = Store(Path(directory) / 'memory')
        setup(store)
        app = create_app(store, lambda: [grant], model, run_worker=False)
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level='critical', access_log=False))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(.01)
            if not server.started:
                raise RuntimeError('Loopback server did not start')
            result = subprocess.run(['node', str(ROOT / 'scripts/localvault-compatibility.cjs'),
                str(external), f'http://127.0.0.1:{port}/mcp/', directory, token, scope, 'patched' if patched else 'original'],
                capture_output=True, text=True, timeout=90)
            if result.returncode:
                raise RuntimeError(result.stderr + result.stdout)
            report = json.loads(result.stdout)
            with store.db() as db:
                report['stored_sources'] = db.execute('SELECT count(*) n FROM sources').fetchone()['n']
                report['jobs_by_state'] = {r['state']: r['n'] for r in db.execute(
                    'SELECT state,count(*) n FROM jobs GROUP BY state').fetchall()}
            if model.calls:
                raise AssertionError('Unexpected model call')
            report['model_calls'] = model.calls
            return report
        finally:
            server.should_exit = True
            thread.join(10)
            sock.close()


if __name__ == '__main__':
    if len(sys.argv) not in (2, 3):
        raise SystemExit('Expected LocalVault source root')
    print(json.dumps(run(sys.argv[1], len(sys.argv) == 3 and sys.argv[2] == '--patched'), ensure_ascii=False, indent=2))
