#!/usr/bin/env python3
"""One owned CREATE, immediate public-key attach,600s SSH and fixed3h job queue.

The queue is complete/frozen before rental. No command retries or interstage
STOP; failed/completed/idle work stops once. A separate owned watchdog observes
the actual controller PID/birth, fixed budget/deadline and120s GET outages.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import inference_vast as v
import inference_startup_window as startup


def write(path,value):v.write(path,value,exclusive=True)


def pending_window(service,clock=time.time):
    folder=service.root/'startup-ssh-window-attempt1';path=folder/'plan.json'
    if not path.is_file() or (folder/'authenticated.json').exists():return None
    value=json.loads(path.read_text());state=service.load()
    v.require(value.get('instance_id')==state.get('instance_id') and value.get('rental_scope_sha256')==state.get('scope_sha256')
        and value.get('deadline_epoch')==value.get('started_epoch',0)+600,'Startup window binding differs')
    return path,value


def recover_window(service,clock=time.time,window_factory=startup.Window):
    # The surviving watchdog is an actual command owner. It adopts the original
    # immutable clock, never another CREATE, START, attach or model call.
    service.heartbeat(os.getpid(),'inference startup diagnostic guardian')
    window=window_factory(service=service);folder=service.root/'startup-ssh-window-attempt1'
    path=window.prepare(folder);guide=window.resume(path)
    return {'guide_authenticated':guide is not None,'terminal':(folder/'terminal.json').is_file()}


def reconcile_delete(service,clock=time.time,sleep=time.sleep):
    while clock()<service.load()['allocation_deadline_epoch']:
        try:
            with service.lock():state=service.reconcile()
            if state.get('destroyed_epoch'):
                write(service.root/'delete-guardian-outcome.json',{'confirmed_absent':True,'destroyed_epoch':state['destroyed_epoch']});return
        except Exception:pass
        sleep(10)
    write(service.root/'delete-guardian-outcome.json',{'confirmed_absent':False,'get_only_next':True,'delete_never_retried':True})


def reconcile_unknown_create(service,clock=time.time,sleep=time.sleep,window_factory=startup.Window):
    """GET-only guardian, retained after parent exit until owned match/deadline."""
    number=0
    while clock()<service.load()['allocation_deadline_epoch']:
        state=service.load()
        try:
            with service.lock():state=service.reconcile()
        except Exception as error:
            number+=1;path=service.root/f'unknown-create-get-{number:04d}.json'
            write(path,{'class':type(error).__name__,'at_epoch':clock(),'create_retried':False})
            # A definitive rejected CREATE plus complete absence is a known
            # zero-allocation result. Unknown HTTP outcomes never get that claim.
            intent=state.get('pending_intent')
            if intent:
                value=json.loads((service.root/intent).with_name(Path(intent).stem+'-outcome.json').read_text())
                if value.get('phase')=='response' and value.get('success') is False and value.get('http_status')==400:
                    rows=service.inventory()
                    if not any(r.get('label')==v.LABEL and r.get('machine_id')==state['machine_id'] for r in rows):
                        state['create_rejected_confirmed_absent_epoch']=clock();service.save(state)
                        write(service.root/'unknown-create-guardian-outcome.json',{'known_rejected':True,'confirmed_no_scoped_allocation':True,'future_billing_claimed':False});return
        if state.get('instance_id'):
            service.heartbeat(os.getpid(),'unknown CREATE reconciled diagnostic owner')
            if state.get('last_status',{}).get('actual_status')=='running' and state['last_status'].get('ports'):
                if state['allocation_deadline_epoch']-clock()<690:
                    result=stop_and_confirm(service,'Fixed allocation cannot fit full SSH window plus cleanup',clock,sleep)
                    write(service.root/'unknown-create-guardian-outcome.json',result);return
                try:result=recover_window(service,clock,window_factory)
                except Exception as error:
                    number+=1;write(service.root/f'unknown-create-window-error-{number:04d}.json',{'class':type(error).__name__,'at_epoch':clock()});sleep(10);continue
                if result['guide_authenticated']:result.update(stop_and_confirm(service,'Unknown CREATE reconciled; no analysis authorized by this failed phase',clock,sleep))
                elif service.load().get('pending_intent'):reconcile_delete(service,clock,sleep)
                write(service.root/'unknown-create-guardian-outcome.json',result);return
        sleep(10)
    state=service.load()
    result=stop_and_confirm(service,'Fixed allocation deadline after unknown CREATE',clock,sleep) if state.get('instance_id') else {'unbound_create_outcome_still_unknown':True,'no_resource_absence_or_cost_closure_claimed':True}
    write(service.root/'unknown-create-guardian-outcome.json',result)


def stop_and_confirm(service,reason,clock=time.time,sleep=time.sleep):
    state=service.load()
    if state.get('destroyed_epoch'):return {'confirmed_absent':True,'stop_confirmed':False}
    try:
        with service.lock():
            service.reconcile();state=service.load()
            if state.get('destroyed_epoch'):return {'confirmed_absent':True,'stop_confirmed':False}
            if service.stopped(state.get('last_status',{})) and all('stop_epoch' in row for row in state['running_intervals']):return {'stop_confirmed':True}
            pending=state.get('pending_intent');op=json.loads((service.root/pending).read_text())['operation'] if pending else None
            if op not in ('stop','delete'):service.stop(reason)
        until=clock()+120
        while clock()<until:
            with service.lock():service.reconcile();state=service.load()
            if state.get('destroyed_epoch'):return {'confirmed_absent':True,'stop_confirmed':False}
            if not state.get('pending_intent') and service.stopped(state.get('last_status',{})):return {'stop_confirmed':True}
            sleep(5)
    except Exception as error:return {'stop_confirmed':False,'cleanup_error_class':type(error).__name__}
    return {'stop_confirmed':False,'cleanup_error_class':'StopConfirmationTimeout'}


def watchdog(service,pid,birth,sleep=time.sleep,clock=time.time):
    outage=None;number=0
    while True:
        state=service.load()
        if state.get('destroyed_epoch'):return
        try:
            with service.lock():service.reconcile();state=service.load()
            outage=None
        except Exception as error:
            if outage is None:outage=clock()
            number+=1;write(service.root/f'watchdog-get-error-{number:04d}.json',{'class':type(error).__name__,'at_epoch':clock(),'first_epoch':outage})
        reason=None
        if clock()>=state['allocation_deadline_epoch']:reason='Fixed3h allocation deadline'
        elif service.cost(state)['total_usd_upper']+state['dph_total']*90/3600>=v.CAP:reason='Shared43USD budget'
        elif service.birth(pid)!=birth:reason='Actual controller no longer alive'
        else:
            try:service.active()
            except Exception:reason='No fresh actual controller heartbeat'
        if outage is not None and clock()-outage>=120:reason='120s provider inventory outage'
        if reason:
            budget=reason in ('Fixed3h allocation deadline','Shared43USD budget')
            pending=pending_window(service,clock)
            if not budget and pending:
                if service.birth(pid)==birth and clock()<pending[1]['deadline_epoch']:
                    # The original owner still handles its read-only window;
                    # GET outages/stale heartbeats cannot shorten that clock.
                    sleep(15);continue
                try:
                    result=recover_window(service,clock)
                    if not result['guide_authenticated']:
                        if service.load().get('pending_intent'):reconcile_delete(service,clock,sleep)
                        return
                except Exception as error:
                    path=service.root/'watchdog-window-recovery-error.json'
                    if not path.exists():write(path,{'class':type(error).__name__,'no_stop_dispatched':True})
                    if clock()<state['allocation_deadline_epoch']:sleep(15);continue
            write(service.root/'watchdog-stop-intent.json',{'reason':reason,'owner_pid':pid,'owner_birth':birth,'at_epoch':clock()})
            result=stop_and_confirm(service,reason,clock,sleep)
            write(service.root/'watchdog-stop-outcome.json',result);return
        sleep(15)


def execute(args,service=None,run=subprocess.Popen,clock=time.time,sleep=time.sleep,window_factory=startup.Window):
    service=service or v.Rental();root=service.root
    v.require(not root.exists(),'Fresh inference control directory required')
    queue_path=Path(args.queue).resolve();queue=json.loads(queue_path.read_text())
    v.require(queue.get('project')==v.PROJECT and queue.get('final') is True and queue.get('commands'),'Complete frozen inference queue required before CREATE')
    names=set()
    for job in queue['commands']:
        v.require(isinstance(job.get('name'),str) and job['name'] not in names and job.get('argv') and all(isinstance(a,str) and '\x00' not in a for a in job['argv']),'Distinct exact command argv required')
        names.add(job['name'])
    root.mkdir();pid=os.getpid();birth=service.birth(pid);v.require(birth,'Actual owning PID required')
    write(root/'create-owner.json',{'project':v.PROJECT,'pid':pid,'birth':birth,'at_epoch':clock()})
    write(root/'queue.json',queue)
    outcome={'project':v.PROJECT,'started_epoch':clock(),'commands':[],'returncode':1,'stop_confirmed':False,'cleanup_confirmed':False,
        'fixed_allocation_seconds':v.WINDOW,'queue':v.desc(root/'queue.json'),'failure':None}
    watchdog_process=None;child=None;finished=threading.Event();heartbeat_thread=None;window=None;startup_plan=None
    try:
        with service.lock():created=service.create(args.selection,args.prior_receipt)
        write(root/'create-result.json',created)
        v.require(created.get('success') is True,'CREATE was failed/unknown; preserve and reconcile, never retry')
        # Mandatory immediate attach precedes status/readiness polling. Its sole
        # failed/unknown response is retained; full SSH diagnostics still run.
        with service.lock():attached=service.attach_early()
        write(root/'attach-result.json',attached)
        def beat():
            while not finished.is_set():
                try:
                    service.heartbeat(pid,'inference_pipeline fixed actual owner')
                except Exception as error:
                    path=root/'heartbeat-error.json'
                    if not path.exists():write(path,{'class':type(error).__name__})
                finished.wait(20)
        service.heartbeat(pid,'inference_pipeline fixed actual owner');heartbeat_thread=threading.Thread(target=beat,daemon=True);heartbeat_thread.start()
        watchdog_process=run([sys.executable,str(Path(__file__).resolve()),'--watchdog','--owner-pid',str(pid),'--owner-birth',birth],cwd=service.repo)
        write(root/'watchdog-process.json',{'pid':watchdog_process.pid,'birth':service.birth(watchdog_process.pid),'owner_pid':pid,'owner_birth':birth})
        # Start the immutable diagnostic clock immediately after the one attach.
        # The watchdog refreshes public endpoint status by GET in parallel;
        # loading/missing ports are retained read-only probe failures, never an
        # early STOP trigger or another CREATE/attach dispatch.
        state=service.load();service.forecast(state)
        window=window_factory(service=service);startup_plan=window.prepare(root/'startup-ssh-window-attempt1')
        guide=window.resume(startup_plan)
        v.require(guide is not None,'Full600s SSH window exhausted; retained terminal evidence')
        state=service.load()
        ready={'project':v.PROJECT,'instance_id':state['instance_id'],'rental_scope_sha256':state['scope_sha256'],'guide':v.desc(guide),'requires_human_full_guide_review':True}
        write(root/'guide-ready.json',ready)
        ack=root/'guide-reviewed.json';until=min(clock()+180,state['allocation_deadline_epoch']-90)
        while not ack.exists() and clock()<until:sleep(2)
        v.require(ack.is_file() and json.loads(ack.read_text()).get('guide_sha256')==v.sha(guide),'Root full-guide review acknowledgement required')
        outcome.update(instance_id=state['instance_id'],rental_scope_sha256=state['scope_sha256'],allocation_deadline_epoch=state['allocation_deadline_epoch'])
        for index,job in enumerate(queue['commands']):
            state=service.load();service.forecast(state);remaining=state['allocation_deadline_epoch']-clock()-90
            v.require(remaining>0,'Fixed allocation cleanup reserve exhausted')
            row={'name':job['name'],'index':index,'started_epoch':clock(),'argv':job['argv']};outcome['commands'].append(row)
            with (root/f'job-{index:02d}.stdout').open('xb') as stdout,(root/f'job-{index:02d}.stderr').open('xb') as stderr:
                child=run(job['argv'],cwd=service.repo,stdout=stdout,stderr=stderr)
                row.update(pid=child.pid,birth=service.birth(child.pid));write(root/f'job-{index:02d}-intent.json',row)
                try:code=child.wait(timeout=min(float(job.get('timeout_s',remaining)),remaining))
                except BaseException:
                    child.send_signal(signal.SIGINT)
                    try:child.wait(timeout=30)
                    except subprocess.TimeoutExpired:child.terminate();child.wait(timeout=15)
                    raise
            row.update(returncode=code,finished_epoch=clock());write(root/f'job-{index:02d}-outcome.json',row);child=None
            v.require(code==0,'Inference job failed; preserve original outcome without retry')
        outcome['returncode']=0
    except BaseException as error:
        outcome['failure']={'class':type(error).__name__}
        # Preserve the original600s clock even if the first window invocation
        # failed locally. No CREATE/attach/model command is replayed.
        if startup_plan and not (Path(startup_plan).parent/'authenticated.json').exists():
            try:window.resume(startup_plan)
            except BaseException as resumed:outcome['startup_recovery_error_class']=type(resumed).__name__
    finally:
        finished.set()
        if heartbeat_thread:heartbeat_thread.join(timeout=25)
        if child is not None and child.poll() is None:
            try:
                child.send_signal(signal.SIGINT)
                try:child.wait(timeout=30)
                except subprocess.TimeoutExpired:child.terminate();child.wait(timeout=15)
            except Exception as error:outcome['child_cleanup_error_class']=type(error).__name__
        relay=service.root.parent/'inference-transport-attempt1/relay-pointer.json'
        if relay.is_file():
            try:
                minimal={k:value for k,value in os.environ.items() if k in ('PATH','HOME','LANG','LC_ALL','TMPDIR')}
                with (root/'transport-cleanup.stdout').open('xb') as stdout,(root/'transport-cleanup.stderr').open('xb') as stderr:
                    result=subprocess.run([sys.executable,str(service.root.parent/'inference_meta_tunnel.py'),'stop'],cwd=service.repo,
                        stdout=stdout,stderr=stderr,timeout=45,env=minimal)
                outcome['transport_cleanup_returncode']=result.returncode
                if result.returncode:outcome['transport_cleanup_error_class']='NonzeroCleanupExit'
            except Exception as error:outcome['transport_cleanup_error_class']=type(error).__name__
        if watchdog_process:
            watchdog_process.terminate()
            try:watchdog_process.wait(timeout=20);outcome['cleanup_confirmed']=True
            except subprocess.TimeoutExpired:outcome['watchdog_cleanup_error_class']='TimeoutExpired'
        else:outcome['cleanup_confirmed']=True
        if outcome.get('transport_cleanup_error_class') or outcome.get('child_cleanup_error_class'):outcome['cleanup_confirmed']=False
        if service.state_path.exists():
            state=service.load()
            terminal=root/'startup-ssh-window-attempt1/terminal.json'
            if state.get('destroyed_epoch'):outcome['confirmed_absent']=True
            elif terminal.is_file() and json.loads(terminal.read_text()).get('delete_intent'):
                outcome['delete_pending_get_only']=True
                guardian=run([sys.executable,str(Path(__file__).resolve()),'--reconcile-delete'],cwd=service.repo)
                outcome['reconciliation_guardian']={'pid':guardian.pid,'birth':service.birth(guardian.pid)}
            elif state.get('instance_id'):outcome.update(stop_and_confirm(service,'Inference work completed/failed; stop idle',clock,sleep))
            else:
                # No blind STOP endpoint and no CREATE retry. A real detached
                # GET-only owner remains to resolve potential late allocation.
                guardian=run([sys.executable,str(Path(__file__).resolve()),'--reconcile-create'],cwd=service.repo)
                outcome['create_outcome_unknown_get_only']=True
                outcome['reconciliation_guardian']={'pid':guardian.pid,'birth':service.birth(guardian.pid)}
        outcome['finished_epoch']=clock();write(root/'outcome.json',outcome)
    return outcome


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--queue');p.add_argument('--selection');p.add_argument('--prior-receipt')
    p.add_argument('--watchdog',action='store_true');p.add_argument('--reconcile-create',action='store_true');p.add_argument('--reconcile-delete',action='store_true');p.add_argument('--owner-pid',type=int);p.add_argument('--owner-birth');a=p.parse_args()
    def interrupted(*_):raise InterruptedError('Owned inference phase interrupted')
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    if a.reconcile_create:reconcile_unknown_create(v.Rental());return 0
    if a.reconcile_delete:reconcile_delete(v.Rental());return 0
    if a.watchdog:watchdog(v.Rental(),a.owner_pid,a.owner_birth);return 0
    result=execute(a);print(json.dumps(result));return result['returncode']


if __name__=='__main__':raise SystemExit(main())
