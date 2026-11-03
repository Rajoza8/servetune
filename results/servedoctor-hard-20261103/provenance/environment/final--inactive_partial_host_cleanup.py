#!/usr/bin/env python3
"""Back up and explicitly retire only the unavailable recorded Hard host.

This is a failed-START cleanup branch, not the completed-analysis finalizer.
The entire available local original study is required; unavailable remote
OPS/control tail is disclosed. Default verify is local/read-only. DELETE is
one-shot, after fresh stopped GET and immutable local backup; unknown means
GET-only reconciliation. No START/STOP/SSH/model/ledger mutation is provided.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import shutil
import sys

OPS=Path(__file__).resolve().parent
REPO=OPS.parent.parent
OLD=REPO/'runs/servedoctor-hard-ops-20261102'
sys.path.insert(0,str(OLD))
import hard_vast as h
import finalize_partial_rental as f

INSTANCE=f.INSTANCE
SCOPE=f.SCOPE
PIPELINE='partial-resume-pipeline-attempt1/outcome.json'
PIPELINE_SHA='17430d395755150bfaf43723ecabcc3618f588681126933726ccbe5bc8590183'
MODE='recorded_original15_preserved_failed_inference_restart'
ACCOUNTING=('instance_id','offer_id','machine_id','image','scope_sha256','created_epoch','prior_baseline',
            'prior_hard_hosts','prior_hard_history','running_intervals','dph_total','storage_dph')
sha=f.sha
load=f.load
desc=f.desc
require=f.require
write_new=f.write_new


def blocked(*_args,**_kwargs):raise RuntimeError('Provider calls forbidden during local verification')


class Cleanup:
    def __init__(self,service=None,backup_dir=None):
        self.service=service or h.Rental(api=blocked,inventory=blocked)
        self.old=self.service.root.resolve();self.repo=self.service.repo.resolve();self.ops=self.repo/f.NEW_REL
        self.backup=Path(backup_dir) if backup_dir else self.ops/'inactive-host5-backup-attempt1'
        if not self.backup.is_absolute():self.backup=self.repo/self.backup
        require(self.backup.parent==self.ops and not self.backup.is_symlink()
            and re.fullmatch('inactive-host5-backup-attempt[1-9][0-9]*',self.backup.name),'Fresh direct OPS15 inactive-host backup required')

    def scope(self):
        state=self.service.load();f.bound(state)
        require(sha(f.regular(self.service.scope_path,self.repo))==SCOPE and state.get('label')==h.LABEL,'Exact immutable host5 scope required')
        return state

    def stopped(self,state):
        require(not state.get('pending_attachment') and f.base.stopped(state),'Fresh stopped/closed state with no queued mutation required')

    def gate(self,state):
        old,repo=self.old,self.repo
        pipeline_path=f.regular(old/PIPELINE,repo);require(sha(pipeline_path)==PIPELINE_SHA,'Exact failed inference restart outcome required')
        pipeline=load(pipeline_path)
        require(pipeline.get('project')==h.LABEL and pipeline.get('analysis_label')==f.LABEL
            and pipeline.get('instance_id')==INSTANCE and pipeline.get('rental_scope_sha256')==SCOPE
            and pipeline.get('returncode')==1 and pipeline.get('stop_confirmed') is True
            and pipeline.get('cleanup_confirmed') is True and not pipeline.get('watchdog_cleanup_error_class')
            and pipeline.get('commands')==[] and pipeline.get('start_request_returncode')==1,'No dispatched partial analysis jobs and quiescent failed parent required')
        queued=pipeline['queued_start'];response_path=f.regular(queued['outcome_path'],repo)
        require(response_path.parent==old and sha(response_path)==queued['outcome_sha256'],'Queued START response changed')
        response=load(response_path)
        require(response.get('instance_id')==INSTANCE and response.get('rental_scope_sha256')==SCOPE
            and response.get('operation')=='start' and response.get('method')=='PUT' and response.get('path')==f'/api/v0/instances/{INSTANCE}/'
            and response.get('phase')=='response' and response.get('success') is False
            and response.get('safe_error_code')=='resources_unavailable','Known nonallocated queued START required')
        last=state['running_intervals'][-1]
        require('running_seen_epoch' not in last and last['start_epoch']<=queued['requested_epoch']<=last['stop_epoch']
            and pipeline.get('finished_epoch',0)>=last['stop_epoch'],'Failed restart must never have been observed running')
        original=old/'blocked-hard-study-attempt1/latest/study';preservation=old/'blocked-hard-study-attempt1/preservation-receipt.json'
        manifest=old/'blocked-hard-study-attempt1/preserved-files-manifest.json';exclusion=old/'partial-analysis-exclusion-20261102T2306Z.json'
        p={'repo':repo,'exclusion':exclusion,'preservation':preservation,'preserved_manifest':manifest}
        f.authorization(p)
        listing=load(manifest)['files'];base=manifest.parent
        require(listing and all(not Path(n).is_absolute() and '..' not in Path(n).parts
            and sha(f.regular(base/n,repo))==digest for n,digest in listing.items()),'Every pinned preserved original/proof byte must match')
        expected={n[len('latest/study/'):]:v for n,v in listing.items() if n.startswith('latest/study/')}
        require(len(expected)==178 and f.inventory_tree(original,repo)==expected,'Exact178-file original study backup required')
        manifests=f.seals(original,repo)
        require(len(manifests)==16 and len(f.SEALED)*len(manifests)==112
            and sha(f.regular(original/'hard-experiment-freeze.json',repo))==f.FREEZE
            and sha(f.regular(original/'engines/engine-06-hard-16/engine.log',repo))==f.FAILURE_LOG,'Original frozen16 inputs/15complete/failure evidence required')
        require(not (original/'answers/validity.json').exists() and not any(q.is_file() for q in (original/'decisions').rglob('*')),'Original evaluation/validity must remain absent')
        for relative in (f.STUDY_REL,f.NEW_REL+'/final-study',f.NEW_REL+'/validation-attempt1',f.NEW_REL+'/evaluation-attempt1'):
            require(not (repo/relative).exists() and not (repo/relative).is_symlink(),'Partial analysis appeared; this failed-start cleanup is no longer applicable')
        ledger=f.regular(repo/'runs/servedoctor-ledger.json',repo);require(sha(ledger)==f.SEED,'Canonical H13 ledger changed; never reset/edit it')
        cost=self.service.cost(state);require(cost.get('total_usd_upper',41)<=40,'Current shared upper exceeds$40')
        return {'failed_pipeline':desc(pipeline_path),'queued_start_outcome':desc(response_path),'authorization':desc(exclusion),
            'preservation':desc(preservation),'preserved_manifest':desc(manifest),'original_study_files':178,
            'sealed_payload_files':112,'recording_manifests':16,'completed_recordings':16,'completed_hard_incidents':15,
            'hard16_failure_log':desc(original/'engines/engine-06-hard-16/engine.log'),'original_freeze_sha256':f.FREEZE,
            'canonical_local_ledger':desc(ledger),'manifest_sha256':manifests}

    def selected(self):
        result=set()
        # Explicit trees only: never recurse into prior backup-of-backup folders.
        trees=(self.old/'blocked-hard-study-attempt1',self.old/Path(PIPELINE).parent)
        for folder in trees:
            for relative in f.inventory_tree(folder,self.repo):result.add(folder/relative)
        # Safe direct control/helper/intent/fixture metadata; private filenames
        # are rejected before content access, not read and then redacted.
        for folder in (self.old,self.ops):
            for path in folder.iterdir():
                if path.is_dir() or path==self.backup or path.name=='operation.lock' or path.name.endswith('.tmp'):continue
                result.add(f.regular(path,self.repo))
        return sorted(result)

    def verify(self):
        state=self.scope();proof=self.gate(state);path=self.backup/'backup-receipt.json';receipt=load(f.regular(path,self.repo))
        require(receipt.get('project')==h.LABEL and receipt.get('analysis_label')==f.LABEL and receipt.get('mode')==MODE
            and receipt.get('instance_id')==INSTANCE and receipt.get('rental_scope_sha256')==SCOPE and receipt.get('proof')==proof
            and receipt.get('all_available_local_scientific_evidence_backed_up') is True
            and receipt.get('all_remote_artifacts_backed_up') is False and receipt.get('remote_ops_control_tail_unverified') is True
            and receipt.get('no_partial_validation_or_arm_work_dispatched') is True
            and receipt.get('last_stop_epoch')==state['running_intervals'][-1]['stop_epoch'],'Truthful failed-start backup scope required')
        require(desc(self.backup/'manifest.json')==receipt['manifest'],'Backup manifest changed')
        manifest=load(self.backup/'manifest.json');require(Path(manifest['root'])==self.backup,'Backup root differs')
        for name,digest in manifest['files'].items():
            require(not Path(name).is_absolute() and '..' not in Path(name).parts and sha(f.regular(self.backup/name,self.repo))==digest,'Immutable backup byte changed')
        source=receipt['source_files_sha256'];require(all(manifest['files'].get('payload/'+n)==digest for n,digest in source.items()),'Payload map incomplete')
        require(str((self.old/PIPELINE).relative_to(self.repo)) in source and str(self.service.scope_path.relative_to(self.repo)) in source
            and str(self.service.state_path.relative_to(self.repo)) in source,'Current stopped control/parent evidence missing')
        prefix=str((self.old/'blocked-hard-study-attempt1/latest/study').relative_to(self.repo))+'/'
        expected={prefix+n:v for n,v in f.inventory_tree(self.old/'blocked-hard-study-attempt1/latest/study',self.repo).items()}
        require(all(source.get(n)==v for n,v in expected.items()),'All178 original study files must be backed up')
        before=load(self.backup/'stopped-state.json')
        require(all(before.get(k)==state.get(k) for k in ACCOUNTING),'Stopped accounting changed after backup')
        require(desc(self.backup/'gpu-hours-before-delete.md')==receipt['gpu_hours_snapshot']
            and desc(self.backup/'canonical-local-ledger.json')==receipt['canonical_local_ledger']
            and sha(self.backup/'canonical-local-ledger.json')==f.SEED,'Immutable hours/H13 snapshots differ')
        return state,desc(path)

    def prepare(self,acknowledge=False):
        require(acknowledge,'Explicit acknowledgement of unavailable remote OPS/control tail required')
        with self.service.lock():
            self.service.reconcile();state=self.scope();self.stopped(state);proof=self.gate(state)
            self.backup.mkdir(exist_ok=False)
            try:
                files={};source_files={}
                for path in self.selected():
                    name=path.relative_to(self.repo).as_posix();target=self.backup/'payload'/name;target.parent.mkdir(parents=True,exist_ok=True)
                    digest=sha(path)
                    with path.open('rb') as inp,target.open('xb') as out:shutil.copyfileobj(inp,out)
                    require(sha(target)==digest==sha(path),'Local backup source changed while copied')
                    source_files[name]=digest;files['payload/'+name]=digest
                for path,name in ((self.repo/'runs/servedoctor-gpu-hours.md','gpu-hours-before-delete.md'),
                                  (self.repo/'runs/servedoctor-ledger.json','canonical-local-ledger.json'),
                                  (self.service.state_path,'stopped-state.json')):
                    target=self.backup/name;target.write_bytes(f.regular(path,self.repo).read_bytes());files[name]=sha(target)
                write_new(self.backup/'manifest.json',{'root':str(self.backup),'files':files})
                receipt={'project':h.LABEL,'analysis_label':f.LABEL,'mode':MODE,'instance_id':INSTANCE,'rental_scope_sha256':SCOPE,
                    'last_stop_epoch':state['running_intervals'][-1]['stop_epoch'],'proof':proof,'source_files_sha256':source_files,
                    'all_available_local_scientific_evidence_backed_up':True,'all_remote_artifacts_backed_up':False,
                    'remote_ops_control_tail_unverified':True,'no_partial_validation_or_arm_work_dispatched':True,
                    'disclosure':'Reference and15 completed Hard recordings, original16 frozen specification/keys, hard16 startup failure and local observer/source/provisioning evidence are retained. The unavailable host latest remote OPS/control tail and model cache are not verified or claimed copied.',
                    'manifest':desc(self.backup/'manifest.json'),'gpu_hours_snapshot':desc(self.backup/'gpu-hours-before-delete.md'),
                    'canonical_local_ledger':desc(self.backup/'canonical-local-ledger.json')}
                write_new(self.backup/'backup-receipt.json',receipt);self.verify();return receipt
            except BaseException as error:
                marker=self.backup/'backup-failure.json'
                if not marker.exists():write_new(marker,{'class':type(error).__name__,'partial_backup_retained':True})
                raise

    def finish(self,binding):
        state=self.scope()
        if not state.get('destroyed_epoch'):return {'confirmed_absent':False,'get_only_reconcile_required':True}
        self.stopped(state);final=self.backup/'final-state.json'
        if final.exists():require(load(final)==state,'Final stopped/deleted state changed')
        else:write_new(final,state)
        cost=self.service.cost(state);require(cost.get('total_usd_upper',41)<=40,'Final shared upper exceeds$40')
        receipt={'project':h.LABEL,'instance_id':INSTANCE,'rental_scope_sha256':SCOPE,'mode':MODE,'confirmed_absent':True,
            'destroyed_epoch':state['destroyed_epoch'],'backup_receipt':binding,'final_state':desc(final),
            'host_cost':self.service.host_cost(state,state['destroyed_epoch']),'network_slack_reserved_once':True,
            'all_remote_artifacts_backed_up':False,'remote_ops_control_tail_unverified':True,
            'gpu_accounting':cost,'gpu_hours_log_sha256':sha(self.repo/'runs/servedoctor-gpu-hours.md')}
        path=self.backup/'destroy-receipt.json'
        if path.exists():require(load(path)==receipt,'Final cost/deletion proof differs')
        else:write_new(path,receipt)
        return {'confirmed_absent':True,'receipt':desc(path),'host_cost':receipt['host_cost']}

    def delete(self):
        with self.service.lock():
            require(not (self.backup/'delete-dispatch.json').exists(),'DELETE dispatch already recorded; GET-only reconcile')
            for path in self.old.glob('intent-*-delete.json'):
                require(load(path).get('instance_id')!=INSTANCE,'DELETE already attempted; GET-only reconcile')
            self.service.reconcile();state,binding=self.verify();self.stopped(state)
            require(not state.get('destroyed_epoch'),'Already deleted; GET-only reconcile')
            write_new(self.backup/'delete-dispatch.json',{'project':h.LABEL,'instance_id':INSTANCE,'rental_scope_sha256':SCOPE,
                'method':'DELETE','path':f'/api/v0/instances/{INSTANCE}/','backup_receipt':binding,'helper_sha256':sha(__file__)})
            self.service.intent(state,'delete',f'/api/v0/instances/{INSTANCE}/',reason='Explicit unavailable host cleanup after immutable local original15 scientific backup; remote OPS/control tail unavailable; no partial evaluation dispatched')
            self.service.reconcile();return self.finish(binding)

    def reconcile(self):
        require((self.backup/'delete-dispatch.json').is_file(),'Prior explicit DELETE dispatch required')
        final=self.backup/'destroy-receipt.json'
        if final.exists():
            value=load(f.regular(final,self.repo))
            require(value.get('project')==h.LABEL and value.get('instance_id')==INSTANCE and value.get('rental_scope_sha256')==SCOPE
                and value.get('confirmed_absent') is True and desc(self.backup/'final-state.json')==value['final_state'],'Final deletion receipt differs')
            return {'confirmed_absent':True,'receipt':desc(final),'host_cost':value['host_cost'],'provider_actions':0}
        with self.service.lock():
            self.service.reconcile();_,binding=self.verify();return self.finish(binding)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('operation',nargs='?',default='verify',choices=('verify','prepare','delete','reconcile'))
    parser.add_argument('--backup-dir');parser.add_argument('--acknowledge-unverified-remote-tail',action='store_true');args=parser.parse_args()
    service=h.Rental(**({'api':blocked,'inventory':blocked} if args.operation=='verify' else {}));guard=Cleanup(service,args.backup_dir)
    if args.operation=='verify':
        state=guard.scope();guard.stopped(state);value={'ready':True,'provider_actions':0,'writes':0,'proof':guard.gate(state)}
    elif args.operation=='prepare':value=guard.prepare(args.acknowledge_unverified_remote_tail)
    else:value=getattr(guard,args.operation)()
    print(json.dumps(value));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:raise SystemExit('Inactive recorded-host cleanup refused: '+type(error).__name__) from None
