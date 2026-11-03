"""Invented partial mirrors, SSH, clock and provider only; no real actions."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import hard_vast as h
import startup_ssh_window as base
import partial_analysis_ssh_window as p
import test_frozen_host5_ssh_window as frozen_tests


class PartialWindowTests(unittest.TestCase):
    def setUp(self):
        self.old=frozen_tests.FrozenHost5Tests('test_prepare_is_offline_and_binds_known_completed_calibration_archive');self.old.setUp();self.addCleanup(self.old.doCleanups)
        self.root,self.s=self.old.root,self.old.s;self.addCleanup(patch.stopall)
        patch.object(p,'SCOPE',self.s.state['scope_sha256']).start();patch.object(p,'LEDGER',h.sha(self.s.repo/'runs/servedoctor-ledger.json')).start()
        folder=self.root/'blocked-hard-study-attempt1';study=folder/'latest/study';study.mkdir(parents=True)
        (study/'hard-experiment-freeze.json').write_text('Invented opaque original freeze\n');patch.object(p,'FREEZE',h.sha(study/'hard-experiment-freeze.json')).start()
        answers=study/'answers';answers.mkdir();(answers/'answer_keys.json').write_bytes(b'OPAQUE answer key not JSON; never decoded')
        (folder/'latest/canonical-ledger.json').write_bytes((self.s.repo/'runs/servedoctor-ledger.json').read_bytes())
        for name in ['reference']+[f'hard-{i:02d}' for i in range(1,16)]:
            directory=study/'incidents'/name;directory.mkdir(parents=True);public={}
            for filename in ['engine_config.json','engine_identity.json','events.json','slo.json','telemetry.jsonl','requests.jsonl','recording.json']:
                h.write(directory/filename,{'status':'completed'} if filename=='recording.json' else {'invented':True});public[filename]=h.sha(directory/filename)
            h.write(directory/'manifest.json',{'files':public})
        failed=study/'engines/engine-06-hard-16';failed.mkdir(parents=True);(failed/'engine.log').write_bytes(b'Invented retained startup error\n')
        receipt=folder/'preservation-receipt.json';h.write(receipt,{'status':'BLOCKED_INCOMPLETE','completed_recordings':16,'planned_recordings':17,
            'freeze_sha256':p.FREEZE,'ledger_sha256':p.LEDGER,'validated':False,'evaluated':False})
        manifest=folder/'preserved-files-manifest.json';h.write(manifest,{'files':{str(path.relative_to(folder)):h.sha(path) for path in folder.rglob('*') if path.is_file()}})
        patch.object(p,'PRESERVATION',h.sha(receipt)).start();patch.object(p,'MANIFEST',h.sha(manifest)).start()
        why=self.root/'partial-analysis-exclusion-20261102T2306Z.json';h.write(why,{'analysis_label':p.LABEL,'included_hard_ids':[f'hard-{i:02d}' for i in range(1,16)],'excluded_ids':['hard-16'],
            'before_validation':True,'before_any_hard_arm_evaluation':True,'hard16_may_be_modified_regenerated_or_rerecorded':False,
            'prompts_rules_scoring_answer_keys_unchanged':True,'original_freeze_sha256':p.FREEZE})
        patch.object(p,'EXCLUSION',h.sha(why)).start()
        stopped=copy.deepcopy(self.s.state);stopped['last_status'].update(actual_status='exited',cur_state='stopped',intended_status='stopped')
        h.write(self.root/'partial-analysis-stopped-state.json',stopped);patch.object(p,'STOPPED',h.sha(self.root/'partial-analysis-stopped-state.json')).start()
        for name in ('record-first9-attempt1','record-last8-attempt1','rearm-frozen-attempt2'):
            (self.root/name).mkdir();h.write(self.root/name/'outcome.json',{'invented':True})
        self.w=p.PartialAnalysisWindow(self.s,clock=self.s.clock,sleep=self.s.sleep,run=self.old.run_probe,collect=self.old.collect)
        self.out=self.root/'startup-ssh-window-attempt7'
    def prepare(self):return self.w.prepare(self.out,rental_proof=self.old.binding)
    def test_offline_prepare_truthfully_binds_partial_data_and_exclusion(self):
        path=self.prepare();plan=json.loads(path.read_text());self.assertEqual(plan['mode'],p.MODE)
        self.assertEqual(plan['analysis_label'],p.LABEL);self.assertEqual(plan['available_local_recordings'],16)
        self.assertTrue(plan['raw_partial_study_mirrored']);self.assertFalse(plan['remote_tail_after_partial_mirror_verified'])
        self.assertNotIn('no_recording_or_model_dispatch_observed',plan);self.assertEqual(self.s.events,[]);self.assertEqual(self.old.calls,[])
    def test_success_returns_only_fixed_guide_no_other_command(self):
        self.old.answer=0;self.assertIsNotNone(self.w.resume(self.prepare()));self.assertEqual(self.s.now,1000)
        self.assertEqual(len(self.old.calls),1);self.assertEqual(self.old.calls[0][0][-1],'cat /etc/vast-agents-guide.md');self.assertEqual(self.s.events,[])
    def test_600_denial_logs300_full_partial_backup_then_one_delete_no_stop(self):
        self.assertIsNone(self.w.resume(self.prepare()));self.assertEqual(self.s.now,1600);self.assertEqual(self.old.logs,[1300])
        self.assertEqual([x for x,t in self.s.events].count('delete'),1);self.assertNotIn('stop',[x for x,t in self.s.events])
        terminal=json.loads((self.out/'terminal.json').read_text());receipt=json.loads(Path(terminal['backup_receipt']['path']).read_text())
        self.assertTrue(receipt['all_available_local_recorded_study_backed_up']);self.assertFalse(receipt['all_remote_artifacts_backed_up'])
        self.assertFalse(receipt['remote_tail_after_partial_mirror_verified']);self.assertEqual(receipt['completed_hard_incidents'],15)
        mapping=json.loads(Path(receipt['manifest']['path']).read_text())['files_sha256']
        self.assertIn('blocked-hard-study-attempt1/latest/study/answers/answer_keys.json',mapping)
        self.assertIn('blocked-hard-study-attempt1/latest/study/engines/engine-06-hard-16/engine.log',mapping)
        self.assertEqual(self.s.state['running_intervals'][0]['stop_epoch'],self.s.state['destroyed_epoch'])
    def test_unknown_delete_resume_get_only_preserves_plan_and_terminal(self):
        self.s.confirm=False;path=self.prepare();plan=path.read_bytes();self.w.resume(path);terminal=(self.out/'terminal.json').read_bytes()
        self.s.confirm=True;self.s.now+=20;calls=len(self.old.calls);self.w.resume(path)
        self.assertEqual(len(self.old.calls),calls);self.assertEqual([x for x,t in self.s.events].count('delete'),1)
        self.assertEqual(path.read_bytes(),plan);self.assertEqual((self.out/'terminal.json').read_bytes(),terminal)
    def test_changed_partial_or_exclusion_never_probes_or_deletes(self):
        path=self.prepare();target=self.root/'blocked-hard-study-attempt1/latest/study/answers/answer_keys.json';target.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.w.resume(path)
        self.assertEqual(self.old.calls,[]);self.assertEqual(self.s.events,[])
    def test_backup_skips_private_and_ephemeral_and_retains_partial_attempt(self):
        path=self.prepare();partial=self.out/'partial-analysis-backup-attempt0001';partial.mkdir();(partial/'receipt.json').write_text('{broken')
        (self.root/'active-command.tmp').write_text('ephemeral');self.s.now=1600
        original=Path.read_bytes
        def guarded(source):
            if source.name in ('private.key','.env','active-command.tmp'):raise AssertionError('Private source must not be read')
            return original(source)
        with patch.object(Path,'read_bytes',guarded):self.w.resume(path)
        self.assertEqual((partial/'receipt.json').read_text(),'{broken');self.assertTrue((self.out/'partial-analysis-backup-attempt0002/receipt.json').exists())
    def test_changed_endpoint_accepts_only_original_key(self):
        path=self.prepare();self.old.answer=0;self.s.state['last_status']['ports']['22/tcp'][0]['HostPort']='3333'
        self.assertIsNotNone(self.w.resume(path));self.assertEqual([v[0] for v,t in self.old.calls],['ssh-keyscan','ssh'])
    def test_late_auth_not_adopted_or_automatically_deleted(self):
        path=self.prepare();_,plan=self.w.load_plan(path);self.s.now=1599;self.old.answer=0;original=self.old.run_probe
        def slow(*args,**kwargs):result=original(*args,**kwargs);self.s.now+=2;return result
        self.w.run=slow;self.assertFalse(self.w.probe(self.out,plan)['guide_authenticated'])
        with self.assertRaises(ValueError):self.w.resume(path)
        self.assertEqual(self.s.events,[])


if __name__=='__main__':unittest.main()
