#!/usr/bin/env python3
"""Private, read-only owned-job witness. Never signals, starts jobs or reads keys.

Only the SERVEDOCTOR_JOB_OWNER environment entry is selected in memory; the
receipt contains its SHA and a verification boolean, never its value or env.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
import hard_integrity as gate

OWNER=b'SERVEDOCTOR_JOB_OWNER='


def python_argv(argv):
    return bool(argv) and re.fullmatch(r'python(?:3(?:\.[0-9]+)?)?',Path(argv[0]).name) is not None


def recorder_argv(argv,study):
    if not python_argv(argv) or argv[1:4]!=['-m','servedoctor','record']:return False
    allowed={'--study-dir','--model-revision','--model-id','--data-dir','--port','--gpu-index','--dtype','--split','--ids'}
    rest=argv[4:]
    if len(rest)%2:return False
    pairs=list(zip(rest[::2],rest[1::2]));flags=dict(pairs)
    if len(flags)!=len(pairs) or not set(flags)<=allowed:return False
    if flags.get('--study-dir')!=study or flags.get('--model-revision')!=gate.REV:return False
    exact={'--model-id':'meta-models/Muse-Glimmer-30B','--port':'8000','--gpu-index':'0','--dtype':'bf16'}
    if any(k in flags and flags[k]!=v for k,v in exact.items()):return False
    if '--split' in flags and flags['--split'] not in ('hard','reference'):return False
    if '--data-dir' in flags and (Path(flags['--data-dir']).is_absolute() or '..' in Path(flags['--data-dir']).parts):return False
    if '--ids' in flags:
        ids=flags['--ids'].split(',')
        if len(ids)!=len(set(ids)) or any(not re.fullmatch(r'hard-(?:0[1-9]|1[0-6])|reference',v) for v in ids):return False
    return True


def job_argv(argv,spec,duration,drain):
    if not python_argv(argv) or argv[1:3]!=['-m',spec['module']]:return False
    rest=argv[3:]
    if len(rest)%2:return False
    pairs=list(zip(rest[::2],rest[1::2]));flags=dict(pairs)
    expected={'--seconds':duration-spec['onset_s']+drain,'--duty':spec['duty'],'--size':spec['matrix_size']}
    if spec.get('period') is not None:expected['--period']=spec['period']
    if len(flags)!=len(pairs) or set(flags)!=set(expected):return False
    try:return all(float(flags[k])==v for k,v in expected.items())
    except ValueError:return False


class ProcFS:
    def __init__(self,root=Path('/proc')):self.root=Path(root)
    def identity(self,pid):
        base=self.root/str(pid)
        try:
            tail=(base/'stat').read_text().rsplit(')',1)[1].split()
            status=(base/'status').read_text().splitlines()
            uid=int(next(line.split()[1] for line in status if line.startswith('Uid:')))
            return {'pid':pid,'state':tail[0],'ppid':int(tail[1]),'start_ticks':int(tail[19]),'uid':uid,
                    'cwd':str((base/'cwd').resolve(strict=True)),
                    'argv':[v.decode('utf-8','strict') for v in (base/'cmdline').read_bytes().split(b'\0') if v]}
        except (OSError,ValueError,UnicodeError,IndexError,StopIteration):return None
    def birth_state(self,pid):
        """Only ENOENT proves absence; permission/read failures stay unknown."""
        try:tail=(self.root/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
        except FileNotFoundError:return None
        return {'state':tail[0],'start_ticks':int(tail[19])}
    def children(self,pid):
        # Timer callbacks launch from a nonleader thread. Linux reports child
        # ownership per task, so inspect every task belonging to this one CLI.
        children=set()
        try:tasks=list((self.root/str(pid)/'task').iterdir())
        except OSError:return []
        for task in tasks:
            try:children.update(int(p) for p in (task/'children').read_text().split())
            except (OSError,ValueError):continue
        return sorted(children)
    def pids(self):
        return [int(p.name) for p in self.root.iterdir() if p.name.isdecimal()]
    def limits(self,pid):
        try:
            fields=next(line.split() for line in (self.root/str(pid)/'limits').read_text().splitlines() if line.startswith('Max open files'))
            return {'fd_soft':int(fields[3]),'fd_hard':int(fields[4])}
        except (OSError,ValueError,StopIteration,IndexError):return None
    def owner_sha(self,pid):
        try:
            # Do not decode, retain or return any other environment entry.
            matches=[v for v in (self.root/str(pid)/'environ').read_bytes().split(b'\0') if v.startswith(OWNER)]
            return hashlib.sha256(matches[0]).hexdigest() if len(matches)==1 and len(matches[0])>len(OWNER) else None
        except OSError:return None


def current_public_time(study,declared):
    active=[]
    for case in declared:
        path=study/'incidents'/case['id']
        telemetry=path/'telemetry.jsonl'
        if path.is_symlink() or telemetry.is_symlink():raise ValueError('Symlink active evidence')
        if telemetry.exists() and not (path/'recording.json').exists():
            raw=telemetry.read_bytes().splitlines(keepends=True)
            if raw and not raw[-1].endswith(b'\n'):raw=raw[:-1]
            if raw:
                rows=[json.loads(line) for line in raw]
                if any(not isinstance(r,dict) or not gate.numeric(r.get('t')) or r['t']<0 for r in rows):raise ValueError('Invalid completed telemetry line')
                active.append((case,rows[-1]['t']))
    if len(active)>1:raise ValueError('Multiple active public incidents')
    return active[0] if active else (None,None)


class Observer:
    def __init__(self,*,repo,study,declared,frozen,recorder_pid,recorder_start_ticks,proc=None):
        self.repo=Path(repo).resolve();self.study=Path(study);self.declared=declared;self.frozen=frozen
        self.recorder_pid=recorder_pid;self.recorder_start_ticks=recorder_start_ticks;self.proc=proc or ProcFS()
        self.jobs={};self.unassigned_owned={};self.issues=set();self.seen_recorder=False
    def retain_unassigned_owned(self,ident):
        """Retain safe cleanup identity even if a failed collector has no clock."""
        if (ident['uid']!=0 or ident['ppid']!=self.recorder_pid or ident['cwd']!=str(self.repo)
                or not any(job_argv(ident['argv'],spec,case['duration_s'],self.frozen['record_drain_timeout_s'])
                    for case in self.declared for spec in case.get('jobs',[]))):return
        marker=self.proc.owner_sha(ident['pid']);again=self.proc.identity(ident['pid'])
        if marker and again and all(again[k]==ident[k] for k in ('start_ticks','ppid','uid','cwd','argv')):
            self.unassigned_owned[(ident['pid'],ident['start_ticks'])]={'pid':ident['pid'],'start_ticks':ident['start_ticks'],
                'module':ident['argv'][2],'owner_marker_sha256':marker}
    def recorder(self):
        current=self.proc.identity(self.recorder_pid)
        if current is None or current['state']=='Z' or current['start_ticks']!=self.recorder_start_ticks:return None
        if (current['uid']!=0 or current['cwd']!=str(self.repo)
                or not recorder_argv(current['argv'],self.study.relative_to(self.repo).as_posix())):
            raise ValueError('Recorder ownership identity differs')
        self.seen_recorder=True;return current
    def sample(self,case,public_t):
        if not self.recorder():return False
        children=self.proc.children(self.recorder_pid);present=set()
        for pid in children:
            ident=self.proc.identity(pid)
            if not ident or ident['state']=='Z':continue
            argv=ident['argv'];module=argv[2] if len(argv)>2 and argv[1]=='-m' else None
            if module not in gate.JOB_MODULES:continue
            if case is None:
                self.retain_unassigned_owned(ident)
                self.issues.add('owned_job_child_without_active_incident');continue
            specs=case.get('jobs',[]);indices=[i for i,spec in enumerate(specs) if spec['module']==module]
            if len(indices)!=1:
                self.retain_unassigned_owned(ident)
                self.issues.add('unexpected_job_module_child');continue
            index=indices[0];spec=specs[index]
            valid=(ident['uid']==0 and ident['ppid']==self.recorder_pid and ident['cwd']==str(self.repo)
                   and job_argv(argv,spec,case['duration_s'],self.frozen['record_drain_timeout_s']))
            marker=self.proc.owner_sha(pid)
            # Re-read birth/parent identity after reading the marker to reject PID races.
            again=self.proc.identity(pid)
            if not valid or not marker or not again or any(again[k]!=ident[k] for k in ('start_ticks','ppid','uid','cwd','argv')):
                self.issues.add('job_ownership_identity_unproven');continue
            key=(case['id'],index,pid,ident['start_ticks']);present.add(key)
            row=self.jobs.setdefault(key,{'incident':case['id'],'job_index':index,'module':module,'pid':pid,
                'start_ticks':ident['start_ticks'],'uid':0,'parent_verified':True,'cwd_verified':True,
                'recorder_pid':self.recorder_pid,'recorder_start_ticks':self.recorder_start_ticks,
                'owner_marker_verified':True,'owner_marker_sha256':marker,'first_public_t':public_t,
                'last_public_t':public_t,'observations':0,'max_public_gap_s':0.0})
            if row['owner_marker_sha256']!=marker:self.issues.add('job_owner_marker_changed')
            row['max_public_gap_s']=max(row['max_public_gap_s'],public_t-row['last_public_t'])
            row['last_public_t']=public_t;row['observations']+=1
        if case is not None:
            for key,row in self.jobs.items():
                if row['incident']==case['id'] and key not in present and public_t<case['duration_s']-gate.SLACK:
                    self.issues.add('observed_job_exited_before_nominal_end')
            for index,spec in enumerate(case.get('jobs',[])):
                if (public_t>spec['onset_s']+self.frozen['job_policy']['startup_allowance_s']
                        and not any(r['incident']==case['id'] and r['job_index']==index for r in self.jobs.values())):
                    self.issues.add('expected_job_missing_after_startup_allowance')
        return True
    def finish(self):
        leaks=[]
        retained={**{(r['pid'],r['start_ticks']):r for r in self.jobs.values()},**self.unassigned_owned}
        for row in retained.values():
            ident=self.proc.identity(row['pid'])
            if ident and ident['state']!='Z' and ident['start_ticks']==row['start_ticks']:
                # Never signal: only previously witnessed direct owned children are reported.
                if (ident['uid']==0 and ident['cwd']==str(self.repo) and python_argv(ident['argv'])
                        and ident['argv'][1:3]==['-m',row['module']]
                        and self.proc.owner_sha(row['pid'])==row['owner_marker_sha256']):
                    leaks.append({'pid':row['pid'],'start_ticks':row['start_ticks'],'owner_verified':True})
                else:self.issues.add('prior_owned_pid_identity_changed')
        if leaks:self.issues.add('verified_owned_jobs_alive_after_recorder_exit')
        if not self.seen_recorder:self.issues.add('recorder_never_witnessed_alive')
        try:finished=self.recorder() is None
        except ValueError:
            finished=False;self.issues.add('recorder_identity_changed_before_exit')
        return {'project':gate.PROJECT,'created_at_utc':gate.utc(),'study_dir':self.study.relative_to(self.repo).as_posix(),
            'source_commit':self.frozen['source_commit'],'freeze_sha256':gate.sha(self.study/gate.FREEZE),
            'preflight_sha256':self.frozen['preflight']['sha256'],
            'recorder_pid':self.recorder_pid,'recorder_start_ticks':self.recorder_start_ticks,
            'finished':finished,'jobs':list(self.jobs.values()),'issues':sorted(self.issues),
            'owned_leaks':leaks,'cleanup':'Read-only observer; verified leaks require explicit owned cleanup before reuse.'}


def physical_binding(study,frozen,*,ops=gate.OPS,environ=None,run=subprocess.run):
    environment=os.environ if environ is None else environ;scope_path=gate.regular(ops,'rental-scope.json');scope=gate.load(scope_path)
    instance=scope.get('instance_id')
    if (gate.sha(scope_path)!=frozen['job_policy']['rental_scope_sha256'] or scope.get('project')!=gate.PROJECT
            or scope.get('label')!=gate.PROJECT or type(instance) is not int or instance<=0 or instance in (58690026,58716527)
            or str(instance)!=environment.get('CONTAINER_ID')):raise ValueError('Physical observer rental namespace differs')
    completed=run(['nvidia-smi','--id=0','--query-gpu=uuid','--format=csv,noheader'],capture_output=True,text=True,timeout=10)
    values=completed.stdout.strip().splitlines()
    if completed.returncode or values!=[frozen['job_policy']['gpu_uuid']]:raise ValueError('GPU0 physical UUID differs from frozen preflight')
    return {'verified':True,'instance_id':instance,'gpu_index':0,'gpu_uuid':values[0],
        'rental_scope_sha256':gate.sha(scope_path),'container_id_matches_scope':True}


def ready_receipt(observer,selected,ready_file,binding_fn=None):
    """Source creates each incident directory before scheduling any job timer."""
    identity=observer.recorder()
    if not identity:raise ValueError('Recorder exited before observer readiness')
    binding=(binding_fn or physical_binding)(observer.study,observer.frozen)
    expected={s['id'] for s in observer.declared}
    if not selected or not set(selected)<=expected:raise ValueError('Observer readiness IDs differ')
    if any((observer.study/'incidents'/name).exists() or (observer.study/'incidents'/name).is_symlink() for name in selected):
        raise ValueError('Observer started after a selected incident directory existed')
    value={'project':gate.PROJECT,'ready_at_utc':gate.utc(),'source_commit':observer.frozen['source_commit'],
        'freeze_sha256':gate.sha(observer.study/gate.FREEZE),'recorder_pid':observer.recorder_pid,
        'recorder_start_ticks':observer.recorder_start_ticks,'selected_ids':sorted(selected),
        'selected_incident_directories_absent':True,'ready_before_source_job_timers':True,'physical_gpu_binding':binding}
    gate.write_new(ready_file,value);return value


def watch(study,pid,start_ticks,out,*,repo=gate.REPO,proc=None,sleeper=time.sleep,ready_file=None,expected_ids=None):
    frozen=gate.verify_freeze(study,repo);declared=gate.cases(study)
    observer=Observer(repo=repo,study=study,declared=declared,frozen=frozen,recorder_pid=pid,recorder_start_ticks=start_ticks,proc=proc)
    if not observer.recorder():raise ValueError('Recorder already exited or birth identity differs; cannot invent job ownership')
    if out.exists():raise ValueError('Never overwrite owned observer proof')
    trail=out.with_suffix('.observations.jsonl');trail.parent.mkdir(parents=True,exist_ok=True)
    error=None
    try:
        with trail.open('x') as stream:
            if ready_file is not None:
                identity=observer.recorder();flags=dict(zip(identity['argv'][4::2],identity['argv'][5::2]))
                selected={s['id'] for s in declared if '--split' not in flags or s['split']==flags['--split']}
                if '--ids' in flags:selected &= set(flags['--ids'].split(','))
                if expected_ids is not None and selected!=set(expected_ids):raise ValueError('Observer command/expected selection differs')
                ready_receipt(observer,selected,ready_file)
            while observer.recorder():
                case,public_t=current_public_time(study,declared)
                observer.sample(case,public_t)
                stream.write(json.dumps({'observed_at_utc':gate.utc(),'incident':case['id'] if case else None,
                    'public_t':public_t,'job_observations':sum(v['observations'] for v in observer.jobs.values()),
                    'issues':sorted(observer.issues)})+'\n');stream.flush()
                sleeper(frozen['job_policy']['observer_poll_s'])
    except BaseException as exc:
        error=exc;observer.issues.add(type(exc).__name__)
    proof=observer.finish();proof['observations']=gate.descriptor(trail)
    if ready_file is not None and ready_file.exists():proof['readiness']=gate.descriptor(ready_file)
    gate.write_new(out,proof)
    if error:raise error
    return proof


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study-dir',type=Path,default=Path(gate.PRIMARY))
    parser.add_argument('--recorder-pid',type=int,required=True);parser.add_argument('--recorder-start-ticks',type=int,required=True)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--ready-file',type=Path)
    parser.add_argument('--expected-ids');args=parser.parse_args()
    root=(gate.REPO/args.study_dir).resolve();out=args.out.absolute()
    if not root.is_relative_to(gate.REPO/'runs') or not out.is_relative_to(gate.OPS) or args.recorder_pid<=0 or args.recorder_start_ticks<=0:parser.error('Invalid scoped identity/output')
    ready=args.ready_file.absolute() if args.ready_file else None
    if ready is not None and (not ready.is_relative_to(gate.OPS) or ready in (out,out.with_suffix('.observations.jsonl'))):parser.error('Invalid private ready receipt')
    proof=watch(root,args.recorder_pid,args.recorder_start_ticks,out,ready_file=ready,
                expected_ids=args.expected_ids.split(',') if args.expected_ids else None)
    print(json.dumps({'finished':proof['finished'],'job_count':len(proof['jobs']),'issues':proof['issues'],
        'owned_leak_count':len(proof['owned_leaks']),'proof_sha256':gate.sha(out)}))
    return int(not proof['finished'] or bool(proof['issues']) or bool(proof['owned_leaks']))


if __name__=='__main__':sys.exit(main())
