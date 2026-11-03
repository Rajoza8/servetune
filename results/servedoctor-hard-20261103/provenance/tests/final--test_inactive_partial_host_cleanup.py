"""Synthetic retained recordings and failed START only; no actual actions."""
import copy
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import inactive_partial_host_cleanup as c
import finalize_partial_rental as f
import test_finalize_partial_rental as fixtures


class Service(fixtures.FakeRental):
    stopped=staticmethod(c.h.Rental.stopped)
    host_cost=staticmethod(c.h.Rental.host_cost)


class InactiveContracts(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.PartialFinalizerContracts('test_default_zero_writes_provider_and_opaque_answers_native_reports');self.fx.setUp()
        self.addCleanup(self.fx.doCleanups);self.addCleanup(patch.stopall)
        x=self.fx;self.repo,self.old,self.ops=x.repo,x.old,x.ops
        shutil.rmtree(x.study);shutil.rmtree(x.eval)
        for folder in (x.remote,x.remote_old,x.control):shutil.rmtree(folder)
        # Pad only synthetic public origin data to the exact real178-file gate.
        count=len(f.inventory_tree(x.original,x.repo))
        for i in range(178-count):(x.original/('synthetic-origin-'+str(i)+'.txt')).write_bytes(b'opaque original evidence')
        blocked=x.preserved.parent
        proof_dirs=('first9-proofs/recording-stage/00-reference','first9-proofs/recording-stage/01-hard','latest/recording-stage/00-hard')
        for name in proof_dirs:
            folder=blocked/name;folder.mkdir(parents=True);x.put(folder/'owned-observer.json',{'finished':True,'issues':[],'owned_leaks':[]})
        listing={'latest/study/'+n:v for n,v in f.inventory_tree(x.original,x.repo).items()}
        listing.update({str(p.relative_to(blocked)):f.sha(p) for p in blocked.rglob('owned-observer.json')})
        x.put(x.preserved,{'files':listing});patch.object(f,'PRESERVED_MANIFEST',f.sha(x.preserved)).start()
        patch.object(c,'SCOPE',f.SCOPE).start()
        canonical=x.repo/'runs/servedoctor-ledger.json';canonical.write_bytes(x.seed.read_bytes())
        response=self.old/'intent-0020-start-outcome.json'
        x.put(response,{'instance_id':c.INSTANCE,'rental_scope_sha256':c.SCOPE,'operation':'start','method':'PUT',
            'path':f'/api/v0/instances/{c.INSTANCE}/','phase':'response','success':False,'safe_error_code':'resources_unavailable'})
        pipeline={'project':c.h.LABEL,'analysis_label':f.LABEL,'instance_id':c.INSTANCE,'rental_scope_sha256':c.SCOPE,'returncode':1,
            'stop_confirmed':True,'cleanup_confirmed':True,'commands':[],'start_request_returncode':1,'finished_epoch':995.,
            'queued_start':{'requested_epoch':901.,'outcome_path':str(response),'outcome_sha256':f.sha(response)}}
        x.put(self.old/c.PIPELINE,pipeline);patch.object(c,'PIPELINE_SHA',f.sha(self.old/c.PIPELINE)).start()
        state={'project':c.h.LABEL,'label':c.h.LABEL,'instance_id':c.INSTANCE,'scope_sha256':c.SCOPE,'created_epoch':100.,'dph_total':1.5,'storage_dph':.08,
            'running_intervals':[{'start_epoch':100.,'running_seen_epoch':110.,'stop_epoch':800.},{'start_epoch':900.,'stop_epoch':990.}],
            'last_status':{'id':c.INSTANCE,'actual_status':'exited','cur_state':'stopped','intended_status':'stopped'}}
        self.s=Service(self.repo,self.old,x.scope,state);self.guard=c.Cleanup(self.s)
    def test_local_gate_zero_provider_writes_and_all178_seals(self):
        before=self.s.state_path.read_bytes();proof=self.guard.gate(self.guard.scope())
        self.assertEqual(proof['original_study_files'],178);self.assertEqual(proof['sealed_payload_files'],112)
        self.assertEqual(self.s.gets,0);self.assertFalse(self.guard.backup.exists());self.assertEqual(self.s.state_path.read_bytes(),before)
    def test_prepare_requires_tail_ack_and_preserves_opaque_originals(self):
        with self.assertRaises(ValueError):self.guard.prepare()
        receipt=self.guard.prepare(True);self.assertFalse(receipt['all_remote_artifacts_backed_up']);self.assertTrue(receipt['remote_ops_control_tail_unverified'])
        self.guard.verify();files=c.load(self.guard.backup/'manifest.json')['files']
        self.assertIn('payload/'+str((self.fx.original/'answers/answer_keys.json').relative_to(self.repo)),files)
        self.assertEqual(self.s.deletes,0);self.assertEqual(self.s.gets,1)
    def test_one_delete_fixed_cost_then_get_only(self):
        self.guard.prepare(True);value=self.guard.delete();self.assertTrue(value['confirmed_absent']);self.assertEqual(self.s.deletes,1)
        before=(self.guard.backup/'destroy-receipt.json').read_bytes();self.guard.reconcile()
        self.assertEqual((self.guard.backup/'destroy-receipt.json').read_bytes(),before)
        with self.assertRaises(ValueError):self.guard.delete()
        self.assertEqual(self.s.deletes,1)
    def test_unknown_delete_preserved_no_replay_then_get_only(self):
        self.guard.prepare(True);self.s.confirm=False;self.assertFalse(self.guard.delete()['confirmed_absent'])
        with self.assertRaises(ValueError):self.guard.delete()
        self.s.confirm=True;self.assertTrue(self.guard.reconcile()['confirmed_absent']);self.assertEqual(self.s.deletes,1)
    def test_interrupted_before_intent_preserves_dispatch_and_blocks_replay(self):
        self.guard.prepare(True);self.s.crash=True
        with self.assertRaises(RuntimeError):self.guard.delete()
        self.assertTrue((self.guard.backup/'delete-dispatch.json').exists())
        with self.assertRaises(ValueError):self.guard.delete()
        self.assertEqual(self.s.deletes,0)
    def test_changed_raw_or_failure_log_refuses_prepare(self):
        (self.fx.original/'incidents/hard-01/requests.jsonl').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.guard.prepare(True)
        self.assertEqual(self.s.deletes,0);self.assertFalse(self.guard.backup.exists())
    def test_h13_ledger_or_actual_partial_study_appearance_refuses(self):
        (self.repo/f.STUDY_REL).mkdir()
        with self.assertRaises(ValueError):self.guard.prepare(True)
        (self.repo/f.STUDY_REL).rmdir();(self.repo/'runs/servedoctor-ledger.json').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.guard.prepare(True)
        self.assertEqual(self.s.deletes,0)
    def test_dispatched_command_or_running_seen_failed_interval_refuses(self):
        value=c.load(self.old/c.PIPELINE);value['commands']=[{'name':'unexpected'}];self.fx.put(self.old/c.PIPELINE,value)
        patch.object(c,'PIPELINE_SHA',f.sha(self.old/c.PIPELINE)).start()
        with self.assertRaises(ValueError):self.guard.prepare(True)
        self.assertEqual(self.s.deletes,0)
    def test_fresh_get_running_state_refuses_delete(self):
        self.guard.prepare(True);original=self.s.reconcile
        def running():original();self.s.state['last_status']['actual_status']='running'
        self.s.reconcile=running
        with self.assertRaises(ValueError):self.guard.delete()
        self.assertEqual(self.s.deletes,0)
    def test_changed_backup_or_repeated_prepare_never_overwrites(self):
        self.guard.prepare(True);before=(self.guard.backup/'backup-receipt.json').read_bytes()
        with self.assertRaises(FileExistsError):self.guard.prepare(True)
        self.assertEqual((self.guard.backup/'backup-receipt.json').read_bytes(),before)
        (self.guard.backup/'canonical-local-ledger.json').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.guard.delete()
        self.assertEqual(self.s.deletes,0)
    def test_private_identity_not_read_and_partial_backup_is_retained(self):
        private=self.old/'ssh_ed25519';private.write_bytes(b'PRIVATE CANARY');read=Path.read_bytes
        def guarded(path):
            if path==private:raise AssertionError('Private key read')
            return read(path)
        with patch.object(Path,'read_bytes',guarded):
            with self.assertRaises(ValueError):self.guard.prepare(True)
        self.assertTrue((self.guard.backup/'backup-failure.json').exists());self.assertEqual(self.s.deletes,0)
    def test_no_full17_backup_gate_or_other_lifecycle_called(self):
        with patch.object(c.h.Rental,'backup',side_effect=AssertionError('unchanged full17 gate')):
            self.guard.prepare(True);self.assertTrue(self.guard.delete()['confirmed_absent'])


if __name__=='__main__':unittest.main()
