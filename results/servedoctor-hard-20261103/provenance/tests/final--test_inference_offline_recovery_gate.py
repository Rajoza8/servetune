"""Synthetic known-file restoration only; no actual outcomes or provider calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import inference_offline_recovery_gate as g


def put(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v));return p


class OfflineProof(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.addCleanup(patch.stopall)
        self.repo=Path(self.tmp.name).resolve();self.ops=self.repo/g.REL;self.ops.mkdir(parents=True);self.out=self.ops/'inference-offline-materialization-attempt1';self.out.mkdir()
        commands=[{'index':i,'name':name,'returncode':rc} for i,(name,rc) in enumerate([('meta-relay',0),('cold-prepare-validate',0),('authenticated-catalog',0),('all-six-arms',0),('mirror-study',0),('mirror-ops',255)])]
        parent=put(self.ops/'inference-rental-attempt1/outcome.json',{'returncode':1,'stop_confirmed':True,'cleanup_confirmed':True,'transport_cleanup_returncode':0,'commands':commands})
        evaluation=put(self.ops/'evaluation.json',{'completed':True,'failure':None,'cleanup_errors':[],'groups':['rules-spark-wonder','glimmer-cascades']})
        coverage=put(self.ops/'coverage.json',{'unrecoverable_scientific_files':0})
        roots={n:self.ops/x for n,x in [('study','inference-final-study'),('original','inference-final-original-study'),('ops','inference-final-remote-ops'),('old_ops','inference-final-remote-old-ops'),('control','inference-final-remote-control')]}
        for name,root in roots.items():
            root.mkdir()
            for i in range(280 if name=='study' else 178 if name=='original' else 1):(root/f'opaque-{i:03d}.txt').write_text('OPAQUE NEVER PARSED')
        put(roots['study']/'inference-analysis-protocol.json',{'original_inventory_sha256':g.inventory(roots['original'])})
        ledger=self.ops/'inference-final-gpu-ledger.json';ledger.write_bytes(b'OPAQUE LEDGER NEVER PARSED')
        patch.object(g,'LEDGER',g.sha(ledger)).start()
        manifest=put(self.ops/'manifest.json',{'stable':True,'study_file_count':281,'study_files_sha256':g.inventory(roots['study']),'ledger_sha256':g.LEDGER})
        target=roots['ops']/'opaque-000.txt';self.source=self.ops/'source.txt';self.source.write_bytes(target.read_bytes())
        put(coverage,{'targets':[{'target':str(target),'sha256':g.sha(target)}]});patch.object(g,'TARGET_COUNT',1).start()
        for name,path in [('PARENT',parent),('EVALUATION',evaluation),('MANIFEST',manifest),('COVERAGE',coverage)]:patch.object(g,name,g.sha(path)).start()
        self.r={'project':g.PROJECT,'analysis_project':g.ANALYSIS,'label':g.LABEL,'instance_id':g.INSTANCE,'rental_scope_sha256':g.SCOPE,'source_commit':g.SOURCE,
            'completed':True,'science_unchanged':True,'no_model_calls':True,'no_new_start':True,'all_required_scientific_artifacts_backed_up':True,
            'all_remote_artifacts_backed_up':False,'remote_ops_control_tail_unverified':True,'original_parent':g.desc(parent),'evaluation_outcome':g.desc(evaluation),
            'study_manifest':g.desc(manifest),'coverage_proof':g.desc(coverage),'restored_files':[{'target':str(target),'sha256':g.sha(target),'source':{'kind':'existing-file','path':str(self.source),'sha256':g.sha(self.source)}}],
            'mirrors':{n:{'local_root':str(root),'files_sha256':g.inventory(root)} for n,root in roots.items()},
            'ledger':{'path':str(ledger),'sha256':g.LEDGER,'remote_sha256':g.LEDGER},'input_verification':{'ready':True,'final_decisions':90}}
        self.path=self.out/'receipt.json';put(self.path,self.r);self.roots=roots;self.parent=parent
    def verify(self):return g.verify_recovery(self.repo,self.path)
    def test_exact_opaque_restoration_policy_and_failed_parent_preserved(self):
        before=self.parent.read_bytes();v=self.verify();self.assertFalse(v['all_remote_artifacts_backed_up']);self.assertTrue(v['all_required_scientific_artifacts_backed_up']);self.assertEqual(self.parent.read_bytes(),before)
        self.assertEqual(v['pipeline_outcome'],g.desc(self.parent));self.assertEqual(g.load(self.parent)['returncode'],1)
    def test_parent_failure_is_not_generalized(self):
        p=g.load(self.parent);p['commands'][3]['returncode']=1;put(self.parent,p);self.r['original_parent']=g.desc(self.parent);put(self.path,self.r);patch.object(g,'PARENT',g.sha(self.parent)).start()
        with self.assertRaises(ValueError):self.verify()
    def test_forged_full_remote_claim_or_new_start_blocks(self):
        for k,val in [('all_remote_artifacts_backed_up',True),('remote_ops_control_tail_unverified',False),('no_new_start',False)]:
            x=copy.deepcopy(self.r);x[k]=val;put(self.path,x)
            with self.assertRaises(ValueError):self.verify()
    def test_changed_scientific_bytes_or_missing_required_tree_blocks(self):
        (self.roots['study']/'opaque-000.txt').write_text('changed')
        with self.assertRaises(ValueError):self.verify()
    def test_missing90_or_foreign_scope_blocks(self):
        self.r['input_verification']['final_decisions']=89;put(self.path,self.r)
        with self.assertRaises(ValueError):self.verify()
    def test_changed_restoration_source_blocks(self):
        target=self.roots['ops']/'opaque-000.txt';source=self.ops/'source.txt';source.write_bytes(target.read_bytes())
        self.r['restored_files']=[{'target':str(target),'sha256':g.sha(target),'source':{'kind':'existing-file','path':str(source),'sha256':g.sha(source)}}];put(self.path,self.r);self.verify()
        source.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.verify()
    def test_receipt_cannot_drop_any_pinned_coverage_target(self):
        self.r['restored_files']=[];put(self.path,self.r)
        with self.assertRaises(ValueError):self.verify()
    def test_linked_member_blocks(self):
        path=self.roots['control']/'alias.txt';path.symlink_to(self.parent)
        with self.assertRaises(ValueError):self.verify()


if __name__=='__main__':unittest.main()
