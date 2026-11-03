"""Synthetic guardian clocks/files only; no processes/provider/network."""
import contextlib
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import inference_pipeline as p
import inference_vast as v
import argparse
import test_inference_vast as rental_fixtures


class Fake:
    def __init__(self,root):
        self.root=root;self.now=1000.;self.calls=[];self.alive=False;self.outage=False;self.match=False
        self.state={'instance_id':60001001,'scope_sha256':'a'*64,'allocation_deadline_epoch':10000.,'dph_total':1.5,
            'machine_id':135236,'last_status':{'actual_status':'running','ports':{'22/tcp':[{'HostPort':'2222'}]}},'running_intervals':[{'start_epoch':1000.}]}
    def load(self):return copy.deepcopy(self.state)
    def lock(self):return contextlib.nullcontext()
    def birth(self,pid):return 'born' if self.alive else None
    def active(self):return {'actual':True}
    def sleep(self,n):self.now+=n
    def clock(self):return self.now
    def cost(self,state):return {'total_usd_upper':38}
    def reconcile(self):
        self.calls.append('GET')
        if self.outage:raise OSError('invented provider read outage')
        if self.state['instance_id'] is None:
            if not self.match:raise ValueError('unknown CREATE no exact match')
            self.state['instance_id']=60001001
        return self.load()
    def inventory(self):self.calls.append('INVENTORY');return []
    def heartbeat(self,pid,command):self.calls.append('HEARTBEAT')
    def save(self,state):self.state=copy.deepcopy(state)


class GuardianContracts(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name);self.s=Fake(self.root)
    def plan(self):
        folder=self.root/'startup-ssh-window-attempt1';folder.mkdir()
        v.write(folder/'plan.json',{'instance_id':60001001,'rental_scope_sha256':'a'*64,'started_epoch':1000.,'deadline_epoch':1600.},exclusive=True)
    def recover(self,service,*args,**kwargs):
        self.assertGreaterEqual(service.now,1000);service.now=max(service.now,1600.)
        service.calls.append('FULL600_LOG300_DELETE');return {'guide_authenticated':False,'terminal':True}
    def test_dead_owner_during_window_adopts_full600_no_stop(self):
        self.plan()
        with patch.object(p,'recover_window',self.recover),patch.object(p,'stop_and_confirm',side_effect=AssertionError('early STOP')):
            p.watchdog(self.s,42,'born',sleep=self.s.sleep,clock=self.s.clock)
        self.assertIn('FULL600_LOG300_DELETE',self.s.calls);self.assertEqual(self.s.now,1600.)
    def test_provider120_outage_while_owner_alive_cannot_shorten_window(self):
        self.plan();self.s.alive=True;self.s.outage=True
        with patch.object(p,'recover_window',self.recover),patch.object(p,'stop_and_confirm',side_effect=AssertionError('early STOP')):
            p.watchdog(self.s,42,'born',sleep=self.s.sleep,clock=self.s.clock)
        self.assertGreaterEqual(self.s.now,1600.);self.assertEqual(self.s.calls.count('FULL600_LOG300_DELETE'),1)
    def test_budget_deadline_overrides_window(self):
        self.plan();self.s.state['allocation_deadline_epoch']=1000.;stops=[]
        def stop(service,reason,*_):stops.append(reason);return {'stop_confirmed':True}
        with patch.object(p,'recover_window',side_effect=AssertionError('budget first')),patch.object(p,'stop_and_confirm',stop):
            p.watchdog(self.s,42,'born',sleep=self.s.sleep,clock=self.s.clock)
        self.assertEqual(stops,['Fixed3h allocation deadline']);self.assertEqual(self.s.now,1000.)
    def unknown(self,known400=False):
        self.s.state['instance_id']=None;self.s.state['pending_intent']='intent-0001-create.json';self.s.state['allocation_deadline_epoch']=1040.
        v.write(self.root/'intent-0001-create-outcome.json',{'phase':'response' if known400 else 'unknown_outcome','success':False,'http_status':400 if known400 else None},exclusive=True)
    def test_unknown_create_get_matched_only_runs_diagnostics_no_create_retry(self):
        self.unknown();self.s.state['allocation_deadline_epoch']=2000.;self.s.match=True
        with patch.object(p,'recover_window',self.recover):p.reconcile_unknown_create(self.s,self.s.clock,self.s.sleep)
        result=json.loads((self.root/'unknown-create-guardian-outcome.json').read_text())
        self.assertTrue(result['terminal']);self.assertNotIn('CREATE',self.s.calls);self.assertNotIn('STOP',self.s.calls)
    def test_unknown_create_no_match_retains_unknown_not_absent_or_free(self):
        self.unknown();p.reconcile_unknown_create(self.s,self.s.clock,self.s.sleep)
        result=json.loads((self.root/'unknown-create-guardian-outcome.json').read_text())
        self.assertTrue(result['unbound_create_outcome_still_unknown']);self.assertTrue(result['no_resource_absence_or_cost_closure_claimed'])
        self.assertNotIn('create_rejected_confirmed_absent_epoch',self.s.state);self.assertEqual(self.s.now,1040.)
    def test_known400_complete_inventory_absence_freezes_known_nonallocation(self):
        self.unknown(True);p.reconcile_unknown_create(self.s,self.s.clock,self.s.sleep)
        result=json.loads((self.root/'unknown-create-guardian-outcome.json').read_text())
        self.assertTrue(result['known_rejected']);self.assertTrue(result['confirmed_no_scoped_allocation']);self.assertIn('create_rejected_confirmed_absent_epoch',self.s.state)
        self.assertEqual(self.s.calls,['GET','INVENTORY'])
    def test_changed_window_scope_refused_without_any_dispatch(self):
        self.plan();self.s.state['scope_sha256']='b'*64
        with self.assertRaises(ValueError):p.pending_window(self.s,self.s.clock)
        self.assertEqual(self.s.calls,[])
    def test_authenticated_window_is_exempt_from_denial_recovery(self):
        self.plan();v.write(self.root/'startup-ssh-window-attempt1/authenticated.json',{'guide_authenticated':True},exclusive=True)
        self.assertIsNone(p.pending_window(self.s,self.s.clock))


class PipelineFlowContracts(unittest.TestCase):
    def setUp(self):
        self.fx=rental_fixtures.RentalContracts('test_real_null_external_offer_create_ack_and_immediate_attach_preserve_create');self.fx.setUp()
        self.addCleanup(self.fx.doCleanups);x=self.fx
        (x.root/'create-owner.json').unlink();x.root.rmdir();self.s=x.s;self.spawns=[];self.code=0
        original=self.s.api
        def api(method,path,payload=None):
            result=original(method,path,payload)
            if '/asks/' in path:x.rows[:]=[x.row()]
            if payload=={'state':'stopped'}:x.rows[:]=[x.row('exited','stopped','stopped')]
            return result
        self.s.api=api
        self.queue=x.ops/'queue.json';x.put(self.queue,{'project':v.PROJECT,'final':True,'commands':[{'name':'one-fixed-job','argv':['python3','fixed-helper.py'],'timeout_s':60}]})
        self.args=argparse.Namespace(queue=str(self.queue),selection=str(x.selection),prior_receipt=str(x.receipt))
    def spawn(self,argv,**kwargs):
        self.spawns.append(argv);owner=self
        class Child:
            pid=4321
            def wait(self,timeout=None):return owner.code if argv[-1]=='fixed-helper.py' else 0
            def terminate(self):pass
            def send_signal(self,_):pass
            def poll(self):return 0
        return Child()
    def window(self,service):
        fixture=self
        class Window:
            def prepare(self,out):
                out.mkdir();service.reconcile();v.write(out/'plan.json',{'original_clock':True},exclusive=True);return out/'plan.json'
            def resume(self,path):
                guide=path.parent/'guide.stdout';guide.write_bytes(b'Public synthetic guide')
                v.write(path.parent/'authenticated.json',{'guide_authenticated':True},exclusive=True)
                v.write(service.root/'guide-reviewed.json',{'guide_sha256':v.sha(guide)},exclusive=True)
                return guide
        return Window()
    def test_full_create_attach_guide_queue_finish_stop_no_retry(self):
        result=p.execute(self.args,self.s,self.spawn,self.s.clock,lambda n:setattr(self.fx,'now',self.fx.now+n),self.window)
        self.assertEqual(result['returncode'],0);self.assertTrue(result['stop_confirmed']);self.assertTrue(result['cleanup_confirmed'])
        self.assertEqual(len(result['commands']),1);self.assertEqual([a[0] for a in self.fx.calls],['PUT','POST','PUT'])
        self.assertEqual(sum(argv[-1]=='fixed-helper.py' for argv in self.spawns),1)
    def test_failed_fixed_job_stops_and_preserves_nonzero_no_replay(self):
        self.code=7;result=p.execute(self.args,self.s,self.spawn,self.s.clock,lambda n:setattr(self.fx,'now',self.fx.now+n),self.window)
        self.assertEqual(result['returncode'],1);self.assertTrue(result['stop_confirmed']);self.assertEqual(result['commands'][0]['returncode'],7)
        self.assertEqual(sum(argv[-1]=='fixed-helper.py' for argv in self.spawns),1)


if __name__=='__main__':unittest.main()
