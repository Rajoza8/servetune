#!/usr/bin/env python3
"""Stage approved fifteen-case infrastructure and dispatch native validation once."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

OPS=Path(__file__).resolve().parent
REPO=OPS.parent.parent
RENTAL=REPO/'runs/servedoctor-hard-ops-20261102'
sys.path.insert(0,str(RENTAL))
import hard_vast as h
LABEL='ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)'
REMOTE='/workspace/servedoctor-hard/servetune'
REL='runs/servedoctor-hard15-ops-20261102'
STUDY='runs/sd-hard-partial-attempt1'
GPU='GPU-ced6c24c-2234-f9e6-4b0f-6b11b82f9681'
EXCLUSION='783ae7be7b60c35146090911ac03d854ad0e5af366c4a178685dbed670a0d1d9'
PRESERVATION='0bb31a20b50ebb5db6c7680f54b22849c76cf007c9b0aa99f6d68bd4dfeb5af8'
HELPERS=('hard_partial_integrity.py','key_runner.py','hard_report_common.py','measure_contexts.py',
         'model_response_guard.py','export_hard_scores.py','partial_evaluation_stage.py')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,value):
    with Path(p).open('x') as f:json.dump(value,f,indent=2);f.write('\n')

def execute(args,service=None,run=subprocess.run):
    service=service or h.Rental();state=service.load();active=service.active()
    deadline=min(time.time()+600,active['deadline_epoch']-180)
    if (state['instance_id']!=58866756 or state['scope_sha256']!='c941c466f1e56180a66c6ebe98972c8507c4fa94bee6b3c96a419e3e6eed0b4c'
        or state.get('pending_intent') or state['last_status']['actual_status']!='running'
        or active['pid'] not in (os.getpid(),os.getppid()) or deadline<=time.time()+120):raise ValueError('Actual bounded running parent required')
    out=Path(args.out).resolve()
    if out.parent!=OPS or out.exists():raise ValueError('Fresh direct OPS15 output required')
    exclusion=RENTAL/'partial-analysis-exclusion-20261102T2306Z.json'
    preservation=RENTAL/'blocked-hard-study-attempt1/preservation-receipt.json'
    if sha(exclusion)!=EXCLUSION or sha(preservation)!=PRESERVATION:raise ValueError('Approved exclusion/preservation differs')
    files={name:sha(OPS/name) for name in HELPERS}
    fixtures=sorted(OPS.glob('*fixtures.json'))
    if not (OPS/'key-runner-fixtures.json').exists() or not (OPS/'partial-evaluation-stage-fixtures.json').exists():raise ValueError('Tested worker/stage required')
    out.mkdir();upload=out/'upload';upload.mkdir()
    for name in HELPERS:
        with (upload/name).open('xb') as f:f.write((OPS/name).read_bytes())
    for name,path in [('exclusion.json',exclusion),('preservation-receipt.json',preservation),*[(p.name,p) for p in fixtures]]:
        with (upload/name).open('xb') as f:f.write(path.read_bytes())
    plan={'project':'servedoctor-hard15-20261102','label':LABEL,'started_at_utc':datetime.now(timezone.utc).isoformat(),
          'source_commit':'4b0add12be36cef0d0776607f683310b1641b0f7','helpers_sha256':files,
          'exclusion_sha256':EXCLUSION,'preservation_sha256':PRESERVATION,'no_generation_or_recording':True}
    write(out/'plan.json',plan)
    result={**plan,'completed':False,'failure':None,'commands':[]};remote=[sys.executable,str(RENTAL/'remote.py')]
    def command(label,argv,timeout=90):
        remaining=deadline-time.time()
        if remaining<=0:raise TimeoutError('Fixed preparation deadline exhausted')
        entry={'name':label,'started_epoch':time.time()};result['commands'].append(entry)
        with (out/(label+'.stdout')).open('xb') as stdout,(out/(label+'.stderr')).open('xb') as stderr:
            value=run(argv,cwd=REPO,stdout=stdout,stderr=stderr,timeout=min(timeout,remaining))
        entry.update(returncode=value.returncode,finished_epoch=time.time())
        if value.returncode:raise subprocess.CalledProcessError(value.returncode,argv)
        return out/(label+'.stdout')
    try:
        p=command('verify-hardware',[*remote,'run','nvidia-smi','--id=0','--query-gpu=uuid','--format=csv,noheader'])
        if p.read_text().strip()!=GPU:raise ValueError('Recorded physical GPU changed')
        command('create-ops15',[*remote,'run','python3','-c',"from pathlib import Path; p=Path('"+REL+"'); assert not p.exists() and not p.is_symlink(); p.mkdir()"])
        for p in sorted(upload.iterdir()):command('upload-'+p.name.replace('.','-'),[*remote,'put',str(p),REMOTE+'/'+REL+'/'+p.name])
        check="import hashlib,json; from pathlib import Path; expected=json.loads(__import__('sys').argv[1]); assert all(hashlib.sha256((Path('"+REL+"')/n).read_bytes()).hexdigest()==v for n,v in expected.items()); print(json.dumps({'label':"+repr(LABEL)+",'helpers_verified':True}))"
        command('verify-upload',[*remote,'run','python3','-c',check,json.dumps(files)])
        argv=[*remote,'run','python3',REL+'/hard_partial_integrity.py','prepare','--study-dir',STUDY,
              '--exclusion',REL+'/exclusion.json','--preservation-receipt',REL+'/preservation-receipt.json']
        for suffix in ('record-first9-attempt1/00-reference/owned-observer.json','record-first9-attempt1/01-hard/owned-observer.json','record-last8-attempt1/00-hard/owned-observer.json'):
            argv+=['--owned-proof','runs/servedoctor-hard-ops-20261102/record-stages/'+suffix]
        command('prepare-preserved15',argv,180)
        command('validate-once',[*remote,'run','python3',REL+'/hard_partial_integrity.py','validate-once','--study-dir',STUDY,'--out',REL+'/validation-attempt1'],180)
        p=command('verify-evaluation',[*remote,'run','python3',REL+'/hard_partial_integrity.py','verify-evaluation','--study-dir',STUDY,'--out',REL+'/validation-attempt1'])
        verified=json.loads(p.read_text())
        if verified.get('total')!=15 or verified.get('label')!=LABEL or verified.get('evaluation_ready') is not True:raise ValueError('One-shot fifteen-case validity incomplete')
        command('validation-mirror',[*remote,'get',REMOTE+'/'+REL+'/validation-attempt1',str(OPS/'validation-attempt1')],180)
        command('exclusion-protocol-mirror',[*remote,'get',REMOTE+'/'+STUDY+'/analysis-protocol.json',str(out/'analysis-protocol.json')])
        result.update(completed=True,verification=verified)
    except BaseException as error:result['failure']={'class':type(error).__name__,'returncode':getattr(error,'returncode',None)}
    result['finished_at_utc']=datetime.now(timezone.utc).isoformat();write(out/'outcome.json',result)
    print(json.dumps(result),flush=True);return result

if __name__=='__main__':
    def interrupted(*_):raise InterruptedError('Preparation terminated; preserve one-shot dispatch evidence')
    signal.signal(signal.SIGTERM,interrupted)
    p=argparse.ArgumentParser();p.add_argument('--out',required=True)
    raise SystemExit(not execute(p.parse_args())['completed'])
