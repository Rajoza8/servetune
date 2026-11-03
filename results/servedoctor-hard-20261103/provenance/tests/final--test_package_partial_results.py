"""Invented temporary studies, labels, ledgers and receipts; no real data/actions."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import package_partial_results as p
import shutil
import test_hard_integrity as fixtures


def put(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value)+'\n')
def lines(path,rows):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(''.join(json.dumps(r)+'\n' for r in rows))


class PackageFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.repo=Path(self.temp.name).resolve()
        self.ops=self.repo/p.OLD_OPS_REL;self.ops.mkdir(parents=True);self.study=self.repo/p.PRIMARY
        self.remote=self.ops/'final-remote-ops';self.remote.mkdir();self.control=self.ops/'final-remote-control';self.control.mkdir()
        self.partial=self.repo/p.OPS_REL;self.partial.mkdir(parents=True);self.partial_remote=self.partial/'final-remote-ops';self.partial_remote.mkdir();self.original=self.ops/'original-mirror';
        self.cal=self.ops/'calibration-mirror';self.cal.mkdir();self.evaluation=self.partial_remote/'evaluation-stages/evaluation1';self.evaluation.mkdir(parents=True)
        scope={'project':p.RENTAL_PROJECT,'instance_id':60000001};put(self.control/'rental-scope.json',scope)
        put(self.ops/'rental-scope.json',scope)
        self.scope=p.sha(self.control/'rental-scope.json');self.head='a'*40
        for name,value in [('HEAD',self.head),('SCOPE',self.scope),('INSTANCE',60000001),('GPU',fixtures.GPU)]:
            patch.object(p,name,value).start()
        self.addCleanup(patch.stopall)
        source=Path(p.__file__);self.helper=self.ops/'package_partial_results.py';self.helper.write_bytes(source.read_bytes());patch.object(p,'__file__',str(self.helper)).start()
        config={'set':'hard','capacity_rps':None,'fixture':True};put(self.repo/'configs/servedoctor-hard.json',config);self.config=p.sha(self.repo/'configs/servedoctor-hard.json');patch.object(p,'CONFIG',self.config).start()
        study={**config,'capacity_rps':6};put(self.study/'study.json',study)
        self.specs=[fixtures.case(n) for n in p.ALL_IDS]
        for spec in self.specs:spec['duration_s']=60
        scenarios={'set':'hard','study_sha256':p.legacy.digest(study),'scenarios':self.specs+[{**fixtures.case('hard-16'),'duration_s':60}]};put(self.study/'scenarios.json',scenarios)
        answers={'study_sha256':p.legacy.digest(study),'answers':[{'id':n,'split':'hard','root_cause':'healthy','onset_s':None,'severity_index':0,'private_canary':'ANSWER_MUST_NOT_ESCAPE'} for n in (*p.IDS,'hard-16')]}
        put(self.study/'answers/answer_keys.json',answers)
        commitment={'scenarios_sha256':p.legacy.digest(scenarios),'answer_keys_sha256':p.legacy.digest(answers)};put(self.study/'commitment.json',commitment)
        for spec in self.specs:fixtures.record(self.study,spec)
        (self.study/'report.json').write_bytes(b'opaque native report deliberately not JSON MODEL_TEXT_MUST_NOT_ESCAPE\n')
        (self.study/'report.html').write_text('opaque report MODEL_TEXT_MUST_NOT_ESCAPE')
        self.ready=self.remote/'preflight-readiness.json';cal=self.cal/'runs/sd-hard-calibration-attempt1/calibration.json';put(cal,{'status':'completed','capacity_rps':6})
        put(self.ready,{'recording_ready':True,'declared_before_generation':True,'source_commit':self.head,'config_sha256':self.config,'gpu_uuid':p.GPU,'rental_scope_sha256':self.scope})
        core=p.OLD_OPS_REL+'/hard_integrity.py';mirror_gate=self.remote/'hard_integrity.py';mirror_gate.write_bytes(Path(p.legacy.__file__).read_bytes())
        frozen=fixtures.frozen();frozen.update(source_commit=self.head,study_dir='runs/sd-hard',model_revision=p.legacy.REV,
            scientific_commitments=commitment,files_sha256={core:p.sha(mirror_gate),'configs/servedoctor-hard.json':self.config,
            **{f'runs/sd-hard/{n}':p.sha(self.study/n) for n in ['study.json','scenarios.json','commitment.json','answers/answer_keys.json']}},
            preflight=self.d(self.ready),calibration=self.d(cal),calibration_provenance={'calibration':self.d(cal)},
            optional_transport_sha256={n:None for n in p.legacy.TRANSPORT},reason_receipt=None)
        frozen['job_policy']['rental_scope_sha256']=self.scope
        put(self.study/p.legacy.FREEZE,frozen);self.frozen=frozen;self.freeze=p.sha(self.study/p.legacy.FREEZE);patch.object(p,'FREEZE',self.freeze).start()
        self.quality_dir=self.partial_remote/'validation-attempt1';self.quality_dir.mkdir()
        phase=self.remote/'record-stages/record1/00-all';phase.mkdir(parents=True)
        physical={**fixtures.physical(frozen),'instance_id':60000001}
        ready={'project':p.RENTAL_PROJECT,'source_commit':self.head,'freeze_sha256':self.freeze,'selected_ids':list(p.ALL_IDS),
            'recorder_pid':100,'recorder_start_ticks':111,'selected_incident_directories_absent':True,'ready_before_source_job_timers':True,'physical_gpu_binding':physical}
        put(phase/'observer-ready.json',ready);lines(phase/'observations.jsonl',[{'safe':True}])
        proof={'project':p.RENTAL_PROJECT,'source_commit':self.head,'study_dir':'runs/sd-hard','freeze_sha256':self.freeze,'preflight_sha256':p.sha(self.ready),
            'finished':True,'issues':[],'owned_leaks':[],'jobs':[],'recorder_pid':100,'recorder_start_ticks':111,
            'readiness':self.d(phase/'observer-ready.json'),'observations':self.d(phase/'observations.jsonl')}
        put(phase/'owned-observer.json',proof)
        for name in ('record-identity.json','observer-identity.json'):put(phase/name,{'uid':0,'cwd':p.REMOTE,'fd_soft':65536,'fd_hard':1048576})
        put(phase/'phase-exit.json',{'completed':True,'record_returncode':0,'observer_returncode':0,'failure_class':None,'cleanup_errors':[]})
        owned={'jobs':[],'physical_by_incident':{n:physical for n in p.ALL_IDS}}
        quality={'project':p.RENTAL_PROJECT,'complete':True,'freeze_sha256':self.freeze,'owned_observer_proofs':[self.d(phase/'owned-observer.json')],
            'recordings':[p.legacy.audit_recording(self.study,spec,frozen,owned) for spec in self.specs]}
        put(self.quality_dir/'quality.json',quality)
        validity={'total':15,'valid':15,'incidents':[{'id':n,'valid':True} for n in p.IDS]};put(self.study/'answers/validity.json',validity)
        dispatch={'project':p.RENTAL_PROJECT,'study_dir':'runs/sd-hard','freeze_sha256':self.freeze,'quality':self.d(self.quality_dir/'quality.json'),
            'manifests':{n:p.sha(self.study/'incidents'/n/'manifest.json') for n in p.ALL_IDS},'recording_bytes_sha256':p.gate.bytes_inventory(self.study)}
        put(self.quality_dir/'dispatch.json',dispatch);put(self.study/p.legacy.VALIDATION_DISPATCH,{'project':p.RENTAL_PROJECT,'dispatch':self.d(self.quality_dir/'dispatch.json')})
        for suffix in ('stdout','stderr'):(self.quality_dir/('validate.'+suffix)).write_bytes(b'')
        put(self.quality_dir/'result.json',{'project':p.RENTAL_PROJECT,'completed':True,'returncode':0,'failure':None,'total':15,'valid':15,'invalid':0,
            'exact_coverage_verified':True,'validity':self.d(self.study/'answers/validity.json'),'dispatch_sha256':p.sha(self.quality_dir/'dispatch.json'),
            'study_dispatch_sha256':p.sha(self.study/p.legacy.VALIDATION_DISPATCH),'stdout_sha256':p.sha(self.quality_dir/'validate.stdout'),'stderr_sha256':p.sha(self.quality_dir/'validate.stderr')})
        for arm in p.ARMS:
            for name in p.IDS:
                trail=[{'t':t,'decision':{'valid_output':True,'usage':{'prompt_tokens':10,'completion_tokens':1},'private_text':'MODEL_TEXT_MUST_NOT_ESCAPE'}} for t in (30,60)]
                put(self.study/'decisions'/arm/(name+'.json'),{'arm':arm,'incident':name,'checkpoints':2,'trail':trail,'final':None,'engine_config':{}})
        put(self.evaluation/'outcome.json',{'completed':True,'failure':None,'cleanup_errors':[],'groups':['rules-spark-wonder','glimmer-cascades']})
        context={'fits_8192':True,'incidents':15,'context_tokens':8192,'model_revision':p.legacy.REV,'freeze_sha256':self.freeze,
            'per_incident_maximum':{n:{kind:{'input_tokens':100,'output_budget_tokens':budget,'total_tokens':100+budget}
                for kind,budget in [('diagnosis',2048),('monitor',600)]} for n in p.IDS},'public_manifests_sha256':{n:p.sha(self.study/'incidents'/n/'manifest.json') for n in p.ALL_IDS}}
        put(self.evaluation/'contexts.json',context)
        for file,arms in [('rules-spark-wonder-responses.json',('rules','spark','wonder')),('glimmer-cascades-responses.json',('glimmer','glimmer_to_spark','glimmer_to_wonder'))]:
            put(self.evaluation/file,p.responses.audit_model_group(self.study,list(arms)))
        all_scores=p.score_study(self.study,split='hard');valid_scores=p.score_study(self.study,split='hard',valid_only=True)
        projection=p.exporter.project(all_scores,valid_scores,set(p.IDS),set());projection.update(freeze_sha256=self.freeze,validity_sha256=p.sha(self.study/'answers/validity.json'),
            final_decisions_sha256={a:{n:p.sha(self.study/'decisions'/a/(n+'.json')) for n in p.IDS} for a in p.ARMS})
        self.projection=self.ops/'safe-score-projection.json';put(self.projection,projection)
        for name,key in [('all','all'),('valid_only','valid_only')]:
            put(self.evaluation/('final-score-'+name+'.stdout'),projection['scoreboards'][key]);(self.evaluation/('final-score-'+name+'.stderr')).write_bytes(b'')
        seed={'project':'servedoctor','caps_usd':{'meta':'50','baseten':'20'},'entries':[]};self.seed=self.ops/'ledger.seed.json';put(self.seed,seed);patch.object(p,'SEED',p.sha(self.seed)).start()
        self.ledger=self.ops/'final-gpu-canonical-ledger.json';put(self.ledger,seed);self.hours=self.repo/'runs/servedoctor-gpu-hours.md';self.hours.write_text('Final invented accounting\n')
        intent={'project':p.RENTAL_PROJECT,'instance_id':60000001,'rental_scope_sha256':self.scope,'operation':'delete','method':'DELETE','path':'/api/v0/instances/60000001/','requested_epoch':2000.}
        put(self.ops/'delete-intent.json',intent);put(self.ops/'delete-outcome.json',{**intent,'phase':'response','success':True})
        put(self.ops/'delete-reconciliation.json',{'instance_id':60000001,'destroyed_epoch':2001.,'pending_intent':None,
            'status':{'actual_status':'exited','cur_state':'stopped','intended_status':'stopped'}})
        before={str(path.relative_to(self.repo)):p.sha(path) for path in self.study.rglob('*') if path.is_file()}
        before[str(self.ledger.relative_to(self.repo))]=p.sha(self.ledger)
        before[str((self.ops/'rental-scope.json').relative_to(self.repo))]=p.sha(self.ops/'rental-scope.json')
        snapshot=self.ops/'pre-delete-gpu-hours.md';snapshot.write_text('Invented immutable predelete hours\n')
        before[str(snapshot.relative_to(self.repo))]=p.sha(snapshot)
        put(self.ops/'backup-manifest.json',{'root':str(self.repo),'files':before})
        put(self.ops/'backup.json',{'project':p.RENTAL_PROJECT,'instance_id':60000001,'rental_scope_sha256':self.scope,'all_remote_artifacts_backed_up':True,'last_stop_epoch':1900.,
            'evidence_manifest':self.d(self.ops/'backup-manifest.json'),'canonical_ledger':{**self.d(self.ledger),'remote_sha256':p.sha(self.ledger)},'gpu_hours_snapshot':self.d(snapshot)})
        baseline=self.ops/'v0-final-proof.json';put(baseline,{'project':'servedoctor','instance_id':58716527,'confirmed_absent':True,'cost':{'total_projected_usd_upper':p.V0}})
        patch.object(p.hard_vast,'PRIOR_PATH',baseline).start();patch.object(p.hard_vast,'PRIOR_SHA',p.sha(baseline)).start()
        baseline_descriptor={**self.d(baseline),'usd_upper':p.V0};hosts=[];previous=None;totals={'running_hours':0.,'compute_usd_upper':0.,'disk_usd_upper':0.}
        for version,instance in enumerate([58843932,58848277,58851643,58858374],1):
            folder=self.ops/f'rental-history/host{version}-{instance}';folder.mkdir(parents=True)
            scoped={'project':p.RENTAL_PROJECT,'label':p.PROJECT,'instance_id':instance,'offer_id':100+version,'machine_id':200+version,
                'image':p.hard_vast.IMAGE,'prior_baseline':baseline_descriptor,'prior_hard_hosts':copy.deepcopy(hosts)}
            put(folder/'rental-scope.json',scoped)
            state={**scoped,'scope_sha256':p.sha(folder/'rental-scope.json'),'created_epoch':float(version*100),'destroyed_epoch':float(version*100+50),
                'dph_total':1.5,'storage_dph':.1,'running_intervals':[{'start_epoch':float(version*100+1),'stop_epoch':float(version*100+40)}]}
            put(folder/'final-state.json',state);money=p.hard_vast.Rental.host_cost(state,state['destroyed_epoch'])
            for key in totals:totals[key]+=money[key]
            receipt={'project':p.RENTAL_PROJECT,'instance_id':instance,'confirmed_absent':True,'destroyed_epoch':state['destroyed_epoch'],
                'final_state':self.d(folder/'final-state.json'),'rental_scope':self.d(folder/'rental-scope.json'),
                'rental_scope_sha256':state['scope_sha256'],'host_cost':money,'network_slack_reserved_once':True}
            put(folder/'billing-receipt.json',receipt);hosts.append({'instance_id':instance,'receipt':self.d(folder/'billing-receipt.json')})
            path=self.ops/('prior-hard-hosts.json' if version==1 else f'prior-hard-hosts-{version}.json')
            document={'project':p.RENTAL_PROJECT,'version':version,'network_slack_reserved_once':True,'hosts':copy.deepcopy(hosts)}
            if previous:document['parent']=self.d(previous)
            put(path,document);previous=path
        current={'project':p.RENTAL_PROJECT,'instance_id':60000001,'scope_sha256':self.scope,'prior_hard_hosts':hosts,'created_epoch':500.,'destroyed_epoch':2001.,
            'dph_total':1.5,'storage_dph':.1,'running_intervals':[{'start_epoch':501.,'stop_epoch':1900.}]}
        self.final_state=self.ops/'final-state.json';put(self.final_state,current)
        for key,value in p.hard_vast.Rental.host_cost(current,2001.).items():totals[key]+=value
        cost={'prior_v0_usd_upper':p.V0,'hard_running_hours':totals['running_hours'],'hard_compute_usd_upper':totals['compute_usd_upper'],
            'hard_disk_usd_upper':totals['disk_usd_upper'],'new_network_reserve_usd':p.hard_vast.NETWORK,'new_slack_reserve_usd':p.hard_vast.SLACK}
        cost['total_usd_upper']=sum(cost[k] for k in cost if k!='hard_running_hours')
        cleanup={'project':p.RENTAL_PROJECT,'instance_id':60000001,'rental_scope_sha256':self.scope,'confirmed_absent':True,'stopped_confirmed':True,'owned_work_quiescent':True,'destroyed_epoch':2001.,
            'canonical_ledger_sha256':p.sha(self.ledger),'remote_ledger_sha256':p.sha(self.ledger),'gpu_hours_log_sha256':p.sha(self.hours),'ledger_summary':p.ledger_summary(self.ledger,self.seed),
            'delete_intent':self.d(self.ops/'delete-intent.json'),'delete_outcome':self.d(self.ops/'delete-outcome.json'),
            'delete_reconciliation':self.d(self.ops/'delete-reconciliation.json'),'backup_receipt':self.d(self.ops/'backup.json'),'gpu_accounting':cost,'final_state':self.d(self.final_state)}
        self.cleanup=self.ops/'final-cleanup.json';put(self.cleanup,cleanup)
        self.readme=self.ops/'final-README.md';self.readme.write_text('Invented complete README '+self.head+' '+self.freeze+' '+p.LABEL+' analysis/analysis-report.html')
        entries=[]
        for group in p.GROUPS:
            source=self.ops/(group+'.json');put(source,{'invented_group':group});entries.append({'source':self.d(source),'destination':'provenance/'+group+'/evidence.json','group':group})
        self.failure=self.ops/'failure-index.json';put(self.failure,{'project':p.RENTAL_PROJECT,'failures':[{'id':'f1','category':'setup','summary':'Invented failure','reason':'Invented continuation','artifacts':[entries[0]['source']]}]})
        self.provenance=self.ops/'allowlist.json';put(self.provenance,{'project':p.RENTAL_PROJECT,'files':entries,'failure_index':self.d(self.failure)})
        self.args=argparse.Namespace(study_dir=str(self.study),original_study_dir=str(self.original),remote_ops=str(self.partial_remote),remote_old_ops=str(self.remote),remote_control=str(self.control),calibration_mirror=str(self.cal),ledger=str(self.ledger),ledger_seed=str(self.seed),hours=str(self.hours),
            out=str(self.repo/'results/servedoctor-hard-20261103'),score_projection=str(self.projection),evaluation_dir=str(self.evaluation),cleanup_evidence=str(self.cleanup),provenance=str(self.provenance),readme=str(self.readme),create=False)
        self.amendment()
    def amendment(self):
        # Build the unchanged original attempt before adding any approved15-case
        # validation, decisions or reports. Every byte is invented in temp dirs.
        failed=self.study/'engines/engine-06-hard-16/engine.log';failed.parent.mkdir(parents=True);failed.write_text('Invented fixed activation reserve failure\n')
        patch.object(p,'FAILURE_LOG',p.sha(failed)).start()
        shutil.copytree(self.study,self.original)
        for name in ('decisions','report.json','report.html','answers/validity.json',p.legacy.VALIDATION_DISPATCH):
            path=self.original/name
            if path.is_dir():shutil.rmtree(path)
            elif path.exists():path.unlink()
        legacy_marker=self.study/p.legacy.VALIDATION_DISPATCH
        if legacy_marker.exists():legacy_marker.unlink()
        count=sum(x.is_file() for x in self.original.rglob('*'))
        self.assertLessEqual(count,p.ORIGINAL_FILE_COUNT)
        for index in range(p.ORIGINAL_FILE_COUNT-count):
            relative=f'engines/retained-fixture/artifact-{index:03d}.json'
            put(self.original/relative,{'invented':index});put(self.study/relative,{'invented':index})
        original={x.relative_to(self.original).as_posix():p.sha(x) for x in self.original.rglob('*') if x.is_file()}
        self.assertEqual(len(original),178)
        helpers={}
        actual=Path(p.gate.__file__).parent
        for name in p.PROTOCOL_HELPERS:
            (self.partial/name).write_bytes((actual/name).read_bytes());(self.partial_remote/name).write_bytes((actual/name).read_bytes());helpers[name]=p.sha(self.partial/name)
        self.preservation=self.partial_remote/'preservation-receipt.json';put(self.preservation,{'invented':'opaque frozen178 preservation','original_files':original})
        patch.object(p,'PRESERVATION',p.sha(self.preservation)).start()
        self.exclusion=self.partial_remote/'exclusion.json'
        why={'project':p.RENTAL_PROJECT,'analysis_label':p.LABEL,'included_hard_ids':list(p.IDS),'excluded_ids':['hard-16'],'reference_id':'reference',
             'original_source_commit':self.head,'original_freeze_sha256':self.freeze,'before_validation':True,'before_any_hard_arm_evaluation':True,
             'prompts_rules_scoring_answer_keys_unchanged':True,'hard16_may_be_modified_regenerated_or_rerecorded':False,
             'native_validity_must_not_be_rewritten':True,'full_hard_set_claim_permitted':False,
             'limits':{'gpu_total_usd':40,'meta_ledger_cap_usd':50,'baseten_ledger_cap_usd':20,'extra_public_note':'unchanged'},
             'original_preservation_receipt':self.d(self.preservation),'recorded_at_utc':'2026-11-02T00:00:00+00:00'}
        put(self.exclusion,why);patch.object(p,'EXCLUSION',p.sha(self.exclusion)).start()
        phase=self.remote/'record-stages/record1/00-all'
        ready=p.load(phase/'observer-ready.json');ready['selected_ids']=[*p.ALL_IDS,'hard-16'];put(phase/'observer-ready.json',ready)
        proof=p.load(phase/'owned-observer.json');proof['readiness']=self.d(phase/'observer-ready.json');put(phase/'owned-observer.json',proof)
        put(phase/'phase-exit.json',{'completed':False,'record_returncode':1,'observer_returncode':0,'failure_class':'CalledProcessError','cleanup_errors':[]})
        protocol={'project':p.PROJECT,'label':p.LABEL,'source_commit':self.head,'study_dir':p.PRIMARY,'original_study_dir':p.ORIGINAL,
            'included_hard_ids':list(p.IDS),'excluded_ids':['hard-16'],'scientific_inputs_changed':False,'old_helpers_changed':False,
            'reference_and_hard_recordings':16,'original_freeze':self.d(self.original/p.legacy.FREEZE),'exclusion':self.d(self.exclusion),
            'preservation':self.d(self.preservation),'created_at_utc':'2026-11-02T00:00:01+00:00','original_inventory_sha256':original,
            'input_files_sha256':{n:p.sha(self.study/n) for n in p.gate.INPUTS},'private_helpers_sha256':helpers,'owned_proofs':[self.d(phase/'owned-observer.json')]}
        put(self.study/p.gate.PROTOCOL,protocol);(self.study/'analysis-label.txt').write_text(p.LABEL+'\n')
        quality=p.load(self.quality_dir/'quality.json');quality.update(project=p.PROJECT,label=p.LABEL,original_freeze_sha256=self.freeze,
            protocol_sha256=p.sha(self.study/p.gate.PROTOCOL),expected_recordings=16,hard_incidents=15,excluded_ids=['hard-16'],owned_observer_proofs=protocol['owned_proofs'])
        put(self.quality_dir/'quality.json',quality)
        dispatch={'project':p.PROJECT,'label':p.LABEL,'study_dir':p.PRIMARY,'created_at_utc':'2026-11-02T00:00:02+00:00',
            'protocol':self.d(self.study/p.gate.PROTOCOL),'quality':self.d(self.quality_dir/'quality.json'),
            'manifests':{n:p.sha(self.study/'incidents'/n/'manifest.json') for n in p.ALL_IDS},'recording_bytes_sha256':p.gate.bytes_inventory(self.study)}
        put(self.quality_dir/'dispatch.json',dispatch)
        put(self.study/p.gate.MARKER,{'project':p.PROJECT,'label':p.LABEL,'dispatch':self.d(self.quality_dir/'dispatch.json')})
        result={'project':p.PROJECT,'label':p.LABEL,'completed':True,'returncode':0,'failure':None,'total':15,'valid':15,'invalid':0,
            'validity':self.d(self.study/'answers/validity.json'),'dispatch':self.d(self.quality_dir/'dispatch.json'),
            'study_dispatch_sha256':p.sha(self.study/p.gate.MARKER),'stdout_sha256':p.sha(self.quality_dir/'validate.stdout'),'stderr_sha256':p.sha(self.quality_dir/'validate.stderr')}
        put(self.quality_dir/'result.json',result)
        for name in ('contexts.json','rules-spark-wonder-responses.json','glimmer-cascades-responses.json'):
            value=p.load(self.evaluation/name);value.update(project=p.PROJECT,label=p.LABEL,
                helper_sha256=helpers['measure_contexts.py' if name=='contexts.json' else 'model_response_guard.py']);put(self.evaluation/name,value)
        value=p.load(self.evaluation/'outcome.json');value.update(project=p.PROJECT,label=p.LABEL);put(self.evaluation/'outcome.json',value)
        projection=p.load(self.projection);projection['helper_sha256']=helpers['export_hard_scores.py'];put(self.projection,projection)
        all_scores=p.score_study(self.study,split='hard');valid_scores=p.score_study(self.study,split='hard',valid_only=True)
        put(self.study/'report.json',{**all_scores,'by_arm_valid_only':valid_scores['by_arm'],'private':'MODEL_TEXT_MUST_NOT_ESCAPE'})
        (self.study/'analysis-report.html').write_text(p.LABEL+'<iframe src="report.html"></iframe>')
        put(self.study/'analysis-report.json',{'project':p.PROJECT,'label':p.LABEL,'scoreboards':projection['scoreboards'],'denominators':projection['denominators'],
            'native_report_json':self.d(self.study/'report.json'),'native_report_html':self.d(self.study/'report.html'),'score_projection':self.d(self.projection)})
        cleanup=p.load(self.cleanup);cleanup.update(analysis_project=p.PROJECT,label=p.LABEL,excluded_ids=['hard-16'],authorization=self.d(self.exclusion),original_preservation=self.d(self.preservation));put(self.cleanup,cleanup)
        failure=p.load(self.failure);first=failure['failures'][0]
        prior=[{**copy.deepcopy(first),'id':f'old-{i}'} for i in range(18)]
        prior_path=self.ops/'original-failure-index.json';put(prior_path,{'project':p.RENTAL_PROJECT,'failures':prior})
        patch.object(p,'ORIGINAL_FAILURE_INDEX',p.sha(prior_path)).start()
        failure.update(project=p.PROJECT,label=p.LABEL,finalized=True,original_failure_index=self.d(prior_path),retained_original_entries=18,
            failures=prior+[{**copy.deepcopy(first),'id':f'new-{i}'} for i in range(3)])
        put(self.failure,failure)
        provenance=p.load(self.provenance);provenance.update(project=p.PROJECT,label=p.LABEL,failure_index=self.d(self.failure));put(self.provenance,provenance)
        self.refresh_backup_proofs()
    def refresh_backup_proofs(self):
        captured={x.relative_to(self.study).as_posix():p.sha(x) for x in self.study.rglob('*') if x.is_file()}
        mirror=self.evaluation/'mirror-manifest.json';put(mirror,{'stable':True,'study_files_sha256':captured,'study_file_count':len(captured),'ledger_sha256':p.sha(self.ledger)})
        outcome=p.load(self.evaluation/'outcome.json');outcome['opaque_mirror']={'manifest_sha256':p.sha(mirror)};put(self.evaluation/'outcome.json',outcome)
        final=self.evaluation/'final-ledger.stdout';put(final,{'sha256':p.sha(self.ledger),'summary':p.ledger_summary(self.ledger,self.seed)})
        parent=self.ops/'partial-resume-pipeline-attempt1/outcome.json';put(parent,{'project':p.RENTAL_PROJECT,'instance_id':p.INSTANCE,'rental_scope_sha256':self.scope,
            'returncode':0,'stop_confirmed':True,'cleanup_confirmed':True})
        ready=self.ops/'finalizer-readiness.json';put(ready,{'project':p.RENTAL_PROJECT,'analysis_project':p.PROJECT,'label':p.LABEL,'ready':True,
            'recordings':16,'hard_incidents':15,'final_decisions':90,'original_freeze_sha256':self.freeze,'canonical_ledger_sha256':p.sha(self.ledger),
            'remote_ledger_sha256':p.sha(self.ledger),'ledger_summary':p.ledger_summary(self.ledger,self.seed),
            'pipeline_outcome':self.d(parent),'evaluation_outcome':self.d(self.evaluation/'outcome.json'),'final_remote_ledger_proof':self.d(final)})
        backup=p.load(self.ops/'backup.json');backup.update(analysis_project=p.PROJECT,label=p.LABEL,excluded_ids=['hard-16'],original_frozen_incidents=16,
            completed_hard_incidents=15,final_decisions=90,authorization=self.d(self.exclusion),original_preservation=self.d(self.preservation),readiness=self.d(ready))
        before={}
        for folder in (self.study,self.original,self.remote,self.partial_remote,self.control,self.evaluation,parent.parent):
            for x in folder.rglob('*'):
                if x.is_file() and x.name not in p.BACKUP_MUTABLE and not x.name.endswith('.tmp'):before[str(x.relative_to(self.repo))]=p.sha(x)
        for item in (self.ledger,self.ops/'rental-scope.json',Path(backup['gpu_hours_snapshot']['path'])):before[str(item.relative_to(self.repo))]=p.sha(item)
        put(self.ops/'backup-manifest.json',{'root':str(self.repo),'files':before})
        backup['evidence_manifest']=self.d(self.ops/'backup-manifest.json');put(self.ops/'backup.json',backup)
        cleanup=p.load(self.cleanup);cleanup['backup_receipt']=self.d(self.ops/'backup.json');put(self.cleanup,cleanup)
    def d(self,path):
        value=p.desc(path)
        if Path(path).is_relative_to(self.remote):value['path']=p.REMOTE+'/'+p.OLD_OPS_REL+'/'+Path(path).relative_to(self.remote).as_posix()
        elif Path(path).is_relative_to(self.partial_remote):value['path']=p.REMOTE+'/'+p.OPS_REL+'/'+Path(path).relative_to(self.partial_remote).as_posix()
        elif Path(path).is_relative_to(self.study):value['path']=p.REMOTE+'/'+p.PRIMARY+'/'+Path(path).relative_to(self.study).as_posix()
        elif Path(path).is_relative_to(self.original):value['path']=p.REMOTE+'/'+p.ORIGINAL+'/'+Path(path).relative_to(self.original).as_posix()
        elif Path(path).is_relative_to(self.cal):value['path']=p.REMOTE+'/'+Path(path).relative_to(self.cal).as_posix()
        return value
    def execute(self):return p.execute(self.args,repo=self.repo,repository_check=lambda repo:None)

    def test_full_verify_then_create_preserves_every_original_and_opaque_report(self):
        before={str(x):p.sha(x) for x in self.repo.rglob('*') if x.is_file()}
        value=self.execute();self.assertTrue(value['verified']);self.assertFalse(value['created']);self.assertFalse(Path(self.args.out).exists())
        self.args.create=True;value=self.execute();self.assertTrue(value['created'])
        out=Path(self.args.out);manifest=p.load(out/'package-manifest.json')
        self.assertEqual((out/'analysis/report.json').read_bytes(),(self.study/'report.json').read_bytes());self.assertEqual((out/'ledger.json').read_bytes(),self.ledger.read_bytes())
        self.assertEqual(len([n for n in manifest['files'] if n.startswith('analysis/decisions/')]),90)
        self.assertTrue(all(p.sha(out/n)==h for n,h in manifest['files'].items()))
        self.assertTrue(all(p.sha(name)==h for name,h in before.items()))
        self.assertNotIn('MODEL_TEXT_MUST_NOT_ESCAPE',json.dumps(value));self.assertNotIn('ANSWER_MUST_NOT_ESCAPE',json.dumps(value))
        with self.assertRaises((p.PackageError,ValueError)):self.execute()
    def test_fifteen_analysis_and_original178_are_separate_and_hard16_failure_is_unchanged(self):
        self.args.create=True;value=self.execute();out=Path(self.args.out)
        self.assertEqual(value['label'],p.LABEL);self.assertEqual(value['final_decisions'],90)
        originals=[x for x in (out/'original-frozen-attempt').rglob('*') if x.is_file()]
        self.assertEqual(len(originals),178)
        self.assertEqual(p.sha(out/'original-frozen-attempt/engines/engine-06-hard-16/engine.log'),p.FAILURE_LOG)
        self.assertFalse((out/'original-frozen-attempt/answers/validity.json').exists())
        self.assertFalse((out/'original-frozen-attempt/decisions').exists())
        self.assertIn(p.LABEL,(out/'analysis/analysis-report.html').read_text())
        self.assertFalse((out/'report.html').exists())

    def test_explicit_final_study_mirror_uses_identical_backed_canonical_copy(self):
        mirror=self.partial/'final-study';shutil.copytree(self.study,mirror)
        self.args.study_dir=str(mirror)
        value=self.execute();self.assertTrue(value['verified']);self.assertFalse(value['created'])
        (mirror/'analysis-label.txt').write_text('A changed mirror cannot borrow a different backup')
        with self.assertRaises(p.PackageError):self.execute()

    def test_original_eighteen_failure_entries_cannot_be_rewritten(self):
        failure=p.load(self.failure);failure['failures'][0]['summary']='Posthoc rewrite forbidden';put(self.failure,failure)
        provenance=p.load(self.provenance);provenance['failure_index']=self.d(self.failure);put(self.provenance,provenance)
        with self.assertRaisesRegex(p.PackageError,'original-failure-history-differs'):self.execute()

    def test_original_private_byte_or_failed_startup_mutation_blocks(self):
        target=self.original/'answers/answer_keys.json';original=target.read_bytes();target.write_bytes(original+b' ')
        with self.assertRaises(p.PackageError):self.execute()
        target.write_bytes(original)
        failed=self.original/'engines/engine-06-hard-16/engine.log';failed.write_text('Replacement success would conceal failure')
        with self.assertRaises(p.PackageError):self.execute()

    def test_exclusion_must_precede_protocol_even_when_test_hash_is_rebound(self):
        why=p.load(self.exclusion);why['recorded_at_utc']='2026-11-02T00:00:09+00:00';put(self.exclusion,why)
        protocol=p.load(self.study/p.gate.PROTOCOL);protocol['exclusion']=self.d(self.exclusion);put(self.study/p.gate.PROTOCOL,protocol)
        with patch.object(p,'EXCLUSION',p.sha(self.exclusion)),self.assertRaisesRegex(p.PackageError,'exclusion-did-not-precede-analysis'):
            self.execute()

    def test_excluded_hard16_decision_and_changed_new_helper_are_rejected(self):
        path=self.study/'decisions/rules/hard-16.json';put(path,{'invented':'must not reintroduce excluded case'})
        with self.assertRaises(p.PackageError):self.execute()
        path.unlink();helper=self.partial/'measure_contexts.py';helper.write_text('# post-freeze replacement forbidden\n')
        with self.assertRaisesRegex(p.PackageError,'partial-helper-source-differs'):self.execute()

    def test_labelled_wrapper_and_native_aggregate_must_match(self):
        target=self.study/'analysis-report.json';value=p.load(target);value['label']='Full16 claim forbidden';put(target,value)
        self.refresh_backup_proofs()
        with self.assertRaisesRegex(p.PackageError,'labelled-analysis-report-differs'):self.execute()

    def test_predelete_manifest_must_cover_original_and_immutable_hours_snapshot(self):
        manifest=self.ops/'backup-manifest.json';original=p.load(manifest)
        changed=copy.deepcopy(original);name=next(n for n in changed['files'] if '/original-mirror/' in n);changed['files'].pop(name);put(manifest,changed)
        backup=p.load(self.ops/'backup.json');backup['evidence_manifest']=self.d(manifest);put(self.ops/'backup.json',backup)
        cleanup=p.load(self.cleanup);cleanup['backup_receipt']=self.d(self.ops/'backup.json');put(self.cleanup,cleanup)
        with self.assertRaisesRegex(p.PackageError,'full-study-not-backed-up'):self.execute()
        put(manifest,original)
        snapshot=Path(backup['gpu_hours_snapshot']['path']);changed=copy.deepcopy(original);changed['files'].pop(str(snapshot.relative_to(self.repo)));put(manifest,changed)
        backup['evidence_manifest']=self.d(manifest);put(self.ops/'backup.json',backup)
        cleanup['backup_receipt']=self.d(self.ops/'backup.json');put(self.cleanup,cleanup)
        with self.assertRaisesRegex(p.PackageError,'immutable-pre-delete-hours-not-backed-up'):self.execute()

    def test_invalid_model_output_with_genuine_usage_is_retained_as_a_result(self):
        for name in p.IDS:
            target=self.study/'decisions/spark'/(name+'.json');value=p.load(target)
            for step in value['trail']:step['decision']['valid_output']=False
            put(target,value)
        scores=p.score_study(self.study,split='hard');valid=p.score_study(self.study,split='hard',valid_only=True)
        projection=p.exporter.project(scores,valid,set(p.IDS),set())
        projection.update(freeze_sha256=self.freeze,validity_sha256=p.sha(self.study/'answers/validity.json'),
            helper_sha256=p.sha(self.partial/'export_hard_scores.py'),final_decisions_sha256={a:{n:p.sha(self.study/'decisions'/a/(n+'.json')) for n in p.IDS} for a in p.ARMS})
        put(self.projection,projection)
        for name,key in [('all','all'),('valid_only','valid_only')]:put(self.evaluation/('final-score-'+name+'.stdout'),projection['scoreboards'][key])
        response=p.responses.audit_model_group(self.study,['rules','spark','wonder']);response['helper_sha256']=p.sha(self.partial/'model_response_guard.py');put(self.evaluation/'rules-spark-wonder-responses.json',response)
        put(self.study/'report.json',{**scores,'by_arm_valid_only':valid['by_arm']})
        wrapped=p.load(self.study/'analysis-report.json');wrapped.update(scoreboards=projection['scoreboards'],denominators=projection['denominators'],
            native_report_json=self.d(self.study/'report.json'),score_projection=self.d(self.projection));put(self.study/'analysis-report.json',wrapped)
        self.refresh_backup_proofs()
        value=self.execute();self.assertTrue(value['verified'])
        self.assertGreater(projection['scoreboards']['all']['spark']['invalid_outputs'],0)
        self.assertFalse(value['created'])

    def test_remote_paths_resolve_only_to_explicit_mirrors_and_changed_descriptor_rejected(self):
        evidence=p.Evidence(self.args,self.repo);require=self.d(self.remote/'preflight-readiness.json')
        self.assertEqual(evidence.descriptor(require),self.ready)
        require['sha256']='f'*64
        with self.assertRaises(p.PackageError):evidence.descriptor(require)
        with self.assertRaises(p.PackageError):evidence.resolve('/etc/passwd')
    def test_changed_recording_missing_case_and_resealed_truncated_collector_block(self):
        folder=self.study/'incidents/hard-01';original=(folder/'telemetry.jsonl').read_bytes();(folder/'telemetry.jsonl').write_bytes(b'{}\n')
        with self.assertRaises((p.PackageError,ValueError)):self.execute()
        (folder/'telemetry.jsonl').write_bytes(original);folder.rename(self.study/'missing-hard-01')
        with self.assertRaises((p.PackageError,ValueError,FileNotFoundError)):self.execute()
    def test_missing_partial_and_forged_scoreboards_block(self):
        path=self.study/'decisions/spark/hard-01.json';original=path.read_bytes();path.unlink()
        with self.assertRaises(p.PackageError):self.execute()
        path.write_bytes(original);put(path.with_name('hard-01.partial.json'),{'incomplete':True})
        with self.assertRaises(p.PackageError):self.execute()
        path.with_name('hard-01.partial.json').unlink();value=p.load(self.projection);value['scoreboards']['all']['spark']['fix_proposed']+=1;put(self.projection,value)
        with self.assertRaises(p.PackageError):self.execute()
    def test_context_response_validity_or_cleanup_failure_blocks(self):
        path=self.evaluation/'contexts.json';value=p.load(path);value['fits_8192']=False;put(path,value)
        with self.assertRaises(p.PackageError):self.execute()
    def test_forged_validity_set_and_unguarded_response_usage_block(self):
        path=self.study/'answers/validity.json';original=path.read_bytes();value=p.load(path);value['incidents'][-1]['id']=p.IDS[0];put(path,value)
        with self.assertRaises((p.PackageError,ValueError)):self.execute()
        path.write_bytes(original);decision=self.study/'decisions/spark/hard-01.json';value=p.load(decision)
        for step in value['trail']:step['decision'].pop('usage')
        put(decision,value)
        with self.assertRaises(p.PackageError):self.execute()
    def test_context_overflow_cannot_hide_behind_true_fit_flag(self):
        path=self.evaluation/'contexts.json';value=p.load(path)
        value['per_incident_maximum']['hard-01']['diagnosis'].update(input_tokens=8000,total_tokens=10048)
        put(path,value)
        with self.assertRaises(p.PackageError):self.execute()
    def test_unconfirmed_delete_or_changed_interval_and_missing_immutable_hours_block(self):
        path=self.ops/'delete-reconciliation.json';original=path.read_bytes();value=p.load(path);value['pending_intent']='delete-pending';put(path,value)
        with self.assertRaises(p.PackageError):self.execute()
        path.write_bytes(original);value=p.load(self.final_state);value['running_intervals'][0]['start_epoch']=1901.;put(self.final_state,value)
        with self.assertRaises(p.PackageError):self.execute()
    def test_prior_host_history_parent_or_cost_tampering_blocks(self):
        path=self.ops/'prior-hard-hosts-4.json';value=p.load(path);value['parent']['sha256']='f'*64;put(path,value)
        with self.assertRaises((p.PackageError,ValueError)):self.execute()
    def test_inherited_ledger_prefix_cannot_be_replaced(self):
        seed=p.load(self.seed);seed['entries']=[{'id':'old','provider':'meta','status':'reserved','accounted_usd':'1'}];put(self.seed,seed)
        with patch.object(p,'SEED',p.sha(self.seed)),self.assertRaises(p.PackageError):p.ledger_summary(self.ledger,self.seed)
    def test_ledger_prefix_caps_and_cost_never_reset_or_ignored(self):
        value=p.load(self.ledger);value['caps_usd']['meta']='500';put(self.ledger,value)
        with self.assertRaises(p.PackageError):p.ledger_summary(self.ledger,self.seed)
        put(self.ledger,p.load(self.seed))
        cost=p.load(self.cleanup);cost['gpu_accounting']['total_usd_upper']=40.1;put(self.cleanup,cost)
        with self.assertRaises(p.PackageError):self.execute()
    def test_secret_key_symlink_duplicate_and_nested_payload_are_rejected(self):
        secret=self.ops/'safe-looking.json';secret.write_bytes(b'Bearer '+b'x'*32)
        with self.assertRaises(p.PackageError):p.scan(secret)
        private=self.ops/'ssh_ed25519.pub';private.write_text('invented public material')
        with self.assertRaises(p.PackageError):p.scan(private)
        payload=self.ops/'retained/payload/safe.json';put(payload,{'fake':True})
        with self.assertRaises(p.PackageError):p.scan(payload)
        linked=self.ops/'linked.json';linked.symlink_to(self.failure)
        with self.assertRaises(p.PackageError):p.Evidence(self.args,self.repo).regular(linked)
    def test_duplicate_allowlist_and_missing_failure_artifact_are_rejected(self):
        value=p.load(self.provenance);value['files'].append(copy.deepcopy(value['files'][0]));put(self.provenance,value)
        with self.assertRaises(p.PackageError):self.execute()
    def test_changed_file_is_detected_across_readonly_gate_reads(self):
        evidence=p.Evidence(self.args,self.repo);path=evidence.regular(self.readme);path.write_text('changed')
        with self.assertRaises(p.PackageError):evidence.regular(path)
    def test_partial_copy_failure_retained_and_never_reused(self):
        self.args.create=True
        with patch.object(p.shutil,'copyfileobj',side_effect=OSError('invented failure')),self.assertRaises(OSError):self.execute()
        out=Path(self.args.out);self.assertTrue((out/'package-failure.json').is_file());self.assertFalse((out/'package-manifest.json').exists())
        with self.assertRaises(p.PackageError):self.execute()


if __name__=='__main__':unittest.main()
