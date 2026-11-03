#!/usr/bin/env python3
"""Local, selective packaging of the explicitly approved fifteen-case Hard analysis. Default verifies; --create copies once.

Trusted scorer/collection functions process private bytes in memory. Only safe
counts and hashes are emitted. No network, model, rental, ledger mutation,
source modification or subprocess carrying credentials is performed.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

OPS=Path(__file__).resolve().parent;REPO=OPS.parent.parent
sys.path.insert(0,str(REPO))
import hard_partial_integrity as gate
import export_hard_scores as exporter
import model_response_guard as responses
from hard_report_common import LABEL, RENTAL_PROJECT
require_new_namespace = (Path(gate.__file__).resolve().parent == OPS
                         and Path(exporter.__file__).resolve().parent == OPS
                         and Path(responses.__file__).resolve().parent == OPS)
if not require_new_namespace:raise ImportError('Only frozen OPS15 verification/report helpers may be imported')
sys.path.append(str(REPO/'runs/servedoctor-hard-ops-20261102'))
import hard_vast
legacy = gate.legacy(REPO)
from servedoctor.scoring import score_study

PROJECT='servedoctor-hard15-20261102'
HEAD='4b0add12be36cef0d0776607f683310b1641b0f7'
CONFIG='0cc70e7ec4cbb0b26c6e13a4b9311dedf6dd05a862d9c0d9d2934ec25a017014'
FREEZE='868fa1c8c8be1bba186937839bdeba0bebeaab7f95623c181a72f42ba0120a68'
INSTANCE=58866756
SCOPE='c941c466f1e56180a66c6ebe98972c8507c4fa94bee6b3c96a419e3e6eed0b4c'
GPU='GPU-ced6c24c-2234-f9e6-4b0f-6b11b82f9681'
SEED='13f777ed328bb0c71bb2063b6b12cf3b6cb8024d78b0ab46b9e374521a566123'
V0=25.90010443543525
REMOTE='/workspace/servedoctor-hard/servetune';CONTROL='/workspace/servedoctor-hard/control'
OPS_REL='runs/servedoctor-hard15-ops-20261102'
OLD_OPS_REL='runs/servedoctor-hard-ops-20261102'
PRIMARY='runs/sd-hard-partial-attempt1'
ORIGINAL='runs/sd-hard'
CORE='eca7c03250aa7b75439ce9b6505c648d4584c3f5fbdba48b341d42ab78b813c5'
EXCLUSION='783ae7be7b60c35146090911ac03d854ad0e5af366c4a178685dbed670a0d1d9'
PRESERVATION='0bb31a20b50ebb5db6c7680f54b22849c76cf007c9b0aa99f6d68bd4dfeb5af8'
FAILURE_LOG='d4656e6cb398f67d010092509f433d316d185a1ea82063ef58c1eb5631dbae26'
ORIGINAL_FILE_COUNT=178
ORIGINAL_FAILURE_INDEX='0212d304fff313a3053e7ce31da942ce113b4a8ab9b0e24cd786b382b4c3ad67'
BACKUP_MUTABLE={'session.json','active-command.json','operation.lock','servedoctor-gpu-hours.md'}
PROTOCOL_HELPERS=('hard_partial_integrity.py','key_runner.py','hard_report_common.py','measure_contexts.py',
                  'model_response_guard.py','export_hard_scores.py','partial_evaluation_stage.py')
IDS=tuple(f'hard-{n:02d}' for n in range(1,16));ALL_IDS=('reference',)+IDS
ARMS=exporter.ARMS
GROUPS={'calibration','kv-refinement','configuration','environment','api-prices','api-access','rental-history','failures','tests','finalization'}
DENY_NAMES={'session.json','known_hosts','active-command.json','operation.lock','key_runner.py','.env','credentials.json','token','token.json'}
DENY_PARTS={'.git','.ssh','__pycache__','.venv','venv','site-packages','node_modules','.hf_home','.vllm_cache','payload','upload','prepare-uploads'}
DENY_SUFFIX={'.pem','.key','.sock','.safetensors','.bin','.pt','.pth','.onnx','.tar','.gz','.zip','.pyc'}
EXTENSIONS={'.json','.jsonl','.log','.html','.md','.txt','.stdout','.stderr','.py','.toml'}
SECRETS=[re.compile(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----'),re.compile(rb'(?i)Bearer\s+[a-z0-9_\-./+=]{16,}'),
 re.compile(rb'(?i)(?:MODEL_API_KEY|META_API_KEY|BASETEN_API_KEY|HF_TOKEN|CONTAINER_API_KEY)["\s]*[:=]["\s]*[a-z0-9_\-./+=]{16,}')]


class PackageError(ValueError):pass
def require(value,code):
    if not value:raise PackageError(code)
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def load(path):return json.loads(Path(path).read_text())
def numeric(value):return type(value) in (int,float) and math.isfinite(value) and value>=0
def desc(path):return {'path':str(Path(path).resolve()),'sha256':sha(path)}
def write_new(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())


class Evidence:
    def __init__(self,args,repo=REPO):
        self.repo=Path(repo).resolve();self.ops=self.repo/OLD_OPS_REL;self.partial_ops=self.repo/OPS_REL;self.study=Path(args.study_dir).resolve();self.original=Path(args.original_study_dir).resolve()
        self.remote_ops=Path(args.remote_old_ops).resolve();self.partial_remote_ops=Path(args.remote_ops).resolve();self.control=Path(args.remote_control).resolve()
        self.calibration=Path(args.calibration_mirror).resolve();self.dependencies={};self.fingerprints={}
        self.mappings=[(REMOTE+'/'+OPS_REL,self.partial_remote_ops),(REMOTE+'/'+OLD_OPS_REL,self.remote_ops),
            (CONTROL,self.control),(REMOTE+'/'+PRIMARY,self.study),(REMOTE+'/'+ORIGINAL,self.original)]
    def regular(self,path):
        path=Path(os.path.abspath(path));require(path.is_relative_to(self.repo),'outside-repository-evidence')
        relative=path.relative_to(self.repo)
        require(all(not self.repo.joinpath(*relative.parts[:i]).is_symlink() for i in range(1,len(relative.parts)+1)),'linked-evidence')
        require(path.is_file(),'missing-regular-evidence')
        digest=sha(path);require(path not in self.fingerprints or self.fingerprints[path]==digest,'evidence-changed-during-gates')
        self.fingerprints.setdefault(path,digest);return path
    def resolve(self,value):
        value=str(value);path=None
        require(Path(value).is_absolute() and '..' not in Path(value).parts,'unsafe-original-descriptor-path')
        for prefix,target in self.mappings:
            if value==prefix or value.startswith(prefix+'/'):path=target/Path(value).relative_to(prefix);break
        if path is None and value.startswith(REMOTE+'/'):
            relative=Path(value).relative_to(REMOTE)
            path=self.calibration/relative if str(relative).startswith('runs/sd-hard-calibration-') else self.repo/relative
        if path is None:path=Path(value)
        return self.regular(path)
    def descriptor(self,value):
        require(isinstance(value,dict) and re.fullmatch('[a-f0-9]{64}',value.get('sha256','')) is not None,'invalid-descriptor')
        path=self.resolve(value['path']);require(sha(path)==value['sha256'],'descriptor-hash-differs')
        self.dependencies[str(value['path'])]=path;return path
    def descriptors(self,value):
        if isinstance(value,dict):
            if {'path','sha256'}<=set(value):self.descriptor(value)
            for item in value.values():self.descriptors(item)
        elif isinstance(value,list):
            for item in value:self.descriptors(item)
    def frozen_file(self,relative):return self.resolve(REMOTE+'/'+relative)


def verify_repository(repo):
    require(subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()==HEAD,'experiment-source-head-differs')
    gate.verify_source_policy(repo,HEAD)
    require(not subprocess.check_output(['git','diff','--name-only','7bb1483deb4c2a801bb397883a4086df8379393b','HEAD','--','servetune','results/20261030'],cwd=repo,text=True).strip(),'protected-v4-differs')


def verify_freeze(evidence):
    root=evidence.original;path=evidence.regular(root/legacy.FREEZE)
    require(sha(path)==FREEZE,'original-freeze-hash-differs');frozen=load(path)
    require(frozen.get('project')==RENTAL_PROJECT and frozen.get('source_commit')==HEAD
            and frozen.get('study_dir')==ORIGINAL,'original-frozen-identity-differs')
    require(sha(evidence.repo/'configs/servedoctor-hard.json')==CONFIG,'config-hash-differs')
    require(frozen['job_policy'].get('gpu_uuid')==GPU and frozen['job_policy'].get('rental_scope_sha256')==SCOPE,'frozen-hardware-differs')
    for relative,digest in frozen['files_sha256'].items():require(sha(evidence.frozen_file(relative))==digest,'original-frozen-file-differs')
    require(sha(legacy.__file__)==frozen['files_sha256'][OLD_OPS_REL+'/hard_integrity.py'],'original-collection-verifier-source-differs')
    require(legacy.transport_inventory(root)==frozen['optional_transport_sha256'],'original-frozen-transport-differs')
    require(legacy.commitments(root)==frozen['scientific_commitments'],'original-scientific-commitment-differs')
    require(not (root/'answers/validity.json').exists() and not (root/'decisions').exists(),'original-attempt-was-validated-or-evaluated')
    require(not (root/'incidents/hard-16').exists(),'original-excluded-case-was-recorded')
    require(sha(evidence.regular(root/'engines/engine-06-hard-16/engine.log'))==FAILURE_LOG,'original-hard16-failure-differs')
    evidence.descriptors({k:frozen.get(k) for k in ('preflight','calibration','calibration_provenance','reason_receipt')})
    ready=load(evidence.descriptor(frozen['preflight']));evidence.descriptors(ready)
    require(ready.get('recording_ready') is True and ready.get('declared_before_generation') is True
            and ready.get('source_commit')==HEAD and ready.get('config_sha256')==CONFIG
            and ready.get('gpu_uuid')==GPU and ready.get('rental_scope_sha256')==SCOPE,'recording-readiness-differs')
    require(sha(gate.__file__)==CORE,'partial-verifier-source-differs')
    protocol=load(evidence.regular(evidence.study/gate.PROTOCOL))
    require(protocol.get('project')==PROJECT and protocol.get('label')==LABEL and protocol.get('source_commit')==HEAD
            and protocol.get('study_dir')==PRIMARY and protocol.get('original_study_dir')==ORIGINAL
            and protocol.get('included_hard_ids')==list(IDS) and protocol.get('excluded_ids')==['hard-16']
            and protocol.get('scientific_inputs_changed') is False and protocol.get('old_helpers_changed') is False
            and protocol.get('reference_and_hard_recordings')==16,'partial-analysis-protocol-differs')
    require(evidence.descriptor(protocol['original_freeze'])==path,'partial-original-freeze-binding-differs')
    exclusion_path=evidence.descriptor(protocol['exclusion']);why=load(exclusion_path)
    require(sha(exclusion_path)==EXCLUSION and why.get('project')==RENTAL_PROJECT and why.get('analysis_label')==LABEL
            and why.get('included_hard_ids')==list(IDS) and why.get('excluded_ids')==['hard-16']
            and why.get('reference_id')=='reference' and why.get('original_source_commit')==HEAD
            and why.get('original_freeze_sha256')==FREEZE and why.get('before_validation') is True
            and why.get('before_any_hard_arm_evaluation') is True and why.get('prompts_rules_scoring_answer_keys_unchanged') is True
            and why.get('hard16_may_be_modified_regenerated_or_rerecorded') is False
            and why.get('native_validity_must_not_be_rewritten') is True and why.get('full_hard_set_claim_permitted') is False,'predeclared-exclusion-differs')
    limits=why.get('limits',{});require((limits.get('gpu_total_usd'),limits.get('meta_ledger_cap_usd'),limits.get('baseten_ledger_cap_usd'))==(40,50,20),'amendment-budget-limits-differ')
    preservation=evidence.descriptor(protocol['preservation'])
    require(sha(preservation)==PRESERVATION and why.get('original_preservation_receipt',{}).get('sha256')==PRESERVATION,'original-preservation-binding-differs')
    authorized=datetime.fromisoformat(why['recorded_at_utc']);created=datetime.fromisoformat(protocol['created_at_utc'])
    require(authorized.tzinfo is not None and created.tzinfo is not None and created>=authorized,'exclusion-did-not-precede-analysis')
    mapping=protocol['original_inventory_sha256']
    actual={p.relative_to(root).as_posix():sha(evidence.regular(p)) for p in root.rglob('*') if p.is_file()}
    require(len(mapping)==ORIGINAL_FILE_COUNT and actual==mapping,'original-attempt-inventory-differs')
    for name,digest in mapping.items():
        require(not Path(name).is_absolute() and '..' not in Path(name).parts,'unsafe-original-inventory-path')
        require(sha(evidence.regular(evidence.study/name))==digest,'copied-original-byte-differs')
    require(protocol['input_files_sha256']=={name:sha(evidence.regular(evidence.study/name)) for name in gate.INPUTS},'copied-scientific-inputs-differ')
    require(set(protocol['private_helpers_sha256'])==set(PROTOCOL_HELPERS),'partial-helper-inventory-differs')
    for name,digest in protocol['private_helpers_sha256'].items():
        require(sha(evidence.regular(evidence.partial_ops/name))==digest
                and sha(evidence.frozen_file(OPS_REL+'/'+name))==digest,'partial-helper-source-differs')
    require((evidence.study/'analysis-label.txt').read_text()==LABEL+'\n','partial-study-label-differs')
    require({p.name for p in (evidence.study/'incidents').iterdir()}==set(ALL_IDS),'partial-recording-directory-set-differs')
    return frozen

def verify_validation(evidence,frozen):
    root=evidence.study;protocol=load(root/gate.PROTOCOL);protocol_sha=sha(root/gate.PROTOCOL)
    marker=load(evidence.regular(root/gate.MARKER));directory=evidence.descriptor(marker['dispatch']).parent
    dispatch=load(evidence.regular(directory/'dispatch.json'));result=load(evidence.regular(directory/'result.json'))
    require(marker.get('project')==PROJECT and marker.get('label')==LABEL
            and dispatch.get('project')==PROJECT and dispatch.get('label')==LABEL and dispatch.get('study_dir')==PRIMARY
            and evidence.descriptor(dispatch['protocol'])==evidence.regular(root/gate.PROTOCOL)
            and result.get('project')==PROJECT and result.get('label')==LABEL and result.get('completed') is True
            and result.get('returncode')==0 and not result.get('failure')
            and evidence.descriptor(result['dispatch'])==directory/'dispatch.json'
            and result.get('study_dispatch_sha256')==sha(root/gate.MARKER),'immutable-partial-validation-differs')
    require(datetime.fromisoformat(dispatch['created_at_utc'])>=datetime.fromisoformat(protocol['created_at_utc']),'validation-precedes-amendment')
    require(set(dispatch['manifests'])==set(ALL_IDS),'partial-validation-coverage-differs')
    quality=load(evidence.descriptor(dispatch['quality']))
    require(quality.get('project')==PROJECT and quality.get('label')==LABEL and quality.get('complete') is True
            and quality.get('original_freeze_sha256')==FREEZE and quality.get('protocol_sha256')==protocol_sha
            and quality.get('expected_recordings')==16 and quality.get('hard_incidents')==15
            and quality.get('excluded_ids')==['hard-16'],'partial-quality-report-incomplete')
    require(len(quality['recordings'])==16 and {r['id'] for r in quality['recordings']}==set(ALL_IDS)
            and all(r.get('complete') is True and not r.get('issues') for r in quality['recordings']),'partial-quality-coverage-differs')
    for name in ('stdout','stderr'):require(sha(evidence.regular(directory/('validate.'+name)))==result[name+'_sha256'],'validation-stream-differs')
    value=load(evidence.descriptor(result['validity']));validity=gate.validity_summary(root)
    require(all(result.get(k)==v for k,v in validity.items() if k!='validity'),'partial-validity-counts-differ')
    require(sha(root/'answers/validity.json')==result['validity']['sha256'],'partial-validity-hash-differs')
    require(gate.bytes_inventory(root)==dispatch['recording_bytes_sha256'],'validated-runtime-or-raw-byte-differs')
    valid={r['id'] for r in value['incidents'] if r['valid']};owned={'jobs':[],'physical_by_incident':{}};seen=set();full_seen=set()
    require(quality['owned_observer_proofs']==protocol['owned_proofs'],'owned-proof-protocol-binding-differs')
    for item in quality['owned_observer_proofs']:
        path=evidence.descriptor(item);proof=load(path);ready=load(evidence.descriptor(proof['readiness']));evidence.descriptor(proof['observations'])
        selected=set(ready['selected_ids']);kept=selected-{'hard-16'}
        require(proof.get('project')==RENTAL_PROJECT and proof.get('study_dir')==ORIGINAL
                and proof.get('finished') is True and not proof.get('owned_leaks') and not proof.get('issues')
                and proof.get('source_commit')==HEAD and proof.get('freeze_sha256')==FREEZE
                and proof.get('preflight_sha256')==frozen['preflight']['sha256'] and ready.get('project')==RENTAL_PROJECT
                and ready.get('source_commit')==HEAD and ready.get('freeze_sha256')==FREEZE
                and ready.get('selected_incident_directories_absent') is True and ready.get('ready_before_source_job_timers') is True
                and selected and selected<=set(ALL_IDS)|{'hard-16'} and not selected&full_seen
                and all(v.get('incident') in kept for v in proof['jobs'])
                and ready.get('recorder_pid')==proof.get('recorder_pid') and ready.get('recorder_start_ticks')==proof.get('recorder_start_ticks')
                and legacy.physical_matches(ready.get('physical_gpu_binding'),frozen),'owned-partial-recording-proof-differs')
        for name in ('record-identity.json','observer-identity.json'):
            identity=load(evidence.regular(path.parent/name))
            require(identity.get('uid')==0 and identity.get('cwd')==REMOTE and identity.get('fd_soft')==65536
                    and type(identity.get('fd_hard')) is int and identity['fd_hard']>=65536,'child-fd-identity-differs')
        # The failed hard-16 startup is intentionally retained; its containing
        # phase is not relabelled successful. Included captures are audited below.
        evidence.regular(path.parent/'phase-exit.json')
        full_seen.update(selected);seen.update(kept);owned['jobs'].extend(proof['jobs'])
        owned['physical_by_incident'].update({n:ready['physical_gpu_binding'] for n in kept})
    require(seen==set(ALL_IDS) and full_seen==set(ALL_IDS)|{'hard-16'},'owned-partial-recording-coverage-differs')
    records=[]
    for case in legacy.cases(evidence.original):
        if case['id']=='hard-16':continue
        row=legacy.audit_recording(root,case,frozen,owned);require(row['complete'],'included-final-structural-audit-failed')
        require(row['manifest_sha256']==dispatch['manifests'][case['id']],'validated-manifest-differs');records.append(row)
    require(len(records)==16,'included-structural-case-count-differs')
    return {'valid_ids':valid,'validation_dir':directory,'quality':quality,'recordings':records,'protocol':protocol}

def verify_scores(evidence,args,validation):
    root=evidence.study;expected={(a,n) for a in ARMS for n in IDS}
    require({p.name for p in (root/'decisions').iterdir()}==set(ARMS),'decision-arm-directory-set-differs')
    for arm in ARMS:require({p.name for p in (root/'decisions'/arm).iterdir()}=={n+'.json' for n in IDS},'missing-extra-or-partial-decisions')
    usage=responses.audit_model_group(root,list(ARMS));require(usage['ready_for_next_group'],'genuine-response-gate-failed')
    evaluation=Path(args.evaluation_dir);outcome=load(evidence.regular(evaluation/'outcome.json'))
    require(outcome.get('project')==PROJECT and outcome.get('label')==LABEL and outcome.get('completed') is True and not outcome.get('failure') and not outcome.get('cleanup_errors')
            and outcome.get('groups')==['rules-spark-wonder','glimmer-cascades'],'evaluation-stage-incomplete')
    context=load(evidence.regular(evaluation/'contexts.json'))
    require(context.get('project')==PROJECT and context.get('label')==LABEL and context.get('helper_sha256')==sha(evidence.partial_ops/'measure_contexts.py')
            and context.get('fits_8192') is True and context.get('incidents')==15 and context.get('context_tokens')==8192
            and context.get('model_revision')==legacy.REV and context.get('freeze_sha256')==FREEZE
            and set(context.get('per_incident_maximum',{}))==set(IDS),'context-proof-differs')
    require(context['public_manifests_sha256']=={n:sha(root/'incidents'/n/'manifest.json') for n in ALL_IDS},'context-seals-differ')
    for peaks in context['per_incident_maximum'].values():
        require(set(peaks)=={'diagnosis','monitor'},'context-kinds-differ')
        for kind,item in peaks.items():
            require(item.get('output_budget_tokens')==({'diagnosis':2048,'monitor':600}[kind])
                    and type(item.get('input_tokens')) is int and item['input_tokens']>0
                    and item.get('total_tokens')==item['input_tokens']+item['output_budget_tokens']
                    and item['total_tokens']<=8192,'context-token-proof-differs')
    for name,arms in [('rules-spark-wonder-responses.json',ARMS[:1]+ARMS[2:4]),('glimmer-cascades-responses.json',(ARMS[1],ARMS[4],ARMS[5]))]:
        saved=load(evidence.regular(evaluation/name));actual=responses.audit_model_group(root,list(arms))
        require(saved.get('project')==PROJECT and saved.get('label')==LABEL and saved.get('helper_sha256')==sha(evidence.partial_ops/'model_response_guard.py')
                and saved.get('ready_for_next_group') is True and saved.get('by_arm')==actual['by_arm'],'response-proof-differs')
    # Only trusted functions process labels/model text; project strips them before
    # the result can enter a log, README or tool output.
    decoys={n for n in IDS if load(root/'answers/runtime'/f'{n}.json').get('decoy_pids')}
    all_scores=score_study(root,split='hard');valid_scores=score_study(root,split='hard',valid_only=True)
    projected=exporter.project(all_scores,valid_scores,validation['valid_ids'],decoys)
    safe=load(evidence.regular(args.score_projection))
    require(all(safe.get(k)==v for k,v in projected.items()),'canonical-safe-score-projection-differs')
    require(safe.get('helper_sha256')==sha(evidence.partial_ops/'export_hard_scores.py') and safe.get('freeze_sha256')==FREEZE and safe.get('validity_sha256')==sha(root/'answers/validity.json'),'score-proof-inputs-differ')
    require(safe.get('final_decisions_sha256')=={a:{n:sha(root/'decisions'/a/(n+'.json')) for n in IDS} for a in ARMS},'score-decision-hashes-differ')
    for label,key in [('all','all'),('valid_only','valid_only')]:
        require(load(evidence.regular(evaluation/('final-score-'+label+'.stdout')))==projected['scoreboards'][key],'canonical-cli-scoreboard-differs')
    require({(r['arm'],r['id']) for r in safe['per_case']}==expected,'safe-per-case-coverage-differs')
    mirror=load(evidence.regular(evaluation/'mirror-manifest.json'))
    captured={p.relative_to(root).as_posix():sha(p) for p in study_files(evidence)}
    require(mirror.get('stable') is True and mirror.get('study_files_sha256')==captured
            and mirror.get('study_file_count')==len(captured) and mirror.get('ledger_sha256')==sha(args.ledger)
            and outcome.get('opaque_mirror',{}).get('manifest_sha256')==sha(evaluation/'mirror-manifest.json'),'stable-full-study-ledger-mirror-differs')
    return {'projection':safe,'usage':usage,'context':context}


def verify_reports(evidence,args,scores):
    root=evidence.study;projected=scores['projection']
    native=load(evidence.regular(root/'report.json'))
    require(native.get('by_arm')==projected['scoreboards']['all']
            and native.get('by_arm_valid_only')==projected['scoreboards']['valid_only'],'native-report-scoreboards-differ')
    wrapped=load(evidence.regular(root/'analysis-report.json'))
    require(wrapped.get('project')==PROJECT and wrapped.get('label')==LABEL
            and wrapped.get('scoreboards')==projected['scoreboards']
            and wrapped.get('denominators')==projected['denominators'],'labelled-analysis-report-differs')
    for key,name in [('native_report_json','report.json'),('native_report_html','report.html')]:
        require(evidence.descriptor(wrapped[key])==evidence.regular(root/name),'native-report-wrapper-hash-differs')
    require(sha(evidence.descriptor(wrapped['score_projection']))==sha(args.score_projection),'wrapper-score-projection-differs')
    html=evidence.regular(root/'analysis-report.html').read_text()
    require(LABEL in html and 'src="report.html"' in html,'labelled-html-entry-differs')


def ledger_summary(path,seed):
    data=load(path);old=load(seed)
    require(sha(seed)==SEED and data.get('project')=='servedoctor' and data.get('caps_usd')=={'meta':'50','baseten':'20'},'ledger-caps-or-seed-differs')
    entries=data['entries'];require(entries[:len(old['entries'])]==old['entries'],'inherited-ledger-history-differs')
    require(len({r['id'] for r in entries})==len(entries),'duplicate-ledger-entry')
    totals={p:sum((Decimal(r['accounted_usd']) for r in entries if r['provider']==p),Decimal(0)) for p in ('meta','baseten')}
    require(all(v.is_finite() and 0<=v<=Decimal(data['caps_usd'][p]) for p,v in totals.items()),'ledger-cap-or-numeric-error')
    require(all(r.get('provider') in totals and r.get('status') in ('reserved','settled','overrun')
                and Decimal(r['accounted_usd']).is_finite() and Decimal(r['accounted_usd'])>=0 for r in entries),'ledger-entry-differs')
    return {'caps_usd':{'meta':50.0,'baseten':20.0},'accounted_usd':{p:float(v) for p,v in totals.items()},
            'warnings':[p+' at or above 50% of its cap' for p,v in totals.items() if v>=Decimal(data['caps_usd'][p])/2],
            'calls':len(entries)}


def verify_rental_accounting(evidence,cleanup):
    # No provider function is reachable from this read-only service. Its
    # existing immutable history verifier checks versions, prefix, baseline,
    # scopes, closed/nonoverlapping intervals and every finalized host cost.
    def blocked(*args,**kwargs):raise PackageError('provider-operation-forbidden')
    service=hard_vast.Rental(root=evidence.ops,repo=evidence.repo,api=blocked,inventory=blocked)
    evidence.descriptor(service.baseline())
    documents=service.history_documents();history=service.history()
    require(len(documents)==4 and len(history)==4,'four-prior-hard-rentals-required')
    totals={'running_hours':0.,'compute_usd_upper':0.,'disk_usd_upper':0.};last=0.
    for path,value in documents:evidence.descriptor(desc(path))
    for item in history:
        receipt=load(evidence.descriptor(item['receipt']));old=load(evidence.descriptor(receipt['final_state']))
        evidence.descriptor(receipt['rental_scope']);last=old['destroyed_epoch']
        for key in totals:totals[key]+=receipt['host_cost'][key]
    state=load(evidence.descriptor(cleanup['final_state']))
    require(state.get('project')==RENTAL_PROJECT and state.get('instance_id')==INSTANCE and state.get('scope_sha256')==SCOPE
            and state.get('destroyed_epoch')==cleanup['destroyed_epoch'] and state.get('prior_hard_hosts')==history
            and state.get('created_epoch',-1)>=last and not state.get('pending_intent')
            and state.get('running_intervals') and all('stop_epoch' in row for row in state['running_intervals']),'final-rental-billing-state-differs')
    own=hard_vast.Rental.host_cost(state,state['destroyed_epoch'])
    for key in totals:totals[key]+=own[key]
    cost=cleanup['gpu_accounting']
    require(all(abs(cost[public]-totals[key])<1e-8 for public,key in [('hard_running_hours','running_hours'),
        ('hard_compute_usd_upper','compute_usd_upper'),('hard_disk_usd_upper','disk_usd_upper')]),'final-rental-cost-does-not-recompute')
    require(cost['new_network_reserve_usd']==hard_vast.NETWORK and cost['new_slack_reserve_usd']==hard_vast.SLACK,'network-slack-reserve-differs')
    require(backup_stop(cleanup,evidence)==state['running_intervals'][-1]['stop_epoch'],'backup-last-stop-differs')


def backup_stop(cleanup,evidence):return load(evidence.descriptor(cleanup['backup_receipt'])).get('last_stop_epoch')


def verify_cleanup(evidence,args):
    cleanup=load(evidence.regular(args.cleanup_evidence));ledger=evidence.regular(args.ledger);hours=evidence.regular(args.hours)
    require(cleanup.get('project')==RENTAL_PROJECT and cleanup.get('analysis_project')==PROJECT and cleanup.get('label')==LABEL
            and cleanup.get('excluded_ids')==['hard-16'] and cleanup.get('instance_id')==INSTANCE and cleanup.get('rental_scope_sha256')==SCOPE
            and cleanup.get('confirmed_absent') is True and cleanup.get('stopped_confirmed') is True
            and cleanup.get('owned_work_quiescent') is True and numeric(cleanup.get('destroyed_epoch')),'final-cleanup-incomplete')
    require(cleanup.get('canonical_ledger_sha256')==cleanup.get('remote_ledger_sha256')==sha(ledger)
            and cleanup.get('gpu_hours_log_sha256')==sha(hours),'final-ledger-or-hours-differs')
    require(sha(evidence.descriptor(cleanup['authorization']))==EXCLUSION
            and sha(evidence.descriptor(cleanup['original_preservation']))==PRESERVATION,'cleanup-amendment-binding-differs')
    summary=ledger_summary(ledger,evidence.regular(args.ledger_seed));require(cleanup.get('ledger_summary')==summary,'final-ledger-summary-differs')
    intent=load(evidence.descriptor(cleanup['delete_intent']));outcome=load(evidence.descriptor(cleanup['delete_outcome']))
    reconciled=load(evidence.descriptor(cleanup['delete_reconciliation']));backup=load(evidence.descriptor(cleanup['backup_receipt']))
    for value in (intent,outcome):require(value.get('operation')=='delete' and value.get('method')=='DELETE'
        and value.get('instance_id')==INSTANCE and value.get('rental_scope_sha256')==SCOPE
        and value.get('path')==f'/api/v0/instances/{INSTANCE}/','delete-intent-scope-differs')
    require(outcome.get('phase') in ('response','unknown_outcome') and reconciled.get('instance_id')==INSTANCE
            and outcome.get('requested_epoch')==intent.get('requested_epoch')
            and reconciled.get('destroyed_epoch')==cleanup['destroyed_epoch'] and not reconciled.get('pending_intent'),'delete-not-get-confirmed')
    status=reconciled.get('status',{})
    require(status.get('actual_status') in ('stopped','exited') and status.get('cur_state') in ('stopped','exited')
            and status.get('intended_status')!='running','stopped-before-delete-unproven')
    require(backup.get('project')==RENTAL_PROJECT and backup.get('analysis_project')==PROJECT and backup.get('label')==LABEL
            and backup.get('excluded_ids')==['hard-16'] and backup.get('original_frozen_incidents')==16
            and backup.get('completed_hard_incidents')==15 and backup.get('final_decisions')==90
            and backup.get('instance_id')==INSTANCE and backup.get('rental_scope_sha256')==SCOPE
            and backup.get('all_remote_artifacts_backed_up') is True,'pre-delete-backup-incomplete')
    require(numeric(backup.get('last_stop_epoch')) and numeric(intent.get('requested_epoch'))
            and backup['last_stop_epoch']<=intent['requested_epoch']<=cleanup['destroyed_epoch'],'delete-backup-timeline-differs')
    require(sha(evidence.descriptor(backup['authorization']))==EXCLUSION
            and sha(evidence.descriptor(backup['original_preservation']))==PRESERVATION,'pre-delete-amendment-binding-differs')
    ready=load(evidence.descriptor(backup['readiness']))
    require(ready.get('project')==RENTAL_PROJECT and ready.get('analysis_project')==PROJECT and ready.get('label')==LABEL
            and ready.get('ready') is True and ready.get('recordings')==16 and ready.get('hard_incidents')==15
            and ready.get('final_decisions')==90 and ready.get('original_freeze_sha256')==FREEZE
            and ready.get('canonical_ledger_sha256')==ready.get('remote_ledger_sha256')==sha(ledger)
            and ready.get('ledger_summary')==summary,'pre-delete-readiness-differs')
    parent=load(evidence.descriptor(ready['pipeline_outcome']))
    require(parent.get('project')==RENTAL_PROJECT and parent.get('instance_id')==INSTANCE
            and parent.get('rental_scope_sha256')==SCOPE and parent.get('returncode')==0
            and parent.get('stop_confirmed') is True and parent.get('cleanup_confirmed') is True
            and not parent.get('watchdog_cleanup_error_class'),'final-parent-not-stopped-or-quiescent')
    require(sha(evidence.descriptor(ready['evaluation_outcome']))==sha(Path(args.evaluation_dir)/'outcome.json'),'backup-evaluation-outcome-differs')
    final=load(evidence.descriptor(ready['final_remote_ledger_proof']))
    require(final.get('sha256')==sha(ledger) and final.get('summary')==summary,'final-GPU-ledger-proof-differs')
    manifest=load(evidence.descriptor(backup['evidence_manifest']));base=Path(manifest['root']);verified=set()
    for name,digest in manifest['files'].items():
        require(not Path(name).is_absolute() and '..' not in Path(name).parts,'unsafe-backup-manifest-path')
        path=evidence.regular(base/name);require(sha(path)==digest,'pre-delete-backup-file-differs');verified.add(path)
    analysis=study_files(evidence)
    if any(p not in verified for p in analysis) and evidence.study==evidence.partial_ops/'final-study':
        canonical=evidence.repo/PRIMARY
        mirrored={p.relative_to(evidence.study).as_posix():sha(p) for p in analysis}
        backed={}
        for path in canonical.rglob('*'):
            require(not path.is_symlink(),'linked-canonical-analysis-copy')
            if path.is_file():
                require(evidence.regular(path) in verified,'canonical-analysis-copy-not-backed-up')
                backed[path.relative_to(canonical).as_posix()]=sha(path)
        require(backed==mirrored,'canonical-analysis-copy-byte-differs')
    else:require(all(p in verified for p in analysis),'full-study-not-backed-up')
    require(all(p in verified for p in original_files(evidence)),'full-study-not-backed-up')
    for folder in (evidence.remote_ops,evidence.partial_remote_ops,evidence.control):
        for path in folder.rglob('*'):
            require(not path.is_symlink(),'linked-final-mirror')
            if path.is_file() and path.name not in BACKUP_MUTABLE and not path.name.endswith('.tmp'):
                require(evidence.regular(path) in verified,'stable-final-OPS-mirror-not-backed-up')
    scope=evidence.regular(evidence.ops/'rental-scope.json');require(scope in verified and sha(scope)==SCOPE,'backup-scope-missing')
    require(evidence.descriptor(backup['gpu_hours_snapshot']) in verified,'immutable-pre-delete-hours-not-backed-up')
    canonical=backup['canonical_ledger'];require(canonical['sha256']==canonical['remote_sha256']==sha(ledger)
        and evidence.descriptor({'path':canonical['path'],'sha256':canonical['sha256']}) in verified,'backup-ledger-differs')
    cost=cleanup['gpu_accounting']
    keys=('prior_v0_usd_upper','hard_running_hours','hard_compute_usd_upper','hard_disk_usd_upper','new_network_reserve_usd','new_slack_reserve_usd','total_usd_upper')
    require(all(numeric(cost.get(k)) for k in keys) and cost['prior_v0_usd_upper']==V0,'fixed-gpu-accounting-fields-differ')
    total=sum(cost[k] for k in keys if k not in ('hard_running_hours','total_usd_upper'))
    require(abs(total-cost['total_usd_upper'])<1e-8 and total<=40,'fixed-gpu-total-over-cap-or-double-counted')
    verify_rental_accounting(evidence,cleanup)
    require(sha(evidence.resolve(CONTROL+'/rental-scope.json'))==SCOPE,'final-control-scope-differs')
    return cleanup


def study_files(evidence):
    result=[]
    for path in sorted(evidence.study.rglob('*')):
        require(not path.is_symlink(),'linked-study-file')
        if path.is_file():result.append(evidence.regular(path))
        else:require(path.is_dir(),'special-study-file')
    return result


def original_files(evidence):
    result=[]
    for path in sorted(evidence.original.rglob('*')):
        require(not path.is_symlink(),'linked-original-attempt-file')
        if path.is_file():result.append(evidence.regular(path))
        else:require(path.is_dir(),'special-original-attempt-file')
    require(len(result)==ORIGINAL_FILE_COUNT,'original-attempt-file-count-differs')
    return result


def scan(path):
    require(path.name not in DENY_NAMES and not path.name.startswith(('.env','ssh_ed25519','gemma_vast_pilot_ed25519'))
            and not set(path.parts)&DENY_PARTS and path.suffix not in DENY_SUFFIX and path.suffix in EXTENSIONS,'private-or-unreviewed-package-file')
    tail=b''
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            value=tail+block;require(not any(pattern.search(value) for pattern in SECRETS),'credential-pattern-in-selected-file');tail=value[-4096:]


def reviewed_files(evidence,args,frozen,validation):
    files={};source_hashes={};destinations={}
    def add(source,target):
        source=evidence.regular(source);target=Path(target)
        require(not target.is_absolute() and '..' not in target.parts,'unsafe-package-destination');scan(source)
        key=target.as_posix();require(key not in files or files[key]==source,'overlapping-package-destinations')
        files[key]=source;source_hashes[key]=sha(source);destinations[str(source)]=key
    for path in study_files(evidence):add(path,Path('analysis')/path.relative_to(evidence.study))
    for path in original_files(evidence):add(path,Path('original-frozen-attempt')/path.relative_to(evidence.original))
    for name in ('study.json','scenarios.json','commitment.json','answers/answer_keys.json','report.json','report.html',
                 'analysis-protocol.json','analysis-label.txt','analysis-report.json','analysis-report.html'):
        require('analysis/'+name in files,'required-labelled-study-artifact-missing')
    for relative in frozen['files_sha256']:
        if relative.startswith(('servedoctor/','servetune/','configs/','docs/')):add(evidence.frozen_file(relative),'source/'+relative)
        elif relative.startswith(OLD_OPS_REL+'/'):add(evidence.frozen_file(relative),'provenance/helpers/original/'+Path(relative).name)
    protocol=validation['protocol']
    for name in PROTOCOL_HELPERS:
        # The credential-handling worker is hash-bound by the public analysis
        # protocol; its private launcher source is not recursively published.
        if name!='key_runner.py':add(evidence.partial_ops/name,'provenance/helpers/analysis/'+name)
    provenance=load(evidence.regular(args.provenance));require(provenance.get('project')==PROJECT and provenance.get('label')==LABEL and isinstance(provenance.get('files'),list),'explicit-provenance-manifest-required')
    groups=set()
    targets=set()
    for row in provenance['files']:
        require(row.get('group') in GROUPS and str(row['destination']).startswith('provenance/'),'provenance-group-or-target-differs')
        require(row['destination'] not in targets,'duplicate-provenance-destination');targets.add(row['destination'])
        add(evidence.descriptor(row['source']),row['destination']);groups.add(row['group'])
    require(groups==GROUPS,'required-provenance-groups-missing')
    failure_path=evidence.descriptor(provenance['failure_index']);failure=load(failure_path)
    require(failure.get('project')==PROJECT and failure.get('label')==LABEL and failure.get('finalized') is True
            and isinstance(failure.get('failures'),list) and failure['failures'],'failure-index-missing')
    original_failure=evidence.descriptor(failure['original_failure_index']);prior=load(original_failure)
    require(sha(original_failure)==ORIGINAL_FAILURE_INDEX and failure.get('retained_original_entries')==18
            and len(prior.get('failures',[]))==18 and len(failure['failures'])>=21
            and failure['failures'][:18]==prior['failures'],'original-failure-history-differs')
    add(original_failure,'provenance/failures/original-full-protocol-failure-index-draft.json')
    for row in failure['failures']:
        require(all(isinstance(row.get(k),str) and row[k] for k in ('id','category','summary','reason')) and row.get('artifacts'),'failure-index-row-incomplete')
        for item in row['artifacts']:require(str(evidence.descriptor(item)) in destinations,'failure-artifact-not-published')
    add(failure_path,'provenance/failures/failure-index.json')
    # Dependencies discovered from original absolute descriptors get deterministic
    # mirrored paths; originals are never rewritten or followed outside the repo.
    for original,path in list(evidence.dependencies.items()):
        if str(path) in destinations:continue
        if path.is_relative_to(evidence.partial_remote_ops):target='provenance/remote-ops15/'+path.relative_to(evidence.partial_remote_ops).as_posix()
        elif path.is_relative_to(evidence.remote_ops):target='provenance/remote-ops/'+path.relative_to(evidence.remote_ops).as_posix()
        elif path.is_relative_to(evidence.control):target='provenance/control/'+path.relative_to(evidence.control).as_posix()
        else:target='provenance/dependencies/'+path.relative_to(evidence.repo).as_posix()
        add(path,target)
    for name in ('record-identity.json','observer-identity.json','phase-exit.json'):
        for item in validation['quality']['owned_observer_proofs']:
            path=evidence.descriptor(item).parent/name
            add(path,'provenance/remote-ops/'+path.relative_to(evidence.remote_ops).as_posix())
    for source,target in [(args.ledger,'ledger.json'),(args.hours,'servedoctor-gpu-hours.md'),(args.cleanup_evidence,'final-cleanup.json'),
        (args.score_projection,'provenance/scoring/hard15-score-projection-final.json'),(args.provenance,'provenance/published-allowlist.json'),(args.readme,'README.md'),
        (__file__,'provenance/helpers/package_partial_results.py')]:add(source,target)
    # Include exact evaluation proofs and canonical boards, never their enclosing
    # OPS tree or raw authenticated/credential-bearing worker state.
    for name in ('outcome.json','contexts.json','rules-spark-wonder-responses.json','glimmer-cascades-responses.json',
                 'final-score-all.stdout','final-score-all.stderr','final-score-valid_only.stdout','final-score-valid_only.stderr',
                 'mirror-manifest.json','final-ledger.stdout'):
        add(Path(args.evaluation_dir)/name,'provenance/evaluation/'+name)
    mapping={original:{'package_path':destinations[str(path)],'sha256':sha(path)} for original,path in evidence.dependencies.items()}
    return files,source_hashes,mapping


def execute(args,*,repo=REPO,repository_check=verify_repository):
    evidence=Evidence(args,repo);repository_check(evidence.repo)
    require(evidence.study in (evidence.repo/PRIMARY,evidence.partial_ops/'final-study'),'declared-partial-study-mirror-required')
    before={str(p):sha(p) for p in study_files(evidence)}
    frozen=verify_freeze(evidence);validation=verify_validation(evidence,frozen);scores=verify_scores(evidence,args,validation)
    verify_reports(evidence,args,scores)
    cleanup=verify_cleanup(evidence,args);files,hashes,mapping=reviewed_files(evidence,args,frozen,validation)
    readme=Path(args.readme).read_text()
    require(not re.search(r'\bPENDING\b|\bTODO\b|\bTBD\b|\{\{',readme,re.I),'unfinished-readme')
    require(HEAD in readme and FREEZE in readme and LABEL in readme and 'analysis/analysis-report.html' in readme,'readme-source-freeze-label-entry-missing')
    require(before=={str(p):sha(p) for p in study_files(evidence)},'study-changed-during-package-gates')
    require(all(sha(path)==digest for path,digest in evidence.fingerprints.items()),'evidence-changed-after-gates')
    out=Path(args.out).resolve();require(out==evidence.repo/'results/servedoctor-hard-20261103','fixed-fresh-hard-destination-required')
    require(not out.exists(),'package-destination-already-exists')
    report={'project':PROJECT,'label':LABEL,'verified':True,'created':False,'source_commit':HEAD,'config_sha256':CONFIG,'freeze_sha256':FREEZE,
        'recordings':16,'sealed_payloads':112,'final_decisions':90,'original_frozen_attempt_files':ORIGINAL_FILE_COUNT,'original_frozen_incidents':16,'excluded_ids':['hard-16'],'valid_cases':len(validation['valid_ids']),
        'files':len(files)+1,'ledger_sha256':sha(args.ledger),'gpu_total_usd_upper':cleanup['gpu_accounting']['total_usd_upper']}
    if not args.create:return report
    out.mkdir(parents=True,exist_ok=False)
    try:
        for relative,source in files.items():
            require(sha(source)==hashes[relative],'source-changed-before-copy');target=out/relative;target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as destination,source.open('rb') as stream:shutil.copyfileobj(stream,destination)
            require(sha(target)==hashes[relative],'copied-file-hash-differs')
        index={'project':PROJECT,'label':LABEL,'created_at_utc':datetime.now(timezone.utc).isoformat(),'experiment_source_commit':HEAD,'analysis_entry':'analysis/analysis-report.html',
            'original_frozen_attempt_files':ORIGINAL_FILE_COUNT,'excluded_ids':['hard-16'],
            'publication_commit':'A subsequent repository commit; the experiment freeze is not restamped.',
            'original_descriptor_to_package':mapping,'private_bytes':'Answers, raw decisions and native reports are opaque artifacts; only trusted scorer projections may enter model prompts.'}
        write_new(out/'artifact-index.json',index);hashes['artifact-index.json']=sha(out/'artifact-index.json')
        require(all(sha(out/name)==digest for name,digest in hashes.items()),'package-post-copy-verification-failed')
        manifest={'project':PROJECT,'label':LABEL,'created_at_utc':datetime.now(timezone.utc).isoformat(),'source_commit':HEAD,'config_sha256':CONFIG,
            'freeze_sha256':FREEZE,'files':hashes,'source_paths':{name:str(path.relative_to(evidence.repo)) for name,path in files.items()},
            'helper_sha256':sha(__file__),'scope':'Labelled fifteen-case analysis, exact original frozen attempt and explicitly reviewed evidence; no recursive operations backups.'}
        write_new(out/'package-manifest.json',manifest);return {**report,'created':True,'destination':str(out),'manifest_sha256':sha(out/'package-manifest.json')}
    except BaseException as error:
        write_new(out/'package-failure.json',{'project':PROJECT,'label':LABEL,'failure_class':type(error).__name__,
            'gate':str(error) if isinstance(error,PackageError) else None,'partial_package_retained':True});raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study-dir',default=str(OPS/'final-study'))
    p.add_argument('--original-study-dir',default=str(REPO/OLD_OPS_REL/'blocked-hard-study-attempt1/latest/study'))
    p.add_argument('--remote-ops',default=str(OPS/'final-remote-ops'))
    p.add_argument('--remote-old-ops',default=str(OPS/'final-remote-old-ops'))
    p.add_argument('--remote-control',default=str(OPS/'final-remote-control'))
    p.add_argument('--calibration-mirror',default=str(REPO/OLD_OPS_REL/'bootstrap-calibration-controller-attempt8/mirror'))
    p.add_argument('--ledger',default=str(OPS/'evaluation-attempt1/final-canonical-ledger.json'))
    p.add_argument('--ledger-seed',default=str(REPO/OLD_OPS_REL/'prepare-next-attempt1/upload/ledger.seed'))
    p.add_argument('--hours',default=str(REPO/'runs/servedoctor-gpu-hours.md'))
    p.add_argument('--out',default=str(REPO/'results/servedoctor-hard-20261103'))
    for name in ('score-projection','evaluation-dir','cleanup-evidence','provenance','readme'):p.add_argument('--'+name,required=True)
    p.add_argument('--create',action='store_true');args=p.parse_args()
    try:print(json.dumps(execute(args)));return 0
    except Exception as error:
        print(json.dumps({'project':PROJECT,'label':LABEL,'verified':False,'created':False,'failure_class':type(error).__name__,
            'gate':str(error) if isinstance(error,PackageError) else None}));return 1


if __name__=='__main__':sys.exit(main())
