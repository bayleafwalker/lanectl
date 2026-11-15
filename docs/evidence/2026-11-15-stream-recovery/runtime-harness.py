import hashlib,json,os,shutil,sqlite3,subprocess,sys,tempfile
from pathlib import Path
from lanectl import stream_recovery as recovery
from lanectl.contracts import make_event
from lanectl.stream_store import initialize
output=Path(sys.argv[1])
root=Path(tempfile.mkdtemp(prefix="lanectl-2910-runtime-reviewed-"))
source=root/"source.sqlite";initialize(source);source.chmod(0o600)
env={**os.environ,"PYTHONPATH":str(Path.cwd()/"src"),"LANECTL_STATE":str(root/"authority-must-remain-absent")}
def process(code,*args,data=None):
    result=subprocess.run([sys.executable,"-c",code,*map(str,args)],input=json.dumps(data) if data is not None else None,capture_output=True,text=True,env=env,check=False)
    assert result.returncode==0,(result.stdout,result.stderr)
    return json.loads(result.stdout)
def cli(*args):
    return process("from lanectl.cli import main; import sys; raise SystemExit(main(sys.argv[1:]))","stream",*args)
def logical(path):
    with sqlite3.connect(path) as db:
        body={t:db.execute("SELECT * FROM "+t+" ORDER BY 1,2,3,4,5").fetchall() for t in ("lane_events","lane_batches")}
    return hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":")).encode()).hexdigest()
events=[make_event("release.published",{"release_id":label,"revision":1},item_id=label) for label in ("proof-a","proof-b","proof-c")]
reader=sqlite3.connect(source);reader.execute("BEGIN");reader.execute("SELECT count(*) FROM lane_events").fetchone()
writer="""
import json,sys
from lanectl.stream_store import StreamStore
owner=StreamStore(sys.argv[1]);events=json.load(sys.stdin)
scopes=[('ws-a','repo-a','control'),('ws-b','repo-a','control'),('ws-a','repo-b','other')]
print(json.dumps([owner.append(*scope,'proof:runner:1','proof-batch-0001',0,[event]) for scope,event in zip(scopes,events)]))
"""
ack=process(writer,source,data=events)
assert Path(str(source)+"-wal").stat().st_size>0
naive=root/"naive.sqlite";shutil.copyfile(source,naive)
with sqlite3.connect(naive) as db: assert db.execute("SELECT count(*) FROM lane_events").fetchone()==(0,)
artifact=root/"snapshot.lane";restored=root/"restored.sqlite"
backup=cli("backup",source,artifact);restore=cli("restore",artifact,restored)
assert backup["counts"]==restore["counts"]=={"lane_events":3,"lane_batches":3}
assert restore["journal_mode"] == "wal"
assert restore["restored_database_sha256"] == hashlib.sha256(restored.read_bytes()).hexdigest()
assert restore["restored_database_sha256"] != restore["payload_sha256"]
assert restore["payload_sha256"] == backup["payload_sha256"]
assert logical(source)==logical(restored)
reopen="""
import hashlib,json,sqlite3,sys
from lanectl.stream_store import StreamStore,StreamError
owner=StreamStore(sys.argv[1]);event=json.load(sys.stdin)
with sqlite3.connect(sys.argv[1]) as db:
    body={t:db.execute('SELECT * FROM '+t+' ORDER BY 1,2,3,4,5').fetchall() for t in ('lane_events','lane_batches')}
proof={'all_rows_sha256':hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest(), 'journal_mode_before':db.execute('PRAGMA journal_mode').fetchone()[0]}
proof['replay']=owner.append('ws-a','repo-a','control','proof:runner:1','proof-batch-0001',0,[event])
changed={**event,'data':{**event['data'],'revision':2}}
try: owner.append('ws-a','repo-a','control','proof:runner:1','proof-batch-0001',0,[changed])
except StreamError as error: proof['changed_content_refusal']=error.code
else: raise AssertionError('changed replay accepted')
proof['next_batch']=owner.append('ws-a','repo-a','control','proof:runner:1','proof-batch-0002',1,[event])
proof['scoped_heads']=[owner.read(*scope)['revision'] for scope in [('ws-a','repo-a','control'),('ws-b','repo-a','control'),('ws-a','repo-b','other'),('foreign','repo-a','control')]]
with sqlite3.connect(sys.argv[1]) as mode_db: proof['journal_mode_after']=mode_db.execute('PRAGMA journal_mode').fetchone()[0]
print(json.dumps(proof))
"""
reopened=process(reopen,restored,data=events[0])
assert reopened["all_rows_sha256"]==logical(source)
assert reopened["replay"]=={**ack[0],"replayed":True}
assert reopened["changed_content_refusal"]=="idempotency-conflict"
assert reopened["journal_mode_before"] == reopened["journal_mode_after"] == "wal"
assert reopened["next_batch"]["revision"]==2 and reopened["scoped_heads"]==[2,1,1,0]
fault_artifact=root/"parent-sync-failed.lane";original_sync=recovery._sync_parent
fault={}
def kernel_failure(parent_fd):
    fd=os.open("/dev/null",os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)
recovery._sync_parent=kernel_failure
try:
    try: recovery.backup(source,fault_artifact)
    except recovery.RecoveryError as error:
        assert error.published==str(fault_artifact) and isinstance(error.__cause__,OSError)
        fault={"phase":"parent-fsync","injection":"real kernel fsync(/dev/null) error","errno":error.__cause__.errno,"published":error.published,"success_receipt":False}
    else: raise AssertionError("fault produced success")
finally: recovery._sync_parent=original_sync
recovery.restore(fault_artifact,root/"fault-restored.sqlite")
try: recovery.backup(source,fault_artifact)
except recovery.RecoveryError as error: assert "existing-destination" in str(error)
else: raise AssertionError("existing output replaced")
reader.close()
assert not (root/"authority-must-remain-absent").exists() and not list(root.glob(".lanectl-recovery-*"))
proof={"source_sha256":hashlib.sha256(Path(recovery.__file__).read_bytes()).hexdigest(),"fixture":str(root),"fixture_durability":"session-local","committed_uncheckpointed_wal":True,"main-file-only-copy_falsified":True,"writer_process":True,"cli_backup_process":backup,"cli_restore_process":restore,"reopen_process":reopened,"source_logical_sha256":logical(source),"kernel_fault":fault,"original_artifact_usable_after_fault":True,"authority_state_absent":True,"owned_candidates_remaining":[]}
fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,"w") as stream: json.dump(proof,stream,indent=2,sort_keys=True)
print(json.dumps({"proof":str(output),"sha256":hashlib.sha256(output.read_bytes()).hexdigest(),"source_sha256":proof["source_sha256"],"counts":backup["counts"]}))
