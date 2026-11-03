"""Synthetic filesystem/provider only; opaque key/report canaries stay unread."""
import argparse
import contextlib
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import finalize_partial_rental as f


class FakeRental:
    def __init__(self,repo,old,scope,state):
        self.repo,self.root,self.scope_path=repo,old,scope;self.state_path=old/'session.json';self.state=state
        self.gets=self.deletes=0;self.confirm=True;self.crash=False;self.total=38.0;self.save(state)
    def load(self):return copy.deepcopy(self.state)
    def save(self,state):
        self.state=copy.deepcopy(state);f.h.write(self.state_path,state)
        (self.repo/'runs/servedoctor-gpu-hours.md').write_text('mutable hours '+str(state.get('destroyed_epoch')))
    def lock(self):return contextlib.nullcontext()
    def cost(self,state):return {'prior_v0_usd_upper':25.90010443543525,'total_usd_upper':self.total,'prior_hard_host_cost':{'compute_usd_upper':1},'current_host_cost':{'compute_usd_upper':2}}
    def reconcile(self):
        self.gets+=1;state=self.load()
        if state.get('pending_intent') and self.confirm:state['destroyed_epoch']=1300.;state.pop('pending_intent')
        self.save(state)
    def intent(self,state,operation,path,reason):
        if self.crash:raise RuntimeError('Synthetic interrupted dispatch')
        assert operation=='delete' and path==f'/api/v0/instances/{f.INSTANCE}/';self.deletes+=1
        record={'project':f.PROJECT,'instance_id':f.INSTANCE,'rental_scope_sha256':f.SCOPE,'operation':'delete','method':'DELETE','path':path}
        target=self.root/'intent-9999-delete.json';f.write_new(target,record)
        f.write_new(target.with_name(target.stem+'-outcome.json'),{**record,'phase':'response' if self.confirm else 'unknown_outcome'})
        state['pending_intent']=target.name;self.save(state)


class PartialFinalizerContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.addCleanup(patch.stopall)
        self.repo=Path(self.tmp.name).resolve();self.old=self.repo/f.OLD_REL;self.old.mkdir(parents=True)
        self.ops=self.repo/f.NEW_REL;self.ops.mkdir();self.study=self.repo/f.STUDY_REL;self.study.mkdir()
        self.original=self.old/'blocked-hard-study-attempt1/latest/study';self.original.mkdir(parents=True)
        self.remote=self.ops/'final-remote-ops';self.remote.mkdir();self.remote_old=self.ops/'final-remote-old-ops';self.remote_old.mkdir()
        self.control=self.ops/'final-remote-control';self.control.mkdir()
        self.scope=self.old/'rental-scope.json';self.put(self.scope,{'project':f.PROJECT,'instance_id':f.INSTANCE})
        self.pin('SCOPE',self.scope);patch.object(f.base,'SCOPE',f.SCOPE).start();(self.control/'rental-scope.json').write_bytes(self.scope.read_bytes())
        (self.control/'guard.log').write_text('public safe metadata')
        self.helper={name:'# synthetic '+name for name in f.HELPER_SHA256}
        for name,text in self.helper.items():(self.remote/name).write_text(text)
        patch.object(f,'HELPER_SHA256',{n:f.sha(self.remote/n) for n in self.helper}).start()
        (self.remote_old/'hard_integrity.py').write_text('# synthetic original frozen integrity')
        for name in ('study.json','scenarios.json','commitment.json'):(self.original/name).write_bytes(b'OPAQUE ORIGINAL INPUT')
        answers=self.original/'answers';answers.mkdir();(answers/'answer_keys.json').write_bytes(b'INVALID JSON KEY CANARY NEVER DECODED')
        runtime=answers/'runtime';runtime.mkdir()
        manifests={}
        for incident in f.ALL_IDS:
            folder=self.original/'incidents'/incident;folder.mkdir(parents=True)
            for name in f.SEALED:
                if name=='recording.json':self.put(folder/name,{'status':'completed','duration_s':90})
                else:(folder/name).write_bytes(b'opaque public sealed payload')
            self.put(folder/'manifest.json',{'files':{n:f.sha(folder/n) for n in f.SEALED}})
            manifests[incident]=f.sha(folder/'manifest.json');(runtime/(incident+'.json')).write_bytes(b'OPAQUE RUNTIME INVALID JSON')
        engine=self.original/'engines/engine-06-hard-16';engine.mkdir(parents=True);(engine/'engine.log').write_text('Synthetic startup failed negativeKV')
        self.pin('FAILURE_LOG',engine/'engine.log')
        self.put(self.original/'hard-experiment-freeze.json',{'source_commit':f.SOURCE,'files_sha256':{f.OLD_REL+'/hard_integrity.py':f.sha(self.remote_old/'hard_integrity.py')}})
        self.pin('FREEZE',self.original/'hard-experiment-freeze.json')
        import shutil;shutil.copytree(self.original,self.study,dirs_exist_ok=True)
        self.exclusion=self.old/'partial-analysis-exclusion-20261102T2306Z.json'
        self.preservation=self.old/'blocked-hard-study-attempt1/preservation-receipt.json';self.put(self.preservation,{'opaque_backup':True});self.pin('PRESERVATION',self.preservation)
        self.put(self.exclusion,{'analysis_label':f.LABEL,'included_hard_ids':list(f.IDS),'excluded_ids':['hard-16'],
            'before_validation':True,'before_any_hard_arm_evaluation':True,'prompts_rules_scoring_answer_keys_unchanged':True,
            'native_validity_must_not_be_rewritten':True,'full_hard_set_claim_permitted':False,'hard16_may_be_modified_regenerated_or_rerecorded':False,
            'original_source_commit':f.SOURCE,'original_freeze_sha256':f.FREEZE,'original_preservation_receipt':{'sha256':f.PRESERVATION},
            'limits':{'gpu_total_usd':40,'meta_ledger_cap_usd':50,'baseten_ledger_cap_usd':20,
                'analysis_cutoff_utc':'2026-11-03T23:00:00Z','paid_calls_finish_cutoff_utc':'2026-11-04T04:59:59Z',
                'optional_live_runs_minimum_gpu_budget_remaining_usd':5}});self.pin('EXCLUSION',self.exclusion)
        origin=f.inventory_tree(self.original,self.repo)
        self.preserved=self.old/'blocked-hard-study-attempt1/preserved-files-manifest.json';self.put(self.preserved,{'files':{'latest/study/'+n:v for n,v in origin.items()}});self.pin('PRESERVED_MANIFEST',self.preserved)
        owned=[]
        for i in range(3):
            folder=self.remote_old/('proof-'+str(i));folder.mkdir();(folder/'observations.jsonl').write_text('public observation')
            self.put(folder/'ready.json',{'ready':True})
            self.put(folder/'owned.json',{'finished':True,'issues':[],'owned_leaks':[],
                'observations':self.remote_desc(folder/'observations.jsonl',f.OLD_REL+'/proof-'+str(i)+'/observations.jsonl'),
                'readiness':self.remote_desc(folder/'ready.json',f.OLD_REL+'/proof-'+str(i)+'/ready.json')})
            owned.append(self.remote_desc(folder/'owned.json',f.OLD_REL+'/proof-'+str(i)+'/owned.json'))
        protocol={'project':f.ANALYSIS_PROJECT,'label':f.LABEL,'study_dir':f.STUDY_REL,'original_study_dir':'runs/sd-hard',
            'source_commit':f.SOURCE,'included_hard_ids':list(f.IDS),'excluded_ids':['hard-16'],'scientific_inputs_changed':False,'old_helpers_changed':False,
            'reference_and_hard_recordings':16,'original_inventory_sha256':origin,'private_helpers_sha256':f.HELPER_SHA256,'owned_proofs':owned,
            'exclusion':f.desc(self.exclusion),'preservation':f.desc(self.preservation),
            'original_freeze':self.remote_desc(self.original/'hard-experiment-freeze.json','runs/sd-hard/hard-experiment-freeze.json')}
        self.put(self.study/'analysis-protocol.json',protocol);(self.study/'analysis-label.txt').write_text(f.LABEL+'\n')
        valid=self.study/'answers/validity.json';self.put(valid,{'total':15,'valid':14,'incidents':[{'id':n,'valid':i!=0} for i,n in enumerate(f.IDS)]})
        validation=self.remote/'validation-attempt1';validation.mkdir();(validation/'validate.stdout').write_text('safe count');(validation/'validate.stderr').write_bytes(b'')
        quality={'project':f.ANALYSIS_PROJECT,'label':f.LABEL,'complete':True,'expected_recordings':16,'hard_incidents':15,
            'protocol_sha256':f.sha(self.study/'analysis-protocol.json'),'recordings':[{'id':n,'complete':True,'manifest_sha256':v} for n,v in manifests.items()], 'owned_observer_proofs':owned}
        self.put(validation/'quality.json',quality)
        raw={f'incidents/{n}/{item}':f.sha(self.study/'incidents'/n/item) for n in f.ALL_IDS for item in f.SEALED|{'manifest.json'}}
        raw.update({f'answers/runtime/{n}.json':f.sha(self.study/'answers/runtime'/(n+'.json')) for n in f.ALL_IDS})
        dispatch={'project':f.ANALYSIS_PROJECT,'label':f.LABEL,'study_dir':f.STUDY_REL,'protocol':self.remote_desc(self.study/'analysis-protocol.json',f.STUDY_REL+'/analysis-protocol.json'),
            'quality':self.remote_desc(validation/'quality.json',f.NEW_REL+'/validation-attempt1/quality.json'),'manifests':manifests,'recording_bytes_sha256':raw}
        self.put(validation/'dispatch.json',dispatch);dispatch_desc=self.remote_desc(validation/'dispatch.json',f.NEW_REL+'/validation-attempt1/dispatch.json')
        self.put(self.study/'hard-partial-validation-dispatch.json',{'project':f.ANALYSIS_PROJECT,'label':f.LABEL,'dispatch':dispatch_desc})
        self.put(validation/'result.json',{'project':f.ANALYSIS_PROJECT,'label':f.LABEL,'completed':True,'returncode':0,'failure':None,
            'dispatch':dispatch_desc,'study_dispatch_sha256':f.sha(self.study/'hard-partial-validation-dispatch.json'),
            'stdout_sha256':f.sha(validation/'validate.stdout'),'stderr_sha256':f.sha(validation/'validate.stderr'),
            'total':15,'valid':14,'invalid':1,'validity':self.remote_desc(valid,f.STUDY_REL+'/answers/validity.json')})
        self.eval=self.ops/'evaluation-attempt1';self.eval.mkdir()
        gate={'project':f.ANALYSIS_PROJECT,'label':f.LABEL,'evaluation_ready':True,'total':15,'protocol_sha256':f.sha(self.study/'analysis-protocol.json'),'validation_sha256':f.sha(validation/'result.json')}
        self.put(self.eval/'integrity-preflight.stdout',gate)
        self.put(self.eval/'contexts.json',{'project':f.ANALYSIS_PROJECT,'label':f.LABEL,'incidents':15,'fits_8192':True,'context_tokens':8192,
            'model_revision':'cec94fcfd6512f2cfe708138c32533b346ea4f69','per_incident_maximum':{n:{} for n in f.IDS},'public_manifests_sha256':manifests,
            'freeze_sha256':f.FREEZE,'validation':gate,'helper_sha256':f.HELPER_SHA256['measure_contexts.py']})
        decisions={}
        for arm in f.ARMS:
            folder=self.study/'decisions'/arm;folder.mkdir(parents=True)
            for n in f.IDS:(folder/(n+'.json')).write_bytes(b'OPAQUE MODEL DECISION NEVER PRINTED')
            decisions[arm]={n:f.sha(folder/(n+'.json')) for n in f.IDS}
        for label,arms in [('rules-spark-wonder',('rules','spark','wonder')),('glimmer-cascades',('glimmer','glimmer_to_spark','glimmer_to_wonder'))]:
            groups={arm:{'incidents':15,'call_failures':0,'ready_for_next_group':True,'incidents_with_successful_response':15,
                'per_incident':[{'id':n,'call_failures':0,'successful_responses':1,'decision_sha256':decisions[arm][n]} for n in f.IDS]} for arm in arms}
            self.put(self.eval/(label+'-responses.json'),{'project':f.ANALYSIS_PROJECT,'label':f.LABEL,'ready_for_next_group':True,'by_arm':groups,'validation':gate,'helper_sha256':f.HELPER_SHA256['model_response_guard.py']})
        boards={'all':{arm:{'incidents':15} for arm in f.ARMS},'valid_only':{arm:{'incidents':14} for arm in f.ARMS}}
        projection=self.eval/'hard15-score-projection.json'
        self.put(projection,{'project':f.ANALYSIS_PROJECT,'label':f.LABEL,'decision_coverage':{'expected':90,'present':90},'valid_cases':14,'invalid_cases':1,
            'final_decisions_sha256':decisions,'validity_sha256':f.sha(valid),'freeze_sha256':f.FREEZE,'scoreboards':boards,'per_case':[{}]*90,
            'validation':gate,'helper_sha256':f.HELPER_SHA256['export_hard_scores.py']})
        for key in boards:self.put(self.eval/('final-score-'+key+'.stdout'),boards[key])
        for name in ('report.html','report.json'):(self.study/name).write_bytes(b'OPAQUE INVALID NATIVE REPORT CANARY')
        self.put(self.study/'analysis-report.json',{'project':f.ANALYSIS_PROJECT,'label':f.LABEL,'scoreboards':boards,
            'native_report_html':self.remote_desc(self.study/'report.html',f.STUDY_REL+'/report.html'),
            'native_report_json':self.remote_desc(self.study/'report.json',f.STUDY_REL+'/report.json'),
            'score_projection':f.desc(projection)})
        (self.study/'analysis-report.html').write_text(f.LABEL)
        self.seed=self.old/'ledger-seed.json';self.put(self.seed,{'project':'servedoctor','caps_usd':{'meta':'50','baseten':'20'},'entries':[]});self.pin('SEED',self.seed);patch.object(f.base,'SEED',f.SEED).start()
        self.ledger=self.eval/'final-canonical-ledger.json';self.put(self.ledger,{'project':'servedoctor','caps_usd':{'meta':'50','baseten':'20'},'entries':[{'id':'invented','status':'settled','provider':'meta','accounted_usd':'0.1'}]})
        self.put(self.eval/'final-ledger.stdout',{'sha256':f.sha(self.ledger),'summary':f.base.ledger_summary(self.ledger,self.seed)})
        self.refresh_mirror()
        parent=self.old/'partial-resume-pipeline-attempt1';parent.mkdir();self.pipeline=parent/'outcome.json'
        self.put(self.pipeline,{'project':f.PROJECT,'instance_id':f.INSTANCE,'rental_scope_sha256':f.SCOPE,'returncode':0,'stop_confirmed':True,'cleanup_confirmed':True})
        state={'project':f.PROJECT,'instance_id':f.INSTANCE,'scope_sha256':f.SCOPE,'running_intervals':[{'start_epoch':1000.,'stop_epoch':1100.}],
            'last_status':{'id':f.INSTANCE,'actual_status':'exited','cur_state':'stopped','intended_status':'stopped'}}
        self.service=FakeRental(self.repo,self.old,self.scope,state);self.out=self.ops/'final-partial-cleanup-attempt1'
        self.args=argparse.Namespace(study_dir=str(self.study),original_dir=str(self.original),evaluation_dir=str(self.eval),pipeline_outcome=str(self.pipeline),
            remote_ops=str(self.remote),remote_old_ops=str(self.remote_old),remote_control=str(self.control),ledger=str(self.ledger),ledger_seed=str(self.seed),out=str(self.out),
            verify_only=True,prepare_backup=False,delete=False,reconcile=False)
    def put(self,path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
    def pin(self,name,path):patch.object(f,name,f.sha(path)).start()
    def remote_desc(self,path,relative):return {'path':f.REMOTE+relative,'sha256':f.sha(path)}
    def refresh_mirror(self):
        target=self.eval/'mirror-manifest.json';self.put(target,{'stable':True,'study_files_sha256':f.inventory_tree(self.study,self.repo),
            'study_file_count':len(f.inventory_tree(self.study,self.repo)),'ledger_sha256':f.sha(self.ledger)})
        self.put(self.eval/'outcome.json',{'project':f.ANALYSIS_PROJECT,'label':f.LABEL,'study_dir':f.STUDY_REL,'completed':True,'failure':None,'cleanup_errors':[],
            'groups':['rules-spark-wonder','glimmer-cascades'],'opaque_mirror':{'manifest_sha256':f.sha(target)}})
    def mode(self,name):
        args=copy.deepcopy(self.args)
        for key in ('verify_only','prepare_backup','delete','reconcile'):setattr(args,key,key==name)
        return args
    def prepare(self):return f.execute(self.mode('prepare_backup'),service=self.service)
    def test_default_zero_writes_provider_and_opaque_answers_native_reports(self):
        before=self.ledger.read_bytes();value=f.execute(self.args,service=self.service)
        self.assertEqual(value['final_decisions'],90);self.assertFalse(self.out.exists());self.assertEqual(self.service.gets,0);self.assertEqual(self.ledger.read_bytes(),before)
    def test_backup_includes_both_studies_and_immutable_hours_excludes_mutable(self):
        self.prepare();receipt=f.load(self.out/'backup-receipt.json');files=f.load(receipt['evidence_manifest']['path'])['files']
        self.assertIn(str((self.original/'answers/answer_keys.json').relative_to(self.repo)),files)
        self.assertIn(str((self.study/'answers/answer_keys.json').relative_to(self.repo)),files)
        self.assertNotIn(str(self.service.state_path.relative_to(self.repo)),files);self.assertNotIn('runs/servedoctor-gpu-hours.md',files)
        self.assertIn(str((self.out/'gpu-hours-before-delete.md').relative_to(self.repo)),files)
    def test_one_delete_fresh_stopped_get_fixed_cleanup_and_get_only_repeat(self):
        self.prepare();result=f.execute(self.mode('delete'),service=self.service);self.assertTrue(result['confirmed_absent']);self.assertEqual(self.service.deletes,1)
        cleanup=f.load(self.out/'cleanup.json');self.assertEqual(cleanup['gpu_hours_log_sha256'],f.sha(self.repo/'runs/servedoctor-gpu-hours.md'))
        self.assertEqual(cleanup['analysis_project'],f.ANALYSIS_PROJECT);self.assertEqual(cleanup['excluded_ids'],['hard-16'])
        before=(self.out/'cleanup.json').read_bytes();gets=self.service.gets;f.execute(self.mode('reconcile'),service=self.service)
        self.assertEqual(self.service.gets,gets);self.assertEqual((self.out/'cleanup.json').read_bytes(),before)
        with self.assertRaises(ValueError):f.execute(self.mode('delete'),service=self.service)
        self.assertEqual(self.service.deletes,1)
    def test_unknown_delete_no_retry_only_get_reconciliation(self):
        self.prepare();self.service.confirm=False;self.assertFalse(f.execute(self.mode('delete'),service=self.service)['confirmed_absent'])
        with self.assertRaises(ValueError):f.execute(self.mode('delete'),service=self.service)
        self.service.confirm=True;self.assertTrue(f.execute(self.mode('reconcile'),service=self.service)['confirmed_absent']);self.assertEqual(self.service.deletes,1)
    def test_crash_before_intent_retains_dispatch_no_replay(self):
        self.prepare();self.service.crash=True
        with self.assertRaises(RuntimeError):f.execute(self.mode('delete'),service=self.service)
        self.assertTrue((self.out/'delete-dispatch.json').exists())
        with self.assertRaises(ValueError):f.execute(self.mode('delete'),service=self.service)
        self.assertEqual(self.service.deletes,0)
    def test_original_keys_cannot_change_even_with_protocol_and_copy(self):
        (self.original/'answers/answer_keys.json').write_bytes(b'changed key');(self.study/'answers/answer_keys.json').write_bytes(b'changed key')
        protocol=f.load(self.study/'analysis-protocol.json');protocol['original_inventory_sha256']=f.inventory_tree(self.original,self.repo);self.put(self.study/'analysis-protocol.json',protocol)
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.out.exists());self.assertEqual(self.service.gets,0)
    def test_missing_decision_or_false_model_usage_rejected(self):
        value=f.load(self.eval/'rules-spark-wonder-responses.json');value['by_arm']['spark']['per_incident'][0]['successful_responses']=0;self.put(self.eval/'rules-spark-wonder-responses.json',value)
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.out.exists())
    def test_changed_native_validity_rejected(self):
        value=f.load(self.study/'answers/validity.json');value['incidents'][0]['valid']=True;value['valid']=15;self.put(self.study/'answers/validity.json',value)
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(self.service.gets,0)
    def test_bad_recording_seal_even_with_mirror_manifest_rejected(self):
        (self.study/'incidents/hard-01/requests.jsonl').write_text('changed');self.refresh_mirror()
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(self.service.gets,0)
    def test_unfinished_parent_watchdog_blocks_before_output(self):
        value=f.load(self.pipeline);value['watchdog_cleanup_error_class']='TimeoutExpired';self.put(self.pipeline,value)
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.out.exists())
    def test_warning_or_shared_gpu_cap_blocks_without_provider(self):
        self.service.total=40.01
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(self.service.gets,0);self.assertFalse(self.out.exists())
    def test_private_identity_never_read(self):
        private=self.control/'ssh_ed25519';private.write_bytes(b'PRIVATE CANARY')
        read=Path.read_bytes
        def guarded(path):
            if path==private:raise AssertionError('private content accessed')
            return read(path)
        with patch.object(Path,'read_bytes',guarded):
            with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(self.service.gets,0)
    def test_symlink_and_remote_descriptor_escape_rejected(self):
        protocol=f.load(self.study/'analysis-protocol.json');protocol['owned_proofs'][0]['path']=f.REMOTE+'runs/unmapped/owned.json';self.put(self.study/'analysis-protocol.json',protocol)
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(self.service.gets,0)
    def test_changed_stopped_state_after_backup_fails_fresh_get_before_delete(self):
        self.prepare();original=self.service.reconcile
        def changed():
            original();self.service.state['last_status']['actual_status']='running'
        self.service.reconcile=changed
        with self.assertRaises(ValueError):f.execute(self.mode('delete'),service=self.service)
        self.assertEqual(self.service.deletes,0)
    def test_full17_backup_is_never_called_or_weakened(self):
        with patch.object(f.h.Rental,'backup',side_effect=AssertionError('Full17 gate must stay separate')):
            self.prepare();self.assertTrue(f.execute(self.mode('delete'),service=self.service)['confirmed_absent'])
    def test_native_cli_score_dictionary_must_match_projection(self):
        value=f.load(self.eval/'final-score-all.stdout');value['spark']['incidents']=14;self.put(self.eval/'final-score-all.stdout',value)
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.out.exists());self.assertEqual(self.service.gets,0)
    def test_descriptor_traversal_and_api_key_never_read(self):
        path=self.control/'vast_api_key';path.write_bytes(b'PRIVATE KEY CANARY')
        read=Path.read_bytes
        def guarded(p):
            if p==path:raise AssertionError('credential read')
            return read(p)
        with patch.object(Path,'read_bytes',guarded):
            with self.assertRaises(ValueError):f.regular(path,self.repo)
            with self.assertRaises(ValueError):f.regular(self.control/'..'/'final-remote-control'/'guard.log',self.repo)
    def test_default_provider_constructor_is_explicitly_blocked(self):
        with patch.object(f.h,'Rental',return_value=self.service) as ctor:f.execute(self.args)
        self.assertEqual(ctor.call_args.kwargs,{'api':f.blocked,'inventory':f.blocked})


if __name__=='__main__':unittest.main()
