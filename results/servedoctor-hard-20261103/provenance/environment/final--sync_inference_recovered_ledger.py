#!/usr/bin/env python3
"""Exact byte-sync adapter for the separately verified copy-recovery parent."""
import argparse
import importlib.util
from pathlib import Path
import sys

OPS=Path(__file__).resolve().parent;sys.path.insert(0,str(OPS))
import inference_copy_recovery_gate as recovery
BASE_SHA='08bb5d9dd68376ba8fc601be57aa32c623db420918ea5fbde66b160f68a71e0e'
path=OPS/'sync_inference_ledger.py';recovery.require(recovery.sha(path)==BASE_SHA,'Original sync helper differs')
spec=importlib.util.spec_from_file_location('_recovered_original_sync',path)
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
original_paths,original_verify=base.paths,base.verify


def paths(args,repo=base.REPO):
    p=original_paths(args,repo);info=recovery.verify_recovery(repo,getattr(args,'recovery_receipt',None))
    p['parent']=Path(info['pipeline_outcome']['path']);p['copy_recovery']=info;return p


def verify(args,repo=base.REPO):
    p,proof=original_verify(args,repo);info=p['copy_recovery'];cleanup=base.load(p['cleanup'])
    base.require(cleanup.get('original_failed_pipeline_outcome')==info['original_pipeline_outcome']
        and cleanup.get('copy_recovery_receipt')==info['copy_recovery_receipt']
        and cleanup.get('copy_recovery_declaration')==info['declaration'],'Recovery cleanup lineage differs')
    adapter=cleanup['copy_recovery_adapter'];source=base.checked(adapter,p['repo'])
    base.require(source==OPS/'finalize_inference_recovered_rental.py','Reviewed recovery finalizer adapter required')
    proof.update(original_failed_pipeline_outcome=info['original_pipeline_outcome'],copy_recovery_receipt=info['copy_recovery_receipt'],
        copy_recovery_declaration=info['declaration'],copy_recovery_sync_adapter=base.desc(__file__))
    return p,proof


base.paths=paths;base.verify=verify
execute=base.execute


def main():
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--verify-only',action='store_true');m.add_argument('--sync',action='store_true')
    p.add_argument('--out',default=str(OPS/'inference-ledger-sync-attempt1'))
    p.add_argument('--recovery-receipt',default=str(OPS/'inference-copy-recovery-attempt1/materialization-receipt.json'))
    print(base.json.dumps(execute(p.parse_args())))


if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit('Recovered ledger synchronization refused: '+type(error).__name__) from None
