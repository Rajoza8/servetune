#!/usr/bin/env python3
"""Offline CPU token counts for all Hard observations; no inference or paid calls.

Run after immutable validation and before any paid evaluation. Output contains
counts/hashes only, never prompts. A context miss blocks the stage for review.
"""
import argparse
from collections.abc import Mapping
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from servedoctor.llm import diagnose_system, MONITOR_SYSTEM
from servedoctor.observe import load_incident, normal_profile, observe, render
from inference_report_common import LABEL, PROJECT, approved_root, evaluation_gate, hard_ids, load, sha, write_new

REV = 'cec94fcfd6512f2cfe708138c32533b346ea4f69'
CONTEXT = 8192


def input_count(tokenizer, system, user):
    result = tokenizer.apply_chat_template(
        [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
        tokenize=True, add_generation_prompt=True, reasoning_strength='low')
    ids = result['input_ids'] if isinstance(result, Mapping) else result
    if ids and isinstance(ids[0], list):
        if len(ids) != 1:
            raise ValueError('Unexpected tokenizer batch size')
        ids = ids[0]
    return len(ids)


def measure(root, tokenizer):
    root = Path(root)
    ids = hard_ids(root)
    if load(root / 'study.json')['timing']['checkpoint_s'] != 30:
        raise ValueError('Frozen checkpoint spacing differs')
    manifests = {}

    def sealed(name):
        folder = root / 'incidents' / name
        manifest = load(folder / 'manifest.json')['files']
        if any(sha(folder / name) != digest for name, digest in manifest.items()):
            raise ValueError('Public recording seal differs')
        if load(folder / 'engine_identity.json')['model_revision'] != REV:
            raise ValueError('Recorded model revision differs')
        incident = load_incident(folder)
        if incident['recording']['status'] != 'completed':
            raise ValueError('Completed recording required')
        manifests[name] = sha(folder / 'manifest.json')
        return incident

    reference = sealed('reference')
    profile = normal_profile(reference['telemetry'])
    prompts = [('diagnosis', diagnose_system(), 2048), ('monitor', MONITOR_SYSTEM, 600)]
    maximum, per_incident, checkpoints = {}, {}, 0
    for name in ids:
        incident, peaks = sealed(name), {}
        duration = incident['recording']['duration_s']
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 30:
            raise ValueError('Invalid recorded duration')
        for now in range(30, int(duration) + 1, 30):
            user = render(observe(incident, now, profile=profile,
                                  reference_config=reference['engine_config']))
            checkpoints += 1
            for kind, system, output_budget in prompts:
                count = input_count(tokenizer, system, user)
                entry = {'incident': name, 'checkpoint_s': now, 'input_tokens': count,
                         'output_budget_tokens': output_budget, 'total_tokens': count + output_budget}
                if kind not in peaks or entry['total_tokens'] > peaks[kind]['total_tokens']:
                    peaks[kind] = entry
                if kind not in maximum or entry['total_tokens'] > maximum[kind]['total_tokens']:
                    maximum[kind] = entry
        per_incident[name] = peaks
    return {'project': PROJECT, 'label': LABEL, 'split': 'hard', 'study_dir': str(root),
            'model_revision': REV, 'context_tokens': CONTEXT, 'incidents': len(ids),
            'checkpoints': checkpoints, 'maximum': maximum, 'per_incident_maximum': per_incident,
            'public_manifests_sha256': manifests,
            'method': 'offline CPU apply_chat_template; reasoning_strength=low; add_generation_prompt=True',
            'fits_8192': all(item['total_tokens'] <= CONTEXT for item in maximum.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study-dir', default='runs/sd-hard-partial-attempt1')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    root = approved_root(args.study_dir)
    proof = evaluation_gate(root)
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained('meta-models/Muse-Glimmer-30B', revision=REV,
                                               local_files_only=True)
    result = measure(root, tokenizer)
    result.update(validation=proof, freeze_sha256=sha(root / 'hard-experiment-freeze.json'),
                  helper_sha256=sha(__file__))
    write_new(args.out, result)
    print(json.dumps(result), flush=True)
    return 0 if result['fits_8192'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
