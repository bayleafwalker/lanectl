"""Recurring owner flags produce deduplicated, unpublished maintenance drafts."""
import json
from pathlib import Path

import pytest

from lanectl import closure
from lanectl.contracts import make_event
from lanectl.events import EventLog


def ruled(aid, fix_class='spec-gap', commit=None, task_class='glue'):
    return [make_event('experiment.recorded',{'attempt_id':aid,'model':'scripted/model',
       'worker':'scripted','task_class':task_class,'decision':'candidate','elapsed_s':1}),
       make_event('decision.recorded',{'attempt_id':aid,'decision':'candidate','reasons':[],
          'rules_revision':'test','by':'gates'}),
       make_event('integrator.fix',{'attempt_id':aid,'commit':commit or aid,'fix_class':fix_class}),
       make_event('item.landed',{'attempt_id':aid,'train_id':'train','fix_commits':[commit or aid]})]


def log_at(tmp_path,events):
    log=EventLog(tmp_path/'events.jsonl')
    for e in events:log.append(e['type'],e['data'],item_id=e['item_id'])
    return log


def test_requires_recurring_ruled_gaps_not_model_errors():
    assert closure.from_flags(ruled('a1'))==[]
    assert closure.from_flags(ruled('a1')+ruled('a2','model-error'))==[]
    assert closure.from_flags(ruled('a1')+ruled('a1'))==[]
    rows=closure.from_flags(ruled('a1')+ruled('a2'))
    assert len(rows)==1 and rows[0]['kind']=='planner'
    assert rows[0]['recurrence']==2 and rows[0]['data_class']=='restricted'
    assert len(rows[0]['evidence_refs'])==2


def test_gate_and_planner_flags_are_separate():
    rows=closure.from_flags(ruled('a1')+ruled('a2')+ruled('a3','gate-gap')+ruled('a4','gate-gap'))
    assert {r['kind'] for r in rows}=={'planner','gate'}


def test_unrelated_events_do_not_change_source_revision():
    events=ruled('a1')+ruled('a2')
    row=closure.from_flags(events)[0]
    extra=make_event('usage.recorded',{'provider':'test','source':'test','units':{'output_tokens':1}})
    assert closure.from_flags(events+[extra])[0]==row
    assert closure.from_flags(events+ruled('a3'))[0]['source_revision']!=row['source_revision']


def test_record_is_idempotent_and_keeps_original_evidence(tmp_path):
    log=log_at(tmp_path,ruled('a1')+ruled('a2'))
    before=log.path.read_bytes()
    rows=closure.scan(log,record=False)
    assert rows and log.path.read_bytes()==before
    assert closure.scan(log,record=True)==rows
    assert closure.scan(log,record=True)==[]
    recorded=closure.proposals(log.read())
    assert recorded[0]['fingerprint']==rows[0]['fingerprint']


def test_draft_never_publishes_and_forces_restricted_data(tmp_path):
    log=log_at(tmp_path,ruled('a1')+ruled('a2'))
    row=closure.scan(log,record=True)[0]
    calls=[]
    def create(release_id,**kw):
        calls.append((release_id,kw));d=tmp_path/release_id;d.mkdir();return d
    result=closure.draft(log,row['fingerprint'],author_model='claude-opus-5-5',
          reviewer_model='claude-fable-5-2',scope=['src/**'],draft_fn=create)
    assert len(calls)==1
    assert calls[0][1]['data_class']=='restricted'
    assert calls[0][1]['lane_name']=='restricted'
    assert 'evidence' in calls[0][1]['intent']
    assert result['action']=='drafted'
    assert closure.draft(log,row['fingerprint'],author_model='claude-opus-5-5',
          reviewer_model='claude-fable-5-2',scope=['src/**'],draft_fn=create)==result
    assert len(calls)==1


def test_draft_refuses_unknown_proposal_and_external_route(tmp_path):
    log=log_at(tmp_path,ruled('a1')+ruled('a2'))
    row=closure.scan(log,record=True)[0]
    with pytest.raises(ValueError,match='unknown'):
        closure.draft(log,'missing',author_model='claude-opus-5-5',reviewer_model='claude-fable-5-2',scope=['src/**'])
    with pytest.raises(ValueError,match='restricted'):
        closure.draft(log,row['fingerprint'],author_model='opencode-go/deepseek-v4-pro',
            reviewer_model='claude-fable-5-2',scope=['src/**'])


def test_active_draft_suppresses_duplicate_work_for_same_class(tmp_path):
    log=log_at(tmp_path,ruled('a1')+ruled('a2'))
    row=closure.scan(log,record=True)[0]
    log.append('triage.proposed',dict(row,action='drafted',release_id='closure-first'))
    for e in ruled('a3'):log.append(e['type'],e['data'])
    assert closure.scan(log,record=True)==[]


def test_completed_maintenance_consumes_old_evidence(tmp_path):
    log=log_at(tmp_path,ruled('a1')+ruled('a2'))
    row=closure.scan(log,record=True)[0]
    log.append('triage.proposed',dict(row,action='drafted',release_id='closure-first'))
    log.append('item.landed',{'attempt_id':'closure-first-a1','train_id':'t','fix_commits':[]},item_id='closure-first')
    assert closure.from_flags(log.read())==[]
    for e in ruled('a3')+ruled('a4'):log.append(e['type'],e['data'])
    new=closure.scan(log,record=True)
    assert len(new)==1 and new[0]['recurrence']==2


def test_concurrent_draft_refuses_second_writer(tmp_path):
    import fcntl
    log=log_at(tmp_path,ruled('a1')+ruled('a2'))
    row=closure.scan(log,record=True)[0]
    with (log.path.parent/f'closure-{row["fingerprint"]}.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(ValueError,match='already being drafted'):
            closure.draft(log,row['fingerprint'],author_model='claude-opus-5-5',
                reviewer_model='claude-fable-5-2',scope=['src/**'])


def test_failed_generation_can_retry_without_losing_intake(tmp_path):
    log=log_at(tmp_path,ruled('a1')+ruled('a2'))
    row=closure.scan(log,record=True)[0]
    def fail(*args,**kwargs):raise ValueError('model unavailable')
    with pytest.raises(ValueError,match='unavailable'):
        closure.draft(log,row['fingerprint'],author_model='claude-opus-5-5',
            reviewer_model='claude-fable-5-2',scope=['src/**'],draft_fn=fail)
    assert closure.proposals(log.read())[0]['action']=='proposed'


def test_crash_after_draft_creation_recovers_without_another_model_call(tmp_path,monkeypatch):
    log=log_at(tmp_path,ruled('a1')+ruled('a2'))
    row=closure.scan(log,record=True)[0]
    home=tmp_path/'home';monkeypatch.setenv('LANECTL_HOME',str(home))
    destination=home/'backlog'/f'closure-{row["fingerprint"][:20]}'
    destination.mkdir(parents=True)
    intent=closure._intent(row)
    import hashlib
    (destination/'specification.json').write_text(json.dumps({'intent_digest':hashlib.sha256(intent.encode()).hexdigest(),
        'release_digest':'digest'}))
    monkeypatch.setattr(closure.specification,'release_digest',lambda p:'digest')
    from types import SimpleNamespace
    monkeypatch.setattr(closure,'load_release',lambda p:SimpleNamespace(id=destination.name))
    def unexpected(*args,**kwargs):raise AssertionError('duplicate model call')
    result=closure.draft(log,row['fingerprint'],author_model='claude-opus-5-5',
        reviewer_model='claude-fable-5-2',scope=['src/**'],draft_fn=unexpected)
    assert result['action']=='drafted' and result['draft_path']==str(destination)
