#!/usr/bin/env python3
"""Exact copy-recovery adapter; original fcbb financial/lifecycle code is retained."""
import argparse
import importlib.util
from pathlib import Path
import sys

OPS=Path(__file__).resolve().parent;sys.path.insert(0,str(OPS))
import inference_copy_recovery_gate as recovery
BASE_SHA='fcbb55ca1b58a810ac87f9991cf5961b5f139f633ecaa10736696495ba5a553c'
path=OPS/'finalize_inference_rental.py';recovery.require(recovery.sha(path)==BASE_SHA,'Original finalizer differs')
spec=importlib.util.spec_from_file_location('_recovered_original_finalizer',path)
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base);sys.path.insert(0,str(OPS))
original_paths,original_readiness,original_inventory=base.paths,base.readiness,base.inventory


def paths(args,service):
    p=original_paths(args,service);info=recovery.verify_recovery(service.repo,getattr(args,'recovery_receipt',None))
    p['pipeline']=Path(info['pipeline_outcome']['path']);p['copy_recovery']=info;return p


def readiness(args,service,verifier=base.verify_inputs):
    p,state,proof=original_readiness(args,service,verifier)
    info=p['copy_recovery'];proof.update(original_failed_pipeline_outcome=info['original_pipeline_outcome'],
        copy_recovery_receipt=info['copy_recovery_receipt'],copy_recovery_declaration=info['declaration'],
        copy_recovery_adapter=base.desc(__file__))
    return p,state,proof


def inventory(p,inputs):
    files=original_inventory(p,inputs);info=p['copy_recovery'];root=Path(info['copy_recovery_receipt']['path']).parent
    for path in root.rglob('*'):
        base.require(not path.is_symlink(),'Linked recovery backup refused')
        if path.is_file() and not path.name.endswith('.tmp'):files[str(path.relative_to(p['repo']))]=base.sha(base.regular(path,p['repo']))
    for path in [Path(info['declaration']['path']),Path(__file__),Path(recovery.__file__)]:files[str(path.relative_to(p['repo']))]=base.sha(base.regular(path,p['repo']))
    return dict(sorted(files.items()))


def finish(args,service):
    p=paths(args,service);state=service.load();base.scope(state,service)
    if not state.get('destroyed_epoch'):return {'confirmed_absent':False,'get_only_next':True}
    base.require(base.stopped(state) and len(base.intents(service))==1,'Confirmed absence requires prior stopped DELETE lineage')
    out=p['out'];cleanup=out/'cleanup.json'
    if cleanup.exists():return {'confirmed_absent':True,'cleanup':base.desc(cleanup),'provider_actions':0}
    proof=base.load(out/'readiness.json');base.require(base.sha(p['ledger'])==proof['canonical_ledger_sha256'],'Authoritative final ledger changed')
    final=out/'final-state.json'
    if final.exists():base.require(base.load(final)==state,'Final state snapshot differs')
    else:base.write_new(final,state)
    reconciled=out/'delete-reconciliation.json'
    if not reconciled.exists():base.write_new(reconciled,{'instance_id':base.INSTANCE,'destroyed_epoch':state['destroyed_epoch'],'pending_intent':None,'confirmed_absent':True})
    intent=base.intents(service)[0];outcome=intent.with_name(intent.stem+'-outcome.json');base.require(outcome.is_file(),'DELETE outcome missing; retain unknown evidence')
    cost=service.cost(state);base.require(cost.get('total_usd_upper',44)<=43 and cost.get('prior_v0_and_five_hard_hosts_usd_upper')==base.PRIOR_TOTAL,'Final all-host cost exceeds43 or prior costs differ')
    names=('project','analysis_project','label','instance_id','rental_scope_sha256','original_recording_instance_id','original_recording_gpu_uuid',
        'excluded_ids','original_freeze_sha256','binding','budget_amendment','authorization','original_preservation','canonical_ledger_sha256','remote_ledger_sha256','ledger_summary',
        'original_failed_pipeline_outcome','copy_recovery_receipt','copy_recovery_declaration','copy_recovery_adapter')
    value={key:proof[key] for key in names}
    value.update(confirmed_absent=True,stopped_confirmed=True,owned_work_quiescent=True,destroyed_epoch=state['destroyed_epoch'],
        backup_receipt=base.desc(out/'backup-receipt.json'),delete_intent=base.desc(intent),delete_outcome=base.desc(outcome),
        delete_reconciliation=base.desc(reconciled),final_state=base.desc(final),gpu_accounting=cost,gpu_hours_log_sha256=base.sha(p['hours']))
    base.write_new(cleanup,value);return {'confirmed_absent':True,'cleanup':base.desc(cleanup)}


# The original module is loaded under a private name. Only its explicit path,
# readiness, backup inventory and new cleanup metadata functions are adapted.
# Its provider mutation implementation and dispatch's fcbb source hash remain
# truthful; the separately hashed adapter is in readiness/cleanup/backup.
base.paths=paths;base.readiness=readiness;base.inventory=inventory;base.finish=finish
execute=base.execute


def main():
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    for name in ('verify-only','prepare-backup','delete','reconcile'):m.add_argument('--'+name,action='store_true')
    for name,value in base.defaults().items():p.add_argument('--'+name.replace('_','-'),default=str(value))
    p.add_argument('--recovery-receipt',default=str(OPS/'inference-copy-recovery-attempt1/materialization-receipt.json'))
    print(base.json.dumps(execute(p.parse_args())))


if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit('Recovered inference cleanup refused: '+type(error).__name__) from None
