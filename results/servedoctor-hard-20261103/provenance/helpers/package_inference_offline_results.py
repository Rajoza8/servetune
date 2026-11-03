#!/usr/bin/env python3
"""Local, selective packaging after the exact post-evaluation copy failure. Default verifies; --create copies once.

Trusted scorer/collection functions process private bytes in memory. Only safe
counts and hashes are emitted. No network, model, rental, ledger mutation,
source modification or subprocess carrying credentials is performed.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal
import hashlib
import importlib.util
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
sys.path.insert(0,str(OPS))
# The finalizer also imports historical helpers with the same short module
# names. Bind this new adapter's preserved P helpers explicitly; source files
# and historical module objects held by their callers remain unchanged.
for _name in ('hard_report_common','hard_partial_integrity','model_response_guard','export_hard_scores'):
    _path=OPS/(_name+'.py');_loaded=sys.modules.get(_name)
    if _loaded is None or Path(getattr(_loaded,'__file__','')).resolve()!=_path.resolve():
        _spec=importlib.util.spec_from_file_location(_name,_path);_module=importlib.util.module_from_spec(_spec)
        sys.modules[_name]=_module;_spec.loader.exec_module(_module)
import inference_integrity as gate
import inference_export_scores as exporter
import inference_response_guard as responses
from inference_report_common import LABEL, RENTAL_PROJECT
require_new_namespace = (Path(gate.__file__).resolve().parent == OPS
                         and Path(exporter.__file__).resolve().parent == OPS
                         and Path(responses.__file__).resolve().parent == OPS)
if not require_new_namespace:raise ImportError('Only frozen OPS15 verification/report helpers may be imported')
sys.path.append(str(REPO/'runs/servedoctor-hard-ops-20261102'))
import inference_vast as hard_vast
legacy = gate.p.legacy
from servedoctor.scoring import score_study

PROJECT='servedoctor-hard15-20261102'
HEAD='4b0add12be36cef0d0776607f683310b1641b0f7'
CONFIG='0cc70e7ec4cbb0b26c6e13a4b9311dedf6dd05a862d9c0d9d2934ec25a017014'
FREEZE='868fa1c8c8be1bba186937839bdeba0bebeaab7f95623c181a72f42ba0120a68'
INSTANCE=58905385
SCOPE='7da4c657be8e5e6bf971e5e017a24b02385d6c0f3221daa20ae64e7eb7cedce7'
GPU='GPU-ced6c24c-2234-f9e6-4b0f-6b11b82f9681'
SEED='13f777ed328bb0c71bb2063b6b12cf3b6cb8024d78b0ab46b9e374521a566123'
V0=25.90010443543525
REMOTE='/workspace/servedoctor-hard/servetune';CONTROL='/workspace/servedoctor-hard/control'
OPS_REL='runs/servedoctor-hard15-ops-20261102'
OLD_OPS_REL='runs/servedoctor-hard-ops-20261102'
PRIMARY='runs/sd-hard-partial-attempt1'
ORIGINAL='runs/sd-hard'
CORE='2a564fcea530f2d1005a0e68924024b11b56ae35dd9ab8655b75867a9bbb37e4'
AMENDMENT='8efba5368ca146e45ff55d16fb45567058ae015bcee51a26a5510a0e31c4ee2a'
PRIOR_END=37.552391290596844
RECORD_INSTANCE=58866756
RECORD_SCOPE='c941c466f1e56180a66c6ebe98972c8507c4fa94bee6b3c96a419e3e6eed0b4c'
EXCLUSION='783ae7be7b60c35146090911ac03d854ad0e5af366c4a178685dbed670a0d1d9'
PRESERVATION='0bb31a20b50ebb5db6c7680f54b22849c76cf007c9b0aa99f6d68bd4dfeb5af8'
FAILURE_LOG='d4656e6cb398f67d010092509f433d316d185a1ea82063ef58c1eb5631dbae26'
ORIGINAL_FILE_COUNT=178
ORIGINAL_FAILURE_INDEX='0212d304fff313a3053e7ce31da942ce113b4a8ab9b0e24cd786b382b4c3ad67'
PRIOR_PARTIAL_FAILURE_INDEX='3f120a18a7cee0b1d867464da84374fd8de1d42abb3e02cded85daa7cc9dc057'
BACKUP_MUTABLE={'session.json','active-command.json','operation.lock','servedoctor-gpu-hours.md'}
PROTOCOL_HELPERS=gate.HELPERS
IDS=tuple(f'hard-{n:02d}' for n in range(1,16));ALL_IDS=('reference',)+IDS
ARMS=exporter.ARMS
GROUPS={'calibration','kv-refinement','configuration','environment','api-prices','api-access','rental-history','failures','tests','finalization'}
DENY_NAMES={'session.json','known_hosts','active-command.json','operation.lock','key_runner.py','inference_key_runner.py','.env','credentials.json','token','token.json'}
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
        self.mappings=[(REMOTE+'/'+OLD_OPS_REL+'/record-stages/record-first9-attempt1',self.partial_remote_ops/'portable-recording-evidence/first9-proofs/recording-stage'),
            (REMOTE+'/'+OLD_OPS_REL+'/record-stages/record-last8-attempt1',self.partial_remote_ops/'portable-recording-evidence/latest/recording-stage'),
            (REMOTE+'/'+OPS_REL,self.partial_remote_ops),(REMOTE+'/'+OLD_OPS_REL,self.remote_ops),
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



# Isolated path-transport adapter only; original verifier and reports unchanged.
import inference_descriptor_adapter as descriptor_adapter
import inference_offline_recovery_gate as offline_recovery
require(sha(descriptor_adapter.__file__)=='fdaf66af25327c4501c8e66b2fa56708600d4c4acc8b5585a32724d3b5f0ae91','descriptor-adapter-source-differs')
require(sha(offline_recovery.__file__)=='625eeabd3035ac61f70b25409df1a227cd479138155d12a441af17f4ab28db2c','offline-recovery-gate-source-differs')
Evidence=descriptor_adapter.Evidence
PackageError=descriptor_adapter.base.PackageError
OFFLINE_FINALIZER_SHA='309faa6208e0cc414d295e99a51ac12b8a4997a846fab4f590af314c803de223'


def verify_offline_policy(e,c,backup,readiness):
    recovered=offline_recovery.verify_recovery(repo=e.repo,receipt_path=e.descriptor(c['offline_recovery_receipt']))
    for value in (c,backup,readiness):
        require(value.get('all_required_scientific_artifacts_backed_up') is True
           and value.get('all_remote_artifacts_backed_up') is False
           and value.get('remote_ops_control_tail_unverified') is True,'honest-offline-backup-scope-required')
        for key in ('original_failed_pipeline_outcome','offline_recovery_receipt'):
            require(value.get(key)==recovered[key],'offline-recovery-lineage-differs')
            e.descriptor(value[key])
    require(readiness.get('pipeline_outcome')==recovered['pipeline_outcome'],'original-failed-parent-not-preserved')
    require(e.descriptor(c['offline_recovery_adapter'])==e.partial_ops/'finalize_inference_offline_rental_v2.py'
       and sha(e.descriptor(c['offline_recovery_adapter']))==OFFLINE_FINALIZER_SHA
       and c['offline_recovery_adapter']==readiness.get('offline_recovery_adapter'),'offline-finalizer-adapter-differs')
    require(readiness.get('input_verification')==recovered['input_verification'],'offline-scientific-verification-differs')
    return recovered


def verify_repository(repo):
    require(subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()==HEAD,'experiment-source-head-differs')
    gate.verify_source_policy(repo,HEAD)
    require(not subprocess.check_output(['git','diff','--name-only','7bb1483deb4c2a801bb397883a4086df8379393b','HEAD','--','servetune','results/20261030'],cwd=repo,text=True).strip(),'protected-v4-differs')




def verify_scores(evidence,args,validation):
    root=evidence.study;expected={(a,n) for a in ARMS for n in IDS}
    require({p.name for p in (root/'decisions').iterdir()}==set(ARMS),'decision-arm-directory-set-differs')
    for arm in ARMS:require({p.name for p in (root/'decisions'/arm).iterdir()}=={n+'.json' for n in IDS},'missing-extra-or-partial-decisions')
    usage=responses.audit_model_group(root,list(ARMS));require(usage['ready_for_next_group'],'genuine-response-gate-failed')
    evaluation=Path(args.evaluation_dir);outcome=load(evidence.regular(evaluation/'outcome.json'))
    require(outcome.get('project')==PROJECT and outcome.get('label')==LABEL and outcome.get('completed') is True and not outcome.get('failure') and not outcome.get('cleanup_errors')
            and outcome.get('groups')==['rules-spark-wonder','glimmer-cascades'],'evaluation-stage-incomplete')
    context=load(evidence.regular(evaluation/'contexts.json'))
    require(context.get('project')==PROJECT and context.get('label')==LABEL and context.get('helper_sha256')==sha(evidence.partial_ops/'inference_measure_contexts.py')
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
        require(saved.get('project')==PROJECT and saved.get('label')==LABEL and saved.get('helper_sha256')==sha(evidence.partial_ops/'inference_response_guard.py')
                and saved.get('ready_for_next_group') is True and saved.get('by_arm')==actual['by_arm'],'response-proof-differs')
    # Only trusted functions process labels/model text; project strips them before
    # the result can enter a log, README or tool output.
    decoys={n for n in IDS if load(root/'answers/runtime'/f'{n}.json').get('decoy_pids')}
    all_scores=score_study(root,split='hard');valid_scores=score_study(root,split='hard',valid_only=True)
    projected=exporter.project(all_scores,valid_scores,validation['valid_ids'],decoys)
    safe=load(evidence.regular(args.score_projection))
    require(all(safe.get(k)==v for k,v in projected.items()),'canonical-safe-score-projection-differs')
    require(safe.get('helper_sha256')==sha(evidence.partial_ops/'inference_export_scores.py') and safe.get('freeze_sha256')==FREEZE and safe.get('validity_sha256')==sha(root/'answers/validity.json'),'score-proof-inputs-differ')
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




def backup_stop(cleanup,evidence):return load(evidence.descriptor(cleanup['backup_receipt'])).get('last_stop_epoch')




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
                 'inference-analysis-protocol.json','analysis-label.txt','analysis-report.json','analysis-report.html'):
        require('analysis/'+name in files,'required-labelled-study-artifact-missing')
    for relative in frozen['files_sha256']:
        if relative.startswith(('servedoctor/','servetune/','configs/','docs/')):add(evidence.frozen_file(relative),'source/'+relative)
        elif relative.startswith(OLD_OPS_REL+'/'):add(evidence.frozen_file(relative),'provenance/helpers/original/'+Path(relative).name)
    protocol=validation['protocol']
    for name in PROTOCOL_HELPERS:
        # The credential-handling worker is hash-bound by the public analysis
        # protocol; its private launcher source is not recursively published.
        if name!='inference_key_runner.py':add(evidence.partial_ops/name,'provenance/helpers/analysis/'+name)
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
    previous=evidence.descriptor(failure['prior_partial_failure_index']);partial=load(previous)
    require(sha(previous)==PRIOR_PARTIAL_FAILURE_INDEX and failure.get('retained_prior_partial_entries')==21 and len(partial.get('failures',[]))==21
       and len(failure['failures'])>=21 and failure['failures'][:21]==partial['failures'],'prior-partial-failure-history-differs')
    add(previous,'provenance/failures/prior-partial-analysis-failure-index-draft.json')
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
            target='provenance/remote-ops15/'+path.relative_to(evidence.partial_remote_ops).as_posix() if path.is_relative_to(evidence.partial_remote_ops) else 'provenance/remote-ops/'+path.relative_to(evidence.remote_ops).as_posix()
            add(path,target)
    for source,target in [(args.ledger,'ledger.json'),(args.hours,'servedoctor-gpu-hours.md'),(args.cleanup_evidence,'final-cleanup.json'),
        (args.score_projection,'provenance/scoring/hard15-score-projection-final.json'),(args.provenance,'provenance/published-allowlist.json'),(args.readme,'README.md'),
        (__file__,'provenance/helpers/package_inference_offline_results.py'),
        (OPS/'package_inference_results.py','provenance/helpers/package_inference_results.py'),
        (descriptor_adapter.__file__,'provenance/helpers/inference_descriptor_adapter.py'),
        (offline_recovery.__file__,'provenance/helpers/inference_offline_recovery_gate.py')]:add(source,target)
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
    require(evidence.study in (evidence.repo/PRIMARY,evidence.partial_ops/'inference-final-study'),'declared-partial-study-mirror-required')
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
        'all_required_scientific_artifacts_backed_up':True,'all_remote_artifacts_backed_up':False,'remote_ops_control_tail_unverified':True,
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
            'recording_instance_id':RECORD_INSTANCE,'inference_instance_id':INSTANCE,'gpu_budget_amendment_sha256':AMENDMENT,
            'unavailable_original_descriptors':[{'path':REMOTE+'/'+OLD_OPS_REL+'/'+name,'sha256':digest} for name,digest in gate.MISSING],
            'old_full_verify_freeze_claimed':False,
            'all_required_scientific_artifacts_backed_up':True,'all_remote_artifacts_backed_up':False,'remote_ops_control_tail_unverified':True,
            'original_failed_pipeline_outcome':cleanup['original_failed_pipeline_outcome'],'offline_recovery_receipt':cleanup['offline_recovery_receipt'],
            'publication_commit':'A subsequent repository commit; the experiment freeze is not restamped.',
            'original_descriptor_to_package':mapping,'private_bytes':'Answers, raw decisions and native reports are opaque artifacts; only trusted scorer projections enter operator summaries; answer/model payloads are never model prompt inputs.'}
        write_new(out/'artifact-index.json',index);hashes['artifact-index.json']=sha(out/'artifact-index.json')
        require(all(sha(out/name)==digest for name,digest in hashes.items()),'package-post-copy-verification-failed')
        manifest={'project':PROJECT,'label':LABEL,'created_at_utc':datetime.now(timezone.utc).isoformat(),'source_commit':HEAD,'config_sha256':CONFIG,
            'freeze_sha256':FREEZE,'files':hashes,'source_paths':{name:str(path.relative_to(evidence.repo)) for name,path in files.items()},
            'helper_sha256':sha(__file__),'scope':'Labelled fifteen-case analysis, exact original frozen attempt and explicitly reviewed evidence; no recursive operations backups.'}
        write_new(out/'package-manifest.json',manifest);return {**report,'created':True,'destination':str(out),'manifest_sha256':sha(out/'package-manifest.json')}
    except BaseException as error:
        write_new(out/'package-failure.json',{'project':PROJECT,'label':LABEL,'failure_class':type(error).__name__,
            'gate':str(error) if isinstance(error,PackageError) else None,'partial_package_retained':True});raise


def verify_freeze(e):
    origin,root=e.original,e.study;frozen=load(e.regular(origin/legacy.FREEZE))
    require(sha(origin/legacy.FREEZE)==FREEZE and frozen.get('source_commit')==HEAD and frozen.get('study_dir')==ORIGINAL
       and frozen.get('project')=='servedoctor-hard-20261102','original-frozen-identity-differs')
    require(sha(e.repo/'configs/servedoctor-hard.json')==CONFIG and frozen['job_policy'].get('gpu_uuid')==GPU
       and frozen['job_policy'].get('rental_scope_sha256')==RECORD_SCOPE,'original-recording-hardware-or-config-differs')
    for name,h in frozen['files_sha256'].items():require(sha(e.frozen_file(name))==h,'original-frozen-source-or-input-differs')
    require(legacy.commitments(origin)==frozen['scientific_commitments'] and legacy.transport_inventory(origin)==frozen['optional_transport_sha256'],'original-scientific-commitment-differs')
    legacy.no_decisions(origin);require(not (origin/'answers/validity.json').exists() and not (origin/'incidents/hard-16').exists(),'original16-was-validated-or-rerecorded')
    require(sha(e.regular(origin/'engines/engine-06-hard-16/engine.log'))==FAILURE_LOG,'original-hard16-failure-differs')
    protocol=load(e.regular(root/gate.PROTOCOL));record=protocol.get('portable_recording_gate',{})
    require(sha(gate.__file__)==CORE and protocol.get('project')==PROJECT and protocol.get('label')==LABEL
       and protocol.get('source_commit')==HEAD and protocol.get('study_dir')==PRIMARY and protocol.get('original_study_dir')==ORIGINAL
       and protocol.get('included_hard_ids')==list(IDS) and protocol.get('excluded_ids')==['hard-16']
       and protocol.get('scientific_inputs_changed') is False and protocol.get('old_helpers_changed') is False
       and protocol.get('recording_instance_id')==RECORD_INSTANCE and protocol.get('recording_gpu_uuid')==GPU
       and protocol.get('budget_amendment_sha256')==AMENDMENT,'portable-analysis-protocol-differs')
    missing=[{'path':REMOTE+'/'+OLD_OPS_REL+'/'+n,'sha256':h} for n,h in gate.MISSING]
    require(record.get('complete') is True and record.get('source_commit')==HEAD and record.get('original_freeze_sha256')==FREEZE
       and record.get('old_full_verify_freeze_claimed') is False and record.get('missing_ancillary_metadata')==missing,'historical-metadata-gap-disclosure-differs')
    def descriptors(v):
        if isinstance(v,dict):
            if {'path','sha256'}<=v.keys():
                if v in missing:pass
                else:e.descriptor(v)
            for q in v.values():descriptors(q)
        elif isinstance(v,list):
            for q in v:descriptors(q)
    descriptors({k:frozen.get(k) for k in ('preflight','calibration','calibration_provenance','reason_receipt')})
    historical=e.descriptor(record['historical_readiness_stdout']);require(sha(historical)==gate.DECLARED,'historical-readiness-attestation-differs')
    h=load(historical);require(h.get('recording_ready') is True and h.get('source_commit')==HEAD and h.get('gpu_uuid')==GPU
       and h.get('readiness_sha256')==gate.MISSING[0][1],'historical-attestation-fields-differ')
    require(sha(e.descriptor(record['original_closure_audit']))==gate.CLOSURE,'original-closure-attestation-differs')
    calibration=e.descriptor(frozen['calibration']);expected=frozen['calibration_provenance'].get('calibration_files_sha256')
    if expected is not None:require(gate.inventory(calibration.parent)==expected,'original-calibration-inventory-differs')
    original={x.relative_to(origin).as_posix():sha(e.regular(x)) for x in origin.rglob('*') if x.is_file()}
    require(len(original)==178 and original==protocol.get('original_inventory_sha256')==record.get('original_inventory_sha256'),'original178-inventory-differs')
    why=e.descriptor(protocol['exclusion']);require(sha(why)==EXCLUSION,'original-exclusion-differs')
    # The amendment is additional authority; original783's frozen$40 text is retained.
    require(datetime.fromisoformat(protocol['created_at_utc'])>=datetime.fromisoformat(load(why)['recorded_at_utc']),'exclusion-did-not-precede-protocol')
    require(sha(e.regular(e.partial_ops/'gpu-budget-amendment-43-20261102.json'))==AMENDMENT,'budget43-amendment-differs')
    for name,digest in protocol.get('private_helpers_sha256',{}).items():
        require(name in PROTOCOL_HELPERS and sha(e.regular(e.partial_ops/name))==digest and sha(e.frozen_file(OPS_REL+'/'+name))==digest,'inference-helper-source-differs')
    require(set(protocol.get('private_helpers_sha256',{}))==set(PROTOCOL_HELPERS),'inference-helper-set-differs')
    bound=load(e.descriptor(protocol['inference_binding']));scope=e.descriptor(bound['rental_scope']) if 'rental_scope' in bound else e.resolve(REMOTE+'/'+OPS_REL+'/inference-rental-attempt1/rental-scope.json')
    require(bound.get('project')==RENTAL_PROJECT and bound.get('instance_id')==INSTANCE and bound.get('recording_instance_id')==RECORD_INSTANCE
       and bound.get('purpose')=='inference-only' and bound.get('rental_scope_sha256')==SCOPE and sha(scope)==SCOPE
       and bound.get('budget_amendment',{}).get('sha256')==AMENDMENT,'inference-binding-differs')
    ack=bound['create_ack'];ack_path=e.frozen_file(OPS_REL+'/inference-rental-attempt1/'+Path(ack['path']).name)
    require(sha(ack_path)==ack['sha256'] and load(ack_path).get('success') is True and load(ack_path).get('new_contract')==INSTANCE,'inference-create-ack-differs')
    hardware=load(e.descriptor(protocol['inference_hardware']))
    require(hardware.get('project')==RENTAL_PROJECT and hardware.get('instance_id')==INSTANCE and hardware.get('rental_scope_sha256')==SCOPE
       and hardware.get('container_id_matches_scope') is True and hardware.get('source_commit')==HEAD
       and hardware.get('model_revision')==legacy.REV and hardware.get('dtype')=='bf16'
       and hardware.get('vllm_version')==frozen['job_policy']['vllm_version'] and str(hardware.get('gpu_uuid','')).startswith('GPU-'),'inference-runtime-or-physical-binding-differs')
    selected=protocol.get('api_transport',{});old_transport=legacy.transport_inventory(origin);new_transport={n:sha(e.regular(root/n)) for n in legacy.TRANSPORT}
    require(selected=={'mode':'meta-https-connect-local-mac','original_files_sha256':old_transport,
       'archived_original_directory':gate.ARCHIVED_TRANSPORT,'analysis_files_sha256':new_transport},'transport-migration-protocol-differs')
    for name,digest in original.items():
        copied=root/gate.ARCHIVED_TRANSPORT/name if name in legacy.TRANSPORT else root/name
        require(sha(e.regular(copied))==digest,'copied-original-byte-differs')
    cfg=load(root/legacy.TRANSPORT[0]);ready=load(root/legacy.TRANSPORT[1]);channel=load(root/legacy.TRANSPORT[2])
    require(set(cfg)=={'project','instance_id','meta_https_connect_proxy'} and cfg['project']=='servedoctor' and cfg['instance_id']==INSTANCE,'new-transport-instance-differs')
    from servedoctor.llm import _meta_proxy_address
    _meta_proxy_address(cfg['meta_https_connect_proxy'])
    require(ready.get('instance_id')==INSTANCE and ready.get('source_commit')==HEAD and ready.get('origin')=='local_mac'
       and ready.get('transport_config_sha256')==new_transport[legacy.TRANSPORT[0]] and ready.get('allowed_target')=='api.meta.ai:443'
       and ready.get('tls_end_to_end') is True and ready.get('keys_visible_to_relay') is False
       and ready.get('evidence_sha256',{}).get(OPS_REL+'/inference-rental-attempt1/rental-scope.json')==SCOPE,'new-transport-ready-proof-differs')
    require(channel.get('instance_id')==INSTANCE and channel.get('source_commit')==HEAD and channel.get('origin')=='local_mac'
       and channel.get('transport_config_sha256')==new_transport[legacy.TRANSPORT[0]] and channel.get('transport_ready_sha256')==new_transport[legacy.TRANSPORT[1]]
       and channel.get('method')=='GET' and channel.get('url')=='https://api.meta.ai/v1/models' and channel.get('http_status')==401
       and channel.get('tls_verified') is True and channel.get('authenticated') is False and channel.get('authorization_sent') is False
       and channel.get('body_read') is False and channel.get('through_configured_transport') is True and channel.get('verified') is True,'new-transport-channel-proof-differs')
    require((root/'analysis-label.txt').read_text()==LABEL+'\n' and {x.name for x in (root/'incidents').iterdir()}==set(ALL_IDS),'analysis-label-or-recording-set-differs')
    return frozen

def verify_validation(e,frozen):
    root=e.study;protocol=load(root/gate.PROTOCOL);marker=load(e.regular(root/gate.MARKER));directory=e.descriptor(marker['dispatch']).parent
    dispatch=load(e.regular(directory/'dispatch.json'));result=load(e.regular(directory/'result.json'))
    require(marker.get('project')==PROJECT and marker.get('label')==LABEL and dispatch.get('project')==PROJECT and dispatch.get('label')==LABEL
       and e.descriptor(dispatch['protocol'])==e.regular(root/gate.PROTOCOL)
       and dispatch.get('inference_binding_sha256')==protocol['inference_binding']['sha256']
       and result.get('project')==PROJECT and result.get('label')==LABEL and result.get('completed') is True and result.get('returncode')==0
       and not result.get('failure') and result.get('dispatch')==marker['dispatch'] and result.get('study_dispatch_sha256')==sha(root/gate.MARKER),'immutable-inference-validation-differs')
    require(datetime.fromisoformat(dispatch['created_at_utc'])>=datetime.fromisoformat(protocol['created_at_utc']),'validation-precedes-protocol')
    require(gate.p.gate.bytes_inventory(root)==dispatch['recording_bytes_sha256'],'validated-raw-or-runtime-bytes-differ')
    validity=gate.p.gate.validity_summary(root);require(all(result.get(k)==v for k,v in validity.items() if k!='validity')
       and sha(e.descriptor(result['validity']))==sha(root/'answers/validity.json'),'native-validity-differs')
    for n in ('stdout','stderr'):require(result.get(n+'_sha256')==sha(e.regular(directory/('validate.'+n))),'validation-stream-differs')
    quality=protocol['portable_recording_gate']['quality'];require(quality.get('complete') is True and quality.get('expected_recordings')==16
       and quality.get('hard_incidents')==15 and quality.get('historical_gpu_only') is True,'portable-recording-quality-incomplete')
    owned={'jobs':[],'physical_by_incident':{}};seen=set();full=set()
    for item in quality['owned_observer_proofs']:
        path=e.descriptor(item);v=load(path);ready=load(e.descriptor(v['readiness']));e.descriptor(v['observations']);selected=set(ready.get('selected_ids',[]));kept=selected-{'hard-16'}
        require(v.get('project')=='servedoctor-hard-20261102' and v.get('study_dir')==ORIGINAL and v.get('source_commit')==HEAD
           and v.get('freeze_sha256')==FREEZE and v.get('preflight_sha256')==frozen['preflight']['sha256'] and v.get('finished') is True
           and not v.get('owned_leaks') and not v.get('issues') and ready.get('project')=='servedoctor-hard-20261102'
           and ready.get('source_commit')==HEAD and ready.get('freeze_sha256')==FREEZE and ready.get('selected_incident_directories_absent') is True
           and ready.get('ready_before_source_job_timers') is True and selected and selected<=set(ALL_IDS)|{'hard-16'} and not selected&full
           and ready.get('recorder_pid')==v.get('recorder_pid') and ready.get('recorder_start_ticks')==v.get('recorder_start_ticks')
           and all(j.get('incident') in kept for j in v['jobs']) and legacy.physical_matches(ready.get('physical_gpu_binding'),frozen),'historical-owned-proof-differs')
        for name in ('record-identity.json','observer-identity.json'):
            ident=load(e.regular(path.parent/name));require(ident.get('uid')==0 and ident.get('cwd')==REMOTE and ident.get('fd_soft')==65536
               and type(ident.get('fd_hard')) is int and ident['fd_hard']>=65536,'historical-child-proof-differs')
        e.regular(path.parent/'phase-exit.json');seen.update(kept);full.update(selected);owned['jobs'].extend(v['jobs']);owned['physical_by_incident'].update({n:ready['physical_gpu_binding'] for n in kept})
    require(seen==set(ALL_IDS) and full==set(ALL_IDS)|{'hard-16'},'historical-owned-coverage-differs')
    rows=[legacy.audit_recording(root,c,frozen,owned) for c in legacy.cases(e.original) if c['id']!='hard-16']
    require(len(rows)==16 and all(r['complete'] and not r['issues'] for r in rows),'unchanged-structural-recording-audit-failed')
    require(rows==quality['recordings'],'portable-original-quality-projection-differs')
    return {'valid_ids':{r['id'] for r in load(root/'answers/validity.json')['incidents'] if r['valid']},'validation_dir':directory,'quality':quality,'recordings':rows,'protocol':protocol}

def _verify_inputs(args,repo=REPO,repository_check=verify_repository):
    e=Evidence(args,repo);repository_check(e.repo)
    require(e.study in (e.repo/PRIMARY,e.partial_ops/'inference-final-study'),'declared-inference-study-mirror-required')
    frozen=verify_freeze(e);validation=verify_validation(e,frozen);scores=verify_scores(e,args,validation);verify_reports(e,args,scores)
    summary=ledger_summary(e.regular(args.ledger),e.regular(args.ledger_seed));require(not summary['warnings'],'ledger-warning-stop-was-reached')
    final=load(e.regular(Path(args.evaluation_dir)/'final-ledger.stdout'));require(final.get('sha256')==sha(args.ledger) and final.get('summary')==summary,'final-canonical-ledger-proof-differs')
    engine_dirs=list((e.study/'engines').glob('evaluation-glimmer-hard-*'));require(len(engine_dirs)==1,'one-dedicated-inference-engine-required')
    engine=load(e.regular(engine_dirs[0]/'engine_metadata.json'));e.regular(engine_dirs[0]/'engine.log')
    require(engine.get('model_revision')==legacy.REV and engine.get('dtype')=='bf16' and engine.get('vllm_version')==frozen['job_policy']['vllm_version']
       and engine.get('cleanup_status')=='completed' and engine.get('returncode')==0,'inference-engine-runtime-or-cleanup-differs')
    paths=set(study_files(e)+original_files(e)+list(e.fingerprints))
    require(all(sha(path)==digest for path,digest in e.fingerprints.items()),'input-evidence-mutated-during-verification')
    result={'project':PROJECT,'label':LABEL,'ready':True,'source_commit':HEAD,'recordings':16,'final_decisions':90,'hard_incidents':15,
       'original_freeze_sha256':FREEZE,'protocol_sha256':sha(e.study/gate.PROTOCOL),'inference_binding_sha256':validation['protocol']['inference_binding']['sha256'],
       'inference_instance_id':INSTANCE,'recording_instance_id':RECORD_INSTANCE,'ledger_summary':summary,'canonical_ledger_sha256':sha(args.ledger),
       'missing_ancillary_metadata':validation['protocol']['portable_recording_gate']['missing_ancillary_metadata'],
       'old_full_verify_freeze_claimed':False,'valid_cases':len(validation['valid_ids']),
       'input_files_sha256':{str(x.relative_to(e.repo)):sha(x) for x in sorted(paths)}}
    return e,frozen,validation,scores,result
def verify_inputs(args,repo=REPO):
    """Safe read-only finalizer gate; hashes/counts only, no cleanup/provider/writes."""
    return _verify_inputs(args,repo)[4]

def verify_rental_accounting(e,cleanup):
    def blocked(*a,**kw):raise PackageError('provider-operation-forbidden')
    state=load(e.descriptor(cleanup['final_state']));control=e.partial_ops/'inference-rental-attempt1'
    service=hard_vast.Rental(root=control,repo=e.repo,api=blocked,inventory=blocked,clock=lambda:state['destroyed_epoch'])
    require(state.get('project')==RENTAL_PROJECT and state.get('instance_id')==INSTANCE and state.get('scope_sha256')==SCOPE
       and state.get('destroyed_epoch')==cleanup['destroyed_epoch'] and not state.get('pending_intent') and not state.get('pending_attachment')
       and state.get('running_intervals') and all('stop_epoch' in x for x in state['running_intervals']),'final-inference-state-differs')
    prior=load(e.descriptor(state['prior_accounting']));require(service.prior(prior['receipt']['path'])==prior and abs(prior['total_usd_upper']-PRIOR_END)<1e-8,'immutable-prior-cost-lineage-differs')
    own=service.host_cost(state,state['destroyed_epoch']);cost=cleanup['gpu_accounting'];total=PRIOR_END+own['compute_usd_upper']+own['disk_usd_upper']
    require(cost.get('inference_host_cost')==own and abs(cost.get('prior_v0_and_five_hard_hosts_usd_upper',0)-PRIOR_END)<1e-8
       and abs(cost.get('total_usd_upper',0)-total)<1e-8 and total<=43 and cost.get('total_cap_usd')==43
       and cost.get('network_and_slack_reserved_once') is True,'final-inference-cost-over-cap-or-double-counted')
    require(backup_stop(cleanup,e)==state['running_intervals'][-1]['stop_epoch'],'last-inference-stop-differs')

def verify_cleanup(e,args):
    c=load(e.regular(args.cleanup_evidence));ledger=e.regular(args.ledger);hours=e.regular(args.hours)
    require(c.get('project')==RENTAL_PROJECT and c.get('analysis_project')==PROJECT and c.get('label')==LABEL and c.get('instance_id')==INSTANCE
       and c.get('rental_scope_sha256')==SCOPE and c.get('confirmed_absent') is True and c.get('stopped_confirmed') is True
       and c.get('owned_work_quiescent') is True and c.get('excluded_ids')==['hard-16'] and numeric(c.get('destroyed_epoch')),'inference-cleanup-incomplete')
    require(c.get('canonical_ledger_sha256')==c.get('remote_ledger_sha256')==sha(ledger) and c.get('gpu_hours_log_sha256')==sha(hours)
       and c.get('ledger_summary')==ledger_summary(ledger,e.regular(args.ledger_seed)),'cleanup-ledger-or-hours-differs')
    require(sha(e.descriptor(c['authorization']))==EXCLUSION and sha(e.descriptor(c['original_preservation']))==PRESERVATION
       and sha(e.descriptor(c['budget_amendment']))==AMENDMENT,'cleanup-original-or-budget-amendment-differs')
    protocol=load(e.study/gate.PROTOCOL);binding_sha=protocol['inference_binding']['sha256']
    require(sha(e.descriptor(c['binding']))==binding_sha and c.get('original_recording_instance_id')==RECORD_INSTANCE
       and c.get('original_recording_gpu_uuid')==GPU and c.get('original_freeze_sha256')==FREEZE,'cleanup-recording-or-inference-lineage-differs')
    intent=load(e.descriptor(c['delete_intent']));outcome=load(e.descriptor(c['delete_outcome']));reconciled=load(e.descriptor(c['delete_reconciliation']))
    for v in (intent,outcome):require(v.get('operation')=='delete' and v.get('method')=='DELETE' and v.get('instance_id')==INSTANCE
       and v.get('rental_scope_sha256')==SCOPE and v.get('path')==f'/api/v0/instances/{INSTANCE}/','inference-delete-binding-differs')
    require(outcome.get('phase') in ('response','unknown_outcome') and outcome.get('requested_epoch')==intent.get('requested_epoch')
       and reconciled.get('instance_id')==INSTANCE and reconciled.get('destroyed_epoch')==c['destroyed_epoch'] and not reconciled.get('pending_intent'),'inference-delete-not-get-confirmed')
    backup=load(e.descriptor(c['backup_receipt']));require(backup.get('project')==RENTAL_PROJECT and backup.get('analysis_project')==PROJECT
       and backup.get('label')==LABEL and backup.get('instance_id')==INSTANCE and backup.get('rental_scope_sha256')==SCOPE
       and backup.get('all_required_scientific_artifacts_backed_up') is True and backup.get('all_remote_artifacts_backed_up') is False
       and backup.get('remote_ops_control_tail_unverified') is True and backup.get('final_decisions')==90,'inference-predelete-backup-incomplete')
    require(backup.get('original_recording_instance_id')==RECORD_INSTANCE and backup.get('original_freeze_sha256')==FREEZE
       and sha(e.descriptor(backup['binding']))==binding_sha and sha(e.descriptor(backup['budget_amendment']))==AMENDMENT
       and sha(e.descriptor(backup['authorization']))==EXCLUSION and sha(e.descriptor(backup['original_preservation']))==PRESERVATION,'backup-lineage-differs')
    require(backup.get('last_stop_epoch')<=intent.get('requested_epoch')<=c['destroyed_epoch'],'inference-backup-delete-order-differs')
    readiness=load(e.descriptor(backup['readiness']));require(readiness.get('ready') is True and readiness.get('instance_id')==INSTANCE
       and readiness.get('rental_scope_sha256')==SCOPE and readiness.get('canonical_ledger_sha256')==sha(ledger),'inference-predelete-readiness-differs')
    recovered=verify_offline_policy(e,c,backup,readiness)
    parent=load(e.descriptor(readiness['pipeline_outcome']));require(parent.get('project')==RENTAL_PROJECT and parent.get('instance_id')==INSTANCE
       and parent.get('returncode')==1 and parent.get('stop_confirmed') is True and parent.get('cleanup_confirmed') is True
       and not any(parent.get(n) for n in ('watchdog_cleanup_error_class','transport_cleanup_error_class','child_cleanup_error_class'))
       and parent.get('transport_cleanup_returncode')==0,'inference-parent-not-stopped-or-quiescent')
    require(readiness.get('input_verification')==verify_inputs(args,e.repo),'predelete-input-verification-differs')
    require(readiness.get('transport_retirement',{}).get('owned_transport_quiescent') is True and readiness.get('relay_stop_proofs'),'owned-relay-retirement-unproven')
    for item in readiness['relay_stop_proofs']:require(load(e.descriptor(item)).get('stopped') is True,'relay-stop-proof-differs')
    manifest=load(e.descriptor(backup['evidence_manifest']));base=Path(manifest['root']);verified=set()
    require(base.resolve()==e.repo,'backup-root-differs')
    for name,h in manifest['files'].items():
        require(not Path(name).is_absolute() and '..' not in Path(name).parts,'unsafe-backup-path');path=e.regular(base/name);require(sha(path)==h,'backup-file-differs');verified.add(path)
    inputs=verify_inputs(args,e.repo)['input_files_sha256']
    require(all(e.regular(e.repo/n) in verified for n in inputs),'verified-input-not-backed-up')
    for folder in (e.partial_remote_ops,e.remote_ops,e.control):
        for path in folder.rglob('*'):
            require(not path.is_symlink(),'linked-final-mirror')
            if path.is_file() and path.name not in BACKUP_MUTABLE and not path.name.endswith('.tmp'):require(e.regular(path) in verified,'full-final-mirror-not-backed-up')
    require(e.descriptor(backup['gpu_hours_snapshot']) in verified,'immutable-hours-snapshot-not-backed-up')
    snapshot=e.descriptor(backup['stopped_state_snapshot']);require(snapshot in verified,'immutable-stopped-state-not-backed-up')
    final_state=load(e.descriptor(c['final_state']));stopped_state=load(snapshot)
    require(stopped_state.get('scope_sha256')==SCOPE and stopped_state.get('running_intervals')==final_state.get('running_intervals'),'stopped-billing-snapshot-differs')
    canonical=backup['canonical_ledger'];require(canonical['sha256']==canonical['remote_sha256']==sha(ledger)
       and e.descriptor({'path':canonical['path'],'sha256':canonical['sha256']}) in verified,'canonical-ledger-not-backed-up')
    verify_rental_accounting(e,c);require(sha(e.resolve(CONTROL+'/rental-scope.json'))==SCOPE,'final-guard-control-scope-differs')
    return c

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study-dir',default=str(OPS/'inference-final-study'))
    p.add_argument('--original-study-dir',default=str(OPS/'inference-final-original-study'))
    p.add_argument('--remote-ops',default=str(OPS/'inference-final-remote-ops'))
    p.add_argument('--remote-old-ops',default=str(OPS/'inference-final-remote-old-ops'))
    p.add_argument('--remote-control',default=str(OPS/'inference-final-remote-control'))
    p.add_argument('--calibration-mirror',default=str(OPS/'inference-final-remote-ops/portable-recording-evidence/calibration'))
    p.add_argument('--ledger',default=str(OPS/'inference-evaluation-attempt1/final-canonical-ledger.json'))
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
