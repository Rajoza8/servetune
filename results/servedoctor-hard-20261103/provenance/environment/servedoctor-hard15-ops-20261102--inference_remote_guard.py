#!/usr/bin/env python3
"""GPU-local fallback: bound scope, 120s idle limit, one stop attempt, no retries.

The primary local Hard phase stops immediately when work ends. This guard is a
backup for lost local control. It needs no repository before bootstrap.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time
import urllib.error
import urllib.request

PROJECT='servedoctor-hard15-inference-20261103'
BASE=Path('/workspace/servedoctor-hard')
CONTROL=BASE/'control'
REPO=BASE/'servetune'
OPS=REPO/'runs/servedoctor-hard15-ops-20261102'
HARD_CUTOFF=1793746800.0  # 2026-11-03 23:00 UTC, 18:00 Eastern.
IDLE_SECONDS=120
APPROVED=('inference_integrity.py','inference_measure_contexts.py','inference_response_guard.py','inference_export_scores.py')

# Exact public launcher code; no credentials are present in either string.
KEY_REMOTE_CODE_SHA256='bac8f8dc247342cee0c7631b5a2a7840f87383a6ca89bdbe390915abb8487caa'
KEY_REMOTE_CHILD_SHA256='e016fa0da62bf796c5e830b51e7c5196f2ff0cdd5041d23bb1f69d6b2a8bd23e'
KEY_REMOTE_DIAGNOSTIC_SHA256='73b1663b7b035dd161e10125d8e537edceac7907269eeda82704a2fb83bd3894'
KEY_DEADLINE=1793768399
REV='cec94fcfd6512f2cfe708138c32533b346ea4f69'
ARMS=('glimmer', 'glimmer_to_spark', 'glimmer_to_wonder', 'rules', 'spark', 'wonder')
PRIVATE_REMOTE_SHA256={'evaluate_prepare': 'aed2b5f93b3b22dfd247da94c2d80fe13af5a70fdc2223107288f8ad0e68f746', 'evaluate_ledger': '86bc7f46b799b8a3aa50c4795ef00fe6e57899d9f24a8b1e3177b49696a31852', 'evaluate_archive': '07930ba4cb81063aaee213f99c2108107087590b301e054e41673ceae3652fa9'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise RuntimeError('Redirect blocked')


def digest(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError('Regular proof file required')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_state(control,instance,hard_deadline):
    path=Path(control)/'inference-guard-state.json'
    if path.is_symlink():raise ValueError('Guard state must not be a symlink')
    with path.open('rb') as stream:raw=stream.read(8193)
    if len(raw)>8192:raise ValueError('Guard state too large')
    value=json.loads(raw)
    if (value.get('project')!=PROJECT or type(value.get('instance_id')) is not int or value['instance_id']!=instance
            or not re.fullmatch('[a-f0-9]{64}',value.get('rental_scope_sha256',''))):
        raise ValueError('Guard scope differs')
    for key in ('deadline_epoch','budget_deadline_epoch'):
        if type(value.get(key)) not in (int,float) or not math.isfinite(value[key]) or value[key]>HARD_CUTOFF:
            raise ValueError('Finite bounded guard deadline required')
    if value['deadline_epoch']>hard_deadline:raise ValueError('Inference guard exceeds fixed three-hour allocation')
    scope_path=Path(control)/'rental-scope.json'
    if digest(scope_path)!=value['rental_scope_sha256']:raise ValueError('Immutable rental scope changed')
    scope=json.loads(scope_path.read_text())
    if (scope.get('project')!=PROJECT or scope.get('label')!=PROJECT
            or type(scope.get('instance_id')) is not int or scope['instance_id']!=instance
            or instance in (58690026,58716527)):
        raise ValueError('Scope is not this new Hard container')
    if (scope.get('budget_amendment',{}).get('sha256')!='8efba5368ca146e45ff55d16fb45567058ae015bcee51a26a5510a0e31c4ee2a'
            or value['deadline_epoch']!=scope.get('allocation_deadline_epoch')
            or value['budget_deadline_epoch']!=scope.get('allocation_deadline_epoch')
            or scope.get('allocation_deadline_epoch')!=min(scope.get('allocation_started_epoch',0)+10800,HARD_CUTOFF)):
        raise ValueError('Fixed3h/$43 authorization deadline differs')
    helpers=value.get('approved_helpers_sha256',{})
    allowed={str(REPO/'runs/servedoctor-hard15-ops-20261102'/name) for name in APPROVED}
    allowed.add('/tmp/servedoctor-inference-bootstrap/inference_cold_bootstrap.py')
    if (set(helpers)!=allowed or any(not re.fullmatch('[a-f0-9]{64}',v) for v in helpers.values())):
        raise ValueError('Exact inference helper hash map required')
    return value


def trusted_bootstrap(script,uid,control=CONTROL,tmp_root=Path('/tmp')):
    script,reference=Path(script),Path(control)/'inference_cold_bootstrap.py'
    if (script!=Path(tmp_root)/'servedoctor-inference-bootstrap/inference_cold_bootstrap.py'
            or script.is_symlink() or script.parent.is_symlink()):return False
    try:
        a,b=script.lstat(),reference.lstat()
        return (uid==a.st_uid==b.st_uid and stat.S_ISREG(a.st_mode) and stat.S_ISREG(b.st_mode)
                and not reference.is_symlink() and a.st_size==b.st_size and a.st_size<=262144
                and digest(script)==digest(reference))
    except OSError:return False


def key_cli_argv(argv):
    if not isinstance(argv, list) or not 1 <= len(argv) <= 32:
        raise ValueError()
    if argv == ['diagnose-models']:
        return argv
    if any(not isinstance(a, str) or len(a) > 256 for a in argv) or argv[0] not in ("evaluate", "live"):
        raise ValueError()
    values, i = {}, 1
    common = {"--study-dir", "--model-revision", "--model-id", "--port", "--gpu-index", "--dtype"}
    allowed = common | ({"--split", "--arms", "--glimmer", "--glimmer-url", "--start-glimmer"}
                        if argv[0] == "evaluate" else {"--id", "--arm", "--glimmer", "--out"})
    while i < len(argv):
        flag = argv[i]
        if flag not in allowed or flag in values:
            raise ValueError()
        if flag == "--start-glimmer":
            values[flag], i = True, i + 1
        else:
            if i + 1 >= len(argv):
                raise ValueError()
            values[flag], i = argv[i + 1], i + 2
    study = values.get("--study-dir", "")
    if not re.fullmatch(r"runs/sd-hard(?:-[a-z0-9-]+-attempt[1-9][0-9]*)?", study):
        raise ValueError()
    fixed = {"--model-revision": REV, "--model-id": "meta-models/Muse-Glimmer-30B", "--port": "8000",
             "--gpu-index": "0", "--dtype": "bf16", "--glimmer": "local", "--glimmer-url": "http://127.0.0.1:8000/v1"}
    if any(k in values and values[k] != v for k, v in fixed.items()):
        raise ValueError()
    if argv[0] == "evaluate":
        if values.get("--split") != "hard" or not values.get("--arms") or not set(values["--arms"].split(",")) <= set(ARMS):
            raise ValueError()
        if len(values['--arms'].split(',')) != len(set(values['--arms'].split(','))):
            raise ValueError()
        if values.get("--start-glimmer") and values.get("--model-revision") != REV:
            raise ValueError()
    else:
        if values.get("--model-revision") != REV or values.get("--arm") not in ARMS or not re.fullmatch(r"hard-(?:0[1-9]|1[0-6])", values.get("--id", "")):
            raise ValueError()
        if "--out" in values and not re.fullmatch(re.escape(study) + r"/live/hard-(?:0[1-9]|1[0-6])-[a-z0-9_-]+", values["--out"]):
            raise ValueError()
        if '--out' not in values or not values['--out'].startswith(study + '/live/' + values['--id'] + '-' + values['--arm'] + '-'):
            raise ValueError()
    return argv


def private_output(value,repo):
    path=Path(value)
    path=(path if path.is_absolute() else Path(repo)/path).resolve()
    base=Path(repo)/'runs/servedoctor-hard15-ops-20261102'
    return path.is_relative_to(base) and path!=base


def helper_role(args,helper,repo):
    """Require the actual durable worker/observer CLI shape, never arbitrary -c."""
    name=Path(helper).name
    if name=='record_hard_stage.py':
        if len(args)<5 or args[2] not in ('launch','run','wait','cancel','worker','status'):return False
        rest=args[3:]
        if len(rest)%2:return False
        pairs=list(zip(rest[::2],rest[1::2]));flags=dict(pairs)
        allowed={'--study-dir','--split','--ids','--prior-stage','--out'}
        if not set(flags)<=allowed or any(k!='--prior-stage' and sum(k==a for a,b in pairs)>1 for k in flags):return False
        if '--out' not in flags or not private_output(flags['--out'],repo):return False
        if args[2]=='worker' and rest!=['--out',flags['--out']]:return False
        if '--study-dir' in flags and not re.fullmatch(r'runs/sd-hard(?:-[a-z0-9-]+-attempt[1-9][0-9]*)?',flags['--study-dir']):return False
        if '--split' in flags and flags['--split'] not in ('reference','hard','all'):return False
        return True
    if name=='hard_job_observer.py':
        rest=args[2:]
        if len(rest)%2:return False
        pairs=list(zip(rest[::2],rest[1::2]));flags=dict(pairs)
        allowed={'--study-dir','--recorder-pid','--recorder-start-ticks','--out','--ready-file','--expected-ids'}
        if len(pairs)!=len(flags) or not set(flags)<=allowed:return False
        if not {'--recorder-pid','--recorder-start-ticks','--out'}<=set(flags):return False
        if any(not re.fullmatch('[1-9][0-9]*',flags[k]) for k in ('--recorder-pid','--recorder-start-ticks')):return False
        if not private_output(flags['--out'],repo) or ('--ready-file' in flags and not private_output(flags['--ready-file'],repo)):return False
        if '--study-dir' in flags and not re.fullmatch(r'runs/sd-hard(?:-[a-z0-9-]+-attempt[1-9][0-9]*)?',flags['--study-dir']):return False
        return True
    return True


def key_runner_role(args,cwd,instance,repo,root_home=Path('/root'),allocation_deadline=None):
    if (len(args)<4 or args[1]!='-c' or Path(args[0]).parent!=Path('/venv/main/bin')
            or type(instance) is not int or instance<=0):return None
    code_sha=hashlib.sha256(args[2].encode()).hexdigest()
    try:
        if code_sha==KEY_REMOTE_CODE_SHA256 and cwd in (Path(repo),Path(root_home)):
            if args[3]!=str(instance):return None
            key_cli_argv(args[4:]);return 'trusted_key_runner_parent'
        if code_sha==KEY_REMOTE_CHILD_SHA256 and cwd==Path(repo):
            if type(allocation_deadline) not in (int,float) or not math.isfinite(allocation_deadline):return None
            expected_deadline=min(allocation_deadline,HARD_CUTOFF,KEY_DEADLINE)
            if (len(args)<7 or not re.fullmatch('[a-f0-9]{40}',args[3])
                    or args[4]!=str(instance) or args[5]!=str(expected_deadline)):return None
            key_cli_argv(args[6:]);return 'trusted_key_runner_cli'
        if code_sha==KEY_REMOTE_DIAGNOSTIC_SHA256 and cwd in (Path(repo),Path(root_home)):
            if args[3:]!=[str(instance)]:return None
            return 'trusted_key_runner_diagnostic'
    except (ValueError,IndexError,TypeError):return None
    return None


def private_stage(value,kind,repo):
    path=Path(value);path=(path if path.is_absolute() else Path(repo)/path).resolve()
    return (path.parent==Path(repo)/'runs/servedoctor-hard15-ops-20261102'/kind
            and re.fullmatch('[a-z0-9][a-z0-9-]{0,95}',path.name) is not None)


def helper_hash_map(value):
    if len(value)>8192:return False
    try:item=json.loads(value)
    except (TypeError,ValueError):return False
    return (isinstance(item,dict) and 0<len(item)<=32
            and all(isinstance(k,str) and re.fullmatch('[a-z_]+[.]py',k)
                    and isinstance(v,str) and re.fullmatch('[a-f0-9]{64}',v) for k,v in item.items()))


def private_code_role(args,cwd,repo):
    if cwd!=Path(repo) or len(args)<3 or args[1]!='-c' or Path(args[0]).parent!=Path('/venv/main/bin'):return None
    digest=hashlib.sha256(args[2].encode()).hexdigest()
    roles=[name for name,expected in PRIVATE_REMOTE_SHA256.items() if expected==digest]
    if len(roles)!=1:return None
    role=roles[0];rest=args[3:]
    study=lambda value:re.fullmatch(r'runs/sd-hard(?:-[a-z0-9-]+-attempt[1-9][0-9]*)?',value) is not None
    if role.endswith('_ledger'):
        valid=not rest
    elif role=='record_prepare':
        valid=(len(rest)==5 and study(rest[0]) and private_stage(rest[1],'record-stages',repo)
               and private_stage(rest[2],'record-mirrors',repo) and helper_hash_map(rest[3]) and rest[4] in ('true','false'))
    elif role=='record_archive':
        valid=(len(rest)==3 and study(rest[0]) and private_stage(rest[1],'record-stages',repo)
               and private_stage(rest[2],'record-mirrors',repo))
    elif role=='evaluate_prepare':
        valid=(len(rest)==3 and private_stage(rest[0],'evaluation-stages',repo) and helper_hash_map(rest[1]) and study(rest[2]))
    elif role=='evaluate_archive':
        valid=len(rest)==2 and study(rest[0]) and private_stage(rest[1],'evaluation-stages',repo)
    else:valid=False
    return 'trusted_private_'+role if valid else None


def processes(proc_root=Path('/proc'),uid=None,own_pid=None,control=CONTROL,repo=REPO,
              base=BASE,tmp_root=Path('/tmp'),instance=None,root_home=Path('/root')):
    """Return only safe ownership metadata; never environments or arbitrary argv."""
    uid=os.geteuid() if uid is None else uid
    own_pid=os.getpid() if own_pid is None else own_pid
    repo,base=Path(repo).resolve(),Path(base).resolve()
    scoped=json.loads((Path(control)/'rental-scope.json').read_text())
    if (scoped.get('project')!=PROJECT or scoped.get('label')!=PROJECT or type(scoped.get('instance_id')) is not int
            or (instance is not None and scoped['instance_id']!=instance)):
        raise ValueError('Process witness scope differs')
    instance=scoped['instance_id']
    approved={str(Path(repo)/'runs/servedoctor-hard15-ops-20261102'/name) for name in APPROVED}
    hashes=json.loads((Path(control)/'inference-guard-state.json').read_text())['approved_helpers_sha256']
    found=[]
    for entry in Path(proc_root).iterdir():
        if not entry.name.isdecimal() or int(entry.name)==own_pid:continue
        try:
            before=(entry/'stat').read_text().rsplit(')',1)[1].split()
            if before[0]=='Z':continue
            status=(entry/'status').read_text()
            ids=next(line.split()[1:] for line in status.splitlines() if line.startswith('Uid:'))
            if len(ids)<2 or any(int(value)!=uid for value in ids[:2]):continue
            raw_args=(entry/'cmdline').read_bytes()
            args=raw_args.rstrip(b'\0').split(b'\0')
            if not args:continue
            args=[p.decode('utf-8','strict') for p in args]
            if not re.fullmatch(r'python(?:3(?:\.[0-9]+)?)?',Path(args[0]).name):continue
            while len(args)>1 and args[1] in ('-u','-B','-s','-E','-I'):
                args.pop(1)
            cwd=(entry/'cwd').resolve(strict=True)
            helper=None
            if len(args)>=2 and not args[1].startswith('-'):
                helper=str((cwd/args[1]).resolve())
            reason=(key_runner_role(args,cwd,instance,repo,root_home,scoped.get('allocation_deadline_epoch')) or private_code_role(args,cwd,repo))
            if cwd==Path(repo) and len(args)>=4 and args[1:3]==['-m','servedoctor'] and args[3] in ('evaluate','score','report','validate'):
                reason='servedoctor_command'
            elif cwd==Path(repo) and helper in approved and digest(helper)==hashes.get(helper) and helper_role(args,helper,repo):
                reason='approved_helper'
            elif (cwd in (Path(base),Path(repo)) and len(args)>=2
                  and trusted_bootstrap(args[1],uid,control,tmp_root)
                  and digest(args[1])==hashes.get(str(Path(args[1]).resolve()))):
                reason='trusted_preclone_bootstrap'
            if reason:
                # Parenthesized /proc command names may contain spaces.
                fields=(entry/'stat').read_text().rsplit(')',1)[1].split()
                if (fields[0]=='Z' or fields[19]!=before[19] or (entry/'cmdline').read_bytes()!=raw_args
                        or (entry/'cwd').resolve(strict=True)!=cwd):continue
                again=next(line.split()[1:] for line in (entry/'status').read_text().splitlines() if line.startswith('Uid:'))
                if len(again)<2 or any(int(v)!=uid for v in again[:2]):continue
                found.append({'pid':int(entry.name),'start_ticks':fields[19],'kind':reason})
        except (OSError,ValueError,StopIteration,UnicodeError,IndexError):continue
    return found


def exclusive(path,value):
    with Path(path).open('xb') as stream:
        stream.write((json.dumps(value,indent=2,allow_nan=False)+'\n').encode())
        stream.flush();os.fsync(stream.fileno())


def stop_once(control,instance,reason,scope_sha,environ=None,clock=time.time,opener=None):
    environ=os.environ if environ is None else environ
    if environ.get('CONTAINER_ID')!=str(instance) or type(instance) is not int or instance<=0:
        raise ValueError('May stop only the current scoped container')
    record={'project':PROJECT,'instance_id':instance,'rental_scope_sha256':scope_sha,
            'operation':'stop','method':'PUT','requested_epoch':clock(),'reason':reason}
    control=Path(control)
    exclusive(control/'guard-stop-intent.json',record)
    outcome={**record,'phase':'unknown_outcome'}
    try:
        key=environ['CONTAINER_API_KEY']
        if not key:raise ValueError('Empty container credential')
        request=urllib.request.Request(f'https://console.vast.ai/api/v0/instances/{instance}/',
            data=b'{"state":"stopped"}',method='PUT',
            headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        client=opener or urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        with client.open(request,timeout=30) as response:
            raw=response.read(4097)
            if len(raw)>4096:raise ValueError('Response too large')
            data=json.loads(raw)
            outcome.update(phase='response',http_status=response.status,success=data.get('success') is True)
    except urllib.error.HTTPError as exc:
        outcome.update(phase='response',http_status=exc.code)
    except Exception as exc:outcome['error_class']=type(exc).__name__
    exclusive(control/'guard-stop-outcome.json',outcome)
    return outcome


def run(control=CONTROL,environ=None,clock=time.time,monotonic=time.monotonic,sleep=time.sleep,
        scan=processes,stop=stop_once):
    environ=os.environ if environ is None else environ
    identity=environ.get('CONTAINER_ID','')
    if not re.fullmatch('[1-9][0-9]+',identity):raise ValueError('Container identity required')
    instance=int(identity);control=Path(control)
    if (control/'guard-stop-intent.json').exists() or (control/'guard-stop-outcome.json').exists():
        raise FileExistsError('Prior one-shot fallback outcome requires review')
    hard_deadline=min(clock()+10800,HARD_CUTOFF)
    initial=read_state(control,instance,hard_deadline)
    scope_sha=initial['rental_scope_sha256']
    launched=last_busy=monotonic()
    while True:
        reason=None
        try:
            config=read_state(control,instance,hard_deadline)
            if config['rental_scope_sha256']!=scope_sha:raise ValueError('Scope changed')
            if clock()>=HARD_CUTOFF:reason='hard_deadline'
            elif clock()>=config['budget_deadline_epoch']:reason='budget_deadline'
            elif clock()>=config['deadline_epoch'] or monotonic()-launched>=10800:reason='phase_deadline'
        except (ValueError,OSError,TypeError,KeyError):reason='invalid_guard_state'
        if reason is None:
            try:
                if scan(control=control,instance=instance):last_busy=monotonic()
            except Exception:reason='process_scan_failed'
        if reason is None and monotonic()-last_busy>=IDLE_SECONDS:reason='idle'
        if reason:
            return stop(control,instance,reason,scope_sha,environ=environ,clock=clock)
        sleep(5)


if __name__=='__main__':
    try:print(json.dumps(run(),indent=2,allow_nan=False))
    except Exception as exc:raise SystemExit('Hard fallback failed: '+type(exc).__name__) from None
