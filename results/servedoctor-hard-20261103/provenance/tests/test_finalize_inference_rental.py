"""Lifecycle/opaque-copy fixtures; mapped science gate has separate contracts."""
import argparse
import contextlib
import copy
import json
from pathlib import Path
import tempfile
import shutil
import unittest
from unittest.mock import patch

import finalize_inference_rental as f


class Service:
    def __init__(self,repo,root,state):
        self.repo,self.root=repo,root;self.scope_path=root/'rental-scope.json';self.binding_path=root/'binding.json';self.state_path=root/'session.json'
        self.state=state;self.gets=self.deletes=0;self.confirm=True;self.crash=False;self.total=41.;self.save(state)
    def load(self):return copy.deepcopy(self.state)
    def lock(self):return contextlib.nullcontext()
    def save(self,state):
        self.state=copy.deepcopy(state);f.v.write(self.state_path,state)
        (self.repo/'runs/servedoctor-gpu-hours.md').write_text('global all-host hours '+str(state.get('destroyed_epoch')))
    def reconcile(self):
        self.gets+=1;state=self.load()
        if state.get('pending_intent') and self.confirm:state['destroyed_epoch']=1300.;state.pop('pending_intent')
        self.save(state);return state
    def cost(self,state):return {'prior_v0_and_five_hard_hosts_usd_upper':f.PRIOR_TOTAL,'inference_host_cost':{'compute_usd_upper':3.,'disk_usd_upper':.1},'total_usd_upper':self.total}
    def intent(self,state,operation,path,reason):
        if self.crash:raise RuntimeError('invented interrupted dispatch')
        assert operation=='delete' and path==f'/api/v0/instances/{f.INSTANCE}/';self.deletes+=1
        target=self.root/'intent-9999-delete.json'
        row={'project':f.PROJECT,'instance_id':f.INSTANCE,'rental_scope_sha256':f.SCOPE,'operation':'delete','method':'DELETE','path':path}
        f.write_new(target,row);f.write_new(target.with_name(target.stem+'-outcome.json'),{**row,'phase':'response' if self.confirm else 'unknown_outcome'})
        state['pending_intent']=target.name;self.save(state)


class FinalInferenceContracts(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.addCleanup(patch.stopall)
        self.repo=Path(self.t.name).resolve();self.ops=self.repo/'runs/servedoctor-hard15-ops-20261102';self.ops.mkdir(parents=True)
        self.root=self.ops/'inference-rental-attempt1';self.root.mkdir()
        self.args=argparse.Namespace(**{k:str(v) for k,v in f.defaults(self.repo).items()},verify_only=True,prepare_backup=False,delete=False,reconcile=False)
        self.dirs=[Path(getattr(self.args,k)) for k in ('study_dir','original_study_dir','evaluation_dir','remote_ops','remote_old_ops','remote_control')]
        for folder in self.dirs:folder.mkdir(parents=True)
        self.study=Path(self.args.study_dir);self.origin=Path(self.args.original_study_dir)
        for folder in (self.study,self.origin):
            (folder/'answers').mkdir();(folder/'answers/answer_keys.json').write_bytes(b'OPAQUE INVALID-JSON KEYS NEVER DECODED')
            (folder/'report.json').write_bytes(b'OPAQUE INVALID-JSON NATIVE REPORT NEVER DECODED')
            (folder/'public.log').write_bytes(b'public retained evidence')
        for folder in self.dirs[2:]:(folder/'public-proof.json').write_text('{}')
        self.put(self.root/'rental-scope.json',{'project':f.PROJECT,'instance_id':f.INSTANCE})
        patch.object(f,'SCOPE',f.sha(self.root/'rental-scope.json')).start()
        self.put(self.root/'binding.json',{'project':f.PROJECT,'instance_id':f.INSTANCE,'rental_scope_sha256':f.SCOPE})
        self.put(self.root/'outcome.json',{'project':f.PROJECT,'instance_id':f.INSTANCE,'rental_scope_sha256':f.SCOPE,'returncode':0,
            'stop_confirmed':True,'cleanup_confirmed':True,'transport_cleanup_returncode':0})
        self.put(self.ops/'gpu-budget-amendment-43-20261102.json',{'authorized_total':43});patch.object(f.v,'AMENDMENT_SHA',f.sha(self.ops/'gpu-budget-amendment-43-20261102.json')).start()
        old=self.repo/f.old.OLD_REL;old.mkdir();self.put(old/'partial-analysis-exclusion-20261102T2306Z.json',{'user':True});patch.object(f.old,'EXCLUSION',f.sha(old/'partial-analysis-exclusion-20261102T2306Z.json')).start()
        preservation=old/'blocked-hard-study-attempt1/preservation-receipt.json';self.put(preservation,{'original178':True});patch.object(f.old,'PRESERVATION',f.sha(preservation)).start()
        self.ledger=Path(self.args.ledger);self.ledger.write_bytes(b'OPAQUE CANONICAL FINAL LEDGER FIXTURE')
        relay=self.ops/'inference-transport-attempt1';relay.mkdir();self.put(relay/'stop-1.json',{'stopped':True,'cleanup':[]})
        attempt=self.root/'meta-relay-attempt-fixture';attempt.mkdir()
        self.put(attempt/'transport-ready.json',{'instance_id':f.INSTANCE,'owned_processes':{
            'relay':{'pid':999991,'start_identity':'born relay'},'ssh':{'pid':999992,'start_identity':'born ssh'}}})
        self.put(relay/'relay-pointer.json',{'instance_id':f.INSTANCE,'rental_scope_sha256':f.SCOPE,'attempt_dir':str(attempt)})
        self.put(relay/'guardian-process.json',{'pid':999993,'start_identity':'born guardian'})
        patch.object(f,'process_identity',return_value=None).start()
        state={'project':f.PROJECT,'instance_id':f.INSTANCE,'scope_sha256':f.SCOPE,'running_intervals':[{'start_epoch':1000.,'stop_epoch':1100.}],
            'last_status':{'actual_status':'exited','cur_state':'stopped','intended_status':'stopped'}}
        self.s=Service(self.repo,self.root,state);self.out=Path(self.args.out);self.gate_calls=0;self.gate_failure=False
    def put(self,path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
    def verify(self,args,repo):
        self.gate_calls+=1
        if self.gate_failure:raise ValueError('Synthetic science gate rejects missing90/validity/context/response')
        inputs={str(p.relative_to(self.repo)):f.sha(p) for folder in self.dirs for p in folder.rglob('*') if p.is_file()}
        return {'project':f.ANALYSIS_PROJECT,'label':f.LABEL,'ready':True,'recordings':16,'final_decisions':90,
            'canonical_ledger_sha256':f.sha(self.ledger),'inference_binding_sha256':f.sha(self.s.binding_path),'original_freeze_sha256':f.old.FREEZE,
            'ledger_summary':{'caps_usd':{'meta':50,'baseten':20},'warnings':[]},'input_files_sha256':inputs}
    def mode(self,name):
        args=copy.deepcopy(self.args)
        for k in ('verify_only','prepare_backup','delete','reconcile'):setattr(args,k,k==name)
        return args
    def execute(self,name='verify_only'):return f.execute(self.mode(name),self.s,self.verify)
    def test_default_local_gate_zero_provider_writes_and_opaque_keys_reports(self):
        value=self.execute();self.assertTrue(value['ready']);self.assertEqual(self.gate_calls,1);self.assertEqual(self.s.gets,0);self.assertFalse(self.out.exists())
        self.assertEqual(value['final_decisions'],90)
    def test_backup_whole_explicit_mirrors_original_and_partial_with_immutable_hours_state(self):
        self.execute('prepare_backup');receipt=f.load(self.out/'backup-receipt.json');files=f.load(receipt['evidence_manifest']['path'])['files']
        for folder in (self.study,self.origin):self.assertIn(str((folder/'answers/answer_keys.json').relative_to(self.repo)),files)
        self.assertNotIn('runs/servedoctor-gpu-hours.md',files);self.assertNotIn(str(self.s.state_path.relative_to(self.repo)),files)
        self.assertIn(str((self.out/'gpu-hours-before-delete.md').relative_to(self.repo)),files)
        self.assertIn(str((self.out/'stopped-state.json').relative_to(self.repo)),files)
    def test_exact_one_delete_fresh_get_fixed_cost_then_no_provider_repeat(self):
        self.execute('prepare_backup');self.assertTrue(self.execute('delete')['confirmed_absent']);self.assertEqual(self.s.deletes,1)
        cleanup=f.load(self.out/'cleanup.json');self.assertEqual(cleanup['gpu_accounting']['total_usd_upper'],41.)
        self.assertEqual(cleanup['gpu_hours_log_sha256'],f.sha(self.repo/'runs/servedoctor-gpu-hours.md'))
        before=(self.out/'cleanup.json').read_bytes();gets=self.s.gets;self.execute('reconcile')
        self.assertEqual(self.s.gets,gets);self.assertEqual((self.out/'cleanup.json').read_bytes(),before)
        with self.assertRaises(ValueError):self.execute('delete')
        self.assertEqual(self.s.deletes,1)
    def test_unknown_delete_get_only_never_replayed(self):
        self.execute('prepare_backup');self.s.confirm=False;self.assertFalse(self.execute('delete')['confirmed_absent'])
        with self.assertRaises(ValueError):self.execute('delete')
        self.s.confirm=True;self.assertTrue(self.execute('reconcile')['confirmed_absent']);self.assertEqual(self.s.deletes,1)
    def test_preintent_crash_preserves_writeahead_and_never_replays(self):
        self.execute('prepare_backup');self.s.crash=True
        with self.assertRaises(RuntimeError):self.execute('delete')
        self.assertTrue((self.out/'delete-dispatch.json').exists())
        with self.assertRaises(ValueError):self.execute('delete')
        self.assertEqual(self.s.deletes,0)
    def test_failed_science_gate_blocks_before_backup_or_provider(self):
        self.gate_failure=True
        with self.assertRaises(ValueError):self.execute('prepare_backup')
        self.assertEqual(self.s.gets,0);self.assertFalse(self.out.exists())
    def test_parent_or_relay_cleanup_failure_blocks(self):
        value=f.load(self.root/'outcome.json');value['cleanup_confirmed']=False;self.put(self.root/'outcome.json',value)
        with self.assertRaises(ValueError):self.execute('prepare_backup')
        self.assertEqual(self.s.gets,0)
    def test_shared43_cap_and_prior_five_costs_required(self):
        self.s.total=43.01
        with self.assertRaises(ValueError):self.execute('prepare_backup')
        self.assertFalse(self.out.exists())
    def test_changed_backup_and_ledger_scientific_input_blocks_delete(self):
        self.execute('prepare_backup');(self.study/'answers/answer_keys.json').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.execute('delete')
        self.assertEqual(self.s.gets,0);self.assertEqual(self.s.deletes,0)
    def test_fresh_get_running_blocks_one_delete(self):
        self.execute('prepare_backup');original=self.s.reconcile
        def running():original();self.s.state['last_status']['actual_status']='running'
        self.s.reconcile=running
        with self.assertRaises(ValueError):self.execute('delete')
        self.assertEqual(self.s.deletes,0)
    def test_private_identity_never_read_or_backed(self):
        key=self.root/'ssh_ed25519';key.write_bytes(b'PRIVATE CANARY');original=Path.read_bytes
        def guarded(path):
            if path==key:raise AssertionError('Private identity read')
            return original(path)
        with patch.object(Path,'read_bytes',guarded):
            with self.assertRaises(ValueError):self.execute('prepare_backup')
        self.assertEqual(self.s.deletes,0)
    def test_default_provider_constructor_explicitly_blocked(self):
        with patch.object(f.v,'Rental',return_value=self.s) as ctor:f.execute(self.args,verifier=self.verify)
        self.assertEqual(ctor.call_args.kwargs,{'api':f.blocked,'inventory':f.blocked})
    def test_repeated_backup_never_overwrites_first(self):
        self.execute('prepare_backup');before=(self.out/'backup-receipt.json').read_bytes()
        with self.assertRaises(FileExistsError):self.execute('prepare_backup')
        self.assertEqual((self.out/'backup-receipt.json').read_bytes(),before)
    def test_live_owned_transport_pid_blocks_without_signalling(self):
        with patch.object(f,'process_identity',return_value={'pid':999991,'start_identity':'born relay'}):
            with self.assertRaises(ValueError):self.execute('prepare_backup')
        self.assertEqual(self.s.gets,0);self.assertEqual(self.s.deletes,0)
    def test_reused_unrelated_pid_is_not_owned_or_signalled(self):
        with patch.object(f,'process_identity',return_value={'start_identity':'different birth'}):self.assertTrue(self.execute()['ready'])
    def test_unreviewed_package_source_is_rejected_before_execution(self):
        path=self.ops/'package_inference_results.py';path.write_text("raise AssertionError('unreviewed code executed')\n")
        with self.assertRaises(ValueError):f.verify_inputs(self.args,self.repo)
        self.assertEqual(self.s.gets,0);self.assertEqual(self.s.deletes,0)


class SharedMappedGateContracts(unittest.TestCase):
    """Real mapped evidence gate on its full invented15/90 fixture, not a stub."""
    def setUp(self):
        import test_package_inference_results as fixtures
        import package_inference_results as package
        self.package=package;self.fx=fixtures.InputsTests('test_complete_safe_gate_without_cleanup_or_provider');self.fx.setUp()
        self.addCleanup(self.fx.doCleanups);self.addCleanup(patch.stopall)
        x=self.fx;repo=x.repo;ops=x.ops;root=ops/'inference-rental-attempt1';self.repo=repo;self.root=root
        values=f.defaults(repo);self.args=argparse.Namespace(**{k:str(v) for k,v in values.items()},verify_only=True,prepare_backup=False,delete=False,reconcile=False)
        shutil.copytree(x.root,Path(self.args.study_dir));shutil.copytree(x.f.original,Path(self.args.original_study_dir))
        for attr in ('remote_ops','remote_old_ops','remote_control','calibration_mirror','score_projection','evaluation_dir','ledger_seed'):
            setattr(self.args,attr,getattr(x.args,attr))
        # Keep the original descriptor targets intact; the explicit final mirror
        # may share bytes with those retained local provenance targets.
        self.args.remote_ops=str(ops/'inference-final-remote-ops');shutil.copytree(ops,Path(self.args.remote_ops),ignore=shutil.ignore_patterns('inference-final-*'))
        self.args.remote_old_ops=str(ops/'inference-final-remote-old-ops');shutil.copytree(Path(x.args.remote_old_ops),Path(self.args.remote_old_ops))
        self.args.remote_control=str(ops/'inference-final-remote-control')
        self.args.calibration_mirror=str(Path(self.args.remote_ops)/'portable-recording-evidence/calibration')
        Path(self.args.ledger).write_bytes(x.ledger.read_bytes())
        # Reproduce production GPU absolute descriptors; local fixture
        # descriptors originally name the retained canonical temp copy.
        study=Path(self.args.study_dir);validation=x.ops/'inference-validation-attempt1'
        dispatch=package.load(validation/'dispatch.json');dispatch['protocol']['path']=package.REMOTE+'/'+package.PRIMARY+'/'+package.gate.PROTOCOL
        fixtures.put(validation/'dispatch.json',dispatch)
        descriptor={'path':package.REMOTE+'/'+package.OPS_REL+'/inference-validation-attempt1/dispatch.json','sha256':package.sha(validation/'dispatch.json')}
        marker=package.load(study/package.gate.MARKER);marker['dispatch']=descriptor;fixtures.put(study/package.gate.MARKER,marker)
        result=package.load(validation/'result.json');result['dispatch']=descriptor;result['study_dispatch_sha256']=package.sha(study/package.gate.MARKER);fixtures.put(validation/'result.json',result)
        for name in ('dispatch.json','result.json'):(Path(self.args.remote_ops)/'inference-validation-attempt1'/name).write_bytes((validation/name).read_bytes())
        report=package.load(study/'analysis-report.json')
        for key,name in [('native_report_json','report.json'),('native_report_html','report.html')]:report[key]['path']=package.REMOTE+'/'+package.PRIMARY+'/'+name
        fixtures.put(study/'analysis-report.json',report)
        manifest=package.load(x.evaluation/'mirror-manifest.json');manifest['study_files_sha256']=x.k.inventory(study);manifest['study_file_count']=len(manifest['study_files_sha256']);fixtures.put(x.evaluation/'mirror-manifest.json',manifest)
        outcome=package.load(x.evaluation/'outcome.json');outcome['opaque_mirror']['manifest_sha256']=package.sha(x.evaluation/'mirror-manifest.json');fixtures.put(x.evaluation/'outcome.json',outcome)
        patch.object(f,'INSTANCE',package.INSTANCE).start();patch.object(f,'SCOPE',package.SCOPE).start();patch.object(f.old,'FREEZE',package.FREEZE).start()
        amendment=ops/'gpu-budget-amendment-43-20261102.json';patch.object(f.v,'AMENDMENT_SHA',f.sha(amendment)).start()
        old=repo/f.old.OLD_REL;old.mkdir(exist_ok=True)
        exclusion=old/'partial-analysis-exclusion-20261102T2306Z.json';exclusion.write_bytes((ops/'exclusion.json').read_bytes());patch.object(f.old,'EXCLUSION',f.sha(exclusion)).start()
        preservation=old/'blocked-hard-study-attempt1/preservation-receipt.json';preservation.parent.mkdir(parents=True,exist_ok=True)
        preservation.write_bytes((ops/'portable-recording-evidence/preservation-receipt.json').read_bytes());patch.object(f.old,'PRESERVATION',f.sha(preservation)).start()
        def put(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
        put(root/'outcome.json',{'project':f.PROJECT,'instance_id':f.INSTANCE,'rental_scope_sha256':f.SCOPE,'returncode':0,'stop_confirmed':True,'cleanup_confirmed':True,'transport_cleanup_returncode':0})
        transport=ops/'inference-transport-attempt1';attempt=root/'meta-relay-attempt-fixture';attempt.mkdir()
        put(attempt/'transport-ready.json',{'instance_id':f.INSTANCE,'owned_processes':{'relay':{'pid':999991,'start_identity':'fixture'}}})
        put(transport/'relay-pointer.json',{'instance_id':f.INSTANCE,'rental_scope_sha256':f.SCOPE,'attempt_dir':str(attempt)})
        put(transport/'guardian-process.json',{'pid':999992,'start_identity':'fixture'});put(transport/'stop-1.json',{'stopped':True})
        patch.object(f,'process_identity',return_value=None).start()
        state={'project':f.PROJECT,'instance_id':f.INSTANCE,'scope_sha256':f.SCOPE,'running_intervals':[{'start_epoch':1000.,'stop_epoch':1100.}],
            'last_status':{'actual_status':'exited','cur_state':'stopped','intended_status':'stopped'}}
        self.s=Service(repo,root,state)
        self.verifier=lambda args,repo:package._verify_inputs(args,repo,lambda _:None)[4]
    def test_complete_actual_mapped_gate_reaches_readonly_finalizer(self):
        value=f.execute(self.args,self.s,self.verifier)
        self.assertTrue(value['ready']);self.assertEqual(value['final_decisions'],90);self.assertEqual(self.s.gets,0)
        self.assertEqual(len(value['input_verification']['missing_ancillary_metadata']),2)
    def test_changed_included_recording_rejected_by_shared_gate_before_provider(self):
        target=Path(self.args.study_dir)/'incidents/hard-01/requests.jsonl';target.write_bytes(b'altered')
        args=copy.deepcopy(self.args);args.verify_only=False;args.prepare_backup=True
        with self.assertRaises(ValueError):f.execute(args,self.s,self.verifier)
        self.assertEqual(self.s.gets,0);self.assertFalse(Path(args.out).exists())


if __name__=='__main__':unittest.main()
