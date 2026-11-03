"""Invented public report files only; no actual outcomes, answers or providers."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import inference_descriptor_adapter as n

class DescriptorTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.r=Path(self.t.name).resolve()
        self.p=self.r/'runs/servedoctor-hard15-ops-20261102';self.study=self.p/'inference-final-study';self.study.mkdir(parents=True)
        self.projection=self.p/'inference-evaluation-attempt1/hard15-score-projection.json';self.projection.parent.mkdir()
        self.args=argparse.Namespace(study_dir=self.study,original_study_dir=self.p/'original',remote_ops=self.p/'remote',remote_old_ops=self.p/'old',remote_control=self.p/'control',calibration_mirror=self.p/'cal',score_projection=self.projection)
        scores={'scoreboards':{'all':{'rules':{'incidents':15}},'valid_only':{'rules':{'incidents':14}}},'denominators':{'all':15,'valid_only':14}}
        native={'by_arm':scores['scoreboards']['all'],'by_arm_valid_only':scores['scoreboards']['valid_only']}
        (self.study/'report.json').write_text(json.dumps(native));(self.study/'report.html').write_text('<html>native fixture</html>');self.projection.write_text(json.dumps(scores))
        aliases={key:(name,n.base.sha(self.projection if name=='score_projection' else self.study/name)) for key,(name,h) in n.ALIASES.items()}
        self.addCleanup(patch.stopall);patch.object(n,'ALIASES',aliases).start()
        keys=list(aliases)
        wrapped={'project':n.base.PROJECT,'label':n.base.LABEL,**scores,'native_report_html':{'path':keys[0],'sha256':aliases[keys[0]][1]},'native_report_json':{'path':keys[1],'sha256':aliases[keys[1]][1]},'score_projection':{'path':keys[2],'sha256':aliases[keys[2]][1]}}
        (self.study/'analysis-report.json').write_text(json.dumps(wrapped));(self.study/'analysis-report.html').write_text(n.base.LABEL+'<iframe src="report.html"></iframe>')
        self.scores=scores;self.wrapped=wrapped
    def test_exact_native_relative_descriptors_pass_unchanged_report_gate(self):
        e=n.Evidence(self.args,self.r);n.base.verify_reports(e,self.args,{'projection':self.scores})
        self.assertEqual(len(e.dependencies),3)
    def test_all_other_relative_and_traversal_paths_rejected(self):
        e=n.Evidence(self.args,self.r)
        for path in ('report.html','runs/sd-hard-partial-attempt1/../report.html','runs/sd-hard-partial-attempt1/report.html/extra','./runs/sd-hard-partial-attempt1/report.html'):
            with self.subTest(path=path),self.assertRaises(n.base.PackageError):e.resolve(path)
    def test_wrong_descriptor_hash_rejected_even_when_file_matches(self):
        e=n.Evidence(self.args,self.r);item=dict(self.wrapped['native_report_html']);item['sha256']='0'*64
        with self.assertRaises(n.base.PackageError):e.descriptor(item)
    def test_changed_report_bytes_rejected(self):
        (self.study/'report.html').write_text('changed fixture')
        with self.assertRaises(n.base.PackageError):n.Evidence(self.args,self.r).resolve(next(iter(n.ALIASES)))
    def test_absolute_descriptor_preserves_original_rules_and_sha(self):
        e=n.Evidence(self.args,self.r);item=n.base.desc(self.study/'report.html');self.assertEqual(e.descriptor(item),self.study/'report.html')
        item['sha256']='0'*64
        with self.assertRaises(n.base.PackageError):e.descriptor(item)
    def test_original_module_global_and_source_unchanged(self):
        self.assertIs(n.base._verify_inputs.__globals__['Evidence'],n.base.Evidence)
        self.assertNotEqual(n.base.Evidence,n.Evidence);self.assertEqual(n._sha(n._source),n.PACKAGE_SHA)

if __name__=='__main__':unittest.main()
