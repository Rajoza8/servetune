#!/usr/bin/env python3
"""Local Hard phase owner: exact remote record, owned cleanup, verified mirror.

Only run under hard_phase. No API/model/ledger mutation or lifecycle operation.
An adopt operation only waits on an existing durable worker and mirrors it.
"""
import argparse
from datetime import datetime,timezone
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

import hard_integrity as gate
from hard_vast import DEADLINE

OPS=gate.OPS;REPO=gate.REPO
REMOTE_REPO='/workspace/servedoctor-hard/servetune'
REMOTE_OPS='runs/servedoctor-hard-ops-20261102'
HELPERS=('hard_integrity.py','hard_job_observer.py','record_hard_stage.py','declare_hard_readiness.py','hard_recording_stage.py')

PREPARE=r'''
import hashlib,json,sys
from pathlib import Path
study,stage,mirror=map(Path,sys.argv[1:4]);expected=json.loads(sys.argv[4]);adopt=sys.argv[5]=='true'
frozen=json.loads((study/'hard-experiment-freeze.json').read_text())
for name,h in expected.items():
    path=Path('runs/servedoctor-hard-ops-20261102')/name
    assert frozen['files_sha256'][path.as_posix()]==h
    assert path.is_file() and not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest()==h
sys.path.insert(0,'runs/servedoctor-hard-ops-20261102')
from hard_integrity import verify_freeze,no_decisions
proof=verify_freeze(study.resolve())
if adopt:
    assert (stage/'plan.json').is_file() and (stage/'launch.json').is_file()
else:
    no_decisions(study)
    assert not (study/'answers/validity.json').exists() and not (study/'hard-validation-dispatch.json').exists()
    assert not stage.exists() and not stage.is_symlink()
stage.parent.mkdir(parents=True,exist_ok=True)
mirror.mkdir(parents=True,exist_ok=False)
print(json.dumps({'ready':True,'source_commit':proof['source_commit'],'freeze_sha256':hashlib.sha256((study/'hard-experiment-freeze.json').read_bytes()).hexdigest()}))
'''

LEDGER=r'''
import hashlib,json
from pathlib import Path
from servedoctor.llm import Ledger
path=Path('runs/servedoctor-ledger.json')
assert path.is_file() and not path.is_symlink()
print(json.dumps({'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'summary':Ledger(path).summary()}))
'''

ARCHIVE=r'''
import hashlib,json,sys,tarfile
from pathlib import Path
study,stage,out=map(Path,sys.argv[1:]);ledger=Path('runs/servedoctor-ledger.json')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def inventory(root):
    result={}
    if not root.exists():return result
    for p in sorted(root.rglob('*')):
        assert not p.is_symlink()
        if p.is_file():result[p.relative_to(root).as_posix()]=sha(p)
    return result
before=inventory(study);stage_before=inventory(stage);ledger_before=sha(ledger)
target=out/'study-record-ledger.tar.gz'
with tarfile.open(target,'x:gz') as archive:
    archive.add(study,arcname='study')
    if stage.exists():archive.add(stage,arcname='recording-stage')
    archive.add(ledger,arcname='canonical-ledger.json')
assert inventory(study)==before and inventory(stage)==stage_before and sha(ledger)==ledger_before
value={'project':'servedoctor-hard-20261102','stable':True,'study_files_sha256':before,'recording_stage_files_sha256':stage_before,
       'ledger_sha256':ledger_before,'archive_sha256':sha(target),'archive_bytes':target.stat().st_size}
manifest=out/'mirror-manifest.json'
with manifest.open('x') as stream:json.dump(value,stream,indent=2);stream.write('\n')
print(json.dumps({'archive':str(target),'archive_sha256':sha(target),'manifest':str(manifest),'manifest_sha256':sha(manifest),
                  'ledger_sha256':ledger_before,'stable':True,'study_file_count':len(before),'recording_stage_file_count':len(stage_before)}))
'''


def owner_deadlines(ops=OPS,clock=time.time):
    value=gate.load(Path(ops)/'active-command.json');now=clock();until=value.get('deadline_epoch');at=value.get('at_epoch')
    if (value.get('project')!=gate.PROJECT or value.get('pid') not in (os.getpid(),os.getppid())
            or any(type(v) not in (int,float) or not math.isfinite(v) for v in (until,at))
            or not 0<=now-at<=90 or not now+420<until<=min(DEADLINE,now+7200)):
        raise ValueError('Fresh owning Hard phase and seven-minute work/cleanup reserve required')
    return until-420,until-180


def scope_sha(ops):
    scope=gate.load(gate.regular(ops,'rental-scope.json'));session=gate.load(gate.regular(ops,'session.json'));checksum=gate.sha(ops/'rental-scope.json')
    fields=('project','label','instance_id','machine_id','offer_id','image')
    if (scope.get('project')!=gate.PROJECT or scope.get('label')!=gate.PROJECT or type(scope.get('instance_id')) is not int
            or scope['instance_id']<=0 or scope['instance_id'] in (58690026,58716527)
            or session.get('scope_sha256')!=checksum or any(session.get(k)!=scope.get(k) for k in fields)):
        raise ValueError('Current Hard scope/session binding differs')
    return checksum


def execute(args,*,ops=OPS,repo=REPO,run=subprocess.run,clock=time.time,ready=owner_deadlines):
    ops=Path(ops).resolve();repo=Path(repo).resolve();study=Path(args.study_dir).as_posix()
    if study!=gate.PRIMARY and not re.fullmatch(r'runs/sd-hard-[a-z0-9-]+-attempt[1-9][0-9]*',study):raise ValueError('Approved Hard root required')
    out=Path(args.out);out=out if out.is_absolute() else repo/out
    if out.parent.resolve()!=ops or not re.fullmatch('[a-z0-9][a-z0-9-]{0,95}',out.name):raise ValueError('Fresh direct Hard OPS output required')
    work_deadline,cleanup_deadline=ready(ops,clock);bound_scope=scope_sha(ops);source=gate.verify_source_policy(repo)
    out.mkdir(exist_ok=False);remote_stage=args.adopt_remote_stage or REMOTE_OPS+'/record-stages/'+out.name
    if not re.fullmatch(re.escape(REMOTE_OPS)+r'/record-stages/[a-z0-9][a-z0-9-]{0,95}',remote_stage):raise ValueError('Existing remote stage path is outside Hard scope')
    for prior in args.prior_stage:
        if not re.fullmatch(re.escape(REMOTE_OPS)+r'/record-stages/[a-z0-9][a-z0-9-]{0,95}',prior):raise ValueError('Prior remote stage path differs')
    remote_mirror=REMOTE_OPS+'/record-mirrors/'+out.name;remote=[sys.executable,str(ops/'remote.py')]
    result={'project':gate.PROJECT,'study_dir':study,'source_commit':source,'scope_sha256':bound_scope,
        'completed':False,'failure':None,'cleanup_errors':[],'remote_stage':remote_stage,'adopted_existing_worker':bool(args.adopt_remote_stage),
        'work_deadline_epoch':work_deadline,'cleanup_deadline_epoch':cleanup_deadline}
    deadline=work_deadline;prepared=False;work_attempted=False;worker_quiescent=False
    def command(label,argv,timeout=120,check=True):
        if scope_sha(ops)!=bound_scope:raise ValueError('Hard rental scope changed during this stage')
        remaining=deadline-clock()
        if remaining<=0:raise TimeoutError('Bounded local recording deadline reached')
        with (out/(label+'.stdout')).open('xb') as stdout,(out/(label+'.stderr')).open('xb') as stderr:
            finished=run(argv,cwd=repo,stdout=stdout,stderr=stderr,timeout=min(timeout,remaining))
        if check and finished.returncode:raise subprocess.CalledProcessError(finished.returncode,argv)
        return out/(label+'.stdout'),finished.returncode
    def json_command(label,argv,timeout=120):
        path,_=command(label,argv,timeout);return json.loads(path.read_text())
    def ledger(label):
        value=json_command(label+'-ledger',[*remote,'run','python3','-c',LEDGER])
        if value['summary'].get('caps_usd')!={'meta':50.0,'baseten':20.0}:raise ValueError('Canonical ledger caps differ')
        target=out/(label+'-canonical-ledger.json')
        command(label+'-ledger-mirror',[*remote,'get',REMOTE_REPO+'/runs/servedoctor-ledger.json',str(target)])
        if gate.sha(target)!=value['sha256']:raise ValueError('Canonical ledger changed during copy')
        gate.write_new(out/(label+'-ledger-summary.json'),value);return value
    try:
        hashes={name:gate.sha(ops/name) for name in HELPERS}
        evidence=json_command('prepare',[*remote,'run','python3','-c',PREPARE,study,remote_stage,remote_mirror,json.dumps(hashes),str(bool(args.adopt_remote_stage)).lower()])
        if evidence.get('ready') is not True or evidence.get('source_commit')!=source:raise ValueError('Remote frozen recording inputs differ')
        result['freeze_sha256']=evidence['freeze_sha256'];prepared=True
        # Copies are allowed only after verifying both existing GPU bytes and frozen hashes.
        for name in HELPERS:command('upload-'+name.replace('.py',''),[*remote,'put',str(ops/name),REMOTE_REPO+'/'+REMOTE_OPS+'/'+name])
        initial=ledger('initial')
        if args.expected_ledger_sha256 and initial['sha256']!=args.expected_ledger_sha256:raise ValueError('Expected canonical ledger lineage differs')
        operation='wait' if args.adopt_remote_stage else 'run'
        argv=[*remote,'run','python3',REMOTE_OPS+'/record_hard_stage.py',operation,'--study-dir',study,'--out',remote_stage]
        if not args.adopt_remote_stage:
            argv+=['--split',args.split]
            if args.ids:argv+=['--ids',args.ids]
            for prior in args.prior_stage:argv+=['--prior-stage',prior]
        work_attempted=True;value=json_command('record-owner',argv,timeout=7200)
        worker_quiescent=value.get('worker_exit_verified') is True
        if value.get('completed') is not True or value.get('returncode')!=0 or not worker_quiescent:raise ValueError('Canonical durable recording stage failed or worker still writing')
        result['record_owner']=value;result['completed']=True
    except BaseException as exc:result['failure']={'class':type(exc).__name__,'returncode':getattr(exc,'returncode',None)}
    finally:
        deadline=cleanup_deadline
        if work_attempted and not result['completed']:
            try:
                # One cleanup request to the already-launched worker; never launches a record.
                path,code=command('owned-worker-cleanup',[*remote,'run','python3',REMOTE_OPS+'/record_hard_stage.py','cancel','--out',remote_stage],timeout=125,check=False)
                result['cleanup_worker_returncode']=code
                witness=json.loads(path.read_text());worker_quiescent=witness.get('worker_exit_verified') is True
            except BaseException as exc:result['cleanup_errors'].append({'stage':'owned-worker-cleanup','class':type(exc).__name__})
        try:result['final_ledger']=ledger('final')
        except BaseException as exc:result['cleanup_errors'].append({'stage':'final-ledger','class':type(exc).__name__})
        result['worker_exit_verified']=worker_quiescent if work_attempted else None
        if work_attempted and not worker_quiescent:result['cleanup_errors'].append({'stage':'worker-exit-unconfirmed','class':'StageError'})
        if prepared and (not work_attempted or worker_quiescent):
            try:
                value=json_command('archive-prepare',[*remote,'run','python3','-c',ARCHIVE,study,remote_stage,remote_mirror],timeout=120)
                for key,name in [('archive','study-record-ledger.tar.gz'),('manifest','mirror-manifest.json')]:
                    target=out/name;command(key+'-mirror',[*remote,'get',REMOTE_REPO+'/'+value[key],str(target)],timeout=120)
                    if gate.sha(target)!=value[key+'_sha256']:raise ValueError('Opaque archive/manifest mirror hash differs')
                if value.get('stable') is not True:raise ValueError('Opaque source changed during archive')
                result['opaque_mirror']=value
            except BaseException as exc:result['cleanup_errors'].append({'stage':'opaque-mirror','class':type(exc).__name__})
        result['completed']=result['completed'] and not result['cleanup_errors'];result['finished_at_utc']=datetime.fromtimestamp(clock(),timezone.utc).isoformat()
        gate.write_new(out/'outcome.json',result);print(json.dumps(result),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study-dir',default=gate.PRIMARY)
    parser.add_argument('--split',choices=['reference','hard','all'],default='all');parser.add_argument('--ids')
    parser.add_argument('--prior-stage',action='append',default=[]);parser.add_argument('--adopt-remote-stage')
    parser.add_argument('--expected-ledger-sha256');parser.add_argument('--out',required=True);args=parser.parse_args()
    def interrupted(*_):raise InterruptedError()
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    return int(not execute(args)['completed'])


if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:sys.exit('Hard local recording stage failed: '+type(exc).__name__)
