"""Age is not authority to steal work from a live or unknown runner."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys

from lanectl import reap, runner, tick
from lanectl.events import EventLog, project_items
from lanectl.doctor import Finding, OK

TEST='from calc import sub\n\ndef test_sub():\n    assert sub(5,3)==2\n'


def claim(estate, identity):
    _,release,original=estate
    release('crash-proof',TEST)
    admitted=runner.admit('implement',original)
    log=EventLog(original.path.with_name('recovery-proof.jsonl'))
    for ev in original.read():
        data=dict(ev['data'])
        if ev['type']=='item.claimed':
            data['runner_process']=identity
            data['worker_unit']='lanectl-attempt-proof.service'
        log.append(ev['type'],data,item_id=ev['item_id'])
    return admitted,log


def later(log):
    return datetime.now(timezone.utc)+timedelta(hours=4)


def dead_identity():
    process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
    try:
        identity=reap.process_identity(process.pid)
        assert identity is not None
        return identity
    finally:
        process.terminate();process.wait(timeout=5)


def test_dead_runner_reclaims_slot_and_is_not_reaped_twice(estate):
    admitted,log=claim(estate,dead_identity())
    assert reap.periodic(log,now=later(log),unit_inactive_fn=lambda unit:True)==[admitted.attempt_id]
    assert project_items(log.read())['crash-proof'].state=='requeued'
    assert reap.periodic(log,now=later(log),unit_inactive_fn=lambda unit:True)==[]
    next_claim=runner.admit('implement',log)
    assert not isinstance(next_claim,str)
    assert next_claim.attempt_id!=admitted.attempt_id


def test_active_local_runner_is_protected_past_timeout(estate):
    _,log=claim(estate,reap.process_identity())
    assert reap.periodic(log,now=later(log),unit_inactive_fn=lambda unit:True)==[]
    assert project_items(log.read())['crash-proof'].state=='claimed'


def test_orphaned_active_sandbox_prevents_recovery(estate):
    _,log=claim(estate,dead_identity())
    assert reap.periodic(log,now=later(log),unit_inactive_fn=lambda unit:False)==[]
    assert project_items(log.read())['crash-proof'].state=='claimed'


def test_foreign_host_is_unknown_not_dead(estate):
    identity=dict(reap.process_identity(),host='another-host')
    _,log=claim(estate,identity)
    assert reap.periodic(log,now=later(log),unit_inactive_fn=lambda unit:True)==[]


def test_legacy_without_birth_identity_is_not_stolen(estate):
    _,log=claim(estate,None)
    assert reap.periodic(log,now=later(log),unit_inactive_fn=lambda unit:True)==[]


def test_periodic_never_accepts_partial_gate_evidence(estate):
    admitted,log=claim(estate,dead_identity())
    log.append('attempt.finished',{'attempt_id':admitted.attempt_id,'outcome':'done','exit_code':0,'head_sha':'b'*40,'seed_sha':'a'*40,'elapsed_s':1,'escalation_reason':None},item_id='crash-proof')
    log.append('gate.result',{'attempt_id':admitted.attempt_id,'gate':'diff','passed':True,'violations':[]},item_id='crash-proof')
    assert reap.periodic(log,now=later(log),unit_inactive_fn=lambda unit:True)==[admitted.attempt_id]
    assert project_items(log.read())['crash-proof'].state=='requeued'
    assert not [e for e in log.read() if e['type']=='decision.recorded' and e['data']['decision']=='candidate']


def test_tick_recovers_before_admitting(estate,monkeypatch):
    calls=[]
    monkeypatch.setattr(reap,'periodic',lambda *a,**k:calls.append('attempt-recovery') or ['a1'])
    out=tick.tick(estate[2],doctor_fn=lambda log:[Finding(OK,'home','ok')],reap_fn=lambda log:[],run_fn=lambda *a:calls.append('admit') or [])
    assert calls==['attempt-recovery','admit']
    assert out['reaped']==['attempt a1: abandoned runner recovered']


def test_pid_reuse_is_distinguished_from_a_live_owner():
    live=reap.process_identity()
    assert live is not None
    assert reap.runner_dead(live) is False
    old=dict(live,start_ticks=str(int(live['start_ticks'])-1))
    assert reap.runner_dead(old) is True
    assert reap.runner_dead(dict(live,start_ticks='unreadable')) is False
