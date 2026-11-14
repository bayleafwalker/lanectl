import importlib.util
from pathlib import Path

p = Path('/tmp/hla-ui-acceptance-observer-repair/files/tests/test_attention_current_ui_acceptance.py')
spec = importlib.util.spec_from_file_location('repaired_acceptance', p)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
prior = 'StaleGuard-abcdef'
cases = {
    'existing_boundary': (200, "This page couldn’t load. Something went wrong while building this page.", True),
    'server_error': (500, 'Unexpected server fault', True),
    'mapped_404': (404, 'Not found in the current report', False),
    'masked_404': (200, "This page couldn't load: not found", False),
    'mapped_503': (200, 'Temporarily unavailable', False),
    'reference_503': (200, "This page couldn't load. Something went wrong. Reference: 503", True),
    'status_503': (503, "This page couldn't load", False),
    'reference_404': (200, "This page couldn't load. Something went wrong. Reference: 404", True),
    'masked_503': (200, "This page couldn't load: unavailable", False),
    'empty_success': (200, 'No attention items. All clear.', False),
    'plain_success': (200, 'Record loaded', False),
    'body_leak': (200, "This page couldn't load " + prior, False),
    'raw_body_leak': (500, 'synthetic_secret', False),
}
for name, (status, body, expected) in cases.items():
    try:
        module.assert_unexpected_error({'status': status, 'body': body}, prior)
        accepted = True
    except AssertionError:
        accepted = False
    assert accepted == expected, name
    print(name, 'accepted' if accepted else 'rejected')
