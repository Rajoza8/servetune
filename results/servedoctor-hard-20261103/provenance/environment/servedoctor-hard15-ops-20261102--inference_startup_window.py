#!/usr/bin/env python3
"""One scope-bound 600s read-only SSH window, with no create/start/attach retries.

Only cat /etc/vast-agents-guide.md is dispatched over SSH. A failed window
snapshots local setup evidence before one DELETE; an unknown DELETE is GET-only.
The caller must own phase heartbeat throughout start/resume and review the guide
before executing any other remote command. No actual operation runs on import.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

import inference_vast as ops
import inference_remote as remote
import inference_request_logs as request_logs_safe

WINDOW_SECONDS = 600
LOG_SECONDS = 300
ALLOWED_REMOTE_ARGV = ['cat','/etc/vast-agents-guide.md']
DELETION_CLOSURE = 'GET-confirmed deletion after unauthenticated startup window; no STOP confirmation'


def descriptor(path):
    path=Path(path).resolve()
    return {'path':str(path),'sha256':ops.sha(path)}


def write_new(path,value):
    ops.write(Path(path),value,exclusive=True)


class Window:
    def __init__(self,service=None,clock=time.time,sleep=time.sleep,run=subprocess.run,collect=None):
        self.service=ops.Rental() if service is None else service
        self.root,self.repo=self.service.root.resolve(),self.service.repo.resolve()
        self.clock,self.sleep,self.run=clock,sleep,run
        self.collect=collect or request_logs_safe.collect

    def scope(self,plan=None):
        state=self.service.load()
        if (not isinstance(state.get('instance_id'),int) or state['instance_id'] in (58690026,58716527)
                or state.get('project')!=ops.LABEL or state.get('label')!=ops.LABEL
                or ops.sha(self.service.scope_path)!=state.get('scope_sha256')):
            raise ValueError('Current immutable Hard scope required')
        if plan and (plan['instance_id']!=state['instance_id'] or plan['rental_scope_sha256']!=state['scope_sha256']):
            raise ValueError('Window scope differs')
        return state

    def load_plan(self,path):
        path=Path(path).resolve()
        if (path.name!='plan.json' or path.parent.parent!=self.root or path.is_symlink()
                or not re.fullmatch(r'startup-ssh-window-attempt[1-9][0-9]*',path.parent.name)):
            raise ValueError('Fixed direct OPS startup window plan required')
        plan=json.loads(path.read_text())
        if (any(type(plan.get(k)) not in (int,float) or not math.isfinite(plan[k]) for k in ('started_epoch','deadline_epoch'))
                or plan.get('project')!=ops.LABEL or plan.get('window_seconds')!=WINDOW_SECONDS
                or plan.get('deadline_epoch')!=plan.get('started_epoch',0)+WINDOW_SECONDS
                or plan.get('terminal_receipt_path')!=str(path.parent/'terminal.json')
                or plan.get('helper_sha256')!=ops.sha(__file__)
                or plan.get('allowed_remote_argv')!=ALLOWED_REMOTE_ARGV
                or plan.get('no_create_start_attach_retries') is not True):
            raise ValueError('Immutable startup window plan changed')
        self.scope(plan)
        return path,plan

    def prepare(self,out):
        out=Path(out).resolve()
        if out.parent!=self.root or not re.fullmatch(r'startup-ssh-window-attempt[1-9][0-9]*',out.name):
            raise ValueError('Fresh direct OPS startup window directory required')
        if (out/'plan.json').exists():
            path,_=self.load_plan(out/'plan.json');return path
        state=self.scope();now=self.clock()
        active=self.service.active()
        if now+WINDOW_SECONDS+90>min(active['deadline_epoch'],ops.DEADLINE):
            raise ValueError('Phase must reserve the full600s window plus cleanup')
        out.mkdir(exist_ok=False)
        plan={'project':ops.LABEL,'instance_id':state['instance_id'],'rental_scope_sha256':state['scope_sha256'],
              'started_epoch':now,'deadline_epoch':now+WINDOW_SECONDS,'window_seconds':WINDOW_SECONDS,
              'terminal_receipt_path':str(out/'terminal.json'),'helper_sha256':ops.sha(__file__),
              'allowed_remote_argv':ALLOWED_REMOTE_ARGV,'no_create_start_attach_retries':True,
              'initial_phase_owner':{k:active[k] for k in ('pid','birth') if k in active}}
        write_new(out/'plan.json',plan)
        return out/'plan.json'

    def start(self,out):
        return self.resume(self.prepare(out))

    def command(self,argv,stdout,stderr,timeout):
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:
            raise TimeoutError('No command may start after its deadline')
        # No inherited credentials, agent or user SSH config. Identity remains a path.
        env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','LANG','LC_ALL','TMPDIR')}
        with stdout.open('xb') as out,stderr.open('xb') as err:
            result=self.run(argv,stdout=out,stderr=err,timeout=timeout,env=env)
        return result.returncode

    def authenticated(self,out,plan,guide,outcome):
        value={'project':ops.LABEL,'instance_id':plan['instance_id'],'rental_scope_sha256':plan['rental_scope_sha256'],
               'guide_authenticated':True,'plan':descriptor(out/'plan.json'),'probe_outcome':descriptor(outcome),
               'guide':descriptor(guide)}
        path=out/'authenticated.json'
        if not path.exists():write_new(path,value)
        elif json.loads(path.read_text())!=value:raise ValueError('Authentication proof changed')
        return Path(guide)

    def probe(self,out,plan):
        if self.clock()>=plan['deadline_epoch']:
            raise TimeoutError('No new probe after600s')
        number=len(list(out.glob('probe-[0-9]*')))+1
        attempt=out/f'probe-{number:04d}';attempt.mkdir(exist_ok=False)
        row={'project':ops.LABEL,'instance_id':plan['instance_id'],'rental_scope_sha256':plan['rental_scope_sha256'],
             'started_epoch':self.clock(),'allowed_remote_argv':plan['allowed_remote_argv'],'guide_authenticated':False}
        write_new(attempt/'intent.json',row)
        try:
            state=self.scope(plan);status=state['last_status']
            milestone=plan['started_epoch']+LOG_SECONDS
            probe_deadline=min(plan['deadline_epoch'],milestone if self.clock()<milestone else plan['deadline_epoch'])
            import ipaddress
            host=str(ipaddress.IPv4Address(status['public_ipaddr']));port=int(status['ports']['22/tcp'][0]['HostPort'])
            if not 1<=port<=65535:raise ValueError('Invalid scoped SSH endpoint')
            known=self.root/'known_hosts'
            if not known.exists():
                rc=self.command(['ssh-keyscan','-T','10','-p',str(port),host],attempt/'keyscan.stdout',attempt/'keyscan.stderr',
                                min(15,probe_deadline-self.clock()))
                keys=(attempt/'keyscan.stdout').read_bytes()
                # ssh-keyscan records public host trust for this fresh scope only.
                if rc or not keys.strip():raise ValueError('Host key readiness unavailable')
                with known.open('xb') as stream:stream.write(keys)
            options,address,ssh_port=remote.connection(self.service)
            argv=['ssh',*options,'-p',str(ssh_port),'root@'+address,shlex.join(ALLOWED_REMOTE_ARGV)]
            rc=self.command(argv,attempt/'guide.stdout',attempt/'guide.stderr',min(20,probe_deadline-self.clock()))
            row['returncode']=rc
            if rc==0:
                if self.clock()>plan['deadline_epoch']:
                    row['late_authentication_evidence']=True
                    raise TimeoutError('Late guide is retained for manual review')
                if not (attempt/'guide.stdout').read_bytes().strip():raise ValueError('Empty guide cannot authenticate setup')
                row.update(guide_authenticated=True,guide=descriptor(attempt/'guide.stdout'))
        except Exception as error:
            row['error_class']=type(error).__name__
        row['finished_epoch']=self.clock()
        if row.get('guide_authenticated') and row['finished_epoch']>plan['deadline_epoch']:
            row.update(guide_authenticated=False,late_authentication_evidence=True,error_class='TimeoutError')
        write_new(attempt/'outcome.json',row)
        return row

    def logs(self,out,plan):
        marker=out/'logs-trigger.json'
        global_marker=self.root/f"request-logs-instance-{plan['instance_id']}-dispatch.json"
        if not marker.exists():
            write_new(marker,{'project':ops.LABEL,'instance_id':plan['instance_id'],
                             'trigger_epoch':self.clock(),'elapsed_s':self.clock()-plan['started_epoch']})
        # The collector owns the exclusive global PUT marker. Its resume path
        # consumes a retained receipt/unknown dispatch without another PUT/GET.
        initial=out/'logs-outcome.json'
        previous=[initial,*sorted(out.glob('logs-reconciliation-*.json'))]
        for candidate in reversed(previous):
            if candidate.exists():
                value=json.loads(candidate.read_text())
                proof=value.get('receipt')
                if proof and descriptor(proof['path'])==proof:return
                break
        row={'project':ops.LABEL,'instance_id':plan['instance_id'],'checked_epoch':self.clock(),
             'elapsed_s':self.clock()-plan['started_epoch'],'request_logs_replayed':False}
        try:
            if global_marker.exists():row['existing_dispatch']=descriptor(global_marker)
            target=self.root/f"container-logs-{plan['instance_id']}-startup-window"
            result=self.collect(plan['instance_id'],target,ops=self.root)
            row.update(completed=result.get('completed') is True,resumed_without_put=result.get('resumed_without_put') is True)
            if result.get('failure'):row['failure']=result['failure']
            proof=result.get('existing_receipt')
            if proof:
                path=Path(proof['path']).resolve()
                if path.name!='receipt.json' or path.parent.parent!=self.root or descriptor(path)!=proof:
                    raise ValueError('Collector receipt scope/path differs')
                row['receipt']=proof
            elif (target/'receipt.json').is_file():row['receipt']=descriptor(target/'receipt.json')
        except Exception as error:row['error_class']=type(error).__name__
        output=initial if not initial.exists() else out/f"logs-reconciliation-{len(list(out.glob('logs-reconciliation-*.json')))+1:04d}.json"
        write_new(output,row)

    def backup(self,out,plan):
        prior=sorted(p for p in out.glob('failed-startup-backup-attempt[0-9]*')
                     if p.is_dir() and re.fullmatch(r'failed-startup-backup-attempt[0-9]+',p.name))
        legacy=out/'failed-startup-backup'
        if legacy.exists():prior.insert(0,legacy)
        for folder in reversed(prior):
            receipt_path=folder/'receipt.json'
            if receipt_path.exists():
                try:self.verify_backup(receipt_path,plan)
                except json.JSONDecodeError:
                    # A killed exclusive JSON writer can leave a partial final
                    # receipt. Retain those exact bytes and start a new snapshot.
                    marker=out/(folder.name+'-incomplete-receipt.json')
                    if not marker.exists():write_new(marker,{'retained_partial_receipt':descriptor(receipt_path),
                                                             'error_class':'JSONDecodeError'})
                    continue
                return descriptor(receipt_path)
        numbers=[int(p.name.rsplit('attempt',1)[-1]) for p in prior if p.name!='failed-startup-backup']
        number=max(numbers,default=0)+1
        target=out/f'failed-startup-backup-attempt{number:04d}'
        target.mkdir(exist_ok=False)
        files={};omitted=[];ephemeral=[]
        try:
            paths=list(self.root.rglob('*'))
            for source in paths:
                if target==source or target in source.parents or source.name=='operation.lock':continue
                if source.name.endswith('.tmp'):
                    ephemeral.append(source.relative_to(self.root).as_posix());continue
                if source.is_symlink():raise ValueError('Symlink in startup evidence')
                if not source.is_file():
                    if not source.is_dir():omitted.append(source.relative_to(self.root).as_posix())
                    continue
                rel=source.relative_to(self.root);dest=target/'payload'/rel;dest.parent.mkdir(parents=True,exist_ok=True)
                # Atomic-source writers may progress after this snapshot. Each
                # copied regular file is byte-exact to one immutable read.
                data=source.read_bytes()
                with dest.open('xb') as stream:stream.write(data)
                files[rel.as_posix()]=hashlib.sha256(data).hexdigest()
            hours=self.repo/'runs/servedoctor-gpu-hours.md'
            with (target/'gpu-hours-before-delete.md').open('xb') as stream:stream.write(hours.read_bytes())
            manifest=target/'manifest.json'
            write_new(manifest,{'files_sha256':files,'omitted_nonregular':omitted,'omitted_ephemeral_tmp':ephemeral})
            receipt={'project':ops.LABEL,'instance_id':plan['instance_id'],'rental_scope_sha256':plan['rental_scope_sha256'],
                     'mode':'unauthenticated_600s_startup_window','guide_authenticated':False,'plan':descriptor(out/'plan.json'),
                     'manifest':descriptor(manifest),'gpu_hours_snapshot':descriptor(target/'gpu-hours-before-delete.md'),
                     'snapshot_epoch':self.clock(),'no_remote_setup_or_model_command_dispatched':True,
                     'retained_prior_incomplete_backup_attempts':[str(p) for p in prior]}
            receipt_path=target/'receipt.json';write_new(receipt_path,receipt);self.verify_backup(receipt_path,plan)
            return descriptor(receipt_path)
        except BaseException as error:
            failure=out/f'backup-failure-attempt{number:04d}.json'
            if not failure.exists():write_new(failure,{'project':ops.LABEL,'instance_id':plan['instance_id'],
                'rental_scope_sha256':plan['rental_scope_sha256'],'error_class':type(error).__name__,
                'retained_partial_directory':str(target),'copied_files_sha256':files})
            raise

    def verify_backup(self,path,plan):
        receipt=json.loads(Path(path).read_text());target=Path(path).parent
        if (receipt.get('instance_id')!=plan['instance_id'] or receipt.get('rental_scope_sha256')!=plan['rental_scope_sha256']
                or receipt.get('mode')!='unauthenticated_600s_startup_window' or receipt.get('guide_authenticated') is not False
                or receipt.get('plan')!=descriptor(target.parent/'plan.json') or receipt.get('no_remote_setup_or_model_command_dispatched') is not True):
            raise ValueError('Startup backup binding differs')
        manifest=Path(receipt['manifest']['path'])
        if manifest!=target/'manifest.json' or ops.sha(manifest)!=receipt['manifest']['sha256']:raise ValueError('Backup manifest differs')
        mapping=json.loads(manifest.read_text())['files_sha256']
        if mapping.get('rental-scope.json')!=plan['rental_scope_sha256']:raise ValueError('Backup lacks exact immutable scope')
        for rel,digest in mapping.items():
            p=Path(rel)
            if p.is_absolute() or '..' in p.parts or (target/'payload'/p).is_symlink() or ops.sha(target/'payload'/p)!=digest:raise ValueError('Backup payload differs')
        if descriptor(target/'gpu-hours-before-delete.md')!=receipt['gpu_hours_snapshot']:raise ValueError('Hours snapshot differs')

    def deletion_intents(self,plan):
        result=[]
        for path in self.root.glob('intent-*-delete.json'):
            value=json.loads(path.read_text())
            if value.get('instance_id')==plan['instance_id'] and value.get('rental_scope_sha256')==plan['rental_scope_sha256']:
                if (value.get('operation')!='delete' or value.get('method')!='DELETE'
                        or value.get('path')!=f"/api/v0/instances/{plan['instance_id']}/"):
                    raise ValueError('DELETE scope/endpoint differs')
                result.append(path)
        if len(result)>1:raise ValueError('Multiple DELETE intents violate one-shot policy')
        return result

    def finalize_deleted(self,out,plan,state):
        if not state.get('destroyed_epoch'):return state
        changed=False
        for interval in state.get('running_intervals',[]):
            if 'stop_epoch' not in interval:
                interval.update(stop_epoch=state['destroyed_epoch'],closure_reason=DELETION_CLOSURE,
                                stop_confirmed=False,deletion_confirmed=True)
                changed=True
        if changed:self.service.save(state)  # Also refreshes aggregate hours/cost.
        number=len(list(out.glob('deletion-reconciliation-*.json')))+1
        receipt={'project':ops.LABEL,'instance_id':plan['instance_id'],'rental_scope_sha256':plan['rental_scope_sha256'],
                 'plan':descriptor(out/'plan.json'),'confirmed_absent':True,'destroyed_epoch':state['destroyed_epoch'],
                 'closure_reason':DELETION_CLOSURE,'stop_confirmed':False,'deletion_confirmed':True,
                 'running_intervals':state.get('running_intervals',[]),'observed_epoch':self.clock()}
        path=out/f'deletion-reconciliation-{number:04d}.json';write_new(path,receipt)
        return state

    def exhausted(self,out,plan):
        if self.clock()<plan['deadline_epoch']:raise ValueError('Full600s window required beforeDELETE')
        if any(json.loads(p.read_text()).get('guide_authenticated') for p in out.glob('probe-*/outcome.json')):
            raise ValueError('Authenticated guide requires normal bootstrap/idle-stop policy')
        # Partial/late guide text proves auth may have reached the exact remote
        # command; preserve it for explicit review rather than claim denial.
        uncertain=[p for p in out.glob('probe-*/guide.stdout') if p.stat().st_size]
        if uncertain:
            marker=out/'authentication-uncertain.json'
            if not marker.exists():write_new(marker,{'project':ops.LABEL,'instance_id':plan['instance_id'],
                'rental_scope_sha256':plan['rental_scope_sha256'],'elapsed_s':self.clock()-plan['started_epoch'],
                'guide_descriptors':[descriptor(p) for p in uncertain],'automatic_delete_blocked':True})
            raise ValueError('Nonempty unverified guide requires manual review')
        write_path=out/'window-exhausted.json'
        if not write_path.exists():write_new(write_path,{'elapsed_s':self.clock()-plan['started_epoch'],'guide_authenticated':False})
        backup=self.backup(out,plan)
        with self.service.lock():
            self.service.reconcile();state=self.scope(plan)
            deletion=self.deletion_intents(plan)
            if not state.get('destroyed_epoch') and not deletion:
                if state.get('pending_intent'):raise ValueError('Unresolved prior mutation requires explicit reconciliation')
                self.service.intent(state,'delete',f"/api/v0/instances/{plan['instance_id']}/",reason='User-directed exhausted600s unauthenticated startup window; local backup verified')
                deletion=self.deletion_intents(plan)
            self.service.reconcile();state=self.finalize_deleted(out,plan,self.scope(plan))
        terminal={'project':ops.LABEL,'instance_id':plan['instance_id'],'rental_scope_sha256':plan['rental_scope_sha256'],
                  'status':'ssh_window_exhausted','elapsed_s':self.clock()-plan['started_epoch'],'guide_authenticated':False,
                  'plan':descriptor(out/'plan.json'),'backup_receipt':backup,'confirmed_absent':bool(state.get('destroyed_epoch')),
                  'delete_intent':descriptor(deletion[0]) if deletion else None,'no_stop_dispatched_by_window':True}
        path=out/'terminal.json'
        if not path.exists():write_new(path,terminal)
        else:
            previous=json.loads(path.read_text())
            # The first terminal is immutable; each later absent GET produces a
            # fresh deletion-reconciliation receipt with exact billing closure.
            if previous['plan']!=terminal['plan'] or previous['backup_receipt']!=backup:raise ValueError('Terminal proof changed')
        return None

    def resume(self,path):
        path,plan=self.load_plan(path);out=path.parent
        successes=[]
        for outcome in out.glob('probe-*/outcome.json'):
            row=json.loads(outcome.read_text())
            if row.get('guide_authenticated'):
                if (row.get('instance_id')!=plan['instance_id'] or row.get('rental_scope_sha256')!=plan['rental_scope_sha256']
                        or row.get('returncode')!=0 or row.get('allowed_remote_argv')!=plan['allowed_remote_argv']
                        or any(type(row.get(k)) not in (int,float) or not math.isfinite(row[k]) for k in ('started_epoch','finished_epoch'))
                        or not plan['started_epoch']<=row['started_epoch']<=row['finished_epoch']<=plan['deadline_epoch']):
                    raise ValueError('Successful guide scope/timing/command differs')
                p=Path(row['guide']['path'])
                if p.parent!=outcome.parent or p.name!='guide.stdout' or descriptor(p)!=row['guide']:raise ValueError('Successful guide changed')
                successes.append((p,outcome))
        if len(successes)>1:raise ValueError('Multiple successful guides are unexpected')
        if successes:return self.authenticated(out,plan,*successes[0])
        while self.clock()<plan['deadline_epoch']:
            if self.clock()-plan['started_epoch']>=LOG_SECONDS:self.logs(out,plan)
            if self.clock()>=plan['deadline_epoch']:break
            row=self.probe(out,plan)
            if row.get('guide_authenticated'):
                guide=Path(row['guide']['path'])
                return self.authenticated(out,plan,guide,guide.parent/'outcome.json')
            milestone=plan['started_epoch']+LOG_SECONDS
            until=min(plan['deadline_epoch'],milestone if self.clock()<milestone else plan['deadline_epoch'])
            self.sleep(min(15,max(0,until-self.clock())))
        self.logs(out,plan)
        return self.exhausted(out,plan)


def read_guide(out,service=None):
    return Window(service=service).start(out)


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='operation',required=True)
    for name in ('prepare','start'):
        start=sub.add_parser(name);start.add_argument('--out',type=Path,required=True)
    resume=sub.add_parser('resume');resume.add_argument('--plan',type=Path,required=True)
    args=parser.parse_args();window=Window()
    if args.operation=='prepare':
        plan=window.prepare(args.out);print(json.dumps({'plan':descriptor(plan),'network_or_lifecycle_dispatched':False}));return 0
    guide=window.start(args.out) if args.operation=='start' else window.resume(args.plan)
    print(json.dumps({'guide_authenticated':guide is not None,'guide_path':str(guide) if guide else None}))
    return 0 if guide is not None else 2


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:raise SystemExit('Startup window refused: '+type(error).__name__) from None
