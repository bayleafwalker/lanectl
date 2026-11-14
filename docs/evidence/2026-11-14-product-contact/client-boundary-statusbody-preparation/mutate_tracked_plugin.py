from pathlib import Path

def pytest_collection_modifyitems(items):
    path=Path.cwd()/'README.md'
    assert path.is_file() and not path.is_symlink()
    with path.open('a') as file:
        file.write('\nqualification-only tracked mutation\n')
