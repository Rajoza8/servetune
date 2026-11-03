#!/usr/bin/env python3
"""600s fixed-guide restart window for the approved15-case partial analysis.

Sixteen completed recordings (reference plus15Hard), the original16-incident
freeze/keys and hard16 startup failure are locally backed up. Remote OPS/control
tail after that mirror is unknown. No setup/evaluation is dispatched by this
window. Only exhausted600s unauthenticated denial can back up then DELETE once.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

import hard_vast as h
import startup_ssh_window as base
from frozen_host5_ssh_window import FrozenHost5Window
from prepare_next_hard_study import rental_binding

INSTANCE=58866756
SCOPE='c941c466f1e56180a66c6ebe98972c8507c4fa94bee6b3c96a419e3e6eed0b4c'
MODE='partial-analysis-host5-restart'
SOURCE='4b0add12be36cef0d0776607f683310b1641b0f7'
FREEZE='868fa1c8c8be1bba186937839bdeba0bebeaab7f95623c181a72f42ba0120a68'
LEDGER='13f777ed328bb0c71bb2063b6b12cf3b6cb8024d78b0ab46b9e374521a566123'
PRESERVATION='0bb31a20b50ebb5db6c7680f54b22849c76cf007c9b0aa99f6d68bd4dfeb5af8'
MANIFEST='505d7d74d4a978f1de9058380c3d38b85826d7c06affe1d7cffcabe16032d068'
EXCLUSION='783ae7be7b60c35146090911ac03d854ad0e5af366c4a178685dbed670a0d1d9'
STOPPED='4b01fa0a1789447c916ad323fc12ee18ff9d54d285e2d81029b53c7edebeb4b6'
LABEL='ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)'


class PartialAnalysisWindow(FrozenHost5Window):
    def scope(self,plan=None):
        state=base.Window.scope(self,plan)
        if state['instance_id']!=INSTANCE or state['scope_sha256']!=SCOPE:raise ValueError('Only approved partial-analysis host5 is allowed')
        return state

    def historical_evidence(self,binding):
        # Historical evidence is explicitly prior to recording; it makes no
        # claim that the current host has never recorded or holds no raw data.
        return FrozenHost5Window.bootstrap_evidence(self,binding)

    def partial_evidence(self,binding):
        evidence=self.historical_evidence(binding)
        folder=self.root/'blocked-hard-study-attempt1';receipt=folder/'preservation-receipt.json';manifest=folder/'preserved-files-manifest.json'
        exclusion=self.root/'partial-analysis-exclusion-20261102T2306Z.json';stopped=self.root/'partial-analysis-stopped-state.json'
        if (h.sha(receipt)!=PRESERVATION or h.sha(manifest)!=MANIFEST or h.sha(exclusion)!=EXCLUSION or h.sha(stopped)!=STOPPED):
            raise ValueError('Pinned partial preservation/exclusion/stopped evidence changed')
        value=json.loads(receipt.read_text());why=json.loads(exclusion.read_text());state=json.loads(stopped.read_text())
        if (value.get('status')!='BLOCKED_INCOMPLETE' or value.get('completed_recordings')!=16 or value.get('planned_recordings')!=17
                or value.get('freeze_sha256')!=FREEZE or value.get('ledger_sha256')!=LEDGER or value.get('validated') is not False
                or value.get('evaluated') is not False or why.get('analysis_label')!=LABEL
                or why.get('included_hard_ids')!=[f'hard-{i:02d}' for i in range(1,16)] or why.get('excluded_ids')!=['hard-16']
                or why.get('before_validation') is not True or why.get('before_any_hard_arm_evaluation') is not True
                or why.get('hard16_may_be_modified_regenerated_or_rerecorded') is not False
                or why.get('prompts_rules_scoring_answer_keys_unchanged') is not True or why.get('original_freeze_sha256')!=FREEZE
                or state.get('instance_id')!=INSTANCE or state.get('scope_sha256')!=SCOPE or state.get('pending_intent')
                or state.get('destroyed_epoch') or not h.Rental.stopped(state.get('last_status',{}))):
            raise ValueError('Approved15-case exclusion or preserved coverage differs')
        mapping=json.loads(manifest.read_text())['files']
        for relative,digest in mapping.items():
            path=Path(relative)
            if path.is_absolute() or '..' in path.parts or (folder/path).is_symlink() or h.sha(folder/path)!=digest:
                raise ValueError('Available partial mirror bytes changed')
        study=folder/'latest/study'
        if h.sha(study/'hard-experiment-freeze.json')!=FREEZE or h.sha(folder/'latest/canonical-ledger.json')!=LEDGER:
            raise ValueError('Original frozen study or ledger backup differs')
        if h.sha(self.repo/'runs/servedoctor-ledger.json')!=LEDGER:raise ValueError('Local inherited ledger changed before partial evaluation')
        expected={'reference',*[f'hard-{i:02d}' for i in range(1,16)]}
        if {p.name for p in (study/'incidents').iterdir()}!=expected:raise ValueError('Exactly reference plus15 completed recordings required')
        public={'engine_config.json','engine_identity.json','events.json','slo.json','telemetry.jsonl','requests.jsonl','recording.json'}
        for name in expected:
            path=study/'incidents'/name;seal=json.loads((path/'manifest.json').read_text())['files']
            if (set(seal)!=public or {p.name for p in path.iterdir()}!=public|{'manifest.json'}
                    or json.loads((path/'recording.json').read_text()).get('status')!='completed'
                    or any(h.sha(path/n)!=v for n,v in seal.items())):raise ValueError('Preserved partial recording seal differs')
        if (study/'answers/validity.json').exists() or (study/'decisions').exists():raise ValueError('Window evidence must precede partial validation/evaluation')
        for key,path in [('partial_preservation',receipt),('partial_manifest',manifest),('partial_exclusion',exclusion),('stopped_snapshot',stopped),
            ('original_partial_freeze',study/'hard-experiment-freeze.json'),('hard16_failure_log',study/'engines/engine-06-hard-16/engine.log')]:
            evidence[key]=base.descriptor(path)
        return evidence

    def load_plan(self,path):
        path,plan=base.Window.load_plan(self,path)
        if (plan.get('mode')!=MODE or plan.get('partial_analysis_helper_sha256')!=h.sha(__file__)
                or plan.get('no_setup_commands_in_this_window') is not True or plan.get('available_local_recordings')!=16
                or plan.get('raw_partial_study_mirrored') is not True or plan.get('remote_tail_after_partial_mirror_verified') is not False
                or plan.get('analysis_label')!=LABEL or plan.get('timeout_policy')!='backup_available_partial_study_then_delete_after600s_denial'):
            raise ValueError('Partial-analysis window policy differs')
        self.trusted_hosts(plan);state=self.scope(plan);proof=plan['rental_binding']
        binding,checked,_=rental_binding(proof['path'],self.root,state)
        if checked!=proof or self.partial_evidence(binding)!=plan['known_evidence']:raise ValueError('Partial-analysis provenance changed')
        if base.descriptor(path.parent/'frozen-public-source.tar')!=plan['source_archive']:raise ValueError('Frozen source archive changed')
        return path,plan

    def prepare(self,out,rental_proof=None,pipeline_out=None):
        out=Path(out).resolve()
        if (out/'plan.json').exists():return self.load_plan(out/'plan.json')[0]
        if out.parent!=self.root or not re.fullmatch('startup-ssh-window-attempt[1-9][0-9]*',out.name):raise ValueError('Fresh direct startup-window output required')
        state=self.scope();active=self.service.active();now=self.clock()
        if now+690>min(active['deadline_epoch'],h.DEADLINE):raise ValueError('Full600s plus cleanup allowance required')
        if rental_proof is None:raise ValueError('Immutable rental creator proof required')
        binding,proof,_=rental_binding(rental_proof,self.root,state);evidence=self.partial_evidence(binding)
        known=self.root/'known_hosts'
        if known.is_symlink() or not known.is_file():raise ValueError('Reviewed original host key required')
        pipeline=Path(pipeline_out).resolve() if pipeline_out else None
        if pipeline and (pipeline.parent!=self.root or pipeline.is_symlink() or not pipeline.is_dir()):raise ValueError('Current controller output differs')
        out.mkdir(exist_ok=False);original=out/'original-known_hosts';original.write_bytes(known.read_bytes());self.host_rows(original.read_bytes())
        archive=out/'frozen-public-source.tar'
        with archive.open('xb') as stream:
            subprocess.run(['git','archive','--format=tar',SOURCE,'servedoctor','servetune','configs','docs/SERVEDOCTOR_HARD.md','pyproject.toml'],cwd=self.repo,stdout=stream,check=True,timeout=30)
        now=self.clock()
        if now+690>min(active['deadline_epoch'],h.DEADLINE):raise ValueError('Full600s allowance required after local archive')
        plan={'project':h.LABEL,'instance_id':INSTANCE,'rental_scope_sha256':SCOPE,'mode':MODE,'analysis_label':LABEL,
            'started_epoch':now,'deadline_epoch':now+600,'window_seconds':600,'terminal_receipt_path':str(out/'terminal.json'),
            'helper_sha256':h.sha(base.__file__),'partial_analysis_helper_sha256':h.sha(__file__),'allowed_remote_argv':base.ALLOWED_REMOTE_ARGV,
            'no_create_start_attach_retries':True,'no_setup_commands_in_this_window':True,'source_archive':base.descriptor(archive),
            'available_local_recordings':16,'completed_hard_incidents':15,'excluded_ids':['hard-16'],'raw_partial_study_mirrored':True,
            'remote_tail_after_partial_mirror_verified':False,'timeout_policy':'backup_available_partial_study_then_delete_after600s_denial',
            'timeout_loss_disclosure':'All16 available completed recordings, original frozen16-incident inputs and failure are preserved locally. Remote OPS/control tail after the last mirror is unverified and may be lost on explicit600s denial cleanup.',
            'rental_binding':proof,'known_evidence':evidence,'pipeline_out':str(pipeline) if pipeline else None,
            'initial_phase_owner':{k:active[k] for k in ('pid','birth') if k in active},
            'original_known_hosts_sha256':h.sha(known),'original_known_hosts':base.descriptor(original)}
        base.write_new(out/'plan.json',plan);return out/'plan.json'

    def backup(self,out,plan):
        previous=sorted(out.glob('partial-analysis-backup-attempt[0-9]*'))
        for folder in reversed(previous):
            receipt=folder/'receipt.json'
            if not receipt.exists():continue
            try:self.verify_backup(receipt,plan)
            except json.JSONDecodeError:
                marker=out/(folder.name+'-incomplete-receipt.json')
                if not marker.exists():base.write_new(marker,{'retained_partial_receipt':base.descriptor(receipt),'error_class':'JSONDecodeError'})
                continue
            return base.descriptor(receipt)
        numbers=[int(p.name.rsplit('attempt',1)[-1]) for p in previous if re.fullmatch('partial-analysis-backup-attempt[0-9]+',p.name)]
        number=max(numbers,default=0)+1;target=out/f'partial-analysis-backup-attempt{number:04d}';target.mkdir(exist_ok=False)
        selected={self.root/n for n in ('rental-scope.json','session.json','active-command.json','known_hosts')};files={};ephemeral=[]
        directories=[out,self.root/'blocked-hard-study-attempt1',self.root/'record-first9-attempt1',self.root/'record-last8-attempt1',
            self.root/'bootstrap-calibration-controller-attempt8',self.root/'prepare-next-attempt1',self.root/'rearm-frozen-attempt2']
        if plan.get('pipeline_out'):directories.append(Path(plan['pipeline_out']))
        logs=self.root/f'container-logs-{INSTANCE}-startup-window'
        if logs.is_dir():directories.append(logs)
        try:
            for folder in [self.root,*directories]:
                if folder.is_symlink() or not folder.is_dir():raise ValueError('Regular local evidence directory required')
                candidates=list(folder.iterdir()) if folder==self.root else list(folder.rglob('*'))
                for path in candidates:
                    if any(p.name.startswith('partial-analysis-backup-attempt') for p in path.relative_to(self.root).parents):continue
                    if path.name.endswith('.tmp'):ephemeral.append(path.relative_to(self.root).as_posix());continue
                    if path.is_symlink():raise ValueError('Linked partial evidence')
                    if path.is_dir():continue
                    if not path.is_file() or path.name=='operation.lock' or re.search('(^|[-_.])(private|secret|env|identity|key)([-_.]|$)',path.name,re.I):continue
                    if path.suffix in {'.json','.jsonl','.log','.stdout','.stderr','.md','.txt','.gz'}:selected.add(path)
            selected.update(Path(row['path']) for row in plan['known_evidence'].values())
            selected.update(Path(plan[k]['path']) for k in ('rental_binding','original_known_hosts','source_archive'))
            # The complete fixed partial mirror is opaque, including generated
            # answer/runtime bytes; no filename filter may silently omit them.
            selected.update(p for p in (self.root/'blocked-hard-study-attempt1').rglob('*') if p.is_file())
            for source in sorted(selected):
                if source.is_symlink() or not source.resolve().is_relative_to(self.root):raise ValueError('Outside/linked partial backup evidence')
                data=source.read_bytes()
                if b'PRIVATE KEY-----' in data:raise ValueError('Private key cannot enter backup')
                relative=source.relative_to(self.root);destination=target/'payload'/relative;destination.parent.mkdir(parents=True,exist_ok=True)
                with destination.open('xb') as stream:stream.write(data)
                files[relative.as_posix()]=hashlib.sha256(data).hexdigest()
            hours=target/'gpu-hours-before-delete.md';hours.write_bytes((self.repo/'runs/servedoctor-gpu-hours.md').read_bytes())
            ledger=target/'canonical-ledger.json';ledger.write_bytes((self.repo/'runs/servedoctor-ledger.json').read_bytes())
            if h.sha(ledger)!=LEDGER:raise ValueError('Inherited ledger changed before partial evaluation')
            manifest=target/'manifest.json';base.write_new(manifest,{'files_sha256':files,'omitted_ephemeral_tmp':ephemeral})
            receipt={'project':h.LABEL,'instance_id':INSTANCE,'rental_scope_sha256':SCOPE,'mode':MODE,'guide_authenticated':False,
                'plan':base.descriptor(out/'plan.json'),'manifest':base.descriptor(manifest),'gpu_hours_snapshot':base.descriptor(hours),
                'canonical_ledger':base.descriptor(ledger),'known_evidence':plan['known_evidence'],'source_archive':plan['source_archive'],
                'available_local_recordings':16,'completed_hard_incidents':15,'raw_partial_study_mirrored':True,
                'all_available_local_recorded_study_backed_up':True,'all_remote_artifacts_backed_up':False,
                'remote_tail_after_partial_mirror_verified':False,'no_setup_commands_in_this_window':True,
                'timeout_policy':plan['timeout_policy'],'timeout_loss_disclosure':plan['timeout_loss_disclosure']}
            path=target/'receipt.json';base.write_new(path,receipt);self.verify_backup(path,plan);return base.descriptor(path)
        except BaseException as error:
            path=out/f'partial-analysis-backup-failure-attempt{number:04d}.json'
            if not path.exists():base.write_new(path,{'error_class':type(error).__name__,'retained_partial_directory':str(target),'copied_files_sha256':files})
            raise

    def verify_backup(self,path,plan):
        path=Path(path);value=json.loads(path.read_text());target=path.parent
        if (value.get('project')!=h.LABEL or value.get('instance_id')!=INSTANCE or value.get('rental_scope_sha256')!=SCOPE
                or value.get('mode')!=MODE or value.get('guide_authenticated') is not False
                or value.get('plan')!=base.descriptor(target.parent/'plan.json') or value.get('known_evidence')!=plan['known_evidence']
                or value.get('available_local_recordings')!=16 or value.get('completed_hard_incidents')!=15
                or value.get('raw_partial_study_mirrored') is not True or value.get('all_available_local_recorded_study_backed_up') is not True
                or value.get('all_remote_artifacts_backed_up') is not False or value.get('remote_tail_after_partial_mirror_verified') is not False
                or value.get('no_setup_commands_in_this_window') is not True or value.get('timeout_policy')!=plan['timeout_policy']):
            raise ValueError('Truthful partial-analysis backup binding differs')
        manifest=target/'manifest.json'
        if base.descriptor(manifest)!=value['manifest']:raise ValueError('Partial backup manifest differs')
        mapping=json.loads(manifest.read_text())['files_sha256']
        if mapping.get('rental-scope.json')!=SCOPE:raise ValueError('Immutable current scope missing')
        for relative,digest in mapping.items():
            rel=Path(relative)
            if rel.is_absolute() or '..' in rel.parts or (target/'payload'/rel).is_symlink() or h.sha(target/'payload'/rel)!=digest:raise ValueError('Partial backup bytes changed')
        for name,filename in [('gpu_hours_snapshot','gpu-hours-before-delete.md'),('canonical_ledger','canonical-ledger.json')]:
            if base.descriptor(target/filename)!=value[name]:raise ValueError('Partial accounting snapshot differs')
        if value['canonical_ledger']['sha256']!=LEDGER:raise ValueError('Inherited ledger snapshot differs')
        for row in (*plan['known_evidence'].values(),plan['rental_binding'],plan['original_known_hosts'],plan['source_archive']):
            if mapping.get(Path(row['path']).relative_to(self.root).as_posix())!=row['sha256']:raise ValueError('Required partial evidence missing')
        source=self.root/'blocked-hard-study-attempt1';original=json.loads((source/'preserved-files-manifest.json').read_text())['files']
        for relative,digest in original.items():
            if mapping.get('blocked-hard-study-attempt1/'+relative)!=digest:raise ValueError('Opaque partial study evidence missing')

    def exhausted(self,out,plan):return base.Window.exhausted(self,out,plan)


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='operation',required=True)
    prepare=sub.add_parser('prepare');prepare.add_argument('--out',type=Path,required=True);prepare.add_argument('--rental-proof',type=Path,required=True);prepare.add_argument('--pipeline-out',type=Path)
    resume=sub.add_parser('resume');resume.add_argument('--plan',type=Path,required=True);args=parser.parse_args();window=PartialAnalysisWindow()
    if args.operation=='prepare':
        path=window.prepare(args.out,args.rental_proof,args.pipeline_out);print(json.dumps({'plan':base.descriptor(path),'network_or_lifecycle_dispatched':False}));return 0
    guide=window.resume(args.plan);print(json.dumps({'guide_authenticated':guide is not None,'guide_path':str(guide) if guide else None}));return 0 if guide else 2


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:raise SystemExit('Partial-analysis SSH window refused: '+type(error).__name__) from None
