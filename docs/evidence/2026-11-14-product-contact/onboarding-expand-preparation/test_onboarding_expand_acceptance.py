"""Independent real-Next onboarding acceptance. No candidate implementation is substituted."""
import json, os, shutil, signal, socket, subprocess, sys, tempfile, time, urllib.request, uuid, xml.etree.ElementTree as ET
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'apps/web/frontend'
OUT = Path(os.environ.get('HLA_ONBOARDING_EVIDENCE', tempfile.mkdtemp(prefix='hla-onboarding-evidence-'))).resolve()
def find_node():
    candidates=[os.environ.get('HLA_NODE'),shutil.which('node'),*[str(p) for p in sorted((ROOT / '.tooling').glob('node-v20*/bin/node'))],'/projects/dev/homelab-analytics/.tooling/node-v20.20.1-linux-x64/bin/node']
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            result=subprocess.run([candidate,'--version'],capture_output=True,text=True)
            if result.returncode==0 and result.stdout.startswith('v20.'): return candidate
    return ''
NODE = find_node()
BROWSER_TIMEOUT = 120
IMAGE = 'sha256:b0ab6f3cb99aa7803adbc14d9027ec1785fc6e433b97e134e0f8fe61683b6b53'
PAGE = '''"use client";
import {useState,useEffect} from "react";
import {OnboardingChecklist} from "@/components/onboarding-checklist";
export default function Probe(){const [fresh,setFresh]=useState([]);useEffect(()=>{setFresh(JSON.parse(sessionStorage.getItem("fixture_sources")||"[]"))},[]);const choose=(v)=>{sessionStorage.setItem("fixture_sources",JSON.stringify(v));setFresh(v)};return <main>
<button onClick={()=>choose([])}>Fixture none</button>
<button onClick={()=>choose(["account_transactions"])}>Fixture partial</button>
<button onClick={()=>choose(["contract_prices","budgets","loan_repayments"])}>Fixture optional</button>
<button onClick={()=>choose(["account_transactions","subscriptions"])}>Fixture core</button>
<button onClick={()=>choose(["account_transactions","subscriptions","contract_prices","budgets","loan_repayments"])}>Fixture all</button>
<OnboardingChecklist freshDatasets={fresh} nextSuggestion={null}/></main>}
'''
SCRIPT = r'''const {chromium}=require('playwright');
(async()=>{const mode=process.argv[3];const browser=mode.startsWith('ws:')?await chromium.connect(mode):await chromium.launch(mode==='bundled'?{headless:true}:{headless:true,executablePath:mode});const result={};
async function run(name,fn,storageThrows=false){const context=await browser.newContext();const p=await context.newPage();try{
 if(storageThrows) await p.addInitScript(()=>{for(const m of ['getItem','setItem','removeItem']) {const original=Storage.prototype[m];Object.defineProperty(Storage.prototype,m,{value(...args){if(this===localStorage)throw Error('synthetic storage unavailable');return original.apply(this,args)}})}});
 await p.goto(process.argv[2]);await p.getByRole('button',{name:'Fixture none'}).waitFor();await fn(p);result[name]={ok:true};
 }catch(e){result[name]={ok:false,error:String(e.message||e)}}finally{await context.close()}}
const panel=p=>p.locator('article');const heading=p=>panel(p).getByRole('heading',{name:'Get started — connect your data sources'});
const badge=p=>panel(p).getByRole('button',{name:'Expand'});const waitText=async(p,t)=>{await panel(p).getByText(t,{exact:false}).waitFor({timeout:3000})};
const click=async(p,name)=>p.getByRole('button',{name,exact:true}).click();
await run('initial',async p=>{await heading(p).waitFor();await waitText(p,'0 of 5 sources active');await waitText(p,'0/2 core sources ready')});
await run('partial',async p=>{await heading(p).waitFor();await click(p,'Fixture partial');await waitText(p,'1 of 5 sources active');await waitText(p,'1/2 core sources ready')});
await run('optional',async p=>{await heading(p).waitFor();await click(p,'Fixture optional');await waitText(p,'3 of 5 sources active');await waitText(p,'0/2 core sources ready')});
await run('auto_core',async p=>{await heading(p).waitFor();await click(p,'Fixture core');await badge(p).waitFor();await waitText(p,'2/5 sources active — core sources ready')});
await run('auto_all',async p=>{await heading(p).waitFor();await click(p,'Fixture all');await badge(p).waitFor();await waitText(p,'5/5 sources active — core sources ready')});
await run('manual_incomplete',async p=>{await heading(p).waitFor();await click(p,'Minimise');await badge(p).waitFor();if(await p.evaluate(()=>localStorage.getItem('onboarding_checklist_dismissed'))!=='compact')throw Error('compact not stored');await p.reload();await badge(p).waitFor();await click(p,'Expand');await heading(p).waitFor();if(await p.evaluate(()=>localStorage.getItem('onboarding_checklist_dismissed'))!==null)throw Error('compact not cleared')});
await run('dismiss',async p=>{await heading(p).waitFor();await click(p,'Dismiss onboarding checklist');await panel(p).waitFor({state:'detached'});if(await p.evaluate(()=>localStorage.getItem('onboarding_checklist_dismissed'))!=='dismissed')throw Error('dismiss not stored');await p.reload();await p.getByRole('button',{name:'Fixture core'}).waitFor();await click(p,'Fixture core');await panel(p).waitFor({state:'detached'});await p.evaluate(()=>localStorage.removeItem('onboarding_checklist_dismissed'));await p.reload();await badge(p).waitFor()});
await run('dismiss_compact',async p=>{await heading(p).waitFor();await click(p,'Fixture core');await badge(p).waitFor();await click(p,'Dismiss onboarding checklist');await panel(p).waitFor({state:'detached'});await p.reload();await p.getByRole('button',{name:'Fixture core'}).waitFor();await panel(p).waitFor({state:'detached'})});
await run('storage_failure_incomplete',async p=>{await heading(p).waitFor();await click(p,'Minimise');await badge(p).waitFor();await click(p,'Expand');await heading(p).waitFor()},true);
await run('expand_core',async p=>{await heading(p).waitFor();await click(p,'Fixture core');await badge(p).waitFor();await click(p,'Expand');await heading(p).waitFor({timeout:3000});await p.getByRole('button',{name:'Minimise'}).waitFor();if(await p.evaluate(()=>localStorage.getItem('onboarding_checklist_dismissed'))!==null)throw Error('Expand must clear storage');await p.reload();await badge(p).waitFor();});
await run('expand_then_minimise',async p=>{await heading(p).waitFor();await click(p,'Fixture core');await badge(p).waitFor();await click(p,'Expand');await heading(p).waitFor({timeout:3000});await click(p,'Minimise');await badge(p).waitFor();if(await p.evaluate(()=>localStorage.getItem('onboarding_checklist_dismissed'))!=='compact')throw Error('compact not stored');await p.reload();await badge(p).waitFor()});
await run('expand_source_transition',async p=>{await heading(p).waitFor();await click(p,'Fixture core');await badge(p).waitFor();await click(p,'Expand');await heading(p).waitFor({timeout:3000});await click(p,'Fixture all');await waitText(p,'5 of 5 sources active');await click(p,'Fixture partial');await waitText(p,'1 of 5 sources active')});
await run('unknown_stored',async p=>{await heading(p).waitFor();await p.evaluate(()=>localStorage.setItem('onboarding_checklist_dismissed','unknown'));await click(p,'Fixture core');await p.reload();await badge(p).waitFor()});
await run('dismiss_after_override',async p=>{await heading(p).waitFor();await click(p,'Fixture core');await badge(p).waitFor();await click(p,'Expand');await heading(p).waitFor({timeout:3000});await click(p,'Dismiss onboarding checklist');await panel(p).waitFor({state:'detached'});await click(p,'Fixture partial');await panel(p).waitFor({state:'detached'});await p.reload();await p.getByRole('button',{name:'Fixture core'}).waitFor();await panel(p).waitFor({state:'detached'})});
await run('storage_failure_dismiss',async p=>{await heading(p).waitFor();await click(p,'Dismiss onboarding checklist');await panel(p).waitFor({state:'detached'});await click(p,'Fixture core');await panel(p).waitFor({state:'detached'})},true);
await run('storage_failure',async p=>{await heading(p).waitFor();await click(p,'Fixture core');await badge(p).waitFor();await click(p,'Expand');await heading(p).waitFor({timeout:3000});await click(p,'Minimise');await badge(p).waitFor()},true);
await browser.close();console.log(JSON.stringify(result));})().catch(e=>{console.error(e);process.exit(1)});'''
CASES = ('initial','partial','optional','auto_core','auto_all','manual_incomplete','dismiss','dismiss_compact','storage_failure_incomplete','expand_core','expand_then_minimise','expand_source_transition','unknown_stored','dismiss_after_override','storage_failure_dismiss','storage_failure')

def snapshot():
    import hashlib
    names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).split(b'\0')
    result={}
    for raw in names:
        if not raw: continue
        p=ROOT/os.fsdecode(raw)
        if p.is_symlink(): result[str(p.relative_to(ROOT))]=('link',os.readlink(p))
        else: result[str(p.relative_to(ROOT))]=(p.stat().st_mode,hashlib.sha256(p.read_bytes()).hexdigest())
    return result

def stop(proc):
    if not proc: return
    try: os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError: pass
    try: proc.wait(timeout=5)
    except subprocess.TimeoutExpired: pass
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        try: os.killpg(proc.pid,0)
        except ProcessLookupError: return
        time.sleep(.1)
    try: os.killpg(proc.pid,signal.SIGKILL)
    except ProcessLookupError: pass
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        try: os.killpg(proc.pid,0)
        except ProcessLookupError: return
        time.sleep(.1)
    raise AssertionError(f'owned process group {proc.pid} remains alive')

def select_browser(modules, env):
    endpoint=os.environ.get('HLA_ONBOARDING_PLAYWRIGHT_WS')
    if endpoint: return endpoint, None
    executable=os.environ.get('HLA_CHROMIUM')
    mode=executable or 'bundled'
    js="const {chromium}=require('playwright');const p=process.argv[1];chromium.launch(p==='bundled'?{headless:true}:{headless:true,executablePath:p}).then(async b=>await b.close()).catch(e=>{console.error(e);process.exit(1)})"
    probe=subprocess.run([NODE,'-e',js,mode],cwd=WEB,env=env,capture_output=True,text=True,timeout=30)
    (OUT/'browser-preflight.log').write_text(probe.stdout+probe.stderr)
    if probe.returncode==0: return mode,None
    assert subprocess.run(['docker','image','inspect',IMAGE],capture_output=True).returncode==0, 'no functional browser or matched image'
    with socket.socket() as sock: sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    owner=uuid.uuid4().hex;name='hla-onboard-'+owner[:12]
    try:
        try:
            launch=subprocess.run(['docker','run','-d','--name',name,'--label','hla-onboard.owner='+owner,'--network','host','--ipc=host','-v',str(modules.resolve())+':/opt/node_modules:ro',IMAGE,'node','/opt/node_modules/playwright/cli.js','run-server','--host','127.0.0.1','--port',str(port)],capture_output=True,text=True,timeout=45)
            (OUT/'browser-launch.log').write_text(launch.stdout+launch.stderr)
        except subprocess.TimeoutExpired as exc:
            (OUT/'browser-launch.log').write_text('launch timeout; partial stdout='+repr(exc.stdout)+' stderr='+repr(exc.stderr)+'\n')
            raise
        ident=launch.stdout.strip()
        assert launch.returncode==0 and len(ident)==64, 'matched browser launch failed'
        for _ in range(40):
            logs=subprocess.run(['docker','logs',ident],capture_output=True,text=True);(OUT/'browser-server.log').write_text(logs.stdout+logs.stderr)
            if 'Listening on' in logs.stdout+logs.stderr: return f'ws://127.0.0.1:{port}/',(name,owner,ident)
            time.sleep(.5)
        raise AssertionError(f'browser startup failed: {name}')
    except BaseException:
        inspect=subprocess.run(['docker','inspect','--format','{{.Id}} {{index .Config.Labels "hla-onboard.owner"}}',name],capture_output=True,text=True)
        if inspect.returncode==0:
            fields=inspect.stdout.strip().split();assert len(fields)==2 and fields[1]==owner, 'browser startup ownership mismatch'
            cleanup_browser((name,owner,fields[0]))
        else:
            inventory=subprocess.run(['docker','ps','-a','--format','{{.Names}}'],capture_output=True,text=True)
            assert inventory.returncode==0 and name not in inventory.stdout.splitlines(),'browser startup cleanup unverified'
        raise

def cleanup_browser(owned):
    if not owned: return
    name,owner,ident=owned
    check=subprocess.run(['docker','inspect','--format','{{.Id}} {{index .Config.Labels "hla-onboard.owner"}}',name],capture_output=True,text=True)
    assert check.returncode==0 and check.stdout.strip()==ident+' '+owner,'browser ownership mismatch'
    removed=subprocess.run(['docker','rm','-f',ident],capture_output=True,text=True)
    inventory=subprocess.run(['docker','ps','-a','--no-trunc','--format','{{.ID}}'],capture_output=True,text=True)
    assert removed.returncode==0 and inventory.returncode==0 and ident not in inventory.stdout.splitlines(), 'browser removal unverified'

def _observations():
    OUT.mkdir(parents=True,exist_ok=True)
    before=snapshot(); (OUT/'source-fingerprint.json').write_text(json.dumps(before,sort_keys=True)+'\n'); modules=WEB/'node_modules'
    assert Path(NODE).is_file() and (modules/'next/package.json').is_file(), 'Node20/locked modules unavailable'
    version=subprocess.run([NODE,'--version'],capture_output=True,text=True); assert version.returncode==0 and version.stdout.startswith('v20.')
    with tempfile.TemporaryDirectory(prefix='hla-onboarding-lab-') as temp:
        temp=Path(temp); copy=temp/'web'; shutil.copytree(WEB,copy,ignore=shutil.ignore_patterns('node_modules','.next','test-results','playwright-report'))
        (copy/'node_modules').symlink_to(modules.resolve(),target_is_directory=True)
        target=copy/'app/acceptance-onboarding/page.jsx';target.parent.mkdir(parents=True);target.write_text(PAGE)
        script=copy/'onboarding-probe.cjs';script.write_text(SCRIPT)
        with socket.socket() as sock: sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env=dict(os.environ,PATH=str(Path(NODE).parent)+':'+os.environ.get('PATH',''))
        proc=browser_proc=owned=None
        errors=[]
        try:
            mode,owned=select_browser(modules,env)
            with (OUT/'next.log').open('w') as log:
                proc=subprocess.Popen([str(modules/'.bin/next'),'dev','-H','127.0.0.1','-p',str(port)],cwd=copy,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                url=f'http://127.0.0.1:{port}/acceptance-onboarding'
                for _ in range(120):
                    try:
                        with urllib.request.urlopen(url,timeout=2) as response:
                            if response.status==200: break
                    except (OSError,TimeoutError): pass
                    assert proc.poll() is None,'Next exited before ready; see next.log'
                    time.sleep(.5)
                else: raise AssertionError('Next not ready; see next.log')
                with (OUT/'browser.stdout').open('w') as stdout, (OUT/'browser.stderr').open('w') as stderr:
                    browser_proc=subprocess.Popen([NODE,str(script),url,mode],cwd=copy,env=env,stdout=stdout,stderr=stderr,start_new_session=True)
                    try: rc=browser_proc.wait(timeout=BROWSER_TIMEOUT)
                    except subprocess.TimeoutExpired:
                        (OUT/'browser.timeout').write_text('browser timed out; partial logs retained\n');raise AssertionError('browser timeout')
                (OUT/'browser.exit').write_text(str(rc)+'\n')
                assert rc==0,'browser failed; see browser.stderr'
                result=json.loads((OUT/'browser.stdout').read_text());assert set(result)==set(CASES),'case population mismatch'
        finally:
            primary=sys.exc_info()[1]
            if primary is not None: errors.append(f'primary: {type(primary).__name__}: {primary}')
            cleaned=[]
            for label, action in (('browser group',lambda:stop(browser_proc)),('Next group',lambda:stop(proc)),('browser container',lambda:cleanup_browser(owned))):
                try: action(); cleaned.append(label+' absent')
                except BaseException as exc: errors.append(f'{label}: {exc}')
            try:
                after=snapshot()
                if after!=before: errors.append('tracked source changed')
                (OUT/'source-invariance.txt').write_text('tracked source unchanged\n' if after==before else 'tracked source CHANGED\n')
            except BaseException as exc: errors.append(f'invariance: {exc}')
            (OUT/'cleanup.txt').write_text('\n'.join(cleaned)+'\n'+('\n'.join(errors)+'\n' if errors else 'none\n'))
            if errors: raise AssertionError('; '.join(errors))
    return result

@pytest.fixture(scope='module')
def observations():
    OUT.mkdir(parents=True,exist_ok=True)
    before=snapshot();result=None;errors=[]
    try:
        result=_observations()
    except BaseException as exc:
        errors.append(f'primary: {type(exc).__name__}: {exc}')
    finally:
        try:
            after=snapshot()
            if after!=before: errors.append('tracked source changed')
            (OUT/'outer-invariance.txt').write_text('tracked source unchanged\n' if after==before else 'tracked source CHANGED\n')
        except BaseException as exc: errors.append(f'outer invariance: {exc}')
        (OUT/'aggregate-errors.txt').write_text('\n'.join(errors)+'\n' if errors else 'none\n')
    if errors: raise AssertionError('; '.join(errors))
    return result

@pytest.mark.parametrize('case',CASES)
def test_onboarding(case, observations):
    assert observations[case]['ok'], observations[case].get('error')

def main():
    OUT.mkdir(parents=True,exist_ok=True); report=OUT/'junit.xml'
    rc=pytest.main(['-q','-p','no:cacheprovider',__file__,'--junitxml',str(report)])
    if rc: return int(rc)
    root=ET.parse(report).getroot();cases=list(root.iter('testcase'))
    assert len(cases)==len(CASES) and {c.get('name') for c in cases}=={f'test_onboarding[{x}]' for x in CASES}
    assert not any(list(root.iter(tag)) for tag in ('skipped','failure','error'))
    print(f'all {len(CASES)} named cases passed without skips');return 0
if __name__=='__main__': raise SystemExit(main())
