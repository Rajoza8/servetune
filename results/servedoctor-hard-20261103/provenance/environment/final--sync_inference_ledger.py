#!/usr/bin/env python3
"""Verify, then explicitly synchronize the final GPU ledger as exact bytes.

Default verification has no writes/provider/process/model operations. --sync
requires the completed stopped/cleaned parent and GET-confirmed deleted589 scope.
The inherited443 entries and immutable seed must be unchanged. Only atomic byte
copy is used; no ledger init/reserve/settle/save or JSON reserialization exists.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import uuid

OPS=Path(__file__).resolve().parent
REPO=OPS.parent.parent
sys.path.insert(0,str(REPO))
from servedoctor.llm import Ledger

PROJECT='servedoctor-hard15-inference-20261103'
ANALYSIS_PROJECT='servedoctor-hard15-20261102'
LABEL='ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)'
INSTANCE=58905385
SCOPE='7da4c657be8e5e6bf971e5e017a24b02385d6c0f3221daa20ae64e7eb7cedce7'
SEED='13f777ed328bb0c71bb2063b6b12cf3b6cb8024d78b0ab46b9e374521a566123'
PREFIX_COUNT=443
FINALIZER='fcbb55ca1b58a810ac87f9991cf5961b5f139f633ecaa10736696495ba5a553c'


def require(value,reason):
    if not value:raise ValueError(reason)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def desc(path):return {'path':str(Path(path).resolve()),'sha256':sha(path)}
def load(path):return json.loads(Path(path).read_text())
def write_new(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())


class ReadOnlyLedger(Ledger):
    @contextmanager
    def _lock(self):
        # Native summary normally creates a lockfile. These immutable stopped
        # copies are hashed before/after, so verification needs no filesystem
        # mutation. Explicit sync separately holds the canonical native lock.
        yield


def regular(path,repo):
    path=Path(path).absolute();repo=Path(repo).resolve();name=path.name.lower()
    require('..' not in path.parts and path.resolve()==path and path.is_relative_to(repo) and path.is_file(),'Regular repository evidence required')
    require(not name.startswith(('.env','ssh_ed25519','gemma_vast_pilot','id_rsa','id_ed25519'))
        and not any(v in name for v in ('api_key','api-key','credentials')) and path.suffix not in ('.key','.pem','.sock'),'Credential is not ledger evidence')
    return path


def paths(args,repo=REPO):
    repo=Path(repo).resolve();ops=repo/'runs/servedoctor-hard15-ops-20261102';old=repo/'runs/servedoctor-hard-ops-20261102'
    out=Path(args.out);out=out.absolute() if out.is_absolute() else repo/out
    require(out.parent==ops and not out.is_symlink() and re.fullmatch('inference-ledger-sync-attempt[1-9][0-9]*',out.name),'Fresh direct ledger-sync proof directory required')
    return {'repo':repo,'ops':ops,'out':out,'canonical':repo/'runs/servedoctor-ledger.json',
        'final':ops/'inference-final-gpu-ledger.json','seed':old/'prepare-next-attempt1/upload/ledger.seed',
        'parent':ops/'inference-rental-attempt1/outcome.json','native':ops/'inference-evaluation-attempt1/final-ledger.stdout',
        'cleanup':ops/'inference-final-cleanup-attempt1/cleanup.json','dispatch':ops/'inference-final-cleanup-attempt1/delete-dispatch.json'}


def checked(value,repo):
    path=regular(value['path'],repo);require(sha(path)==value['sha256'],'Descriptor bytes differ');return path


def verify(args,repo=REPO):
    p=paths(args,repo);r=p['repo']
    for name in ('canonical','final','seed','parent','native','cleanup','dispatch'):regular(p[name],r)
    require(sha(p['seed'])==SEED,'Immutable inherited seed differs')
    parent=load(p['parent']);cleanup=load(p['cleanup']);dispatch=load(p['dispatch'])
    require(parent.get('project')==PROJECT and parent.get('instance_id')==INSTANCE and parent.get('rental_scope_sha256')==SCOPE
        and parent.get('returncode')==0 and parent.get('stop_confirmed') is True and parent.get('cleanup_confirmed') is True
        and parent.get('transport_cleanup_returncode')==0
        and not any(parent.get(k) for k in ('failure','watchdog_cleanup_error_class','child_cleanup_error_class','transport_cleanup_error_class')),
        'Completed stopped/quiescent parent required before ledger sync')
    require(cleanup.get('project')==PROJECT and cleanup.get('instance_id')==INSTANCE and cleanup.get('rental_scope_sha256')==SCOPE
        and cleanup.get('confirmed_absent') is True and cleanup.get('stopped_confirmed') is True and cleanup.get('owned_work_quiescent') is True
        and cleanup.get('gpu_accounting',{}).get('total_usd_upper',44)<=43,'Final GET-confirmed589 deletion under43 required')
    require(dispatch.get('project')==PROJECT and dispatch.get('instance_id')==INSTANCE and dispatch.get('rental_scope_sha256')==SCOPE
        and dispatch.get('method')=='DELETE' and dispatch.get('path')==f'/api/v0/instances/{INSTANCE}/'
        and dispatch.get('helper_sha256')==FINALIZER,'Reviewed finalizer DELETE dispatch required')
    final_state=load(checked(cleanup['final_state'],r));reconciliation=load(checked(cleanup['delete_reconciliation'],r))
    require(final_state.get('project')==PROJECT and final_state.get('instance_id')==INSTANCE and final_state.get('scope_sha256')==SCOPE
        and final_state.get('destroyed_epoch')==cleanup.get('destroyed_epoch') and not final_state.get('pending_intent')
        and final_state.get('running_intervals') and all('stop_epoch' in row for row in final_state['running_intervals'])
        and final_state.get('last_status',{}).get('actual_status') in ('stopped','exited')
        and final_state.get('last_status',{}).get('cur_state') in ('stopped','exited') and final_state.get('last_status',{}).get('intended_status')!='running'
        and reconciliation.get('instance_id')==INSTANCE and reconciliation.get('destroyed_epoch')==cleanup.get('destroyed_epoch')
        and reconciliation.get('confirmed_absent') is True and not reconciliation.get('pending_intent'),'Final deletion reconciliation/state differs')
    for name in ('delete_intent','delete_outcome'):
        value=load(checked(cleanup[name],r))
        require(value.get('operation')=='delete' and value.get('method')=='DELETE' and value.get('instance_id')==INSTANCE
            and value.get('rental_scope_sha256')==SCOPE and value.get('path')==f'/api/v0/instances/{INSTANCE}/','DELETE scope proof differs')
    seed,final=load(p['seed']),load(p['final']);prefix=seed.get('entries',[])
    require(seed.get('project')=='servedoctor' and seed.get('caps_usd')=={'meta':'50','baseten':'20'} and len(prefix)==PREFIX_COUNT,'Exact inherited443 ledger prefix/caps required')
    require(final.get('project')=='servedoctor' and final.get('caps_usd')==seed['caps_usd'] and isinstance(final.get('entries'),list)
        and final['entries'][:PREFIX_COUNT]==prefix,'Final ledger must retain exact inherited prefix/caps')
    entries=final['entries'];ids=[v.get('id') for v in entries]
    require(all(isinstance(v,str) and v for v in ids) and len(set(ids))==len(ids),'Final ledger IDs must be unique')
    for row in entries:
        amount=Decimal(row['accounted_usd'])
        require(row.get('provider') in ('meta','baseten') and row.get('status') in ('reserved','settled','overrun')
            and amount.is_finite() and amount>=0,'Invalid canonical ledger entry')
    before=sha(p['final']);summary=ReadOnlyLedger(p['final']).summary()
    require(sha(p['final'])==before and summary.get('caps_usd')=={'meta':50.0,'baseten':20.0}
        and not summary.get('warnings') and all(math.isfinite(v) and 0<=v<=summary['caps_usd'][k] for k,v in summary['accounted_usd'].items()),
        'Final native ledger summary warns or exceeds unchanged caps')
    native=load(p['native'])
    require(native.get('sha256')==before and native.get('summary')==summary and cleanup.get('canonical_ledger_sha256')==before
        and cleanup.get('remote_ledger_sha256')==before and cleanup.get('ledger_summary')==summary,'Authoritative final GPU ledger/cleanup/native summary differs')
    current=sha(p['canonical']);require(current in (SEED,before),'Local ledger changed independently; refuse overwrite')
    if current==SEED:require(load(p['canonical'])==seed,'Canonical inherited ledger bytes differ from seed')
    else:require(p['canonical'].read_bytes()==p['final'].read_bytes(),'Already-synchronized bytes differ')
    require(sha(p['seed'])==SEED and sha(p['final'])==before,'Immutable source changed during verification')
    return p,{'project':ANALYSIS_PROJECT,'rental_project':PROJECT,'label':LABEL,'instance_id':INSTANCE,'rental_scope_sha256':SCOPE,'verified':True,'already_synchronized':current==before,
        'current_canonical_sha256':current,'final_sha256':before,'inherited_prefix_entries':PREFIX_COUNT,'final_entries':len(entries),
        'canonical_ledger_sha256':current,'remote_ledger_sha256':before,'seed_prefix_unchanged':True,
        'ledger_summary':summary,'source':desc(p['final']),'seed':desc(p['seed']),'cleanup':desc(p['cleanup']),'parent':desc(p['parent']),
        'provider_actions':0,'writes':0}


def execute(args,repo=REPO):
    p,proof=verify(args,repo)
    if not args.sync or proof['already_synchronized']:return proof
    lock=p['canonical'].with_name(p['canonical'].name+'.lock')
    require(not lock.is_symlink() and (not lock.exists() or lock.is_file()),'Canonical ledger lock must be regular')
    with lock.open('a') as handle:
        fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
        p,proof=verify(args,repo)
        if proof['already_synchronized']:return proof
        p['out'].mkdir(exist_ok=False);temporary=None
        try:
            write_new(p['out']/'intent.json',{**proof,'operation':'atomic-final-ledger-byte-sync','at_utc':datetime.now(timezone.utc).isoformat(),
                'helper_sha256':sha(__file__),'ledger_bytes_not_reencoded':True})
            before=p['out']/'canonical-before-sync.json'
            with p['canonical'].open('rb') as source,before.open('xb') as target:shutil.copyfileobj(source,target)
            require(sha(before)==SEED,'Inherited ledger backup differs')
            temporary=p['canonical'].with_name(p['canonical'].name+'.inference-sync-'+uuid.uuid4().hex+'.tmp')
            with p['final'].open('rb') as source,temporary.open('xb') as target:
                shutil.copyfileobj(source,target);target.flush();os.fsync(target.fileno())
            os.chmod(temporary,stat.S_IMODE(p['canonical'].stat().st_mode))
            require(sha(temporary)==proof['final_sha256']==sha(p['final']) and sha(p['canonical'])==SEED,'Source/canonical changed before atomic replacement')
            os.replace(temporary,p['canonical']);_,after=verify(args,repo)
            require(after['already_synchronized'] and sha(p['seed'])==SEED,'Atomic byte sync verification failed')
            result={**after,'synchronized':True,'changed':True,'ledger_bytes_not_reencoded':True,'canonical_before':desc(before),
                'writes':1,'proof_directory':str(p['out'])}
            write_new(p['out']/'outcome.json',result);return result
        except BaseException as error:
            marker={'class':type(error).__name__,'original_failure_preserved':True,'canonical_sha256':sha(p['canonical']),
                'temporary_retained':str(temporary) if temporary and temporary.exists() else None,'no_automatic_retry':True}
            if not (p['out']/'failure.json').exists():write_new(p['out']/'failure.json',marker)
            raise


def main():
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--verify-only',action='store_true');mode.add_argument('--sync',action='store_true')
    parser.add_argument('--out',default=str(OPS/'inference-ledger-sync-attempt1'));args=parser.parse_args()
    print(json.dumps(execute(args)))


if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit('Final ledger synchronization refused: '+type(error).__name__) from None
