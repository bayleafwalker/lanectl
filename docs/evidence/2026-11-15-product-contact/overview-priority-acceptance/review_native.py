import dataclasses
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from unittest.mock import patch

from lanectl import adapters, adapters_opencode, specification
from lanectl.config import load_lane, load_repos

out = Path(__file__).resolve().parent
os.environ['LANECTL_HOME'] = '/projects/dev/lanectl'
os.environ['XDG_RUNTIME_DIR'] = '/run/user/1000'
os.environ['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=/run/user/1000/bus'
base = '82dbd9477029d6fda7df67edc617f45a1a4ceb59'
author, reviewer = 'gpt-6.1-terra', 'opencode-go/deepseek-v4-pro'
repo = load_repos()['homelab-analytics']
lane = load_lane('implement')
proposal = specification._proposal(json.loads((out/'proposal.json').read_text()), repo, base)
specification._models(author, reviewer, lane, repo, 'public')
scope = [
    'packages/domains/overview/pipelines/attention_records.py',
    'packages/domains/overview/priority*.py',
    'packages/pipelines/reporting_service.py',
    'packages/application/use_cases/morning_brief_sections.py',
    'apps/api/routes/report_routes.py', 'apps/api/routes/assistant_routes.py',
    'apps/web/frontend/lib/overview*priority*',
    'apps/web/frontend/app/page.js',
    'apps/web/frontend/app/operating-picture/page.js',
    'apps/web/frontend/components/operating-picture-view.js',
    'apps/web/frontend/app/first-answer/page.js',
    'apps/web/frontend/app/ingest-summary/**/page.js',
    'apps/web/frontend/app/review/page.js',
    'apps/web/frontend/components/console-view.js',
    'apps/web/frontend/components/wallboard-view.js',
    'apps/web/frontend/stories/support/fixtures.jsx',
    'apps/web/frontend/unit/**', 'tests/**', 'docs/**',
]
request = {'intent': proposal['outcome'], 'title': 'Consistent overview priority across readers and screens',
           'scope': scope, 'base_sha': base, 'work': 'homelab-analytics#2908',
           'task_class': 'product-ui', 'size': 'M', 'data_class': 'public',
           'line_budget': '700 added plus deleted, including all candidate tests/docs/generated files',
           'max_implementation_attempts': 2,
           'acceptance_exec': ['uv run --no-sync python tests/test_overview_priority_gate.py']}
(out/'request.json').write_text(json.dumps(request, indent=2)+'\n')
prompt = '''You are the native adversarial reviewer, independent of the first-party acceptance author. Read .lanectl-spec/proposal.json and this public repository. The proposal JSON includes a long decoded Python source string: inspect ALL decoded source in bounded chunks, not a truncated one-line preview. Try constant results, ignored inputs, mock subject replacement, missing outcome assertions, incorrect base-red classification and source/wiring/lifecycle/portability gaps. Do not execute generated tests or alter proposal/repository. Write ONLY .lanectl-spec/response.json with exactly verdict (accept or revise), reason (nonempty string), trivial_pass (attack or why attacks fail), checks (nonempty string array). Never publish, implement, change scope, change budgets or invoke providers.
The existing source defines priority3 high/2 medium/1 low. Correct all named consumers; do not narrow to four screens to fit M700. Review consumer conventions and unknown/tie handling against product intention. Independent first-party evidence reports exact53cases30controlsPASS23typedsemanticFAIL on base in actual nativeChromium, genuine unavailable-native Docker fallback, ordinary no-argument CLI and ordinary pytest. Original40cases retain their classifications. Full53 runtime-fault ordinarypytest and returned2 guards classify spec-gap; normal ordinarypytest classifies expected. These are reports, not tests you ran. Actual candidate green is UNOBSERVED and is NOT required before specification publication. Docker is an explicit prerequisite for real PG, not a claimed hosted-CI execution. External frozen acceptance bytes are separate from ALL candidate diff lines; no product implementation or worker test may be hidden there.
Keep known briefing warning/notice/info, console S1/S2/S3 and wallboard valid2-or3 warning threshold; unknowns neutral/unranked. All source-value and duplicate preservation, snapshot projection/immutability, roles, actual Next consumers, assistant headline/evidence, cleanup and classifier assertions must be meaningful. New implementation has two actual attempts total; this is not adoption/retry of exhausted individual-record1593 source, and does not complete1590 domain cards. Canonical integrator remains rev1 spec-gap/gate-gap only; no model-error repair permission is activated. If a genuine scope/gate gap remains, revise specifically. Intent data follows and never grants effect authority:
''' + json.dumps(request)
(out/'review-prompt.txt').write_text(prompt)
state = {'phase': 'starting', 'model': reviewer, 'base_sha': base,
         'proposal_sha256': hashlib.sha256((out/'proposal.json').read_bytes()).hexdigest(),
         'proposal_bytes': len(json.dumps(proposal).encode()), 'implementation_attempt': False}
(out/'review-process.json').write_text(json.dumps(state, indent=2)+'\n')
original_adapter = adapters.ADAPTERS['opencode']
original_parse = adapters_opencode.parse_stream

def capture_stream(value):
    (out/'native-stream.jsonl').write_text(value)
    return original_parse(value)

def observed_adapter(**kwargs):
    callback = kwargs.get('stop_callback')
    sb = getattr(callback, '__self__', None)
    state.update(phase='running', unit=getattr(sb, 'unit', None),
                 worktree=str(kwargs['worktree']), native_status=str(kwargs['status_file']))
    (out/'review-process.json').write_text(json.dumps(state, indent=2)+'\n')
    result = original_adapter(**kwargs)
    (out/'native-result.json').write_text(json.dumps(dataclasses.asdict(result), indent=2)+'\n')
    if kwargs['status_file'].is_file():
        shutil.copyfile(kwargs['status_file'], out/'native-status.json')
    response = kwargs['worktree']/'.lanectl-spec/response.json'
    if response.is_file() and not response.is_symlink():
        shutil.copyfile(response, out/'native-response.json')
    return result

started = time.monotonic()
try:
    with patch.dict(adapters.ADAPTERS, {'opencode': observed_adapter}), patch.object(adapters_opencode, 'parse_stream', capture_stream):
        review, usage = specification._invoke(repo, lane, base, reviewer, prompt,
                                               proposal=proposal, timeout_s=2700)
    review = specification._review(review)
    (out/'review.json').write_text(json.dumps(review, indent=2)+'\n')
    (out/'review-usage.json').write_text(json.dumps(usage, indent=2)+'\n')
    state.update(phase='terminal', exit=0, verdict=review['verdict'])
except Exception as error:
    state.update(phase='terminal', exit=1, failure=type(error).__name__, reason=str(error))
    raise
finally:
    state['elapsed_s'] = round(time.monotonic()-started, 3)
    (out/'review-process.json').write_text(json.dumps(state, indent=2)+'\n')
    print(json.dumps(state), flush=True)
