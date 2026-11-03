"""Synthetic opaque files/archives only. No real study/answer/model/provider reads."""
import argparse
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import materialize_inference_offline as n

def put(q,v):q.parent.mkdir(parents=True,exist_ok=True);q.write_text(json.dumps(v)+'\n')
class MaterializerTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.addCleanup(patch.stopall);self.r=Path(self.t.name).resolve();self.p=self.r/'runs/servedoctor-hard15-ops-20261102';self.p.mkdir(parents=True)
        self.e=self.p/'inference-evaluation-attempt1';self.e.mkdir();self.source=self.p/'opaque-source.dat';self.source.write_bytes(b'opaque payload bytes\x00\xff')
        self.old=self.r/'runs/servedoctor-hard-ops-20261102/blocked-hard-study-attempt1';origin=self.old/'latest/study';origin.mkdir(parents=True)
        for i in range(178):(origin/f'item-{i:03d}.dat').write_bytes(b'opaque old bytes'+str(i).encode())
        put(self.old/'preserved-files-manifest.json',{'files':{'latest/study/'+k:v for k,v in n.inventory(origin).items()}})
        study=self.p/'inference-final-study';study.mkdir();(study/'sealed.dat').write_bytes(b'unchanged scientific bytes')
        self.archive=self.e/'study-ledger.tar.gz'
        with tarfile.open(self.archive,'x:gz') as a:
            a.add(study/'sealed.dat',arcname='study/sealed.dat');data=b'opaque final ledger'
            m=tarfile.TarInfo('canonical-ledger.json');m.size=len(data);a.addfile(m,io.BytesIO(data))
        self.ledger_sha=__import__('hashlib').sha256(data).hexdigest()
        put(self.e/'mirror-manifest.json',{'stable':True,'study_files_sha256':n.inventory(study),'ledger_sha256':self.ledger_sha,'archive_sha256':n.sha(self.archive),'archive_bytes':self.archive.stat().st_size})
        put(self.p/'inference-rental-attempt1/outcome.json',{'returncode':1,'commands':[{'name':'mirror-ops','returncode':255}]})
        put(self.e/'outcome.json',{'completed':True,'groups':['rules-spark-wonder','glimmer-cascades']})
        targets=[]
        for i in range(178):
            q=origin/f'item-{i:03d}.dat';targets.append({'target':str(self.p/'inference-final-original-study'/q.name),'sha256':n.sha(q),'candidates':[{'kind':'existing-file','path':str(q)}]})
        for folder,count in [('inference-final-remote-ops',100),('inference-final-remote-control',30),('inference-final-remote-old-ops',10),('inference-evaluation-attempt1',7)]:
            for i in range(count):targets.append({'target':str(self.p/folder/f'known-{i:03d}.dat'),'sha256':n.sha(self.source),'candidates':[{'kind':'existing-file','path':str(self.source)}]})
        targets.append({'target':str(self.p/'inference-final-gpu-ledger.json'),'sha256':self.ledger_sha,'candidates':[{'kind':'archive-member','archive':str(self.archive),'member':'canonical-ledger.json'}]})
        self.assertEqual(len(targets),326)
        partial=self.p/'inference-final-remote-ops';partial.mkdir();(partial/'partial-transfer.dat').write_bytes(b'failed partial bytes retained')
        self.c=self.p/'offline-inference-recovery-coverage.json';put(self.c,{'targets':targets,'model_stage_manifest':n.desc(self.e/'mirror-manifest.json'),'model_stage_archive':n.desc(self.archive),'unknown_final_operator_tails':[{'root':str(partial),'complete_remote_inventory_known':False}]})
        for key,value in [('COVERAGE',n.sha(self.c)),('PARENT',n.sha(self.p/'inference-rental-attempt1/outcome.json')),('EVALUATION',n.sha(self.e/'outcome.json')),('MANIFEST',n.sha(self.e/'mirror-manifest.json')),('PRESERVED',n.sha(self.old/'preserved-files-manifest.json'))]:patch.object(n,key,value).start()
        self.args=argparse.Namespace(coverage=str(self.c),out=str(self.p/'inference-offline-materialization-attempt1'),restore=False)
    def fake_gate(self,args,repo):
        self.assertEqual(repo,self.r);self.assertTrue(Path(args.ledger).is_file());self.assertEqual(n.sha(args.ledger),self.ledger_sha)
        return {'ready':True,'recordings':16,'final_decisions':90,'canonical_ledger_sha256':self.ledger_sha}
    def test_default_audit_has_no_writes(self):
        before=n.inventory(self.p);v=n.execute(self.args,self.r,gate=self.fake_gate)
        self.assertEqual(v['restores'],0);self.assertEqual(before,n.inventory(self.p));self.assertFalse(Path(self.args.out).exists())
    def test_restore_exact_bytes_and_preserve_original_failure_and_partial(self):
        self.args.restore=True;parent=n.sha(self.p/'inference-rental-attempt1/outcome.json');study=n.inventory(self.p/'inference-final-study')
        v=n.execute(self.args,self.r,gate=self.fake_gate);self.assertTrue(v['completed'])
        receipt=n.load(Path(self.args.out)/'receipt.json');self.assertFalse(receipt['all_remote_artifacts_backed_up']);self.assertTrue(receipt['remote_ops_control_tail_unverified'])
        self.assertTrue(receipt['all_required_scientific_artifacts_backed_up']);self.assertEqual(receipt['input_verification']['final_decisions'],90)
        self.assertEqual(parent,n.sha(self.p/'inference-rental-attempt1/outcome.json'));self.assertEqual(study,n.inventory(self.p/'inference-final-study'))
        self.assertEqual((Path(self.args.out)/'preserved-existing/inference-final-remote-ops/partial-transfer.dat').read_bytes(),b'failed partial bytes retained')
        self.assertEqual((self.p/'inference-final-gpu-ledger.json').read_bytes(),b'opaque final ledger')
        with self.assertRaises(ValueError):n.execute(self.args,self.r,gate=self.fake_gate)
    def test_source_tamper_blocks_before_any_restore(self):
        self.args.restore=True;self.source.write_bytes(b'tampered')
        with self.assertRaises(ValueError):n.execute(self.args,self.r,gate=self.fake_gate)
        self.assertFalse(Path(self.args.out).exists())
    def test_changed_existing_scientific_study_blocks(self):
        self.args.restore=True;(self.p/'inference-final-study/sealed.dat').write_bytes(b'changed')
        with self.assertRaises(ValueError):n.execute(self.args,self.r,gate=self.fake_gate)
        self.assertFalse(Path(self.args.out).exists())
    def test_existing_different_ledger_never_overwritten(self):
        q=self.p/'inference-final-gpu-ledger.json';q.write_bytes(b'otherledger');self.args.restore=True
        with self.assertRaises(ValueError):n.execute(self.args,self.r,gate=self.fake_gate)
        self.assertEqual(q.read_bytes(),b'otherledger')
    def test_full_gate_failure_retains_partial_outputs_and_no_completed_receipt(self):
        self.args.restore=True
        with self.assertRaises(ValueError):n.execute(self.args,self.r,gate=lambda *a,**kw:{'ready':False})
        out=Path(self.args.out);self.assertTrue((out/'failure.json').exists());self.assertFalse((out/'receipt.json').exists())
        self.assertTrue((out/'preserved-existing/inference-final-remote-ops').is_dir())
    def test_source_in_partial_tree_is_rebound_to_preserved_exact_bytes(self):
        self.args.restore=True;v=n.load(self.c);row=next(x for x in v['targets'] if '/inference-final-remote-ops/known-' in x['target'])
        source=self.p/'inference-final-remote-ops/partial-transfer.dat';row['sha256']=n.sha(source);row['candidates']=[{'kind':'existing-file','path':str(source)}]
        put(self.c,v);patch.object(n,'COVERAGE',n.sha(self.c)).start()
        n.execute(self.args,self.r,gate=self.fake_gate);receipt=n.load(Path(self.args.out)/'receipt.json')
        restored=next(x for x in receipt['restored_files'] if x['target']==row['target'])
        self.assertEqual(restored['source']['original_path'],str(source));self.assertTrue(Path(restored['source']['path']).is_file())
        self.assertEqual(n.sha(restored['source']['path']),restored['sha256']);self.assertFalse(source.exists())
if __name__=='__main__':unittest.main()
