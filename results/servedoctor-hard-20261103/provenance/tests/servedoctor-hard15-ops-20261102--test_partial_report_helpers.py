"""Invented CPU/file fixtures only. Never opens a real study, answer or ledger."""
from collections import UserDict
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import export_hard_scores as scores
from hard_report_common import ARMS, IDS, FROZEN_IDS, LABEL, approved_root, hard_ids, sha, write_new
import measure_contexts as contexts
import model_response_guard as responses
from servedoctor.scoring import aggregate


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve()
        self.root = self.repo / 'runs/sd-hard-partial-attempt1'
        put(self.root / 'scenarios.json', {'scenarios': [{'id': name, 'split': 'hard'} for name in FROZEN_IDS]})
        put(self.root / 'study.json', {'timing': {'checkpoint_s': 30}})

    def recordings(self):
        for name in ('reference',) + IDS:
            folder = self.root / 'incidents' / name
            put(folder / 'recording.json', {'status': 'completed', 'duration_s': 60})
            put(folder / 'engine_identity.json', {'model_revision': contexts.REV})
            put(folder / 'manifest.json', {'files': {filename: sha(folder / filename)
                                                    for filename in ('recording.json', 'engine_identity.json')}})

    def decisions(self, arms=ARMS):
        self.recordings()
        for arm in arms:
            for name in IDS:
                step = {'decision': {'incident': False, 'valid_output': False,
                                     'usage': {'prompt_tokens': 2, 'completion_tokens': 0}}}
                trail = [{**copy.deepcopy(step), 't': now} for now in (30, 60)]
                put(self.root / 'decisions' / arm / (name + '.json'),
                    {'arm': arm, 'incident': name, 'checkpoints': 2, 'trail': trail, 'final': None})


class ContextContracts(Fixtures):
    def test_path_and_id_guards(self):
        self.assertEqual(approved_root('runs/sd-hard-partial-attempt1', self.repo), self.root)
        with self.assertRaises(ValueError):approved_root('runs/sd-hard-partial-attempt2', self.repo)
        for bad in ('runs/sd-study-r2-api2', 'runs/sd-hard-dev', 'runs/sd-hard-attempt0', '../runs/sd-hard'):
            with self.assertRaises(ValueError):
                approved_root(bad, self.repo)
        self.assertEqual(hard_ids(self.root), IDS)
        value = json.loads((self.root / 'scenarios.json').read_text())
        value['scenarios'][-1]['id'] = IDS[0]
        put(self.root / 'scenarios.json', value)
        with self.assertRaises(ValueError):
            hard_ids(self.root)

    def test_batchencoding_and_template_arguments(self):
        class Tokenizer:
            def apply_chat_template(this, messages, **kwargs):
                self.assertEqual(messages, [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'u'}])
                self.assertEqual(kwargs, {'tokenize': True, 'add_generation_prompt': True, 'reasoning_strength': 'low'})
                return UserDict(input_ids=[[1, 2, 3]])
        self.assertEqual(contexts.input_count(Tokenizer(), 's', 'u'), 3)

    def test_scans_all_checkpoints_unchanged_caps_and_counts_only(self):
        self.recordings()
        class Tokenizer:
            def apply_chat_template(this, messages, **kwargs):
                value = json.loads(messages[-1]['content'])
                return {'input_ids': [0] * (6100 + int(value['id'][-2:]) + value['t'])}
        def incident(path):
            return {'id': path.name, 'telemetry': [], 'engine_config': {},
                    'recording': {'status': 'completed', 'duration_s': 60}}
        with patch.object(contexts, 'load_incident', incident), patch.object(contexts, 'normal_profile', return_value={}), \
             patch.object(contexts, 'observe', side_effect=lambda item, now, **kw: {'id': item['id'], 't': now}), \
             patch.object(contexts, 'render', side_effect=json.dumps):
            value = contexts.measure(self.root, Tokenizer())
        self.assertEqual((value['incidents'], value['checkpoints']), (15, 30))
        self.assertEqual(value['maximum']['diagnosis']['total_tokens'], 6100 + 15 + 60 + 2048)
        self.assertEqual(value['maximum']['monitor']['output_budget_tokens'], 600)
        self.assertFalse(value['fits_8192'])
        self.assertEqual(value['maximum']['diagnosis']['incident'], 'hard-15')
        self.assertNotIn('6100', json.dumps(value))
        self.assertNotIn('content', json.dumps(value))

    def test_tampered_seal_blocks_before_tokenizer(self):
        self.recordings()
        put(self.root / 'incidents/reference/recording.json', {'status': 'completed', 'duration_s': 90})
        with self.assertRaises(ValueError):
            contexts.measure(self.root, None)

    def test_outputs_exclusive(self):
        target = self.repo / 'new.json'
        write_new(target, {'value': 1})
        with self.assertRaises(FileExistsError):
            write_new(target, {'value': 2})
        self.assertEqual(json.loads(target.read_text()), {'value': 1})


class ResponseContracts(Fixtures):
    def test_invalid_json_with_real_usage_is_a_measured_result(self):
        self.decisions(['spark'])
        value = responses.audit_model_group(self.root, ['spark'])
        self.assertTrue(value['ready_for_next_group'])
        self.assertEqual(value['by_arm']['spark']['successful_responses'], 30)

    def test_recorded_call_failure_stops_next_group_without_deleting(self):
        self.decisions(['spark'])
        path = self.root / 'decisions/spark/hard-03.json'
        value = json.loads(path.read_text())
        value['trail'][0].update(error='TimeoutError')
        put(path, value)
        digest = sha(path)
        report = responses.audit_model_group(self.root, ['spark'])
        self.assertFalse(report['ready_for_next_group'])
        self.assertEqual(report['by_arm']['spark']['call_failures'], 1)
        self.assertEqual(sha(path), digest)

    def test_monitor_only_healthy_cascade_is_valid(self):
        self.decisions(['glimmer_to_wonder'])
        for name in IDS:
            path = self.root / 'decisions/glimmer_to_wonder' / (name + '.json')
            value = json.loads(path.read_text())
            for step in value['trail']:
                step['monitor'] = step.pop('decision')
                step['decision'] = {'incident': False}
            put(path, value)
        self.assertTrue(responses.audit_model_group(self.root, ['glimmer_to_wonder'])['ready_for_next_group'])

    def test_no_usage_and_incomplete_journal_rejected(self):
        self.decisions(['spark'])
        path = self.root / 'decisions/spark/hard-01.json'
        value = json.loads(path.read_text())
        for step in value['trail']:
            step['decision'].pop('usage')
        put(path, value)
        self.assertFalse(responses.audit_model_group(self.root, ['spark'])['ready_for_next_group'])
        value['trail'].pop()
        value['checkpoints'] = 1
        put(path, value)
        with self.assertRaises(ValueError):
            responses.audit_model_group(self.root, ['spark'])

    def test_partial_preserved_and_rules_need_no_usage(self):
        self.decisions(['rules'])
        for name in IDS:
            path = self.root / 'decisions/rules' / (name + '.json')
            value = json.loads(path.read_text())
            for step in value['trail']:
                step['decision'].pop('usage')
            put(path, value)
        self.assertTrue(responses.audit_model_group(self.root, ['rules'])['ready_for_next_group'])
        path = self.root / 'decisions/rules/hard-01.partial.json'
        put(path, {'incomplete': True})
        with self.assertRaises(ValueError):
            responses.audit_model_group(self.root, ['rules'])
        self.assertTrue(path.exists())


class ScoreProjectionContracts(unittest.TestCase):
    def fixture(self, valid_ids=IDS[:8]):
        rows = []
        for arm in ARMS:
            for index, case in enumerate(IDS):
                healthy = index < 3
                row = {'arm': arm, 'incident': case, 'split': 'hard',
                       'truth': 'healthy' if healthy else 'PRIVATE_FAULT_LABEL',
                       'variant': 'PRIVATE_VARIANT', 'actions': [{'secret': 'PRIVATE_MODEL_TEXT'}],
                       'flagged': not healthy, 'false_alarm': False, 'detected': not healthy,
                       'diagnosis_correct': True, 'fix_proposed': True, 'complete_fix': index != 4,
                       'harmful': False, 'stopped_decoy': index == 8, 'flag_t': None if healthy else 30,
                       'time_to_detect_s': None if healthy else 0, 'checkpoints': 1, 'escalations': 0,
                       'invalid_outputs': 0, 'call_failures': 0, 'api_calls': 1, 'api_cost_usd': .01}
                if 3 <= index < 7:
                    row['root_causes'] = ['PRIVATE_CAUSE_A', 'PRIVATE_CAUSE_B']
                rows.append(row)
        valid = [row for row in rows if row['incident'] in valid_ids]
        return {'rows': rows, 'by_arm': aggregate(rows)}, {'rows': valid, 'by_arm': aggregate(valid)}

    def test_projection_all_valid_compound_decoy_and_no_raw_labels(self):
        all_scores, valid_scores = self.fixture()
        value = scores.project(all_scores, valid_scores, IDS[:8], IDS[7:13])
        self.assertEqual(value['scoreboards'], {'all': all_scores['by_arm'], 'valid_only': valid_scores['by_arm']})
        self.assertEqual(value['denominators']['all'], {'cases': 15, 'healthy_controls': 3,
                         'nonhealthy_cases': 12, 'compound_cases': 4, 'decoy_cases': 6})
        self.assertEqual(value['denominators']['valid_only']['decoy_cases'], 1)
        self.assertEqual(len(value['per_case']), 90)
        self.assertEqual(value['label'],LABEL)
        self.assertNotIn('PRIVATE_', json.dumps(value))
        for forbidden in ('truth', 'variant', 'root_causes', 'actions', 'predicted', 'raw_output'):
            self.assertNotIn(forbidden, value['per_case'][0])

    def test_no_valid_cases_preserves_empty_canonical_board(self):
        all_scores, valid_scores = self.fixture(())
        value = scores.project(all_scores, valid_scores, (), ())
        self.assertEqual(value['scoreboards']['valid_only'], {})
        self.assertEqual(value['denominators']['valid_only']['cases'], 0)

    def test_missing_duplicate_and_changed_valid_rows_rejected(self):
        all_scores, valid_scores = self.fixture()
        bad = copy.deepcopy(all_scores)
        bad['rows'][-1] = bad['rows'][0]
        with self.assertRaises(ValueError):
            scores.project(bad, valid_scores, IDS[:8], ())
        bad_valid = copy.deepcopy(valid_scores)
        bad_valid['rows'][0]['fix_proposed'] = False
        with self.assertRaises(ValueError):
            scores.project(all_scores, bad_valid, IDS[:8], ())

    def test_string_payload_in_numeric_metric_rejected(self):
        all_scores, valid_scores = self.fixture(())
        all_scores['rows'][0]['api_cost_usd'] = 'PRIVATE_VALUE'
        with self.assertRaisesRegex(ValueError, '^Invalid canonical numeric metric$'):
            scores.project(all_scores, valid_scores, (), ())


if __name__ == '__main__':
    unittest.main()
