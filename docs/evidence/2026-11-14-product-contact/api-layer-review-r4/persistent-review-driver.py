"""Retain diagnostics while using official _invoke and native adapter unchanged."""
from contextlib import contextmanager
import json
import shutil
from pathlib import Path

from lanectl import specification as spec


def record(root, name, value):
    # Diagnostic I/O must not replace an invocation result or exception.
    try:
        (root / name).write_text(json.dumps(value, indent=2) + '\n')
    except Exception:
        pass


@contextmanager
def retain_spec_directories(root):
    original = spec.tempfile.TemporaryDirectory

    class RetainingDirectory(original):
        def __init__(self, *args, **kwargs):
            self._keep_spec = kwargs.get('prefix') == 'lanectl-spec-'
            self._copy_attempted = False
            self._copied = False
            super().__init__(*args, **kwargs)
            if self._keep_spec:
                record(root, 'active-runtime.json', {
                    'temporary_root': self.name, 'saved_root': str(root / 'invocation')})

        def cleanup(self):
            try:
                if self._keep_spec and not self._copy_attempted:
                    self._copy_attempted = True
                    try:
                        # Preserve links as links; never follow a model-created link.
                        shutil.copytree(self.name, root / 'invocation', symlinks=True)
                        self._copied = True
                        record(root, 'retention.json', {'complete': True})
                    except Exception as exc:
                        record(root, 'retention.json', {
                            'complete': False, 'type': type(exc).__name__, 'message': str(exc)})
            finally:
                super().cleanup()

    # Dedicated process only: this changes directory lifecycle globally until
    # restored. No adapter/model/response/security check is replaced.
    spec.tempfile.TemporaryDirectory = RetainingDirectory
    try:
        yield
    finally:
        spec.tempfile.TemporaryDirectory = original


def invoke(repo, lane, base_sha, model, prompt, *, proposal, timeout_s, run_root):
    assert 1 <= timeout_s <= lane.timeout_s
    root = Path(run_root)
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    # Refuse startup if initial diagnostics cannot be written.
    (root / 'request.json').write_text(json.dumps({
        'model': model, 'base_sha': base_sha, 'timeout_s': timeout_s,
        'prompt': prompt, 'invocation': 'official specification._invoke unchanged',
        'retention': 'best-effort copy during normal temporary-directory cleanup'}, indent=2) + '\n')
    print(json.dumps({'persistent_review_root': str(root), 'timeout_s': timeout_s}), flush=True)
    try:
        with retain_spec_directories(root):
            response, usage = spec._invoke(repo, lane, base_sha, model, prompt,
                                          proposal=proposal, timeout_s=timeout_s)
    except BaseException as exc:
        record(root, 'invocation-error.json', {'type': type(exc).__name__, 'message': str(exc)})
        raise
    record(root, 'actual-return.json', {'response': response, 'usage': usage})
    return response, usage
