"""Invented preserved studies, usage, ledgers and receipts only; no real outcomes."""
import argparse
import copy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import package_inference_results as n
import test_inference_integrity as fixtures

def put(path,v):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(v)+'\n')

class InputsTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.PortableTests();self.f.setUp();self.addCleanup(self.f.doCleanups);self.addCleanup(patch.stopall)
        self.repo=self.f.repo;self.root=self.f.root;self.ops=self.f.ops;self.k=fixtures.k
        values={'HEAD':self.k.SOURCE,'CONFIG':self.k.p.CONFIG,'FREEZE':self.k.p.FREEZE,'GPU':self.k.p.GPU,
          'RECORD_INSTANCE':self.k.p.INSTANCE,'RECORD_SCOPE':self.k.p.SCOPE,'INSTANCE':70000001,
          'SCOPE':self.k.sha(self.ops/'inference-rental-attempt1/rental-scope.json'),
          'FAILURE_LOG':self.k.p.FAILURE_LOG,'PRESERVATION':self.k.p.PRESERVATION,'EXCLUSION':self.k.p.gate.EXCLUSION_SHA}
        for key,value in values.items():patch.object(n,key,value).start()
        patch.object(n,'AMENDMENT',self.k.AMEND).start();self.evaluation=self.ops/'inference-evaluation-attempt1';self.evaluation.mkdir()
        control=self.ops/'inference-rental-attempt1';ack=control/'intent-0001-create-outcome.json'
        put(ack,{'project':n.RENTAL_PROJECT,'operation':'create','method':'PUT','phase':'response','success':True,'new_contract':n.INSTANCE})
        bound=self.k.load(control/'binding.json');bound.update(rental_scope=n.desc(control/'rental-scope.json'),create_ack=n.desc(ack));put(control/'binding.json',bound)
        transport=self.ops/'inference-transport-attempt1';ready=self.k.load(transport/self.k.TRANSPORT[1])
        ready['evidence_sha256']={n.OPS_REL+'/inference-rental-attempt1/rental-scope.json':n.SCOPE};put(transport/self.k.TRANSPORT[1],ready)
        channel=self.k.load(transport/self.k.TRANSPORT[2]);channel['transport_ready_sha256']=n.sha(transport/self.k.TRANSPORT[1]);put(transport/self.k.TRANSPORT[2],channel)
        self.k.prepare(self.root,self.repo)
        validation=self.ops/'inference-validation-attempt1'
        def native(*a,**kw):put(self.root/'answers/validity.json',{'total':15,'valid':15,'incidents':[{'id':x,'valid':True} for x in n.IDS]});return SimpleNamespace(returncode=0)
        self.k.validate_once(self.root,validation,self.repo,native)
        for arm in n.ARMS:
            for case in n.IDS:
                trail=[{'t':t,'decision':{'incident':False,'valid_output':False,'usage':{'prompt_tokens':10,'completion_tokens':0}}} for t in (30,60)]
                put(self.root/'decisions'/arm/(case+'.json'),{'arm':arm,'incident':case,'checkpoints':2,'final':None,'trail':trail,'engine_config':{}})
        put(self.evaluation/'outcome.json',{'project':n.PROJECT,'label':n.LABEL,'completed':True,'failure':None,'cleanup_errors':[],'groups':['rules-spark-wonder','glimmer-cascades']})
        helpers=self.k.helper_hashes(self.repo)
        put(self.evaluation/'contexts.json',{'project':n.PROJECT,'label':n.LABEL,'helper_sha256':helpers['inference_measure_contexts.py'],
           'fits_8192':True,'incidents':15,'context_tokens':8192,'model_revision':n.legacy.REV,'freeze_sha256':n.FREEZE,
           'public_manifests_sha256':{x:n.sha(self.root/'incidents'/x/'manifest.json') for x in n.ALL_IDS},
           'per_incident_maximum':{x:{kind:{'input_tokens':100,'output_budget_tokens':budget,'total_tokens':100+budget} for kind,budget in [('diagnosis',2048),('monitor',600)]} for x in n.IDS}})
        for name,arms in [('rules-spark-wonder-responses.json',['rules','spark','wonder']),('glimmer-cascades-responses.json',['glimmer','glimmer_to_spark','glimmer_to_wonder'])]:
            value=n.responses.audit_model_group(self.root,arms);value['helper_sha256']=helpers['inference_response_guard.py'];put(self.evaluation/name,value)
        engine=self.root/'engines/evaluation-glimmer-hard-deadbeefabcd';engine.mkdir();(engine/'engine.log').write_text('invented startup proof\n')
        put(engine/'engine_metadata.json',{'model_revision':n.legacy.REV,'dtype':'bf16','vllm_version':self.f.frozen['job_policy']['vllm_version'],'cleanup_status':'completed','returncode':0})
        seed={'project':'servedoctor','caps_usd':{'meta':'50','baseten':'20'},'entries':[]};self.seed=self.ops/'ledger.seed';put(self.seed,seed);patch.object(n,'SEED',n.sha(self.seed)).start()
        self.ledger=self.evaluation/'final-canonical-ledger.json';put(self.ledger,seed)
        put(self.evaluation/'final-ledger.stdout',{'sha256':n.sha(self.ledger),'summary':n.ledger_summary(self.ledger,self.seed)})
        self.projection=self.evaluation/'hard15-score-projection.json'
        self.control=self.ops/'inference-final-remote-control';self.control.mkdir();(self.control/'rental-scope.json').write_bytes((self.ops/'inference-rental-attempt1/rental-scope.json').read_bytes())
        self.args=argparse.Namespace(study_dir=str(self.root),original_study_dir=str(self.f.original),remote_ops=str(self.ops),remote_old_ops=str(self.f.fixture.ops),remote_control=str(self.control),
          calibration_mirror=str(self.f.e/'calibration'),score_projection=str(self.projection),evaluation_dir=str(self.evaluation),ledger=str(self.ledger),ledger_seed=str(self.seed))
        self.refresh()
    def refresh(self):
        helpers=self.k.helper_hashes(self.repo)
        a=n.score_study(self.root,split='hard');v=n.score_study(self.root,split='hard',valid_only=True)
        valid_ids={x['id'] for x in n.load(self.root/'answers/validity.json')['incidents'] if x['valid']}
        project=n.exporter.project(a,v,valid_ids,set())
        project.update(helper_sha256=helpers['inference_export_scores.py'],freeze_sha256=n.FREEZE,validity_sha256=n.sha(self.root/'answers/validity.json'),
            final_decisions_sha256={arm:{x:n.sha(self.root/'decisions'/arm/(x+'.json')) for x in n.IDS} for arm in n.ARMS})
        put(self.projection,project)
        for key,label in [('all','all'),('valid_only','valid_only')]:put(self.evaluation/('final-score-'+label+'.stdout'),project['scoreboards'][key]);(self.evaluation/('final-score-'+label+'.stderr')).write_bytes(b'')
        put(self.root/'report.json',{**a,'by_arm_valid_only':v['by_arm']});(self.root/'report.html').write_text('opaque native MODEL_CANARY')
        put(self.root/'analysis-report.json',{'project':n.PROJECT,'label':n.LABEL,'scoreboards':project['scoreboards'],'denominators':project['denominators'],
          'native_report_json':n.desc(self.root/'report.json'),'native_report_html':n.desc(self.root/'report.html'),'score_projection':n.desc(self.projection)})
        (self.root/'analysis-report.html').write_text(n.LABEL+'<iframe src="report.html"></iframe>')
        mirror=self.evaluation/'mirror-manifest.json';put(mirror,{'stable':True,'study_files_sha256':self.k.inventory(self.root),'study_file_count':len(self.k.inventory(self.root)),'ledger_sha256':n.sha(self.ledger)})
        out=n.load(self.evaluation/'outcome.json');out['opaque_mirror']={'manifest_sha256':n.sha(mirror)};put(self.evaluation/'outcome.json',out)
    def verify(self):return n._verify_inputs(self.args,self.repo,lambda _:None)[4]
    def test_complete_safe_gate_without_cleanup_or_provider(self):
        result=self.verify();self.assertTrue(result['ready']);self.assertEqual((result['recordings'],result['final_decisions']),(16,90))
        self.assertFalse(result['old_full_verify_freeze_claimed']);self.assertEqual(len(result['missing_ancillary_metadata']),2)
        self.assertNotIn('ANSWER_MUST_NOT_ESCAPE',json.dumps(result));self.assertNotIn('MODEL_CANARY',json.dumps(result))
        self.assertEqual(result['canonical_ledger_sha256'],n.sha(self.ledger));self.assertTrue(result['input_files_sha256'])
    def test_model_parse_failures_with_usage_are_valid_measured_outcomes(self):self.assertTrue(self.verify()['ready'])
    def test_explicit_native_call_failures_remain_measured(self):
        for arm in n.ARMS:
            if arm=='rules':continue
            for case in n.IDS:
                path=self.root/'decisions'/arm/(case+'.json');v=n.load(path)
                for step in v['trail']:step['decision'].pop('usage');step['decision']['call_failed']=True;step['error']='TimeoutError'
                put(path,v)
        for name,arms in [('rules-spark-wonder-responses.json',['rules','spark','wonder']),('glimmer-cascades-responses.json',['glimmer','glimmer_to_spark','glimmer_to_wonder'])]:
            value=n.responses.audit_model_group(self.root,arms);value['helper_sha256']=self.k.helper_hashes(self.repo)['inference_response_guard.py'];put(self.evaluation/name,value)
        self.refresh();self.assertTrue(self.verify()['ready'])
    def test_missing_or_partial_decision_blocks(self):
        q=self.root/'decisions/spark/hard-01.json';q.rename(q.with_name('hard-01.partial.json'))
        with self.assertRaises(ValueError):self.verify()
    def test_changed_original_transport_archive_blocks(self):
        # This invented fixture has no old transport; the live production
        # archive case is separately covered by the portable-integrity suite.
        q=self.root/'api-transport.json';value=n.load(q);value['instance_id']=1;put(q,value)
        with self.assertRaises(ValueError):self.verify()
    def test_context_overflow_blocks(self):
        q=self.evaluation/'contexts.json';v=n.load(q);v['per_incident_maximum']['hard-01']['diagnosis']['total_tokens']=9000;put(q,v)
        with self.assertRaises(ValueError):self.verify()
    def test_source_or_helper_change_blocks(self):
        (self.ops/'inference_measure_contexts.py').write_text('# changed')
        with self.assertRaises(ValueError):self.verify()
    def test_engine_cleanup_failure_blocks(self):
        q=next((self.root/'engines').glob('evaluation-glimmer-hard-*/engine_metadata.json'));v=n.load(q);v['cleanup_status']='failed';put(q,v)
        with self.assertRaises(ValueError):self.verify()
    def test_valid_only_uses_native_fourteen_without_filtering_all(self):
        self.validity_fixture(set(n.IDS[:-1]));value=self.verify();self.assertEqual(value['valid_cases'],14)
        projection=n.load(self.projection);self.assertEqual(projection['denominators']['all']['cases'],15)
        self.assertEqual(projection['denominators']['valid_only']['cases'],14)
    def test_zero_valid_cases_preserves_empty_valid_board(self):
        self.validity_fixture(set());value=self.verify();self.assertEqual(value['valid_cases'],0)
        self.assertEqual(n.load(self.projection)['scoreboards']['valid_only'],{})
    def validity_fixture(self,valid):
        put(self.root/'answers/validity.json',{'total':15,'valid':len(valid),'incidents':[{'id':x,'valid':x in valid} for x in n.IDS]})
        path=self.ops/'inference-validation-attempt1/result.json';value=n.load(path)
        value.update(self.k.p.gate.validity_summary(self.root));put(path,value);self.refresh()
    def finish_fixture(self):
        # Move the explicit remote-P mirror outside its own source tree. Every
        # byte is still invented; this mimics the separately supplied final SCP.
        mirror=self.repo/'mirrors/ops';shutil.copytree(self.ops,mirror);self.args.remote_ops=str(mirror)
        self.hours=self.repo/'runs/servedoctor-gpu-hours.md';self.hours.write_text('Invented final GPU accounting\n');self.args.hours=str(self.hours)
        out=self.ops/'inference-final-cleanup-attempt1';out.mkdir();self.args.cleanup_evidence=str(out/'cleanup.json')
        prior=self.ops/'inference-rental-attempt1/prior-accounting.json';put(prior,{'total_usd_upper':n.PRIOR_END,'receipt':{'path':str(self.ops/'prior-retirement.json'),'sha256':'0'*64}})
        state={'project':n.RENTAL_PROJECT,'instance_id':n.INSTANCE,'scope_sha256':n.SCOPE,'destroyed_epoch':2000.,'created_epoch':1000.,
          'dph_total':1.5,'storage_dph':.1,'prior_accounting':n.desc(prior),'running_intervals':[{'start_epoch':1001.,'stop_epoch':1900.}],
          'last_status':{'actual_status':'exited','cur_state':'stopped','intended_status':'stopped'},'pending_intent':None,'pending_attachment':None}
        put(out/'stopped-state.json',state);put(out/'final-state.json',state)
        host_cost_fn=n.hard_vast.Rental.host_cost
        cost=host_cost_fn(state,2000.)
        prior_value=n.load(prior)
        class LocalCost:
            def __init__(self,**kw):pass
            host_cost=staticmethod(host_cost_fn)
            def prior(self,path):return prior_value
        patch.object(n.hard_vast,'Rental',LocalCost).start()
        patch.object(n,'verify_inputs',lambda args,repo=n.REPO:self.verify()).start()
        input_proof=self.verify();binding=n.desc(self.ops/'inference-rental-attempt1/binding.json')
        budget=n.desc(self.ops/'gpu-budget-amendment-43-20261102.json');authorization=n.desc(self.ops/'exclusion.json');preservation=n.desc(self.f.e/'preservation-receipt.json')
        parent=self.ops/'inference-rental-attempt1/outcome.json';put(parent,{'project':n.RENTAL_PROJECT,'instance_id':n.INSTANCE,'rental_scope_sha256':n.SCOPE,
           'returncode':0,'stop_confirmed':True,'cleanup_confirmed':True,'transport_cleanup_returncode':0})
        stop=self.ops/'inference-transport-attempt1/stop-test.json';put(stop,{'stopped':True})
        ready={'project':n.RENTAL_PROJECT,'analysis_project':n.PROJECT,'label':n.LABEL,'ready':True,'instance_id':n.INSTANCE,'rental_scope_sha256':n.SCOPE,
           'canonical_ledger_sha256':n.sha(self.ledger),'pipeline_outcome':n.desc(parent),'input_verification':input_proof,
           'relay_stop_proofs':[n.desc(stop)],'transport_retirement':{'owned_transport_quiescent':True}}
        put(out/'readiness.json',ready);(out/'gpu-hours-before-delete.md').write_bytes(self.hours.read_bytes())
        files=dict(input_proof['input_files_sha256'])
        for folder in (Path(self.args.remote_ops),Path(self.args.remote_old_ops),Path(self.args.remote_control)):
            for q in folder.rglob('*'):
                if q.is_file() and q.name not in n.BACKUP_MUTABLE and not q.name.endswith('.tmp'):files[str(q.relative_to(self.repo))]=n.sha(q)
        for q in (out/'gpu-hours-before-delete.md',out/'stopped-state.json'):files[str(q.relative_to(self.repo))]=n.sha(q)
        put(out/'backup-manifest.json',{'root':str(self.repo),'files':files})
        common={'project':n.RENTAL_PROJECT,'analysis_project':n.PROJECT,'label':n.LABEL,'instance_id':n.INSTANCE,'rental_scope_sha256':n.SCOPE,
           'original_recording_instance_id':n.RECORD_INSTANCE,'original_recording_gpu_uuid':n.GPU,'original_freeze_sha256':n.FREEZE,
           'excluded_ids':['hard-16'],'binding':binding,'budget_amendment':budget,'authorization':authorization,'original_preservation':preservation}
        put(out/'backup-receipt.json',{**common,'all_remote_artifacts_backed_up':True,'final_decisions':90,'last_stop_epoch':1900.,'readiness':n.desc(out/'readiness.json'),
           'evidence_manifest':n.desc(out/'backup-manifest.json'),'gpu_hours_snapshot':n.desc(out/'gpu-hours-before-delete.md'),'stopped_state_snapshot':n.desc(out/'stopped-state.json'),
           'canonical_ledger':{**n.desc(self.ledger),'remote_sha256':n.sha(self.ledger)}})
        intent={'operation':'delete','method':'DELETE','instance_id':n.INSTANCE,'rental_scope_sha256':n.SCOPE,'path':f'/api/v0/instances/{n.INSTANCE}/','requested_epoch':1999.}
        put(out/'intent.json',intent);put(out/'outcome.json',{**intent,'phase':'response'});put(out/'reconciliation.json',{'instance_id':n.INSTANCE,'destroyed_epoch':2000.,'pending_intent':None})
        put(out/'cleanup.json',{**common,'confirmed_absent':True,'stopped_confirmed':True,'owned_work_quiescent':True,'destroyed_epoch':2000.,
           'canonical_ledger_sha256':n.sha(self.ledger),'remote_ledger_sha256':n.sha(self.ledger),'gpu_hours_log_sha256':n.sha(self.hours),
           'ledger_summary':n.ledger_summary(self.ledger,self.seed),'backup_receipt':n.desc(out/'backup-receipt.json'),'delete_intent':n.desc(out/'intent.json'),
           'delete_outcome':n.desc(out/'outcome.json'),'delete_reconciliation':n.desc(out/'reconciliation.json'),'final_state':n.desc(out/'final-state.json'),
           'gpu_accounting':{'prior_v0_and_five_hard_hosts_usd_upper':n.PRIOR_END,'inference_host_cost':cost,
              'total_usd_upper':n.PRIOR_END+cost['compute_usd_upper']+cost['disk_usd_upper'],'total_cap_usd':43,'network_and_slack_reserved_once':True}})
        self.args.provenance=str(self.ops/'provenance.json');self.args.readme=str(self.ops/'README.md');self.args.out=str(self.repo/'results/servedoctor-hard-20261103');self.args.create=False
        Path(self.args.readme).write_text(n.LABEL+' '+n.HEAD+' '+n.FREEZE+' analysis/analysis-report.html')
        entries=[]
        for group in n.GROUPS:
            q=self.ops/('safe-'+group+'.json');put(q,{'group':group});entries.append({'source':n.desc(q),'destination':'provenance/'+group+'/safe.json','group':group})
        previous=self.f.fixture.failure;partial=n.load(previous);patch.object(n,'PRIOR_PARTIAL_FAILURE_INDEX',n.sha(previous)).start()
        original=partial['original_failure_index'];patch.object(n,'ORIGINAL_FAILURE_INDEX',original['sha256']).start()
        for row in partial['failures']:
            for item in row['artifacts']:
                if not any(x['source']==item for x in entries):entries.append({'source':item,'destination':'provenance/inherited/'+Path(item['path']).name,'group':'failures'})
        failure=self.ops/'inference-failure-index.json';put(failure,{**partial,'project':n.PROJECT,'label':n.LABEL,'finalized':True,
            'prior_partial_failure_index':n.desc(previous),'retained_prior_partial_entries':21})
        put(Path(self.args.provenance),{'project':n.PROJECT,'label':n.LABEL,'files':entries,'failure_index':n.desc(failure)})
        source=self.ops/'package_inference_results.py';source.write_bytes(Path(n.__file__).read_bytes());patch.object(n,'__file__',str(source)).start()
        return out
    def test_cleanup_matches_snapshot_before_delete_and43cap(self):
        self.finish_fixture();e=n.Evidence(self.args,self.repo);value=n.verify_cleanup(e,self.args)
        self.assertTrue(value['confirmed_absent']);self.assertLess(value['gpu_accounting']['total_usd_upper'],43)
    def test_missing_backup_input_blocks(self):
        out=self.finish_fixture();m=n.load(out/'backup-manifest.json');m['files'].pop(next(iter(m['files'])));put(out/'backup-manifest.json',m)
        b=n.load(out/'backup-receipt.json');b['evidence_manifest']=n.desc(out/'backup-manifest.json');put(out/'backup-receipt.json',b)
        c=n.load(out/'cleanup.json');c['backup_receipt']=n.desc(out/'backup-receipt.json');put(out/'cleanup.json',c)
        with self.assertRaises(ValueError):n.verify_cleanup(n.Evidence(self.args,self.repo),self.args)
    def test_fresh_package_create_and_existing_destination_refused(self):
        self.finish_fixture();self.args.create=True
        result=n.execute(self.args,repo=self.repo,repository_check=lambda _:None);self.assertTrue(result['created'])
        out=Path(self.args.out);self.assertTrue((out/'original-frozen-attempt/answers/answer_keys.json').is_file())
        self.assertTrue((out/'analysis/analysis-report.html').is_file())
        with self.assertRaises(ValueError):n.execute(self.args,repo=self.repo,repository_check=lambda _:None)
if __name__=='__main__':unittest.main()
