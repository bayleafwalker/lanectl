#!/usr/bin/env python3
"""Read-only identity and empty-schema preflight; no publication or cleanup."""
import argparse, json, re, subprocess, sys

def run(*args):
    p = subprocess.run(args, capture_output=True, text=True, check=True)
    if not p.stdout.strip(): raise ValueError('empty command response')
    return p.stdout

def require(value, message):
    if not value: raise ValueError(message)

def check_identity(config, api, pg, network, volume, members):
    require(re.fullmatch(r'[0-9a-f]{40}', config['sha']), 'invalid source SHA')
    require(config['project'] == 'lane-dev-' + config['train_id'], 'project not owned lane')
    for service, container, expected in [('api', api, config['api_id']), ('postgres', pg, config['pg_id'])]:
        require(container['Id'] == expected, f'{service} container identity mismatch')
        labels = container['Config'].get('Labels') or {}
        require(labels.get('com.docker.compose.project') == config['project'], 'project mismatch')
        require(labels.get('com.docker.compose.service') == service, 'service mismatch')
        require(container['State']['Running'], f'{service} is not running')
    require(api['Image'] == config['api_image'], 'API image identity mismatch')
    require(network['Id'] == config['network_id'], 'network identity mismatch')
    require(network.get('Labels', {}).get('com.docker.compose.project') == config['project'], 'network project mismatch')
    require(volume['Name'] == config['volume'], 'volume identity mismatch')
    require(volume.get('Labels', {}).get('com.docker.compose.project') == config['project'], 'volume project mismatch')
    require(any(m.get('Name') == config['volume'] and m['Destination'] == '/var/lib/postgresql/data' for m in pg['Mounts']), 'postgres volume mismatch')
    require(config['api_id'] in members and config['pg_id'] in members, 'containers absent from network')
    require(set(members) == set(config['network_members']), 'unexpected network members')
    env = dict(x.split('=',1) for x in api['Config']['Env'] if '=' in x)
    require(env.get('HOMELAB_ANALYTICS_REPORTING_BACKEND') == 'postgres', 'reporting backend mismatch')
    require(env.get('HOMELAB_ANALYTICS_REPORTING_POSTGRES_DSN') == 'postgresql://homelab:homelab@postgres:5432/homelab', 'reporting audience mismatch')
    require(env.get('HOMELAB_ANALYTICS_REPORTING_SCHEMA', 'reporting') == 'reporting', 'reporting schema mismatch')
    return True

def check_receipt(cfg):
    from datetime import datetime, timezone
    with open(cfg['event_log']) as stream:
        events=[json.loads(line) for line in stream if line.strip()]
    relevant=[e for e in events if (e.get('data') or {}).get('train_id')==cfg['train_id']]
    builds=[e['data'] for e in relevant if e.get('type')=='train.built']
    deploys=[(i,e) for i,e in enumerate(relevant) if e.get('type')=='train.deployed']
    require(builds and deploys, 'train receipt absent')
    build=builds[-1]; index,deploy_event=deploys[-1]; deploy=deploy_event['data']
    require(build.get('passed') is True and build.get('checked_sha')==cfg['sha'], 'train build receipt mismatch')
    require(deploy.get('passed') is True and deploy.get('checked_sha')==cfg['sha'] and deploy.get('namespace')==cfg['project'], 'deploy receipt mismatch')
    require(deploy.get('repo')==build.get('repo')==cfg['repo'], 'receipt repository mismatch')
    require(not any(e.get('type') in ('train.torn_down','train.built') for e in relevant[index+1:]), 'deploy superseded or torn down')
    require(datetime.fromisoformat(deploy['expires_at'].replace('Z','+00:00'))>datetime.now(timezone.utc), 'deploy receipt expired')
    require(build.get('worktree')==cfg['source_path'], 'receipt worktree mismatch')
    return deploy_event

def parse_utc(value):
    from datetime import datetime, timezone
    require(isinstance(value,str) and value.endswith('Z'), 'timestamp must be UTC Z')
    return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc)

def check_fresh_volume(cfg, volume, deploy_event, proof, docker_server_id):
    from datetime import timedelta
    require(proof.get('schema')=='hla-volume-absence/v1', 'invalid volume absence proof')
    for name in ('project','train_id','sha','source_path','volume'):
        require(proof.get(name)==cfg[name], 'volume absence proof context mismatch: '+name)
    require(proof.get('docker_server_id')==docker_server_id and docker_server_id, 'volume proof Docker server mismatch')
    require(proof.get('command')=='docker volume ls --format {{.Name}}', 'volume proof command mismatch')
    require(proof.get('exit_code')==0 and isinstance(proof.get('volume_names'),list), 'volume absence probe failed')
    require(cfg['volume'] not in proof['volume_names'], 'volume existed at predeploy probe')
    observed_text=proof.get('observed_at','')
    require(re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z',observed_text), 'volume observation must have UTC microsecond precision')
    observed=parse_utc(observed_text)
    from datetime import datetime, timezone
    created=datetime.fromisoformat(volume['CreatedAt'].replace('Z','+00:00'))
    require(created.tzinfo is not None, 'volume timestamp lacks timezone')
    created=created.astimezone(timezone.utc)
    receipt_ts=deploy_event.get('ts','')
    require(re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',receipt_ts), 'unexpected deploy timestamp precision')
    # Docker timestamps can carry nanoseconds, parsed at microsecond precision.
    # Require a positive microsecond gap; lanectl event time is truncated to seconds,
    # so its exclusive upper bound is the following second.
    require(created-observed >= timedelta(microseconds=1), 'volume predates absence observation')
    require(created < parse_utc(receipt_ts)+timedelta(seconds=1), 'volume created after deploy receipt')
    return {'absence_observed_at':observed_text,'volume_created_at':volume['CreatedAt'],'deploy_recorded_at':receipt_ts}

def check_dns(cfg, api, pg, network, resolved, inspected_members):
    endpoints=network.get('Containers') or {}
    pg_ip=endpoints.get(cfg['pg_id'],{}).get('IPv4Address','').split('/')[0]
    require(pg_ip, 'postgres network address missing')
    pg_networks=pg.get('NetworkSettings',{}).get('Networks',{})
    matching=[n for n in pg_networks.values() if n.get('NetworkID')==cfg['network_id']]
    require(len(matching)==1 and matching[0].get('IPAddress')==pg_ip and 'postgres' in (matching[0].get('Aliases') or []), 'postgres network alias mismatch')
    for item in inspected_members:
        if item['Id']==cfg['pg_id']: continue
        for n in item.get('NetworkSettings',{}).get('Networks',{}).values():
            require(n.get('NetworkID')!=cfg['network_id'] or 'postgres' not in (n.get('Aliases') or []), 'postgres alias claimed by another container')
    require(set(resolved)=={pg_ip}, 'postgres DNS does not resolve only to expected container')
    return pg_ip

def check_sessions(sessions, api_ip):
    # pg_isready opens only transient health probes. No stable identity is
    # available to distinguish those from arbitrary local clients, so reject
    # every local/loopback session as well as all other unexpected clients.
    require(all(addr==api_ip for addr,app,user in sessions), 'unexpected database client')

def main():
    p=argparse.ArgumentParser(); p.add_argument('config'); p.add_argument('--allow-nonempty', action='store_true'); args=p.parse_args()
    cfg=json.load(open(args.config))
    for key in ('api_id','pg_id','api_image','network_id'):
        require(re.fullmatch(r'(?:sha256:)?[0-9a-f]{64}',cfg[key]), f'invalid {key}')
    deploy_event=check_receipt(cfg)
    sha=run('git','-C',cfg['source_path'],'rev-parse','HEAD').strip()
    require(sha == cfg['sha'], 'source revision mismatch')
    require(subprocess.run(['git','-C',cfg['source_path'],'diff','--quiet','HEAD','--'],check=False).returncode == 0, 'source tree changed')
    def inspect(kind, name): return json.loads(run('docker',kind,'inspect',name))[0]
    api=inspect('container',cfg['api_id']); pg=inspect('container',cfg['pg_id']); net=inspect('network',cfg['network_id']); vol=inspect('volume',cfg['volume'])
    check_identity(cfg,api,pg,net,vol,list((net.get('Containers') or {}).keys()))
    with open(cfg['predeploy_volume_proof']) as stream: proof=json.load(stream)
    docker_server_id=run('docker','info','--format','{{.ID}}').strip()
    volume_times=check_fresh_volume(cfg,vol,deploy_event,proof,docker_server_id)
    all_ids=run('docker','ps','--no-trunc','-q','--filter','label=com.docker.compose.project='+cfg['project']).split()
    require(set(all_ids)==set(cfg['project_containers']), 'unexpected project container')
    require(set(cfg['network_members']).issubset(set(all_ids)), 'network has a non-project member')
    member_items=[]
    for cid in all_ids:
        item=inspect('container',cid)
        member_items.append(item)
        service=(item['Config'].get('Labels') or {}).get('com.docker.compose.service','')
        require(service in ('api','postgres','minio','web'), 'unexpected writer service')
        require(cid in (cfg['api_id'],cfg['pg_id']) or not any(m.get('Name')==cfg['volume'] for m in item['Mounts']), 'unexpected volume attachment')
    dns_code="import json,socket;print(json.dumps(sorted(set(x[4][0] for x in socket.getaddrinfo('postgres',5432,type=socket.SOCK_STREAM)))))"
    resolved=json.loads(run('docker','exec',cfg['api_id'],'python','-c',dns_code))
    pg_ip=check_dns(cfg,api,pg,net,resolved,member_items)
    # Compare the complete tracked Python source tree with the image, including
    # extra image-side Python files, instead of trusting caller-supplied SHA labels.
    import hashlib
    paths=[p for p in run('git','-C',cfg['source_path'],'ls-tree','-r','--name-only',sha,'--','packages','apps').splitlines() if p.endswith('.py')]
    require(paths and 'packages/domains/overview/pipelines/attention_records.py' in paths, 'missing checked source')
    manifest={}
    for path in paths:
        data=subprocess.run(['git','-C',cfg['source_path'],'show',f'{sha}:{path}'],capture_output=True,check=True).stdout
        manifest[path]=hashlib.sha256(data).hexdigest()
    code="""import hashlib,json,pathlib
r=pathlib.Path('/app'); d={}
for top in ('packages','apps'):
 for p in (r/top).rglob('*.py'):
  d[str(p.relative_to(r))]=hashlib.sha256(p.read_bytes()).hexdigest()
print(json.dumps(d))
"""
    actual=json.loads(run('docker','exec',cfg['api_id'],'python','-c',code))
    require(actual==manifest, 'image Python source provenance mismatch')
    # Ask API-container Python to use only the checked-in example DSN. Never print it.
    probe="""import json,psycopg\nwith psycopg.connect('postgresql://homelab:homelab@postgres:5432/homelab', application_name='hla_qualification_preflight') as c:\n print(json.dumps({'audience':c.execute('select current_database(), current_user').fetchone(),'objects':c.execute(\"select c.relname,c.relkind from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='reporting' order by 1\").fetchall(),'other_sessions':c.execute(\"select coalesce(client_addr::text,'local'), coalesce(application_name,''),usename from pg_stat_activity where datname=current_database() and pid<>pg_backend_pid() and backend_type='client backend'\").fetchall()}))\n"""
    result=json.loads(run('docker','exec','-i',cfg['api_id'],'python','-c',probe))
    require(result['audience']==['homelab','homelab'], 'database audience mismatch')
    require(args.allow_nonempty or not result['objects'], 'reporting namespace is nonempty; do not retry')
    api_ip=(net.get('Containers') or {}).get(cfg['api_id'],{}).get('IPv4Address','').split('/')[0]
    require(api_ip, 'API network address missing')
    check_sessions(result['other_sessions'],api_ip)
    print(json.dumps({'preflight':'pass','project':cfg['project'],'sha':sha,'api_id':cfg['api_id'],'pg_id':cfg['pg_id'],'api_image':cfg['api_image'],'network_id':cfg['network_id'],'volume':cfg['volume'],'reporting_objects':result['objects'],'postgres_ip':pg_ip,'volume_proof':volume_times},indent=2))

if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('REFUSED: '+str(exc),file=sys.stderr); sys.exit(1)
