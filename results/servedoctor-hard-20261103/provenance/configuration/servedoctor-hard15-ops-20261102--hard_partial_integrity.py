#!/usr/bin/env python3
"""User-authorized15-case analysis gates; original16-case study stays unchanged.

Trusted code processes opaque key/runtime bytes only for integrity and canonical
validation. It never returns answer labels, model prompts, roles or key values.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

OPS=Path(__file__).resolve().parent
REPO=OPS.parent.parent
OLD_REL='runs/servedoctor-hard-ops-20261102'
PROJECT='servedoctor-hard15-20261102'
RENTAL_PROJECT='servedoctor-hard-20261102'
LABEL='ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)'
PRIMARY='runs/sd-hard-partial-attempt1'
ORIGINAL='runs/sd-hard'
SOURCE='4b0add12be36cef0d0776607f683310b1641b0f7'
FREEZE_SHA='868fa1c8c8be1bba186937839bdeba0bebeaab7f95623c181a72f42ba0120a68'
OLD_CORE_SHA='68ba481d4c0ce457179fb5d2f69c2b33e729215052003b4e4e4ad3d548ea3933'
EXCLUSION_SHA='783ae7be7b60c35146090911ac03d854ad0e5af366c4a178685dbed670a0d1d9'
FAILURE_LOG_SHA='d4656e6cb398f67d010092509f433d316d185a1ea82063ef58c1eb5631dbae26'
PRESERVATION_SHA='0bb31a20b50ebb5db6c7680f54b22849c76cf007c9b0aa99f6d68bd4dfeb5af8'
IDS=tuple(f'hard-{i:02d}' for i in range(1,16))
ALL_IDS=('reference',)+IDS
PROTOCOL='analysis-protocol.json'
MARKER='hard-partial-validation-dispatch.json'
INPUTS=('study.json','scenarios.json','commitment.json','answers/answer_keys.json','hard-experiment-freeze.json')
HELPERS=('hard_partial_integrity.py','key_runner.py','hard_report_common.py','measure_contexts.py',
         'model_response_guard.py','export_hard_scores.py','partial_evaluation_stage.py')
OWNED=('record-first9-attempt1/00-reference/owned-observer.json','record-first9-attempt1/01-hard/owned-observer.json',
       'record-last8-attempt1/00-hard/owned-observer.json')


def require(value,reason):
    if not value:raise ValueError(reason)
def load(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def utc():return datetime.now(timezone.utc).isoformat()
def regular(path):
    path=Path(path).absolute()
    require(path.is_file() and not any(p.is_symlink() for p in (path,*path.parents)),'Regular nonlinked evidence required')
    return path
def desc(path):
    path=regular(path);return {'path':str(path),'sha256':sha(path)}
def checked(value):
    path=regular(value['path']);require(sha(path)==value['sha256'],'Evidence hash differs');return path
def write_new(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n')
def inventory(root):
    result={}
    for path in sorted(Path(root).rglob('*')):
        require(not path.is_symlink(),'Linked study evidence')
        if path.is_file():result[path.relative_to(root).as_posix()]=sha(path)
        else:require(path.is_dir(),'Nonregular study evidence')
    return result

def legacy(repo=REPO):
    path=regular(Path(repo)/OLD_REL/'hard_integrity.py');require(sha(path)==OLD_CORE_SHA,'Original frozen integrity source differs')
    spec=importlib.util.spec_from_file_location('_hard16_frozen_integrity',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def verify_source_policy(repo=REPO,expected_commit=None,baseline=None):
    require(expected_commit in (None,SOURCE),'Partial analysis source must stay4b')
    return legacy(repo).verify_source_policy(Path(repo),expected_commit=SOURCE)

def root_at(root,repo=REPO):
    root,repo=Path(root).absolute(),Path(repo).resolve()
    require(root==repo/PRIMARY and not root.is_symlink(),'Only declared partial study allowed');return root,repo

def exclusion(path):
    path=regular(path);require(sha(path)==EXCLUSION_SHA,'Exact pre-validation user authorization required');value=load(path)
    require(value.get('project')==RENTAL_PROJECT and value.get('analysis_label')==LABEL and value.get('included_hard_ids')==list(IDS)
        and value.get('excluded_ids')==['hard-16'] and value.get('reference_id')=='reference'
        and value.get('original_source_commit')==SOURCE and value.get('original_freeze_sha256')==FREEZE_SHA
        and value.get('hard16_may_be_modified_regenerated_or_rerecorded') is False
        and value.get('before_validation') is True and value.get('before_any_hard_arm_evaluation') is True
        and value.get('prompts_rules_scoring_answer_keys_unchanged') is True and value.get('native_validity_must_not_be_rewritten') is True
        and value.get('full_hard_set_claim_permitted') is False,'User exclusion policy differs')
    limits=value['limits'];require((limits.get('gpu_total_usd'),limits.get('meta_ledger_cap_usd'),limits.get('baseten_ledger_cap_usd'))==(40,50,20),'Budget caps changed')
    when=datetime.fromisoformat(value['recorded_at_utc']);require(when.tzinfo is not None,'Timestamped exclusion required')
    return value

def original(repo=REPO):
    repo=Path(repo).resolve();old=legacy(repo);root=repo/ORIGINAL
    require(sha(regular(root/'hard-experiment-freeze.json'))==FREEZE_SHA,'Original16 freeze changed')
    frozen=old.verify_freeze(root,repo);require(frozen['source_commit']==SOURCE,'Original source differs')
    old.no_decisions(root);require(not (root/'answers/validity.json').exists(),'Original16 validity must remain absent')
    require(not (root/'incidents/hard-16').exists() and not (root/'incidents/hard-16').is_symlink(),'Excluded case must remain unrecorded')
    require(sha(regular(root/'engines/engine-06-hard-16/engine.log'))==FAILURE_LOG_SHA,'Original startup failure changed')
    require({p.name for p in (root/'incidents').iterdir()}==set(ALL_IDS),'Exactly15 completed Hard plus reference required')
    return old,root,frozen

def helpers(ops):return {name:sha(regular(Path(ops)/name)) for name in HELPERS}

def prepare(root,exclusion_path,preservation_path,owned_proofs,repo=REPO):
    root,repo=root_at(root,repo);ops=repo/'runs/servedoctor-hard15-ops-20261102';ops.mkdir(exist_ok=True)
    require(not root.exists() and not root.is_symlink(),'Fresh partial directory required')
    old,origin,frozen=original(repo);authorized=exclusion(exclusion_path)
    require(datetime.now(timezone.utc)>=datetime.fromisoformat(authorized['recorded_at_utc']),'Exclusion timestamp is in the future')
    preservation=regular(preservation_path);require(sha(preservation)==PRESERVATION_SHA,'Opaque preservation receipt differs')
    require(authorized['original_preservation_receipt']['sha256']==sha(preservation),'Exclusion preservation binding differs')
    expected={repo/OLD_REL/'record-stages'/name for name in OWNED};proofs=[Path(p).absolute() for p in owned_proofs]
    require(set(proofs)==expected and len(proofs)==3,'Three original observer proofs required')
    for path in proofs:regular(path)
    frozen_helpers=helpers(ops)
    before=inventory(origin);require(not (ops/'partial-preparation-intent.json').exists(),'Preparation already dispatched; preserve partial copy')
    write_new(ops/'partial-preparation-intent.json',{'project':PROJECT,'label':LABEL,'created_at_utc':utc(),
        'original_freeze_sha256':FREEZE_SHA,'target':PRIMARY,'exclusion':desc(exclusion_path),'source_inventory_sha256':hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest()})
    shutil.copytree(origin,root)
    require(inventory(root)==before and inventory(origin)==before,'Opaque copy or original bytes changed')
    protocol={'project':PROJECT,'label':LABEL,'created_at_utc':utc(),'study_dir':PRIMARY,'original_study_dir':ORIGINAL,
        'source_commit':SOURCE,'original_freeze':desc(origin/'hard-experiment-freeze.json'),'exclusion':desc(exclusion_path),
        'preservation':desc(preservation),'included_hard_ids':list(IDS),'excluded_ids':['hard-16'],
        'original_inventory_sha256':before,'input_files_sha256':{name:before[name] for name in INPUTS},
        'private_helpers_sha256':frozen_helpers,'owned_proofs':[desc(p) for p in proofs],
        'scientific_inputs_changed':False,'old_helpers_changed':False,'reference_and_hard_recordings':16}
    write_new(root/PROTOCOL,protocol);(root/'analysis-label.txt').write_text(LABEL+'\n')
    verify_freeze(root,repo)
    return {'project':PROJECT,'label':LABEL,'prepared':True,'total':15,'protocol':desc(root/PROTOCOL),'original_unchanged':True}

def verify_freeze(root,repo=REPO):
    root,repo=root_at(root,repo);old,origin,frozen=original(repo);value=load(regular(root/PROTOCOL))
    require(value.get('project')==PROJECT and value.get('label')==LABEL and value.get('study_dir')==PRIMARY
        and value.get('original_study_dir')==ORIGINAL and value.get('source_commit')==SOURCE
        and value.get('included_hard_ids')==list(IDS) and value.get('excluded_ids')==['hard-16']
        and value.get('scientific_inputs_changed') is False,'Partial protocol differs')
    require(value['original_freeze']==desc(origin/'hard-experiment-freeze.json'),'Original freeze descriptor changed')
    authorized=exclusion(checked(value['exclusion']));checked(value['preservation'])
    require(value['preservation']['sha256']==PRESERVATION_SHA and datetime.fromisoformat(value['created_at_utc'])>=datetime.fromisoformat(authorized['recorded_at_utc']),'Authorization must precede partial protocol')
    require(inventory(origin)==value['original_inventory_sha256'],'Original16 evidence changed')
    for name,digest in value['original_inventory_sha256'].items():require(sha(regular(root/name))==digest,'Copied original byte changed')
    require(value['input_files_sha256']=={name:sha(regular(root/name)) for name in INPUTS},'Original inputs/freeze bytes changed')
    require(helpers(repo/'runs/servedoctor-hard15-ops-20261102')==value['private_helpers_sha256'],'Amended helper bytes changed')
    require({p.name for p in (root/'incidents').iterdir()}==set(ALL_IDS) and not (root/'incidents/hard-16').exists(),'Exactly excluded16 remains absent')
    require((root/'analysis-label.txt').read_text()==LABEL+'\n','Analysis label changed')
    return {**frozen,'project':PROJECT,'label':LABEL,'source_commit':SOURCE,'protocol_sha256':sha(root/PROTOCOL)}

def bytes_inventory(root):
    return {name:sha(regular(Path(root)/name)) for incident in ALL_IDS
        for name in [f'incidents/{incident}/'+v for v in ('manifest.json','engine_config.json','engine_identity.json','events.json','slo.json','telemetry.jsonl','requests.jsonl','recording.json')]+[f'answers/runtime/{incident}.json']}

def audit(root,repo=REPO):
    root,repo=root_at(root,repo);frozen=verify_freeze(root,repo);old=legacy(repo);protocol=load(root/PROTOCOL)
    declarations=[v for v in old.cases(repo/ORIGINAL) if v['id']!='hard-16'];ids=set(ALL_IDS)
    jobs=[];physical={};seen=set();full_seen=set()
    for item in protocol['owned_proofs']:
        path=checked(item);value=load(path)
        require(value.get('project')==RENTAL_PROJECT and value.get('study_dir')==ORIGINAL and value.get('source_commit')==SOURCE
            and value.get('freeze_sha256')==FREEZE_SHA and value.get('preflight_sha256')==frozen['preflight']['sha256']
            and value.get('finished') is True and not value.get('owned_leaks') and not value.get('issues'),'Original owned observer proof incomplete')
        old.verify_descriptor(value['observations']);ready=load(old.verify_descriptor(value['readiness']));selected=set(ready.get('selected_ids',[]));kept=selected-{'hard-16'}
        require(selected and selected<=ids|{'hard-16'} and not full_seen&selected and ready.get('project')==RENTAL_PROJECT
            and ready.get('source_commit')==SOURCE and ready.get('freeze_sha256')==FREEZE_SHA
            and ready.get('recorder_pid')==value.get('recorder_pid') and ready.get('recorder_start_ticks')==value.get('recorder_start_ticks')
            and ready.get('selected_incident_directories_absent') is True and ready.get('ready_before_source_job_timers') is True
            and old.physical_matches(ready.get('physical_gpu_binding'),frozen)
            and all(v.get('incident') in kept for v in value['jobs']),'Original readiness/ownership differs')
        full_seen.update(selected);seen.update(kept);jobs.extend(value['jobs']);physical.update({name:ready['physical_gpu_binding'] for name in kept})
    require(seen==ids and full_seen==ids|{'hard-16'},'Original complete observer coverage must include all16 declarations')
    rows=[old.audit_recording(root,case,frozen,{'jobs':jobs,'physical_by_incident':physical}) for case in declarations]
    require({v['id'] for v in rows}==ids and all(v['complete'] for v in rows),'Included recording infrastructure incomplete')
    return {'project':PROJECT,'label':LABEL,'created_at_utc':utc(),'complete':True,'expected_recordings':16,'hard_incidents':15,
        'excluded_ids':['hard-16'],'source_commit':SOURCE,'original_freeze_sha256':FREEZE_SHA,'protocol_sha256':sha(root/PROTOCOL),
        'recordings':rows,'owned_observer_proofs':protocol['owned_proofs'],'acceptance':'Unchanged structural/ownership checks for included recordings; only authorized unrecordable16 excluded.'}

def validity_summary(root):
    value=load(regular(Path(root)/'answers/validity.json'));rows=value.get('incidents',[])
    require(type(value.get('total')) is int and value['total']==15 and len(rows)==15 and {v.get('id') for v in rows}==set(IDS)
        and all(type(v.get('valid')) is bool for v in rows) and type(value.get('valid')) is int and value['valid']==sum(v['valid'] for v in rows),'Exactly15 one-shot native verdicts required')
    return {'total':15,'valid':value['valid'],'invalid':15-value['valid'],'validity':desc(Path(root)/'answers/validity.json')}

def validate_once(root,out,repo=REPO,run=subprocess.run):
    root,repo=root_at(root,repo);out=Path(out).absolute();ops=repo/'runs/servedoctor-hard15-ops-20261102'
    require(out.parent==ops and not out.exists(),'Fresh direct partial validation output required')
    legacy(repo).no_decisions(root)
    require(not (root/'answers/validity.json').exists() and not (root/MARKER).exists(),'Partial native validity/global dispatch already exists; never retry')
    quality=audit(root,repo);before=bytes_inventory(root);out.mkdir()
    write_new(out/'quality.json',quality)
    dispatch={'project':PROJECT,'label':LABEL,'created_at_utc':utc(),'study_dir':PRIMARY,'protocol':desc(root/PROTOCOL),
        'quality':desc(out/'quality.json'),'recording_bytes_sha256':before,'manifests':{v['id']:v['manifest_sha256'] for v in quality['recordings']}}
    write_new(out/'dispatch.json',dispatch);write_new(root/MARKER,{'project':PROJECT,'label':LABEL,'dispatch':desc(out/'dispatch.json')})
    result={'project':PROJECT,'label':LABEL,'completed':False,'returncode':None,'failure':None,'dispatch':desc(out/'dispatch.json'),'study_dispatch_sha256':sha(root/MARKER)}
    try:
        with (out/'validate.stdout').open('xb') as stdout,(out/'validate.stderr').open('xb') as stderr:
            done=run([sys.executable,'-m','servedoctor','validate','--study-dir',PRIMARY],cwd=repo,stdout=stdout,stderr=stderr)
        result['returncode']=done.returncode;require(done.returncode==0,'Native validate exited nonzero')
        verify_freeze(root,repo);require(bytes_inventory(root)==before,'Included raw/runtime bytes changed during validation')
        result.update(validity_summary(root));result['completed']=True
    except BaseException as error:result['failure']=type(error).__name__
    result.update(stdout_sha256=sha(out/'validate.stdout'),stderr_sha256=sha(out/'validate.stderr'),finished_at_utc=utc())
    write_new(out/'result.json',result);return result

def verify_evaluation(root,validation_dir,repo=REPO):
    root,repo=root_at(root,repo);frozen=verify_freeze(root,repo);directory=Path(validation_dir).absolute()
    require(directory.parent==repo/'runs/servedoctor-hard15-ops-20261102','Validation proof outside OPS15')
    marker=load(regular(root/MARKER));dispatch=load(regular(directory/'dispatch.json'));result=load(regular(directory/'result.json'))
    require(marker.get('project')==PROJECT and marker.get('label')==LABEL and marker['dispatch']==desc(directory/'dispatch.json')
        and dispatch.get('project')==PROJECT and dispatch.get('label')==LABEL and dispatch.get('study_dir')==PRIMARY
        and dispatch['protocol']==desc(root/PROTOCOL) and result.get('project')==PROJECT and result.get('label')==LABEL
        and result.get('completed') is True and result.get('returncode')==0 and not result.get('failure')
        and result['dispatch']==desc(directory/'dispatch.json') and result.get('study_dispatch_sha256')==sha(root/MARKER),'Complete immutable15 validation required')
    quality=load(checked(dispatch['quality']));require(quality.get('complete') is True and quality.get('label')==LABEL
        and quality.get('protocol_sha256')==sha(root/PROTOCOL),'Validated quality differs')
    require(bytes_inventory(root)==dispatch['recording_bytes_sha256'] and set(dispatch['manifests'])==set(ALL_IDS),'Included raw/runtime bytes changed after validation')
    require(result.get('stdout_sha256')==sha(directory/'validate.stdout') and result.get('stderr_sha256')==sha(directory/'validate.stderr'),'Canonical validation logs changed')
    current=validity_summary(root);require(all(result.get(k)==v for k,v in current.items()),'Native validity changed')
    require(dispatch['manifests']=={name:sha(root/'incidents'/name/'manifest.json') for name in ALL_IDS},'Validated manifests changed')
    for item in quality['owned_observer_proofs']:
        value=load(checked(item));checked(value['observations']);checked(value['readiness'])
    return {'project':PROJECT,'label':LABEL,'source_commit':SOURCE,'evaluation_ready':True,'total':15,
        'protocol_sha256':frozen['protocol_sha256'],'validation_sha256':sha(directory/'result.json')}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=('prepare','audit','validate-once','verify-evaluation'))
    p.add_argument('--study-dir',default=PRIMARY);p.add_argument('--out');p.add_argument('--exclusion');p.add_argument('--preservation-receipt');p.add_argument('--owned-proof',action='append')
    a=p.parse_args();root=Path(a.study_dir);root=root if root.is_absolute() else REPO/root
    if a.operation=='prepare':value=prepare(root,a.exclusion,a.preservation_receipt,a.owned_proof or [])
    elif a.operation=='audit':value=audit(root)
    elif a.operation=='validate-once':value=validate_once(root,Path(a.out) if Path(a.out).is_absolute() else REPO/a.out)
    else:value=verify_evaluation(root,Path(a.out) if Path(a.out).is_absolute() else REPO/a.out)
    print(json.dumps(value));return int(value.get('completed') is False)

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:raise SystemExit('Partial15 integrity refused: '+type(error).__name__) from None
