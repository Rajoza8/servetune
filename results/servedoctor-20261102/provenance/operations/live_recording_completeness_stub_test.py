"""Synthetic public live capture fixtures; never real outcomes/answers/network."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import live_recording_completeness as audit


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value)+'\n')


class LiveCompletenessContracts(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.ids=['inc-01','inc-04','inc-06','inc-14','inc-16','inc-21']
        self.cases=[{'id':ident,'duration_s':360,'request_timeout_s':60,'workload_seed':100+i,'max_output_tokens':128,'slo':{'p95_latency_s':1,'max_error_rate':.01},
            'schedule':[{'start_s':0,'rate_rps':.05,'mix':{'short':.3,'medium':.3,'long':.4}}]} for i,ident in enumerate(self.ids)]
        put(self.root/'scenarios.json',{'scenarios':self.cases})
        put(self.root/'dev-selected-escalation.json',{'arm':'glimmer_to_spark','live_ids':dict(enumerate(self.ids))})
        public_hashes={audit.STUDY+'/'+name:audit.sha(self.root/name) for name in ('scenarios.json','dev-selected-escalation.json')}
        public_hashes.update({name:audit.sha(audit.REPO/name) for name in ('servedoctor/live.py','servedoctor/loadgen.py')})
        put(self.root/'experiment-freeze.json',{'files_sha256':public_hashes})
        private=self.root/'answers/answer_keys.json';private.parent.mkdir();private.write_bytes(b'\xffNEVER_READ_PRIVATE_ANSWER_BYTES')
        for case in self.cases:
            for arm in audit.ARMS:self.make_run(case,arm)

    def make_run(self,case,arm):
        folder=self.root/'live'/(case['id']+'-'+arm+'-fixture');folder.mkdir(parents=True)
        put(folder/'scenario_public.json',{'id':case['id'],'arm':arm,'duration_s':660,'slo':case['slo'],'started_at':'2026-11-02T06:00:00+00:00'})
        step={'t':30,'decision':{'raw_output':'NEVER_EMIT_MODEL_TEXT','explanation':'NEVER_EMIT_EXPLANATION'}}
        put(folder/'live_result.json',{'id':case['id'],'arm':arm,'failure':None,'cleanup_errors':[],'trail':[step],
            'recovered':False,'rolled_back':True,'decision':{'raw_output':'NEVER_EMIT_MODEL_TEXT'}})
        (folder/'checkpoints.jsonl').write_text(json.dumps(step)+'\n')
        self.telemetry(folder,range(843))
        requests=[{'id':ident,'t_sched':t,'cls':cls,'status':'timeout','t_done':t+180,'latency_s':180.0}
                  for ident,(t,cls) in audit.expected_requests(case).items()]
        self.requests(folder,requests)
        return folder

    def folder(self):return self.root/'live'/(self.ids[0]+'-glimmer_to_spark-fixture')
    def telemetry(self,folder,times):
        (folder/'telemetry.jsonl').write_text(''.join(json.dumps({'t':t,'log':[]})+'\n' for t in times))
    def requests(self,folder,rows):
        (folder/'requests.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    def hashes(self):return {str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}

    def test_all12_high_error_unrecovered_rollback_runs_pass_without_model_text_or_writes(self):
        before=self.hashes();result=audit.audit_study(self.root)
        self.assertTrue(result['all_expected_live_runs_complete']);self.assertEqual(result['complete_run_counts'],{'glimmer_to_spark':6,'rules':6})
        self.assertTrue(all(row['checkpoints']['rows']==1 for row in result['runs']))
        self.assertEqual(before,self.hashes());self.assertNotIn('NEVER_',json.dumps(result,allow_nan=False))

    def test_dead_collector_is_rejected_despite_successful_result_file(self):
        self.telemetry(self.folder(),range(232));result=audit.audit_study(self.root)
        self.assertFalse(result['all_expected_live_runs_complete'])
        row=next(r for r in result['runs'] if r['run_directory']==str(self.folder()))
        self.assertIn('truncated_nominal_telemetry',row['issues']);self.assertEqual(row['telemetry']['last_s'],231)

    def test_exact_request_ids_schedule_classes_and_terminal_timings_are_required(self):
        folder=self.folder();data=[json.loads(line) for line in (folder/'requests.jsonl').read_text().splitlines()]
        data.pop();data.append(dict(data[0]));data[1]['cls']='wrong';data[2].pop('t_done');self.requests(folder,data)
        row=audit.audit_run(folder,self.cases[0],'glimmer_to_spark')
        self.assertFalse(row['complete']);self.assertIn('incomplete_or_changed_scheduled_outcomes',row['issues'])
        self.assertTrue(row['requests']['missing_ids']);self.assertTrue(row['requests']['duplicate_ids']);self.assertTrue(row['requests']['nonterminal_or_invalid_completion_ids'])

    def test_actual_late_completion_requires_telemetry_coverage_without_upper_time_cutoff(self):
        folder=self.folder();data=[json.loads(line) for line in (folder/'requests.jsonl').read_text().splitlines()]
        data[-1]['t_done']=980;data[-1]['latency_s']=980-data[-1]['t_sched'];self.requests(folder,data)
        self.assertIn('telemetry_ends_before_observed_request_drain',audit.audit_run(folder,self.cases[0],'glimmer_to_spark')['issues'])
        self.telemetry(folder,range(983));self.assertTrue(audit.audit_run(folder,self.cases[0],'glimmer_to_spark')['complete'])

    def test_collector_emfile_and_thread_trace_are_reported_without_raw_logs(self):
        log=self.root/'collector.stdout';log.write_text('Exception in thread servedoctor-recorder:\nOSError: [Errno 24] Too many open files: NEVER_EMIT_LOG_BODY\n')
        result=audit.audit_study(self.root,[log]);self.assertFalse(result['all_expected_live_runs_complete']);self.assertTrue(result['collector_errors_require_review'])
        self.assertGreater(result['collector_logs'][0]['emfile_matches'],0);self.assertNotIn('NEVER_',json.dumps(result))

    def test_journal_partial_or_duplicate_attempt_cannot_be_silently_accepted(self):
        path=self.folder()/'checkpoints.jsonl';path.write_text(path.read_text()+'{"unterminated":')
        self.assertIn('unterminated_final_jsonl',audit.audit_run(self.folder(),self.cases[0],'glimmer_to_spark')['issues'])
        duplicate=self.root/'live'/(self.ids[0]+'-glimmer_to_spark-second');duplicate.mkdir()
        result=audit.audit_study(self.root);self.assertFalse(result['all_expected_live_runs_complete']);self.assertEqual(len(result['duplicate_pairs']),1)

    def test_source_shed_zero_latency_remains_valid_and_impossible_timings_fail(self):
        folder=self.folder();data=[json.loads(line) for line in (folder/'requests.jsonl').read_text().splitlines()]
        data[0].update(status='shed',latency_s=0,t_done=data[0]['t_sched']+.02);self.requests(folder,data)
        self.assertTrue(audit.audit_run(folder,self.cases[0],'glimmer_to_spark')['complete'])
        data[1]['t_done']=data[1]['t_sched']-1;self.requests(folder,data)
        self.assertIn('incomplete_or_changed_scheduled_outcomes',audit.audit_run(folder,self.cases[0],'glimmer_to_spark')['issues'])

    def test_bound_schedule_change_and_mutating_final_file_cannot_pass(self):
        folder=self.folder();original=audit.rows;changed=False
        def rows(path):
            nonlocal changed
            result=original(path)
            if not changed:
                changed=True;path.write_bytes(path.read_bytes()+b'{"t":843}\n')
            return result
        with patch.object(audit,'rows',side_effect=rows):
            self.assertIn('public_files_changed_during_audit',audit.audit_run(folder,self.cases[0],'glimmer_to_spark')['issues'])
        put(self.root/'scenarios.json',{'scenarios':[{**case,'workload_seed':999} for case in self.cases]})
        with self.assertRaisesRegex(ValueError,'Frozen public'):audit.audit_study(self.root)

    def test_changed_journal_payload_and_public_slo_do_not_pass_by_timestamp_alone(self):
        folder=self.folder();path=folder/'checkpoints.jsonl';step=json.loads(path.read_text())
        step['decision']['raw_output']='different opaque content';path.write_text(json.dumps(step)+'\n')
        self.assertIn('checkpoint_journal_metadata_mismatch',audit.audit_run(folder,self.cases[0],'glimmer_to_spark')['issues'])
        public=audit.load(folder/'scenario_public.json');public['slo']['max_error_rate']=.5;put(folder/'scenario_public.json',public)
        self.assertIn('public_slo_binding_changed',audit.audit_run(folder,self.cases[0],'glimmer_to_spark')['issues'])

    def test_stage_collector_discovery_is_limited_to_the12_named_live_logs(self):
        ops=self.root/'ops';ops.mkdir()
        for mode in ('escalation','rules'):
            folder=ops/('sd-study-r2-api2-live-'+mode+'-fixture');folder.mkdir()
            for i,ident in enumerate(self.ids):
                (folder/(f'{i+1:02d}-'+ident+'-live.stdout')).write_text('public wrapper log\n')
            (folder/'unrelated.json').write_bytes(b'\xffNEVER_READ_UNRELATED')
        found=audit.discover_stage_logs(ops)
        self.assertEqual(len(found),12);self.assertEqual({arm for _,_,arm in found},set(audit.ARMS))


if __name__=='__main__':unittest.main()
