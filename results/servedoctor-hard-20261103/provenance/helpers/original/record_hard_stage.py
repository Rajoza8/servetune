#!/usr/bin/env python3
"""Private durable Hard recorder. Launch/status only; no API or lifecycle calls.

The detached worker runs the exact public record CLI and an early-ready owned
job observer. All child streams are files, so SSH/controller loss cannot break
canonical logging. Failed paths are retained and are never dispatched again.
"""
import argparse
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
import hard_integrity as gate
import hard_job_observer as witness

SCRIPT=Path(__file__).resolve()


class StageError(RuntimeError):pass


def canonical_argv(root,split,ids,repo=gate.REPO):
    argv=[sys.executable,'-m','servedoctor','record','--study-dir',root.relative_to(repo).as_posix(),
        '--split',split,'--model-id','meta-models/Muse-Glimmer-30B','--model-revision',gate.REV,
        '--port','8000','--gpu-index','0','--dtype','bf16','--data-dir','data/gsm8k']
    if split=='hard':argv+=['--ids',','.join(sorted(ids))]
    return argv


def engine_paths(declared,selected):
    groups={}
    for case in declared:
        if case['id'] in selected:groups.setdefault(json.dumps(gate.engine_knobs(case['engine']),sort_keys=True),[]).append(case)
    return [f'engines/engine-{n:02d}-{group[0]["id"]}' for n,(_,group) in enumerate(sorted(groups.items(),key=lambda item:-len(item[1])))]


def scoped_rental(frozen,repo,ops,environ):
    path=gate.regular(ops,'rental-scope.json');value=gate.load(path)
    instance=value.get('instance_id')
    if (gate.sha(path)!=frozen['job_policy']['rental_scope_sha256'] or value.get('project')!=gate.PROJECT
            or value.get('label')!=gate.PROJECT or type(instance) is not int or instance<=0 or instance in (58690026,58716527)
            or str(instance)!=environ.get('CONTAINER_ID')):raise ValueError('Hard rental/namespace scope differs')
    return {'instance_id':instance,'scope':gate.descriptor(path)}


def active_owned(proc,repo):
    found=[]
    for pid in proc.pids():
        ident=proc.identity(pid)
        if not ident or ident['state']=='Z' or ident['uid']!=0 or ident['cwd']!=str(repo):continue
        argv=ident['argv'];module=argv[2] if len(argv)>2 and argv[1]=='-m' else None
        kind=('record' if module=='servedoctor' and argv[3:4]==['record'] else
              'job' if module in gate.JOB_MODULES else 'engine' if any('vllm' in arg.lower() for arg in argv) else None)
        if kind:found.append({'pid':pid,'start_ticks':ident['start_ticks'],'kind':kind})
    return found


def proof_data(paths,frozen,root,repo):
    jobs=[];physical={}
    for path in paths:
        proof=gate.load(path)
        if (proof.get('project')!=gate.PROJECT or proof.get('study_dir')!=root.relative_to(repo).as_posix()
                or proof.get('source_commit')!=frozen['source_commit'] or proof.get('freeze_sha256')!=gate.sha(root/gate.FREEZE)
                or proof.get('finished') is not True or proof.get('issues') or proof.get('owned_leaks')):
            raise ValueError('Prior observer did not finish cleanly')
        gate.verify_descriptor(proof['observations']);ready=gate.load(gate.verify_descriptor(proof['readiness']))
        if not gate.physical_matches(ready.get('physical_gpu_binding'),frozen):raise ValueError('Prior physical GPU binding differs')
        physical.update({name:ready['physical_gpu_binding'] for name in ready['selected_ids']});jobs.extend(proof['jobs'])
    return {'jobs':jobs,'physical_by_incident':physical}


def precheck(root,split,ids,prior_stages,*,repo=gate.REPO,ops=gate.OPS,proc=None,environ=None):
    repo=Path(repo).resolve();root=Path(root).resolve();ops=Path(ops).resolve();proc=proc or witness.ProcFS()
    frozen=gate.verify_freeze(root,repo);gate.no_decisions(root)
    if (root/'answers/validity.json').exists() or (root/gate.VALIDATION_DISPATCH).exists():raise ValueError('Recording must precede one-shot validation/evaluation')
    scope=scoped_rental(frozen,repo,ops,os.environ if environ is None else environ)
    declared=gate.cases(root);hard={s['id'] for s in declared if s['split']=='hard'}
    selected=set(ids) if ids is not None else hard
    if not selected or not selected<=hard:raise ValueError('Only public Hard IDs may be selected')
    if split not in ('reference','hard','all') or (split=='reference' and ids is not None):raise ValueError('Reference selection cannot be overridden')
    phases=([('reference',{'reference'})] if split in ('reference','all') else [])+([('hard',selected)] if split in ('hard','all') else [])
    all_selected=set().union(*(values for _,values in phases));known={s['id'] for s in declared}
    existing={p.name for p in (root/'incidents').iterdir()} if (root/'incidents').exists() else set()
    if (root/'incidents').is_symlink() or not existing<=known or existing&all_selected:raise ValueError('Selected recording exists or unknown/unsafe evidence is present; never retry')
    previous={};proofs=[];prior=[]
    for stage in prior_stages:
        stage=Path(stage).resolve()
        if not stage.is_relative_to(ops):raise ValueError('Prior stage must be scoped Hard OPS')
        path=gate.regular(stage,'exit.json');value=gate.load(path)
        if (value.get('project')!=gate.PROJECT or value.get('completed') is not True or value.get('returncode')!=0
                or value.get('source_commit')!=frozen['source_commit'] or value.get('freeze_sha256')!=gate.sha(root/gate.FREEZE)
                or value.get('study_dir')!=root.relative_to(repo).as_posix()):raise ValueError('Prior phase is failed/partial or has different frozen inputs')
        if set(previous)&set(value['recordings']):raise ValueError('Duplicate prior recording receipts')
        previous.update(value['recordings']);prior.append(gate.descriptor(path))
        for descriptor in value['owned_observer_proofs']:proofs.append(gate.verify_descriptor(descriptor))
    if existing!=set(previous):raise ValueError('Every prior recording needs a completed immutable stage receipt')
    if split=='hard' and 'reference' not in existing:raise ValueError('Complete reference must precede Hard recordings')
    runtime=root/'answers/runtime';runtime_ids={p.stem for p in runtime.iterdir()} if runtime.exists() else set()
    if runtime.is_symlink() or runtime_ids!=existing:raise ValueError('Prior opaque runtime coverage differs')
    owned=proof_data(proofs,frozen,root,repo)
    for case in declared:
        if case['id'] not in existing:continue
        quality=gate.audit_recording(root,case,frozen,owned)
        current={'manifest_sha256':quality.get('manifest_sha256'),'runtime_sha256':gate.sha(gate.regular(root,'answers/runtime/'+case['id']+'.json'))}
        if not quality['complete'] or current!=previous[case['id']]:raise ValueError('Prior recording is partial/changed or failed structural quality')
    engines=root/'engines'
    if engines.is_symlink():raise ValueError('Unsafe prior engine evidence')
    for folder in engines.iterdir() if engines.exists() else []:
        if folder.is_symlink() or not folder.is_dir() or (folder/'failure.json').exists():raise ValueError('Prior engine attempt is failed/unknown; use fresh reasoned study')
        meta=gate.load(gate.regular(folder,'engine_metadata.json'))
        if meta.get('cleanup_status')!='completed' or meta.get('returncode') is None:raise ValueError('Prior engine cleanup unconfirmed')
    plans=[]
    for phase,selected_ids in phases:
        paths=engine_paths(declared,selected_ids)
        if any((root/path).exists() or (root/path).is_symlink() for path in paths):raise ValueError('Expected engine artifact directory already exists')
        plans.append({'split':phase,'ids':sorted(selected_ids),'argv':canonical_argv(root,phase,selected_ids,repo),
            'engine_paths':paths,'nominal_recording_seconds':sum(s['duration_s'] for s in declared if s['id'] in selected_ids)})
    if active_owned(proc,repo):raise ValueError('An existing record/engine/job process must be reconciled before fresh dispatch')
    return {'project':gate.PROJECT,'study_dir':root.relative_to(repo).as_posix(),'source_commit':frozen['source_commit'],
        'freeze_sha256':gate.sha(root/gate.FREEZE),'split':split,'requested_ids':sorted(selected),
        'phases':plans,'prior_stage_receipts':prior,'prior_recordings':previous,
        'prior_owned_observer_proofs':[gate.descriptor(p) for p in proofs],'gpu_uuid':frozen['job_policy']['gpu_uuid'],**scope}


def capture_identity(process,argv,repo,proc,clock,sleep,timeout=5,require_fd=False):
    end=clock()+timeout
    while clock()<end:
        ident=proc.identity(process.pid)
        if ident and ident['state']!='Z' and ident['uid']==0 and ident['cwd']==str(repo) and ident['argv']==argv:
            if require_fd:
                limits=proc.limits(process.pid)
                if not limits or limits['fd_soft']!=65536 or limits['fd_hard']<65536:raise StageError('Canonical child descriptor proof differs')
                ident.update(limits)
            return ident
        if process.poll() is not None:break
        sleep(.02)
    raise StageError('Owned child identity was not observed')


def safe_signal(process,identity,signum,proc,signal_fn=os.kill):
    if process.poll() is not None:return
    current=proc.identity(process.pid)
    if not current or any(current[k]!=identity[k] for k in ('start_ticks','uid','cwd','argv')):raise StageError('Child identity changed; no signal sent')
    signal_fn(process.pid,signum)


def last_observer_issues(path):
    if not path.exists():return []
    lines=path.read_bytes().splitlines(keepends=True)
    if lines and not lines[-1].endswith(b'\n'):lines=lines[:-1]
    rows=[json.loads(line) for line in lines]
    return sorted({issue for row in rows for issue in row.get('issues',[])})


def check_ready(path,plan,phase,record_identity):
    value=gate.load(path)
    physical=value.get('physical_gpu_binding',{})
    if (value.get('project')!=gate.PROJECT or value.get('source_commit')!=plan['source_commit']
            or value.get('freeze_sha256')!=plan['freeze_sha256'] or value.get('recorder_pid')!=record_identity['pid']
            or value.get('recorder_start_ticks')!=record_identity['start_ticks'] or value.get('selected_ids')!=phase['ids']
            or value.get('selected_incident_directories_absent') is not True or value.get('ready_before_source_job_timers') is not True
            or physical.get('verified') is not True or physical.get('gpu_uuid')!=plan['gpu_uuid']
            or physical.get('instance_id')!=plan['instance_id'] or physical.get('rental_scope_sha256')!=plan['scope']['sha256']
            or physical.get('container_id_matches_scope') is not True or physical.get('gpu_index')!=0):raise StageError('Early observer readiness differs')


def run_phase(root,plan,phase,out,*,repo=gate.REPO,ops=gate.OPS,popen=subprocess.Popen,proc=None,clock=time.monotonic,sleep=time.sleep,signal_fn=os.kill):
    proc=proc or witness.ProcFS();out.mkdir(exist_ok=False)
    result={'project':gate.PROJECT,'split':phase['split'],'ids':phase['ids'],'completed':False,
        'record_returncode':None,'observer_returncode':None,'failure_class':None,'cleanup_errors':[]}
    record=observer=None;record_identity=observer_identity=None;handles=[]
    try:
        environment={k:v for k,v in os.environ.items() if not k.endswith('_API_KEY')}
        environment.update(PYTHONUNBUFFERED='1',HF_HOME='/workspace/.hf_home',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
            HF_HUB_DISABLE_TELEMETRY='1',VLLM_NO_USAGE_STATS='1',VLLM_CACHE_ROOT='/workspace/.vllm_cache')
        def output(name):
            stream=(out/name).open('xb');handles.append(stream);return stream
        record=popen(phase['argv'],cwd=repo,env=environment,stdin=subprocess.DEVNULL,
            stdout=output('record.stdout'),stderr=output('record.stderr'),start_new_session=True)
        record_identity=capture_identity(record,phase['argv'],repo,proc,clock,sleep,require_fd=True)
        gate.write_new(out/'record-identity.json',{**record_identity,'source_commit':plan['source_commit'],'freeze_sha256':plan['freeze_sha256']})
        observer_argv=[sys.executable,str(ops/'hard_job_observer.py'),'--study-dir',plan['study_dir'],
            '--recorder-pid',str(record.pid),'--recorder-start-ticks',str(record_identity['start_ticks']),
            '--out',str(out/'owned-observer.json'),'--ready-file',str(out/'observer-ready.json'),'--expected-ids',','.join(phase['ids'])]
        observer=popen(observer_argv,cwd=repo,env=environment,stdin=subprocess.DEVNULL,
            stdout=output('observer.stdout'),stderr=output('observer.stderr'),start_new_session=True)
        observer_identity=capture_identity(observer,observer_argv,repo,proc,clock,sleep,require_fd=True)
        gate.write_new(out/'observer-identity.json',observer_identity)
        ready_deadline=clock()+30
        while not (out/'observer-ready.json').exists():
            if record.poll() is not None or observer.poll() is not None or clock()>=ready_deadline:raise StageError('Observer did not prove readiness before recording')
            sleep(.1)
        check_ready(out/'observer-ready.json',plan,phase,record_identity)
        while record.poll() is None:
            if observer.poll() is not None and record.poll() is None:raise StageError('Observer ended before recorder')
            if last_observer_issues(out/'owned-observer.observations.jsonl'):raise StageError('Owned job infrastructure observation failed')
            sleep(1)
        result['record_returncode']=record.wait()
        result['observer_returncode']=observer.wait(timeout=15)
        if result['record_returncode']!=0 or result['observer_returncode']!=0:raise StageError('Canonical record or observer exited nonzero')
        proof=gate.load(out/'owned-observer.json')
        if proof.get('finished') is not True or proof.get('issues') or proof.get('owned_leaks'):raise StageError('Owned observer proof incomplete')
        gate.verify_descriptor(proof['observations']);gate.verify_descriptor(proof['readiness'])
        result['owned_observer_proof']=gate.descriptor(out/'owned-observer.json');result['completed']=True
    except BaseException as exc:result['failure_class']=type(exc).__name__
    finally:
        if record is not None and record.poll() is None:
            try:
                if record_identity is None:raise StageError('No safe child identity for cleanup')
                safe_signal(record,record_identity,signal.SIGINT,proc,signal_fn)
                result['record_returncode']=record.wait(timeout=90)
            except BaseException as exc:result['cleanup_errors'].append({'resource':'record','error_class':type(exc).__name__})
        elif record is not None:result['record_returncode']=record.returncode
        if observer is not None:
            try:result['observer_returncode']=observer.wait(timeout=15)
            except subprocess.TimeoutExpired:
                try:
                    if observer_identity is None:raise StageError('No safe observer identity for cleanup')
                    safe_signal(observer,observer_identity,signal.SIGINT,proc,signal_fn)
                    result['observer_returncode']=observer.wait(timeout=10)
                except BaseException as exc:result['cleanup_errors'].append({'resource':'observer','error_class':type(exc).__name__})
        if result['cleanup_errors']:result['completed']=False
        for stream in handles:stream.close()
        result['finished_at_utc']=gate.utc();gate.write_new(out/'phase-exit.json',result)
    return result


def worker(out,*,repo=gate.REPO,ops=gate.OPS,popen=subprocess.Popen,proc=None,environ=None):
    out=Path(out).resolve();plan=gate.load(gate.regular(out,'plan.json'));proc=proc or witness.ProcFS()
    identity=proc.identity(os.getpid());expected=[sys.executable,str(ops/'record_hard_stage.py'),'worker','--out',str(out)]
    if not identity or identity['uid']!=0 or identity['cwd']!=str(repo) or identity['argv']!=expected or identity['state']=='Z':
        raise StageError('Worker self identity differs before any canonical child')
    gate.write_new(out/'worker-start.json',{'project':gate.PROJECT,'pid':os.getpid(),'identity':identity,
        'started_at_utc':gate.utc(),'plan_sha256':gate.sha(out/'plan.json')})
    result={'project':gate.PROJECT,'study_dir':plan['study_dir'],'source_commit':plan['source_commit'],
        'freeze_sha256':plan['freeze_sha256'],'plan_sha256':gate.sha(out/'plan.json'),'completed':False,
        'returncode':1,'failure_class':None,'phases':[],'recordings':{},'owned_observer_proofs':[]}
    root=repo/plan['study_dir'];prior=[Path(d['path']).parent for d in plan['prior_stage_receipts']]
    try:
        current=precheck(root,plan['split'],plan['requested_ids'] if plan['split']!='reference' else None,prior,repo=repo,ops=ops,proc=proc,environ=environ)
        if any(plan.get(k)!=v for k,v in current.items()):raise StageError('Dispatch plan changed before worker')
        soft,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
        if hard!=resource.RLIM_INFINITY and hard<65536:raise StageError('Descriptor hard limit too low')
        resource.setrlimit(resource.RLIMIT_NOFILE,(65536,hard));result['limits']={'old_soft':soft,'new_soft':65536,'hard':hard}
        proofs=[gate.verify_descriptor(d) for d in plan['prior_owned_observer_proofs']]
        for number,phase in enumerate(plan['phases']):
            gate.verify_freeze(root,repo)
            if active_owned(proc,repo):raise StageError('Owned GPU processes remain before next canonical call')
            value=run_phase(root,plan,phase,out/f'{number:02d}-{phase["split"]}',repo=repo,ops=ops,popen=popen,proc=proc)
            result['phases'].append(value)
            if not value['completed']:raise StageError('Failed recording phase retained; no retry')
            path=gate.verify_descriptor(value['owned_observer_proof']);proofs.append(path)
            owned=proof_data(proofs,gate.verify_freeze(root,repo),root,repo)
            for case in gate.cases(root):
                if case['id'] not in phase['ids']:continue
                row=gate.audit_recording(root,case,gate.verify_freeze(root,repo),owned)
                if not row['complete']:raise StageError('New recording failed structural collection quality')
                result['recordings'][case['id']]={'manifest_sha256':row['manifest_sha256'],
                    'runtime_sha256':gate.sha(gate.regular(root,'answers/runtime/'+case['id']+'.json'))}
            result['owned_observer_proofs'].append(gate.descriptor(path))
        gate.verify_freeze(root,repo)
        if active_owned(proc,repo):raise StageError('Owned GPU processes remain after canonical cleanup')
        if {p.name for p in (root/'incidents').iterdir()}=={s['id'] for s in gate.cases(root)}:
            quality=gate.audit(root,proofs,repo);gate.write_new(out/'all17-quality.json',quality)
            result['all17_quality']=gate.descriptor(out/'all17-quality.json')
            if not quality['complete']:raise StageError('All17 collection quality failed')
        result.update(completed=True,returncode=0)
    except BaseException as exc:result['failure_class']=type(exc).__name__
    finally:
        try:
            result['remaining_owned_processes']=active_owned(proc,repo)
            if result['remaining_owned_processes']:result.update(completed=False,returncode=1)
        except BaseException as exc:result.update(completed=False,returncode=1,remaining_process_check_error=type(exc).__name__)
        try:
            for name,h in plan['prior_recordings'].items():
                if gate.sha(root/'incidents'/name/'manifest.json')!=h['manifest_sha256'] or gate.sha(root/'answers/runtime'/f'{name}.json')!=h['runtime_sha256']:
                    raise StageError('Prior immutable recordings changed')
            result['prior_recordings_unchanged']=True
        except BaseException as exc:result.update(completed=False,returncode=1,prior_preservation_error=type(exc).__name__)
        result['finished_at_utc']=gate.utc();gate.write_new(out/'exit.json',result)
    return result


def retained_worker_identity(out,process,argv,repo):
    """Trusted worker writes its own birth proof before it can launch a record."""
    try:
        proof=gate.load(gate.regular(out,'worker-start.json'));identity=proof['identity']
        if (proof.get('project')==gate.PROJECT and proof.get('plan_sha256')==gate.sha(out/'plan.json')
                and proof.get('pid')==process.pid and identity.get('pid')==process.pid and identity.get('uid')==0
                and identity.get('cwd')==str(repo) and identity.get('argv')==argv and identity.get('start_ticks',0)>0):return identity
    except (OSError,ValueError,KeyError,TypeError):pass
    return None


def launch(root,split,ids,prior_stages,out,*,repo=gate.REPO,ops=gate.OPS,popen=subprocess.Popen,proc=None,environ=None,process_holder=None):
    out=Path(out).resolve()
    if not out.is_relative_to(Path(ops).resolve()):raise ValueError('Fresh output must stay within Hard OPS')
    out.mkdir(exist_ok=False)
    process=None;worker_argv=None
    try:
        plan=precheck(root,split,ids,prior_stages,repo=repo,ops=ops,proc=proc,environ=environ)
        plan['created_at_utc']=gate.utc();gate.write_new(out/'plan.json',plan)
        with (out/'worker.stdout').open('xb') as stdout,(out/'worker.stderr').open('xb') as stderr:
            worker_argv=[sys.executable,str(ops/'record_hard_stage.py'),'worker','--out',str(out)]
            process=popen(worker_argv,
                cwd=repo,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
        identity=capture_identity(process,worker_argv,repo,proc or witness.ProcFS(),time.monotonic,time.sleep)
        value={'project':gate.PROJECT,'worker_pid':process.pid,'worker_identity':identity,'plan_sha256':gate.sha(out/'plan.json'),'started_at_utc':gate.utc()}
        gate.write_new(out/'launch.json',value)
        if process_holder is not None:process_holder['process']=process
        return value
    except BaseException as exc:
        failure={'project':gate.PROJECT,'error_class':type(exc).__name__,'at_utc':gate.utc(),'cleanup':{}}
        if process is not None:
            # Popen is retained: an unreaped direct child cannot be mistaken for
            # a reused PID, even when cross-process identity capture failed.
            identity=retained_worker_identity(out,process,worker_argv,repo)
            if identity is not None and not (out/'launch.json').exists():
                try:
                    gate.write_new(out/'launch.json',{'project':gate.PROJECT,'worker_pid':process.pid,'worker_identity':identity,
                        'plan_sha256':gate.sha(out/'plan.json'),'started_at_utc':gate.utc(),'capture_failed':True,'identity_source':'worker_self_before_canonical_child'})
                    failure['fallback_cancel_receipt']=True
                except BaseException as write_error:failure['fallback_receipt_error_class']=type(write_error).__name__
            try:
                if process.poll() is None:
                    if identity is not None:
                        try:
                            gate.write_new(out/'cleanup-request.json',{'project':gate.PROJECT,'requested_at_utc':gate.utc(),
                                'plan_sha256':gate.sha(out/'plan.json'),'worker_pid':process.pid,'worker_start_ticks':identity['start_ticks'],
                                'signal':'SIGINT','one_shot':True})
                        except BaseException as write_error:failure['cleanup']['marker_error_class']=type(write_error).__name__
                    process.send_signal(signal.SIGINT);failure['cleanup']['signal']='SIGINT'
                failure['cleanup']['returncode']=process.wait(timeout=120)
            except BaseException as cleanup_error:
                failure['cleanup']['error_class']=type(cleanup_error).__name__
                # If the self gate never completed, source ordering proves no
                # canonical child could have started. Only that retained child
                # may be force-reaped; a recording worker keeps its cancel path.
                if retained_worker_identity(out,process,worker_argv,repo) is None and process.poll() is None:
                    try:
                        process.kill();failure['cleanup']['forced_before_canonical_child']=True
                        failure['cleanup']['returncode']=process.wait(timeout=5)
                    except BaseException as kill_error:failure['cleanup']['reap_error_class']=type(kill_error).__name__
        gate.write_new(out/'launch-failure.json',failure);raise


def worker_exit_state(identity,proc):
    birth=proc.birth_state(identity['pid'])
    if birth is None:return 'absent'
    if birth['start_ticks']!=identity['start_ticks']:return 'pid_reused'
    if birth['state']=='Z':return 'zombie'
    current=proc.identity(identity['pid'])
    if current is None:raise StageError('Original worker still exists but identity is unreadable')
    if any(current[k]!=identity[k] for k in ('uid','cwd','argv')):raise StageError('Original worker identity changed before exit')
    return 'alive'


def wait_for_exit(out,*,proc=None,clock=time.monotonic,sleep=time.sleep,signal_fn=os.kill,max_wait_s=None,owned_process=None):
    """Adopt the existing worker; never creates a plan or dispatches a record."""
    proc=proc or witness.ProcFS();plan=gate.load(gate.regular(out,'plan.json'));launch_receipt=gate.load(gate.regular(out,'launch.json'))
    if launch_receipt.get('plan_sha256')!=gate.sha(out/'plan.json'):raise StageError('Existing launch plan differs')
    identity=launch_receipt['worker_identity'];interrupted=False;cleanup_deadline=clock()+max_wait_s if max_wait_s is not None else None
    while True:
        try:
            state=worker_exit_state(identity,proc)
            if state!='alive':
                if (out/'exit.json').exists():break
                raise StageError('Worker missing or replaced before durable exit; preserve and reconcile')
            if cleanup_deadline is not None and clock()>=cleanup_deadline:raise StageError('Verified worker cleanup did not finish; no signal retry')
            sleep(1)
        except KeyboardInterrupt:
            if interrupted:raise StageError('Repeated interruption during bounded cleanup')
            interrupted=True;cleanup_deadline=clock()+120
            current=proc.identity(identity['pid'])
            if not current or any(current[k]!=identity[k] for k in ('start_ticks','uid','cwd','argv')):raise StageError('Worker identity unproven; no signal sent')
            signal_fn(identity['pid'],signal.SIGINT)
    result=gate.load(gate.regular(out,'exit.json'))
    if (result.get('project')!=gate.PROJECT or result.get('plan_sha256')!=gate.sha(out/'plan.json')
            or result.get('study_dir')!=plan['study_dir'] or result.get('freeze_sha256')!=plan['freeze_sha256']):raise StageError('Durable worker exit binding differs')
    result={**result,'worker_exit_verified':True,'worker_exit_state':state,'worker_process_returncode':None}
    if owned_process is not None:
        result['worker_process_returncode']=owned_process.wait(timeout=5)
        if result['worker_process_returncode']!=result['returncode']:
            result.update(completed=False,returncode=1,failure_class='WorkerProcessReturncodeMismatch')
    return result


def request_cleanup(out,*,repo=gate.REPO,ops=gate.OPS,proc=None,signal_fn=os.kill,sleep=time.sleep,clock=time.monotonic):
    """One verified worker SIGINT; no GPU/API lifecycle operation or retry."""
    proc=proc or witness.ProcFS();launch_receipt=gate.load(gate.regular(out,'launch.json'));identity=launch_receipt['worker_identity']
    if (identity.get('uid')!=0 or identity.get('cwd')!=str(repo) or not witness.python_argv(identity.get('argv',[]))
            or identity['argv'][1:]!=[str(ops/'record_hard_stage.py'),'worker','--out',str(out)]):raise StageError('Worker cleanup command scope differs')
    marker=out/'cleanup-request.json'
    if marker.exists():
        prior=gate.load(marker)
        if (prior.get('project')!=gate.PROJECT or prior.get('plan_sha256')!=launch_receipt['plan_sha256']
                or prior.get('worker_pid')!=identity['pid'] or prior.get('worker_start_ticks')!=identity['start_ticks']
                or prior.get('signal')!='SIGINT' or prior.get('one_shot') is not True):raise StageError('Existing cleanup marker binding differs; no signal retry')
    if not (out/'exit.json').exists() and not marker.exists():
        current=proc.identity(identity['pid'])
        if not current or any(current[k]!=identity[k] for k in ('start_ticks','uid','cwd','argv')):raise StageError('Worker cleanup birth identity differs')
        gate.write_new(marker,{'project':gate.PROJECT,'requested_at_utc':gate.utc(),'plan_sha256':launch_receipt['plan_sha256'],
            'worker_pid':identity['pid'],'worker_start_ticks':identity['start_ticks'],'signal':'SIGINT','one_shot':True})
        signal_fn(identity['pid'],signal.SIGINT)
    return wait_for_exit(out,proc=proc,sleep=sleep,clock=clock,signal_fn=signal_fn,max_wait_s=120)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('operation',choices=['launch','run','wait','cancel','worker','status'])
    parser.add_argument('--study-dir',type=Path,default=Path(gate.PRIMARY));parser.add_argument('--split',choices=['reference','hard','all'],default='all')
    parser.add_argument('--ids');parser.add_argument('--prior-stage',type=Path,action='append',default=[]);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve()
    if not out.is_relative_to(gate.OPS):parser.error('Output must stay under private Hard OPS')
    if args.operation=='status':
        if (out/'exit.json').exists():
            receipt=gate.load(gate.regular(out,'launch.json'))
            if worker_exit_state(receipt['worker_identity'],witness.ProcFS())=='alive':
                print(json.dumps({'completed':False,'status':'worker_finalizing'}));return 2
            value=wait_for_exit(out);print(json.dumps({k:value.get(k) for k in ('completed','returncode','failure_class','source_commit','study_dir','prior_recordings_unchanged','worker_exit_verified')}));return int(not value['completed'])
        print(json.dumps({'completed':False,'status':'worker_exit_not_recorded','launch':gate.load(out/'launch.json') if (out/'launch.json').exists() else None}));return 2
    def interrupted(*_):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    if args.operation in ('wait','cancel'):
        value=request_cleanup(out) if args.operation=='cancel' else wait_for_exit(out)
        print(json.dumps({k:value.get(k) for k in ('completed','returncode','failure_class','worker_exit_verified','worker_process_returncode')}));return value['returncode']
    if args.operation=='worker':
        value=worker(out);print(json.dumps({'completed':value['completed'],'returncode':value['returncode'],'failure_class':value['failure_class']}));return value['returncode']
    root=(gate.REPO/args.study_dir).resolve()
    holder={};value=launch(root,args.split,args.ids.split(',') if args.ids else None,args.prior_stage,out,process_holder=holder)
    if args.operation=='run':
        value=wait_for_exit(out,owned_process=holder.get('process'))
        print(json.dumps({k:value.get(k) for k in ('completed','returncode','failure_class','worker_exit_verified','worker_process_returncode')}));return value['returncode']
    print(json.dumps(value));return 0


if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:sys.exit('Hard recorder orchestration failed: '+type(exc).__name__)
