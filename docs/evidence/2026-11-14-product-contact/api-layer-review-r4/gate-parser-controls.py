import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
p=Path('/projects/dev/lanectl/backlog/hla-attention-records-r5/files/tests/attention_record_pg_gate.py')
s=importlib.util.spec_from_file_location('gate',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
def xml(cases, tests='3', skipped='0', failures='0', errors='0'):
    return f'<testsuites><testsuite tests="{tests}" skipped="{skipped}" failures="{failures}" errors="{errors}">{cases}</testsuite></testsuites>'
def case(name, content=''):
    return f'<testcase classname="tests.test_attention_record_api" name="{name}">{content}</testcase>'
valid=''.join(case(n) for n in m.CASES)
tests={'valid':xml(valid),'zero':xml('',tests='0'),'skipped':xml(case(m.CASES[0],'<skipped/>')+''.join(case(n) for n in m.CASES[1:]),skipped='1'),'incomplete':xml(''.join(case(n) for n in m.CASES[:2]),tests='2'),'duplicate':xml(case(m.CASES[0])*2+case(m.CASES[1])),'wrong-name':xml(case('other')+''.join(case(n) for n in m.CASES[1:])), 'failure':xml(case(m.CASES[0],'<failure/>')+''.join(case(n) for n in m.CASES[1:]),failures='1'), 'error':xml(case(m.CASES[0],'<error/>')+''.join(case(n) for n in m.CASES[1:]),errors='1'), 'mismatch-summary':xml(valid,tests='2'), 'malformed':'<testsuites>', 'missing-field':xml(valid).replace(' errors="0"','')}
with TemporaryDirectory() as td:
    path=Path(td)/'report.xml'
    for label,data in tests.items():
        path.write_text(data)
        try: m.validate_report(path); passed=True
        except Exception: passed=False
        assert passed == (label=='valid'), label
        print(label, 'accepted' if passed else 'rejected')
    path.unlink()
    try: m.validate_report(path)
    except FileNotFoundError: print('missing rejected')
    else: raise AssertionError('missing accepted')
