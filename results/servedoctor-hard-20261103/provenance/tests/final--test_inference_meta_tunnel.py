"""Invented relay state only; no network, credential, GPU or provider actions."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import inference_meta_tunnel as t


class RelayContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.control=self.root/'control';self.control.mkdir()
        self.ops=self.root/'ops';self.ops.mkdir();self.out=self.ops/'inference-transport-attempt1'
        self.old=self.root/'old';self.old.mkdir()
        for n in ('meta_tunnel.py','meta_connect_relay.py'):(self.old/n).write_text('invented relay source')
        self.state={'project':t.v.PROJECT,'instance_id':60000001,'scope_sha256':'a'*64,
            'allocation_deadline_epoch':2000,'last_status':{'id':60000001,'actual_status':'running','cur_state':'running',
                'public_ipaddr':'127.0.0.1','ports':{'22/tcp':[{'HostPort':'23456'}]}}}
        self.binding={'project':t.v.PROJECT,'instance_id':60000001,'rental_scope_sha256':'a'*64,
            'budget_amendment':{'sha256':t.v.AMENDMENT_SHA}}
        self.put(self.control/'binding.json',self.binding);self.put(self.control/'rental-scope.json',{})
        self.put(self.control/'active-command.json',{'pid':123,'birth':'invented birth'})
        self.service=SimpleNamespace(load=lambda:self.state,active=lambda:None)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for name,value in [('OPS',self.ops),('CONTROL',self.control),('OUT',self.out),('OLD',self.old),
                           ('BASE_SHA',t.v.sha(self.old/'meta_tunnel.py')),('RELAY_SHA',t.v.sha(self.old/'meta_connect_relay.py'))]:
            self.stack.enter_context(patch.object(t,name,value))
        self.stack.enter_context(patch.object(t,'service',return_value=self.service))
        self.stack.enter_context(patch.object(t.os,'getppid',return_value=123))
        self.fake=SimpleNamespace(MINIMAL_ENV={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},
            identity=Mock(return_value={'pid':456,'pgid':456,'start_identity':'birth'}),
            cleanup=Mock(return_value=[{'already_exited':True}]),terminate_owned=Mock(return_value={'exited':True}),
            cleanup_spawned_child=Mock(),attempt_dir=lambda p:Path(p))
        def start(*args,**kwargs):
            q=self.control/'meta-relay-attempt-invented';q.mkdir()
            self.put(q/'api-transport.json',{'project':'servedoctor','instance_id':60000001})
            self.put(q/'transport-ready.json',{'instance_id':60000001,'owned_processes':{'relay':{'pid':456}}})
            return {'attempt_dir':str(q)}
        def probe(q):self.put(q/'transport-channel-proof.json',{'verified':True});return {'verified':True}
        self.fake.start=Mock(side_effect=start);self.fake.probe=Mock(side_effect=probe)
        self.stack.enter_context(patch.object(t,'base_module',return_value=self.fake))
        self.spawn=self.stack.enter_context(patch.object(t.subprocess,'Popen',return_value=SimpleNamespace(pid=456)))

    def put(self,path,value):path.write_text(json.dumps(value)+'\n')
    def test_start_copies_verified_trio_and_never_inherits_key_environment(self):
        r=t.start();self.assertTrue(r['ready']);self.assertEqual(r['paid_calls'],0)
        self.assertEqual(self.spawn.call_args.kwargs['env'],self.fake.MINIMAL_ENV)
        self.assertIs(self.spawn.call_args.kwargs['stdin'],t.subprocess.DEVNULL)
        self.assertTrue(self.spawn.call_args.kwargs['start_new_session'])
        self.assertEqual(set(r['files_sha256']),{'api-transport.json','api-transport-receipt.json','api-transport-channel-proof.json'})
    def test_probe_failure_retained_and_owned_transport_cleaned(self):
        self.fake.probe.side_effect=RuntimeError('invented failure')
        with self.assertRaises(RuntimeError):t.start()
        self.assertTrue((self.out/'failure.json').is_file());self.fake.cleanup.assert_called_once();self.spawn.assert_not_called()
    def test_second_start_never_replays_original_attempt(self):
        t.start()
        with self.assertRaises(ValueError):t.start()
        self.fake.start.assert_called_once()
    def test_scope_requires_current_running_instance(self):
        self.state['last_status']['actual_status']='exited'
        with self.assertRaises(ValueError):t.start()
        self.fake.start.assert_not_called();self.assertFalse(self.out.exists())
    def test_pending_mutation_blocks_transport(self):
        self.state['pending_intent']='invented.json'
        with self.assertRaises(ValueError):t.scope()
    def test_binding_different_from_state_blocks_transport(self):
        self.binding['instance_id']=60000002;self.put(self.control/'binding.json',self.binding)
        with self.assertRaises(ValueError):t.bound_instance(self.control)
    def test_existing_changed_core_not_used(self):
        (self.control/'meta_tunnel.py').write_text('wrong bytes')
        with self.assertRaises(ValueError):t.start()
        self.assertTrue((self.out/'failure.json').is_file());self.fake.start.assert_not_called()
    def test_unidentified_guardian_is_reaped_and_start_failure_retained(self):
        self.fake.identity.return_value=None
        with self.assertRaises(RuntimeError):t.start()
        self.assertTrue((self.out/'failure.json').exists());self.assertTrue(self.fake.cleanup_spawned_child.called)
    def test_stop_before_start_is_read_only(self):
        self.assertEqual(t.stop(),{'stopped':True,'never_started':True});self.assertFalse(self.out.exists())
    def test_stop_does_not_hide_owned_cleanup_errors(self):
        t.start();self.fake.cleanup.return_value=[{'error_class':'OwnershipMismatch'}]
        self.assertFalse(t.stop()['stopped'])
    def test_dead_owner_guardian_closes_transport(self):
        t.start();self.fake.identity.return_value=None
        with patch.object(t,'stop',return_value={'stopped':True}) as close:
            t.guardian();close.assert_called_once_with(include_guardian=False)
    def test_deadline_guardian_closes_transport(self):
        t.start()
        with patch.object(t.time,'time',return_value=3000),patch.object(t,'stop',return_value={'stopped':True}) as close:
            t.guardian();close.assert_called_once_with(include_guardian=False)


if __name__=='__main__':unittest.main()
