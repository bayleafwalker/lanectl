from lanectl.ready import _first_party


def test_restricted_local_route_requires_explicit_loopback_configuration(monkeypatch):
    monkeypatch.delenv('LANECTL_LOCAL_BASE_URL', raising=False)
    assert not _first_party('local/worker-fast')
    monkeypatch.setenv('LANECTL_LOCAL_BASE_URL', 'https://provider.invalid/v1')
    assert not _first_party('local/worker-fast')
    monkeypatch.setenv('LANECTL_LOCAL_BASE_URL', 'http://127.0.0.1:8020/v1')
    assert _first_party('local/worker-fast')
    assert not _first_party('local/../private')
    assert not _first_party('unknown/model')
