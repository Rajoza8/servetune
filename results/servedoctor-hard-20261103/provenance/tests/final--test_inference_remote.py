"""SSH argv only; no processes, private-key reads or network."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import inference_remote as r


class TransportContracts(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(prefix='inference spaces ');self.addCleanup(self.t.cleanup)
        self.repo=Path(self.t.name);self.root=self.repo/'control';self.root.mkdir();(self.root/'known_hosts').write_text('public host trust')
        self.state={'instance_id':60001001,'last_status':{'id':60001001,'actual_status':'running','public_ipaddr':'203.0.113.1','ports':{'22/tcp':[{'HostPort':'2222'}]}}}
        owner=self
        class Service:
            repo=owner.repo;root=owner.root
            def load(self):return owner.state
        self.s=Service()
    def test_run_strict_identity_scope_offline_fd_and_no_private_read(self):
        key=self.repo/'runs/vast-preflight-20261029/ssh_ed25519';key.parent.mkdir(parents=True);key.write_bytes(b'PRIVATE CANARY')
        read=Path.read_bytes
        def guarded(path):
            if path==key:raise AssertionError('private read')
            return read(path)
        with patch.object(Path,'read_bytes',guarded):argv=r.command('run',['python3','fixed.py'],self.s)
        self.assertIn('-F',argv);self.assertIn('/dev/null',argv);self.assertIn('IdentitiesOnly=yes',argv);self.assertIn('StrictHostKeyChecking=yes',argv)
        self.assertIn(str(key),argv);self.assertIn('HF_HUB_OFFLINE=1',argv[-1]);self.assertIn('65536',argv[-1]);self.assertIn(r.REMOTE_REPO,argv[-1])
        self.assertIn('UserKnownHostsFile="'+str(self.root/'known_hosts')+'"',argv)
    def test_stopped_or_destroyed_never_dispatches(self):
        self.state['last_status']['actual_status']='exited'
        with self.assertRaises(ValueError):r.connection(self.s)
        self.state['last_status']['actual_status']='running';self.state['destroyed_epoch']=1
        with self.assertRaises(ValueError):r.connection(self.s)
    def test_endpoint_injection_and_invalid_port_rejected(self):
        self.state['last_status']['public_ipaddr']='203.0.113.1;echo bad'
        with self.assertRaises(ValueError):r.connection(self.s)
        self.state['last_status']['public_ipaddr']='203.0.113.1';self.state['last_status']['ports']['22/tcp'][0]['HostPort']='99999'
        with self.assertRaises(ValueError):r.connection(self.s)
    def test_get_never_overwrites_retained_evidence(self):
        target=self.repo/'existing';target.write_bytes(b'retain')
        with self.assertRaises(ValueError):r.command('get',['/workspace/public',str(target)],self.s)
        self.assertEqual(target.read_bytes(),b'retain')
    def test_put_refuses_link_and_relative_remote_path(self):
        target=self.repo/'public';target.write_bytes(b'public');link=self.repo/'linked';link.symlink_to(target)
        with self.assertRaises(ValueError):r.command('put',[str(link),'/workspace/public'],self.s)
        with self.assertRaises(ValueError):r.command('put',[str(target),'relative'],self.s)


if __name__=='__main__':unittest.main()
