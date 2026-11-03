"""Invented numeric projections only; no study/answer/model/GPU reads."""
import copy
import unittest

import render_partial_readme as r


def fixture():
    board = {a: {k: 0 for k in ('incidents', 'detected', 'diagnosis_correct', 'fix_proposed',
             'complete_fix', 'compound_complete_fix', 'compound_incidents', 'harmful', 'stopped_decoy')}
             for a in r.ARMS}
    for row in board.values():
        row['incidents'] = 15
    counts = {'cases': 15, 'healthy_controls': 0, 'nonhealthy_cases': 15,
              'compound_cases': 0, 'decoy_cases': 0}
    projection = {'project': r.PROJECT, 'label': r.LABEL, 'freeze_sha256': r.FREEZE,
        'decision_coverage': {'expected': 90, 'present': 90}, 'valid_cases': 15, 'invalid_cases': 0,
        'scoreboards': {'all': board, 'valid_only': copy.deepcopy(board)},
        'denominators': {'all': counts, 'valid_only': copy.deepcopy(counts)},
        'per_case': [{'id': i, 'arm': a, 'valid': True, 'compound': False, 'has_decoy': False,
                     'diagnosis_correct': False, 'complete_fix': False, 'harmful': False,
                     'stopped_decoy': False} for i in r.IDS for a in r.ARMS]}
    cleanup = {'confirmed_absent': True, 'gpu_accounting': {
        'total_usd_upper': 39, 'hard_running_hours': 1, 'prior_v0_usd_upper': 25,
        'hard_compute_usd_upper': 5, 'hard_disk_usd_upper': 1, 'new_network_reserve_usd': 4,
        'new_slack_reserve_usd': 1}, 'ledger_summary': {'caps_usd': {'meta': 50.0, 'baseten': 20.0},
        'accounted_usd': {'meta': 12, 'baseten': 0}, 'calls': 443, 'warnings': []}}
    failures = {'project': r.PROJECT, 'finalized': True, 'failures': []}
    hardware = {'driver_version': 'invented-driver', 'vllm_version': 'invented-vllm'}
    prices = {'verified_at_utc': '2026-11-02T23:00:00Z'}
    protocol = {'project': r.PROJECT, 'label': r.LABEL, 'source_commit': r.HEAD,
        'included_hard_ids': list(r.IDS), 'excluded_ids': ['hard-16'], 'scientific_inputs_changed': False,
        'original_freeze': {'sha256': r.FREEZE}, 'exclusion': {'sha256': r.EXCLUSION}}
    return [projection, cleanup, failures, hardware, prices, protocol, 'not-run-budget-below-5']


class ReportingText(unittest.TestCase):
    def test_exact_label_fifteen_rows_ninety_cells_and_no_live_claim(self):
        text = r.render(*fixture())
        self.assertTrue(text.startswith('# '+r.LABEL+'\n'))
        self.assertEqual(sum(line.startswith('| hard-') for line in text.splitlines()), 15)
        self.assertIn('There are90 arm/case cells', text)
        self.assertIn('not live recovery measurements', text)
        self.assertIn('analysis/analysis-report.html', text)
        self.assertIn('hard-16 could not start', text)
        self.assertIn('original16-case attempt', text)

    def test_incomplete_full16_or_unfinalized_inputs_cannot_render(self):
        for change in ('coverage', 'cleanup', 'failures', 'protocol'):
            values = fixture()
            if change == 'coverage': values[0]['decision_coverage'] = {'expected': 96, 'present': 96}
            if change == 'cleanup': values[1]['confirmed_absent'] = False
            if change == 'failures': values[2]['finalized'] = False
            if change == 'protocol': values[5]['excluded_ids'] = []
            with self.subTest(change=change), self.assertRaises(ValueError): r.render(*values)

    def test_zero_valid_cases_preserves_empty_canonical_scoreboard(self):
        values = fixture(); projection = values[0]
        projection.update(valid_cases=0, invalid_cases=15)
        projection['scoreboards']['valid_only'] = {}
        projection['denominators']['valid_only'] = {k: 0 for k in projection['denominators']['all']}
        for row in projection['per_case']: row['valid'] = False
        text = r.render(*values)
        self.assertIn('empty: no retained case passed validity', text)


if __name__ == '__main__':
    unittest.main()
