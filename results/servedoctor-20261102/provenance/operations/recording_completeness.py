#!/usr/bin/env python3
"""Public recording integrity/coverage audit, independent of latency or fault scores."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from servedoctor.scenarios import make_arrivals

INTERVAL_S = 1.0
METRICS_TIMEOUT_S = 2.0
COVERAGE_SLACK_S = INTERVAL_S + METRICS_TIMEOUT_S
DRAIN_TIMEOUT_S = 90.0
EMFILE = re.compile(rb'Errno\s*24\b|\bEMFILE\b|too many open files', re.IGNORECASE)


def load(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    if path.is_symlink(): raise ValueError('Symlink public evidence')
    lines = path.read_bytes().splitlines(keepends=True); partial = bool(lines and not lines[-1].endswith(b'\n'))
    if partial: lines.pop()
    values = [json.loads(line) for line in lines]
    if any(not isinstance(v, dict) for v in values): raise ValueError('Non-object public row')
    return values, partial


def expected_arrivals(case):
    # Canonical pools have48 items/class after load_questions requires>=100.
    # Choice consumes RNG by pool length, never by prompt content/length.
    pools = {name: ['public-placeholder']*48 for name in ['short','medium','long']}
    return {r['id']: (r['t'], r['cls']) for r in make_arrivals(case, pools)}


def log_errors(path):
    data = path.read_bytes()
    return {'path': str(path), 'sha256': sha(path), 'emfile_matches': len(EMFILE.findall(data))}


def audit_incident(root, case):
    folder = root / 'incidents' / case['id']; duration = case['duration_s']
    result = {'id': case['id'], 'duration_s': duration, 'status_in_recording': None,
        'expected_nominal_and_max_drain_end_s': [duration, duration+DRAIN_TIMEOUT_S],
        'coverage_slack_s': COVERAGE_SLACK_S, 'coverage_slack_basis': 'source1s sampling interval plus2s metrics scrape timeout; operational resolution only',
        'complete': False, 'issues': [], 'warnings': []}
    if folder.is_symlink() or not folder.is_dir(): result['issues'].append('recording_directory_missing_or_untrusted'); return result
    files = ['recording.json', 'telemetry.jsonl', 'requests.jsonl', 'manifest.json']
    missing = [name for name in files if not (folder/name).is_file() or (folder/name).is_symlink()]
    if missing: result['issues'].append('missing_final_public_files'); result['missing_files'] = missing; return result
    try:
        recording = load(folder/'recording.json'); result['status_in_recording'] = recording.get('status')
        manifest = load(folder/'manifest.json')['files']
        present = {p.name for p in folder.iterdir() if p.is_file() and p.name != 'manifest.json'}
        sealed = present == set(manifest) and all(not (folder/name).is_symlink() and sha(folder/name)==digest for name,digest in manifest.items())
        result['sealed'] = sealed; result['manifest_sha256'] = sha(folder/'manifest.json')
        if not sealed: result['issues'].append('seal_mismatch')
        telemetry, tpartial = rows(folder/'telemetry.jsonl'); requests, rpartial = rows(folder/'requests.jsonl')
        if tpartial or rpartial: result['issues'].append('unterminated_final_jsonl')
        times = [row['t'] for row in telemetry]
        gaps = [b-a for a,b in zip(times,times[1:])]
        source_errors = Counter()
        emfile = 0
        for row in telemetry:
            for source, field in [('vllm','scrape_error'),('gpu','sample_error')]:
                if row.get(source,{}).get(field): source_errors[source+':'+str(row[source][field])] += 1
            emfile += sum(len(EMFILE.findall(str(line).encode())) for line in row.get('log',[]))
        first, last = (times[0],times[-1]) if times else (None,None)
        largest = max(gaps,default=None)
        nominal = bool(times) and first <= COVERAGE_SLACK_S and last >= duration-COVERAGE_SLACK_S
        result['telemetry'] = {'rows': len(times), 'metadata_rows': recording.get('telemetry_rows'),
            'first_s': first, 'last_s': last, 'max_gap_s': largest,
            'leading_gap_s': first, 'trailing_nominal_gap_s': max(0,duration-last) if times else duration,
            'observed_drain_s': max(0,last-duration) if times else 0,
            'nominal_duration_covered': nominal, 'source_error_counts': dict(source_errors),
            'metadata_errors': recording.get('telemetry_errors'), 'operational_log_emfile_matches': emfile}
        if not nominal: result['issues'].append('truncated_nominal_telemetry')
        if any(gap<0 for gap in gaps): result['issues'].append('backward_telemetry_time')
        if any(gap==0 for gap in gaps): result['warnings'].append('duplicate_rounded_telemetry_timestamp')
        if recording.get('telemetry_rows') != len(times): result['issues'].append('telemetry_metadata_count_mismatch')
        result['requires_resolution_review'] = largest is not None and largest > COVERAGE_SLACK_S
        if result['requires_resolution_review']: result['warnings'].append('internal_telemetry_gap_exceeds_source_resolution_budget')
        if emfile: result['issues'].append('emfile_in_public_operational_log')
        expected = expected_arrivals(case); actual = Counter(r['id'] for r in requests)
        missing_ids = sorted(set(expected)-set(actual)); extra_ids = sorted(set(actual)-set(expected))
        duplicates = sorted(name for name,count in actual.items() if count!=1)
        mismatched = sorted(r['id'] for r in requests if r['id'] in expected and (r.get('t_sched'),r.get('cls'))!=expected[r['id']])
        statuses = Counter(r.get('status','missing') for r in requests)
        error_classes = Counter(str(r['error_class']) for r in requests if r.get('error_class'))
        last_done = max((r['t_done'] for r in requests if isinstance(r.get('t_done'),(int,float))),default=None)
        invalid_rows=[]
        for r in requests:
            terminal=isinstance(r.get('status'),str) and re.fullmatch(r'ok|shed|timeout|connection_error|error|http_[0-9]{3}',r['status']) is not None
            timing=all(type(r.get(k)) in (int,float) and math.isfinite(r[k]) and r[k]>=0 for k in ['t_done','latency_s'])
            if not terminal or not timing: invalid_rows.append(r['id'])
        outcomes_complete = not(missing_ids or extra_ids or duplicates or mismatched or invalid_rows)
        result['outcomes'] = {'expected': len(expected), 'observed': len(requests), 'complete': outcomes_complete,
            'missing_ids': missing_ids, 'extra_ids': extra_ids, 'duplicate_ids': duplicates, 'schedule_or_class_mismatch_ids': mismatched,
            'nonterminal_or_invalid_completion_ids': invalid_rows,
            'status_counts': dict(statuses), 'error_class_counts': dict(error_classes), 'last_done_s': last_done,
            'last_scheduled_s': max((r['t_sched'] for r in requests),default=None),
            'telemetry_covers_observed_completions': bool(times) and (last_done is None or last >= min(last_done,duration+DRAIN_TIMEOUT_S)-COVERAGE_SLACK_S)}
        if not outcomes_complete: result['issues'].append('incomplete_or_changed_request_outcomes')
        if not result['outcomes']['telemetry_covers_observed_completions']: result['issues'].append('telemetry_ends_before_observed_drain')
        if recording.get('status') != 'completed' or recording.get('failure'): result['issues'].append('canonical_recording_failed')
        result['complete'] = not result['issues'] and not result['requires_resolution_review']
    except (OSError,ValueError,KeyError,TypeError) as exc:
        result['issues'].append(type(exc).__name__)
    return result


def audit_study(root, collector_logs=()):
    cases = load(root/'scenarios.json')['scenarios']
    present = [s for s in cases if (root/'incidents'/s['id']).exists()]
    results = [audit_incident(root,s) for s in present]
    logs = [log_errors(path) for path in collector_logs]
    for path in sorted((root/'engines').glob('*/engine.log')) if (root/'engines').exists() else []:
        if path.is_symlink(): raise ValueError('Symlink engine evidence')
        item = log_errors(path)
        if item['emfile_matches']: logs.append(item)
    return {'schema_version': 1, 'created_at_utc': datetime.now(timezone.utc).isoformat(), 'study_dir': str(root),
        'scope': 'Public integrity, collector coverage and exact scheduled outcome completeness only; never selects by fault performance or model scores.',
        'present_incidents': len(results), 'all_present_recordings_complete': all(r['complete'] for r in results),
        'expected_incidents': len(cases), 'missing_incident_ids': [s['id'] for s in cases if not (root/'incidents'/s['id']).exists()],
        'all_expected_recordings_complete': len(results)==len(cases) and all(r['complete'] for r in results),
        'recordings': results, 'source_log_error_evidence': logs,
        'source_log_errors_require_review': any(item['emfile_matches'] for item in logs),
        'future_source_fix_needed': 'Recorder thread exceptions must propagate to recording failure after cleanup; currently a completed status can coexist with a dead collector. Do not modify frozen source during this study.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study-dir', type=Path, default=Path('runs/sd-study-r2-api2'))
    parser.add_argument('--collector-log', type=Path, action='append', default=[])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); root = (REPO/args.study_dir).resolve(); out = args.out.absolute()
    if not root.is_relative_to(REPO/'runs') or 'answers' in root.parts: parser.error('Use an approved runs study root')
    if not out.is_relative_to(Path(__file__).resolve().parent) or out.exists(): parser.error('Use a fresh private OPS report path')
    for path in args.collector_log:
        if path.is_symlink() or not path.resolve().is_relative_to(Path(__file__).resolve().parent): parser.error('Only reviewed OPS collector logs')
    report = audit_study(root,args.collector_log)
    with out.open('x') as stream: json.dump(report,stream,indent=2); stream.write('\n')
    print(json.dumps({'report': str(out), 'sha256': sha(out), 'incidents': report['present_incidents'],
        'all_present_recordings_complete': report['all_present_recordings_complete'],
        'all_expected_recordings_complete': report['all_expected_recordings_complete'],
        'missing_incident_count': len(report['missing_incident_ids']),
        'source_log_errors_require_review': report['source_log_errors_require_review']}))


if __name__ == '__main__': main()
