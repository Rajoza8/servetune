#!/usr/bin/env python3
"""Private Hard collection/validation gates. No model, network, ledger or GPU calls.

Private answer JSON is machine-processed only for commitments and PID unions;
no answer object, cause, variant, role, marker or environment value is returned.
"""
import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import inspect
import json
import math
from pathlib import Path
import re
import subprocess
import sys

OPS=Path(__file__).resolve().parent
REPO=OPS.parent.parent
sys.path.insert(0,str(REPO))
from servetune.artifacts import digest
from servedoctor.record import JOB_MODULES,engine_knobs,record_incident
from servedoctor.scenarios import make_arrivals

PROJECT='servedoctor-hard-20261102'
BASE_SOURCE='d3fe20a07ce9c687e75956200b655c5913021d49'
PRIMARY='runs/sd-hard'
REV='cec94fcfd6512f2cfe708138c32533b346ea4f69'
FREEZE='hard-experiment-freeze.json'
VALIDATION_DISPATCH='hard-validation-dispatch.json'
TRANSPORT=('api-transport.json','api-transport-receipt.json','api-transport-channel-proof.json')
PUBLIC={'engine_config.json','engine_identity.json','events.json','slo.json','telemetry.jsonl','requests.jsonl','recording.json'}
ARMS=('rules','glimmer','spark','wonder','glimmer_to_spark','glimmer_to_wonder')
SLACK=3.0  # Frozen recorder1s interval plus2s metrics scrape timeout.


def load(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def utc():return datetime.now(timezone.utc).isoformat()
def numeric(x):return type(x) in (int,float) and math.isfinite(x)
def commit(repo):return subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
def ensure_clean_scientific_source(repo):
    completed=subprocess.run(['git','diff','--quiet','HEAD','--','servedoctor','servetune','configs','docs/SERVEDOCTOR_HARD.md'],cwd=repo)
    if completed.returncode:raise ValueError('Pinned scientific/runtime source has uncommitted changes or cannot be verified')
def write_new(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n')
def regular(root,relative):
    parts=Path(relative)
    if parts.is_absolute() or '..' in parts.parts:raise ValueError('Unsafe evidence path')
    path=root/parts
    if any(root.joinpath(*parts.parts[:i]).is_symlink() for i in range(1,len(parts.parts)+1)) or not path.is_file():raise ValueError('Missing or symlink evidence')
    return path
def bytes_inventory(root):
    """Opaque evidence inventory; deliberately never returns private JSON values."""
    names=[f'incidents/{s["id"]}/manifest.json' for s in cases(root)]
    names += [f'answers/runtime/{s["id"]}.json' for s in cases(root)]
    return {name:sha(regular(root,name)) for name in names}
def descriptor(path):return {'path':str(path.resolve()),'sha256':sha(path)}
def verify_descriptor(value):
    path=Path(value['path'])
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or sha(path)!=value['sha256']:raise ValueError('Evidence descriptor differs')
    return path
def transport_inventory(root):
    present=[name for name in TRANSPORT if (root/name).exists() or (root/name).is_symlink()]
    if present and set(present)!=set(TRANSPORT):raise ValueError('Transport config/ready/channel proof must be all present or all absent before freeze')
    return {name:sha(regular(root,name)) if name in present else None for name in TRANSPORT}


def cases(root):
    payload=load(regular(root,'scenarios.json')); values=payload['scenarios']
    hard=[s for s in values if s.get('split')=='hard']; refs=[s for s in values if s.get('split')=='reference']
    expected={'hard-'+str(i).zfill(2) for i in range(1,17)}
    if (payload.get('set')!='hard' or len(hard)!=16 or {s['id'] for s in hard}!=expected
            or len(refs)!=1 or refs[0]['id']!='reference' or len(values)!=17):raise ValueError('Exactly16Hard plus reference required')
    return values


def commitments(root):
    study=load(regular(root,'study.json')); scenario=load(regular(root,'scenarios.json')); declared=load(regular(root,'commitment.json'))
    # Values remain in this process only; output is hashes/booleans, never keys.
    private=load(regular(root,'answers/answer_keys.json'))
    if (scenario.get('study_sha256')!=digest(study) or private.get('study_sha256')!=digest(study)
            or declared.get('scenarios_sha256')!=digest(scenario) or declared.get('answer_keys_sha256')!=digest(private)):
        raise ValueError('Generated commitments differ')
    expected={s['id'] for s in cases(root) if s['split']=='hard'}
    if len(private.get('answers',[]))!=16 or {v['id'] for v in private['answers']}!=expected:raise ValueError('Private commitment coverage differs')
    return {'scenarios_sha256':declared['scenarios_sha256'],'answer_keys_sha256':declared['answer_keys_sha256']}


def no_decisions(root):
    folder=root/'decisions'
    if folder.is_symlink() or (folder.exists() and any(p.is_file() or p.is_symlink() for p in folder.rglob('*'))):raise ValueError('Validation must precede every Hard decision or partial')


def preflight_policy(path,expected_commit,config_sha):
    value=load(path)
    required=('declared_before_generation','recording_ready','gpu_namespace_local_pids_verified',
              'all4_job_modules_verified','culprit_and_decoy_startup_verified')
    if (value.get('project')!=PROJECT or value.get('source_commit')!=expected_commit
            or value.get('model_revision')!=REV or value.get('config_sha256')!=config_sha
            or any(value.get(k) is not True for k in required)):
        raise ValueError('Complete pre-generation infrastructure preflight required')
    allowance=value.get('job_startup_allowance_s',value.get('startup_allowance_s'))
    if not numeric(allowance) or allowance<=0 or not numeric(value.get('observer_poll_s')) or not 0<value['observer_poll_s']<=1:
        raise ValueError('Predeclared job startup/poll policy required')
    if not re.fullmatch('[0-9a-f]{64}',value.get('rental_scope_sha256','')) or not isinstance(value.get('gpu_uuid'),str) or not value['gpu_uuid'].startswith('GPU-'):
        raise ValueError('Preflight rental scope and physical GPU identity required')
    if not isinstance(value.get('vllm_version'),str) or not value['vllm_version']:raise ValueError('Exact calibration vLLM version required')
    return {'startup_allowance_s':allowance,'observer_poll_s':value['observer_poll_s'],'namespace_verified':True,
            'rental_scope_sha256':value['rental_scope_sha256'],'gpu_uuid':value['gpu_uuid'],'vllm_version':value['vllm_version']}


def allowed_host_config_transition(old,new):
    """Only the user-approved two host KV values and prose notes may differ."""
    adjusted=copy.deepcopy(new)
    if 'notes' in old:adjusted['notes']=old['notes']
    else:adjusted.pop('notes',None)
    names={'kv-near-threshold','kv-plus-context'}
    for i,spec in enumerate(old.get('hard_incidents',[])):
        if spec.get('name') in names:
            value=adjusted['hard_incidents'][i]['engine']['gpu_memory_utilization']
            if not numeric(value) or not 0<value<1:raise ValueError('Host KV setting is not finite/in range')
            adjusted['hard_incidents'][i]['engine']['gpu_memory_utilization']=spec['engine']['gpu_memory_utilization']
    if adjusted!=old:raise ValueError('Changes exceed the two approved host KV fields and notes')


def verify_source_policy(repo=REPO,expected_commit=None,baseline=BASE_SOURCE):
    """Pre-generation source gate; never reads any study or private answer data."""
    current=commit(repo)
    if expected_commit is not None and current!=expected_commit:raise ValueError('Expected recording source HEAD differs')
    ensure_clean_scientific_source(repo)
    if current!=baseline:
        ancestor=subprocess.run(['git','merge-base','--is-ancestor',baseline,current],cwd=repo)
        changed=subprocess.check_output(['git','diff','--name-only',baseline,current],cwd=repo,text=True).splitlines()
        if ancestor.returncode or set(changed)-{'configs/servedoctor-hard.json'}:raise ValueError('Source exceeds approved Hard host config descendant')
        original=subprocess.check_output(['git','show',baseline+':configs/servedoctor-hard.json'],cwd=repo)
        allowed_host_config_transition(json.loads(original),load(repo/'configs/servedoctor-hard.json'))
    return current


def calibration_provenance(path,calibration,expected_commit,repo):
    value=load(path);origin=value.get('calibration_source_commit');old_sha=value.get('calibration_config_sha256')
    if not re.fullmatch('[0-9a-f]{40}',origin or '') or not re.fullmatch('[0-9a-f]{64}',old_sha or ''):
        raise ValueError('Honest calibration source/config origin is required')
    actual=verify_descriptor(value['actual_preflight']);bound_calibration=verify_descriptor(value['calibration'])
    if bound_calibration.resolve()!=calibration.resolve() or value['calibration']!=descriptor(calibration):raise ValueError('Calibration provenance differs from selected capacity result')
    if load(actual).get('status')!='completed':raise ValueError('Actual calibration preflight did not complete')
    if origin==expected_commit:
        original=(repo/'configs/servedoctor-hard.json').read_bytes()
    else:
        ancestor=subprocess.run(['git','merge-base','--is-ancestor',origin,expected_commit],cwd=repo)
        changed=subprocess.check_output(['git','diff','--name-only',origin,expected_commit],cwd=repo,text=True).splitlines()
        if ancestor.returncode or set(changed)-{'configs/servedoctor-hard.json'}:raise ValueError('Recording source differs from calibration beyond approved host config')
        original=subprocess.check_output(['git','show',origin+':configs/servedoctor-hard.json'],cwd=repo)
    if hashlib.sha256(original).hexdigest()!=old_sha:raise ValueError('Calibration config origin hash differs')
    allowed_host_config_transition(json.loads(original),load(repo/'configs/servedoctor-hard.json'))
    result={'source_commit':origin,'config_sha256':old_sha,'actual_preflight':descriptor(actual),
            'calibration':descriptor(calibration),'recording_source_commit':expected_commit,
            'transition':'Only approved host-specific two KV utilization fields and notes; calibration base workload/engine unchanged.'}
    if 'calibration_files_sha256' in value:
        directory=Path(value['calibration_directory'])
        if not directory.is_absolute() or directory.resolve()!=calibration.parent.resolve():raise ValueError('Calibration artifact inventory scope differs')
        inventory=value['calibration_files_sha256']
        actual_names={p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file() or p.is_symlink()}
        if actual_names!=set(inventory) or any(sha(regular(directory,name))!=h for name,h in inventory.items()):raise ValueError('Calibration output inventory changed')
        result['calibration_files_sha256']=inventory
    for name in ('calibration_engine_metadata','declaration'):
        if name in value:verify_descriptor(value[name]);result[name]=value[name]
    return result


def freeze(root,preflight,calibration,expected_commit,repo=REPO,ops=OPS,reason_receipt=None):
    relative=root.relative_to(repo).as_posix()
    if relative!=PRIMARY and not re.fullmatch(r'runs/sd-hard-[a-z0-9-]+-attempt[1-9][0-9]*',relative):raise ValueError('Unapproved study path')
    no_decisions(root)
    if (root/'answers/validity.json').exists() or (root/'incidents').exists():raise ValueError('Freeze before recording/validation')
    verify_source_policy(repo,expected_commit)
    config=repo/'configs/servedoctor-hard.json'; template=load(config); study=load(root/'study.json'); adjusted=dict(study)
    adjusted['capacity_rps']=template.get('capacity_rps')
    if adjusted!=template:raise ValueError('Scientific configuration differs from declared Hard config')
    calibrated=load(calibration)
    if calibrated.get('status')!='completed' or study.get('capacity_rps')!=calibrated.get('capacity_rps') or not study['capacity_rps']>0:
        raise ValueError('Capacity must match completed host calibration')
    policy=preflight_policy(preflight,expected_commit,sha(config)); provenance=calibration_provenance(preflight,calibration,expected_commit,repo);scientific=commitments(root)
    if relative!=PRIMARY:
        if reason_receipt is None:raise ValueError('Fresh infrastructure attempt requires an immutable reason receipt')
        reason=load(reason_receipt); original=load(repo/PRIMARY/FREEZE)
        names=('study.json','scenarios.json','commitment.json','answers/answer_keys.json')
        expected={name:original['files_sha256'][PRIMARY+'/'+name] for name in names}
        if (reason.get('project')!=PROJECT or reason.get('study_dir')!=relative or not reason.get('reason')
                or reason.get('scientific_inputs_changed') is not False or reason.get('input_files_sha256')!=expected
                or any(sha(root/name)!=h for name,h in expected.items())):raise ValueError('Infrastructure attempt changed frozen inputs')
    paths=sorted((repo/'servedoctor').rglob('*.py'))+sorted((repo/'servetune').rglob('*.py'))+[config,repo/'configs/servedoctor.json',repo/'docs/SERVEDOCTOR_HARD.md']
    paths += [root/name for name in ['study.json','scenarios.json','commitment.json','answers/answer_keys.json']]
    paths += [ops/name for name in ['hard_integrity.py','hard_job_observer.py','record_hard_stage.py','declare_hard_readiness.py','hard_recording_stage.py']]
    transport=transport_inventory(root);paths += [root/name for name,h in transport.items() if h is not None]
    result={'project':PROJECT,'created_at_utc':utc(),'study_dir':relative,'source_commit':expected_commit,
        'model_revision':REV,'scientific_commitments':scientific,'files_sha256':{p.relative_to(repo).as_posix():sha(p) for p in paths},
        'preflight':descriptor(preflight),'calibration':descriptor(calibration),'calibration_provenance':provenance,'job_policy':policy,'optional_transport_sha256':transport,
        'record_drain_timeout_s':inspect.signature(record_incident).parameters['drain_timeout_s'].default,
        'rule':'Collection integrity only; never uses SLO breaches, arm outputs or scores to accept recordings.',
        'reason_receipt':descriptor(reason_receipt) if reason_receipt else None}
    write_new(root/FREEZE,result);return result


def verify_freeze(root,repo=REPO):
    value=load(regular(root,FREEZE))
    if value.get('project')!=PROJECT or value.get('study_dir')!=root.relative_to(repo).as_posix() or commit(repo)!=value['source_commit']:
        raise ValueError('Frozen study/source identity differs')
    verify_source_policy(repo,value['source_commit'])
    for name,h in value['files_sha256'].items():
        if sha(regular(repo,name))!=h:raise ValueError('Frozen source/config/input bytes changed')
    if transport_inventory(root)!=value['optional_transport_sha256']:raise ValueError('Frozen transport presence or bytes changed')
    verify_descriptor(value['preflight']);verify_descriptor(value['calibration'])
    origin=value['calibration_provenance']
    verify_descriptor(origin['actual_preflight']);verify_descriptor(origin['calibration'])
    if calibration_provenance(Path(value['preflight']['path']),Path(value['calibration']['path']),value['source_commit'],repo)!=origin:
        raise ValueError('Calibration/recording provenance changed')
    if value.get('reason_receipt'):verify_descriptor(value['reason_receipt'])
    if commitments(root)!=value['scientific_commitments']:raise ValueError('Scientific commitments changed')
    return value


def jsonl(path):
    data=path.read_bytes().splitlines(keepends=True)
    if data and not data[-1].endswith(b'\n'):raise ValueError('Unterminated final public JSONL')
    rows=[json.loads(line) for line in data]
    if any(not isinstance(r,dict) for r in rows):raise ValueError('Non-object public row')
    return rows


def expected_arrivals(case):
    return {r['id']:(r['t'],r['cls']) for r in make_arrivals(case,{k:['public-placeholder']*48 for k in ('short','medium','long')})}


def physical_matches(binding,frozen):
    policy=frozen['job_policy']
    return (isinstance(binding,dict) and binding.get('verified') is True and binding.get('gpu_index')==0
        and binding.get('gpu_uuid')==policy['gpu_uuid'] and binding.get('rental_scope_sha256')==policy['rental_scope_sha256']
        and binding.get('container_id_matches_scope') is True and type(binding.get('instance_id')) is int
        and binding['instance_id']>0 and binding['instance_id'] not in (58690026,58716527))


def audit_recording(root,case,frozen,owned):
    folder=root/'incidents'/case['id']; issues=[]; duration=case['duration_s']
    actual={p.name for p in folder.iterdir()} if folder.is_dir() and not folder.is_symlink() else set()
    if actual!=PUBLIC|{'manifest.json'}:raise ValueError('Missing or unexpected sealed public files')
    manifest=load(regular(folder,'manifest.json'))['files']
    if set(manifest)!=PUBLIC or any(sha(regular(folder,name))!=h for name,h in manifest.items()):raise ValueError('Public recording seal differs')
    recording=load(folder/'recording.json'); identity=load(folder/'engine_identity.json')
    if recording.get('status')!='completed' or recording.get('mode')!='live' or recording.get('duration_s')!=duration:issues.append('canonical_recording_not_completed')
    physical=owned.get('physical_by_incident',{}).get(case['id']) if owned else None
    if (identity.get('model_revision')!=REV or identity.get('dtype')!=case['dtype'] or identity.get('vllm_version')!=frozen['job_policy']['vllm_version']
            or identity.get('model_id')!='meta-models/Muse-Glimmer-30B'
            or (identity.get('gpu_uuid')!=frozen['job_policy']['gpu_uuid'] and not (identity.get('gpu_uuid') is None and physical_matches(physical,frozen)))):issues.append('engine_identity_differs')
    if load(folder/'engine_config.json')!=engine_knobs(case['engine']):issues.append('engine_configuration_differs')
    if load(folder/'events.json')!=case['events'] or load(folder/'slo.json')!=case['slo']:issues.append('public_scenario_binding_differs')
    telemetry=jsonl(folder/'telemetry.jsonl'); requests=jsonl(folder/'requests.jsonl'); times=[r.get('t') for r in telemetry]
    if not times or any(not numeric(t) or t<0 for t in times):raise ValueError('Missing or invalid public telemetry time')
    gaps=[b-a for a,b in zip(times,times[1:])]
    if times[0]>SLACK or times[-1]<duration-SLACK or any(g<0 or g>SLACK for g in gaps):issues.append('incomplete_telemetry_timeline')
    if recording.get('telemetry_rows')!=len(telemetry):issues.append('telemetry_metadata_count_differs')
    expected=expected_arrivals(case); counts=Counter(r.get('id') for r in requests); invalid=[]
    for r in requests:
        terminal=isinstance(r.get('status'),str) and re.fullmatch(r'ok|shed|timeout|connection_error|error|http_[0-9]{3}',r['status'])
        timing=all(numeric(r.get(k)) and r[k]>=0 for k in ('t_sched','t_done','latency_s'))
        if timing:
            timing=r['t_done']>=r['t_sched'] and (r['latency_s']==0 if r.get('status')=='shed' else abs(r['latency_s']-(r['t_done']-r['t_sched']))<=1e-6)
        if (r.get('id') not in expected or (r.get('t_sched'),r.get('cls'))!=expected.get(r.get('id')) or not terminal or not timing):invalid.append(str(r.get('id')))
    if set(counts)!=set(expected) or any(n!=1 for n in counts.values()) or invalid:issues.append('incomplete_or_changed_scheduled_outcomes')
    last_done=max((r['t_done'] for r in requests if numeric(r.get('t_done'))),default=0)
    if times[-1]<min(last_done,duration+frozen['record_drain_timeout_s'])-SLACK:issues.append('telemetry_ends_before_observed_drain')
    job_specs=case.get('jobs',[]); supports=[r for r in telemetry if isinstance(r.get('gpu',{}).get('processes'),list) and r['gpu']['processes']]
    engine_rows=[r for r in supports if any('vllm' in str(p.get('command','')).lower() for p in r['gpu']['processes'])]
    if not engine_rows or engine_rows[-1]['t']<duration-SLACK:issues.append('engine_gpu_presence_unproven')
    proof_entries=owned.get('jobs',[]) if owned else []
    ours=[p for p in proof_entries if p.get('incident')==case['id']]
    # Runtime labels stay in process memory only; the proof never emits roles.
    runtime=load(regular(root,'answers/runtime/'+case['id']+'.json'))
    runtime_pids=set(runtime.get('contention_pids',[]))|set(runtime.get('decoy_pids',[]))
    observed_pids=set(); startup=frozen['job_policy']['startup_allowance_s']
    for index,spec in enumerate(job_specs):
        matching=[p for p in ours if p.get('job_index')==index]
        if len(matching)!=1:issues.append('owned_job_startup_unproven');continue
        p=matching[0]; pid=p.get('pid'); observed_pids.add(pid)
        if (p.get('module')!=spec['module'] or p.get('owner_marker_verified') is not True
                or not re.fullmatch('[0-9a-f]{64}',p.get('owner_marker_sha256','')) or not p.get('start_ticks')
                or p.get('uid')!=0 or p.get('parent_verified') is not True or p.get('cwd_verified') is not True):
            issues.append('owned_job_identity_unproven')
        seen=[r['t'] for r in supports if any(v.get('pid')==pid and spec['module'] in str(v.get('command','')) for v in r['gpu']['processes'])]
        if not seen or seen[0]>spec['onset_s']+startup or seen[-1]<duration-SLACK:issues.append('job_gpu_liveness_unproven')
        elif any(not any(v.get('pid')==pid for v in r['gpu']['processes']) for r in supports if seen[0]<=r['t']<=duration):issues.append('job_exited_before_nominal_end')
        if (p.get('last_public_t',-1)<duration-SLACK or p.get('first_public_t',duration)>spec['onset_s']+startup
                or not numeric(p.get('max_public_gap_s')) or p['max_public_gap_s']>SLACK+frozen['job_policy']['observer_poll_s']
                or p.get('observations',0)<2):issues.append('owned_job_liveness_unproven')
    if runtime_pids!=observed_pids or len(ours)!=len(job_specs):issues.append('runtime_job_pid_union_differs')
    if recording.get('telemetry_errors') or recording.get('cleanup_errors') or recording.get('failure'):issues.append('collector_or_cleanup_failure')
    if any(re.search(r'Errno\s*24|EMFILE|too many open files',str(line),re.I) for r in telemetry for line in r.get('log',[])):issues.append('resource_failure_in_public_log')
    if any(sha(regular(folder,name))!=h for name,h in manifest.items()):raise ValueError('Public bytes changed during quality audit')
    return {'id':case['id'],'complete':not issues,'issues':sorted(set(issues)),'manifest_sha256':sha(folder/'manifest.json'),
        'duration_s':duration,'telemetry':{'rows':len(times),'first_s':times[0],'last_s':times[-1],'max_gap_s':max(gaps,default=None)},
        'outcomes':{'expected':len(expected),'observed':len(requests),'invalid_terminal_or_timing':len(invalid)},
        'job_count':len(job_specs),'owned_and_gpu_job_presence_verified':not any('job' in s for s in issues)}


def audit(root,owned_proofs,repo=REPO):
    frozen=verify_freeze(root,repo); declared=cases(root); ids={s['id'] for s in declared}
    if (root/'incidents').is_symlink() or {p.name for p in (root/'incidents').iterdir()}!=ids:raise ValueError('All17 exact public recording directories required')
    owned_jobs=[]; descriptors=[];observed_ids=set();physical_by_incident={}
    for path in owned_proofs:
        value=load(path)
        if (value.get('project')!=PROJECT or value.get('study_dir')!=root.relative_to(repo).as_posix()
                or value.get('source_commit')!=frozen['source_commit'] or value.get('freeze_sha256')!=sha(root/FREEZE)
                or value.get('preflight_sha256')!=frozen['preflight']['sha256']
                or value.get('finished') is not True or value.get('owned_leaks') or value.get('issues')):raise ValueError('Owned observer proof incomplete')
        verify_descriptor(value['observations'])
        ready=load(verify_descriptor(value['readiness']));selected=set(ready.get('selected_ids',[]))
        if (ready.get('project')!=PROJECT or ready.get('source_commit')!=frozen['source_commit']
                or ready.get('freeze_sha256')!=sha(root/FREEZE) or not selected or not selected<=ids
                or observed_ids&selected or ready.get('recorder_pid')!=value.get('recorder_pid')
                or ready.get('recorder_start_ticks')!=value.get('recorder_start_ticks')
                or ready.get('selected_incident_directories_absent') is not True or ready.get('ready_before_source_job_timers') is not True
                or not physical_matches(ready.get('physical_gpu_binding'),frozen)
                or any(p.get('incident') not in selected for p in value['jobs'])):raise ValueError('Observer did not prove readiness before selected recording timers')
        observed_ids.update(selected)
        physical_by_incident.update({name:ready['physical_gpu_binding'] for name in selected})
        owned_jobs.extend(value['jobs']);descriptors.append(descriptor(path))
    if observed_ids!=ids:raise ValueError('Every reference/Hard recording needs an early-ready observer proof')
    rows=[]
    for case in declared:
        try:rows.append(audit_recording(root,case,frozen,{'jobs':owned_jobs,'physical_by_incident':physical_by_incident}))
        except (OSError,ValueError,KeyError,TypeError) as exc:rows.append({'id':case['id'],'complete':False,'issues':[type(exc).__name__]})
    return {'project':PROJECT,'created_at_utc':utc(),'study_dir':root.relative_to(repo).as_posix(),'source_commit':frozen['source_commit'],
        'freeze_sha256':sha(root/FREEZE),'expected_recordings':17,'complete':all(r['complete'] for r in rows),
        'recordings':rows,'owned_observer_proofs':descriptors,'acceptance':'Infrastructure/coverage only; never filters by SLO or arm performance.'}


def validity_summary(root):
    value=load(regular(root,'answers/validity.json')); entries=value.get('incidents',[]); expected={s['id'] for s in cases(root) if s['split']=='hard'}
    if (type(value.get('total')) is not int or value['total']!=16 or type(value.get('valid')) is not int
            or len(entries)!=16 or {r.get('id') for r in entries}!=expected
            or any(type(r.get('valid')) is not bool for r in entries) or value.get('valid')!=sum(r['valid'] for r in entries)):
        raise ValueError('One-shot validity must contain exactly16 unique boolean verdicts')
    return {'total':16,'valid':value['valid'],'invalid':16-value['valid'],'exact_coverage_verified':True,
            'validity':descriptor(root/'answers/validity.json')}


def validate_once(root,owned_proofs,out,repo=REPO,run=subprocess.run):
    no_decisions(root)
    if (root/'answers/validity.json').exists() or (root/VALIDATION_DISPATCH).exists():raise ValueError('Immutable validation dispatch or validity already exists; never retry/rewrite')
    report=audit(root,owned_proofs,repo)
    if not report['complete']:raise ValueError('Infrastructure completeness failed; preserve attempt and require a fresh directory/reason')
    out.mkdir(exist_ok=False);write_new(out/'quality.json',report)
    dispatch={'project':PROJECT,'created_at_utc':utc(),'study_dir':root.relative_to(repo).as_posix(),
        'freeze_sha256':sha(root/FREEZE),'quality':descriptor(out/'quality.json'),
        'manifests':{r['id']:r['manifest_sha256'] for r in report['recordings']},'recording_bytes_sha256':bytes_inventory(root)}
    write_new(out/'dispatch.json',dispatch)
    # A study-global exclusive marker prevents retry under a different --out,
    # including after an unknown subprocess/controller outcome.
    write_new(root/VALIDATION_DISPATCH,{'project':PROJECT,'created_at_utc':utc(),'dispatch':descriptor(out/'dispatch.json')})
    result={'project':PROJECT,'completed':False,'returncode':None,'failure':None,'dispatch_sha256':sha(out/'dispatch.json'),
            'study_dispatch_sha256':sha(root/VALIDATION_DISPATCH)}
    try:
        with (out/'validate.stdout').open('xb') as stdout,(out/'validate.stderr').open('xb') as stderr:
            completed=run([sys.executable,'-m','servedoctor','validate','--study-dir',root.relative_to(repo).as_posix()],cwd=repo,stdout=stdout,stderr=stderr)
        result['returncode']=completed.returncode
        if completed.returncode:raise RuntimeError('Canonical validate exited nonzero')
        verify_freeze(root,repo)
        if bytes_inventory(root)!=dispatch['recording_bytes_sha256']:raise ValueError('Recording or opaque runtime bytes changed during validation')
        if {r['id']:sha(root/'incidents'/r['id']/'manifest.json') for r in report['recordings']}!=dispatch['manifests']:raise ValueError('Recording manifests changed during validation')
        result.update(validity_summary(root));result['completed']=True
    except BaseException as exc:result['failure']=type(exc).__name__
    result.update(finished_at_utc=utc(),stdout_sha256=sha(out/'validate.stdout'),stderr_sha256=sha(out/'validate.stderr'))
    write_new(out/'result.json',result);return result


def verify_evaluation(root,validation_dir,repo=REPO):
    verify_freeze(root,repo);dispatch=load(validation_dir/'dispatch.json');result=load(validation_dir/'result.json')
    marker=load(regular(root,VALIDATION_DISPATCH));verify_descriptor(marker['dispatch'])
    expected={s['id'] for s in cases(root)}
    if (dispatch.get('project')!=PROJECT or dispatch.get('study_dir')!=root.relative_to(repo).as_posix()
            or set(dispatch.get('manifests',{}))!=expected or marker.get('project')!=PROJECT
            or marker['dispatch']!=descriptor(validation_dir/'dispatch.json')
            or result.get('study_dispatch_sha256')!=sha(root/VALIDATION_DISPATCH)
            or result.get('project')!=PROJECT or result.get('completed') is not True or result.get('returncode')!=0
            or result.get('failure') or result.get('dispatch_sha256')!=sha(validation_dir/'dispatch.json')
            or dispatch.get('freeze_sha256')!=sha(root/FREEZE)):raise ValueError('Complete immutable validation required')
    verify_descriptor(dispatch['quality']);verify_descriptor(result['validity'])
    quality=load(dispatch['quality']['path'])
    if quality.get('complete') is not True or quality.get('freeze_sha256')!=sha(root/FREEZE):raise ValueError('Validated collection quality proof differs')
    for entry in quality['owned_observer_proofs']:
        proof=load(verify_descriptor(entry));verify_descriptor(proof['observations']);verify_descriptor(proof['readiness'])
    if bytes_inventory(root)!=dispatch['recording_bytes_sha256']:raise ValueError('Validated recording/runtime bytes changed')
    if sha(validation_dir/'validate.stdout')!=result['stdout_sha256'] or sha(validation_dir/'validate.stderr')!=result['stderr_sha256']:raise ValueError('Canonical validation logs changed')
    current=validity_summary(root)
    if any(result.get(k)!=current[k] for k in current):raise ValueError('Validity proof changed')
    for name,h in dispatch['manifests'].items():
        folder=root/'incidents'/name;manifest=load(regular(folder,'manifest.json'))['files']
        if sha(folder/'manifest.json')!=h or any(sha(regular(folder,f))!=v for f,v in manifest.items()):raise ValueError('Validated public data changed')
    return {'project':PROJECT,'evaluation_ready':True,'validation_sha256':sha(validation_dir/'result.json'),'total':16}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('operation',choices=['freeze','audit','validate-once','verify-evaluation'])
    parser.add_argument('--study-dir',type=Path,default=Path(PRIMARY));parser.add_argument('--preflight',type=Path);parser.add_argument('--calibration',type=Path)
    parser.add_argument('--expected-commit');parser.add_argument('--reason-receipt',type=Path);parser.add_argument('--owned-proof',type=Path,action='append',default=[]);parser.add_argument('--out',type=Path)
    args=parser.parse_args();root=(REPO/args.study_dir).resolve()
    if not root.is_relative_to(REPO/'runs'):parser.error('Study must stay under this repository runs directory')
    if args.operation=='freeze':
        if not all([args.preflight,args.calibration,args.expected_commit]):parser.error('Freeze needs preflight, calibration and expected source commit')
        freeze(root,args.preflight.resolve(),args.calibration.resolve(),args.expected_commit,reason_receipt=args.reason_receipt)
        print(json.dumps({'frozen':True,'freeze_sha256':sha(root/FREEZE)}));return
    if args.out is None:parser.error('Use an explicit private OPS output path')
    out=args.out.absolute()
    if not out.is_relative_to(OPS):parser.error('Output must be under private Hard OPS')
    if args.operation=='audit':
        value=audit(root,args.owned_proof);write_new(out,value);print(json.dumps({'complete':value['complete'],'report_sha256':sha(out)}))
    elif args.operation=='validate-once':
        value=validate_once(root,args.owned_proof,out);print(json.dumps({k:value.get(k) for k in ['completed','returncode','failure','total','valid','invalid']}));return int(not value['completed'])
    else:print(json.dumps(verify_evaluation(root,out)))


if __name__=='__main__':sys.exit(main())
