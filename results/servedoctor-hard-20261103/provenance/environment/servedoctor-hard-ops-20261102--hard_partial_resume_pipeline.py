#!/usr/bin/env python3
"""Authorized15-case scopedSTART and append-only Hard queue; original failures stay intact.

No scientific inputs are interpreted here. Commands use argv, never a shell.
Each invocation keeps its initial owner deadline; only the next command renews it.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

import hard_vast as h
import prepare_next_hard_study as prep
from hard_phase import queued_start

ANALYSIS_LABEL='ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)'
POLL=5
HEARTBEAT=20
IDLE=120
START_WAIT=120
CLEANUP=180


def finite(value):return type(value) in (int,float) and math.isfinite(value)
def bound(state,binding,allow_deleted=False):
    if (state.get('project')!=h.LABEL or state.get('instance_id')!=binding['instance_id']
            or state.get('scope_sha256')!=binding['rental_scope_sha256']
            or (state.get('offer_id'),state.get('machine_id'))!=(binding['expected_offer_id'],binding['expected_machine_id'])
            or (state.get('destroyed_epoch') and not allow_deleted)):
        raise ValueError('Resume rental differs from immutable creation binding')


def stopped(state):
    row=state.get('last_status',{})
    return (h.Rental.stopped(row) and row.get('intended_status')!='running' and not state.get('pending_intent')
            and all('stop_epoch' in item for item in state.get('running_intervals',[])))
def queue_at(path,previous=None,allow_repair=False):
    path=Path(path)
    if path.is_symlink():raise ValueError('Regular queue required')
    value=json.loads(path.read_text())
    if (value.get('project')!=h.LABEL or value.get('expected_offer_id')!=h.OFFER
            or value.get('expected_machine_id')!=h.MACHINE or 'instance_id' in value or 'rental_scope_sha256' in value
            or type(value.get('final')) is not bool
            or not isinstance(value.get('commands'),list)):
        raise ValueError('Queue scope/schema differs')
    proof=value.get('rental_proof',{})
    if set(proof)!={'path','sha256'} or not Path(proof['path']).is_absolute() or not re.fullmatch('[a-f0-9]{64}',proof.get('sha256','')):raise ValueError('Sealed creation proof required')
    acks=value.get('failure_acknowledgements',[])
    if not isinstance(acks,list):raise ValueError('Repair acknowledgements must be append-only')
    names=set();outputs={'outcome.json','watchdog.stdout','watchdog.stderr'}
    for row in value['commands']:
        name=row.get('name','');argv=row.get('argv')
        if (not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}',name) or name in names
                or not isinstance(argv,list) or not argv or any(type(s) is not str or not s or '\x00' in s for s in argv)):
            raise ValueError('Unique named argv commands required')
        names.add(name)
        for key,suffix in [('stdout','.stdout'),('stderr','.stderr'),('outcome','.json')]:
            filename=row.get(key,name+suffix)
            if (type(filename) is not str or Path(filename).name!=filename or filename in ('.','..')
                    or not filename.endswith(suffix) or filename in outputs
                    or filename.startswith(('control-','queue-snapshot-'))):
                raise ValueError('Direct output filenames required')
            outputs.add(filename)
        timeout=row.get('timeout_s',6900)
        if not finite(timeout) or not 0<timeout<=6900:raise ValueError('Command timeout must fit the fixed two-hour owner window')
        owner_window=row.get('owner_window_s',7200)
        if (not finite(owner_window) or not 420<owner_window<=7200
                or ('owner_window_s' in row and owner_window>timeout+180)):
            raise ValueError('Explicit owner window must reserve cleanup within the command timeout')
        if 'remaining_hours' in row and (not finite(row['remaining_hours']) or not 0<=row['remaining_hours']<=h.REMAINING_HOURS
                or not isinstance(row.get('remaining_reason'),str) or not row['remaining_reason'].strip()):
            raise ValueError('Documented remaining-work estimate required')
    if previous and (any(value.get(k)!=previous.get(k) for k in ('project','expected_offer_id','expected_machine_id','rental_proof'))
            or acks[:len(previous.get('failure_acknowledgements',[]))]!=previous.get('failure_acknowledgements',[])
            or len(acks)<len(previous.get('failure_acknowledgements',[]))
            or value['commands'][:len(previous['commands'])]!=previous['commands']
            or len(value['commands'])<len(previous['commands']) or (previous['final'] and value!=previous and not allow_repair)):
        raise ValueError('Existing queue commands/final declaration are immutable')
    return value


def repair_acknowledgement(queue,failed_index,outcome,minimum_new_index):
    matches=[row for row in queue.get('failure_acknowledgements',[]) if row.get('failed_index')==failed_index]
    if not matches:return None
    if len(matches)!=1:raise ValueError('Exactly one acknowledgement per failed command required')
    ack=matches[0];target=ack.get('repair_job_index');reason=ack.get('reason')
    expected={'path':str(Path(outcome).resolve()),'sha256':h.sha(outcome)}
    if (ack.get('failed_outcome')!=expected or type(target) is not int or not minimum_new_index<=target<len(queue['commands'])
            or not isinstance(reason,str) or not reason.strip() or queue['commands'][target].get('repair_reason')!=reason):
        raise ValueError('Repair requires a new reasoned command bound to the immutable failed outcome')
    if any(queue['commands'][target]['argv']==row['argv'] for row in queue['commands'][:minimum_new_index]):
        raise ValueError('An existing command argv cannot be replayed as a repair')
    return ack


def execute(args,root=h.ROOT,service=None,run=subprocess.run,popen=subprocess.Popen,clock=time.time,sleep=time.sleep):
    root=Path(root).resolve();out=Path(args.out).resolve();queue_path=Path(args.queue).resolve()
    startup_plan=getattr(args,'startup_window_plan',None)
    startup_plan=Path(startup_plan).resolve() if startup_plan else None
    if startup_plan is None:raise ValueError('Fresh authorized15-case SSH window required')
    if (out.parent!=root or out.exists() or queue_path.parent!=root or queue_path.is_symlink()
            or not finite(args.max_hours) or not 0<args.max_hours<=5
            or (args.remaining_hours is not None and (not finite(args.remaining_hours) or not 0<=args.remaining_hours<=h.REMAINING_HOURS))):
        raise ValueError('Fresh direct OPS output and bounded queue required')
    service=service or h.Rental();state=service.load()
    binding,binding_descriptor,_=prep.rental_binding(args.rental_proof,root,state);bound(state,binding)
    if args.remaining_hours is None or args.max_hours>args.remaining_hours:raise ValueError('Total fixed allocation must fit the explicit reserved hours')
    if not stopped(state):raise ValueError('OneSTART requires confirmed stopped state and closed intervals')
    queue=queue_at(queue_path)
    if queue['rental_proof']!=binding_descriptor:raise ValueError('Queue and creation proof differ')
    out.mkdir()
    if startup_plan:
        first=queue['commands'][0]['argv'] if queue['commands'] else []
        if (startup_plan.name!='plan.json' or startup_plan.parent.parent!=root
                or not re.fullmatch(r'startup-ssh-window-attempt[1-9][0-9]*',startup_plan.parent.name)
                or len(first)!=5 or Path(first[1]).resolve()!=root/'partial_analysis_ssh_window.py'
                or first[2:4]!=['resume','--plan'] or Path(first[4]).resolve()!=startup_plan):
            raise ValueError('First command must consume the exact authorized15-case restart SSH window')
    result={'analysis_label':ANALYSIS_LABEL,'project':h.LABEL,'instance_id':binding['instance_id'],'rental_scope_sha256':binding['rental_scope_sha256'],'rental_proof':binding_descriptor,'returncode':1,'stop_confirmed':False,
            'started_epoch':clock(),'commands':[],'queue_source':str(queue_path),'no_intermediate_stop':True}
    deadline=min(h.DEADLINE,clock()+args.max_hours*3600);work_deadline=deadline-CLEANUP
    result['deadline_epoch']=deadline
    hard_guard_failure=False;child=guard=None;control_number=0;owner_until=min(work_deadline,clock()+7200);last_heartbeat=-float('inf')
    def beat(force=False,remaining=None):
        nonlocal last_heartbeat,hard_guard_failure
        if clock()>=work_deadline:
            hard_guard_failure=True;raise TimeoutError('Pipeline work deadline reached')
        try:
            # The user-approved maximum total rental allocation is fixed at
            # invocation. Count its remaining duration down, never extend it.
            # The actual parent owns every command; ledger/history/caps stay intact.
            if force or clock()-last_heartbeat>=HEARTBEAT:
                planned=max(0.,(deadline-clock())/3600)
                if planned>args.remaining_hours+1e-8:raise ValueError('Fixed envelope exceeds approved reservation')
                service.heartbeat(os.getpid(),owner_until)
                with service.lock():service.heartbeat(os.getpid(),owner_until,planned)
                last_heartbeat=clock()
            else:service.forecast(service.load())
        except Exception:
            hard_guard_failure=True;raise
    def control(operation,*values,check=True,timeout=60):
        nonlocal control_number
        control_number+=1;prefix=out/f'control-{control_number:04d}-{operation}'
        with prefix.with_suffix('.stdout').open('xb') as stdout,prefix.with_suffix('.stderr').open('xb') as stderr:
            return run([sys.executable,str(root/'hard_vast.py'),operation,*map(str,values)],stdin=subprocess.DEVNULL,
                stdout=stdout,stderr=stderr,check=check,timeout=timeout)
    def snapshot(value):
        path=out/f'queue-snapshot-{len(list(out.glob("queue-snapshot-*.json"))):04d}.json'
        h.write(path,value,exclusive=True);result['latest_queue']={'path':str(path),'sha256':h.sha(path)}
    def ready():
        row=service.load();bound(row,binding);status=row.get('last_status',{})
        return (status.get('actual_status')=='running' and status.get('cur_state')=='running'
                and status.get('ports') and not row.get('pending_intent'))
    def spawn_guard():
        nonlocal guard
        argv=[sys.executable,str(root/'hard_vast.py'),'watchdog']
        if startup_plan:argv+=['--startup-window-plan',str(startup_plan)]
        with (out/'watchdog.stdout').open('xb') as stdout,(out/'watchdog.stderr').open('xb') as stderr:
            guard=popen(argv,stdin=subprocess.DEVNULL,
                        stdout=stdout,stderr=stderr,start_new_session=True)
        result['watchdog_pid']=guard.pid
    try:
        snapshot(queue);beat(True,args.remaining_hours)
        requested=clock()
        try:started=control('start','--reason','resume pipeline '+out.name,check=False,timeout=90)
        finally:spawn_guard()
        result['start_request_returncode']=started.returncode
        if started.returncode:
            evidence=queued_start(root,service.load(),requested)
            if evidence is None:raise subprocess.CalledProcessError(started.returncode,started.args)
            result['queued_start']=evidence
        while True:
            beat()
            status=control('status',check=False,timeout=45)
            if status.returncode==0 and ready():break
            if clock()>=min(work_deadline,requested+START_WAIT):raise TimeoutError('One start request did not become ready within120s')
            sleep(POLL)
        if startup_plan:
            from partial_analysis_ssh_window import PartialAnalysisWindow
            path=PartialAnalysisWindow(service=service,clock=clock,sleep=sleep).prepare(startup_plan.parent,rental_proof=args.rental_proof,pipeline_out=out)
            result['startup_window_plan']={'path':str(path),'sha256':h.sha(path)}
        pending=list(range(len(queue['commands'])));seen=len(queue['commands']);executed=set();idle_since=clock()
        while True:
            if clock()>=work_deadline:raise TimeoutError('Pipeline work deadline reached')
            latest=queue_at(queue_path,queue)
            if latest!=queue:queue=latest;snapshot(queue)
            pending.extend(range(seen,len(queue['commands'])));seen=len(queue['commands'])
            if not pending:
                if queue['final']:result['returncode']=0;break
                if clock()-idle_since>=IDLE:raise TimeoutError('No queued concrete work for120s')
                owner_until=min(work_deadline,clock()+7200);beat();sleep(POLL);continue
            index=pending.pop(0)
            if index in executed:raise ValueError('A queue index can execute only once')
            row=queue['commands'][index];owner_until=min(work_deadline,clock()+row.get('owner_window_s',7200))
            entry={'index':index,'name':row['name'],'argv_sha256':hashlib.sha256(json.dumps(row['argv']).encode()).hexdigest(),
                   'started_epoch':clock(),'owner_deadline_epoch':owner_until,'returncode':None}
            if 'remaining_hours' in row:
                entry['remaining_work']={'before_hours':service.load().get('remaining_gpu_hours'),
                    'hours':row['remaining_hours'],'reason':row['remaining_reason']}
            beat(True,row.get('remaining_hours'))
            result['commands'].append(entry)
            stdout_path=out/row.get('stdout',row['name']+'.stdout');stderr_path=out/row.get('stderr',row['name']+'.stderr')
            outcome=out/row.get('outcome',row['name']+'.json')
            if any(p.exists() for p in (stdout_path,stderr_path,outcome)):raise ValueError('Command output already exists; no replay')
            failure=None
            try:
                with stdout_path.open('xb') as stdout,stderr_path.open('xb') as stderr:
                    child=popen(row['argv'],stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
                entry['pid']=child.pid;entry['birth']=service.birth(child.pid)
                if not entry['birth']:
                    if child.poll() is None:raise RuntimeError('Actual command PID identity unavailable')
                    entry['exited_before_identity_capture']=True
                command_deadline=min(work_deadline,owner_until-CLEANUP,clock()+row.get('timeout_s',6900))
                while child.poll() is None:
                    if clock()>=command_deadline:raise TimeoutError('Queued command deadline reached')
                    if guard.poll() is not None:raise RuntimeError('Independent budget watchdog exited during work')
                    beat();sleep(POLL)
                entry['returncode']=child.returncode
                if child.returncode:raise subprocess.CalledProcessError(child.returncode,row['argv'])
            except BaseException as exc:
                entry['error_class']=type(exc).__name__;failure=exc
            finally:
                entry['outcome_recorded_epoch']=clock()
                entry['finished_epoch']=clock() if child is None or child.poll() is not None else None
                h.write(outcome,entry,exclusive=True)
            executed.add(index)
            if failure is not None:
                if isinstance(failure,(KeyboardInterrupt,SystemExit)) or hard_guard_failure:raise failure
                current=service.load()
                if current.get('destroyed_epoch') or guard.poll() is not None:raise failure
                window=h.Rental.startup_window_at(root,startup_plan,current,clock)
                if window and not window['authenticated']:
                    # No acknowledged repair may bypass the fixed-guide-only
                    # authentication window. Its own recovery runs below.
                    raise failure
                if child is not None and child.poll() is None:
                    cleanup={'termination_requested_epoch':clock(),'pid':child.pid}
                    child.terminate();until=min(work_deadline,clock()+120)
                    while child.poll() is None and clock()<until:beat(True);sleep(POLL)
                    if child.poll() is None:cleanup['forced_kill']=True;child.kill();child.wait(timeout=5)
                    cleanup.update(returncode=child.returncode,finished_epoch=clock())
                    h.write(out/(row['name']+'-cleanup.json'),cleanup,exclusive=True)
                    if child.poll() is None:raise RuntimeError('Failed command is still running')
                child=None;owner_until=min(work_deadline,clock()+7200)
                attention_start=clock();attention_until=min(work_deadline,attention_start+120)
                minimum_new_index=len(queue['commands'])
                attention={'failed_index':index,'failed_outcome':{'path':str(outcome),'sha256':h.sha(outcome)},
                    'started_epoch':attention_start,'deadline_epoch':attention_until,'no_retry_of_failed_index':True}
                h.write(out/(row['name']+'-repair-attention.json'),attention,exclusive=True)
                accepted=None
                while clock()<attention_until:
                    beat(True)
                    current=service.load();bound(current,binding)
                    if current.get('pending_intent') or current.get('last_status',{}).get('actual_status')!='running':
                        raise RuntimeError('Repair cannot dispatch while rental state is unresolved or stopped')
                    latest=queue_at(queue_path,queue,allow_repair=True)
                    accepted=repair_acknowledgement(latest,index,outcome,minimum_new_index)
                    if accepted:
                        queue=latest;snapshot(queue)
                        pending.extend(range(seen,len(queue['commands'])));seen=len(queue['commands'])
                        target=accepted['repair_job_index']
                        if target in executed:raise ValueError('Repair target was already dispatched')
                        pending.remove(target);pending.insert(0,target)
                        h.write(out/(row['name']+'-repair-accepted.json'),{**attention,'acknowledgement':accepted,
                            'accepted_epoch':clock(),'queue':result['latest_queue']},exclusive=True)
                        break
                    sleep(POLL)
                if not accepted:raise TimeoutError('Failed command needs new acknowledged work within120s')
                result.setdefault('repaired_failures',[]).append(index)
            child=None;idle_since=clock()
    except BaseException as exc:
        if clock()>=work_deadline:hard_guard_failure=True
        result.update(returncode=1,error_class=type(exc).__name__)
    finally:
        if child is not None and child.poll() is None:
            result['child_termination_requested']=True;child.terminate()
            end=min(h.DEADLINE,clock()+120)
            while child.poll() is None and clock()<end:
                try:beat(True)
                except Exception:pass
                sleep(POLL)
            if child.poll() is None:
                result['child_forced_kill']=True;child.kill()
                try:child.wait(timeout=5)
                except Exception as exc:result['child_cleanup_error_class']=type(exc).__name__
        preserve_window=False
        if startup_plan and startup_plan.exists() and not hard_guard_failure and not service.load().get('destroyed_epoch'):
            window=h.Rental.startup_window_at(root,startup_plan,service.load(),clock)
            if window and not window['authenticated']:
                preserve_window=True;result['stop_skipped_for_unauthenticated_restart_window']=True
                try:
                    with (out/'restart-recovery.stdout').open('xb') as stdout,(out/'restart-recovery.stderr').open('xb') as stderr:
                        recovery=popen([sys.executable,str(root/'partial_analysis_ssh_window.py'),'resume','--plan',str(startup_plan)],
                                       stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
                    recovery_until=min(work_deadline,window['plan']['deadline_epoch']+180)
                    while recovery.poll() is None and clock()<recovery_until:beat(True);sleep(POLL)
                    if recovery.poll() is None:raise TimeoutError('Restart-window cleanup requires explicit reconciliation')
                    result['restart_recovery_returncode']=recovery.returncode
                    window=h.Rental.startup_window_at(root,startup_plan,service.load(),clock)
                    if window and window['authenticated']:preserve_window=False
                except BaseException as exc:result['restart_recovery_error_class']=type(exc).__name__
        state=service.load()
        if state.get('destroyed_epoch'):
            result.update(deletion_confirmed=True,cleanup_confirmed=all('stop_epoch' in x for x in state.get('running_intervals',[])),
                          destroyed_epoch=state['destroyed_epoch'],stop_confirmed=False,stop_skipped_for_confirmed_deletion=True)
        elif not preserve_window:
            try:
                stopped_result=control('stop','--reason','pipeline '+out.name+' final or failure',check=False,timeout=90)
                result['stop_request_returncode']=stopped_result.returncode
            except BaseException as exc:result['stop_error_class']=type(exc).__name__
        end=min(h.DEADLINE,clock()+120)
        while not result.get('cleanup_confirmed') and clock()<end:
            try:
                control('reconcile',check=False,timeout=45)
                state=service.load()
                if state.get('destroyed_epoch'):
                    if startup_plan:
                        from partial_analysis_ssh_window import PartialAnalysisWindow
                        path,plan=PartialAnalysisWindow(service=service,clock=clock,sleep=sleep).load_plan(startup_plan)
                        PartialAnalysisWindow(service=service,clock=clock,sleep=sleep).finalize_deleted(path.parent,plan,state)
                        state=service.load()
                    result.update(deletion_confirmed=True,cleanup_confirmed=all('stop_epoch' in x for x in state.get('running_intervals',[])),
                                  destroyed_epoch=state['destroyed_epoch'],stop_confirmed=False)
                    if result['cleanup_confirmed']:break
                else:
                    bound(state,binding)
                    if not preserve_window and stopped(state):result.update(stop_confirmed=True,cleanup_confirmed=True);break
            except BaseException as exc:result['reconcile_error_class']=type(exc).__name__
            sleep(POLL)
        if not result.get('cleanup_confirmed'):result['returncode']=1
        if guard is not None and result.get('cleanup_confirmed'):
            try:guard.wait(timeout=10)
            except subprocess.TimeoutExpired:
                guard.terminate()
                try:guard.wait(timeout=5)
                except Exception as exc:result['watchdog_cleanup_error_class']=type(exc).__name__
        result['finished_epoch']=clock();h.write(out/'outcome.json',result,exclusive=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue',required=True);parser.add_argument('--out',required=True)
    parser.add_argument('--rental-proof',type=Path,required=True);parser.add_argument('--remaining-hours',type=float)
    parser.add_argument('--max-hours',type=float,default=4)
    parser.add_argument('--startup-window-plan',type=Path,required=True)
    args=parser.parse_args()
    def interrupted(signum,frame):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    value=execute(args);print(json.dumps(value,indent=2));return value['returncode']


if __name__=='__main__':raise SystemExit(main())
