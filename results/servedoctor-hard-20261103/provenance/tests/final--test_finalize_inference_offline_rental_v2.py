"""Same offline financial contracts with the exact three-path verifier adapter."""
from unittest.mock import patch
import test_finalize_inference_offline_rental as previous
import finalize_inference_offline_rental_v2 as finalizer


class OfflineV2FinancialContracts(previous.OfflineFinancialContracts):
    def setUp(self):
        module=patch.object(previous,'offline',finalizer);module.start();self.addCleanup(module.stop)
        super().setUp()
        (self.ops/'inference_descriptor_adapter.py').write_text('synthetic adapter backup source')
        (self.ops/'package_inference_results.py').write_text('synthetic frozen scanner backup source')
    def test_v2_pins_three_path_adapter_and_backs_up_both_verifiers(self):
        self.assertEqual(finalizer.PACKAGE_SHA,'fdaf66af25327c4501c8e66b2fa56708600d4c4acc8b5585a32724d3b5f0ae91')
        self.execute('prepare_backup');receipt=finalizer.load(self.out/'backup-receipt.json');files=finalizer.load(receipt['evidence_manifest']['path'])['files']
        self.assertIn(str((self.ops/'inference_descriptor_adapter.py').relative_to(self.repo)),files)
        self.assertIn(str((self.ops/'package_inference_results.py').relative_to(self.repo)),files)


if __name__=='__main__':previous.original.unittest.main()
