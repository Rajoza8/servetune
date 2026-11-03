"""Reuse inherited financial byte-sync contracts; old failed parent stays failed."""
from unittest.mock import patch
import test_sync_inference_ledger as original
import sync_inference_offline_ledger as offline


class OfflineSyncContracts(original.SyncContracts):
    def setUp(self):
        self.module_patch=patch.object(original,'s',offline);self.module_patch.start();self.addCleanup(self.module_patch.stop)
        super().setUp()
        value=offline.load(self.p['parent']);value['returncode']=1;value['failure']={'class':'ValueError'};self.put(self.p['parent'],value)
        receipt=self.ops/'inference-offline-materialization-attempt1/receipt.json';self.put(receipt,{'known-science-only':True})
        info={'pipeline_outcome':offline.desc(self.p['parent']),'original_failed_pipeline_outcome':offline.desc(self.p['parent']),'offline_recovery_receipt':offline.desc(receipt)}
        patch.object(offline.recovery,'verify_recovery',return_value=info).start()
        c=offline.load(self.p['cleanup']);c.update(all_required_scientific_artifacts_backed_up=True,all_remote_artifacts_backed_up=False,
            remote_ops_control_tail_unverified=True,original_failed_pipeline_outcome=info['original_failed_pipeline_outcome'],offline_recovery_receipt=info['offline_recovery_receipt']);self.put(self.p['cleanup'],c)
    def test_incomplete_parent_or_unconfirmed_delete_blocks(self):
        value=offline.load(self.p['parent']);value['returncode']=2;self.put(self.p['parent'],value)
        with self.assertRaises(ValueError):self.execute(True)
        self.assertFalse(self.p['out'].exists());self.assertEqual(offline.sha(self.p['canonical']),offline.SEED)
    def test_offline_sync_retains_failed_parent_and_honest_policy(self):
        before=self.p['parent'].read_bytes();result=self.execute(True)
        self.assertEqual(self.p['parent'].read_bytes(),before);self.assertEqual(offline.load(self.p['parent'])['returncode'],1)
        self.assertTrue(result['all_required_scientific_artifacts_backed_up']);self.assertFalse(result['all_remote_artifacts_backed_up']);self.assertTrue(result['remote_ops_control_tail_unverified'])
    def test_false_full_remote_backup_claim_blocks(self):
        c=offline.load(self.p['cleanup']);c['all_remote_artifacts_backed_up']=True;self.put(self.p['cleanup'],c)
        with self.assertRaises(ValueError):self.execute(True)
        self.assertEqual(offline.sha(self.p['canonical']),offline.SEED)


if __name__=='__main__':original.unittest.main()
