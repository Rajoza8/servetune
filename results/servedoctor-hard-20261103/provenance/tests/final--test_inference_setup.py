"""Fake subprocesses/files only; no provider, SSH, GPU, key, model or actual study."""
import argparse
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import inference_cold_bootstrap as cold
import inference_prepare_stage as stage

def put(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v)+'\n')

class ColdTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.base=Path(self.t.name)
        self.repo=self.base/'repo';self.scope=self.base/'scope.json';put(self.scope,{'project':cold.PROJECT,'instance_id':70000001})
        self.bound=self.base/'binding.json';put(self.bound,{'project':cold.PROJECT,'instance_id':70000001,'purpose':'inference-only','rental_scope_sha256':cold.sha(self.scope)})
        self.args=argparse.Namespace(out=str(self.base/'out'),binding=str(self.bound),scope=str(self.scope),expected_vllm='v4-pinned')
        self.calls=[]
    def fake(self,argv,**kw):
        self.calls.append(argv)
        if argv[:2]==['git','clone']:self.repo.mkdir()
        if argv==['git','rev-parse','HEAD']:kw['stdout'].write((cold.SOURCE+'\n').encode())
        if argv[0]=='nvidia-smi':kw['stdout'].write(b'GPU-inference, NVIDIA RTX PRO 6000 Blackwell, 97887\n')
        return SimpleNamespace(returncode=0)
    def runfake(self,version='v4-pinned',container='70000001'):
        with patch.object(cold,'REPO',self.repo),patch.object(cold.resource,'getrlimit',return_value=(1024,1048576)),patch.object(cold.resource,'setrlimit'):
            return cold.run(self.args,self.fake,lambda _:version,{'CONTAINER_ID':container})
    def test_exact_source_revision_and_inference_only(self):
        v=self.runfake();self.assertTrue(v['completed']);self.assertIn(['git','checkout','--detach',cold.SOURCE],self.calls)
        text=json.dumps(self.calls);self.assertNotIn('generate-hard',text);self.assertNotIn('calibrate',text)
        self.assertNotIn('MODEL_API_KEY',text);self.assertIn('token=False',text);self.assertIn(cold.REV,text)
        h=json.loads((self.repo/cold.REL/'inference-hardware.json').read_text());self.assertEqual(h['dtype'],'bf16');self.assertEqual(h['fd_soft'],65536)
    def test_foreign_container_fails_before_commands_and_journals(self):
        with self.assertRaises(ValueError):self.runfake(container='1')
        self.assertEqual(self.calls,[]);self.assertEqual(json.loads((self.base/'out/outcome.json').read_text())['failure'],'ValueError')
    def test_wrong_vllm_is_not_reinstalled_or_downloaded(self):
        with self.assertRaises(ValueError):self.runfake(version='changed')
        self.assertFalse(any('download' in str(x) for x in self.calls));self.assertFalse(any('pip' in x for x in self.calls))
    def test_existing_repository_is_never_overwritten(self):
        self.repo.mkdir();(self.repo/'retained').write_text('retain')
        with self.assertRaises(ValueError):self.runfake()
        self.assertEqual((self.repo/'retained').read_text(),'retain');self.assertEqual(self.calls,[])

class StageTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.repo=Path(self.t.name);self.ops=self.repo/stage.p.OPS_REL;self.ops.mkdir(parents=True)
        self.control=self.ops/'inference-rental-attempt1';self.control.mkdir();self.binding=self.control/'binding.json';put(self.binding,{'safe':True})
        put(self.control/'rental-scope.json',{'allocation_deadline_epoch':10800})
        for n in (*stage.gate.HELPERS,'inference_cold_bootstrap.py','inference_remote_guard.py'):(self.ops/n).write_text('# invented '+n)
        self.args=argparse.Namespace(out=str(self.ops/'inference-prepare-attempt1'));self.labels=[];self.fail=None
    def build(self,out,repo):
        archive=out/'portable-recording-inputs.tar.gz';archive.write_bytes(b'invented');return archive,{'job_policy':{'vllm_version':'v4'}}
    def fake(self,argv,**kw):
        label=Path(kw['stdout'].name).name.removesuffix('.stdout');self.labels.append(label)
        if label==self.fail:return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)
    def runfake(self):
        with patch.object(stage,'build_bundle',self.build),patch.object(stage.remote,'connection',return_value=([], '127.0.0.1',22)),patch.object(stage.remote,'command',side_effect=lambda op,args:['REMOTE',op,*args]):
            return stage.execute(self.args,self.repo,self.fake,lambda:0,lambda *a:(9000,self.binding,{'instance_id':70000001,'rental_scope_sha256':'a'*64}))
    def test_guard_then_cold_then_install_then_one_native_validate(self):
        v=self.runfake();self.assertTrue(v['completed'])
        expected=['arm-fallback-guard','cold-bootstrap','install-portable-inputs','prepare-opaque-study','validate-once','verify-evaluation']
        self.assertEqual([x for x in self.labels if x in expected],expected);self.assertEqual(self.labels.count('validate-once'),1)
        self.assertIn('mirror-partial-study',self.labels);self.assertIn('mirror-fallback-guard-proof',self.labels)
        with self.assertRaises(ValueError):self.runfake()
    def test_failed_cold_setup_preserved_mirrors_and_no_validation(self):
        self.fail='cold-bootstrap'
        with self.assertRaises(Exception):self.runfake()
        v=json.loads((Path(self.args.out)/'outcome.json').read_text());self.assertFalse(v['completed']);self.assertEqual(v['failure'],'CalledProcessError')
        self.assertNotIn('validate-once',self.labels);self.assertIn('mirror-bootstrap-evidence',self.labels)
    def test_failed_native_validation_is_not_replayed_or_followed_by_verify(self):
        self.fail='validate-once'
        with self.assertRaises(Exception):self.runfake()
        self.assertEqual(self.labels.count('validate-once'),1);self.assertNotIn('verify-evaluation',self.labels);self.assertIn('mirror-validation-evidence',self.labels)
if __name__=='__main__':unittest.main()
