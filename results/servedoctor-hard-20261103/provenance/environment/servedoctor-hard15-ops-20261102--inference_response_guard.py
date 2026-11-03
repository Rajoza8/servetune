"""Hard result-completeness/usage check; never filters diagnosis or JSON quality.

Transport/call failures remain recorded. A failed group is reported for review,
never retried or removed. This helper reads no answer keys and calls no models.
"""
import argparse
import json
from pathlib import Path

from inference_report_common import LABEL, PROJECT, ARMS, approved_root, evaluation_gate, hard_ids, load, sha, write_new


def successful_usage(usage):
    return (isinstance(usage, dict) and type(usage.get('prompt_tokens')) is int
            and type(usage.get('completion_tokens')) is int
            and usage['prompt_tokens'] > 0 and usage['completion_tokens'] >= 0)


def complete_results(root, arms):
    root = Path(root)
    ids = hard_ids(root)
    if not arms or len(set(arms)) != len(arms) or set(arms) - set(ARMS):
        raise ValueError('Use distinct frozen arms')
    results = {}
    for arm in arms:
        rows = []
        for name in ids:
            folder = root / 'decisions' / arm
            if (folder / (name + '.partial.json')).exists() or (folder / (name + '.partial.tmp')).exists():
                raise ValueError('Partial evaluation remains; retain it and stop')
            path = folder / (name + '.json')
            item = load(path)
            trail = item.get('trail')
            if (item.get('arm') != arm or item.get('incident') != name or item.get('incomplete')
                    or not isinstance(trail, list) or not trail
                    or item.get('checkpoints') != len(trail)):
                raise ValueError('Final evaluation metadata is incomplete')
            duration = load(root / 'incidents' / name / 'recording.json')['duration_s']
            if [step.get('t') for step in trail] != list(range(30, 30 * (len(trail) + 1), 30)):
                raise ValueError('Checkpoint journal spacing differs')
            if trail[-1]['t'] > duration or (item.get('final') is None and trail[-1]['t'] + 30 <= duration):
                raise ValueError('Evaluation stopped without a final decision or full journal')
            failures = sum(bool(step.get('error') or (step.get('decision') or {}).get('call_failed')
                                or (step.get('monitor') or {}).get('call_failed')) for step in trail)
            responses = sum(successful_usage((step.get('decision') or {}).get('usage'))
                            + successful_usage((step.get('monitor') or {}).get('usage')) for step in trail)
            rows.append({'id': name, 'call_failures': failures, 'successful_responses': responses,
                         'checkpoints': len(trail), 'decision_sha256': sha(path)})
        results[arm] = rows
    return results


def audit_model_group(root, arms):
    groups = complete_results(root, arms)
    output = {}
    for arm, rows in groups.items():
        failures = sum(row['call_failures'] for row in rows)
        total = sum(row['successful_responses'] for row in rows)
        direct = arm in ('glimmer', 'spark', 'wonder')
        complete = arm == 'rules' or total > 0 or failures > 0
        if direct:
            complete = complete and all(row['successful_responses'] > 0 or row['call_failures'] > 0 for row in rows)
        output[arm] = {'incidents': len(rows), 'call_failures': failures,
                       'successful_responses': total, 'ready_for_next_group': complete,
                       'failed_calls_preserved_as_measured_results': True,
                       'incidents_with_successful_response': sum(row['successful_responses'] > 0 for row in rows),
                       'per_incident': rows}
    return {'project': PROJECT, 'label': LABEL, 'split': 'hard', 'by_arm': output,
            'ready_for_next_group': all(row['ready_for_next_group'] for row in output.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study-dir', default='runs/sd-hard-partial-attempt1')
    parser.add_argument('--arms', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    root = approved_root(args.study_dir)
    proof = evaluation_gate(root)
    result = audit_model_group(root, args.arms.split(','))
    result.update(validation=proof, helper_sha256=sha(__file__))
    write_new(args.out, result)
    print(json.dumps(result), flush=True)
    return 0 if result['ready_for_next_group'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
