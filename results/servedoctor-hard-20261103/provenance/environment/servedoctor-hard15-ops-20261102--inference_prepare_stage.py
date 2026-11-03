#!/usr/bin/env python3
"""One cold inference setup and opaque preserved-study transfer, then native validate once.

No generation, recording, calibration, model calls, credential access or rental
mutation. The owning three-hour controller controls lifecycle and deadlines.
"""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import time

import inference_integrity as gate
import inference_remote as remote
p=gate.p;OPS=gate.OPS;REPO=gate.REPO
PROJECT='servedoctor-hard15-inference-20261103'
REMOTE=Path('/workspace/servedoctor-hard/servetune')
DEPENDENCIES=('cpu_rules_adapter.py','package_partial_results.py',*p.PROTOCOL_HELPERS)
INSTALL=r'''
import hashlib,json,sys,tarfile
from pathlib import Path
archive,expected=Path(sys.argv[1]),sys.argv[2];repo=Path.cwd();assert hashlib.sha256(archive.read_bytes()).hexdigest()==expected
with tarfile.open(archive) as t:
 for m in t.getmembers():
  q=Path(m.name);assert not q.is_absolute() and '..' not in q.parts and (m.isfile() or m.isdir()) and not m.issym() and not m.islnk()
  dst=repo/q;assert all(not x.is_symlink() for x in (dst,*dst.parents))
  if dst.exists() and m.isfile():
   data=t.extractfile(m).read();assert dst.is_file() and dst.read_bytes()==data
  elif m.isdir():dst.mkdir(parents=True,exist_ok=True)
  else:
   dst.parent.mkdir(parents=True,exist_ok=True)
   with dst.open('xb') as f:f.write(t.extractfile(m).read())
print(json.dumps({'installed':True,'archive_sha256':expected}))
'''
ARM_GUARD=r'''
import hashlib,json,os,subprocess,sys,time
from pathlib import Path
control=Path('/workspace/servedoctor-hard/control');source=control/'inference-remote-guard.py';state=control/'inference-guard-state.json'
assert os.getuid()==0 and hashlib.sha256(source.read_bytes()).hexdigest()==sys.argv[1]
value=json.loads(state.read_text());assert os.environ.get('CONTAINER_ID')==str(value['instance_id'])
target=control/'inference-guard-process.json';assert not target.exists()
with (control/'inference-guard.log').open('xb') as log:
 child=subprocess.Popen([sys.executable,str(source)],cwd=control.parent,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
try:
 time.sleep(.2);assert child.poll() is None
 proc=Path('/proc')/str(child.pid);raw=(proc/'stat').read_text();birth=int(raw[raw.rfind(')')+2:].split()[19]);assert proc.stat().st_uid==0
 assert (proc/'cmdline').read_bytes().split(b'\0')[:-1]==[os.fsencode(sys.executable),os.fsencode(source)]
 result={'project':value['project'],'instance_id':value['instance_id'],'rental_scope_sha256':value['rental_scope_sha256'],
   'pid':child.pid,'start_ticks':birth,'uid':0,'cwd':str(control.parent),'guard_sha256':sys.argv[1],
   'state_sha256':hashlib.sha256(state.read_bytes()).hexdigest(),'deadline_epoch':value['deadline_epoch'],'captured_epoch':time.time()}
 with target.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
 print(json.dumps(result))
except BaseException:
 if child.poll() is None:child.terminate()
 try:child.wait(timeout=5)
 except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
 raise
'''
def write(x,v):return gate.write(x,v)
def binding_ready(repo=REPO,clock=time.time):
    path,value=gate.binding(repo);root=repo/p.OPS_REL/'inference-rental-attempt1';active=gate.load(root/'active-command.json');now=clock()
    if (active.get('project')!=PROJECT or active.get('pid') not in (os.getpid(),os.getppid())
        or not 0<=now-active.get('at_epoch',0)<=60 or not now+360<active.get('deadline_epoch',0)<=now+10800):raise ValueError('Fresh actual inference owner required')
    ready=gate.load(root/'guide-ready.json');reviewed=gate.load(root/'guide-reviewed.json')
    if (ready.get('instance_id')!=value['instance_id'] or ready.get('rental_scope_sha256')!=value['rental_scope_sha256']
        or reviewed.get('guide_sha256')!=ready.get('guide',{}).get('sha256')):raise ValueError('Exact full SSH guide must be reviewed before setup')
    return active['deadline_epoch']-360,path,value
def build_bundle(out,repo=REPO):
    repo=Path(repo).resolve();ops=repo/p.OPS_REL;old=repo/p.OLD_OPS_REL;preserved=old/'blocked-hard-study-attempt1';origin=preserved/'latest/study'
    p.verify_repository(repo)
    manifest=gate.load(preserved/'preserved-files-manifest.json');require=gate.require
    require(gate.sha(preserved/'preserved-files-manifest.json')==gate.PRESERVED,'preserved-manifest-differs')
    entries={n[len('latest/study/'):]:h for n,h in manifest['files'].items() if n.startswith('latest/study/')}
    require(len(entries)==178 and gate.inventory(origin)==entries,'original178-byte-inventory-differs')
    frozen=gate.load(origin/p.legacy.FREEZE);require(gate.sha(origin/p.legacy.FREEZE)==p.FREEZE,'original-freeze-differs')
    folder=out/'bundle';folder.mkdir();selected={}
    def copy(source,relative,expected=None):
        source=p.gate.regular(source);digest=gate.sha(source)
        if expected is not None:require(digest==expected,'bundle-source-hash-differs')
        target=folder/relative;target.parent.mkdir(parents=True,exist_ok=True)
        with source.open('rb') as a,target.open('xb') as b:shutil.copyfileobj(a,b)
        require(gate.sha(target)==digest,'bundle-copy-differs');selected[relative]=digest
    for name,h in entries.items():copy(origin/name,p.ORIGINAL+'/'+name,h)
    evidence=p.OPS_REL+'/'+gate.EVIDENCE
    for prefix in ('first9-proofs/recording-stage/','latest/recording-stage/'):
        for name,h in manifest['files'].items():
            if name.startswith(prefix):copy(preserved/name,evidence+'/'+name,h)
    for name in ('preserved-files-manifest.json','preservation-receipt.json'):copy(preserved/name,evidence+'/'+name)
    copy(old/'prepare-next-attempt1/declare-readiness.stdout',evidence+'/declare-readiness.stdout',gate.DECLARED)
    copy(ops/'original-portable-closure-audit.json',evidence+'/original-portable-closure-audit.json',gate.CLOSURE)
    for name in ('intent.json','response.json'):copy(ops/'stopped-preflight-recovery-attempt1'/name,evidence+'/stopped-preflight-recovery-attempt1/'+name)
    caldir=old/'bootstrap-calibration-controller-attempt8/mirror/runs/sd-hard-calibration-attempt1'
    calfiles=frozen['calibration_provenance']['calibration_files_sha256']
    require(gate.inventory(caldir)==calfiles,'original-calibration-inventory-differs')
    for name,h in calfiles.items():copy(caldir/name,evidence+'/calibration/runs/sd-hard-calibration-attempt1/'+name,h)
    for relative,h in frozen['files_sha256'].items():
        if relative.startswith(p.OLD_OPS_REL+'/'):copy(repo/relative,relative,h)
    for name in set((*DEPENDENCIES,*gate.HELPERS,'inference_cold_bootstrap.py')):copy(ops/name,p.OPS_REL+'/'+name)
    # Import-only old rental definitions are needed by the pinned map verifier;
    # their provider functions are never constructed or invoked by the gate.
    copy(old/'hard_vast.py',p.OLD_OPS_REL+'/hard_vast.py')
    for name in ('binding.json','rental-scope.json'):copy(ops/'inference-rental-attempt1'/name,p.OPS_REL+'/inference-rental-attempt1/'+name)
    bound=gate.load(ops/'inference-rental-attempt1/binding.json');ack=bound['create_ack'];ack_source=Path(ack['path'])
    require(ack_source.parent.resolve()==(ops/'inference-rental-attempt1').resolve(),'create-ack-outside-inference-scope')
    copy(ack_source,p.OPS_REL+'/inference-rental-attempt1/'+ack_source.name,ack['sha256'])
    # Continue the exact canonical ledger byte history; never ledger-init/reset.
    copy(repo/'runs/servedoctor-ledger.json','runs/servedoctor-ledger.json',p.SEED)
    copy(ops/'gpu-budget-amendment-43-20261102.json',p.OPS_REL+'/gpu-budget-amendment-43-20261102.json',gate.AMEND)
    gate.transport(ops/'inference-transport-attempt1',repo)
    for name in gate.TRANSPORT:copy(ops/'inference-transport-attempt1'/name,p.OPS_REL+'/inference-transport-attempt1/'+name)
    copy(old/'partial-analysis-exclusion-20261102T2306Z.json',p.OPS_REL+'/exclusion.json',p.EXCLUSION)
    archive=out/'portable-recording-inputs.tar.gz'
    with tarfile.open(archive,'x:gz') as t:
        for relative in sorted(selected):t.add(folder/relative,arcname=relative,recursive=False)
    write(out/'bundle-manifest.json',{'project':gate.PROJECT,'label':gate.LABEL,'files_sha256':selected,'archive_sha256':gate.sha(archive),
        'source_commit':gate.SOURCE,'original_files':178,'old_full_verify_freeze_claimed':False,'metadata_gaps':list(gate.MISSING)})
    return archive,frozen
def execute(args,repo=REPO,run=subprocess.run,clock=time.time,ready=binding_ready):
    repo=Path(repo).resolve();ops=repo/p.OPS_REL;out=Path(args.out).resolve();gate.require(out.parent==ops and not out.exists(),'fresh-direct-inference-preparation-output-required')
    deadline,binding,value=ready(repo,clock);cleanup_deadline=deadline+180;out.mkdir();result={'project':gate.PROJECT,'label':gate.LABEL,'completed':False,'failure':None,'cleanup_errors':[],'commands':[]}
    remote_ops=p.OPS_REL;remote_stage=REMOTE/remote_ops/'preparation-stages'/out.name
    def command(label,argv,timeout=180):
        remaining=deadline-clock()
        if remaining<=0:raise TimeoutError('Fixed inference setup deadline reached')
        row={'label':label,'started_at_utc':gate.utc()};result['commands'].append(row)
        with (out/(label+'.stdout')).open('xb') as stdout,(out/(label+'.stderr')).open('xb') as stderr:
            done=run(argv,cwd=repo,stdout=stdout,stderr=stderr,timeout=min(timeout,remaining))
        row.update(returncode=done.returncode,finished_at_utc=gate.utc())
        if done.returncode:raise subprocess.CalledProcessError(done.returncode,argv)
        return out/(label+'.stdout')
    def remote_run(label,argv,timeout=180):return command(label,remote.command('run',argv),timeout)
    try:
        archive,frozen=build_bundle(out,repo)
        options,address,port=remote.connection();tmp='/tmp/servedoctor-inference-bootstrap';control='/workspace/servedoctor-hard/control'
        ssh=['ssh',*options,'-p',str(port),'root@'+address]
        command('make-bootstrap-control',[*ssh,shlex.join(['mkdir','-p',tmp,control])])
        scope=gate.load(ops/'inference-rental-attempt1/rental-scope.json')
        approved={str(REMOTE/p.OPS_REL/n):gate.sha(ops/n) for n in ('inference_integrity.py','inference_measure_contexts.py','inference_response_guard.py','inference_export_scores.py')}
        approved[tmp+'/inference_cold_bootstrap.py']=gate.sha(ops/'inference_cold_bootstrap.py')
        state={'project':PROJECT,'instance_id':value['instance_id'],'rental_scope_sha256':value['rental_scope_sha256'],
            'deadline_epoch':scope['allocation_deadline_epoch'],'budget_deadline_epoch':scope['allocation_deadline_epoch'],'approved_helpers_sha256':approved}
        write(out/'inference-guard-state.json',state)
        for name,source in [('inference_cold_bootstrap.py',ops/'inference_cold_bootstrap.py'),('binding.json',binding),('scope.json',ops/'inference-rental-attempt1/rental-scope.json')]:
            command('upload-'+name,remote.command('put',[str(source),tmp+'/'+name]))
        for name,source in [('inference-remote-guard.py',ops/'inference_remote_guard.py'),('inference-guard-state.json',out/'inference-guard-state.json'),
                            ('rental-scope.json',ops/'inference-rental-attempt1/rental-scope.json'),('inference_cold_bootstrap.py',ops/'inference_cold_bootstrap.py')]:
            command('upload-control-'+name,remote.command('put',[str(source),control+'/'+name]))
        command('arm-fallback-guard',[*ssh,shlex.join(['/venv/main/bin/python','-c',ARM_GUARD,gate.sha(ops/'inference_remote_guard.py')])],30)
        result['fallback_guard']={'guard_sha256':gate.sha(ops/'inference_remote_guard.py'),'state_sha256':gate.sha(out/'inference-guard-state.json'),'scope_sha256':value['rental_scope_sha256']}
        code=['env','PATH=/venv/main/bin:/usr/local/bin:/usr/bin:/bin','HF_HOME=/workspace/.hf_home','HF_HUB_OFFLINE=0','TRANSFORMERS_OFFLINE=0','HF_HUB_DISABLE_TELEMETRY=1','VLLM_NO_USAGE_STATS=1',
              '/venv/main/bin/python',tmp+'/inference_cold_bootstrap.py','--binding',tmp+'/binding.json','--scope',tmp+'/scope.json',
              '--expected-vllm',frozen['job_policy']['vllm_version'],'--out','/workspace/servedoctor-hard/control/inference-cold-bootstrap-attempt1']
        launch="import os;os.chdir('/workspace/servedoctor-hard');os.execvp('env',"+repr(code)+")"
        command('cold-bootstrap',[*ssh,shlex.join(['/venv/main/bin/python','-c',launch])],1800)
        command('upload-portable-inputs',remote.command('put',[str(archive),tmp+'/portable-inputs.tar.gz']),300)
        remote_run('install-portable-inputs',['python3','-c',INSTALL,tmp+'/portable-inputs.tar.gz',gate.sha(archive)],180)
        remote_run('prepare-opaque-study',['python3',remote_ops+'/inference_integrity.py','prepare'],180)
        remote_run('validate-once',['python3',remote_ops+'/inference_integrity.py','validate-once','--out',str(ops.relative_to(repo)/'inference-validation-attempt1')],180)
        remote_run('verify-evaluation',['python3',remote_ops+'/inference_integrity.py','verify-evaluation','--out',str(ops.relative_to(repo)/'inference-validation-attempt1')],180)
        result['completed']=True
    except BaseException as error:result['failure']=type(error).__name__;raise
    finally:
        deadline=cleanup_deadline
        for label,source in [('bootstrap-evidence','/workspace/servedoctor-hard/control/inference-cold-bootstrap-attempt1'),('fallback-guard-proof','/workspace/servedoctor-hard/control/inference-guard-process.json'),('validation-evidence',str(REMOTE/p.OPS_REL/'inference-validation-attempt1')),('inference-hardware',str(REMOTE/p.OPS_REL/'inference-hardware.json')),('partial-study',str(REMOTE/p.PRIMARY))]:
            try:command('mirror-'+label,remote.command('get',[source,str(out/label)]),120)
            except BaseException as error:result['cleanup_errors'].append({'stage':label,'class':type(error).__name__})
        result['finished_at_utc']=gate.utc();write(out/'outcome.json',result)
    return result
def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--out',default=str(OPS/'inference-prepare-attempt1'));args=a.parse_args()
    def interrupted(signum,frame):raise InterruptedError('Owning controller ended inference preparation')
    previous=signal.signal(signal.SIGTERM,interrupted)
    try:print(json.dumps(execute(args)));return 0
    finally:signal.signal(signal.SIGTERM,previous)
if __name__=='__main__':raise SystemExit(main())
