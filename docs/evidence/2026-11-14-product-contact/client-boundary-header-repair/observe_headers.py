def pytest_collection_modifyitems(items):
    module = items[0].module
    original = module.http
    def observed(*args, **kwargs):
        code, headers, body = original(*args, **kwargs)
        if code in (303, 307, 308):
            print('redirect status', code, 'header names', sorted(headers), 'location', headers.get('location'))
        return code, headers, body
    module.http = observed
