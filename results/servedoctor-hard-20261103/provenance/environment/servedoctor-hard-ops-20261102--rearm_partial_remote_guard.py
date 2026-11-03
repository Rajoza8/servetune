#!/usr/bin/env python3
"""Rearm host5 for the approved15-case partial analysis after a proved restart.

First invocation binds immutable bootstrap process/state/source snapshots; later
invocations bind their own successful receipt lineage. An explicit proved restart permits only the old birth to be absent.
No provider calls, GPU lifecycle changes, credential reads or mutation retries.
"""
import argparse
import fcntl
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid

import hard_vast
from prepare_next_hard_study import rental_binding

OPS=Path(__file__).resolve().parent
BASE=Path('/workspace/servedoctor-hard')
PYTHON='/venv/main/bin/python'
PROJECT='servedoctor-hard-20261102'
CUTOFF=1793746800.0
INITIAL_GUARD_SHA='95fd839de039206460055da889a574a4a9846b85e5dde9c482d251d44eec40eb'
INSTANCE=58866756
SCOPE_SHA='c941c466f1e56180a66c6ebe98972c8507c4fa94bee6b3c96a419e3e6eed0b4c'
STOPPED_STATE_SHA='4b01fa0a1789447c916ad323fc12ee18ff9d54d285e2d81029b53c7edebeb4b6'
ANCESTOR_HELPER_SHA='dde0cd76dfc059b0419d6bb3898c9016d0507cdc6a4c447dcbf6794eb217f7ee'
ANCESTOR_RECEIPT_SHA='1d7e30a42b3a791df7362ee8e21b19af2fa89dc4bc6617b6c6168503c8a35714'


def digest(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError('Regular evidence required')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path,value):
    with Path(path).open('xb') as stream:
        stream.write((json.dumps(value,indent=2,allow_nan=False)+'\n').encode())
        stream.flush();os.fsync(stream.fileno())


def descriptor(path):return {'path':str(Path(path).resolve()),'sha256':digest(path)}


def argv_hash(base):
    return hashlib.sha256(b'\0'.join(p.encode() for p in (PYTHON,str(Path(base)/'control/remote_guard.py')))+b'\0').hexdigest()


def same_identity(actual,expected):
    return (actual is not None and actual.get('state')!='Z'
            and all(actual.get(k)==expected.get(k) for k in ('pid','start_ticks','uid','cwd','argv_sha256')))


class LinuxProcess:
    def __init__(self,root=Path('/proc')):self.root=Path(root)
    def identity(self,pid):
        folder=self.root/str(pid)
        try:
            fields=(folder/'stat').read_text().rsplit(')',1)[1].split()
            status=(folder/'status').read_text()
            uids=next(line.split()[1:] for line in status.splitlines() if line.startswith('Uid:'))
            if len(uids)!=4:raise ValueError('Invalid process owner metadata')
            raw=(folder/'cmdline').read_bytes()
            return {'pid':pid,'start_ticks':fields[19],'state':fields[0],'uid':int(uids[0]) if len(set(uids))==1 else None,
                    'cwd':str((folder/'cwd').resolve(strict=True)),
                    'argv_sha256':hashlib.sha256(raw).hexdigest()}
        except (FileNotFoundError,ProcessLookupError):return None

    def terminate_owned(self,expected):
        # A pidfd pins the process across the final identity check and signal.
        fd=os.pidfd_open(expected['pid'],0)
        try:
            if not same_identity(self.identity(expected['pid']),expected):raise ValueError('Guard birth changed')
            signal.pidfd_send_signal(fd,signal.SIGTERM,None,0)
        finally:os.close(fd)

    def quiescent(self,expected):
        try:fields=(self.root/str(expected['pid'])/'stat').read_text().rsplit(')',1)[1].split()
        except (FileNotFoundError,ProcessLookupError):return True
        return fields[0]=='Z' or fields[19]!=expected['start_ticks']

    def guards(self,base):
        result=[]
        for folder in self.root.iterdir():
            if not folder.name.isdecimal():continue
            try:
                # Unknown guard variants (-u, another cwd/UID) are blockers,
                # never kill targets. Match only the exact script argument;
                # do not inspect environments or emit arbitrary command lines.
                with (folder/'cmdline').open('rb') as stream:args=stream.read(65537).rstrip(b'\0').split(b'\0')
                if str(Path(base)/'control/remote_guard.py').encode() not in args:continue
                value=self.identity(int(folder.name))
                if value and value['state']!='Z':result.append(value)
            except (OSError,ValueError,IndexError,StopIteration):continue
        return result


def valid_restart(proof,binding,now):
    if proof is None:return False
    if (proof.get('project')!=PROJECT or proof.get('instance_id')!=INSTANCE or proof.get('scope_sha256')!=SCOPE_SHA
            or binding['instance_id']!=INSTANCE or binding['rental_scope_sha256']!=SCOPE_SHA):
        raise ValueError('Restart proof scope differs')
    closed,opened=proof['closed_interval'],proof['open_interval'];start=proof['start']
    sequence=[closed['start_epoch'],closed['running_seen_epoch'],closed['stop_epoch'],opened['start_epoch'],
              start['requested_epoch'],opened['running_seen_epoch'],start['confirmed_epoch'],now]
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in sequence) or sequence!=sorted(sequence):
        raise ValueError('Confirmed closed STOP then observed START lineage required')
    for row in (proof['stopped_state'],*(start[k] for k in ('intent','outcome','reconciled'))):
        if not re.fullmatch('[a-f0-9]{64}',row.get('sha256','')):raise ValueError('Restart immutable evidence hash required')
    return True


def retired_stop_records(control,restart,old_state):
    control=Path(control);names=('guard-stop-intent.json','guard-stop-outcome.json')
    present=[(control/name).exists() or (control/name).is_symlink() for name in names]
    if not any(present):return {}
    if not all(present) or restart is None:raise ValueError('Incomplete old guard stop requires review')
    required={'project','instance_id','rental_scope_sha256','operation','method','requested_epoch','reason'}
    values={}
    for name in names:
        path=control/name
        if path.is_symlink() or path.stat().st_size>8192:raise ValueError('Bounded regular stop metadata required')
        value=json.loads(path.read_text());allowed=required if name==names[0] else required|{'phase','http_status','success','error_class'}
        if (not required.issubset(value) or not set(value).issubset(allowed)
                or value['project']!=PROJECT or value['instance_id']!=INSTANCE or value['rental_scope_sha256']!=SCOPE_SHA
                or value['operation']!='stop' or value['method']!='PUT' or value['reason'] not in ('idle','phase_deadline')
                or type(value['requested_epoch']) not in (int,float) or not math.isfinite(value['requested_epoch'])):
            raise ValueError('Only scoped idle/phase stop records may be retired')
        if name==names[1]:
            if value.get('phase') not in ('response','unknown_outcome'):raise ValueError('Old stop outcome classification differs')
            if 'http_status' in value and (type(value['http_status']) is not int or not 100<=value['http_status']<=599):raise ValueError('Safe status required')
            if 'success' in value and type(value['success']) is not bool:raise ValueError('Safe success flag required')
            if 'error_class' in value and not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,79}',value['error_class']):raise ValueError('Safe error class required')
        values[name]=value
    first,second=(values[name] for name in names)
    if any(first[k]!=second[k] for k in required):raise ValueError('Old stop intent/outcome differ')
    closed=restart['closed_interval'];requested=first['requested_epoch']
    if not closed['running_seen_epoch']<=requested<=closed['stop_epoch']<restart['open_interval']['start_epoch']:
        raise ValueError('Old stop is not within the confirmed closed interval')
    if first['reason']=='idle' and not (requested>=closed['start_epoch']+120
            and requested<min(old_state['budget_deadline_epoch'],old_state['deadline_epoch'],CUTOFF)):
        raise ValueError('Old idle record violates its expired owner timeline')
    if first['reason']=='phase_deadline' and (requested<min(old_state['deadline_epoch'],closed['start_epoch']+7200) or requested>=CUTOFF):
        raise ValueError('Old phase record violates the fixed deadline')
    return {name:{'sha256':digest(control/name),'reason':first['reason'],'requested_epoch':requested,'record':values[name]} for name in names}


def restart_proof(ops,state,binding,stopped_state_proof,now):
    ops=Path(ops).resolve()
    if stopped_state_proof is None:raise ValueError('Immutable stopped-state snapshot required')
    path=Path(stopped_state_proof).resolve()
    if path!=ops/'partial-analysis-stopped-state.json' or digest(path)!=STOPPED_STATE_SHA:raise ValueError('Pinned stopped snapshot differs')
    stopped=json.loads(path.read_text());closed=stopped.get('running_intervals',[]);intervals=state.get('running_intervals',[])
    if (stopped.get('project')!=PROJECT or stopped.get('instance_id')!=INSTANCE or stopped.get('scope_sha256')!=SCOPE_SHA
            or stopped.get('pending_intent') or stopped.get('destroyed_epoch') or not hard_vast.Rental.stopped(stopped.get('last_status',{}))
            or not closed or any('stop_epoch' not in row for row in closed) or len(intervals)!=len(closed)+1
            or intervals[:-1]!=closed or 'stop_epoch' in intervals[-1] or 'running_seen_epoch' not in intervals[-1]):
        raise ValueError('Confirmed stopped prefix and exactly one new running interval required')
    opened=intervals[-1];found=[];payload_sha=hashlib.sha256(json.dumps({'state':'running'},sort_keys=True).encode()).hexdigest()
    for intent in ops.glob('intent-*-start.json'):
        value=json.loads(intent.read_text());requested=value.get('requested_epoch')
        if (value.get('instance_id')!=INSTANCE or value.get('rental_scope_sha256')!=SCOPE_SHA
                or type(requested) not in (int,float) or not opened['start_epoch']<=requested<=opened['running_seen_epoch']):continue
        outcome=intent.with_name(intent.stem+'-outcome.json');reconciled=intent.with_name(intent.stem+'-reconciled.json')
        response=json.loads(outcome.read_text());observed=json.loads(reconciled.read_text());status=observed['status']
        for row in (value,response):
            if (row.get('project')!=PROJECT or row.get('instance_id')!=INSTANCE or row.get('rental_scope_sha256')!=SCOPE_SHA
                    or row.get('operation')!='start' or row.get('method')!='PUT' or row.get('path')!=f'/api/v0/instances/{INSTANCE}/'
                    or row.get('requested_epoch')!=requested or row.get('payload_sha256')!=payload_sha):raise ValueError('START request identity differs')
        if (response.get('phase')!='response' or response.get('success') is not True or observed.get('operation')!='start'
                or status.get('id')!=INSTANCE or status.get('label')!=PROJECT or status.get('actual_status')!='running'
                or status.get('cur_state')!='running'):raise ValueError('START ACK and observed running reconciliation required')
        found.append({'requested_epoch':requested,'confirmed_epoch':observed['confirmed_epoch'],
            'intent':descriptor(intent),'outcome':descriptor(outcome),'reconciled':descriptor(reconciled)})
    if len(found)!=1:raise ValueError('Exactly one new scoped START required')
    proof={'project':PROJECT,'instance_id':INSTANCE,'scope_sha256':SCOPE_SHA,'stopped_state':descriptor(path),
        'closed_interval':{key:closed[-1][key] for key in ('start_epoch','running_seen_epoch','stop_epoch')},
        'open_interval':{key:opened[key] for key in ('start_epoch','running_seen_epoch')},'start':found[0]}
    valid_restart(proof,binding,now);return proof


def remote_perform(payload,expected_binding,*,base=BASE,proc=None,spawn=subprocess.Popen,clock=time.time,
                   monotonic=time.monotonic,sleep=time.sleep,environ=None):
    instance=expected_binding['instance_id'];scope_sha=expected_binding['rental_scope_sha256']
    base=Path(base);control=base/'control';proc=proc or LinuxProcess()
    environ=os.environ if environ is None else environ
    if instance!=INSTANCE or scope_sha!=SCOPE_SHA or environ.get('CONTAINER_ID')!=str(instance):raise ValueError('Calibrated container binding differs')
    nonce=payload.get('nonce','')
    if not re.fullmatch('[a-f0-9]{32}',nonce):raise ValueError('Fresh operation nonce required')
    if payload.get('instance_id')!=instance or payload.get('scope_sha256')!=scope_sha:raise ValueError('Scope differs')
    scope=control/'rental-scope.json'
    if digest(scope)!=scope_sha:raise ValueError('Remote immutable scope differs')
    value=json.loads(scope.read_text())
    if (value.get('project')!=PROJECT or value.get('label')!=PROJECT or value.get('instance_id')!=instance
            or value.get('image')!=expected_binding['image'] or value.get('offer_id')!=expected_binding['expected_offer_id']
            or value.get('machine_id')!=expected_binding['expected_machine_id']):raise ValueError('Scope identity differs')
    script=control/'remote_guard.py';state_path=control/'guard-state.json'
    staged=control/('remote-guard-staged-'+nonce+'.py');attempt=control/('guard-rearm-'+nonce)
    if digest(staged)!=payload['new_source_sha256'] or staged.stat().st_size>262144:raise ValueError('Staged source differs')
    raw=payload['state_json'].encode()
    if len(raw)>8192 or hashlib.sha256(raw).hexdigest()!=payload['new_state_sha256']:raise ValueError('Candidate state differs')
    state=json.loads(raw)
    if (set(state)!={'project','instance_id','rental_scope_sha256','deadline_epoch','budget_deadline_epoch'}
            or state['project']!=PROJECT or state['instance_id']!=instance or state['rental_scope_sha256']!=scope_sha
            or any(type(state[k]) not in (int,float) or not math.isfinite(state[k]) for k in ('deadline_epoch','budget_deadline_epoch'))
            or not clock()+120<state['budget_deadline_epoch']<=state['deadline_epoch']<=min(clock()+7200,CUTOFF)):
        raise ValueError('Bounded live replacement lease required')
    expected=payload['old_guard']
    if (set(expected)!={'pid','start_ticks','uid','cwd','argv_sha256'} or type(expected['pid']) is not int or expected['pid']<=1
            or not re.fullmatch('[0-9]+',expected['start_ticks']) or expected['uid']!=0
            or expected['cwd']!=str(base) or expected['argv_sha256']!=argv_hash(base)):
        raise ValueError('Owned guard identity required')
    result={'project':PROJECT,'instance_id':instance,'scope_sha256':scope_sha,'nonce':nonce,
            'completed':False,'old_guard_retired':False,'guard_state_installed':False,
            'new_guard_started':False,'new_source_sha256':payload['new_source_sha256'],
            'new_state_sha256':payload['new_state_sha256'],'failure':None,'after_restart':payload.get('after_restart')}
    # A nonblocking transaction lock prevents overlapping retire/install steps.
    with (control/'guard-rearm.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        def no_stop():
            if any((control/name).exists() or (control/name).is_symlink() for name in ('guard-stop-intent.json','guard-stop-outcome.json')):
                raise ValueError('Existing guard stop requires reconciliation')
        restart=valid_restart(payload.get('after_restart'),expected_binding,clock())
        if not restart:no_stop()
        if digest(state_path)!=payload['expected_old_state_sha256']:raise ValueError('Old guard state changed')
        old_script_sha=digest(script)
        if old_script_sha!=payload['expected_old_source_sha256']:
            raise ValueError('Old installed source changed')
        live=same_identity(proc.identity(expected['pid']),expected)
        if restart:
            if live or not proc.quiescent(expected):raise ValueError('Restart requires the proved old birth to be quiescent')
        elif not live:raise ValueError('Old owned guard is not live')
        markers=retired_stop_records(control,payload.get('after_restart'),json.loads(state_path.read_text())) if restart else {}
        if any(not same_identity(item,expected) for item in proc.guards(base)):
            raise ValueError('Unknown guard must be reconciled without killing it')
        result['eligible_stop_records']=markers
        attempt.mkdir(mode=0o700,exist_ok=False)
        write_new(attempt/'intent.json',{**result,'old_guard':expected,'deadline_epoch':state['deadline_epoch'],
                                      'budget_deadline_epoch':state['budget_deadline_epoch'],'old_source_sha256':old_script_sha})
        try:
            if live:
                no_stop();proc.terminate_owned(expected)
                until=monotonic()+5
                while not proc.quiescent(expected) and monotonic()<until:sleep(.05)
            if not proc.quiescent(expected):raise TimeoutError('Old guard still live')
            result.update(old_guard_retired=True,old_guard_already_quiescent=not live)
            if proc.guards(base):raise ValueError('A guard is still live before replacement')
            # Hash-copy then atomically archive only the validated old scoped
            # idle/phase stop records. Never unlink, overwrite, or erase them.
            result['retired_stop_records']={}
            for name,proof in markers.items():
                source=control/name;destination=attempt/('retired-'+name)
                if digest(source)!=proof['sha256']:raise ValueError('Old stop record changed')
                with (attempt/('copy-'+name)).open('xb') as stream:stream.write(source.read_bytes())
                os.replace(source,destination)
                if digest(destination)!=proof['sha256']:raise ValueError('Retired stop record changed')
                result['retired_stop_records'][name]={**proof,'archived_path':str(destination)}
            no_stop()
            # Back up exact nonsecret old source/state before either replacement.
            for source,name in ((script,'old-guard.py'),(state_path,'old-state.json')):
                with (attempt/name).open('xb') as stream:stream.write(source.read_bytes())
            if digest(staged)!=payload['new_source_sha256']:raise ValueError('Staged source changed')
            os.replace(staged,script)
            next_state=attempt/'new-state.json'
            with next_state.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            os.replace(next_state,state_path);result['guard_state_installed']=True
            if digest(script)!=payload['new_source_sha256'] or digest(state_path)!=payload['new_state_sha256']:raise ValueError('Installed bytes differ')
            no_stop()
            with (attempt/'guard.log').open('xb') as log:
                child=spawn([PYTHON,str(script)],cwd=base,stdin=subprocess.DEVNULL,stdout=log,
                            stderr=subprocess.STDOUT,start_new_session=True)
            result.update(new_guard_started=True,new_guard_pid=child.pid)
            sleep(.3)
            actual=proc.identity(child.pid)
            if (child.poll() is not None or actual is None or actual.get('state')=='Z' or actual.get('uid')!=0
                    or actual.get('cwd')!=str(base) or actual.get('argv_sha256')!=argv_hash(base)
                    or child.pid==expected['pid']):raise ValueError('New guard identity/startup differs')
            no_stop()
            result.update(completed=True,new_guard={k:actual[k] for k in ('pid','start_ticks','uid','cwd','argv_sha256')},
                          remote_log=str(attempt/'guard.log'),remote_attempt=str(attempt),old_guard=expected)
        except BaseException as error:result['failure']={'class':type(error).__name__}
        write_new(attempt/'receipt.json',result)
    return result


def remote_code(binding):
    # The expected identity is sealed into the fixed command, separate from its
    # data envelope. No remote caller-provided target or arbitrary code hook.
    header=('import fcntl,hashlib,json,math,os,re,signal,subprocess,sys,time\nfrom pathlib import Path\n'
            f'BASE=Path({str(BASE)!r});PYTHON={PYTHON!r};PROJECT={PROJECT!r};CUTOFF={CUTOFF!r};INSTANCE={INSTANCE!r};SCOPE_SHA={SCOPE_SHA!r}\n'
            f'EXPECTED_BINDING={binding!r}\n')
    source='\n\n'.join(inspect.getsource(value) for value in (digest,write_new,argv_hash,same_identity,LinuxProcess,valid_restart,retired_stop_records,remote_perform))
    tail="\ntry:\n result=remote_perform(json.loads(sys.argv[1]),EXPECTED_BINDING)\nexcept BaseException as error:\n result={'completed':False,'failure':{'class':type(error).__name__}}\nprint(json.dumps(result),flush=True)\nsys.exit(0 if result['completed'] else 1)\n"
    return header+source+tail


def bootstrap_prior(ops,binding,process_path,state_path,source_path):
    ops=Path(ops).resolve();paths=[Path(p).resolve() for p in (process_path,state_path,source_path)]
    process_path,state_path,source_path=paths;folder=process_path.parent
    match=re.fullmatch('bootstrap-calibration-controller-attempt([89])',folder.name)
    if (folder.parent!=ops or match is None or any(p.parent!=folder for p in paths) or process_path.name!='remote-guard-process.json'
            or state_path.name!='guard-state.json' or source_path.name!='remote-guard-source.py'):
        raise ValueError('Same immutable repaired attempt8/9 guard snapshots required')
    evidence={name:descriptor(path) for name,path in zip(('process','state','source'),paths)}
    if evidence['source']['sha256']!=INITIAL_GUARD_SHA:raise ValueError('Tested bootstrap guard source differs')
    process=json.loads(process_path.read_text());state=json.loads(state_path.read_text())
    if (set(process)!={'pid','start_ticks'} or type(process['pid']) is not int or process['pid']<=1
            or type(process['start_ticks']) is not str or not re.fullmatch('[0-9]+',process['start_ticks'])):
        raise ValueError('Bootstrap process birth required')
    if (set(state)!={'project','instance_id','rental_scope_sha256','deadline_epoch','budget_deadline_epoch'}
            or state['project']!=PROJECT or state['instance_id']!=binding['instance_id']
            or state['rental_scope_sha256']!=binding['rental_scope_sha256']
            or any(type(state[k]) not in (int,float) or not math.isfinite(state[k]) for k in ('deadline_epoch','budget_deadline_epoch'))
            or not binding['created_epoch']<state['budget_deadline_epoch']<=state['deadline_epoch']<=CUTOFF):
        raise ValueError('Bootstrap lease scope differs')
    outcome_path=folder/'outcome.json';outcome=json.loads(outcome_path.read_text())
    if (outcome.get('project')!=PROJECT or outcome.get('instance_id')!=binding['instance_id']
            or outcome.get('attempt')!=int(match.group(1)) or outcome.get('status')!='completed'
            or outcome.get('stage')!='pre-generation-calibration-complete'
            or outcome.get('guard_source')!=evidence['source']):
        raise ValueError('Completed same-host bootstrap source proof required')
    return {'kind':'bootstrap','evidence':evidence,'outcome':descriptor(outcome_path),
            'old_guard':{**process,'uid':0,'cwd':str(BASE),'argv_sha256':argv_hash(BASE)},
            'old_state_sha256':evidence['state']['sha256'],'old_source_sha256':evidence['source']['sha256']}


def accepted_prior_helper(ops,path,value):
    return value.get('helper_sha256')==digest(__file__)


def prior(ops,binding,binding_descriptor,receipt=None,bootstrap=None,seen=None):
    ops=Path(ops).resolve()
    if receipt is None:
        if bootstrap is None or len(bootstrap)!=3:raise ValueError('Three immutable bootstrap snapshots required')
        return bootstrap_prior(ops,binding,*bootstrap)
    if bootstrap is not None:raise ValueError('Use bootstrap snapshots or own prior receipt')
    path=Path(receipt).resolve()
    if path.name!='receipt.json' or path.parent.parent!=ops:raise ValueError('Own direct OPS receipt required')
    if path==ops/'rearm-frozen-attempt2/receipt.json':
        original=ops/'rearm_frozen_remote_guard.py'
        if digest(original)!=ANCESTOR_HELPER_SHA or digest(path)!=ANCESTOR_RECEIPT_SHA:
            raise ValueError('Pinned original frozen rearm source/receipt changed')
        import rearm_frozen_remote_guard as previous
        if Path(previous.__file__).resolve()!=original or digest(previous.__file__)!=ANCESTOR_HELPER_SHA:
            raise ValueError('Original frozen verifier source differs')
        return previous.prior(ops,binding,binding_descriptor,path)
    seen=set() if seen is None else seen
    if path in seen or len(seen)>32:raise ValueError('Prior receipt lineage cycles')
    seen.add(path);value=json.loads(path.read_text())
    if (value.get('project')!=PROJECT or value.get('instance_id')!=binding['instance_id']
            or value.get('scope_sha256')!=binding['rental_scope_sha256']
            or value.get('rental_binding')!=binding_descriptor or value.get('completed') is not True
            or not accepted_prior_helper(ops,path,value)):
        raise ValueError('Successful pinned-ancestor or same-helper/same-rental prior receipt required')
    previous=value['prior']
    if previous['kind']=='bootstrap':
        evidence=previous['evidence']
        for row in (*evidence.values(),previous['outcome']):
            if descriptor(row['path'])!=row:raise ValueError('Bootstrap evidence bytes changed')
        anchor=bootstrap_prior(ops,binding,*(evidence[k]['path'] for k in ('process','state','source')))
    elif previous['kind']=='rearm':
        proof=previous['proof']
        if descriptor(proof['path'])!=proof:raise ValueError('Prior receipt bytes changed')
        anchor=prior(ops,binding,binding_descriptor,proof['path'],seen=seen)
    else:raise ValueError('Unknown guard lineage')
    if previous!=anchor:raise ValueError('Guard lineage changed')
    remote=value['remote'];identity=remote['new_guard']
    if (remote.get('completed') is not True or remote.get('instance_id')!=binding['instance_id']
            or remote.get('scope_sha256')!=binding['rental_scope_sha256']
            or type(identity.get('pid')) is not int or identity['pid']<=1
            or type(identity.get('start_ticks')) is not str or not re.fullmatch('[0-9]+',identity['start_ticks'])
            or identity.get('uid')!=0 or identity.get('cwd')!=str(BASE) or identity.get('argv_sha256')!=argv_hash(BASE)
            or any(not re.fullmatch('[a-f0-9]{64}',remote.get(k,'')) for k in ('new_source_sha256','new_state_sha256'))):
        raise ValueError('Remote successful owned birth proof absent')
    return {'kind':'rearm','proof':descriptor(path),'old_guard':identity,
            'old_state_sha256':remote['new_state_sha256'],'old_source_sha256':remote['new_source_sha256']}


def execute(out,*,rental_proof,bootstrap=None,prior_receipt=None,after_restart=False,stopped_state_proof=None,service=None,run=subprocess.run,clock=time.time,token=uuid.uuid4):
    service=service or hard_vast.Rental();ops=service.root.resolve();out=Path(out)
    if not out.is_absolute():out=service.repo/out
    if out.parent.resolve()!=ops or not re.fullmatch('[a-z0-9][a-z0-9-]{0,95}',out.name):raise ValueError('Fresh direct Hard OPS output required')
    state=service.load();active=service.active();now=clock();budget=service.forecast(state)
    binding,binding_descriptor,_=rental_binding(rental_proof,ops,state)
    instance=binding['instance_id'];scope_sha=binding['rental_scope_sha256']
    if instance!=INSTANCE or scope_sha!=SCOPE_SHA:raise ValueError('Only calibrated host5 is allowed')
    if prior_receipt is None or bootstrap is not None:raise ValueError('Frozen host rearm requires successful prior receipt lineage')
    if Path(prior_receipt).resolve()==ops/'rearm-frozen-attempt2/receipt.json' and not after_restart:
        raise ValueError('Initial frozen rearm requires the pinned fresh stopped snapshot and observed restart')
    if not after_restart and stopped_state_proof is not None:raise ValueError('Stopped proof applies only to an explicit restart')
    restart=restart_proof(ops,state,binding,stopped_state_proof,now) if after_restart else None
    if (state.get('destroyed_epoch') or state.get('pending_intent')
            or state.get('last_status',{}).get('actual_status')!='running'
            or active.get('pid') not in (os.getpid(),os.getppid())):raise ValueError('Fresh scoped running owner required')
    rate=state['dph_total'];remaining=40-budget['total_usd_upper']-budget['shutdown_margin_usd']
    if type(rate) not in (int,float) or not math.isfinite(rate) or rate<=0:raise ValueError('Finite positive rental rate required')
    if type(active.get('deadline_epoch')) not in (int,float) or not math.isfinite(active['deadline_epoch']):raise ValueError('Finite owner deadline required')
    deadline=min(active['deadline_epoch'],now+7200,CUTOFF)
    budget_deadline=min(deadline,now+remaining/rate*3600)
    if not now+180<budget_deadline<=deadline:raise ValueError('Insufficient safe rearm lease')
    old=prior(ops,binding,binding_descriptor,prior_receipt,bootstrap);nonce=token().hex
    out.mkdir(exist_ok=False)
    source=ops/'remote_guard_partial.py'
    if source.is_symlink() or not source.is_file() or source.stat().st_size>262144:raise ValueError('Bounded regular guard source required')
    source_raw=source.read_bytes();new_source_sha=hashlib.sha256(source_raw).hexdigest()
    if new_source_sha!=INITIAL_GUARD_SHA:raise ValueError('Frozen tested replacement guard source differs')
    (out/'guard-source.py').write_bytes(source_raw)
    lease={'project':PROJECT,'instance_id':instance,'rental_scope_sha256':scope_sha,
           'deadline_epoch':deadline,'budget_deadline_epoch':budget_deadline}
    write_new(out/'guard-state.json',lease)
    payload={'nonce':nonce,'instance_id':instance,'scope_sha256':scope_sha,'old_guard':old['old_guard'],
             'expected_old_state_sha256':old['old_state_sha256'],'expected_old_source_sha256':old['old_source_sha256'],
             'new_source_sha256':new_source_sha,'state_json':(out/'guard-state.json').read_text(),
             'new_state_sha256':digest(out/'guard-state.json'),'after_restart':restart}
    code=remote_code(binding);code_sha=hashlib.sha256(code.encode()).hexdigest()
    write_new(out/'plan.json',{'project':PROJECT,'instance_id':instance,'scope_sha256':scope_sha,'rental_binding':binding_descriptor,
        'prior':old,'helper_sha256':digest(__file__),'remote_code_sha256':code_sha,'payload':payload,
        'budget':budget,'phase_deadline_epoch':active['deadline_epoch']})
    result={'project':PROJECT,'instance_id':instance,'scope_sha256':scope_sha,'rental_binding':binding_descriptor,
            'helper_sha256':digest(__file__),'remote_code_sha256':code_sha,'prior':old,
            'completed':False,'failure':None,'remote_command_dispatched':False}
    remote=[sys.executable,str(ops/'remote.py')]
    try:
        def command(label,argv,timeout,check=True):
            with (out/(label+'.stdout')).open('xb') as stdout,(out/(label+'.stderr')).open('xb') as stderr:
                finished=run(argv,stdout=stdout,stderr=stderr,cwd=service.repo,timeout=timeout)
            if check and finished.returncode:raise subprocess.CalledProcessError(finished.returncode,argv)
            return finished.returncode
        staged=str(BASE/'control'/('remote-guard-staged-'+nonce+'.py'))
        command('stage-source',[*remote,'put',str(out/'guard-source.py'),staged],60)
        if digest(source)!=new_source_sha or descriptor(rental_proof)!=binding_descriptor:raise ValueError('Local bound source/proof changed during staging')
        if prior(ops,binding,binding_descriptor,prior_receipt,bootstrap)!=old:raise ValueError('Prior guard evidence changed during staging')
        if after_restart and restart_proof(ops,state,binding,stopped_state_proof,clock())!=restart:raise ValueError('Confirmed restart evidence changed during staging')
        result['remote_command_dispatched']=True
        command_argv=[*remote,'run',PYTHON,'-c',code,json.dumps(payload)]
        rc=command('retire-install',command_argv,45,check=False);result['remote_returncode']=rc
        text=(out/'retire-install.stdout').read_text()
        try:remote_result=json.loads(text[text.index('{'):])
        except (ValueError,json.JSONDecodeError):
            if rc:raise subprocess.CalledProcessError(rc,command_argv) from None
            raise
        result['remote']=remote_result
        if rc:raise subprocess.CalledProcessError(rc,command_argv)
        if (remote_result.get('completed') is not True or remote_result.get('instance_id')!=instance
                or remote_result.get('scope_sha256')!=scope_sha or remote_result.get('nonce')!=nonce
                or remote_result.get('new_source_sha256')!=new_source_sha
                or remote_result.get('new_state_sha256')!=payload['new_state_sha256']):raise ValueError('Remote proof differs')
        result['completed']=True
    except BaseException as error:result['failure']={'class':type(error).__name__,'returncode':getattr(error,'returncode',None)}
    write_new(out/'receipt.json',result);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('out','rental-proof'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--prior-receipt');parser.add_argument('--after-restart',action='store_true');parser.add_argument('--stopped-state-proof')
    for name in ('process','state','source'):parser.add_argument('--bootstrap-'+name+'-proof')
    args=parser.parse_args();parts=(args.bootstrap_process_proof,args.bootstrap_state_proof,args.bootstrap_source_proof)
    if any(parts) and not all(parts):raise ValueError('All three bootstrap snapshots required together')
    value=execute(args.out,rental_proof=args.rental_proof,prior_receipt=args.prior_receipt,bootstrap=parts if all(parts) else None,after_restart=args.after_restart,stopped_state_proof=args.stopped_state_proof)
    print(json.dumps(value));return int(not value['completed'])


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:raise SystemExit('Calibrated host5 guard rearm failed: '+type(error).__name__) from None
