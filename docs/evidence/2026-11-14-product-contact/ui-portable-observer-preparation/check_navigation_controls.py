"""Exercise the repaired observer, not a reference UI."""
import importlib.util
import os
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

p = Path('/tmp/hla-ui-portable-observer-preparation/files/tests/test_attention_current_ui_acceptance.py')
spec = importlib.util.spec_from_file_location('repaired_acceptance', p)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/target':
            body = '<main><h1>Arrived at target</h1></main>'
        else:
            mode = self.path.strip('/')
            target = '/target' if mode == 'correct' else '/wrong'
            action = '' if mode == 'none' else f"setTimeout(()=>history.pushState({{}},'', '{target}'),200)"
            body = f"<main><div class='attentionRow'><span>Fixture row</span><a href='/target' onclick=\"event.preventDefault();{action}\">Review</a></div></main>"
        payload = body.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
with closing(socket.socket()) as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
name = 'hla-ui-observer-control-' + uuid.uuid4().hex[:12]
cid = None
try:
    modules = Path('/projects/dev/homelab-analytics/apps/web/frontend/node_modules')
    cid = subprocess.check_output(['docker', 'run', '-d', '--name', name, '--network', 'host', '--ipc=host',
                                   '-v', str(modules) + ':/opt/node_modules:ro', module.IMAGE,
                                   'node', '/opt/node_modules/playwright/cli.js', 'run-server',
                                   '--host', '127.0.0.1', '--port', str(port)], text=True).strip()
    for _ in range(40):
        logs = subprocess.run(['docker', 'logs', cid], capture_output=True, text=True)
        if 'Listening on' in logs.stdout + logs.stderr:
            break
        time.sleep(.5)
    else:
        raise RuntimeError('browser did not start: ' + logs.stdout + logs.stderr)
    with tempfile.TemporaryDirectory(prefix='observer-controls-') as directory:
        script = Path(directory) / 'browser.cjs'
        # Only the failure deadline is shortened for this negative control.
        assert module.BROWSER.count('timeout:15000') == 2
        script.write_text(module.BROWSER.replace('timeout:15000', 'timeout:1200'))
        env = dict(os.environ, PATH=module.NODE + ':' + os.environ['PATH'], NODE_PATH=str(modules))
        for mechanism in ('keyboard', 'click'):
            for mode in ('correct', 'wrong', 'none'):
                title, href = ('Fixture row', '') if mechanism == 'keyboard' else ('', '/target')
                command = ['node', str(script), f'ws://127.0.0.1:{port}/',
                           f'http://127.0.0.1:{server.server_port}/{mode}', title, href]
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
                expected = mode == 'correct'
                assert (result.returncode == 0) == expected, (mechanism, mode, result.stdout, result.stderr)
                if expected:
                    assert '"/target"' in result.stdout or '/target"' in result.stdout, result.stdout
                else:
                    assert 'Timeout' in result.stderr, result.stderr
                print(mechanism, mode, 'accepted' if expected else 'rejected')
finally:
    if cid:
        subprocess.run(['docker', 'rm', '-f', cid], capture_output=True)
        inv = subprocess.run(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}}'], capture_output=True, text=True)
        assert inv.returncode == 0 and cid not in inv.stdout.splitlines(), 'owned browser remains'
        print('owned browser absent')
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
