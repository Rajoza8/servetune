"""Synthetic process/time witnesses only; no actual process/provider actions."""
import hashlib
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_remote_guard as original
import remote_guard_partial as g


class PartialGuardContracts(original.Contracts):
    def setUp(self):
        patch.object(original,'g',g).start();self.addCleanup(patch.stopall);super().setUp()
    def test_exact_new_context_helper_hash_cwd_uid_and_birth_protect_cpu_work(self):
        folder=self.repo/g.PARTIAL_OPS_REL;folder.mkdir(parents=True);source=folder/'measure_contexts.py';source.write_bytes(b'# invented context helper\n')
        with patch.object(g,'PARTIAL_HELPER_SHA256',{'measure_contexts.py':g.digest(source)}):
            self.process(201,['/venv/main/bin/python',str(source),'--study-dir','runs/sd-hard-partial-attempt1','--out','safe.json'],self.repo)
            self.process(202,['/venv/main/bin/python',str(source)],self.base)
            self.process(203,['/venv/main/bin/python',str(source)],self.repo,uid=os.getuid()+1)
            self.assertEqual([(p['pid'],p['kind']) for p in self.scan()],[(201,'approved_partial_helper')])
            source.write_bytes(b'# changed')
            self.assertEqual(self.scan(),[])
    def test_actual_unchanged_child_partial_study_survives_http_idle_until_fixed_deadline(self):
        args=['evaluate','--study-dir','runs/sd-hard-partial-attempt1','--split','hard','--arms','rules,spark,wonder']
        self.process(210,['/venv/main/bin/python','-c',original.key.REMOTE_CHILD,'1'*40,'999',str(g.KEY_DEADLINE),*args],self.repo)
        result=self.run_guard(lambda **_:self.scan());self.assertEqual(result['reason'],'phase_deadline');self.assertEqual(self.mono,600)
    def test_current_partial_source_pins_match_frozen_reporter_code(self):
        repo=Path(__file__).resolve().parents[2]
        for name,digest in g.PARTIAL_HELPER_SHA256.items():self.assertEqual(hashlib.sha256((repo/g.PARTIAL_OPS_REL/name).read_bytes()).hexdigest(),digest)
    def test_exact_new_worker_parent_and_diagnostic_hashes_protect_only_scoped_code(self):
        repo=Path(__file__).resolve().parents[2];path=repo/g.PARTIAL_OPS_REL/'key_runner.py'
        spec=importlib.util.spec_from_file_location('partial_guard_worker_fixture_metadata',path);worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
        self.assertEqual(hashlib.sha256(worker.REMOTE_CODE.encode()).hexdigest(),g.PARTIAL_KEY_REMOTE_CODE_SHA256)
        self.assertEqual(hashlib.sha256(worker.REMOTE_DIAGNOSTIC.encode()).hexdigest(),g.PARTIAL_KEY_REMOTE_DIAGNOSTIC_SHA256)
        self.assertEqual(hashlib.sha256(worker.REMOTE_CHILD.encode()).hexdigest(),g.KEY_REMOTE_CHILD_SHA256)
        args=['evaluate','--study-dir','runs/sd-hard-partial-attempt1','--split','hard','--arms','spark,wonder']
        self.process(220,['/venv/main/bin/python','-c',worker.REMOTE_CODE,'999',*args],self.root_home)
        self.process(221,['/venv/main/bin/python','-c',worker.REMOTE_DIAGNOSTIC,'999'],self.root_home)
        self.process(222,['/venv/main/bin/python','-c',worker.REMOTE_CODE+'\n','999',*args],self.root_home)
        self.process(223,['/venv/main/bin/python','-c',worker.REMOTE_DIAGNOSTIC,'998'],self.root_home)
        self.assertEqual({p['pid'] for p in self.scan()},{220,221})


if __name__=='__main__':unittest.main()
