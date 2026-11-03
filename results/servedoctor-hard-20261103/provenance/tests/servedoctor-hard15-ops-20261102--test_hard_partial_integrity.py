"""Synthetic opaque16-key lineage,16recordings and15-verdict gates only."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import hard_partial_integrity as p


class PartialContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.addCleanup(patch.stopall)
        self.repo=Path(self.tmp.name).resolve();self.ops=self.repo/'runs/servedoctor-hard15-ops-20261102';self.ops.mkdir(parents=True)
        self.oldops=self.repo/p.OLD_REL;self.oldops.mkdir();self.origin=self.repo/p.ORIGINAL;self.origin.mkdir()
        self.root=self.repo/p.PRIMARY;self.validation=self.ops/'validation-attempt1';self.native_calls=0;self.bad_case=None;self.verdict_count=15
        for name in p.HELPERS:(self.ops/name).write_text('# synthetic helper '+name+'\n')
        for name in ('study.json','scenarios.json','commitment.json'):(self.origin/name).write_bytes(b'opaque unchanged public input')
        answers=self.origin/'answers';answers.mkdir();(answers/'answer_keys.json').write_bytes(b'OPAQUE16ANSWERKEYS: NOT JSON AND NEVER PARSED BY THE ADAPTER')
        freeze=self.origin/'hard-experiment-freeze.json';p.write_new(freeze,{'source_commit':p.SOURCE})
        patch.object(p,'FREEZE_SHA',p.sha(freeze)).start()
        fail=self.origin/'engines/engine-06-hard-16';fail.mkdir(parents=True);(fail/'engine.log').write_bytes(b'known synthetic startup -0.54GiB')
        patch.object(p,'FAILURE_LOG_SHA',p.sha(fail/'engine.log')).start()
        self.public={'engine_config.json','engine_identity.json','events.json','slo.json','telemetry.jsonl','requests.jsonl','recording.json'}
        for name in p.ALL_IDS:
            folder=self.origin/'incidents'/name;folder.mkdir(parents=True)
            for field in self.public:(folder/field).write_bytes(b'opaque complete public fixture')
            p.write_new(folder/'manifest.json',{'files':{field:p.sha(folder/field) for field in self.public}})
            runtime=self.origin/'answers/runtime';runtime.mkdir(exist_ok=True);(runtime/(name+'.json')).write_bytes(b'OPAQUE RUNTIME UNION')
        self.preservation=self.ops/'preservation.json';p.write_new(self.preservation,{'status':'BLOCKED_INCOMPLETE','completed_recordings':16})
        patch.object(p,'PRESERVATION_SHA',p.sha(self.preservation)).start()
        self.authorization=self.ops/'exclusion.json'
        self.auth={'project':p.RENTAL_PROJECT,'analysis_label':p.LABEL,'recorded_at_utc':'2000-01-01T00:00:00+00:00',
            'included_hard_ids':list(p.IDS),'excluded_ids':['hard-16'],'reference_id':'reference','original_source_commit':p.SOURCE,
            'original_freeze_sha256':p.FREEZE_SHA,'hard16_may_be_modified_regenerated_or_rerecorded':False,'before_validation':True,
            'before_any_hard_arm_evaluation':True,'prompts_rules_scoring_answer_keys_unchanged':True,'native_validity_must_not_be_rewritten':True,
            'full_hard_set_claim_permitted':False,'limits':{'gpu_total_usd':40,'meta_ledger_cap_usd':50,'baseten_ledger_cap_usd':20},
            'original_preservation_receipt':p.desc(self.preservation)}
        p.write_new(self.authorization,self.auth);patch.object(p,'EXCLUSION_SHA',p.sha(self.authorization)).start()
        self.frozen={'source_commit':p.SOURCE,'preflight':{'sha256':'f'*64},'job_policy':{'gpu_uuid':'GPU-synthetic'}}
        def no_decisions(root):
            folder=Path(root)/'decisions'
            p.require(not folder.exists() or not any(v.is_file() for v in folder.rglob('*')),'No decisions before validation')
        def audit_recording(root,case,frozen,owned):
            folder=Path(root)/'incidents'/case['id'];manifest=p.load(folder/'manifest.json')['files']
            complete=case['id']!=self.bad_case and set(manifest)==self.public and all(p.sha(folder/name)==h for name,h in manifest.items())
            complete=complete and case['id'] in owned['physical_by_incident']
            return {'id':case['id'],'complete':complete,'manifest_sha256':p.sha(folder/'manifest.json')}
        self.old=types.SimpleNamespace(verify_source_policy=lambda repo,expected_commit:p.SOURCE,verify_freeze=lambda root,repo:copy.deepcopy(self.frozen),
            no_decisions=no_decisions,cases=lambda root:[{'id':'reference'}]+[{'id':f'hard-{i:02d}'} for i in range(1,17)],
            verify_descriptor=p.checked,physical_matches=lambda physical,frozen:physical.get('verified') is True,audit_recording=audit_recording)
        self.real_loader=p.legacy;patch.object(p,'legacy',return_value=self.old).start()
        self.proofs=[]
        sets=[['reference'],[f'hard-{i:02d}' for i in range(1,9)],[f'hard-{i:02d}' for i in range(9,17)]]
        for index,(name,selected) in enumerate(zip(p.OWNED,sets)):
            path=self.oldops/'record-stages'/name;path.parent.mkdir(parents=True)
            observations=path.parent/'observations.jsonl';observations.write_bytes(b'{"synthetic":true}\n')
            ready=path.parent/'ready.json';p.write_new(ready,{'project':p.RENTAL_PROJECT,'source_commit':p.SOURCE,'freeze_sha256':p.FREEZE_SHA,
                'selected_ids':selected,'recorder_pid':100+index,'recorder_start_ticks':'1','selected_incident_directories_absent':True,
                'ready_before_source_job_timers':True,'physical_gpu_binding':{'verified':True}})
            p.write_new(path,{'project':p.RENTAL_PROJECT,'study_dir':p.ORIGINAL,'source_commit':p.SOURCE,'freeze_sha256':p.FREEZE_SHA,
                'preflight_sha256':'f'*64,'finished':True,'owned_leaks':[],'issues':[],'jobs':[],
                'observations':p.desc(observations),'readiness':p.desc(ready),'recorder_pid':100+index,'recorder_start_ticks':'1'})
            self.proofs.append(path)
    def prepare(self):return p.prepare(self.root,self.authorization,self.preservation,self.proofs,self.repo)
    def native(self,argv,cwd,stdout,stderr):
        self.native_calls+=1;self.assertEqual(argv[1:],['-m','servedoctor','validate','--study-dir',p.PRIMARY])
        rows=[{'id':name,'valid':True} for name in p.IDS[:self.verdict_count]]
        p.write_new(self.root/'answers/validity.json',{'total':len(rows),'valid':len(rows),'incidents':rows})
        stdout.write(b'{"synthetic_native":true}\n');return types.SimpleNamespace(returncode=0)
    def validate(self):return p.validate_once(self.root,self.validation,self.repo,run=self.native)
    def test_prepare_preserves_all16_opaque_keys_inputs_freeze_and_original(self):
        before=p.inventory(self.origin);value=self.prepare();self.assertTrue(value['prepared']);self.assertEqual(value['label'],p.LABEL)
        self.assertEqual(p.inventory(self.origin),before)
        for name in p.INPUTS:self.assertEqual((self.root/name).read_bytes(),(self.origin/name).read_bytes())
        self.assertFalse((self.root/'incidents/hard-16').exists());self.assertEqual(len(list((self.root/'incidents').iterdir())),16)
        with self.assertRaises(ValueError):self.prepare()
    def test_audit_keeps_original_observer_proofs_and_only_excludes16(self):
        self.prepare();quality=p.audit(self.root,self.repo)
        self.assertTrue(quality['complete']);self.assertEqual(len(quality['recordings']),16)
        self.assertEqual(quality['owned_observer_proofs'],[p.desc(v) for v in self.proofs])
        self.bad_case='hard-15'
        with self.assertRaises(ValueError):p.audit(self.root,self.repo)
    def test_native_once15_then_immutable_eval_gate(self):
        self.prepare();value=self.validate();self.assertTrue(value['completed']);self.assertEqual(value['total'],15);self.assertEqual(self.native_calls,1)
        proof=p.verify_evaluation(self.root,self.validation,self.repo);self.assertEqual(proof['total'],15);self.assertEqual(proof['label'],p.LABEL)
        with self.assertRaises(ValueError):p.validate_once(self.root,self.ops/'validation-attempt2',self.repo,run=self.native)
        self.assertEqual(self.native_calls,1)
    def test_bad_native_count_stays_recorded_and_cannot_be_revalidated(self):
        self.prepare();self.verdict_count=14;value=self.validate();self.assertFalse(value['completed']);self.assertTrue((self.root/p.MARKER).exists())
        with self.assertRaises(ValueError):p.verify_evaluation(self.root,self.validation,self.repo)
        with self.assertRaises(ValueError):p.validate_once(self.root,self.ops/'validation-attempt2',self.repo,run=self.native)
        self.assertEqual(self.native_calls,1)
    def test_case16_included_or_label_changed_blocks(self):
        self.prepare();(self.root/'incidents/hard-16').mkdir()
        with self.assertRaises(ValueError):p.verify_freeze(self.root,self.repo)
        (self.root/'incidents/hard-16').rmdir();(self.root/'analysis-label.txt').write_text('full Hard')
        with self.assertRaises(ValueError):p.verify_freeze(self.root,self.repo)
    def test_copy_or_original_key_change_blocks_without_parsing_values(self):
        self.prepare();(self.root/'answers/answer_keys.json').write_bytes(b'changed opaque keys')
        with self.assertRaises(ValueError):p.verify_freeze(self.root,self.repo)
    def test_original_changed_or_helper_changed_blocks(self):
        self.prepare();(self.ops/'measure_contexts.py').write_bytes(b'changed helper')
        with self.assertRaises(ValueError):p.verify_freeze(self.root,self.repo)
    def test_nested_owned_readiness_or_observations_mutation_blocks_after_validation(self):
        self.prepare();self.assertTrue(self.validate()['completed'])
        (self.proofs[-1].parent/'observations.jsonl').write_bytes(b'changed observations')
        with self.assertRaises(ValueError):p.verify_evaluation(self.root,self.validation,self.repo)
    def test_decisions_before_validation_or_earlier_auth_mismatch_block(self):
        self.prepare();folder=self.root/'decisions/rules';folder.mkdir(parents=True);(folder/'hard-01.json').write_bytes(b'not permitted yet')
        with self.assertRaises(ValueError):self.validate()
        self.assertEqual(self.native_calls,0)
    def test_exclusion_semantics_hold_even_when_fixture_hash_is_approved(self):
        self.auth['before_validation']=False;self.authorization.write_text(json.dumps(self.auth));patch.object(p,'EXCLUSION_SHA',p.sha(self.authorization)).start()
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.root.exists())
    def test_no_weakening_original_global_observer_failures(self):
        value=p.load(self.proofs[-1]);value['issues']=['not clean'];self.proofs[-1].write_text(json.dumps(value))
        self.prepare()
        with self.assertRaises(ValueError):p.audit(self.root,self.repo)
    def test_tampered_original_core_rejected_before_import(self):
        (self.oldops/'hard_integrity.py').write_bytes(b'raise AssertionError("must not import")')
        with patch.object(p,'legacy',self.real_loader):
            with self.assertRaises(ValueError):p.legacy(self.repo)


if __name__=='__main__':unittest.main()
