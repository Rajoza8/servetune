"""Reuse the frozen financial/lifecycle contracts with explicit offline policy."""
from pathlib import Path
from unittest.mock import patch
import test_finalize_inference_rental as original
import finalize_inference_offline_rental as offline


class OfflineFinancialContracts(original.FinalInferenceContracts):
    def setUp(self):
        self.module_patch=patch.object(original,'f',offline);self.module_patch.start();self.addCleanup(self.module_patch.stop)
        super().setUp()
        old=self.root/'outcome.json';value=offline.load(old);value['returncode']=1;self.put(old,value)
        receipt=self.ops/'inference-offline-materialization-attempt1/receipt.json';self.put(receipt,{'opaque_offline_receipt':True})
        source=self.ops/'finalize_inference_offline_rental.py';source.write_text('invented reviewed adapter')
        shared=self.ops/'inference_offline_recovery_gate.py';shared.write_text('invented reviewed offline gate')
        patch.object(offline,'__file__',str(source)).start();patch.object(offline.recovery,'__file__',str(shared)).start()
        verified=self.verify(self.args,self.repo);self.gate_calls=0
        info={'pipeline_outcome':offline.desc(old),'original_failed_pipeline_outcome':offline.desc(old),'offline_recovery_receipt':offline.desc(receipt),'input_verification':verified}
        patch.object(offline.recovery,'verify_recovery',return_value=info).start()
    def test_backup_policy_and_cleanup_explicitly_disclose_unknown_tail(self):
        self.execute('prepare_backup');receipt=offline.load(self.out/'backup-receipt.json')
        self.assertTrue(receipt['all_required_scientific_artifacts_backed_up']);self.assertFalse(receipt['all_remote_artifacts_backed_up']);self.assertTrue(receipt['remote_ops_control_tail_unverified'])
        self.execute('delete');c=offline.load(self.out/'cleanup.json');self.assertEqual(c['original_failed_pipeline_outcome'],offline.desc(self.root/'outcome.json'))
        self.assertEqual(offline.load(self.root/'outcome.json')['returncode'],1);self.assertFalse(c['all_remote_artifacts_backed_up'])


if __name__=='__main__':original.unittest.main()
