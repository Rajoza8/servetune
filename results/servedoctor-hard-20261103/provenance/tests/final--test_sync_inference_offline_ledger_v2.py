"""Same exact inherited ledger-byte contracts with the v2 cleanup source pin."""
from unittest.mock import patch
import test_sync_inference_offline_ledger as previous
import sync_inference_offline_ledger_v2 as sync


class OfflineV2SyncContracts(previous.OfflineSyncContracts):
    def setUp(self):
        module=patch.object(previous,'offline',sync);module.start();self.addCleanup(module.stop)
        super().setUp()


if __name__=='__main__':previous.original.unittest.main()
