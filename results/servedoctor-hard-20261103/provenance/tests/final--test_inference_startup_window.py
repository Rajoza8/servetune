import contextlib
import copy
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import inference_vast as ops
import inference_startup_window as window


class Fake:
    def __init__(self,root):
        self.root=root;self.repo=root.parent;self.scope_path=root/'rental-scope.json'
        ops.write(self.scope_path,{'project':ops.LABEL,'instance_id':60000001},exclusive=True)
        self.state={'project':ops.LABEL,'label':ops.LABEL,'instance_id':60000001,'scope_sha256':ops.sha(self.scope_path),
                    'last_status':{'id':60000001,'actual_status':'running','public_ipaddr':'203.0.113.1',
                                   'ports':{'22/tcp':[{'HostPort':'2222'}]}}}
        self.state['running_intervals']=[{'start_epoch':1000.,'running_seen_epoch':1000.}]
        self.now=1000.;self.events=[];self.confirm=True;self.saves=[]
        ops.write(root/'session.json',self.state,exclusive=True)
        ops.write(root/'active-command.json',{'deadline_epoch':10000.},exclusive=True)
        (self.repo/'runs').mkdir(exist_ok=True);(self.repo/'runs/servedoctor-gpu-hours.md').write_text('safe cost snapshot\n')
    def load(self):return copy.deepcopy(self.state)
    def active(self):return json.loads((self.root/'active-command.json').read_text())
    def clock(self):return self.now
    def sleep(self,t):self.now+=t
    def lock(self):return contextlib.nullcontext()
    def save(self,state):
        self.state=copy.deepcopy(state);self.saves.append(copy.deepcopy(state));ops.write(self.root/'session.json',state)
    def reconcile(self):
        self.events.append(('GET',self.now))
        if self.state.get('pending_intent') and self.confirm:self.state.update(destroyed_epoch=self.now);self.state.pop('pending_intent')
    def intent(self,state,operation,path,reason):
        self.events.append((operation,self.now));assert operation=='delete'
        name='intent-0001-delete.json';value={'project':ops.LABEL,'instance_id':state['instance_id'],
             'rental_scope_sha256':state['scope_sha256'],'operation':'delete','method':'DELETE','path':path}
        ops.write(self.root/name,value,exclusive=True);self.state['pending_intent']=name


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'ops';self.root.mkdir();self.s=Fake(self.root)
        self.calls=[];self.logs=[];self.answer=255;self.fail_run=False;self.fail_logs=False
        self.w=window.Window(self.s,clock=self.s.clock,sleep=self.s.sleep,run=self.fake_run,collect=self.collect)
        self.out=self.root/'startup-ssh-window-attempt1'
    def fake_run(self,argv,stdout,stderr,timeout,env):
        self.calls.append((argv,self.s.now))
        self.assertNotIn('MODEL_API_KEY',env);self.assertNotIn('SSH_AUTH_SOCK',env)
        if self.fail_run:raise OSError('fake')
        if argv[0]=='ssh-keyscan':stdout.write(b'[203.0.113.1]:2222 ssh-ed25519 PUBLIC\n');return types.SimpleNamespace(returncode=0)
        self.assertEqual(argv[-1],'cat /etc/vast-agents-guide.md')
        if self.answer==0:stdout.write(b'Public instance guide\n')
        else:stderr.write(b'Permission denied (publickey).\n')
        return types.SimpleNamespace(returncode=self.answer)
    def collect(self,instance,out,ops):
        self.logs.append(self.s.now)
        if self.fail_logs:raise OSError('fake')
        marker=self.root/f'request-logs-instance-{instance}-dispatch.json'
        if marker.exists():
            prior=json.loads(marker.read_text())
            if prior.get('receipt'):
                return {'resumed_without_put':True,'completed':True,'existing_receipt':prior['receipt']}
            return {'resumed_without_put':True,'completed':False,'failure':{'class':'PriorRequestOutcomeUnknown'}}
        out.mkdir();window.write_new(out/'receipt.json',{'safe':True})
        window.write_new(marker,{'once':True,'receipt':window.descriptor(out/'receipt.json')})
        return {'completed':True}
    def test_denial_waits_full600_logs_at300_and_backups_before_one_delete(self):
        self.assertIsNone(self.w.start(self.out));terminal=json.loads((self.out/'terminal.json').read_text())
        self.assertEqual([x for x,t in self.s.events if x=='delete'],['delete'])
        self.assertEqual(next(t for x,t in self.s.events if x=='delete'),1600.)
        self.assertEqual(self.logs,[1300.]);self.assertGreaterEqual(terminal['elapsed_s'],600)
        self.assertTrue(terminal['confirmed_absent']);self.assertFalse(terminal['guide_authenticated'])
        self.assertTrue(Path(terminal['backup_receipt']['path']).is_file())
        self.assertFalse(any(x=='stop' for x,t in self.s.events))
        interval=self.s.state['running_intervals'][0]
        self.assertEqual(interval['stop_epoch'],self.s.state['destroyed_epoch'])
        self.assertFalse(interval['stop_confirmed']);self.assertTrue(interval['deletion_confirmed'])
        self.assertEqual(len(self.s.saves),1);self.assertEqual(len(list(self.out.glob('deletion-reconciliation-*.json'))),1)
    def test_read_and_log_errors_still_hold_same_full_window(self):
        self.fail_run=True;self.fail_logs=True;self.w.start(self.out)
        self.assertEqual(self.s.now,1600);self.assertEqual(self.logs[0],1300)
        rows=[json.loads(p.read_text()) for p in self.out.glob('probe-*/outcome.json')]
        self.assertTrue(rows);self.assertTrue(all(r['error_class']=='OSError' for r in rows))
    def test_success_returns_guide_with_scope_proof_and_no_delete_logs_or_stop(self):
        self.answer=0;guide=self.w.start(self.out)
        self.assertEqual(guide.read_bytes(),b'Public instance guide\n');self.assertEqual(self.s.events,[])
        proof=json.loads((self.out/'authenticated.json').read_text());self.assertTrue(proof['guide_authenticated'])
        self.assertEqual(proof['guide'],window.descriptor(guide));self.assertEqual(self.logs,[])
        count=len(self.calls);self.assertEqual(self.w.resume(self.out/'plan.json'),guide);self.assertEqual(count,len(self.calls))
    def test_resume_keeps_original_clock_and_never_replays_unknown_delete(self):
        self.s.confirm=False;self.w.start(self.out);count=len(self.calls);self.s.now+=20
        self.w.resume(self.out/'plan.json')
        self.assertEqual(len(self.calls),count);self.assertEqual([x for x,t in self.s.events].count('delete'),1)
        self.assertEqual(json.loads((self.out/'plan.json').read_text())['started_epoch'],1000.)
    def test_existing_logs_dispatch_never_replayed(self):
        window.write_new(self.root/'request-logs-instance-60000001-dispatch.json',{'unknown':True})
        self.w.start(self.out);self.assertTrue(self.logs);self.assertTrue(all(t>=1300 for t in self.logs))
        self.assertIn('existing_dispatch',json.loads((self.out/'logs-outcome.json').read_text()))
    def test_changed_scope_or_clock_plan_blocks_without_actions(self):
        self.answer=0;self.w.start(self.out);path=self.out/'plan.json';value=json.loads(path.read_text());value['started_epoch']-=1
        ops.write(path,value)
        with self.assertRaises(ValueError):self.w.resume(path)
        self.assertEqual(self.s.events,[])
    def plan_only(self):
        return self.w.prepare(self.out)
    def test_prepare_before_child_is_offline_and_start_adopts_original_clock(self):
        path=self.w.prepare(self.out);before=path.read_bytes()
        self.assertEqual(self.calls,[]);self.assertEqual(self.s.events,[]);self.s.now+=42;self.answer=0
        guide=self.w.start(self.out);self.assertTrue(guide.is_file());self.assertEqual(path.read_bytes(),before)
        self.assertEqual(json.loads(before)['deadline_epoch'],1600.)
    def test_incomplete_backup_is_preserved_and_resume_uses_fresh_attempt(self):
        path=self.plan_only();partial=self.out/'failed-startup-backup-attempt0001';partial.mkdir()
        (partial/'partial.raw').write_bytes(b'preserve failure')
        self.s.now=1600;self.w.resume(path)
        self.assertEqual((partial/'partial.raw').read_bytes(),b'preserve failure')
        terminal=json.loads((self.out/'terminal.json').read_text())
        self.assertIn('failed-startup-backup-attempt0002',terminal['backup_receipt']['path'])
        self.assertEqual([x for x,t in self.s.events].count('delete'),1)
    def test_interrupted_partial_json_backup_receipt_is_retained_then_fresh_snapshot(self):
        path=self.plan_only();partial=self.out/'failed-startup-backup-attempt0001';partial.mkdir()
        receipt=partial/'receipt.json';receipt.write_bytes(b'{"project":')
        self.s.now=1600;self.w.resume(path)
        self.assertEqual(receipt.read_bytes(),b'{"project":')
        terminal=json.loads((self.out/'terminal.json').read_text())
        self.assertIn('failed-startup-backup-attempt0002',terminal['backup_receipt']['path'])
        self.assertTrue((self.out/'failed-startup-backup-attempt0001-incomplete-receipt.json').is_file())
    def test_failed_backup_and_ephemeral_tmp_are_retained_without_wedging_resume(self):
        path=self.plan_only();self.s.now=1600
        source=self.root/'ordinary-evidence.log';source.write_bytes(b'retain')
        ephemeral=self.root/'active-command.tmp';ephemeral.write_bytes(b'ephemeral')
        original=Path.read_bytes;failed=[]
        def injected(p):
            if p.resolve()==source.resolve() and not failed:failed.append(True);raise FileNotFoundError('fixture')
            if p.resolve()==ephemeral.resolve():raise AssertionError('Must skip atomic-write temp')
            return original(p)
        with patch.object(Path,'read_bytes',injected):
            with self.assertRaises(FileNotFoundError):self.w.resume(path)
        self.assertEqual([x for x,t in self.s.events].count('delete'),0)
        failure=self.out/'backup-failure-attempt0001.json';self.assertTrue(failure.is_file())
        self.w.resume(path)
        terminal=json.loads((self.out/'terminal.json').read_text())
        backup=json.loads(Path(terminal['backup_receipt']['path']).read_text())
        manifest=json.loads(Path(backup['manifest']['path']).read_text())
        self.assertIn('active-command.tmp',manifest['omitted_ephemeral_tmp'])
        self.assertNotIn('active-command.tmp',manifest['files_sha256'])
        self.assertTrue(failure.is_file());self.assertEqual([x for x,t in self.s.events].count('delete'),1)
    def test_fixed_remote_argv_cannot_be_changed_in_plan(self):
        path=self.plan_only();value=json.loads(path.read_text());value['allowed_remote_argv']=['echo','forbidden']
        ops.write(path,value)
        with self.assertRaises(ValueError):self.w.resume(path)
        self.assertEqual(self.calls,[]);self.assertEqual(self.s.events,[])
    def test_no_probe_after_deadline_and_no_ssh_after_keyscan_exhausts_budget(self):
        path=self.plan_only();_,plan=self.w.load_plan(path);self.s.now=1599
        original=self.fake_run
        def slow(*args,**kwargs):
            result=original(*args,**kwargs);self.s.now+=2;return result
        self.w.run=slow;row=self.w.probe(self.out,plan)
        self.assertEqual([a[0] for a,t in self.calls],['ssh-keyscan'])
        self.assertEqual(row['error_class'],'TimeoutError')
        before=len(self.calls)
        with self.assertRaises(TimeoutError):self.w.probe(self.out,plan)
        self.assertEqual(len(self.calls),before)
    def test_late_auth_is_preserved_for_manual_review_and_never_adopted_or_deleted(self):
        path=self.plan_only();_,plan=self.w.load_plan(path);(self.root/'known_hosts').write_text('public fixture')
        self.s.now=1599;self.answer=0;original=self.fake_run
        def slow(*args,**kwargs):
            result=original(*args,**kwargs);self.s.now+=2;return result
        self.w.run=slow;row=self.w.probe(self.out,plan)
        self.assertFalse(row['guide_authenticated']);self.assertTrue(row['late_authentication_evidence'])
        with self.assertRaises(ValueError):self.w.resume(path)
        self.assertFalse((self.out/'authenticated.json').exists());self.assertTrue((self.out/'authentication-uncertain.json').exists())
        self.assertEqual(self.s.events,[])
    def test_existing_collector_receipt_is_adopted_without_fresh_target(self):
        earlier=self.root/'earlier-container-logs';earlier.mkdir();window.write_new(earlier/'receipt.json',{'safe':True})
        proof=window.descriptor(earlier/'receipt.json')
        window.write_new(self.root/'request-logs-instance-60000001-dispatch.json',{'receipt':proof})
        self.w.start(self.out);row=json.loads((self.out/'logs-outcome.json').read_text())
        self.assertEqual(row['receipt'],proof);self.assertTrue(row['resumed_without_put'])
        self.assertEqual(self.logs,[1300]);self.assertFalse((self.root/'container-logs-60000001-startup-window').exists())
    def test_delete_descriptor_ignores_other_scope_and_later_absence_closes_billing(self):
        window.write_new(self.root/'intent-0000-delete.json',{'instance_id':123,'rental_scope_sha256':'f'*64,'operation':'delete'})
        self.s.confirm=False;self.w.start(self.out);terminal=self.out/'terminal.json';before=terminal.read_bytes()
        value=json.loads(before);self.assertEqual(Path(value['delete_intent']['path']).name,'intent-0001-delete.json')
        self.assertNotIn('stop_epoch',self.s.state['running_intervals'][0]);self.assertFalse(value['confirmed_absent'])
        self.s.confirm=True;self.s.now+=40;self.w.resume(self.out/'plan.json')
        self.assertEqual(terminal.read_bytes(),before);self.assertEqual([x for x,t in self.s.events].count('delete'),1)
        interval=self.s.state['running_intervals'][0]
        self.assertEqual(interval['stop_epoch'],self.s.state['destroyed_epoch']);self.assertFalse(interval['stop_confirmed'])
        self.assertEqual(len(list(self.out.glob('deletion-reconciliation-*.json'))),1)
    def test_full_window_must_fit_phase_before_any_probe(self):
        ops.write(self.root/'active-command.json',{'deadline_epoch':1500})
        with self.assertRaises(ValueError):self.w.start(self.out)
        self.assertFalse(self.out.exists());self.assertEqual(self.calls,[])

if __name__=='__main__':unittest.main()
