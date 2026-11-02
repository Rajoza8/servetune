#!/usr/bin/env python3
"""Predeclared descriptive live windows, separate from canonical scores/recovery."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

OPS = Path(__file__).resolve().parent
REPO = OPS.parent.parent
STUDY = 'runs/sd-study-r2-api2'
PLAN = OPS / 'live-window-reporting-plan.json'
ARMS = ['rules', 'glimmer', 'spark', 'wonder', 'glimmer_to_spark', 'glimmer_to_wonder']
CHANGE_TYPES = {'set_engine_config', 'gateway_rate_limit', 'gateway_max_prompt_tokens', 'stop_gpu_process'}
ACTION_KEYS = {'set_engine_config': ['knob', 'value'], 'gateway_rate_limit': ['max_rps'],
               'gateway_max_prompt_tokens': ['max_prompt_tokens'], 'stop_gpu_process': ['pid'],
               'no_action': [], 'recommend_consolidation': [], 'escalate_to_human': []}
KNOBS = {'max_model_len', 'max_num_seqs', 'max_num_batched_tokens', 'gpu_memory_utilization'}


def load(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def numeric(value): return type(value) in (int, float) and math.isfinite(value)
def utc(): return datetime.now(timezone.utc).isoformat()


def write_new(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False); stream.write('\n')


def public_onset(case, base):
    sources = []
    if any(case['engine'].get(k) != base.get(k) for k in base): sources.append((0.0, 'public engine differs from base at deployment'))
    if case.get('contention'): sources.append((float(case['contention']['onset_s']), 'public contention onset_s'))
    phases = case.get('schedule', [])
    if len(phases) > 1: sources.append((min(float(p['start_s']) for p in phases[1:]), 'first later public workload schedule phase'))
    if len(sources) != 1: raise ValueError('Expected exactly one unambiguous public intervention onset')
    return {'onset_s': sources[0][0], 'derivation': sources[0][1]}


def create_plan(repo=REPO, ops=OPS, helper=Path(__file__).resolve()):
    root = repo / STUDY; cases = load(root / 'scenarios.json')['scenarios']; selection = load(root / 'dev-selected-escalation.json')
    freeze = load(root / 'experiment-freeze.json'); study = load(root / 'study.json')
    if (root / 'live').exists() and any((root / 'live').iterdir()): raise ValueError('Plan must precede all live evidence')
    if any((root / 'decisions' / arm / (s['id'] + suffix)).exists() for arm in ARMS for s in cases if s['split'] == 'test' for suffix in ['.json', '.partial.json']):
        raise ValueError('Plan must precede all test evaluation')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    if commit != freeze['git_commit']: raise ValueError('Frozen source commit differs')
    selected = set(selection['live_ids'].values())
    chosen = {s['id']: {**public_onset(s, study['engine_base']), 'slo': s['slo']} for s in cases if s['id'] in selected}
    if len(chosen) != 6: raise ValueError('Six frozen selected public scenarios required')
    paths = [root / name for name in ['study.json', 'scenarios.json', 'dev-selected-escalation.json', 'experiment-freeze.json']]
    paths += [repo / 'servedoctor/live.py', repo / 'servedoctor/loadgen.py', helper]
    result = {'schema_version': 1, 'created_at_utc': utc(), 'source_commit': commit, 'study_dir': STUDY,
        'selected_arm': selection['arm'], 'cases': chosen,
        'files_sha256': {p.relative_to(repo).as_posix(): sha(p) for p in paths},
        'scope': 'Descriptive public live evidence only. Never used for arm selection, canonical scoring/recovery, prompts, thresholds or answer keys.',
        'window_rules': {'pre': '[max(public_onset_s, triggering_checkpoint_t - 60), triggering_checkpoint_t)',
                         'post': '[action_completion_s + 30, action_completion_s + 90)',
                         'request_membership': 'start <= t_sched < end; final persisted public requests only',
                         'empty_or_reversed': 'Zero rows and inconclusive; do not substitute another window.'},
        'metric_rules': {'N_and_offered': 'Count persisted request outcomes in the window; do not infer unpersisted arrivals.',
            'ok': 'status == ok', 'shed': 'status == shed', 'failed': 'status not in {ok,shed}',
            'admitted': 'N - shed', 'error_rate': 'failed/admitted if admitted>0, else0 (source convention; counts disclosed)',
            'shed_rate': 'shed/N if N>0, else0', 'p95_latency_s': 'Linear interpolation at (n-1)*.95 over successful latency_s only; measured from scheduled arrival, including queueing.',
            'latency_error_target_met': 'N>0, ok>0, p95<=existing slo.p95_latency_s, error_rate<=existing slo.max_error_rate; empty window is null.',
            'full_configured_target_met': 'latency_error_target_met plus shed_rate<=existing slo.max_shed_rate; no new threshold.'},
        'interpretation_rules': ['No action/change, missing canonical verification, failed/partial evidence: inconclusive.',
            'Pre-onset trigger, action start or action completion: report explicitly; do not claim restoration.',
            'Both pre and post latency/error targets met: restoration not demonstrated.',
            'Pre miss/post meet: temporal improvement only, not causal proof.',
            'Canonical recovered ignores shed cap; retain unchanged alongside descriptive full configured target.'],
        'canonical_disclosures': {'fault_window_before_action': 'onset through action completion; includes API/action/restart time',
            'after_action': 'action completion through live duration; may include rollback',
            'post_fix_window': 'stored lagged60s online window; exact bounds not persisted; not assumed identical to descriptive post window',
            'time_to_recover_s': 'onset-relative end of first passing retrospective30s window scanned every10s, conditional on canonical recovery; not time since repair'},
        'restart_classification': 'Match ordered knob/value restart entries to attempted forward set_engine_config actions, then reverse previous-value rollback actions. Unmatched entries stay unclassified. Show all seconds separately.'}
    write_new(ops / PLAN.name, result)
    return result


def read_requests(path):
    if path.is_symlink(): raise ValueError('Symlink public request evidence')
    lines = path.read_bytes().splitlines(keepends=True); partial = bool(lines and not lines[-1].endswith(b'\n'))
    if partial: lines.pop()
    rows = [json.loads(line) for line in lines]
    if any(not isinstance(r, dict) for r in rows): raise ValueError('Non-object completed public evidence row')
    return rows, partial


def p95(values):
    if not values: return None
    values = sorted(values); position = (len(values)-1)*.95; lo, hi = math.floor(position), math.ceil(position)
    return values[lo] + (values[hi]-values[lo])*(position-lo)


def window(requests, start, end, slo):
    rows = [r for r in requests if numeric(r.get('t_sched')) and start <= r['t_sched'] < end]
    ok = [r for r in rows if r.get('status') == 'ok']; shed = sum(r.get('status') == 'shed' for r in rows)
    if any(not numeric(r.get('latency_s')) for r in ok): raise ValueError('Successful request missing finite latency')
    failed = len(rows)-len(ok)-shed; admitted = len(rows)-shed
    latency = p95([r['latency_s'] for r in ok]); error = failed/admitted if admitted else 0.0
    shed_rate = shed/len(rows) if rows else 0.0
    target = bool(ok) and latency <= slo['p95_latency_s'] and error <= slo['max_error_rate'] if rows else None
    return {'start_s': start, 'end_s': end, 'length_s': max(0.0, end-start), 'N': len(rows), 'offered': len(rows),
        'ok': len(ok), 'failed': failed, 'shed': shed, 'admitted': admitted, 'p95_latency_s': latency,
        'error_rate': error, 'shed_rate': shed_rate, 'latency_error_target_met': target,
        'full_configured_target_met': target and shed_rate <= slo['max_shed_rate'] if target is not None else None,
        'count_basis': 'persisted request outcomes by scheduled arrival; no missing arrivals inferred'}


def clean_action(item):
    action = item.get('action', {}); kind = action.get('type')
    if kind not in ACTION_KEYS: raise ValueError('Unknown public executed action type')
    result = {'type': kind, 'status': str(item.get('status', '')).split(':', 1)[0]}
    if result['status'] not in {'executed', 'failed', 'rejected', 'refused'}: raise ValueError('Unknown public action status')
    if result['status'] == 'failed' and ': ' in item['status']: result['error_class'] = safe_error(item['status'].split(': ', 1)[1])
    for key in ACTION_KEYS[kind]:
        value = action.get(key)
        if key == 'knob':
            if value not in KNOBS: raise ValueError('Unknown public executed engine knob')
        elif not numeric(value): raise ValueError('Invalid numeric public action')
        result[key] = value
    return result


def restarts(result):
    forward = [item['action'] for item in result['executed'] if item.get('action', {}).get('type') == 'set_engine_config'
               and str(item.get('status', '')).split(':', 1)[0] in {'executed', 'failed'}]
    rollback = [{'knob': next(iter(item['previous'])), 'value': next(iter(item['previous'].values()))}
                for item in reversed(result['executed']) if item.get('action', {}).get('type') == 'set_engine_config'
                and item.get('previous') and str(item.get('status', '')).split(':', 1)[0] in {'executed', 'failed'}]
    entries = []; totals = {'forward': 0.0, 'rollback': 0.0, 'unclassified': 0.0}
    for item in result.get('engine_restarts', []):
        phase = 'unclassified'
        for label, pending in [('forward', forward), ('rollback', rollback)]:
            if pending and item.get('knob') == pending[0]['knob'] and item.get('value') == pending[0]['value']:
                phase = label; pending.pop(0); break
        if item.get('knob') not in KNOBS or not numeric(item.get('value')) or not numeric(item.get('seconds')):
            raise ValueError('Invalid public restart evidence')
        entry = {k: item[k] for k in ['knob', 'value', 'status', 'seconds']}
        entry['phase'] = phase
        if item.get('error'): entry['error_class'] = safe_error(item['error'])
        entries.append(entry); totals[phase] += item['seconds']
    return {'entries': entries, 'seconds': totals}


def safe_error(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', value) else 'UnrecognizedErrorClass'


def audit_run(folder, case, repo=REPO):
    if folder.is_symlink(): raise ValueError('Symlink public live directory')
    result_path = folder / 'live_result.json'; checkpoints_path = folder / 'checkpoints.jsonl'; request_path = folder / 'requests.jsonl'
    if any(p.is_symlink() for p in [result_path, checkpoints_path, request_path, folder / 'scenario_public.json']): raise ValueError('Symlink public live file')
    result = load(result_path); public = load(folder / 'scenario_public.json')
    if result['id'] != public['id'] or result['arm'] != public['arm'] or public['slo'] != case['slo']: raise ValueError('Public live identity/SLO changed')
    checkpoints, checkpoint_partial = read_requests(checkpoints_path); requests, request_partial = read_requests(request_path)
    trigger = next((row['t'] for row in checkpoints if row.get('decision', {}).get('incident') is True), None)
    if trigger is not None and not numeric(trigger): raise ValueError('Invalid triggering checkpoint time')
    action = result.get('acted_at_s'); action = action if numeric(action) else None
    onset = case['onset_s']; slo = case['slo']
    pre = window(requests, max(onset, trigger-60), trigger, slo) if trigger is not None else None
    post = window(requests, action+30, action+90, slo) if action is not None else None
    executed = [clean_action(item) for item in result.get('executed', [])]
    actual_change = any(item['type'] in CHANGE_TYPES and item['status'] == 'executed' for item in executed)
    starts = [(datetime.fromisoformat(item['at'])-datetime.fromisoformat(public['started_at'])).total_seconds()
              for item in result.get('executed', []) if item.get('at')]
    runtime_errors = sorted({safe_error(item['error']) for item in result.get('cleanup_errors', []) if item.get('error')}
                    | ({safe_error(result['failure'])} if result.get('failure') else set()))
    call_errors = sorted({safe_error(item['error']) for row in checkpoints
                          for item in [row, row.get('monitor', {}), row.get('decision', {})]
                          if isinstance(item, dict) and item.get('error')})
    action_errors = sorted({item['error_class'] for item in executed if item.get('error_class')})
    flags = {'trigger_pre_onset': trigger < onset if trigger is not None else None,
             'action_start_pre_onset_approximate': min(starts) < onset if starts else None,
             'action_completion_pre_onset': action < onset if action is not None else None,
             'no_executed_change': not actual_change, 'canonical_verification_missing': result.get('recovered') is None,
             'partial_jsonl': checkpoint_partial or request_partial,
             'both_latency_error_windows_met': bool(pre and post and pre['latency_error_target_met'] is True and post['latency_error_target_met'] is True),
             'post_shedding_exceeds_configured_cap': bool(post and post['shed_rate'] > slo['max_shed_rate'])}
    inconclusive = (not actual_change or action is None or result.get('recovered') is None or bool(runtime_errors)
                    or flags['partial_jsonl'] or not pre or not post or not pre['N'] or not post['N'])
    if inconclusive: interpretation = 'Inconclusive descriptive restoration comparison; see flags and unchanged canonical outcomes.'
    elif any(flags[k] for k in ['trigger_pre_onset', 'action_start_pre_onset_approximate', 'action_completion_pre_onset']):
        interpretation = 'Pre-onset trigger or intervention; restoration from the later fault is not established.'
    elif flags['both_latency_error_windows_met']: interpretation = 'Latency/error target met before and after; restoration not demonstrated.'
    elif post['latency_error_target_met'] is True: interpretation = 'Latency/error target attained in the post window after a pre-window miss; temporal association only, not causal proof.'
    else: interpretation = 'Post window misses the latency/error target.'
    canonical = {key: result.get(key) for key in ['recovered', 'rolled_back', 'time_to_recover_s', 'acted_at_s',
                   'fault_window_before_action', 'after_action', 'post_fix_window', 'failure', 'failure_stage', 'cleanup_errors']}
    return {'id': result['id'], 'arm': result['arm'], 'run_directory': folder.relative_to(repo).as_posix(),
        'anchors': {'public_onset_s': onset, 'triggering_checkpoint_s': trigger, 'action_completion_s': action,
                    'action_starts_s_approximate': starts, 'action_start_basis': 'executed.at minus scenario_public.started_at; t0 offset is not persisted'},
        'slo': slo, 'pre': pre, 'post': post, 'canonical': canonical, 'executed': executed, 'restarts': restarts(result),
        'error_classes': {'runtime': runtime_errors, 'calls': call_errors, 'actions': action_errors},
        'flags': flags, 'inconclusive': inconclusive, 'interpretation': interpretation,
        'public_files_sha256': {p.name: sha(p) for p in [result_path, checkpoints_path, request_path, folder / 'scenario_public.json']}}


def report(repo=REPO, ops=OPS):
    path = ops / PLAN.name; plan = load(path)
    for relative, expected in plan['files_sha256'].items():
        if sha(repo / relative) != expected: raise ValueError('Predeclared public inputs or reporting helper changed')
    root = repo / STUDY; rows = []; unavailable = []
    for folder in sorted((root / 'live').iterdir()) if (root / 'live').exists() else []:
        if not folder.is_dir() or folder.is_symlink(): raise ValueError('Unexpected public live path')
        match = re.fullmatch(r'(inc-[0-9]{2})-(glimmer_to_spark|glimmer_to_wonder|rules)(?:-[a-z0-9]+)?', folder.name)
        if not match or match[1] not in plan['cases'] or match[2] not in ['rules', plan['selected_arm']]: raise ValueError('Unreviewed live run directory')
        if not all((folder / name).is_file() for name in ['live_result.json', 'checkpoints.jsonl', 'requests.jsonl', 'scenario_public.json']):
            unavailable.append({'run_directory': folder.relative_to(repo).as_posix(), 'status': 'missing final public evidence; inconclusive'}); continue
        audited = audit_run(folder, plan['cases'][match[1]], repo)
        if audited['id'] != match[1] or audited['arm'] != match[2]: raise ValueError('Live path/result identity mismatch')
        rows.append(audited)
    return {'schema_version': 1, 'generated_at_utc': utc(), 'study_dir': STUDY, 'plan_sha256': sha(path),
        'plan_created_at_utc': plan['created_at_utc'], 'scope': plan['scope'], 'canonical_disclosures': plan['canonical_disclosures'],
        'runs': rows, 'unavailable_runs': unavailable,
        'run_counts': dict(Counter(row['arm'] for row in rows)),
        'limits': 'Descriptive matched cases, not causal inference. Canonical flags/metrics unchanged. N/offered count persisted outcomes; missing arrivals are not inferred. No model text or answers read.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--create-plan', action='store_true')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.create_plan:
        if args.out: parser.error('Plan path is fixed; omit --out')
        create_plan(); print(json.dumps({'plan': str(PLAN), 'sha256': sha(PLAN)})); return
    if args.out is None: parser.error('Request an explicit new OPS report with --out')
    out = args.out.absolute()
    if out.exists() or not out.is_relative_to(OPS) or out.suffix != '.json' or not out.parent.is_dir() or any(p.is_symlink() for p in [out, *out.parents] if p.is_relative_to(OPS)):
        parser.error('Use a fresh JSON output under the existing private OPS directory')
    result = report(); write_new(out, result)
    print(json.dumps({'report': str(out), 'sha256': sha(out), 'runs': len(result['runs'])}))


if __name__ == '__main__': main()
