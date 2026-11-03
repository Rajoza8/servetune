#!/usr/bin/env python3
"""Verify the authorized fifteen-case analysis; explicitly back up/delete once.

Default verification is local and read-only. The original full-study finalizer
and Rental.backup remain unchanged. This separate gate admits only the exact
pre-validation user exclusion of unrecordable hard-16. Keys/native reports are
hashed opaquely, never returned. Unknown DELETE outcomes allow GET only.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

OPS=Path(__file__).resolve().parent
REPO=OPS.parent.parent
RENTAL_OPS=REPO/'runs/servedoctor-hard-ops-20261102'
sys.path.insert(0,str(RENTAL_OPS))
import hard_vast as h
import finalize_hard_rental as base

PROJECT=base.PROJECT
ANALYSIS_PROJECT='servedoctor-hard15-20261102'
LABEL='ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)'
INSTANCE=base.INSTANCE
SCOPE=base.SCOPE
SEED=base.SEED
SOURCE=base.SOURCE
FREEZE=base.FREEZE
EXCLUSION='783ae7be7b60c35146090911ac03d854ad0e5af366c4a178685dbed670a0d1d9'
PRESERVATION='0bb31a20b50ebb5db6c7680f54b22849c76cf007c9b0aa99f6d68bd4dfeb5af8'
PRESERVED_MANIFEST='505d7d74d4a978f1de9058380c3d38b85826d7c06affe1d7cffcabe16032d068'
FAILURE_LOG='d4656e6cb398f67d010092509f433d316d185a1ea82063ef58c1eb5631dbae26'
ARMS=base.ARMS
IDS=tuple(f'hard-{i:02d}' for i in range(1,16))
ALL_IDS=('reference',)+IDS
OLD_REL='runs/servedoctor-hard-ops-20261102'
NEW_REL='runs/servedoctor-hard15-ops-20261102'
STUDY_REL='runs/sd-hard-partial-attempt1'
REMOTE='/workspace/servedoctor-hard/servetune/'
SEALED={'engine_config.json','engine_identity.json','events.json','slo.json','telemetry.jsonl','requests.jsonl','recording.json'}
HELPER_SHA256={
    'hard_partial_integrity.py':'eca7c03250aa7b75439ce9b6505c648d4584c3f5fbdba48b341d42ab78b813c5',
    'key_runner.py':'d262566e97f06691cbcedf1ac2b93d5df23f5b3f54be91007a0bd4cfdcc04689',
    'hard_report_common.py':'8c01113fe02b335979807a516e9a5678a34feb87259006d9891aff6a21c8499e',
    'measure_contexts.py':'a2d366f8470a31f07f1da88f8bbc0e2899f7e387bc981f388d0669f91b3a90dc',
    'model_response_guard.py':'68602959e499804a33d28751153347d06973a39361c525587885f150e7c6b92a',
    'export_hard_scores.py':'daf5a37ee9f40356c203cf4a0711b115a272c13d5e281a970b082f96ee3317d3',
    'partial_evaluation_stage.py':'00c07e59a5170812b92f25539c277e175ce23dfd81a9043439a0b44208b3334e'}
MUTABLE=base.MUTABLE
load=base.load
sha=base.sha
desc=base.desc
write_new=base.write_new
require=base.require
blocked=base.blocked


def regular(path,repo):
    path=Path(path).absolute()
    require('..' not in path.parts and path.resolve()==path,'Evidence traversal/link refused')
    name=path.name.lower()
    require(not any(part in name for part in ('api_key','api-key','credentials'))
        and not name.startswith(('id_rsa','id_ed25519','id_ecdsa')),'Credential filename is not evidence')
    return base.regular(path,repo)


def bound(state):
    require(state.get('project')==PROJECT and state.get('instance_id')==INSTANCE and state.get('scope_sha256')==SCOPE,'Rental binding differs')


def paths(args,service):
    repo,old=service.repo.resolve(),service.root.resolve();ops=repo/NEW_REL
    def resolve(value):
        path=Path(value);return path.absolute() if path.is_absolute() else repo/path
    keys=('study_dir','original_dir','evaluation_dir','pipeline_outcome','remote_ops','remote_old_ops','remote_control','ledger','ledger_seed','out')
    p={key:resolve(getattr(args,key)) for key in keys}
    require(p['study_dir']==repo/STUDY_REL,'Only declared partial study allowed')
    require(p['original_dir']==old/'blocked-hard-study-attempt1/latest/study','Only preserved original study allowed')
    require(p['evaluation_dir']==ops/'evaluation-attempt1' and p['pipeline_outcome']==old/'partial-resume-pipeline-attempt1/outcome.json','Only approved completed analysis phase allowed')
    require(p['out'].parent==ops and not p['out'].is_symlink() and re.fullmatch('[a-z0-9][a-z0-9-]{0,95}',p['out'].name),'Direct fresh OPS15 output required')
    for key in ('remote_ops','remote_old_ops','remote_control'):
        folder=p[key];require(folder.is_relative_to(ops) and folder.is_dir() and not folder.is_symlink(),'Explicit final local mirror required')
        require(not p['out'].is_relative_to(folder) and folder!=p['out'],'Output overlaps evidence')
    p.update(repo=repo,ops=ops,old_ops=old,hours=repo/'runs/servedoctor-gpu-hours.md',
             exclusion=old/'partial-analysis-exclusion-20261102T2306Z.json',
             preservation=old/'blocked-hard-study-attempt1/preservation-receipt.json',
             preserved_manifest=old/'blocked-hard-study-attempt1/preserved-files-manifest.json')
    return p


class Evidence:
    """Resolve original remote descriptors only through explicit local mirrors."""
    def __init__(self,p):self.p=p
    def resolve(self,value):
        name=value['path'];path=Path(name);p=self.p
        if name.startswith(REMOTE):
            relative=name[len(REMOTE):]
            mappings=((STUDY_REL,p['study_dir']),('runs/sd-hard',p['original_dir']),
                      (NEW_REL,p['remote_ops']),(OLD_REL,p['remote_old_ops']))
            for prefix,folder in mappings:
                if relative==prefix or relative.startswith(prefix+'/'):
                    path=folder/relative[len(prefix):].lstrip('/');break
            else:raise ValueError('Remote descriptor has no explicit local mirror')
        elif name.startswith('/workspace/servedoctor-hard/control/'):
            path=p['remote_control']/name[len('/workspace/servedoctor-hard/control/'):]
        path=regular(path,p['repo']);require(sha(path)==value['sha256'],'Descriptor bytes differ')
        return path
    def read(self,value):return load(self.resolve(value))


def inventory_tree(folder,repo):
    require(folder.is_dir() and not folder.is_symlink(),'Regular evidence tree required')
    result={}
    for q in sorted(folder.rglob('*')):
        require(not q.is_symlink(),'Linked evidence tree')
        if q.is_dir():continue
        result[q.relative_to(folder).as_posix()]=sha(regular(q,repo))
    return result


def seals(root,repo):
    require({q.name for q in (root/'incidents').iterdir()}==set(ALL_IDS),'Exactly reference plus15 completed Hard recordings required')
    manifests={}
    for incident in ALL_IDS:
        folder=root/'incidents'/incident
        require(not folder.is_symlink() and {q.name for q in folder.iterdir()}==SEALED|{'manifest.json'},'Exact recording file set required')
        manifest=load(regular(folder/'manifest.json',repo))['files']
        require(set(manifest)==SEALED and all(sha(regular(folder/name,repo))==digest for name,digest in manifest.items()),'Recording seal differs')
        require(load(folder/'recording.json').get('status')=='completed','Recording is incomplete')
        manifests[incident]=sha(folder/'manifest.json')
    return manifests


def authorization(p):
    for name,digest in (('exclusion',EXCLUSION),('preservation',PRESERVATION),('preserved_manifest',PRESERVED_MANIFEST)):
        require(sha(regular(p[name],p['repo']))==digest,'Original authorization/preservation proof differs')
    value=load(p['exclusion'])
    require(value.get('analysis_label')==LABEL and value.get('included_hard_ids')==list(IDS) and value.get('excluded_ids')==['hard-16']
        and value.get('before_validation') is True and value.get('before_any_hard_arm_evaluation') is True
        and value.get('prompts_rules_scoring_answer_keys_unchanged') is True
        and value.get('native_validity_must_not_be_rewritten') is True and value.get('full_hard_set_claim_permitted') is False
        and value.get('hard16_may_be_modified_regenerated_or_rerecorded') is False
        and value.get('original_source_commit')==SOURCE and value.get('original_freeze_sha256')==FREEZE
        and value.get('original_preservation_receipt',{}).get('sha256')==PRESERVATION
        and value.get('limits')=={'gpu_total_usd':40,'meta_ledger_cap_usd':50,'baseten_ledger_cap_usd':20,
            'analysis_cutoff_utc':'2026-11-03T23:00:00Z','paid_calls_finish_cutoff_utc':'2026-11-04T04:59:59Z',
            'optional_live_runs_minimum_gpu_budget_remaining_usd':5},'Exact user partial-analysis scope required')
    return value


def scientific(p):
    evidence=Evidence(p);authorization(p);root=p['study_dir'];original=p['original_dir'];repo=p['repo']
    origin=inventory_tree(original,repo)
    preserved=load(p['preserved_manifest'])['files'];prefix='latest/study/'
    require({name[len(prefix):]:digest for name,digest in preserved.items() if name.startswith(prefix)}==origin,'Pinned original opaque preservation inventory differs')
    require(not (original/'answers/validity.json').exists() and not any(q.is_file() or q.is_symlink() for q in (original/'decisions').rglob('*')),'Original16 analysis evidence must remain unevaluated')
    require(sha(regular(original/'hard-experiment-freeze.json',repo))==FREEZE
        and sha(regular(original/'engines/engine-06-hard-16/engine.log',repo))==FAILURE_LOG,'Original freeze/startup failure differs')
    protocol=load(regular(root/'analysis-protocol.json',repo))
    require(protocol.get('project')==ANALYSIS_PROJECT and protocol.get('label')==LABEL and protocol.get('study_dir')==STUDY_REL
        and protocol.get('original_study_dir')=='runs/sd-hard' and protocol.get('source_commit')==SOURCE
        and protocol.get('included_hard_ids')==list(IDS) and protocol.get('excluded_ids')==['hard-16']
        and protocol.get('scientific_inputs_changed') is False and protocol.get('old_helpers_changed') is False
        and protocol.get('reference_and_hard_recordings')==16 and protocol.get('original_inventory_sha256')==origin,'Partial lineage differs')
    require(sha(evidence.resolve(protocol['exclusion']))==EXCLUSION and sha(evidence.resolve(protocol['preservation']))==PRESERVATION
        and sha(evidence.resolve(protocol['original_freeze']))==FREEZE,'Partial authorization descriptors differ')
    for relative,digest in origin.items():require(sha(regular(root/relative,repo))==digest,'Copied original scientific byte changed')
    require((root/'analysis-label.txt').read_text()==LABEL+'\n','Partial label differs')
    frozen=load(regular(root/'hard-experiment-freeze.json',repo))
    require(sha(root/'hard-experiment-freeze.json')==FREEZE and frozen.get('source_commit')==SOURCE,'Frozen source differs')
    for relative,digest in frozen['files_sha256'].items():
        if relative.startswith(OLD_REL+'/'):require(sha(regular(p['remote_old_ops']/relative[len(OLD_REL)+1:],repo))==digest,'Original private source mirror differs')
    require(protocol.get('private_helpers_sha256')==HELPER_SHA256,'Tested partial helper commitments differ')
    for name,digest in protocol['private_helpers_sha256'].items():
        require('/' not in name and sha(regular(p['remote_ops']/name,repo))==digest,'Amended helper mirror differs')
    manifests=seals(root,repo);require(seals(original,repo)==manifests,'Original and partial recording seals differ')
    # Validation is immutable native output. Only its safe counts are returned.
    marker=load(regular(root/'hard-partial-validation-dispatch.json',repo));dispatch=evidence.read(marker['dispatch'])
    directory=evidence.resolve(marker['dispatch']).parent
    result=load(regular(directory/'result.json',repo));quality=evidence.read(dispatch['quality'])
    require(marker.get('project')==ANALYSIS_PROJECT and marker.get('label')==LABEL
        and dispatch.get('project')==ANALYSIS_PROJECT and dispatch.get('label')==LABEL and dispatch.get('study_dir')==STUDY_REL
        and sha(evidence.resolve(dispatch['protocol']))==sha(root/'analysis-protocol.json')
        and result.get('project')==ANALYSIS_PROJECT and result.get('label')==LABEL and result.get('completed') is True
        and result.get('returncode')==0 and not result.get('failure') and result.get('dispatch')==marker['dispatch']
        and result.get('study_dispatch_sha256')==sha(root/'hard-partial-validation-dispatch.json')
        and result.get('stdout_sha256')==sha(regular(directory/'validate.stdout',repo))
        and result.get('stderr_sha256')==sha(regular(directory/'validate.stderr',repo)),'One-shot native validation incomplete')
    validity_path=regular(root/'answers/validity.json',repo);validity=load(validity_path);rows=validity.get('incidents',[])
    require(type(validity.get('total')) is int and validity['total']==15 and len(rows)==15 and {v.get('id') for v in rows}==set(IDS)
        and all(type(v.get('valid')) is bool for v in rows) and type(validity.get('valid')) is int
        and validity['valid']==sum(v['valid'] for v in rows) and result.get('total')==15 and result.get('valid')==validity['valid']
        and result.get('invalid')==15-validity['valid'] and sha(evidence.resolve(result['validity']))==sha(validity_path),'Exactly15 immutable native verdicts required')
    require(quality.get('complete') is True and quality.get('project')==ANALYSIS_PROJECT and quality.get('label')==LABEL
        and quality.get('expected_recordings')==16 and quality.get('hard_incidents')==15
        and quality.get('protocol_sha256')==sha(root/'analysis-protocol.json')
        and len(quality.get('recordings',[]))==16 and {v.get('id') for v in quality['recordings']}==set(ALL_IDS)
        and all(v.get('complete') is True and v.get('manifest_sha256')==manifests[v['id']] for v in quality['recordings'])
        and dispatch.get('manifests')==manifests,'Included structural quality incomplete')
    expected={f'incidents/{name}/{item}':sha(root/'incidents'/name/item) for name in ALL_IDS for item in SEALED|{'manifest.json'}}
    expected.update({f'answers/runtime/{name}.json':sha(regular(root/'answers/runtime'/(name+'.json'),repo)) for name in ALL_IDS})
    require(dispatch.get('recording_bytes_sha256')==expected,'Validated recording/runtime bytes changed')
    require(quality.get('owned_observer_proofs')==protocol.get('owned_proofs') and len(protocol.get('owned_proofs',[]))==3,'Original observer proof coverage differs')
    for item in protocol['owned_proofs']:
        owned=evidence.read(item);evidence.resolve(owned['observations']);evidence.resolve(owned['readiness'])
        require(owned.get('finished') is True and not owned.get('issues') and not owned.get('owned_leaks'),'Original observer proof incomplete')
    return {'manifests':manifests,'valid':validity['valid'],'validation_sha256':sha(directory/'result.json'),'protocol_sha256':sha(root/'analysis-protocol.json')}


def results(p,science):
    repo,root,directory=p['repo'],p['study_dir'],p['evaluation_dir'];evidence=Evidence(p)
    evaluation=load(regular(directory/'outcome.json',repo))
    require(evaluation.get('project')==ANALYSIS_PROJECT and evaluation.get('label')==LABEL and evaluation.get('study_dir')==STUDY_REL
        and evaluation.get('completed') is True and not evaluation.get('failure') and not evaluation.get('cleanup_errors')
        and evaluation.get('groups')==['rules-spark-wonder','glimmer-cascades'],'Both completed analysis groups required')
    gate=load(regular(directory/'integrity-preflight.stdout',repo))
    require(gate.get('project')==ANALYSIS_PROJECT and gate.get('label')==LABEL and gate.get('evaluation_ready') is True
        and gate.get('total')==15 and gate.get('protocol_sha256')==science['protocol_sha256']
        and gate.get('validation_sha256')==science['validation_sha256'],'Native evaluation gate differs')
    context=load(regular(directory/'contexts.json',repo))
    require(context.get('project')==ANALYSIS_PROJECT and context.get('label')==LABEL and context.get('incidents')==15
        and context.get('fits_8192') is True and context.get('context_tokens')==8192
        and context.get('model_revision')=='cec94fcfd6512f2cfe708138c32533b346ea4f69'
        and set(context.get('per_incident_maximum',{}))==set(IDS) and context.get('public_manifests_sha256')==science['manifests']
        and context.get('freeze_sha256')==FREEZE and context.get('validation')==gate
        and context.get('helper_sha256')==HELPER_SHA256['measure_contexts.py'],'Genuine frozen context proof incomplete')
    decision_hashes={}
    for arm in ARMS:
        folder=root/'decisions'/arm
        require(folder.is_dir() and not folder.is_symlink() and {q.name for q in folder.iterdir()}=={name+'.json' for name in IDS},'Exactly15 final decisions per arm required')
        decision_hashes[arm]={name:sha(regular(folder/(name+'.json'),repo)) for name in IDS}
    for label,arms in (('rules-spark-wonder',('rules','spark','wonder')),('glimmer-cascades',('glimmer','glimmer_to_spark','glimmer_to_wonder'))):
        response=load(regular(directory/(label+'-responses.json'),repo))
        require(response.get('project')==ANALYSIS_PROJECT and response.get('label')==LABEL and response.get('ready_for_next_group') is True
            and set(response.get('by_arm',{}))==set(arms) and response.get('validation')==gate
            and response.get('helper_sha256')==HELPER_SHA256['model_response_guard.py'],'Genuine response group incomplete')
        for arm,entry in response['by_arm'].items():
            rows=entry.get('per_incident',[])
            require(entry.get('ready_for_next_group') is True and entry.get('incidents')==15 and entry.get('call_failures')==0
                and len(rows)==15 and {v.get('id') for v in rows}==set(IDS)
                and all(v.get('call_failures')==0 and v.get('decision_sha256')==decision_hashes[arm][v['id']] for v in rows),'Response/decision proof differs')
            if arm in ('glimmer','spark','wonder'):
                require(entry.get('incidents_with_successful_response')==15 and all(v.get('successful_responses',0)>0 for v in rows),'Every direct model incident requires a genuine response')
    projection=load(regular(directory/'hard15-score-projection.json',repo))
    require(projection.get('project')==ANALYSIS_PROJECT and projection.get('label')==LABEL
        and projection.get('decision_coverage')=={'expected':90,'present':90} and projection.get('valid_cases')==science['valid']
        and projection.get('invalid_cases')==15-science['valid'] and projection.get('final_decisions_sha256')==decision_hashes
        and projection.get('validity_sha256')==sha(root/'answers/validity.json') and projection.get('freeze_sha256')==FREEZE
        and projection.get('validation')==gate and projection.get('helper_sha256')==HELPER_SHA256['export_hard_scores.py']
        and set(projection.get('scoreboards',{}))=={'all','valid_only'}
        and set(projection['scoreboards']['all'])==set(ARMS)
        and set(projection['scoreboards']['valid_only'])==(set(ARMS) if science['valid'] else set())
        and len(projection.get('per_case',[]))==90,'Both canonical scoreboards and final decision coverage required')
    for key,filename in (('all','final-score-all.stdout'),('valid_only','final-score-valid_only.stdout')):
        scores=load(regular(directory/filename,repo))
        require(set(scores)==set(projection['scoreboards'][key])
            and all(all(scores[arm].get(metric)==value for metric,value in row.items()) for arm,row in projection['scoreboards'][key].items()),'Canonical score stdout differs from safe projection')
    # Native reports are opaque. The labelled wrapper binds their exact bytes.
    report=load(regular(root/'analysis-report.json',repo))
    require(report.get('project')==ANALYSIS_PROJECT and report.get('label')==LABEL
        and sha(evidence.resolve(report['native_report_html']))==sha(regular(root/'report.html',repo))
        and sha(evidence.resolve(report['native_report_json']))==sha(regular(root/'report.json',repo))
        and sha(evidence.resolve(report['score_projection']))==sha(directory/'hard15-score-projection.json')
        and report.get('scoreboards')==projection['scoreboards'],'Labelled native report binding differs')
    regular(root/'analysis-report.html',repo)
    return evaluation


def readiness(args,service):
    p=paths(args,service);state=service.load();bound(state)
    require(sha(service.scope_path)==SCOPE and not state.get('destroyed_epoch') and base.stopped(state),'Observed stopped rental with closed intervals required')
    pipeline=load(regular(p['pipeline_outcome'],p['repo']))
    require(pipeline.get('project')==PROJECT and pipeline.get('instance_id')==INSTANCE and pipeline.get('rental_scope_sha256')==SCOPE
        and pipeline.get('returncode')==0 and pipeline.get('stop_confirmed') is True and pipeline.get('cleanup_confirmed') is True
        and not pipeline.get('watchdog_cleanup_error_class'),'Completed stopped parent with quiescent watchdog required')
    science=scientific(p);evaluation=results(p,science)
    ledger=regular(p['ledger'],p['repo']);summary=base.ledger_summary(ledger,regular(p['ledger_seed'],p['repo']))
    final=load(regular(p['evaluation_dir']/'final-ledger.stdout',p['repo']))
    require(final.get('sha256')==sha(ledger) and final.get('summary')==summary and not summary['warnings'],'Authoritative final GPU ledger proof differs or warns')
    mirror=load(regular(p['evaluation_dir']/'mirror-manifest.json',p['repo']));actual=inventory_tree(p['study_dir'],p['repo'])
    require(mirror.get('stable') is True and mirror.get('study_files_sha256')==actual and mirror.get('study_file_count')==len(actual)
        and mirror.get('ledger_sha256')==sha(ledger) and evaluation.get('opaque_mirror',{}).get('manifest_sha256')==sha(p['evaluation_dir']/'mirror-manifest.json'),'Stable full partial-study/ledger mirror differs')
    require(sha(regular(p['remote_control']/'rental-scope.json',p['repo']))==SCOPE,'Final control scope differs')
    cost=service.cost(state);require(cost.get('total_usd_upper',41)<=40,'Shared GPU upper exceeds$40')
    return p,state,{'project':PROJECT,'analysis_project':ANALYSIS_PROJECT,'label':LABEL,'instance_id':INSTANCE,'rental_scope_sha256':SCOPE,
        'ready':True,'authorization':desc(p['exclusion']),'original_preservation':desc(p['preservation']),
        'original_freeze_sha256':FREEZE,'excluded_ids':['hard-16'],'recordings':16,'hard_incidents':15,'final_decisions':90,
        'pipeline_outcome':desc(p['pipeline_outcome']),'evaluation_outcome':desc(p['evaluation_dir']/'outcome.json'),
        'final_remote_ledger_proof':desc(p['evaluation_dir']/'final-ledger.stdout'),'canonical_ledger_sha256':sha(ledger),
        'remote_ledger_sha256':final['sha256'],'ledger_summary':summary,'last_stop_epoch':state['running_intervals'][-1]['stop_epoch'],
        'owned_work_quiescent':True,'gpu_accounting':cost}


def inventory(p):
    selected={regular(p['ledger'],p['repo']),regular(p['old_ops']/'rental-scope.json',p['repo']),
              regular(p['exclusion'],p['repo']),regular(p['preservation'],p['repo']),regular(p['preserved_manifest'],p['repo'])}
    for folder in (p['study_dir'],p['original_dir'],p['evaluation_dir'],p['pipeline_outcome'].parent,p['remote_ops'],p['remote_old_ops'],p['remote_control']):
        for relative in inventory_tree(folder,p['repo']):
            path=folder/relative
            if not path.is_relative_to(p['study_dir']) and not path.is_relative_to(p['original_dir']) and (path.name in MUTABLE or path.name.endswith('.tmp')):continue
            selected.add(regular(path,p['repo']))
    return {str(path.relative_to(p['repo'])):sha(path) for path in sorted(selected)}


def verify_backup(path,p,state,service):
    receipt=load(regular(path,p['repo']));bound(state)
    require(receipt.get('project')==PROJECT and receipt.get('analysis_project')==ANALYSIS_PROJECT and receipt.get('label')==LABEL
        and receipt.get('instance_id')==INSTANCE and receipt.get('rental_scope_sha256')==SCOPE
        and receipt.get('all_remote_artifacts_backed_up') is True and receipt.get('last_stop_epoch')==state['running_intervals'][-1]['stop_epoch']
        and receipt.get('authorization')==desc(p['exclusion']) and receipt.get('original_preservation')==desc(p['preservation']),'Partial backup scope differs')
    manifest=receipt['evidence_manifest'];require(desc(regular(manifest['path'],p['repo']))==manifest,'Backup manifest changed')
    value=load(manifest['path']);require(Path(value['root']).resolve()==p['repo'],'Backup manifest root differs')
    for name,digest in value['files'].items():require(not Path(name).is_absolute() and '..' not in Path(name).parts and sha(regular(p['repo']/name,p['repo']))==digest,'Backup evidence changed')
    snapshot=receipt['gpu_hours_snapshot'];require(desc(regular(snapshot['path'],p['repo']))==snapshot,'Hours snapshot differs')
    required=inventory(p);required[str(Path(snapshot['path']).relative_to(p['repo']))]=snapshot['sha256']
    require(value['files']==required,'Whole explicit partial/original/final mirror inventory required')
    ledger=receipt['canonical_ledger'];require(ledger['sha256']==sha(p['ledger'])==ledger['remote_sha256'] and Path(ledger['path'])==p['ledger'],'Authoritative ledger backup differs')
    scientific(p)  # Narrow15-case gate; h.Rental.backup's full17 gate stays unchanged.
    state['delete_backup_receipt']=desc(path)
    return receipt


def prepare(args,service):
    p,state,proof=readiness(args,service);out=p['out'];out.mkdir(exist_ok=False)
    write_new(out/'readiness.json',proof)
    hours=out/'gpu-hours-before-delete.md';hours.write_bytes(regular(p['hours'],p['repo']).read_bytes())
    files=inventory(p);files[str(hours.relative_to(p['repo']))]=sha(hours)
    manifest=out/'backup-manifest.json';write_new(manifest,{'root':str(p['repo']),'files':files})
    after=inventory(p);after[str(hours.relative_to(p['repo']))]=sha(hours);require(after==files,'Final evidence changed during backup')
    receipt={'project':PROJECT,'analysis_project':ANALYSIS_PROJECT,'label':LABEL,'instance_id':INSTANCE,'rental_scope_sha256':SCOPE,
        'authorization':desc(p['exclusion']),'original_preservation':desc(p['preservation']),'all_remote_artifacts_backed_up':True,
        'backup_scope':'Entire authorized partial analysis, unchanged locally preserved original16 specification/reference+15 recordings/failed hard16 engine, final GPU ledger, supplied complete final OPS15/oldOPS/control mirrors; unrelated model caches excluded.',
        'original_frozen_incidents':16,'completed_hard_incidents':15,'excluded_ids':['hard-16'],'final_decisions':90,
        'last_stop_epoch':proof['last_stop_epoch'],'evidence_manifest':desc(manifest),'gpu_hours_snapshot':desc(hours),
        'canonical_ledger':{'path':str(p['ledger']),'sha256':proof['canonical_ledger_sha256'],'remote_sha256':proof['remote_ledger_sha256']},
        'readiness':desc(out/'readiness.json'),'owned_work_quiescent':True}
    path=out/'backup-receipt.json';write_new(path,receipt);verify_backup(path,p,state,service)
    return {'prepared':True,'backup_receipt':desc(path),'files':len(files),'provider_actions':0}


def finish(args,service):
    p=paths(args,service);out=p['out'];state=service.load();bound(state);intents=base.delete_intents(p['old_ops'])
    if not state.get('destroyed_epoch'):return {'confirmed_absent':False,'get_only_next':True,'pending_intent':bool(state.get('pending_intent'))}
    require(len(intents)==1 and not state.get('pending_intent') and base.stopped(state),'Absence requires stopped DELETE lineage')
    cleanup=out/'cleanup.json'
    if cleanup.exists():return {'confirmed_absent':True,'cleanup':desc(cleanup),'get_only_next':True}
    reconciliation=out/f'delete-reconciliation-{len(list(out.glob("delete-reconciliation-*.json")))+1:04d}.json'
    write_new(reconciliation,{'instance_id':INSTANCE,'status':state['last_status'],'destroyed_epoch':state['destroyed_epoch'],'pending_intent':None})
    final=out/'final-state.json'
    if final.exists():require(load(final)==state,'Prior final state differs')
    else:write_new(final,state)
    proof=load(out/'readiness.json');require(sha(p['ledger'])==proof['canonical_ledger_sha256'],'Authoritative GPU ledger changed')
    intent=intents[0];outcome=intent.with_name(intent.stem+'-outcome.json');require(outcome.is_file(),'DELETE outcome missing; preserve unknown state')
    cost=service.cost(state);require(cost.get('total_usd_upper',41)<=40,'Final shared GPU upper exceeds$40')
    value={'project':PROJECT,'analysis_project':ANALYSIS_PROJECT,'label':LABEL,'instance_id':INSTANCE,'rental_scope_sha256':SCOPE,
        'authorization':desc(p['exclusion']),'original_preservation':desc(p['preservation']),'excluded_ids':['hard-16'],
        'confirmed_absent':True,'stopped_confirmed':True,'owned_work_quiescent':True,'destroyed_epoch':state['destroyed_epoch'],
        'backup_receipt':desc(out/'backup-receipt.json'),'delete_intent':desc(intent),'delete_outcome':desc(outcome),
        'delete_reconciliation':desc(reconciliation),'final_state':desc(final),'canonical_ledger_sha256':proof['canonical_ledger_sha256'],
        'remote_ledger_sha256':proof['remote_ledger_sha256'],'ledger_summary':proof['ledger_summary'],
        'gpu_accounting':cost,'gpu_hours_log_sha256':sha(p['hours'])}
    write_new(cleanup,value);return {'confirmed_absent':True,'cleanup':desc(cleanup)}


def execute(args,service=None):
    service=service or h.Rental(**({} if args.delete or args.reconcile else {'api':blocked,'inventory':blocked}))
    if args.prepare_backup:return prepare(args,service)
    if args.reconcile:
        p=paths(args,service)
        if (p['out']/'cleanup.json').exists():return {'confirmed_absent':True,'cleanup':desc(p['out']/'cleanup.json'),'provider_actions':0}
        require((p['out']/'delete-dispatch.json').is_file(),'Prior explicit DELETE dispatch required')
        with service.lock():service.reconcile()
        return finish(args,service)
    p,state,proof=readiness(args,service);backup=p['out']/'backup-receipt.json'
    if not args.delete:
        if backup.exists():verify_backup(backup,p,state,service)
        return {**proof,'backup_verified':backup.exists(),'provider_actions':0,'writes':0}
    require(p['out'].is_dir() and backup.is_file(),'Prepare and inspect partial backup beforeDELETE')
    verify_backup(backup,p,state,service)
    with service.lock():
        service.reconcile();p,state,_=readiness(args,service)
        require(not base.delete_intents(p['old_ops']) and not (p['out']/'delete-dispatch.json').exists(),'DELETE attempted: GET-only reconcile')
        verify_backup(backup,p,state,service)
        write_new(p['out']/'delete-dispatch.json',{'project':PROJECT,'analysis_project':ANALYSIS_PROJECT,'label':LABEL,
            'instance_id':INSTANCE,'rental_scope_sha256':SCOPE,'method':'DELETE','path':f'/api/v0/instances/{INSTANCE}/',
            'authorization':desc(p['exclusion']),'backup_receipt':desc(backup),'helper_sha256':sha(__file__)})
        verify_backup(backup,p,state,service)
        service.intent(state,'delete',f'/api/v0/instances/{INSTANCE}/',reason='Explicit final cleanup after verified authorized fifteen-case partial analysis backup')
        service.reconcile()
    return finish(args,service)


def main():
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group()
    for name in ('verify-only','prepare-backup','delete','reconcile'):mode.add_argument('--'+name,action='store_true')
    defaults={'study-dir':REPO/STUDY_REL,'original-dir':RENTAL_OPS/'blocked-hard-study-attempt1/latest/study',
        'evaluation-dir':OPS/'evaluation-attempt1','pipeline-outcome':RENTAL_OPS/'partial-resume-pipeline-attempt1/outcome.json',
        'remote-ops':OPS/'final-remote-ops','remote-old-ops':OPS/'final-remote-old-ops','remote-control':OPS/'final-remote-control',
        'ledger':OPS/'evaluation-attempt1/final-canonical-ledger.json','ledger-seed':RENTAL_OPS/'prepare-next-attempt1/upload/ledger.seed',
        'out':OPS/'final-partial-cleanup-attempt1'}
    for name,value in defaults.items():parser.add_argument('--'+name,default=str(value))
    print(json.dumps(execute(parser.parse_args())))


if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit('Partial rental cleanup refused: '+type(error).__name__) from None
