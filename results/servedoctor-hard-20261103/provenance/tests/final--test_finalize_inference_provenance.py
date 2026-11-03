"""Invented publication metadata only. No actual study/model/provider data."""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

P=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('finaldocs',P/'finalize_inference_provenance.py')
n=importlib.util.module_from_spec(spec);spec.loader.exec_module(n)


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n')
    return path


class PublicationMetadata(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.scan=staticmethod(n.package_scanner())
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.repo=Path(self.tmp.name).resolve();self.ops=self.repo/'runs/servedoctor-hard15-ops-20261102';self.ops.mkdir(parents=True)
        self.files=[]
        for i in range(243):
            path=self.ops/f'artifact-{i:03d}.txt';path.write_text('invented public metadata\n')
            self.files.append({'source':n.descriptor(path),'destination':f'provenance/fake/artifact-{i:03d}.txt','group':sorted(n.GROUPS)[i%10]})
        self.rows=[{'id':f'historical-{i}','category':'synthetic','summary':'Invented failure','reason':'Offline fixture','artifacts':[self.files[0]['source']]} for i in range(29)]
        historic={}
        for count,field in [(18,'original_failure_index'),(21,'prior_partial_failure_index'),(28,'prior_inference_failure_index')]:
            path=put(self.ops/f'prefix-{count}.json',{'failures':self.rows[:count]});historic[field]=n.descriptor(path)
        self.failure=put(self.ops/'failures-draft.json',{'project':n.PROJECT,'label':n.LABEL,'finalized':False,'failures':self.rows,**historic})
        self.flat=put(self.ops/'flat-draft.json',{'project':n.PROJECT,'label':n.LABEL,'files':self.files,'failure_index':n.descriptor(self.failure),'pending_required_groups':['finalization']})
        self.additions=put(self.ops/'additions.json',{'project':n.PROJECT,'label':n.LABEL,'files':[],'failures':[]})
        self.projection=put(self.ops/'projection.json',{'project':n.PROJECT,'label':n.LABEL,'freeze_sha256':n.FREEZE,'decision_coverage':{'expected':90,'present':90},
            'valid_cases':14,'invalid_cases':1,'denominators':{'all':{'cases':15},'valid_only':{'cases':14}},'per_case':[{'id':i,'arm':a} for i in sorted(n.IDS) for a in sorted(n.ARMS)]})
        self.evaluation=put(self.ops/'evaluation.json',{'project':n.PROJECT,'label':n.LABEL,'completed':True,'groups':['rules-spark-wonder','glimmer-cascades'],'failure':None,'cleanup_errors':[],'finished_at_utc':'2026-11-03T05:00:00+00:00'})
        self.ledger=self.ops/'ledger.json';self.ledger.write_text('invented opaque ledger bytes\n')
        self.cleanup=put(self.ops/'cleanup.json',{'project':'servedoctor-hard15-inference-20261103','analysis_project':n.PROJECT,'label':n.LABEL,'original_freeze_sha256':n.FREEZE,
            'instance_id':58905385,'rental_scope_sha256':n.SCOPE,'confirmed_absent':True,'stopped_confirmed':True,'owned_work_quiescent':True,
            'gpu_accounting':{'total_usd_upper':42.1,'total_cap_usd':43},'ledger_summary':{'caps_usd':{'meta':50.,'baseten':20.},'warnings':[]},
            'canonical_ledger_sha256':n.sha(self.ledger),'remote_ledger_sha256':n.sha(self.ledger)})
        self.sync=put(self.ops/'sync.json',{'project':n.PROJECT,'label':n.LABEL,'canonical_ledger_sha256':n.sha(self.ledger),'remote_ledger_sha256':n.sha(self.ledger),'seed_prefix_unchanged':True,'verified':True,'already_synchronized':True,'inherited_prefix_entries':443,'final_sha256':n.sha(self.ledger),'source':n.descriptor(self.ledger),'cleanup':n.descriptor(self.cleanup)})
        self.out=self.ops/'inference-provenance-finalization-attempt1'
        self.args=argparse.Namespace(draft=str(self.flat),failures=str(self.failure),additions=str(self.additions),projection=str(self.projection),evaluation=str(self.evaluation),cleanup=str(self.cleanup),ledger=str(self.ledger),ledger_sync_receipt=str(self.sync),out=str(self.out))
        self.addCleanup(patch.stopall)
        patch.object(n,'FLAT_SHA',n.sha(self.flat)).start();patch.object(n,'FAILURE_SHA',n.sha(self.failure)).start()
    def run_final(self):return n.finalize(self.args,repo=self.repo,scanner=self.scan)
    def mutate(self,path,key,value):
        x=n.load(path);x[key]=value;put(path,x)
    def blocked(self):
        with self.assertRaises(ValueError):self.run_final()
        self.assertFalse(self.out.exists())
    def test_complete_emits_fresh_preserved_index_and_manifest_only(self):
        before={p:n.sha(p) for p in (self.flat,self.failure,self.ledger)}
        result=self.run_final();self.assertTrue(result['finalized']);self.assertEqual((result['files'],result['failure_rows']),(248,29))
        index=n.load(self.out/'failure-index.json');manifest=n.load(self.out/'published-allowlist.json')
        self.assertEqual(index['failures'][:29],self.rows);self.assertTrue(index['finalized'])
        self.assertEqual(index['pending_appendices'],[]);self.assertIn('scoped cleanup verified',index['current_outcome_not_claimed'])
        self.assertEqual(index['completion_evidence']['cleanup'],n.descriptor(self.cleanup))
        self.assertEqual(manifest['files'][:243],self.files)
        self.assertEqual(manifest['failure_index'],n.descriptor(self.out/'failure-index.json'))
        self.assertEqual(before,{p:n.sha(p) for p in before});self.assertEqual(result['provider_actions'],0);self.assertEqual(result['ledger_writes'],0)
    def test_partial_or_failed_evaluation_blocks_without_outputs(self):
        self.mutate(self.evaluation,'completed',False);self.blocked()
    def test_incomplete90_coverage_blocks(self):
        self.mutate(self.projection,'decision_coverage',{'expected':90,'present':79});self.blocked()
    def test_wrong_label_or_duplicated_cells_blocks(self):
        x=n.load(self.projection);x['per_case'][-1]=x['per_case'][0];put(self.projection,x);self.blocked()
    def test_unconfirmed_cleanup_and_cap_violation_block(self):
        self.mutate(self.cleanup,'confirmed_absent',False);self.blocked()
        self.mutate(self.cleanup,'confirmed_absent',True);self.mutate(self.cleanup,'gpu_accounting',{'total_usd_upper':43.01,'total_cap_usd':43});self.blocked()
    def test_ledger_sync_mismatch_blocks_and_does_not_write_ledger(self):
        before=n.sha(self.ledger);self.mutate(self.sync,'remote_ledger_sha256','0'*64);self.blocked();self.assertEqual(n.sha(self.ledger),before)
    def test_changed_reviewed_draft_blocks(self):
        self.mutate(self.flat,'label','Wrong');self.blocked()
    def test_changed_selected_artifact_blocks(self):
        Path(self.files[0]['source']['path']).write_text('changed');self.blocked()
    def test_secret_canary_is_rejected_by_actual_packager_scan(self):
        path=self.ops/'canary.txt';path.write_text('MODEL_'+'API_KEY='+'FAKE_'+'SECRET_CANARY_'+'12345678901234567890\n')
        put(self.additions,{'project':n.PROJECT,'label':n.LABEL,'files':[{'source':n.descriptor(path),'destination':'provenance/finalization/canary.txt','group':'finalization'}]});self.blocked()
    def test_new_failure_requires_selected_artifact_and_then_appends(self):
        path=self.ops/'late-failure.json';put(path,{'safe_failure_class':'InterruptedError'})
        row={'id':'late-failure','category':'synthetic','summary':'Invented later failure','reason':'Retained evidence','artifacts':[n.descriptor(path)]}
        put(self.additions,{'project':n.PROJECT,'label':n.LABEL,'files':[],'failures':[row]});self.blocked()
        put(self.additions,{'project':n.PROJECT,'label':n.LABEL,'files':[{'source':n.descriptor(path),'destination':'provenance/failures/late.json','group':'failures'}],'failures':[row]})
        result=self.run_final();self.assertEqual(result['failure_rows'],30);self.assertEqual(n.load(self.out/'failure-index.json')['failures'][:29],self.rows)
    def test_ledger_sync_must_be_after_copy_not_only_pre_sync_verification(self):
        self.mutate(self.sync,'already_synchronized',False);self.blocked()
    def test_new_helper_and_fixture_sources_are_publishable(self):
        self.scan(P/'finalize_inference_provenance.py');self.scan(P/'test_finalize_inference_provenance.py')
    def test_second_run_never_reuses_or_deletes_first_output(self):
        self.run_final();before={x.name:n.sha(x) for x in self.out.iterdir()}
        with self.assertRaises(ValueError):self.run_final()
        self.assertEqual(before,{x.name:n.sha(x) for x in self.out.iterdir()})
    def test_cutoff_and_native_warning_stop_are_required(self):
        self.mutate(self.evaluation,'finished_at_utc','2026-11-03T23:00:01+00:00');self.blocked()
        self.mutate(self.evaluation,'finished_at_utc','2026-11-03T05:00:00+00:00')
        self.mutate(self.cleanup,'ledger_summary',{'caps_usd':{'meta':50.,'baseten':20.},'warnings':['meta50percent']});self.blocked()


if __name__=='__main__':unittest.main()
