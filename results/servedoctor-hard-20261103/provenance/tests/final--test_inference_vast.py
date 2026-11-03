"""All provider/process/key material invented; no actual operations."""
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import inference_vast as v


class RentalContracts(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.addCleanup(patch.stopall)
        self.repo=Path(self.t.name).resolve();self.ops=self.repo/'runs/servedoctor-hard15-ops-20261102';self.ops.mkdir(parents=True);self.root=self.ops/'inference-rental-attempt1';self.root.mkdir()
        self.now=1000.;self.calls=[];self.rows=[];self.unknown=False
        self.s=v.Rental(self.root,self.repo,self.api,lambda:self.rows,clock=lambda:self.now,birth=lambda _:'born')
        def put(path,obj):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj))
        self.put=put
        amendment=self.ops/'gpu-budget-amendment-43-20261102.json';put(amendment,{'new_total_gpu_cap_usd':43,'previous_total_gpu_cap_usd':40,'api_caps_unchanged':{'meta':50,'baseten':20},'scientific_freeze_unchanged':True});patch.object(v,'AMENDMENT_SHA',v.sha(amendment)).start()
        v0=self.ops/'v0-final.json';put(v0,{'fixed':True});patch.object(v.old,'PRIOR_PATH',v0).start();patch.object(v.old,'PRIOR_SHA',v.sha(v0)).start()
        prior=[]
        for i in range(4):
            p=self.ops/f'prior{i}.json';put(p,{'instance_id':100+i,'confirmed_absent':True,'host_cost':{'compute_usd_upper':.1,'disk_usd_upper':.01}});prior.append({'instance_id':100+i,'receipt':v.desc(p)})
        old_state={'instance_id':58866756,'scope_sha256':v.OLD_SCOPE,'created_epoch':100.,'destroyed_epoch':900.,'dph_total':1.5,'storage_dph':.08,
            'prior_hard_hosts':prior,'running_intervals':[{'start_epoch':100.,'stop_epoch':800.}],
            'last_status':{'actual_status':'exited','cur_state':'stopped','intended_status':'stopped'}}
        final=self.ops/'old-final-state.json';put(final,old_state);cost=v.old.Rental.host_cost(old_state,900.)
        total=v.old.PRIOR_USD+v.old.NETWORK+v.old.SLACK+.44+cost['compute_usd_upper']+cost['disk_usd_upper']
        self.receipt=self.ops/'old-destroy.json';put(self.receipt,{'project':v.old.LABEL,'instance_id':58866756,'rental_scope_sha256':v.OLD_SCOPE,'confirmed_absent':True,
            'destroyed_epoch':900.,'final_state':v.desc(final),'host_cost':cost,'gpu_accounting':{'total_usd_upper':total}});patch.object(v,'PRIOR_RECEIPT_SHA',v.sha(self.receipt)).start()
        (self.repo/'runs/servedoctor-gpu-hours.md').write_text('Prior all-five accounting\n')
        public=self.repo/'runs/vast-preflight-20261029/ssh_ed25519.pub';public.parent.mkdir();public.write_text('ssh-ed25519 AAAAC3NzaFAKE fixture')
        self.offer={'id':54078995,'machine_id':135236,'verification':'verified','num_gpus':1,'gpu_name':'RTX PRO 6000 WS','gpu_ram':97887,'disk_space':1000,
            'cpu_ram':100000,'reliability':.995,'cuda_max_good':13.,'rentable':True,'rented':False,'external':None,'is_bid':False,
            'geolocation':'Massachusetts, US','dph_total':1.4704667,'storage_total_cost':.02,'inet_down_cost':.003,'inet_up_cost':.004}
        self.selection=self.ops/'inference-offer-selection-attempt1.json';self.quote()
        put(self.root/'create-owner.json',{'project':v.PROJECT,'pid':42,'birth':'born','at_epoch':self.now})
    def quote(self):self.put(self.selection,{'project':v.PROJECT,'helper_sha256':v.sha(v.__file__),'at_utc':datetime.fromtimestamp(self.now,timezone.utc).isoformat(),'selected_offer':self.offer})
    def api(self,method,path,payload=None):
        self.calls.append((method,path,payload))
        if self.unknown:raise TimeoutError('invented')
        if '/asks/' in path:return {'success':True,'http_status':200,'new_contract':60001001}
        return {'success':True,'http_status':200}
    def create(self):return self.s.create(self.selection,self.receipt)
    def row(self,actual='running',cur='running',intended='running'):
        return {'id':60001001,'label':v.LABEL,'machine_id':135236,'actual_status':actual,'cur_state':cur,'intended_status':intended,'image_uuid':v.IMAGE,
            'public_ipaddr':'203.0.113.1','ports':{'22/tcp':[{'HostPort':'2222'}]}}
    def test_real_null_external_offer_create_ack_and_immediate_attach_preserve_create(self):
        self.create();state=self.s.load();pending=state['pending_intent'];binding=json.loads(self.s.binding_path.read_text())
        self.assertEqual(binding['instance_id'],60001001);self.assertEqual(v.sha(binding['create_ack']['path']),binding['create_ack']['sha256'])
        self.s.attach_early();self.assertEqual(self.s.load()['pending_intent'],pending)
        self.assertEqual([x[0] for x in self.calls],['PUT','POST'])
        with self.assertRaises(ValueError):self.s.attach_early()
        self.assertEqual(len(self.calls),2)
    def test_three_hour_clock_and_prior_five_costs_once(self):
        self.create();state=self.s.load();deadline=state['allocation_deadline_epoch'];self.assertEqual(deadline,11800.)
        base=self.s.cost(state)['prior_v0_and_five_hard_hosts_usd_upper'];self.assertEqual(base,json.loads((self.root/'prior-accounting.json').read_text())['total_usd_upper'])
        self.now+=60;self.s.heartbeat(42,'actual fake child');self.assertEqual(self.s.load()['allocation_deadline_epoch'],deadline)
    def test_stale_create_stopped_row_does_not_close_billing_then_running_seen(self):
        self.create();self.rows=[self.row('exited','stopped','running')];self.now+=15;self.s.reconcile()
        state=self.s.load();self.assertIn('pending_intent',state);self.assertNotIn('stop_epoch',state['running_intervals'][0])
        self.rows=[self.row()];self.s.reconcile();state=self.s.load();self.assertNotIn('pending_intent',state);self.assertIn('running_seen_epoch',state['running_intervals'][0])
    def test_unknown_create_retained_no_automatic_retry_then_exact_get_reconcile(self):
        self.unknown=True;result=self.create();self.assertEqual(result['phase'],'unknown_outcome');self.assertEqual(len(self.calls),1)
        with self.assertRaises(ValueError):self.create()
        self.rows=[self.row()];self.s.reconcile();self.assertEqual(self.s.load()['instance_id'],60001001);self.assertEqual(len(self.calls),1)
        self.assertFalse(self.s.binding_path.exists())
    def test_unknown_create_no_match_never_claims_absence_or_free_cost(self):
        self.unknown=True;self.create();self.now+=10
        with self.assertRaises(ValueError):self.s.reconcile()
        self.assertGreater(self.s.cost(self.s.load())['inference_host_cost']['compute_usd_upper'],0)
        self.assertNotIn('destroyed_epoch',self.s.load())
    def test_no_repeated_create_and_no_old_instance_rebind(self):
        self.create()
        with self.assertRaises(ValueError):self.create()
        with self.assertRaises(ValueError):self.s.bind(self.s.load(),58866756)
        self.assertEqual(len(self.calls),1)
    def test_fresh_rate_reliability_forecast_and_helper_quote_before_mutation(self):
        self.offer['reliability']=.98;self.quote()
        with self.assertRaises(ValueError):self.create()
        self.assertEqual(self.calls,[])
    def test_reviewed_texas_quote1_553_within1_65_keeps43_cap_and3h_clock(self):
        self.offer.update(id=46205793,machine_id=130011,geolocation='Texas, US',dph_total=1.5531777778)
        self.quote();self.create();state=self.s.load()
        self.assertEqual(v.MAX_RATE,1.65);self.assertEqual(state['dph_total'],1.5531777778)
        self.assertEqual(state['allocation_deadline_epoch']-state['allocation_started_epoch'],10800.)
        self.assertLess(self.s.forecast(state)['forecast_usd_upper']+self.s.forecast(state)['shutdown_margin_usd'],43)
    def test_stale_quote_refused_before_any_api(self):
        self.now+=11
        with self.assertRaises(ValueError):self.create()
        self.assertEqual(self.calls,[])
    def test_wrong_budget_or_prior_receipt_blocks(self):
        self.receipt.write_text('{}')
        with self.assertRaises(ValueError):self.create()
        self.assertEqual(self.calls,[])
    def test_fixed_deadline_and43_forecast_cannot_extend(self):
        self.create();self.now=11800
        with self.assertRaises(ValueError):self.s.forecast(self.s.load())
        state=self.s.load();state['allocation_deadline_epoch']+=1;self.s.save(state)
        with self.assertRaises(ValueError):self.s.load()
    def test_stop_cancels_pending_create_once_get_only_until_confirmed(self):
        self.create();self.s.stop();calls=len(self.calls)
        with self.assertRaises(ValueError):self.s.stop()
        self.assertEqual(len(self.calls),calls)
        self.rows=[self.row('exited','stopped','stopped')];self.s.reconcile();self.assertTrue(self.s.stop()['already_stopped'])
    def test_scoped_image_and_machine_identity_rechecked(self):
        self.create();bad=self.row();bad['image_uuid']='other-image';self.rows=[bad]
        with self.assertRaises(ValueError):self.s.reconcile()
        self.assertEqual(len(self.calls),1)


if __name__=='__main__':unittest.main()
