"""Live proof that stopping the fixed service kills a setsid descendant."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import shlex
import signal
import threading
import time
from unittest.mock import patch

from lanectl.config import load_repos
from lanectl import fenced_train as fence


def process(pid):
    try:
        fields=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
        return {'state':fields[0],'start_ticks':fields[19]}
    except FileNotFoundError:
        return None


def same_live(pid,birth):
    current=process(pid)
    return current is not None and current['start_ticks']==birth and current['state'] not in ('Z','X')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',default='sovite')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    repo=replace(load_repos()[args.repo],setup_cmd='')
    child="import os,time; os.setsid(); print('LANECTL_SETSID_PID='+str(os.getpid()),flush=True); time.sleep(3600)"
    parent='import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",'+repr(child)+']); time.sleep(3600)'
    command=shlex.join(['/run/current-system/sw/bin/python3','-c',parent])
    observed={}
    threads=[]
    witnessed_live=[]
    original_start,original_stop=fence._start,fence._stop_terminal
    def start(tool,unit):
        original_start(tool,unit)
        observed['unit']=unit
        def wait_child():
            try:
                deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    text=fence._journal('journalctl',unit)
                    match=re.search(r'LANECTL_SETSID_PID=([0-9]+)',text)
                    if match:
                        pid=int(match[1])
                        before=process(pid)
                        if before is None:
                            raise RuntimeError('setsid child exited before positive control')
                        observed.update(pid=pid,birth=before['start_ticks'],before=before)
                        observed['positive_live_control']=same_live(pid,before['start_ticks'])
                        witnessed_live.append(time.monotonic())
                        break
                    time.sleep(0.1)
                else:
                    observed['error']='child readiness marker not observed'
            except Exception as error:
                observed['error']=type(error).__name__
            finally:
                os.kill(os.getpid(),signal.SIGINT)
        thread=threading.Thread(target=wait_child)
        threads.append(thread)
        thread.start()
    def stop(tool,unit):
        result=original_stop(tool,unit)
        observed['stop_acknowledged']=result
        return result
    try:
        with patch.object(fence,'_start',side_effect=start),patch.object(fence,'_stop_terminal',side_effect=stop):
            try:
                fence.run_command(repo,repo.path,command,timeout_s=180)
            except KeyboardInterrupt:
                observed['interrupted']=True
            else:
                raise RuntimeError('expected live cancellation did not occur')
    finally:
        for thread in threads:
            thread.join()
    assert not observed.get('error'),observed
    assert observed.get('positive_live_control') and observed.get('stop_acknowledged'),observed
    deadline=time.monotonic()+5
    while time.monotonic()<deadline and same_live(observed['pid'],observed['birth']):
        time.sleep(0.1)
    observed['child_gone']=not same_live(observed['pid'],observed['birth'])
    observed['terminal']=fence._active('systemctl',observed['unit']) in fence.TERMINAL
    tid=observed['unit'].split('@',1)[1].removesuffix('.service')
    observed['checkout_removed']=not (fence.TRAIN_ROOT/tid).exists()
    observed['cancellation_elapsed_s']=round(time.monotonic()-witnessed_live[0],3)
    observed['child_natural_lifetime_s']=3600
    observed['command_timeout_s']=180
    args.output.write_text(json.dumps(observed,indent=2)+'\n')
    print(json.dumps(observed),flush=True)
    assert observed['child_gone'] and observed['terminal'] and observed['checkout_removed'],observed
    # Finish well before either natural expiry or the independent command timeout.
    assert observed['cancellation_elapsed_s'] < 60,observed


if __name__=='__main__':
    main()
