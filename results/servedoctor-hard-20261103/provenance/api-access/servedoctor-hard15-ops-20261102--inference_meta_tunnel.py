#!/usr/bin/env python3
"""Bind the unchanged TLS-blind Meta relay to the inference-only rental.

No credentials are read or inherited. One start/probe is recorded; failures
are retained without retry. Native Meta requests remain end-to-end TLS.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import inference_vast as v

OPS=Path(__file__).resolve().parent
REPO=OPS.parent.parent
CONTROL=OPS/'inference-rental-attempt1'
OUT=OPS/'inference-transport-attempt1'
OLD=REPO/'runs/servedoctor-hard-ops-20261102'
BASE_SHA='ade2ecbb3f732953fa80b33363d0e2ee56a3e781b9961eddeb52c2b4321a5f85'
RELAY_SHA='c3aa28f5c5784dbc0afde3a73a7492758432def5a5cc135172e9c16b4c8c9b5d'
LABEL='ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)'
PORT=48081


def blocked(*_a,**_k):raise RuntimeError('Rental provider operations are forbidden')
def service():return v.Rental(api=blocked,inventory=blocked)
def desc(p):return v.desc(p)
def write(p,data):v.write(p,data,exclusive=True)


def bound_instance(root=None):
    root=Path(CONTROL if root is None else root).resolve()
    if root!=CONTROL.resolve():raise ValueError('Exact inference control directory required')
    s=service().load();b=json.loads((root/'binding.json').read_text())
    if (s.get('destroyed_epoch') or s.get('pending_intent') or b.get('project')!=v.PROJECT
        or b.get('instance_id')!=s.get('instance_id') or b.get('rental_scope_sha256')!=s.get('scope_sha256')
        or b.get('budget_amendment',{}).get('sha256')!=v.AMENDMENT_SHA):raise ValueError('Inference transport binding differs')
    return s['instance_id']


def scope(root=None):
    instance=bound_instance(root);s=service().load();r=s.get('last_status',{})
    if r.get('id')!=instance or r.get('actual_status')!='running' or r.get('cur_state')!='running':
        raise ValueError('Bound running inference rental required')
    import ipaddress
    host=str(ipaddress.ip_address(r['public_ipaddr']));port=int(r['ports']['22/tcp'][0]['HostPort'])
    if not 1<=port<=65535:raise ValueError('Scoped SSH port differs')
    return host,port


def base_module():
    if v.sha(OLD/'meta_tunnel.py')!=BASE_SHA or v.sha(OLD/'meta_connect_relay.py')!=RELAY_SHA:
        raise ValueError('Frozen relay implementation changed')
    spec=importlib.util.spec_from_file_location('_inference_relay_core',OLD/'meta_tunnel.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    original_ssh=m.ssh_base
    m.OPS=CONTROL;m.LABEL=v.PROJECT;m.instance_id=bound_instance;m.scope=scope
    def ssh(host,port,*,ops=CONTROL,repo=REPO):
        if Path(ops).resolve()!=CONTROL.resolve():raise ValueError('SSH scope differs')
        return original_ssh(host,port,ops=CONTROL,repo=repo)
    def attempt(value,ops=CONTROL):
        p=Path(value).resolve()
        if p.parent!=CONTROL.resolve() or not p.name.startswith('meta-relay-attempt-'):
            raise ValueError('Owned inference relay attempt required')
        return p
    m.ssh_base=ssh;m.attempt_dir=attempt
    return m


def stop(include_guardian=True):
    pointer=OUT/'relay-pointer.json'
    if not pointer.is_file():return {'stopped':True,'never_started':True}
    m=base_module();value=json.loads(pointer.read_text());attempt=m.attempt_dir(value['attempt_dir'])
    ready=json.loads((attempt/'transport-ready.json').read_text())
    if ready.get('instance_id')!=value.get('instance_id'):raise ValueError('Relay ownership differs')
    result={'cleanup':m.cleanup(attempt,ready['owned_processes'])}
    result['stopped']=not any('error_class' in item for item in result['cleanup'])
    guardian=OUT/'guardian-process.json'
    if include_guardian and guardian.is_file():
        record=json.loads(guardian.read_text())
        if record['pid']!=os.getpid():result['guardian']=m.terminate_owned(record)
    path=OUT/('stop-'+str(time.time_ns())+'.json');write(path,result)
    return result


def guardian():
    value=json.loads((OUT/'relay-pointer.json').read_text());m=base_module()
    while True:
        now=time.time();owner=m.identity(value['owner_pid'])
        if now>=value['allocation_deadline_epoch'] or owner is None or owner.get('start_identity')!=value['owner_birth']:
            result=stop(include_guardian=False);write(OUT/'guardian-cleanup.json',result);return
        time.sleep(min(10,max(.1,value['allocation_deadline_epoch']-now)))


def start():
    r=service();r.active();state=r.load();scope();owner=json.loads((CONTROL/'active-command.json').read_text())
    if owner['pid'] not in (os.getpid(),os.getppid()):raise ValueError('Actual inference parent required')
    if OUT.exists():raise ValueError('Transport attempt already exists; no retry')
    m=base_module();OUT.mkdir();attempt=None;proc=None
    try:
        for name,expected in [('meta_connect_relay.py',RELAY_SHA),('meta_tunnel.py',BASE_SHA)]:
            source=OLD/name;target=CONTROL/name
            if target.exists():
                if v.sha(target)!=expected:raise ValueError('Relay core copy differs')
            else:
                with source.open('rb') as a,target.open('xb') as b:shutil.copyfileobj(a,b)
            if v.sha(target)!=expected:raise ValueError('Relay core changed')
        result=m.start(PORT,[CONTROL/'rental-scope.json',CONTROL/'binding.json'],ops=CONTROL,repo=REPO,host_scope=scope)
        attempt=Path(result['attempt_dir']);ready=json.loads((attempt/'transport-ready.json').read_text())
        pointer={'project':v.PROJECT,'label':LABEL,'instance_id':state['instance_id'],'rental_scope_sha256':state['scope_sha256'],
            'attempt_dir':str(attempt),'owner_pid':owner['pid'],'owner_birth':owner['birth'],
            'allocation_deadline_epoch':state['allocation_deadline_epoch'],'adapter':desc(__file__),
            'core_launcher_sha256':BASE_SHA,'core_relay_sha256':RELAY_SHA,'key_environment_inherited':False}
        write(OUT/'relay-pointer.json',pointer)
        proof=m.probe(attempt)
        if proof.get('verified') is not True:raise RuntimeError('One explicit unauthenticated TLS probe failed')
        for source,name in [('api-transport.json','api-transport.json'),('transport-ready.json','api-transport-receipt.json'),
                            ('transport-channel-proof.json','api-transport-channel-proof.json')]:
            with (attempt/source).open('rb') as a,(OUT/name).open('xb') as b:shutil.copyfileobj(a,b)
        with (OUT/'guardian.stdout').open('xb') as stdout,(OUT/'guardian.stderr').open('xb') as stderr:
            proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'guardian'],stdin=subprocess.DEVNULL,
                stdout=stdout,stderr=stderr,env=m.MINIMAL_ENV,start_new_session=True)
        ident=m.identity(proc.pid)
        if ident is None:
            m.cleanup_spawned_child(proc);raise RuntimeError('Relay guardian identity unavailable')
        write(OUT/'guardian-process.json',ident)
        result={'project':v.PROJECT,'label':LABEL,'ready':True,'instance_id':state['instance_id'],
            'rental_scope_sha256':state['scope_sha256'],'verified_unauthenticated_get':True,'paid_calls':0,
            'files_sha256':{name:v.sha(OUT/name) for name in ('api-transport.json','api-transport-receipt.json','api-transport-channel-proof.json')},
            'adapter':desc(__file__),'core_launcher_sha256':BASE_SHA,'core_relay_sha256':RELAY_SHA}
        write(OUT/'result.json',result);return result
    except BaseException as error:
        cleanup=None
        if attempt is not None:
            try:
                if (OUT/'relay-pointer.json').exists():cleanup=stop()
                else:
                    record=json.loads((attempt/'transport-ready.json').read_text())
                    cleanup={'cleanup':m.cleanup(attempt,record['owned_processes'])}
            except Exception as failure:cleanup={'error_class':type(failure).__name__}
        if proc is not None:
            try:m.cleanup_spawned_child(proc)
            except Exception:pass
        write(OUT/'failure.json',{'class':type(error).__name__,'cleanup':cleanup,'no_retry':True})
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=('start','stop','guardian'));args=p.parse_args()
    result={'guardian':guardian,'start':start,'stop':stop}[args.operation]()
    if result is not None:print(json.dumps(result))
if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit('Inference Meta relay refused: '+type(error).__name__) from None
