#!/usr/bin/env python3
"""Trusted canonical-score projection for a completed Hard study.

Only this program/scorer reads sealed labels and runtime metadata. The emitted
JSON contains numeric scoreboards, boolean category reductions and per-case
metrics; it excludes truth, variant, root causes, actions, PIDs and model text.
Do not print or feed native report.json/answer files to any model prompt.
No model, ledger or GPU operation is performed.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from servedoctor.scoring import score_study
from inference_report_common import LABEL, PROJECT, ARMS, IDS, approved_root, evaluation_gate, load, sha, write_new
from inference_response_guard import complete_results

BOARD_FIELDS = ('incidents', 'healthy_controls', 'detected', 'false_alarms', 'healthy_false_alarms',
                'diagnosis_correct', 'fix_proposed', 'complete_fix', 'compound_incidents',
                'compound_complete_fix', 'harmful', 'stopped_decoy', 'median_time_to_detect_s',
                'invalid_outputs', 'call_failures', 'api_calls', 'api_cost_usd')
BOOL_FIELDS = ('flagged', 'false_alarm', 'detected', 'diagnosis_correct', 'fix_proposed',
               'complete_fix', 'harmful', 'stopped_decoy')
NUMBER_FIELDS = ('flag_t', 'time_to_detect_s', 'checkpoints', 'escalations', 'invalid_outputs',
                 'call_failures', 'api_calls', 'api_cost_usd')


def number(value):
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
        raise ValueError('Invalid canonical numeric metric')
    return value


def boards(value):
    if set(value) - set(ARMS):
        raise ValueError('Unknown arm in canonical scoreboard')
    return {arm: {key: number(item[key]) for key in BOARD_FIELDS} for arm, item in value.items()}


def project(all_scores, valid_scores, valid_ids, decoy_ids):
    """Pure projection; tests inject invented scorer dictionaries, never answers."""
    valid_ids, decoy_ids = set(valid_ids), set(decoy_ids)
    if valid_ids - set(IDS) or decoy_ids - set(IDS):
        raise ValueError('Unexpected metadata IDs')
    all_rows, valid_rows = all_scores['rows'], valid_scores['rows']
    expected = {(arm, case) for arm in ARMS for case in IDS}
    pairs = [(row['arm'], row['incident']) for row in all_rows]
    valid_pairs = [(row['arm'], row['incident']) for row in valid_rows]
    if len(pairs) != 90 or set(pairs) != expected:
        raise ValueError('Exactly ninety final retained arm/case scores required')
    if (len(valid_pairs) != len(valid_ids) * len(ARMS)
            or set(valid_pairs) != {(arm, case) for arm in ARMS for case in valid_ids}):
        raise ValueError('Valid-only score coverage differs from immutable verdicts')
    by_pair = {(row['arm'], row['incident']): row for row in all_rows}
    if any(row != by_pair[(row['arm'], row['incident'])] for row in valid_rows):
        raise ValueError('Valid-only scorer changed a retained row')
    categories = {}
    per_case = []
    for row in sorted(all_rows, key=lambda row: (row['incident'], ARMS.index(row['arm']))):
        case, arm = row['incident'], row['arm']
        if row.get('split') != 'hard' or any(type(row[key]) is not bool for key in BOOL_FIELDS):
            raise ValueError('Invalid canonical case metadata')
        category = {'healthy_control': row['truth'] == 'healthy',
                    'compound': len(row.get('root_causes', [])) > 1,
                    'has_decoy': case in decoy_ids}
        if case in categories and category != categories[case]:
            raise ValueError('Case categories differ between arms')
        categories[case] = category
        per_case.append({'arm': arm, 'id': case, 'valid': case in valid_ids, **category,
                         **{key: row[key] for key in BOOL_FIELDS},
                         **{key: number(row[key]) for key in NUMBER_FIELDS}})

    def counts(subset):
        return {'cases': len(subset), 'healthy_controls': sum(categories[c]['healthy_control'] for c in subset),
                'nonhealthy_cases': sum(not categories[c]['healthy_control'] for c in subset),
                'compound_cases': sum(categories[c]['compound'] for c in subset),
                'decoy_cases': sum(categories[c]['has_decoy'] for c in subset)}

    all_board, valid_board = boards(all_scores['by_arm']), boards(valid_scores['by_arm'])
    if set(all_board) != set(ARMS) or set(valid_board) != (set(ARMS) if valid_ids else set()):
        raise ValueError('Canonical scoreboard arms are incomplete')
    return {'project': PROJECT, 'label': LABEL, 'split': 'hard',
            'scoreboards': {'all': all_board, 'valid_only': valid_board},
            'denominators': {'all': counts(IDS), 'valid_only': counts(valid_ids)},
            'valid_cases': len(valid_ids), 'invalid_cases': len(IDS) - len(valid_ids),
            'per_case': per_case, 'decision_coverage': {'expected': 90, 'present': len(pairs)},
            'interpretation': ['The fifteen retained frozen incidents are evaluated; hard-16 could not start and is excluded before validation and model calls. Validity only changes the reported subset.',
                               'A compound fix_proposed may address one cause; complete_fix requires both safely.',
                               'Nonhealthy includes underutilization, matching the canonical scorer denominator.',
                               'Zero valid cases produces the canonical empty valid-only scoreboard.']}


def export(root):
    root = Path(root)
    proof = evaluation_gate(root)
    complete = complete_results(root, ARMS)  # Includes failed calls as measured outcomes.
    validity = load(root / 'answers/validity.json')
    valid_ids = {row['id'] for row in validity['incidents'] if row['valid']}
    decoy_ids = {case for case in IDS if load(root / 'answers/runtime' / (case + '.json')).get('decoy_pids')}
    result = project(score_study(root, split='hard'), score_study(root, split='hard', valid_only=True),
                     valid_ids, decoy_ids)
    result.update(created_at_utc=datetime.now(timezone.utc).isoformat(), validation=proof,
                  freeze_sha256=sha(root / 'hard-experiment-freeze.json'),
                  validity_sha256=sha(root / 'answers/validity.json'), helper_sha256=sha(__file__),
                  final_decisions_sha256={arm: {row['id']: row['decision_sha256'] for row in rows}
                                         for arm, rows in complete.items()})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study-dir', default='runs/sd-hard-partial-attempt1')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    result = export(approved_root(args.study_dir))
    write_new(args.out, result)
    # stdout is only a safe summary, never native scorer rows or model replies.
    print(json.dumps({key: result[key] for key in ('project', 'label', 'scoreboards', 'denominators', 'decision_coverage')}))


if __name__ == '__main__':
    main()
