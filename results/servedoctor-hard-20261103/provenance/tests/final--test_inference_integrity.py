"""Invented opaque studies/proofs only. No real data, answers, models or network."""
import copy
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import inference_integrity as k
import test_package_partial_results as f

class PortableTests(unittest.TestCase):
    def setUp(self):
        self.fixture=f.PackageFixture();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        x=self.fixture;self.repo=x.repo;self.root=x.study;self.ops=x.partial;self.e=self.ops/k.EVIDENCE
        self.e.mkdir();self.original=self.repo/k.p.ORIGINAL;shutil.copytree(x.original,self.original)
        shutil.rmtree(self.root)
        # Retain source4b policy as an injected fake repo identity only; every
        # infrastructure acceptance function below remains the actual frozen68.
        self.addCleanup(patch.stopall)
        patch.object(k,'verify_source_policy',lambda *a,**kw:x.head).start();patch.object(k,'SOURCE',x.head).start()
        actual_core=Path(k.p.legacy.__file__);(x.ops/'hard_integrity.py').write_bytes(actual_core.read_bytes())
        frozen=k.load(self.original/k.p.legacy.FREEZE)
        cal=self.e/'calibration/runs/sd-hard-calibration-attempt1/calibration.json';f.put(cal,{'status':'completed','capacity_rps':6})
        raw=k.p.REMOTE+'/runs/sd-hard-calibration-attempt1/calibration.json'
        frozen['calibration']={'path':raw,'sha256':k.sha(cal)}
        frozen['preflight']={'path':k.p.REMOTE+'/'+k.p.OLD_OPS_REL+'/'+k.MISSING[0][0],'sha256':k.MISSING[0][1]}
        frozen['calibration_provenance']={'calibration':frozen['calibration'],'declaration':{
           'path':k.p.REMOTE+'/'+k.p.OLD_OPS_REL+'/'+k.MISSING[1][0],'sha256':k.MISSING[1][1]},'calibration_files_sha256':{'calibration.json':k.sha(cal)}}
        f.put(self.original/k.p.legacy.FREEZE,frozen);self.frozen=frozen
        patch.object(k.p,'FREEZE',k.sha(self.original/k.p.legacy.FREEZE)).start()
        saved={'latest/study/'+n:h for n,h in k.inventory(self.original).items()}
        self.assertEqual(len(saved),178)
        physical={**f.fixtures.physical(frozen),'instance_id':k.p.INSTANCE}
        selected=[['reference'],list(k.p.IDS[:8]),[*k.p.IDS[8:],'hard-16']]
        prefixes=['first9-proofs/recording-stage/00-reference','first9-proofs/recording-stage/01-hard','latest/recording-stage/00-hard']
        for index,(relative,ids) in enumerate(zip(prefixes,selected)):
            folder=self.e/relative;folder.mkdir(parents=True)
            remote=k.p.REMOTE+'/'+k.p.OLD_OPS_REL+'/record-stages/'+k.p.gate.OWNED[index].rsplit('/',1)[0]
            f.put(folder/'observer-ready.json',{'project':k.p.RENTAL_PROJECT,'source_commit':x.head,'freeze_sha256':k.p.FREEZE,
                'selected_ids':ids,'recorder_pid':100+index,'recorder_start_ticks':111+index,'selected_incident_directories_absent':True,
                'ready_before_source_job_timers':True,'physical_gpu_binding':physical})
            (folder/'owned-observer.observations.jsonl').write_text('{"safe":true}\n')
            f.put(folder/'owned-observer.json',{'project':k.p.RENTAL_PROJECT,'source_commit':x.head,'study_dir':k.p.ORIGINAL,
                'freeze_sha256':k.p.FREEZE,'preflight_sha256':k.MISSING[0][1],'finished':True,'owned_leaks':[],'issues':[],
                'jobs':[],'recorder_pid':100+index,'recorder_start_ticks':111+index,
                'readiness':{'path':remote+'/observer-ready.json','sha256':k.sha(folder/'observer-ready.json')},
                'observations':{'path':remote+'/owned-observer.observations.jsonl','sha256':k.sha(folder/'owned-observer.observations.jsonl')}})
            for name in ('record-identity.json','observer-identity.json'):f.put(folder/name,{'uid':0,'cwd':k.p.REMOTE,'fd_soft':65536,'fd_hard':1048576})
            f.put(folder/'phase-exit.json',{'completed':index!=2,'failure_class':'CalledProcessError' if index==2 else None})
            for q in folder.iterdir():saved[q.relative_to(self.e).as_posix()]=k.sha(q)
        f.put(self.e/'preserved-files-manifest.json',{'files':saved});patch.object(k,'PRESERVED',k.sha(self.e/'preserved-files-manifest.json')).start()
        (self.e/'preservation-receipt.json').write_bytes(x.preservation.read_bytes())
        historical={'recording_ready':True,'source_commit':x.head,'gpu_uuid':k.p.GPU,'readiness_sha256':k.MISSING[0][1],'job_proofs':13}
        f.put(self.e/'declare-readiness.stdout',historical);patch.object(k,'DECLARED',k.sha(self.e/'declare-readiness.stdout')).start()
        export={}
        for name in ('intent.json','response.json'):
            q=self.e/'stopped-preflight-recovery-attempt1'/name;f.put(q,{'safe':name});export[name]=k.desc(q)
        f.put(self.e/'original-portable-closure-audit.json',{'failed_stopped_export':export});patch.object(k,'CLOSURE',k.sha(self.e/'original-portable-closure-audit.json')).start()
        why=k.load(x.exclusion);why['original_freeze_sha256']=k.p.FREEZE;f.put(self.ops/'exclusion.json',why)
        for name,val in [('EXCLUSION_SHA',k.sha(self.ops/'exclusion.json')),('SOURCE',x.head),('FREEZE_SHA',k.p.FREEZE),('PRESERVATION_SHA',k.p.PRESERVATION)]:patch.object(k.p.gate,name,val).start()
        for name in k.HELPERS:(self.ops/name).write_text('# invented helper '+name+'\n')
        root=self.ops/'inference-rental-attempt1';root.mkdir()
        f.put(self.ops/'gpu-budget-amendment-43-20261102.json',{'cap':43});patch.object(k,'AMEND',k.sha(self.ops/'gpu-budget-amendment-43-20261102.json')).start()
        scope={'project':'servedoctor-hard15-inference-20261103','instance_id':70000001};f.put(root/'rental-scope.json',scope)
        f.put(root/'binding.json',{**scope,'purpose':'inference-only','recording_instance_id':k.p.INSTANCE,'rental_scope_sha256':k.sha(root/'rental-scope.json'),'budget_amendment':{'sha256':k.AMEND}})
        f.put(self.ops/'inference-hardware.json',{**scope,'rental_scope_sha256':k.sha(root/'rental-scope.json'),'container_id_matches_scope':True,
           'source_commit':x.head,'model_revision':k.p.legacy.REV,'dtype':'bf16','vllm_version':frozen['job_policy']['vllm_version'],'gpu_uuid':'GPU-new-inference'})
        tunnel=self.ops/'inference-transport-attempt1';tunnel.mkdir()
        f.put(tunnel/k.TRANSPORT[0],{'project':'servedoctor','instance_id':scope['instance_id'],'meta_https_connect_proxy':'http://127.0.0.1:18443'})
        f.put(tunnel/k.TRANSPORT[1],{'project':'servedoctor','instance_id':scope['instance_id'],'source_commit':x.head,
           'transport_config_sha256':k.sha(tunnel/k.TRANSPORT[0]),'origin':'local_mac','allowed_target':'api.meta.ai:443',
           'tls_end_to_end':True,'keys_visible_to_relay':False,'evidence_sha256':{'scope':k.sha(root/'rental-scope.json')}})
        f.put(tunnel/k.TRANSPORT[2],{'project':'servedoctor','instance_id':scope['instance_id'],'source_commit':x.head,
           'transport_config_sha256':k.sha(tunnel/k.TRANSPORT[0]),'transport_ready_sha256':k.sha(tunnel/k.TRANSPORT[1]),
           'origin':'local_mac','method':'GET','url':'https://api.meta.ai/v1/models','http_status':401,'tls_verified':True,
           'authenticated':False,'authorization_sent':False,'body_read':False,'through_configured_transport':True,'verified':True})
    def test_prepare_maps_original_proofs_without_rewriting_them(self):
        before=k.inventory(self.e);result=k.prepare(self.root,self.repo)
        self.assertTrue(result['prepared']);self.assertEqual(k.inventory(self.e),before)
        value=k.load(self.root/k.PROTOCOL);self.assertFalse(value['portable_recording_gate']['old_full_verify_freeze_claimed'])
        self.assertEqual(len(value['portable_recording_gate']['missing_ancillary_metadata']),2)
        self.assertEqual(value['recording_gpu_uuid'],k.p.GPU)
    def test_structural_truncation_rejected_before_copy(self):
        q=self.original/'incidents/hard-01/telemetry.jsonl';q.write_text('{}\n')
        with self.assertRaises(ValueError):k.prepare(self.root,self.repo)
        self.assertFalse(self.root.exists())
    def test_altered_owned_observation_hash_rejected(self):
        q=self.e/'first9-proofs/recording-stage/00-reference/owned-observer.observations.jsonl';q.write_text('{}\n')
        with self.assertRaises(ValueError):k.prepare(self.root,self.repo)
    def test_foreign_new_inference_scope_rejected(self):
        q=self.ops/'inference-rental-attempt1/binding.json';v=k.load(q);v['recording_instance_id']=99;f.put(q,v)
        with self.assertRaises(ValueError):k.prepare(self.root,self.repo)
    def test_old_original_metadata_unchanged_after_prepare(self):
        before=k.inventory(self.original);k.prepare(self.root,self.repo);self.assertEqual(k.inventory(self.original),before)
        q=self.root/'answers/answer_keys.json';q.write_text('{}')
        with self.assertRaises(ValueError):k.verify_freeze(self.root,self.repo)
    def test_native_validate_once_with_exact_fifteen_verdicts(self):
        k.prepare(self.root,self.repo);out=self.ops/'inference-validation-attempt1';calls=[]
        def run(argv,**kwargs):
            calls.append(argv);f.put(self.root/'answers/validity.json',{'total':15,'valid':15,'incidents':[{'id':n,'valid':True} for n in k.p.IDS]});return SimpleNamespace(returncode=0)
        result=k.validate_once(self.root,out,self.repo,run)
        self.assertTrue(result['completed']);self.assertEqual(len(calls),1)
        self.assertTrue(k.verify_evaluation(self.root,out,self.repo)['evaluation_ready'])
        with self.assertRaises(ValueError):k.validate_once(self.root,out,self.repo,run)
        self.assertEqual(len(calls),1)
    def test_failed_validate_preserved_and_not_replayed(self):
        k.prepare(self.root,self.repo);out=self.ops/'inference-validation-attempt1'
        result=k.validate_once(self.root,out,self.repo,lambda *a,**kw:SimpleNamespace(returncode=1))
        self.assertFalse(result['completed']);self.assertEqual(result['failure'],'ValueError');self.assertTrue((self.root/k.MARKER).exists())
        with self.assertRaises(ValueError):k.validate_once(self.root,out,self.repo,lambda *a,**kw:self.fail('replay'))
    def test_post_validation_helper_change_blocks_eval(self):
        k.prepare(self.root,self.repo);(self.ops/'inference_report_common.py').write_text('# changed')
        with self.assertRaises(ValueError):k.verify_freeze(self.root,self.repo)
    def test_transport_rebinding_archives_only_analysis_bytes(self):
        origin=self.repo/'invented-original-transport';root=self.repo/'invented-analysis-transport';origin.mkdir();root.mkdir()
        for name in k.TRANSPORT:
            (origin/name).write_text('opaque old transport '+name);(root/name).write_bytes((origin/name).read_bytes())
        before=k.inventory(origin);selected=k.install_analysis_transport(root,origin,self.repo)
        self.assertEqual(k.inventory(origin),before)
        for name in k.TRANSPORT:
            self.assertEqual(k.sha(root/k.ARCHIVED_TRANSPORT/name),before[name]);self.assertNotEqual(k.sha(root/name),before[name])
        self.assertEqual(selected['original_files_sha256'],before)
    def test_new_transport_foreign_instance_blocks_before_copy(self):
        path=self.ops/'inference-transport-attempt1'/k.TRANSPORT[0];value=k.load(path);value['instance_id']=1;f.put(path,value)
        with self.assertRaises(ValueError):k.prepare(self.root,self.repo)
        self.assertFalse(self.root.exists())
if __name__=='__main__':unittest.main()
