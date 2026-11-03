#!/usr/bin/env python3
"""Offline restoration cleanup: the exact scientific gate stays unchanged.
Read-only completed-inference verification, immutable backup, explicit DELETE.

Only the new58905385 inference rental/$43 overlay is admitted. The unchanged
recorded15-case evidence and exact portable-metadata disclosure are verified by
the separately frozen local packager gate. No original study, ledger, scoring,
prompt, answer, source or old40-dollar receipt is modified. Unknown DELETE is
GET-only; the first finalized accounting receipt is immutable.
"""
import argparse
import inference_offline_recovery_gate as recovery
import importlib.util
import json
from pathlib import Path
import re
import sys

import inference_vast as v
import finalize_partial_rental as old

OPS=Path(__file__).resolve().parent
REPO=OPS.parent.parent
# The import-only old rental helper adds its own directory to sys.path. Restore
# this analysis namespace before loading the separately pinned mapped gate.
sys.path.insert(0,str(OPS))
INSTANCE=58905385
SCOPE='7da4c657be8e5e6bf971e5e017a24b02385d6c0f3221daa20ae64e7eb7cedce7'
PROJECT=v.PROJECT
ANALYSIS_PROJECT=old.ANALYSIS_PROJECT
LABEL=old.LABEL
PACKAGE_SHA='fdaf66af25327c4501c8e66b2fa56708600d4c4acc8b5585a32724d3b5f0ae91'
PRIOR_TOTAL=37.552391290596844
MUTABLE=old.MUTABLE
load=old.load
sha=old.sha
desc=old.desc
write_new=old.write_new
require=old.require
regular=old.regular


def blocked(*_args,**_kwargs):raise RuntimeError('Provider forbidden during local verification')


def verify_inputs(args,repo):
    path=regular(Path(repo)/'runs/servedoctor-hard15-ops-20261102/inference_descriptor_adapter.py',repo)
    require(PACKAGE_SHA is not None and sha(path)==PACKAGE_SHA,'Reviewed frozen inference evidence gate required')
    spec=importlib.util.spec_from_file_location('_final_inference_evidence_gate',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.verify_inputs(args,repo=Path(repo))


def paths(args,service):
    repo=service.repo.resolve();ops=repo/'runs/servedoctor-hard15-ops-20261102'
    require(service.root.resolve()==ops/'inference-rental-attempt1','Exact new inference controller required')
    out=Path(args.out);out=out.absolute() if out.is_absolute() else repo/out
    require(out.parent==ops and not out.is_symlink() and re.fullmatch('inference-final-cleanup-attempt[1-9][0-9]*',out.name),'Fresh direct inference cleanup output required')
    def resolve(value):
        p=Path(value);return p.absolute() if p.is_absolute() else repo/p
    p={name:resolve(getattr(args,name)) for name in ('study_dir','original_study_dir','evaluation_dir','remote_ops','remote_old_ops','remote_control','ledger','ledger_seed')}
    expected={'study_dir':ops/'inference-final-study','original_study_dir':ops/'inference-final-original-study',
        'evaluation_dir':ops/'inference-evaluation-attempt1','remote_ops':ops/'inference-final-remote-ops',
        'remote_old_ops':ops/'inference-final-remote-old-ops','remote_control':ops/'inference-final-remote-control',
        'ledger':ops/'inference-final-gpu-ledger.json'}
    require(all(p[n]==value for n,value in expected.items()),'Only explicit final inference mirrors allowed')
    p.update(repo=repo,ops=ops,control=service.root.resolve(),out=out,hours=repo/'runs/servedoctor-gpu-hours.md',
        recovery_receipt=resolve(getattr(args,'recovery_receipt',None) or ops/'inference-offline-materialization-attempt2/receipt.json'),
        pipeline=service.root/'outcome.json',binding=service.binding_path,budget=ops/'gpu-budget-amendment-43-20261102.json',
        exclusion=repo/old.OLD_REL/'partial-analysis-exclusion-20261102T2306Z.json',
        preservation=repo/old.OLD_REL/'blocked-hard-study-attempt1/preservation-receipt.json')
    return p


def scope(state,service):
    require(state.get('project')==PROJECT and state.get('instance_id')==INSTANCE and state.get('scope_sha256')==SCOPE
        and sha(service.scope_path)==SCOPE,'Exact new inference scope required')


def stopped(state):
    return (not state.get('pending_intent') and not state.get('pending_attachment') and v.Rental.stopped(state.get('last_status',{}))
        and state.get('running_intervals') and all('stop_epoch' in row for row in state['running_intervals']))


def process_identity(pid):
    # Read-only ps through the pinned relay core; never call its stop/cleanup.
    import inference_meta_tunnel
    return inference_meta_tunnel.base_module().identity(pid)


def transport_quiescent(p):
    folder=p['ops']/'inference-transport-attempt1';pointer=load(regular(folder/'relay-pointer.json',p['repo']))
    require(pointer.get('instance_id')==INSTANCE and pointer.get('rental_scope_sha256')==SCOPE,'Transport pointer scope differs')
    attempt=Path(pointer['attempt_dir'])
    require(attempt.parent==p['control'] and attempt.name.startswith('meta-relay-attempt-'),'Owned transport attempt required')
    ready=load(regular(attempt/'transport-ready.json',p['repo']))
    require(ready.get('instance_id')==INSTANCE,'Transport ready instance differs')
    owned=list(ready['owned_processes'].values())
    owned.append(load(regular(folder/'guardian-process.json',p['repo'])))
    for identity in owned:
        require(type(identity.get('pid')) is int and identity.get('start_identity'),'Owned transport birth identity required')
        actual=process_identity(identity['pid'])
        require(actual is None or actual.get('start_identity')!=identity['start_identity'],'Owned relay/tunnel/guardian still alive')
    return {'owned_processes_checked':len(owned),'owned_transport_quiescent':True,'pointer':desc(folder/'relay-pointer.json'),
        'ready':desc(attempt/'transport-ready.json'),'guardian':desc(folder/'guardian-process.json')}


def readiness(args,service,verifier=verify_inputs):
    p=paths(args,service);state=service.load();scope(state,service)
    recovered=recovery.verify_recovery(p['repo'],p['recovery_receipt'])
    require(not state.get('destroyed_epoch') and stopped(state),'Freshly observed stopped inference rental/closed billing required')
    parent=load(regular(p['pipeline'],p['repo']))
    require(parent.get('project')==PROJECT and parent.get('instance_id')==INSTANCE and parent.get('rental_scope_sha256')==SCOPE
        and parent.get('returncode')==1 and desc(p['pipeline'])==recovered['pipeline_outcome'] and parent.get('stop_confirmed') is True and parent.get('cleanup_confirmed') is True
        and not any(parent.get(n) for n in ('watchdog_cleanup_error_class','transport_cleanup_error_class','child_cleanup_error_class'))
        and parent.get('transport_cleanup_returncode')==0,'Completed parent, owned child/watchdog/relay cleanup required')
    # No native/model/answer text is returned by the pinned mapped verifier.
    inputs=verifier(args,p['repo'])
    require(inputs==recovered['input_verification'],'Exact restored c98 scientific verification differs')
    require(inputs.get('project')==ANALYSIS_PROJECT and inputs.get('label')==LABEL and inputs.get('ready') is True
        and inputs.get('recordings')==16 and inputs.get('final_decisions')==90
        and inputs.get('canonical_ledger_sha256')==sha(regular(p['ledger'],p['repo']))
        and inputs.get('inference_binding_sha256')==sha(regular(p['binding'],p['repo']))
        and inputs.get('original_freeze_sha256')==old.FREEZE,'Completed immutable15/90 inputs required')
    require(sha(regular(p['budget'],p['repo']))==v.AMENDMENT_SHA and sha(regular(p['exclusion'],p['repo']))==old.EXCLUSION
        and sha(regular(p['preservation'],p['repo']))==old.PRESERVATION,'User43 overlay/original15 authorization differs')
    cost=service.cost(state)
    require(cost.get('prior_v0_and_five_hard_hosts_usd_upper')==PRIOR_TOTAL and cost.get('total_usd_upper',44)<=43,'All prior/current costs under43 required')
    # The queue has an explicit relay-stop job; the parent repeats only owned
    # idempotent cleanup in finally. Require the retained actual stop result.
    transport=p['ops']/'inference-transport-attempt1';stops=sorted(transport.glob('stop-*.json'))
    require(stops and all(load(regular(path,p['repo'])).get('stopped') is True for path in stops),'Owned inference relay/tunnel retirement proof required')
    transport_proof=transport_quiescent(p)
    return p,state,{'project':PROJECT,'analysis_project':ANALYSIS_PROJECT,'label':LABEL,'instance_id':INSTANCE,'rental_scope_sha256':SCOPE,
        'ready':True,'original_recording_instance_id':58866756,'original_recording_gpu_uuid':'GPU-ced6c24c-2234-f9e6-4b0f-6b11b82f9681',
        'excluded_ids':['hard-16'],'original_freeze_sha256':old.FREEZE,'binding':desc(p['binding']),
        'budget_amendment':desc(p['budget']),'authorization':desc(p['exclusion']),'original_preservation':desc(p['preservation']),
        'pipeline_outcome':desc(p['pipeline']),'original_failed_pipeline_outcome':recovered['original_failed_pipeline_outcome'],
        'offline_recovery_receipt':recovered['offline_recovery_receipt'],'offline_recovery_adapter':desc(__file__),
        'all_required_scientific_artifacts_backed_up':True,'all_remote_artifacts_backed_up':False,'remote_ops_control_tail_unverified':True,'input_verification':inputs,'last_stop_epoch':state['running_intervals'][-1]['stop_epoch'],
        'canonical_ledger_sha256':inputs['canonical_ledger_sha256'],'remote_ledger_sha256':inputs['canonical_ledger_sha256'],
        'ledger_summary':inputs['ledger_summary'],'gpu_accounting':cost,'owned_work_quiescent':True,'final_decisions':90,
        'relay_stop_proofs':[desc(path) for path in stops],'transport_retirement':transport_proof}


def inventory(p,inputs):
    files={}
    for name,digest in inputs['input_files_sha256'].items():
        require(not Path(name).is_absolute() and '..' not in Path(name).parts and sha(regular(p['repo']/name,p['repo']))==digest,'Input gate file changed')
        files[name]=digest
    roots=(p['study_dir'],p['original_study_dir'],p['evaluation_dir'],p['remote_ops'],p['remote_old_ops'],p['remote_control'],p['control'],p['ops']/'inference-transport-attempt1')
    for folder in roots:
        require(folder.is_dir() and not folder.is_symlink() and not p['out'].is_relative_to(folder),'Nonoverlapping final mirror required')
        for path in sorted(folder.rglob('*')):
            require(not path.is_symlink(),'Linked final evidence refused')
            if path.is_dir():continue
            if path.name in MUTABLE or path.name.endswith('.tmp'):continue
            files[str(path.relative_to(p['repo']))]=sha(regular(path,p['repo']))
    for path in (p['ledger'],p['budget'],p['binding'],p['exclusion'],p['preservation'],Path(recovery.verify_recovery(p['repo'],p['recovery_receipt'])['offline_recovery_receipt']['path']),Path(__file__),Path(recovery.__file__),p['ops']/'inference_descriptor_adapter.py',p['ops']/'package_inference_results.py'):files[str(path.relative_to(p['repo']))]=sha(regular(path,p['repo']))
    return dict(sorted(files.items()))


def verify_backup(args,service,verifier=verify_inputs):
    p=paths(args,service);state=service.load();scope(state,service);path=p['out']/'backup-receipt.json';receipt=load(regular(path,p['repo']))
    require(receipt.get('all_required_scientific_artifacts_backed_up') is True and receipt.get('remote_ops_control_tail_unverified') is True,'Required-science backup and operator-tail disclosure required')
    require(receipt.get('project')==PROJECT and receipt.get('analysis_project')==ANALYSIS_PROJECT and receipt.get('label')==LABEL
        and receipt.get('instance_id')==INSTANCE and receipt.get('rental_scope_sha256')==SCOPE and receipt.get('all_remote_artifacts_backed_up') is False
        and receipt.get('last_stop_epoch')==state['running_intervals'][-1]['stop_epoch'],'Final inference backup binding differs')
    manifest=receipt['evidence_manifest'];require(desc(regular(manifest['path'],p['repo']))==manifest,'Backup manifest changed')
    value=load(manifest['path']);require(Path(value['root']).resolve()==p['repo'],'Manifest root differs')
    proof=load(p['out']/'readiness.json');inputs=verifier(args,p['repo'])
    require(inputs==proof['input_verification'],'Scientific/ledger gate changed after backup')
    expected=inventory(p,inputs);snapshot=receipt['gpu_hours_snapshot'];require(desc(regular(snapshot['path'],p['repo']))==snapshot,'Hours snapshot changed')
    expected[str(Path(snapshot['path']).relative_to(p['repo']))]=snapshot['sha256']
    state_snapshot=receipt['stopped_state_snapshot'];require(desc(regular(state_snapshot['path'],p['repo']))==state_snapshot,'Stopped state snapshot changed')
    expected[str(Path(state_snapshot['path']).relative_to(p['repo']))]=state_snapshot['sha256']
    require(value['files']==dict(sorted(expected.items())),'Complete final evidence inventory differs')
    for name,digest in value['files'].items():require(sha(regular(p['repo']/name,p['repo']))==digest,'Final backup byte changed')
    before=load(state_snapshot['path'])
    require(before['running_intervals']==state['running_intervals'] and before['scope_sha256']==state['scope_sha256'],'Stopped accounting changed after backup')
    return p,state,receipt


def prepare(args,service,verifier=verify_inputs):
    p,state,proof=readiness(args,service,verifier);out=p['out'];out.mkdir(exist_ok=False)
    try:
        write_new(out/'readiness.json',proof)
        hours=out/'gpu-hours-before-delete.md';hours.write_bytes(regular(p['hours'],p['repo']).read_bytes())
        snapshot=out/'stopped-state.json';write_new(snapshot,state)
        before=inventory(p,proof['input_verification']);before[str(hours.relative_to(p['repo']))]=sha(hours);before[str(snapshot.relative_to(p['repo']))]=sha(snapshot)
        manifest=out/'backup-manifest.json';write_new(manifest,{'root':str(p['repo']),'files':dict(sorted(before.items()))})
        after=inventory(p,proof['input_verification']);after[str(hours.relative_to(p['repo']))]=sha(hours);after[str(snapshot.relative_to(p['repo']))]=sha(snapshot)
        require(before==after,'Final input changed while snapshotting')
        receipt={'project':PROJECT,'analysis_project':ANALYSIS_PROJECT,'label':LABEL,'instance_id':INSTANCE,'rental_scope_sha256':SCOPE,
            'all_required_scientific_artifacts_backed_up':True,'all_remote_artifacts_backed_up':False,'remote_ops_control_tail_unverified':True,
            'offline_recovery_receipt':proof['offline_recovery_receipt'],'original_failed_pipeline_outcome':proof['original_failed_pipeline_outcome'],
            'backup_scope':'All required scientific, source and known operator evidence restored byte-for-byte locally. Original178/failed16 and evaluated281/90 retained. Unmanifested remote OPS/control tail remains unverified; model cache excluded.',
            'original_recording_instance_id':58866756,'budget_amendment':proof['budget_amendment'],'authorization':proof['authorization'],
            'original_preservation':proof['original_preservation'],'original_freeze_sha256':old.FREEZE,'binding':proof['binding'],
            'last_stop_epoch':proof['last_stop_epoch'],'evidence_manifest':desc(manifest),'gpu_hours_snapshot':desc(hours),'stopped_state_snapshot':desc(snapshot),
            'canonical_ledger':{'path':str(p['ledger']),'sha256':proof['canonical_ledger_sha256'],'remote_sha256':proof['remote_ledger_sha256']},
            'readiness':desc(out/'readiness.json'),'owned_work_quiescent':True,'final_decisions':90}
        write_new(out/'backup-receipt.json',receipt);verify_backup(args,service,verifier)
        return {'prepared':True,'backup_receipt':desc(out/'backup-receipt.json'),'files':len(before),'provider_actions':0}
    except BaseException as error:
        marker=out/'backup-failure.json'
        if not marker.exists():write_new(marker,{'class':type(error).__name__,'partial_backup_retained':True,'delete_dispatched':False})
        raise

def intents(service):
    matches=[]
    for path in service.root.glob('intent-*-delete.json'):
        value=load(path)
        if value.get('instance_id')==INSTANCE and value.get('rental_scope_sha256')==SCOPE:
            require(value.get('operation')=='delete' and value.get('method')=='DELETE' and value.get('path')==f'/api/v0/instances/{INSTANCE}/','DELETE scope differs');matches.append(path)
    require(len(matches)<=1,'Multiple DELETE intents require review');return matches


def finish(args,service):
    p=paths(args,service);state=service.load();scope(state,service)
    if not state.get('destroyed_epoch'):return {'confirmed_absent':False,'get_only_next':True}
    require(stopped(state) and len(intents(service))==1,'Confirmed absence requires prior stopped DELETE lineage')
    out=p['out'];cleanup=out/'cleanup.json'
    if cleanup.exists():return {'confirmed_absent':True,'cleanup':desc(cleanup),'provider_actions':0}
    proof=load(out/'readiness.json');require(sha(p['ledger'])==proof['canonical_ledger_sha256'],'Authoritative final ledger changed')
    final=out/'final-state.json'
    if final.exists():require(load(final)==state,'Final state snapshot differs')
    else:write_new(final,state)
    reconciliation=out/'delete-reconciliation.json'
    if not reconciliation.exists():write_new(reconciliation,{'instance_id':INSTANCE,'destroyed_epoch':state['destroyed_epoch'],'pending_intent':None,'confirmed_absent':True})
    intent=intents(service)[0];outcome=intent.with_name(intent.stem+'-outcome.json');require(outcome.is_file(),'DELETE outcome missing; retain unknown evidence')
    cost=service.cost(state);require(cost.get('total_usd_upper',44)<=43 and cost.get('prior_v0_and_five_hard_hosts_usd_upper')==PRIOR_TOTAL,'Final all-host cost exceeds43 or prior costs differ')
    value={key:proof[key] for key in ('project','analysis_project','label','instance_id','rental_scope_sha256','original_recording_instance_id',
        'original_recording_gpu_uuid','excluded_ids','original_freeze_sha256','binding','budget_amendment','authorization','original_preservation',
        'canonical_ledger_sha256','remote_ledger_sha256','ledger_summary','original_failed_pipeline_outcome','offline_recovery_receipt','offline_recovery_adapter',
        'all_required_scientific_artifacts_backed_up','all_remote_artifacts_backed_up','remote_ops_control_tail_unverified')}
    value.update(confirmed_absent=True,stopped_confirmed=True,owned_work_quiescent=True,destroyed_epoch=state['destroyed_epoch'],
        backup_receipt=desc(out/'backup-receipt.json'),delete_intent=desc(intent),delete_outcome=desc(outcome),
        delete_reconciliation=desc(reconciliation),final_state=desc(final),gpu_accounting=cost,gpu_hours_log_sha256=sha(p['hours']))
    write_new(cleanup,value);return {'confirmed_absent':True,'cleanup':desc(cleanup)}


def execute(args,service=None,verifier=verify_inputs):
    service=service or v.Rental(**({} if args.delete or args.reconcile else {'api':blocked,'inventory':blocked}))
    if args.prepare_backup:return prepare(args,service,verifier)
    p=paths(args,service)
    if args.reconcile:
        if (p['out']/'cleanup.json').exists():return {'confirmed_absent':True,'cleanup':desc(p['out']/'cleanup.json'),'provider_actions':0}
        require((p['out']/'delete-dispatch.json').is_file(),'Prior explicit DELETE dispatch required')
        with service.lock():service.reconcile()
        return finish(args,service)
    p,state,proof=readiness(args,service,verifier)
    if not args.delete:
        if (p['out']/'backup-receipt.json').exists():verify_backup(args,service,verifier)
        return {**proof,'backup_verified':(p['out']/'backup-receipt.json').exists(),'writes':0,'provider_actions':0}
    require((p['out']/'backup-receipt.json').is_file(),'Prepare and inspect final backup beforeDELETE')
    require(not (p['out']/'delete-dispatch.json').exists() and not intents(service),'DELETE attempted; GET-only reconcile')
    verify_backup(args,service,verifier)
    with service.lock():
        service.reconcile();p,state,_=readiness(args,service,verifier);verify_backup(args,service,verifier)
        require(not intents(service),'DELETE attempted; GET-only reconcile')
        write_new(p['out']/'delete-dispatch.json',{'project':PROJECT,'instance_id':INSTANCE,'rental_scope_sha256':SCOPE,
            'method':'DELETE','path':f'/api/v0/instances/{INSTANCE}/','backup_receipt':desc(p['out']/'backup-receipt.json'),'helper_sha256':sha(__file__)})
        service.intent(state,'delete',f'/api/v0/instances/{INSTANCE}/',reason='Explicit complete15-case inference cleanup after immutable all-input backup under authorized43 cap')
        service.reconcile()
    return finish(args,service)


def defaults(repo=REPO):
    repo=Path(repo);ops=repo/'runs/servedoctor-hard15-ops-20261102';r=repo/old.OLD_REL
    return {'study_dir':ops/'inference-final-study','original_study_dir':ops/'inference-final-original-study',
        'evaluation_dir':ops/'inference-evaluation-attempt1','remote_ops':ops/'inference-final-remote-ops',
        'remote_old_ops':ops/'inference-final-remote-old-ops','remote_control':ops/'inference-final-remote-control',
        'calibration_mirror':ops/'inference-final-remote-ops/portable-recording-evidence/calibration',
        'score_projection':ops/'inference-evaluation-attempt1/hard15-score-projection.json',
        'ledger':ops/'inference-final-gpu-ledger.json','ledger_seed':r/'prepare-next-attempt1/upload/ledger.seed',
        'out':ops/'inference-final-cleanup-attempt1'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group()
    for name in ('verify-only','prepare-backup','delete','reconcile'):mode.add_argument('--'+name,action='store_true')
    parser.add_argument('--recovery-receipt',default=str(REPO/'runs/servedoctor-hard15-ops-20261102/inference-offline-materialization-attempt2/receipt.json'))
    for name,value in defaults().items():parser.add_argument('--'+name.replace('_','-'),default=str(value))
    print(json.dumps(execute(parser.parse_args())))


if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit('Inference final cleanup refused: '+type(error).__name__) from None
