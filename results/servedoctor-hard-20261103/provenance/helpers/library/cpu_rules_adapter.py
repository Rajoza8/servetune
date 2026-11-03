#!/usr/bin/env python3
"""Inactive-by-default, local CPU validation/rules adapter. No model, key, GPU, ledger or network calls.

Old proof bytes stay unchanged. Their absolute GPU descriptors are resolved
through explicit, hash-verified local mirrors. Only --execute makes a fresh copy
and dispatches the unchanged native validate/rules commands, once each.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import package_partial_results as p

LABEL=p.LABEL
MODE='local-cpu-validation-and-rules-only'
MANIFEST='505d7d74d4a978f1de9058380c3d38b85826d7c06affe1d7cffcabe16032d068'
PRESERVED=p.OPS.parent/'servedoctor-hard-ops-20261102/blocked-hard-study-attempt1'
MARKER='cpu-rules-dispatch.json'
PROTOCOL='cpu-operation-protocol.json'
NOT_RUN=[a for a in p.ARMS if a!='rules']

def require(value,code):
    if not value:raise ValueError(code)
def utc():return datetime.now(timezone.utc).isoformat()
def desc(path):return {'path':str(Path(path).resolve()),'sha256':p.sha(path)}
def write(path,value):
    with Path(path).open('x') as f:json.dump(value,f,indent=2,allow_nan=False);f.write('\n')
def inventory(root):return p.gate.inventory(root)

def evidence(args,repo=p.REPO):
    e=p.Evidence(args,repo)
    # More specific aliases precede the ordinary old-OPS mapping. No proof is
    # rewritten, and every descriptor still has to match its original SHA.
    aliases=[]
    for remote,local in getattr(args,'map',[]) or []:
        require(remote.startswith(p.REMOTE+'/') and '..' not in Path(remote).parts,'unsafe-map-origin')
        local=Path(local).resolve();require(local.is_relative_to(e.repo) and local.is_dir() and not local.is_symlink(),'unsafe-map-target')
        aliases.append((remote.rstrip('/'),local))
    require(len({a for a,_ in aliases})==len(aliases),'duplicate-map-origin')
    e.mappings=sorted(aliases+e.mappings,key=lambda x:len(x[0]),reverse=True)
    return e

def original_gate(e,args,verify_repository=p.verify_repository):
    verify_repository(e.repo)
    require(p.sha(p.__file__)==getattr(args,'package_helper_sha256',p.sha(p.__file__)),'mapped-verifier-source-differs')
    origin=e.original
    preservation=e.regular(args.preservation_receipt);manifest=e.regular(args.preserved_manifest)
    require(p.sha(preservation)==p.PRESERVATION and p.sha(manifest)==MANIFEST,'preservation-proof-differs')
    saved=p.load(manifest)['files'];prefix='latest/study/'
    expected={k[len(prefix):]:v for k,v in saved.items() if k.startswith(prefix)}
    require(len(expected)==178 and inventory(origin)==expected,'original178-byte-inventory-differs')
    # Full frozen source/config/input commitments and all descriptor hashes.
    frozen=p.load(e.regular(origin/p.legacy.FREEZE))
    require(p.sha(origin/p.legacy.FREEZE)==p.FREEZE and frozen.get('source_commit')==p.HEAD
            and frozen.get('study_dir')==p.ORIGINAL and frozen.get('project')==p.RENTAL_PROJECT,'original-freeze-differs')
    require(p.sha(e.repo/'configs/servedoctor-hard.json')==p.CONFIG,'config-differs')
    for relative,digest in frozen['files_sha256'].items():require(p.sha(e.frozen_file(relative))==digest,'frozen-source-or-input-differs')
    require(p.legacy.transport_inventory(origin)==frozen['optional_transport_sha256'],'frozen-transport-differs')
    require(p.legacy.commitments(origin)==frozen['scientific_commitments'],'scientific-commitment-differs')
    p.legacy.no_decisions(origin)
    require(not (origin/'answers/validity.json').exists() and not (origin/'incidents/hard-16').exists(),'original-was-validated-or-hard16-recorded')
    require(p.sha(e.regular(origin/'engines/engine-06-hard-16/engine.log'))==p.FAILURE_LOG,'hard16-failure-differs')
    e.descriptors({k:frozen.get(k) for k in ('preflight','calibration','calibration_provenance','reason_receipt')})
    ready=p.load(e.descriptor(frozen['preflight']));e.descriptors(ready)
    require(p.legacy.preflight_policy(e.descriptor(frozen['preflight']),p.HEAD,p.CONFIG)==frozen['job_policy'],'preflight-policy-differs')
    require(ready.get('gpu_uuid')==p.GPU and ready.get('rental_scope_sha256')==p.SCOPE,'historical-physical-binding-differs')
    if 'calibration_files_sha256' in ready:
        calibration=e.descriptor(frozen['calibration']);folder=calibration.parent
        require(inventory(folder)==ready['calibration_files_sha256'],'calibration-inventory-differs')
    why=p.gate.exclusion(e.regular(args.exclusion))
    require(why['original_preservation_receipt']['sha256']==p.sha(preservation),'exclusion-preservation-differs')
    return frozen,expected

def quality(e,frozen,proofs):
    owned={'jobs':[],'physical_by_incident':{}};seen=set();full=set();checked=[]
    for descriptor in proofs:
        path=e.descriptor(descriptor);v=p.load(path);ready=p.load(e.descriptor(v['readiness']));e.descriptor(v['observations'])
        selected=set(ready.get('selected_ids',[]));kept=selected-{'hard-16'}
        require(v.get('project')==p.RENTAL_PROJECT and v.get('study_dir')==p.ORIGINAL and v.get('finished') is True
            and not v.get('owned_leaks') and not v.get('issues') and v.get('source_commit')==p.HEAD
            and v.get('freeze_sha256')==p.FREEZE and v.get('preflight_sha256')==frozen['preflight']['sha256']
            and ready.get('project')==p.RENTAL_PROJECT and ready.get('source_commit')==p.HEAD
            and ready.get('freeze_sha256')==p.FREEZE and ready.get('selected_incident_directories_absent') is True
            and ready.get('ready_before_source_job_timers') is True and selected and selected<=set(p.ALL_IDS)|{'hard-16'}
            and not selected&full and all(j.get('incident') in kept for j in v['jobs'])
            and ready.get('recorder_pid')==v.get('recorder_pid') and ready.get('recorder_start_ticks')==v.get('recorder_start_ticks')
            and p.legacy.physical_matches(ready.get('physical_gpu_binding'),frozen),'owned-recording-proof-differs')
        for name in ('record-identity.json','observer-identity.json'):
            identity=p.load(e.regular(path.parent/name))
            require(identity.get('uid')==0 and identity.get('cwd')==p.REMOTE and identity.get('fd_soft')==65536
                and type(identity.get('fd_hard')) is int and identity['fd_hard']>=65536,'child-identity-or-limit-differs')
        e.regular(path.parent/'phase-exit.json') # Retain failed hard16 phase honestly.
        full.update(selected);seen.update(kept);owned['jobs'].extend(v['jobs'])
        owned['physical_by_incident'].update({n:ready['physical_gpu_binding'] for n in kept});checked.append(descriptor)
    require(full==set(p.ALL_IDS)|{'hard-16'} and seen==set(p.ALL_IDS),'owned-full-declaration-coverage-differs')
    rows=[p.legacy.audit_recording(e.original,case,frozen,owned) for case in p.legacy.cases(e.original) if case['id']!='hard-16']
    require(len(rows)==16 and {r['id'] for r in rows}==set(p.ALL_IDS) and all(r['complete'] and not r['issues'] for r in rows),'structural-recording-quality-failed')
    return {'project':p.PROJECT,'label':LABEL,'mode':MODE,'complete':True,'expected_recordings':16,'hard_incidents':15,
            'recordings':rows,'owned_observer_proofs':checked,'historical_gpu_only':True,
            'acceptance':'Unchanged frozen audit_recording; infrastructure and coverage only, never SLO or model performance.'}

def audit(args,repo=p.REPO,verify_repository=p.verify_repository):
    e=evidence(args,repo);frozen,before=original_gate(e,args,verify_repository)
    proofs=[]
    require(len(args.owned_proof)==3,'exactly-three-original-owned-proofs-required')
    for raw in args.owned_proof:
        path=e.resolve(raw);proofs.append({'path':raw,'sha256':p.sha(path)})
    result=quality(e,frozen,proofs)
    require(inventory(e.original)==before,'original-changed-during-audit')
    result.update(original_inventory_sha256=before,source_commit=p.HEAD,original_freeze_sha256=p.FREEZE,
        descriptor_map=[{'remote_prefix':a,'local_prefix':str(b)} for a,b in e.mappings],
        verified_descriptor_files_sha256={str(v):p.sha(v) for v in e.dependencies.values()},
        arms={'rules':'PLANNED',**{a:'NOT_RUN' for a in NOT_RUN}},gpu_used=False,paid_calls=False,
        package_helper=desc(p.__file__),adapter=desc(__file__))
    return e,result

def execute(args,repo=p.REPO,run=subprocess.run,verify_repository=p.verify_repository):
    e,proof=audit(args,repo,verify_repository)
    root=e.study;out=Path(args.out).resolve()
    require(root==e.repo/p.PRIMARY and not root.exists() and not root.is_symlink(),'fresh-canonical-local-analysis-root-required')
    require(out.parent==e.partial_ops and not out.exists(),'fresh-direct-cpu-output-required')
    out.mkdir();before=proof['original_inventory_sha256']
    write(out/'intent.json',{'project':p.PROJECT,'label':LABEL,'created_at_utc':utc(),'mode':MODE,
        'source_commit':p.HEAD,'no_gpu_no_network_no_model_no_ledger_access':True,'audit':proof})
    result={'project':p.PROJECT,'label':LABEL,'mode':MODE,'completed':False,'failure':None,
            'arms':{'rules':'NOT_RUN',**{a:'NOT_RUN' for a in NOT_RUN}},'gpu_used':False,'paid_calls':False}
    try:
        shutil.copytree(e.original,root);require(inventory(root)==before,'opaque-copy-differs')
        protocol={'project':p.PROJECT,'label':LABEL,'created_at_utc':utc(),'mode':MODE,'source_commit':p.HEAD,
            'study_dir':root.relative_to(e.repo).as_posix(),'original_study_dir':str(e.original),
            'included_hard_ids':list(p.IDS),'excluded_ids':['hard-16'],'scientific_inputs_changed':False,
            'original_inventory_sha256':before,'original_freeze_sha256':p.FREEZE,'exclusion':desc(args.exclusion),
            'preservation':desc(args.preservation_receipt),'descriptor_map':proof['descriptor_map'],
            'verified_descriptor_files_sha256':proof['verified_descriptor_files_sha256'],'adapter':desc(__file__),
            'package_helper':desc(p.__file__),'gpu_used':False,'paid_calls':False,'arms':result['arms']}
        write(root/PROTOCOL,protocol);(root/'analysis-label.txt').write_text(LABEL+'\n')
        write(out/'quality.json',proof)
        dispatch={'project':p.PROJECT,'label':LABEL,'created_at_utc':utc(),'protocol':desc(root/PROTOCOL),
            'quality':desc(out/'quality.json'),'recording_bytes_sha256':p.gate.bytes_inventory(root)}
        write(out/'dispatch.json',dispatch);write(root/MARKER,{'project':p.PROJECT,'label':LABEL,'dispatch':desc(out/'dispatch.json')})
        def command(name,argv):
            with (out/(name+'.stdout')).open('xb') as stdout,(out/(name+'.stderr')).open('xb') as stderr:
                done=run(argv,cwd=e.repo,stdout=stdout,stderr=stderr,timeout=300)
            write(out/(name+'-exit.json'),{'returncode':done.returncode,'finished_at_utc':utc()})
            require(done.returncode==0,'native-'+name+'-failed')
        command('validate',[sys.executable,'-m','servedoctor','validate','--study-dir',str(root)])
        validity=p.gate.validity_summary(root);write(out/'validity-summary.json',{**validity,'project':p.PROJECT,'label':LABEL})
        require(p.gate.bytes_inventory(root)==dispatch['recording_bytes_sha256'],'raw-or-runtime-changed-during-validation')
        p.legacy.no_decisions(root)
        command('rules',[sys.executable,'-m','servedoctor','evaluate','--study-dir',str(root),'--split','hard','--arms','rules'])
        files={x.name for x in (root/'decisions/rules').iterdir()}
        require(files=={n+'.json' for n in p.IDS},'exactly-fifteen-final-rules-decisions-required')
        require({x.name for x in (root/'decisions').iterdir()}=={'rules'},'unexpected-model-arm-output')
        for kind,extra in [('all',[]),('valid-only',['--valid-only'])]:
            command('score-'+kind,[sys.executable,'-m','servedoctor','score','--study-dir',str(root),'--split','hard',*extra])
            scores=p.load(out/('score-'+kind+'.stdout'));require(set(scores)<= {'rules'},'unexpected-scored-arm')
            write(out/('labelled-score-'+kind+'.json'),{'project':p.PROJECT,'label':LABEL,'scoreboard':scores,
                'arm_status':{'rules':'COMPLETED',**{a:'NOT_RUN' for a in NOT_RUN}}})
        require(inventory(e.original)==before and p.gate.bytes_inventory(root)==dispatch['recording_bytes_sha256'],'preserved-evidence-changed')
        result.update(completed=True,validity=validity,arms={'rules':'COMPLETED',**{a:'NOT_RUN' for a in NOT_RUN}})
    except BaseException as error:
        result['failure']=type(error).__name__
        raise
    finally:
        result['finished_at_utc']=utc();write(out/'outcome.json',result)
    return result

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--execute',action='store_true')
    a.add_argument('--study-dir',default=str(p.REPO/p.PRIMARY));a.add_argument('--original-study-dir',default=str(PRESERVED/'latest/study'))
    a.add_argument('--remote-ops',default=str(p.OPS));a.add_argument('--remote-old-ops',default=str(p.REPO/p.OLD_OPS_REL))
    a.add_argument('--remote-control',default=str(p.OPS/'final-remote-control'));a.add_argument('--calibration-mirror',default=str(p.REPO/p.OLD_OPS_REL/'bootstrap-calibration-controller-attempt8/mirror'))
    a.add_argument('--preservation-receipt',default=str(PRESERVED/'preservation-receipt.json'));a.add_argument('--preserved-manifest',default=str(PRESERVED/'preserved-files-manifest.json'))
    a.add_argument('--exclusion',default=str(p.REPO/p.OLD_OPS_REL/'partial-analysis-exclusion-20261102T2306Z.json'))
    a.add_argument('--owned-proof',action='append',required=True);a.add_argument('--map',nargs=2,action='append')
    a.add_argument('--out',default=str(p.OPS/'cpu-rules-attempt1'));args=a.parse_args()
    try:
        if args.execute:value=execute(args)
        else:
            _,proof=audit(args);value={k:proof[k] for k in ('project','label','mode','complete','expected_recordings','hard_incidents','source_commit','original_freeze_sha256','arms','gpu_used','paid_calls')}
            value['dispatch_performed']=False
        print(json.dumps(value));return 0
    except BaseException as error:print(json.dumps({'project':p.PROJECT,'label':LABEL,'error_class':type(error).__name__}));return 1
if __name__=='__main__':raise SystemExit(main())
