"""Fake old/new rearm lineage and fake process/transport only."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_rearm_calibrated_remote_guard as shared
import test_rearm_frozen_remote_guard as frozen_tests
import rearm_frozen_remote_guard as previous
import rearm_partial_remote_guard as r


class RemoteContracts(shared.RemoteContracts):
    def setUp(self):
        patch.object(shared,'r',r).start();self.addCleanup(patch.stopall);super().setUp()


class PartialRearmContracts(unittest.TestCase):
    def setUp(self):
        self.fixture=frozen_tests.FrozenLineageContracts('test_pinned_old_rearm_receipt_becomes_new_guard_ancestor_after_restart')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups);self.addCleanup(patch.stopall)
        f=self.fixture;self.ops=f.ops
        copied=self.ops/'rearm_frozen_remote_guard.py';copied.write_bytes(Path(previous.__file__).read_bytes())
        patch.object(previous,'__file__',str(copied)).start()
        first=f.execute('rearm-frozen-attempt1');self.assertTrue(first['completed'])
        second=f.execute('rearm-frozen-attempt2',self.ops/'rearm-frozen-attempt1/receipt.json');self.assertTrue(second['completed'])
        self.ancestor=self.ops/'rearm-frozen-attempt2/receipt.json';patch.object(r,'ANCESTOR_HELPER_SHA',r.digest(copied)).start();patch.object(r,'ANCESTOR_RECEIPT_SHA',r.digest(self.ancestor)).start()
        patch.object(r,'SCOPE_SHA',f.scope_sha).start()
        f.state['running_intervals'][-1]['stop_epoch']=f.now-100
        stopped=copy.deepcopy(f.state);stopped['last_status'].update(actual_status='exited',cur_state='stopped',intended_status='stopped')
        self.stopped=self.ops/'partial-analysis-stopped-state.json';r.write_new(self.stopped,stopped);patch.object(r,'STOPPED_STATE_SHA',r.digest(self.stopped)).start()
        f.state['running_intervals'].append({'start_epoch':f.now-50,'running_seen_epoch':f.now-40})
        event={'project':r.PROJECT,'instance_id':r.INSTANCE,'rental_scope_sha256':f.scope_sha,'operation':'start','method':'PUT',
            'path':f'/api/v0/instances/{r.INSTANCE}/','requested_epoch':f.now-49,'payload_sha256':hashlib.sha256(json.dumps({'state':'running'},sort_keys=True).encode()).hexdigest()}
        intent=self.ops/'intent-0200-start.json';r.write_new(intent,event);r.write_new(intent.with_name(intent.stem+'-outcome.json'),{**event,'phase':'response','success':True})
        r.write_new(intent.with_name(intent.stem+'-reconciled.json'),{'operation':'start','confirmed_epoch':f.now-39,'status':{'id':r.INSTANCE,'label':r.PROJECT,'actual_status':'running','cur_state':'running'}})
        source=self.ops/'remote_guard_partial.py';source.write_bytes(b'# invented new partial guard\n');patch.object(r,'INITIAL_GUARD_SHA',r.digest(source)).start()
        f.calls=[]
    def execute(self,name='rearm-partial-attempt1',prior=None):
        f=self.fixture
        return r.execute(self.ops/name,rental_proof=f.proof,prior_receipt=prior or self.ancestor,after_restart=prior is None,
            stopped_state_proof=self.stopped if prior is None else None,service=f.service,run=f.fake_run,clock=lambda:f.now,
            token=lambda:type('Token',(),{'hex':'c'*32})())
    def test_exact_prior_frozen2_then_own_successful_receipt_lineage(self):
        result=self.execute();self.assertTrue(result['completed']);self.assertEqual(result['prior']['proof'],r.descriptor(self.ancestor))
        self.assertEqual(result['helper_sha256'],r.digest(r.__file__));self.assertTrue(self.execute('rearm-partial-attempt2',self.ops/'rearm-partial-attempt1/receipt.json')['completed'])
    def test_changed_old_frozen_source_or_prior_receipt_blocks_staging(self):
        source=self.ops/'rearm_frozen_remote_guard.py';raw=source.read_bytes();source.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.execute()
        source.write_bytes(raw);self.ancestor.write_bytes(self.ancestor.read_bytes()+b' ')
        with self.assertRaises(ValueError):self.execute()
        self.assertEqual(self.fixture.calls,[])
    def test_new_stopped_prefix_and_start_ack_are_mandatory(self):
        path=self.ops/'intent-0200-start-outcome.json';v=json.loads(path.read_text());v['success']=False;path.write_text(json.dumps(v))
        with self.assertRaises(ValueError):self.execute()
        self.assertEqual(self.fixture.calls,[])


if __name__=='__main__':unittest.main()
