"""Synthetic controller contracts. No real subprocesses, sockets, records or keys."""
import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

import importlib.util
import sys
if importlib.util.find_spec('key_runner') is None:
    stub=types.SimpleNamespace(REV='cec94fcfd6512f2cfe708138c32533b346ea4f69',SOCKET=Path('/invented-unused-socket'))
    with patch.dict(sys.modules,{'key_runner':stub}):
        import partial_evaluation_stage as stage
else:
    import partial_evaluation_stage as stage


class EvaluationStageContracts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.repo=Path(self.temp.name).resolve();self.ops=self.repo/'runs/servedoctor-hard15-ops-20261102'
        self.ops.mkdir(parents=True);(self.repo/'runs/sd-hard-partial-attempt1').mkdir();self.rental_ops=self.repo/'runs/servedoctor-hard-ops-20261102';self.rental_ops.mkdir()
        self.now=1793628000.;self.calls=[];self.failure=None;self.context_fits=True;self.warning=False
        self.ledger=b'{"invented":"canonical-ledger-fixture-only"}'
        self.ledger_sha=hashlib.sha256(self.ledger).hexdigest()
        self.blobs={};self.evaluated=[]
        for name in stage.HELPERS:(self.ops/name).write_text('# invented helper fixture only\n')
        proof={'returncode':0,'py_compile':'passed','files_sha256':{name:stage.sha(self.ops/name) for name in stage.HELPERS}}
        (self.ops/stage.HELPER_PROOF).write_text(json.dumps(proof))

    def args(self,**updates):
        value={'study_dir':'runs/sd-hard-partial-attempt1','out':str(self.ops/'evaluation-attempt1'),'expected_ledger_sha256':self.ledger_sha}
        value.update(updates);return argparse.Namespace(**value)

    def fake_run(self,argv,**kwargs):
        label=Path(kwargs['stdout'].name).stem;self.calls.append((label,argv,kwargs['timeout']))
        data={};code=0
        if label.endswith('-evaluate'):
            self.evaluated.append(argv[argv.index('evaluate'):])
            kwargs['stdout'].write(b'INVENTED_RAW_MODEL_PAYLOAD\n')
            if self.failure==label:code=1
            if self.failure=='primary-and-snapshot':code=7
        elif label=='integrity-preflight':data={'project':stage.PROJECT,'label':'wrong full-study label' if self.failure=='wrong-label' else stage.LABEL,'evaluation_ready':True,'total':15}
        elif label.endswith('-ledger'):
            if self.failure=='primary-and-snapshot' and label=='rules-spark-wonder-ledger':
                return subprocess.CompletedProcess(argv,9)
            data={'sha256':self.ledger_sha,'summary':{'caps_usd':{'meta':50.0,'baseten':20.0},
                  'accounted_usd':{'meta':12.25,'baseten':0},'calls':443,'warnings':['budget'] if self.warning else []}}
        elif label.endswith('-ledger-mirror'):Path(argv[-1]).write_bytes(self.ledger)
        elif '-score-' in label:data={'rules':{'incidents':13,'healthy_controls':3,'call_failures':0}}
        elif label=='contexts':data={'project':stage.PROJECT,'label':stage.LABEL,'incidents':15,'fits_8192':self.context_fits,'model_revision':stage.REV,
             'per_incident_maximum':{case:{} for case in stage.IDS}}
        elif label.endswith('-responses'):
            data={'project':stage.PROJECT,'label':stage.LABEL,'ready_for_next_group':self.failure!='zero-usage','by_arm':{}}
            if self.failure==label:code=2
        elif label=='score-export':data={'scoreboards':{'all':{},'valid_only':{}},'denominators':{},'decision_coverage':{'present':90}}
        elif label=='score-export-mirror':Path(argv[-1]).write_text('{"invented":"safe-score-projection"}')
        elif label=='archive-prepare':
            if self.failure==label:return subprocess.CompletedProcess(argv,1)
            base=stage.REMOTE_OPS+'/evaluation-stages/evaluation-attempt1'
            archive=b'opaque invented archive fixture';manifest=b'{"invented":"opaque-file-hashes-only"}'
            self.blobs[stage.REMOTE_REPO+'/'+base+'/study-ledger.tar.gz']=archive
            self.blobs[stage.REMOTE_REPO+'/'+base+'/mirror-manifest.json']=manifest
            data={'archive':base+'/study-ledger.tar.gz','archive_sha256':hashlib.sha256(archive).hexdigest(),
                  'manifest':base+'/mirror-manifest.json','manifest_sha256':hashlib.sha256(manifest).hexdigest(),
                  'ledger_sha256':self.ledger_sha,'study_file_count':320,'stable':True}
        elif label in ('archive-mirror','manifest-mirror'):Path(argv[-1]).write_bytes(self.blobs[argv[-2]])
        if data:kwargs['stdout'].write(json.dumps(data).encode())
        return subprocess.CompletedProcess(argv,code)

    def execute(self,**updates):
        self.progress=io.StringIO()
        with redirect_stdout(self.progress):
            return stage.execute(self.args(**updates),ops=self.ops,repo=self.repo,run=self.fake_run,
                                 clock=lambda:self.now,ready=lambda ops,clock:(self.now+3600,self.now+3780))

    def test_exact_two_groups_prerequisites_final_scores_and_opaque_mirror(self):
        result=self.execute()
        self.assertTrue(result['completed']);self.assertIsNone(result['failure']);self.assertEqual(result['label'],stage.LABEL)
        self.assertEqual([cmd[cmd.index('--arms')+1] for cmd in self.evaluated],
                         ['rules,spark,wonder','glimmer,glimmer_to_spark,glimmer_to_wonder'])
        self.assertNotIn('--start-glimmer',self.evaluated[0]);self.assertIn('--start-glimmer',self.evaluated[1])
        self.assertEqual(self.evaluated[1][-2:],['--model-revision',stage.REV])
        labels=[row[0] for row in self.calls]
        self.assertLess(labels.index('contexts'),labels.index('rules-spark-wonder-evaluate'))
        self.assertLess(labels.index('rules-spark-wonder-responses'),labels.index('glimmer-cascades-evaluate'))
        self.assertNotIn('INVENTED_RAW_MODEL_PAYLOAD',self.progress.getvalue())
        self.assertTrue((self.ops/'evaluation-attempt1/study-ledger.tar.gz').is_file())
        self.assertFalse((self.repo/'runs/servedoctor-ledger.json').exists())
        self.assertTrue(all(0<timeout<=3780 for _,_,timeout in self.calls))

    def test_first_group_failure_never_retries_or_dispatches_second(self):
        self.failure='rules-spark-wonder-evaluate';result=self.execute()
        self.assertFalse(result['completed']);self.assertEqual(result['failure']['class'],'CalledProcessError')
        self.assertEqual(len(self.evaluated),1)
        self.assertTrue((self.ops/'evaluation-attempt1/rules-spark-wonder-evaluate.stdout').exists())
        self.assertIn('final-ledger',[row[0] for row in self.calls]);self.assertIn('opaque_mirror',result)

    def test_context_miss_and_initial_warning_each_block_all_paid_groups(self):
        self.context_fits=False;result=self.execute()
        self.assertFalse(result['completed']);self.assertEqual(self.evaluated,[])
        # Independent fresh attempt for another invented prerequisite outcome.
        self.context_fits=True;self.warning=True
        result=self.execute(out=str(self.ops/'evaluation-attempt2'))
        self.assertFalse(result['completed']);self.assertEqual(self.evaluated,[])

    def test_archive_failure_retained_without_retry(self):
        self.failure='archive-prepare';result=self.execute()
        self.assertFalse(result['completed'])
        self.assertEqual([row[0] for row in self.calls].count('archive-prepare'),1)
        self.assertEqual(result['cleanup_errors'][-1]['stage'],'opaque-study-mirror')

    def test_failed_response_guard_blocks_second_group(self):
        self.failure='rules-spark-wonder-responses';result=self.execute()
        self.assertFalse(result['completed']);self.assertEqual(len(self.evaluated),1)
        self.assertEqual(result['failure']['returncode'],2)

    def test_primary_submit_failure_survives_snapshot_failure(self):
        self.failure='primary-and-snapshot';result=self.execute()
        self.assertEqual(result['failure']['returncode'],7)
        self.assertEqual(len(self.evaluated),1)
        self.assertEqual(result['cleanup_errors'][0]['stage'],'rules-spark-wonder-snapshot')

    def test_canonical_ledger_hash_mismatch_blocks_all_evaluation(self):
        result=self.execute(expected_ledger_sha256='0'*64)
        self.assertFalse(result['completed']);self.assertEqual(self.evaluated,[])
        self.assertEqual(result['failure']['class'],'ValueError')

    def test_stale_helper_proof_no_dispatch_and_existing_output_no_reuse(self):
        (self.ops/stage.HELPERS[0]).write_text('# untested change')
        result=self.execute();self.assertFalse(result['completed']);self.assertEqual(self.evaluated,[])
        self.assertFalse(any(label.startswith('upload-') for label,_,_ in self.calls))
        with self.assertRaises(FileExistsError):self.execute()

    def test_phase_socket_readiness_is_metadata_only_and_fixed_code_compiles(self):
        active={'project':stage.RENTAL_PROJECT,'pid':os.getppid(),'at_epoch':self.now,'deadline_epoch':self.now+3600}
        (self.rental_ops/'active-command.json').write_text(json.dumps(active))
        info=types.SimpleNamespace(st_mode=stat.S_IFSOCK|0o600,st_uid=os.getuid())
        with patch.object(stage.key_runner,'SOCKET',types.SimpleNamespace(lstat=lambda:info)):
            self.assertEqual(stage.readiness(self.ops,lambda:self.now),(self.now+3240,self.now+3420))
            info.st_mode=stat.S_IFSOCK|0o666
            with self.assertRaises(ValueError):stage.readiness(self.ops,lambda:self.now)
        for code in (stage.PREPARE,stage.LEDGER,stage.ARCHIVE,stage.LABEL_REPORT):compile(code,'fixed-offline-fixture','exec')


    def test_zero_usage_and_wrong_analysis_label_fail_closed_and_keep_mirrors(self):
        self.failure='zero-usage';value=self.execute()
        self.assertFalse(value['completed']);self.assertEqual(len(self.evaluated),1)
        self.assertIn('opaque_mirror',value)
        self.assertTrue((self.ops/'evaluation-attempt1/rules-spark-wonder-evaluate.stdout').is_file())
        self.failure='wrong-label';self.evaluated=[]
        value=self.execute(out=str(self.ops/'evaluation-attempt2'))
        self.assertFalse(value['completed']);self.assertEqual(self.evaluated,[])

    def test_display_wrapper_labels_partial_analysis_without_changing_native_bytes(self):
        study=self.repo/'runs/sd-hard-partial-attempt1'
        (study/'report.html').write_text('<p>INVENTED_NATIVE_REPORT</p>')
        (study/'report.json').write_text('{"invented":"private native provenance"}')
        before={name:stage.sha(study/name) for name in ('report.html','report.json')}
        projection=self.ops/'invented-score-projection.json'
        projection.write_text(json.dumps({'label':stage.LABEL,'decision_coverage':{'expected':90,'present':90},'scoreboards':{'all':{},'valid_only':{}},'denominators':{}}))
        output=io.StringIO()
        with patch.object(sys,'argv',['fixed-fixture',str(study),str(projection)]),redirect_stdout(output):
            exec(compile(stage.LABEL_REPORT,'fixed-fixture','exec'),{})
        self.assertEqual(before,{name:stage.sha(study/name) for name in before})
        wrapped=json.loads((study/'analysis-report.json').read_text())
        self.assertEqual(wrapped['label'],stage.LABEL)
        self.assertIn(stage.LABEL,(study/'analysis-report.html').read_text())
        self.assertNotIn('private native provenance',json.dumps(wrapped))
        with patch.object(sys,'argv',['fixed-fixture',str(study),str(projection)]):
            with self.assertRaises(FileExistsError):exec(compile(stage.LABEL_REPORT,'fixed-fixture','exec'),{})

    def test_finite_work_and_cleanup_envelope_and_labelled_progress(self):
        result=self.execute(max_work_seconds=300)
        self.assertTrue(result['completed'])
        self.assertEqual(result['work_deadline_epoch'],self.now+300)
        self.assertEqual(result['cleanup_deadline_epoch'],self.now+480)
        self.assertTrue(all(timeout<=480 for _,_,timeout in self.calls))
        for line in self.progress.getvalue().splitlines():
            self.assertEqual(json.loads(line)['label'],stage.LABEL)
        with self.assertRaises(ValueError):self.execute(out=str(self.ops/'bad-envelope'),max_work_seconds=3901)


if __name__=='__main__':unittest.main()
