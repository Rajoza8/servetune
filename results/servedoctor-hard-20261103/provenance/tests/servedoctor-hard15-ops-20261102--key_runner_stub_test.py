"""Invented credentials, fake processes/transports; no real env key or network."""
import ast
import hashlib
import io
import json
from pathlib import Path
import shlex
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import urllib.error

import key_runner as runner
sys.path.insert(0,str(runner.ROOT.parent.parent))

FAKE_KEY = b'offline-ASCII-credential-for-fixtures-only'


def evaluation(**updates):
    values = {'--study-dir':'runs/sd-hard-partial-attempt1','--split':'hard','--arms':'spark,wonder'}
    values.update(updates)
    return ['evaluate', *[item for pair in values.items() for item in pair]]


class HardRunnerContracts(unittest.TestCase):
    def scope_fixture(self, **updates):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        scope = {'project':runner.RENTAL_PROJECT,'label':runner.RENTAL_PROJECT,'instance_id':60000001,
                 'machine_id':18114,'offer_id':58349612,'image':'offline-pinned-image-fixture',
                 'prior_baseline':{'path':'offline-baseline.json','sha256':'0'*64,'usd_upper':25.9}}
        scope.update(updates)
        raw = json.dumps(scope).encode()
        checksum = hashlib.sha256(raw).hexdigest()
        (root/'rental-scope.json').write_bytes(raw)
        state = {**scope,'scope_sha256':checksum,'last_status':{'id':scope['instance_id'],
            'actual_status':'running','cur_state':'running','public_ipaddr':'203.0.113.10','ports':{'22/tcp':[{'HostPort':'40222'}]}}}
        (root/'session.json').write_text(json.dumps(state))
        return root, scope, checksum

    def test_only_hard_commands_and_frozen_values_are_accepted(self):
        self.assertEqual(runner.validate(evaluation()), evaluation())
        local = evaluation(**{'--arms':'glimmer,glimmer_to_spark,glimmer_to_wonder', '--model-revision':runner.REV})
        self.assertEqual(runner.validate(local+['--start-glimmer']), local+['--start-glimmer'])
        self.assertEqual(runner.validate(['diagnose-models']), ['diagnose-models'])
        for root in ('runs/sd-hard','runs/sd-hard-infra-attempt2','runs/sd-hard-ssh-loss-attempt12'):
            with self.assertRaises(ValueError):runner.validate(evaluation(**{'--study-dir':root}))
        for update in ({'--study-dir':'runs/sd-study-r2-api2'}, {'--split':'test'}, {'--split':'dev'},
                       {'--study-dir':'runs/sd-hard/../other'}, {'--arms':'spark,spark'},
                       {'--arms':'spark,'}, {'--glimmer':'baseten'}, {'--model-revision':'0'*40},
                       {'--ledger':'other-ledger.json'}, {'--glimmer-url':'https://example.invalid/v1'}):
            with self.subTest(update=update), self.assertRaises(ValueError):runner.validate(evaluation(**update))
        with self.assertRaises(ValueError):runner.validate(evaluation()+['--arms','rules'])

    def test_optional_hard_live_ids_out_paths_and_revision_are_bound(self):
        command=['live','--study-dir','runs/sd-hard-partial-attempt1','--id','hard-15','--arm','glimmer_to_spark',
                 '--model-revision',runner.REV,'--out','runs/sd-hard-partial-attempt1/live/hard-15-glimmer_to_spark-attempt1']
        self.assertEqual(runner.validate(command),command)
        for old,new in [('hard-15','hard-16'),('hard-15','inc-16'),
                        ('runs/sd-hard-partial-attempt1/live/hard-15-glimmer_to_spark-attempt1','runs/sd-hard-partial-attempt1/live/hard-15-rules-attempt1')]:
            changed=[new if item==old else item for item in command]
            with self.assertRaises(ValueError):runner.validate(changed)

    def test_new_scope_is_dynamic_but_retired_ids_and_mismatches_are_rejected(self):
        root,scope,checksum=self.scope_fixture()
        self.assertEqual(runner.read_scope(root)[1],scope)
        with self.assertRaises(runner.StartupError):runner.read_scope(root,expected_sha='0'*64)
        state=json.loads((root/'session.json').read_text());state['machine_id']=9
        (root/'session.json').write_text(json.dumps(state))
        with self.assertRaises(ValueError):runner.read_scope(root)
        for update in ({'instance_id':58716527},{'instance_id':58690026},{'project':'servedoctor'},
                       {'instance_id':'60000001'}):
            bad,_,_=self.scope_fixture(**update)
            with self.assertRaises(ValueError):runner.read_scope(bad)
        self.assertIn(runner.ROOT_ID,runner.SOCKET.name)
        self.assertTrue(runner.SOCKET.name.startswith('sd-hard15-'))

    def test_stopped_identity_can_start_server_but_no_dispatch_connection(self):
        root,scope,checksum=self.scope_fixture();state=json.loads((root/'session.json').read_text())
        state['last_status'].update(actual_status='exited',cur_state='stopped',intended_status='stopped',ports=None)
        state['running_intervals']=[{'start_epoch':1,'stop_epoch':2}];(root/'session.json').write_text(json.dumps(state))
        self.assertEqual(runner.read_scope(root,require_connection=False)[2],checksum)
        with self.assertRaises(runner.StartupError):runner.read_scope(root)
        with patch.object(runner,'RENTAL_ROOT',root),patch.object(runner,'source_policy',return_value='4'*40),patch.object(runner,'_ssh') as ssh:
            with self.assertRaises(runner.StartupError):runner.execute(evaluation(),FAKE_KEY,expected_sha=checksum)
        ssh.assert_not_called()
    def test_stopped_server_identity_rejects_pending_or_open_interval(self):
        for field,value in [('pending_intent','intent-pending.json'),('running_intervals',[{'start_epoch':1}])]:
            root,_,_=self.scope_fixture();state=json.loads((root/'session.json').read_text())
            state['last_status'].update(actual_status='stopped',cur_state='stopped',intended_status='stopped',ports=None)
            state['running_intervals']=[{'start_epoch':1,'stop_epoch':2}];state[field]=value
            (root/'session.json').write_text(json.dumps(state))
            with self.assertRaises(runner.StartupError):runner.read_scope(root,require_connection=False)
    def test_bad_credentials_have_static_diagnostics_and_no_dispatch(self):
        for value in ('',None,'bad key','bad\nkey','bad\x00key','invented-ñ-key','x'*16384):
            with self.subTest(kind=type(value).__name__), self.assertRaises(runner.StartupError) as caught:
                runner.credential({'MODEL_API_KEY':value})
            if isinstance(value,str) and value:self.assertNotIn(value,str(caught.exception))
        self.assertEqual(runner.credential({'MODEL_API_KEY':FAKE_KEY.decode()}),FAKE_KEY)

    def test_paid_deadline_blocks_dispatch_and_catalog_remains_read_only(self):
        runner.check_paid_deadline(evaluation(),now=runner.PAID_DEADLINE-1)
        with self.assertRaises(runner.StartupError):runner.check_paid_deadline(evaluation(),now=runner.PAID_DEADLINE)
        runner.check_paid_deadline(['diagnose-models'],now=runner.PAID_DEADLINE+100)
        with patch.object(runner.time,'time',return_value=runner.PAID_DEADLINE),patch.object(runner,'_ssh') as ssh:
            with self.assertRaises(runner.StartupError):runner.execute(evaluation(),FAKE_KEY)
            ssh.assert_not_called()

    def test_stale_protocol_or_loaded_source_is_rejected_before_execute(self):
        payload=runner.request_payload(evaluation())
        with patch.object(runner,'execute',return_value={'returncode':0}) as execute:
            runner.handle_request(payload,FAKE_KEY,'scope-sha')
            execute.assert_called_once_with(evaluation(),FAKE_KEY,expected_sha='scope-sha')
            execute.reset_mock()
            for bad in ([*evaluation()],{**payload,'source_sha256':'0'*64},{**payload,'protocol':'old-v0'},
                        {**payload,'url':'https://example.invalid'}):
                with self.assertRaises(ValueError):runner.handle_request(bad,FAKE_KEY,'scope-sha')
            execute.assert_not_called()

    def test_disconnected_submit_client_does_not_retry_or_expose_output(self):
        connection=Mock();connection.sendall.side_effect=BrokenPipeError()
        with patch('builtins.print') as output:
            self.assertFalse(runner.send_response(connection,{'returncode':1,'output':'invented private output'}))
        connection.sendall.assert_called_once()
        self.assertNotIn('invented private output',str(output.call_args))

    def test_ssh_uses_fixed_host_code_stdin_secret_and_cross_chunk_redaction(self):
        root,scope,checksum=self.scope_fixture()
        class Sink(io.BytesIO):
            def close(self):pass
        class Process:
            def __init__(self):
                self.stdin=Sink();self.stdout=io.BytesIO(b'x'*65530+FAKE_KEY+b'end');self.terminated=False
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def wait(self):return 0
            def terminate(self):self.terminated=True
        process=Process()
        with patch.object(runner,'ROOT',root),patch.object(runner,'RENTAL_ROOT',root),patch.object(runner.subprocess,'Popen',return_value=process) as popen:
            result=runner._ssh(evaluation(),FAKE_KEY,expected_sha=checksum)
        args,kwargs=popen.call_args
        command=args[0]
        self.assertEqual(command[command.index('-i')+1],str(root.parent.parent/'runs/vast-preflight-20261029/ssh_ed25519'))
        self.assertNotIn(FAKE_KEY.decode(),json.dumps(command))
        self.assertEqual(process.stdin.getvalue(),b'null\n'+FAKE_KEY+b'\n')
        self.assertNotIn(FAKE_KEY.decode(),result['output'])
        self.assertIn('[REDACTED]',result['output'])
        self.assertNotIn('MODEL_API_KEY',kwargs['env'])
        remote=shlex.split(command[-1]);self.assertEqual(remote[:2],['/venv/main/bin/python','-c'])
        self.assertEqual(remote[3],str(scope['instance_id']))
        self.assertIn('StrictHostKeyChecking=yes',command)
        self.assertNotIn('IdentityAgent=none',command)
        self.assertIn('UserKnownHostsFile="'+str(root/'known_hosts')+'"',command)

    def test_fixed_remote_payloads_compile_and_never_initialize_the_ledger(self):
        for source in (runner.REMOTE_CODE,runner.REMOTE_CHILD,runner.REMOTE_DIAGNOSTIC):compile(source,'fixed-remote','exec')
        self.assertIn("resource.setrlimit(resource.RLIMIT_NOFILE,(65536,hard))",runner.REMOTE_BOOTSTRAP)
        self.assertIn('signal.setitimer',runner.REMOTE_CHILD)
        self.assertIn('class PaidDeadlineReached(BaseException)',runner.REMOTE_CHILD)
        self.assertNotIn('ledger-init',runner.REMOTE_CODE)
        self.assertNotIn('.initialize(',runner.REMOTE_CODE)
        identity=next(node for node in ast.parse(runner.REMOTE_BOOTSTRAP).body if isinstance(node,ast.FunctionDef) and node.name=='identity')
        self.assertNotIn('environ',[node.value for node in ast.walk(identity) if isinstance(node,ast.Constant)])

    def test_catalog_redirect_is_rejected_without_another_request(self):
        namespace={};exec(runner.DIAGNOSTIC_CORE,namespace)
        handler=namespace['DiagnosticNoRedirect']()
        with self.assertRaises(namespace['DiagnosticRedirectBlocked']):
            handler.redirect_request(None,None,302,'redirect',{},'https://example.invalid/other')

    def test_all_fixed_secret_channel_code_uses_the_new_root_and_no_old_socket(self):
        self.assertIn('/workspace/servedoctor-hard/servetune',runner.REMOTE_CODE)
        self.assertNotIn('/workspace/servedoctor-session/servetune',runner.REMOTE_CODE)
        self.assertEqual(runner.SOURCE,'d3fe20a07ce9c687e75956200b655c5913021d49')
        self.assertEqual(runner.PAID_DEADLINE,1793768399)
        self.assertLess(len(str(runner.SOCKET).encode()),104)

    def test_engine_limit_proof_reads_only_fake_owned_process_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);proc=root/'proc';folder=proc/'321';folder.mkdir(parents=True)
            repo=root/'repo';repo.mkdir();(folder/'cwd').symlink_to(repo)
            fields=['S','123','321','321']+['0']*15+['456']
            (folder/'stat').write_text('321 (python) '+' '.join(fields))
            (folder/'status').write_text('Uid:\t0\t0\t0\t0\n')
            (folder/'limits').write_text('Max open files 65536 1048576 files\n')
            (folder/'cmdline').write_bytes(b'/venv/main/bin/vllm\0serve\0--served-model-name\0servetune-glimmer\0')
            definition=next(n for n in ast.parse(runner.REMOTE_BOOTSTRAP).body if isinstance(n,ast.FunctionDef) and n.name=='identity')
            namespace={'Path':lambda value:proc if value=='/proc' else Path(value),'REMOTE':str(repo.resolve()),'SOURCE':runner.SOURCE,'hashlib':hashlib}
            classes=[n for n in ast.parse(runner.REMOTE_BOOTSTRAP).body if isinstance(n,ast.ClassDef)]
            exec(compile(ast.Module(body=[*classes,definition],type_ignores=[]),'fake-process-proof','exec'),namespace)
            proof=namespace['identity'](321,123)
            self.assertEqual(proof['role'],'engine');self.assertEqual(proof['fd_soft'],65536)
            self.assertNotIn('argv',proof)
            (folder/'limits').write_text('Max open files 1024 1048576 files\n')
            with self.assertRaises(namespace['DescriptorLimitError']):namespace['identity'](321,123)

    def test_evaluation_dispatch_requires_private_validation_proof_before_work(self):
        definition=next(n for n in ast.parse(runner.REMOTE_BOOTSTRAP).body if isinstance(n,ast.FunctionDef) and n.name=='validation_gate')
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td).resolve();root=repo/'runs/sd-hard-partial-attempt1';root.mkdir(parents=True)
            out=repo/'runs/servedoctor-hard15-ops-20261102/validation-attempt1';out.mkdir(parents=True)
            marker=root/'hard-partial-validation-dispatch.json'
            marker.write_text(json.dumps({'dispatch':{'path':str(out/'dispatch.json'),'sha256':'0'*64}}))
            verified=Mock(return_value={'evaluation_ready':True,'total':15,'project':runner.PROJECT,'label':runner.LABEL})
            frozen=Mock(return_value={'source_commit':'1'*40})
            module=types.SimpleNamespace(verify_evaluation=verified,verify_freeze=frozen)
            namespace={'Path':Path,'REMOTE':str(repo),'json':json,'sys':types.SimpleNamespace(path=[])}
            classes=[n for n in ast.parse(runner.REMOTE_BOOTSTRAP).body if isinstance(n,ast.ClassDef)]
            exec(compile(ast.Module(body=[*classes,definition],type_ignores=[]),'fake-validation-gate','exec'),namespace)
            with patch.dict(sys.modules,{'hard_partial_integrity':module}):
                result=namespace['validation_gate'](evaluation())
                self.assertTrue(result['evaluation_ready'])
                self.assertEqual(result['source_commit'],'1'*40)
                verified.assert_called_once_with(root,out)
                verified.reset_mock()
                marker.write_text(json.dumps({'dispatch':{'path':str(repo/'outside/dispatch.json')}}))
                with self.assertRaises(namespace['ValidationBindingError']):namespace['validation_gate'](evaluation())
                verified.assert_not_called()
                self.assertIsNone(namespace['validation_gate'](['diagnose-models']))

    def test_source_policy_follows_only_verified_config_descendants_without_reload(self):
        allowed=Mock(side_effect=[runner.SOURCE,'1'*40])
        with patch.dict(sys.modules,{'hard_partial_integrity':types.SimpleNamespace(verify_source_policy=allowed)}):
            self.assertEqual(runner.source_policy(),runner.SOURCE)
            self.assertEqual(runner.source_policy(),'1'*40)
        self.assertEqual(allowed.call_args.kwargs,{'repo':runner.ROOT.parent.parent,'baseline':runner.SOURCE})
        self.assertEqual(runner.SOURCE,'d3fe20a07ce9c687e75956200b655c5913021d49')

    def transport_fixture(self):
        container,scope,checksum=self.scope_fixture()
        ops=container/'runs/servedoctor-hard-ops-20261102';ops.mkdir(parents=True)
        for name in ('session.json','rental-scope.json'):
            (ops/name).write_bytes((container/name).read_bytes())
        study=container/'runs/sd-hard-partial-attempt1';study.mkdir()
        config={'project':'servedoctor','instance_id':scope['instance_id'],
                'meta_https_connect_proxy':'http://127.0.0.1:18443'}
        (study/'api-transport.json').write_text(json.dumps(config))
        checksum_config=hashlib.sha256((study/'api-transport.json').read_bytes()).hexdigest()
        ready={'project':'servedoctor','instance_id':scope['instance_id'],'source_commit':runner.SOURCE,
               'origin':'local_mac','allowed_target':'api.meta.ai:443','tls_end_to_end':True,
               'keys_visible_to_relay':False,'payload_logging':False,'key_environment_inherited':False,
               'transport_config_sha256':checksum_config,'remote_loopback_port':18443,
               'evidence_sha256':{'runs/servedoctor-hard-ops-20261102/rental-scope.json':checksum}}
        (study/'api-transport-receipt.json').write_text(json.dumps(ready))
        report={'method':'GET','url':'https://api.meta.ai/v1/models','authenticated':False,
                'authorization_sent':False,'body_read':False,'through_configured_transport':True,
                'proxy_url':config['meta_https_connect_proxy'],'http_status':401,'tls_verified':True,'verified':True}
        channel={'project':'servedoctor','instance_id':scope['instance_id'],'origin':'local_mac',
                 'source_commit':runner.SOURCE,'transport_config_sha256':checksum_config,
                 'transport_ready_sha256':hashlib.sha256((study/'api-transport-receipt.json').read_bytes()).hexdigest(),
                 **report,'verification':report}
        (study/'api-transport-channel-proof.json').write_text(json.dumps(channel))
        return ops,study,scope,checksum

    def test_transport_trio_binds_scope_config_source_and_fixed_get_tls(self):
        ops,study,scope,checksum=self.transport_fixture()
        with patch.object(runner,'ROOT',ops),patch.object(runner,'RENTAL_ROOT',ops):
            binding=runner.transport_binding(evaluation(),checksum,runner.SOURCE)
            self.assertEqual(binding['scope_sha256'],checksum)
            self.assertEqual(binding['config_sha256'],hashlib.sha256((study/'api-transport.json').read_bytes()).hexdigest())
            self.assertIsNone(runner.transport_binding(evaluation(**{'--arms':'rules,glimmer'}),checksum,runner.SOURCE))
        self.assertNotIn(FAKE_KEY.decode(),json.dumps(binding))
        self.assertNotIn('--api-transport-config',runner.validate(evaluation()))

    def test_transport_missing_stale_scope_unauthenticated_or_tls_proof_rejected(self):
        for field,value in [('authenticated',True),('tls_verified',False),('http_status',200),
                            ('through_configured_transport',False),('source_commit','1'*40)]:
            ops,study,scope,checksum=self.transport_fixture()
            path=study/'api-transport-channel-proof.json';proof=json.loads(path.read_text())
            proof[field]=value;path.write_text(json.dumps(proof))
            with patch.object(runner,'ROOT',ops),patch.object(runner,'RENTAL_ROOT',ops),self.assertRaises(runner.StartupError):
                runner.transport_binding(evaluation(),checksum,runner.SOURCE)
        ops,study,scope,checksum=self.transport_fixture()
        path=study/'api-transport-receipt.json';ready=json.loads(path.read_text())
        ready['evidence_sha256']['runs/servedoctor-hard-ops-20261102/rental-scope.json']='0'*64
        path.write_text(json.dumps(ready))
        with patch.object(runner,'ROOT',ops),patch.object(runner,'RENTAL_ROOT',ops),self.assertRaises(runner.StartupError):
            runner.transport_binding(evaluation(),checksum,runner.SOURCE)
        (study/'api-transport-channel-proof.json').unlink()
        with patch.object(runner,'ROOT',ops),patch.object(runner,'RENTAL_ROOT',ops),self.assertRaises(runner.StartupError):
            runner.transport_binding(evaluation(),checksum,runner.SOURCE)

    def test_remote_transport_hashes_verified_before_credential_is_read(self):
        ops,study,scope,checksum=self.transport_fixture()
        with patch.object(runner,'ROOT',ops),patch.object(runner,'RENTAL_ROOT',ops):binding=runner.transport_binding(evaluation(),checksum,runner.SOURCE)
        node=next(n for n in ast.parse(runner.REMOTE_BOOTSTRAP).body if isinstance(n,ast.FunctionDef) and n.name=='transport_gate')
        classes=[n for n in ast.parse(runner.REMOTE_BOOTSTRAP).body if isinstance(n,ast.ClassDef)]
        stream=io.BytesIO(json.dumps(binding).encode()+b'\n'+FAKE_KEY+b'\n')
        namespace={'Path':Path,'REMOTE':str(ops.parent.parent),'json':json,'hashlib':hashlib,
                   're':__import__('re'),'sys':types.SimpleNamespace(stdin=types.SimpleNamespace(buffer=stream))}
        exec(compile(ast.Module(body=[*classes,node],type_ignores=[]),'fake-remote-transport','exec'),namespace)
        self.assertEqual(namespace['transport_gate'](evaluation(),str(scope['instance_id']),runner.SOURCE),binding)
        self.assertEqual(stream.readline(),FAKE_KEY+b'\n')
        (study/'api-transport.json').write_text('{}')
        stream.seek(0)
        with self.assertRaises(namespace['TransportBindingError']):
            namespace['transport_gate'](evaluation(),str(scope['instance_id']),runner.SOURCE)
        self.assertEqual(stream.readline(),FAKE_KEY+b'\n')

    def test_execute_keeps_public_argv_unchanged_and_sends_only_hash_binding(self):
        ops,study,scope,checksum=self.transport_fixture()
        with patch.object(runner,'ROOT',ops),patch.object(runner,'RENTAL_ROOT',ops),patch.object(runner,'source_policy',return_value=runner.SOURCE), \
             patch.object(runner,'_ssh',return_value={'returncode':0,'output':''}) as ssh:
            runner.execute(evaluation(),FAKE_KEY,expected_sha=checksum)
        self.assertEqual(ssh.call_args.args,(evaluation(),FAKE_KEY))
        self.assertEqual(ssh.call_args.kwargs['transport']['scope_sha256'],checksum)

    def test_native_child_is_exact_original_guard_recognized_hash(self):
        self.assertEqual(hashlib.sha256(runner.REMOTE_CHILD.encode()).hexdigest(),'e016fa0da62bf796c5e830b51e7c5196f2ff0cdd5041d23bb1f69d6b2a8bd23e')
        self.assertNotIn('require_below_warning',runner.REMOTE_CHILD)

    def test_catalog_route_is_fixed_get_and_emits_only_public_models_and_specs(self):
        namespace={};exec(runner.DIAGNOSTIC_CORE,namespace)
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def read(self,_):return json.dumps({'data':[{'id':'muse-spark-1.3'},{'id':'muse-wonder-1.0'},
                                                       {'id':'other-provider-model'}]}).encode()
        opener=Mock();opener.open.return_value=Response()
        result=namespace['diagnostic_report'](FAKE_KEY,runner.WONDER_MODEL,opener)
        self.assertEqual(result['catalog'],{'http_status':200,'models':['muse-spark-1.3','muse-wonder-1.0']})
        self.assertEqual(result['clients']['wonder']['input_per_m'],'4')
        self.assertEqual(result['clients']['wonder']['output_per_m'],'20')
        request=opener.open.call_args.args[0]
        self.assertEqual(request.full_url,'https://api.meta.ai/v1/models');self.assertEqual(request.get_method(),'GET')
        self.assertNotIn(FAKE_KEY.decode(),json.dumps(result))
        opener.open.side_effect=urllib.error.HTTPError(request.full_url,403,'invented-private-body',{},io.BytesIO(b'invented-private-body'))
        error=namespace['diagnostic_catalog'](FAKE_KEY,opener)
        self.assertEqual(error,{'http_status':403,'error':'HTTPError'})


if __name__=='__main__':unittest.main()
