"""Native local OpenCode adapter with a pinned, isolated loopback provider.

local/<profile> is a separate provider, never an alias for OpenCode Go. No
configured endpoint, an unsupported native schema, a busy inference lane or a
failed local server fails the attempt; none selects a paid/remote fallback.
"""
from __future__ import annotations

import json
import contextlib
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from .child_process import communicate

PROVIDER = 'lanectl-local'
DEFAULT_LANE_HELPER = Path('/projects/dev/local-inference/scripts/lib/lane.py')


def profile_for(model):
    match = re.fullmatch(r'local/([A-Za-z0-9][A-Za-z0-9_.-]{0,63})', model)
    if not match:
        raise ValueError('local model must be local/<explicit-profile>')
    return match.group(1)


def validate_origin(origin):
    parsed = urlsplit(origin)
    if (parsed.scheme not in ('http', 'https') or parsed.hostname not in ('127.0.0.1', '::1')
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path.rstrip('/') != '/v1' or not parsed.port):
        raise ValueError('local origin must be an explicit literal loopback origin with port and /v1')
    return origin.rstrip('/')



def configured(model):
    """Eligibility needs an explicit local endpoint; this is not qualification."""
    try:
        profile_for(model)
        validate_origin(os.environ.get('LANECTL_LOCAL_BASE_URL', ''))
        return True
    except (TypeError, ValueError):
        return False


def validate_version(text):
    match = re.search(r'(?:^|\s|v)(2\.\d+\.\d+)\b', text)
    if not match:
        raise ValueError('local adapter requires the qualified OpenCode 2 configuration schema')
    version = match.group(1)
    if tuple(map(int, version.split('.'))) < (2, 2, 3):
        raise ValueError('local adapter requires OpenCode 2.2.3 or newer')
    return version


def provider_config(profile, origin):
    return {
        'model': f'{PROVIDER}/{profile}', 'update': 'disable', 'snapshots': False,
        'providers': {PROVIDER: {
            'name': 'Explicit local inference', 'package': '@opencode/ai/providers/openai-compatible',
            'settings': {'baseURL': validate_origin(origin), 'apiKey': 'local-only'},
            'models': {profile: {'name': profile, 'limit': {'context': 32768, 'output': 8192}}},
        }},
        'policies': [
            {'action': 'provider.use', 'resource': '*', 'effect': 'deny'},
            {'action': 'provider.use', 'resource': PROVIDER, 'effect': 'allow'},
            {'action': 'plugin.use', 'resource': '*', 'effect': 'deny'},
            {'action': 'integration.use', 'resource': '*', 'effect': 'deny'},
            {'action': 'integration.use', 'resource': PROVIDER, 'effect': 'allow'},
            {'action': 'mcp.use', 'resource': '*', 'effect': 'deny'},
            {'action': 'skill.use', 'resource': '*', 'effect': 'deny'},
        ],
        'permissions': [
            {'action': '*', 'resource': '*', 'effect': 'deny'},
            *({'action': action, 'resource': '*', 'effect': 'allow'}
              for action in ('read', 'edit', 'glob', 'grep', 'shell')),
            {'action': 'external_directory', 'resource': '*', 'effect': 'deny'},
            {'action': 'shell', 'resource': 'git push *', 'effect': 'deny'},
        ],
        'mcp': {'servers': {}}, 'plugins': [],
        'compaction': {'auto': False},
    }



@contextlib.contextmanager
def local_relay(origin, timeout_s):
    """Keep model requests on the selected origin, including redirect refusal."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            self.forward()
        def do_POST(self):
            self.forward()
        def forward(self):
            if self.path not in ('/v1/chat/completions', '/v1/models'):
                self.send_error(400, 'unsupported local model endpoint')
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 <= size <= 2 * 1024 * 1024:
                    raise ValueError('request exceeds local model bound')
                body = self.rfile.read(size) if size else None
                request = urllib.request.Request(origin + self.path[len('/v1'):],
                    data=body, method=self.command,
                    headers={'Content-Type': 'application/json', 'Authorization': 'Bearer local-only'})
                with opener.open(request, timeout=timeout_s) as response:
                    data = response.read(8 * 1024 * 1024 + 1)
                    if len(data) > 8 * 1024 * 1024:
                        raise ValueError('response exceeds local model bound')
                    self.send_response(response.status)
                    self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
            except (OSError, ValueError, urllib.error.URLError):
                # Do not expose upstream redirects or error bodies to a client
                # that could follow a remote Location or print private content.
                self.send_error(502, 'selected local model unavailable')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _clean_env(env):
    # Keep transport/runtime basics, never auth, provider overrides, proxy or
    # telemetry exporters. HOME remains the operator's value, not a fake home.
    names = ('PATH', 'HOME', 'USER', 'LANG', 'TERM', 'XDG_RUNTIME_DIR',
             'SSL_CERT_FILE', 'NIX_SSL_CERT_FILE', 'LLAMA_SWAP_LANE_LOCK')
    source = os.environ if env is None else env
    return {key: source[key] for key in names if source.get(key)}


def launch_command(*, profile, origin, worktree, config_dir, runtime_dir, sandbox,
                   opencode, lane_helper, prompt, timeout_s, env=None):
    """Place isolation variables inside the original attempt's named sandbox."""
    clean = _clean_env(env)
    # A parent runner's PATH contains sandbox shims. The explicit executable
    # below is resolved from the coordinator's PATH, not that injected PATH.
    assignments = dict(clean,
        OPENCODE_CONFIG_DIR=str(config_dir),
        OPENCODE_DISABLE_PROJECT_CONFIG='1', OPENCODE_CONFIG_PROJECT_DISABLE='1',
        OPENCODE_DISABLE_CLAUDE_CODE='1', OPENCODE_DISABLE_MODELS_FETCH='1',
        OPENCODE_DISABLE_AUTOUPDATE='1', OPENCODE_DISABLE_FREE_MODELS='1',
        XDG_CONFIG_HOME=str(runtime_dir / 'xdg-config'),
        XDG_DATA_HOME=str(runtime_dir / 'data'), XDG_CACHE_HOME=str(runtime_dir / 'cache'),
        XDG_STATE_HOME=str(runtime_dir / 'state'))
    prefix = sandbox.prefix(worktree)
    if sandbox.mode != 'none':
        prefix.append(f'-pReadOnlyPaths={config_dir}')
    native = [opencode, 'run', '--standalone', '--format', 'json', '--auto',
              '--model', f'{PROVIDER}/{profile}', '--', prompt]
    inside = [shutil.which('env') or '/usr/bin/env', '-i',
              *(f'{key}={value}' for key, value in assignments.items()), *native]
    return [sys.executable, str(lane_helper), 'run', '--model', profile, '--wait', '0',
            '--purpose', 'lanectl-local-attempt', '--', *prefix, *inside], clean


def run_local(*, model, worktree, prompt, status_file, timeout_s, external,
              env=None, sandbox=None, cancel_event=None, stop_callback=None):
    """Drive the native harness; no generated shell/tool loop lives in lanectl."""
    from .adapters import AdapterResult
    from .adapters_opencode import parse_stream, _write_status
    usage = None
    outcome, code, tail = 'failed', 1, ''
    try:
        if external:
            raise ValueError('local provider refuses external-provider attestation')
        if sandbox is None or sandbox.mode != 'systemd-run':
            raise ValueError('local provider requires the existing attempt sandbox')
        profile = profile_for(model)
        origin = (os.environ if env is None else env).get('LANECTL_LOCAL_BASE_URL')
        if not origin:
            raise ValueError('LANECTL_LOCAL_BASE_URL must explicitly select the local pool')
        origin = validate_origin(origin)
        # Managed system plugins/providers are above user config precedence.
        # Refuse this unsupported composition instead of pretending it is isolated.
        system = Path('/etc/opencode')
        if system.is_dir() and any(system.iterdir()):
            raise ValueError('local provider cannot isolate inherited system OpenCode configuration')
        helper = Path(os.environ.get('LANECTL_LOCAL_LANE_HELPER', DEFAULT_LANE_HELPER))
        if not helper.is_absolute() or not helper.is_file():
            raise ValueError('local inference lane helper is unavailable')
        opencode = shutil.which('opencode')
        if not opencode:
            raise ValueError('native OpenCode is unavailable')
        with local_relay(origin, timeout_s) as relay, tempfile.TemporaryDirectory(prefix='.lanectl-local-', dir=worktree) as temp:
            runtime = Path(temp)
            config = runtime / 'config'
            config.mkdir()
            config_file = config / 'opencode.json'
            config_file.write_text(json.dumps(provider_config(profile, relay)))
            config_file.chmod(0o400)
            clean = _clean_env(env)
            version_env = dict(clean, OPENCODE_CONFIG_DIR=str(config),
                XDG_DATA_HOME=str(runtime/'data'), XDG_CACHE_HOME=str(runtime/'cache'),
                XDG_STATE_HOME=str(runtime/'state'))
            version = subprocess.run([opencode, '--version'], capture_output=True, text=True,
                                     env=version_env, timeout=min(timeout_s, 10))
            validate_version(version.stdout)
            cmd, clean = launch_command(profile=profile, origin=origin, worktree=Path(worktree),
                config_dir=config, runtime_dir=runtime, sandbox=sandbox, opencode=opencode,
                lane_helper=helper, prompt=prompt, timeout_s=timeout_s, env=env)
            proc = subprocess.Popen(cmd, cwd=worktree, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                start_new_session=True, env=clean)
            try:
                output, _, stopped = communicate(proc, timeout_s, cancel_event,
                    on_stop=stop_callback or sandbox.cancel)
            finally:
                if cancel_event is not None and cancel_event.is_set():
                    sandbox.cancel()
            text, usage = parse_stream(output or '')
            if stopped:
                sandbox.cancel()
                code, tail = 124, f'local attempt {stopped}'
            else:
                code = proc.returncode
                outcome = 'done' if code == 0 else 'failed'
                tail = (text or output or '')[-2000:]
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        if sandbox is not None and hasattr(sandbox, 'cancel'):
            sandbox.cancel()
        tail = f'local provider: {exc}'
    _write_status(Path(status_file), dict(model=model, provider='local', outcome=outcome,
        exit_code=code, final_message_tail=tail, usage=usage))
    return AdapterResult(outcome, code, tail, None, usage)
