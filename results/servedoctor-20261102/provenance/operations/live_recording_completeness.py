#!/usr/bin/env python3
"""Local-only structural audit of six frozen escalation/rules live pairs.

No answers, ledger, network, model calls, scores or recovery targets. A failed
or rolled-back intervention with complete public capture remains usable.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys

OPS=Path(__file__).resolve().parent
REPO=OPS.parent.parent
sys.path.insert(0,str(REPO))
from servedoctor.scenarios import make_arrivals

STUDY='runs/sd-study-r2-api2'
DURATION_S=660
EXTRA_S=300
COVERAGE_SLACK_S=3.0  # Canonical1s interval+2s metrics scrape timeout.
TIMING_IDENTITY_SLACK_S=1e-6  # Floating subtraction only; never a latency target.
ARMS=('glimmer_to_spark','rules')
FILES=('scenario_public.json','live_result.json','telemetry.jsonl','requests.jsonl','checkpoints.jsonl')
NAME=re.compile(r'(inc-(?:0[1-9]|1[0-9]|2[0-4]))-(glimmer_to_spark|rules)(?:-[a-z0-9]+)?\Z')
EMFILE=re.compile(rb'Errno\s*24\b|\bEMFILE\b|too many open files',re.I)
COLLECTOR=re.compile(rb'Exception in thread servedoctor-recorder\b')


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def public_file(root,relative):
    parts=Path(relative)
    if parts.is_absolute() or '..' in parts.parts or 'answers' in parts.parts:raise ValueError('UntrustedPublicPath')
    path=root/parts
    if root.is_symlink() or any(root.joinpath(*parts.parts[:i]).is_symlink() for i in range(1,len(parts.parts)+1)):
        raise ValueError('SymlinkPublicEvidence')
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):raise ValueError('MissingPublicEvidence')
    return path


def load(path):return json.loads(Path(path).read_text())
def object_sha(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def numeric(value):return type(value) in (int,float) and math.isfinite(value) and value>=0
def error_class(value):return value if isinstance(value,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}',value) else 'UnrecognizedErrorClass'


def rows(path):
    lines=Path(path).read_bytes().splitlines(keepends=True)
    partial=bool(lines and not lines[-1].endswith(b'\n'))
    if partial:lines.pop()
    values=[json.loads(line) for line in lines]
    if any(not isinstance(value,dict) for value in values):raise ValueError('NonObjectPublicRow')
    return values,partial


def expected_requests(case):
    live_case=dict(case,duration_s=DURATION_S)
    # All three canonical prompt pools have48 entries. Only their length
    # affects the seeded arrival RNG; no prompt/question/answer text is read.
    pools={name:['public-placeholder']*48 for name in ('short','medium','long')}
    return {r['id']:(r['t'],r['cls']) for r in make_arrivals(live_case,pools)}


def log_evidence(path):
    data=Path(path).read_bytes()
    return {'path':str(path),'sha256':sha(path),'emfile_matches':len(EMFILE.findall(data)),
            'collector_thread_exception_matches':len(COLLECTOR.findall(data))}


def discover_stage_logs(ops=OPS):
    result=[]
    for folder in sorted(Path(ops).iterdir()):
        stage=re.fullmatch(r'sd-study-r2-api2-live-(escalation|rules)-[a-z0-9]+',folder.name)
        if not stage:continue
        if folder.is_symlink() or not folder.is_dir():raise ValueError('Untrusted stage-log directory')
        for path in sorted(folder.glob('[0-9][0-9]-inc-[0-9][0-9]-live.stdout')):
            name=re.fullmatch(r'[0-9]{2}-(inc-[0-9]{2})-live\.stdout',path.name)
            if path.is_symlink() or not path.is_file():raise ValueError('Untrusted stage collector log')
            result.append((path,name[1],'rules' if stage[1]=='rules' else 'glimmer_to_spark'))
    return result


def audit_run(folder,case,arm):
    row={'id':case['id'],'arm':arm,'run_directory':str(folder),'complete':False,'issues':[],'warnings':[],
         'expected_duration_s':DURATION_S,'coverage_slack_s':COVERAGE_SLACK_S,
         'acceptance_basis':'Structural public capture only; recovery, rollback, latency, error rates and model replies never select a run.'}
    try:
        files={name:public_file(folder,name) for name in FILES}
        row['public_files_sha256']={name:sha(path) for name,path in files.items()}
        public,result=load(files['scenario_public.json']),load(files['live_result.json'])
        if (case.get('duration_s')+EXTRA_S!=DURATION_S or public.get('duration_s')!=DURATION_S
                or public.get('id')!=case['id'] or public.get('arm')!=arm
                or result.get('id')!=case['id'] or result.get('arm')!=arm):row['issues'].append('identity_or_duration_binding_changed')
        if not isinstance(case.get('slo'),dict) or public.get('slo')!=case['slo']:row['issues'].append('public_slo_binding_changed')
        if result.get('failure'):row['issues'].append('canonical_runtime_failure');row['failure_class']=error_class(result['failure'])
        cleanup=result.get('cleanup_errors',[])
        if cleanup:row['issues'].append('canonical_cleanup_failure');row['cleanup_error_classes']=[error_class(e.get('error')) for e in cleanup if isinstance(e,dict)]
        telemetry,tpartial=rows(files['telemetry.jsonl']);requests,rpartial=rows(files['requests.jsonl']);checkpoints,cpartial=rows(files['checkpoints.jsonl'])
        if any((tpartial,rpartial,cpartial)):row['issues'].append('unterminated_final_jsonl')
        times=[r.get('t') for r in telemetry]
        if not times or any(not numeric(t) for t in times):
            row['issues'].append('missing_or_invalid_telemetry_times');times=[]
        gaps=[b-a for a,b in zip(times,times[1:])]
        first,last=(times[0],times[-1]) if times else (None,None)
        if first is None or first>COVERAGE_SLACK_S or last<DURATION_S-COVERAGE_SLACK_S:row['issues'].append('truncated_nominal_telemetry')
        if any(g<0 for g in gaps):row['issues'].append('backward_telemetry_time')
        if any(g==0 for g in gaps):row['warnings'].append('duplicate_rounded_telemetry_timestamp')
        if max(gaps,default=0)>COVERAGE_SLACK_S:row['issues'].append('internal_telemetry_gap_requires_resolution_review')
        emfile=sum(len(EMFILE.findall(str(line).encode())) for r in telemetry for line in r.get('log',[]))
        row['telemetry']={'rows':len(telemetry),'first_s':first,'last_s':last,'max_gap_s':max(gaps,default=None),
            'nominal660_seconds_covered':bool(times) and first<=COVERAGE_SLACK_S and last>=DURATION_S-COVERAGE_SLACK_S,
            'public_log_emfile_matches':emfile}
        if emfile:row['issues'].append('emfile_in_public_operational_log')
        expected=expected_requests(case);actual=Counter(r.get('id') for r in requests)
        missing=sorted(set(expected)-set(actual));extra=sorted(str(i) for i in set(actual)-set(expected));duplicates=sorted(str(i) for i,n in actual.items() if n!=1)
        mismatch=[r.get('id') for r in requests if r.get('id') in expected and (r.get('t_sched'),r.get('cls'))!=expected[r['id']]]
        invalid=[];status=Counter()
        for r in requests:
            terminal=isinstance(r.get('status'),str) and re.fullmatch(r'ok|shed|timeout|connection_error|error|http_[0-9]{3}',r['status']) is not None
            timing=all(numeric(r.get(k)) for k in ('t_sched','t_done','latency_s'))
            if timing:
                timing=(r['t_done']+TIMING_IDENTITY_SLACK_S>=r['t_sched'] and
                    (r['latency_s']==0 if r.get('status')=='shed' else
                     math.isclose(r['latency_s'],r['t_done']-r['t_sched'],rel_tol=0,abs_tol=TIMING_IDENTITY_SLACK_S)))
            if not terminal or not timing:invalid.append(str(r.get('id')))
            status[r['status'] if terminal else 'invalid_terminal_status']+=1
        if missing or extra or duplicates or mismatch or invalid:row['issues'].append('incomplete_or_changed_scheduled_outcomes')
        last_done=max((r['t_done'] for r in requests if numeric(r.get('t_done'))),default=None)
        covers=bool(times) and (last_done is None or last>=last_done-COVERAGE_SLACK_S)
        if not covers:row['issues'].append('telemetry_ends_before_observed_request_drain')
        row['requests']={'expected':len(expected),'observed':len(requests),'missing_ids':missing,'extra_ids':extra,'duplicate_ids':duplicates,
            'schedule_or_class_mismatch_ids':mismatch,'nonterminal_or_invalid_completion_ids':invalid,'status_counts':dict(status),
            'last_done_s':last_done,'telemetry_covers_observed_completions':covers,
            'configured_drain_wait_s':case.get('request_timeout_s',0)+10,
            'drain_basis':'Canonical request timeout+10s wait; coverage uses actual last completion with no upper-time or performance cutoff.',
            'timing_identity_slack_s':TIMING_IDENTITY_SLACK_S,
            'timing_basis':'Finite scheduled/completion times; non-shed latency equals completion minus schedule within floating precision. Shed latency is exactly0 by source.'}
        trail=result.get('trail')
        ct=[r.get('t') for r in checkpoints]
        # Opaque content commitments enforce the canonical writer invariant;
        # no decision/monitor/output/explanation field is interpreted or emitted.
        journal_hash,trail_hash=object_sha(checkpoints),object_sha(trail)
        journal_ok=(isinstance(trail,list) and len(trail)==len(checkpoints)>0 and all(numeric(t) for t in ct)
            and not any(b<a for a,b in zip(ct,ct[1:])) and journal_hash==trail_hash)
        if not journal_ok:row['issues'].append('checkpoint_journal_metadata_mismatch')
        row['checkpoints']={'rows':len(checkpoints),'result_trail_rows':len(trail) if isinstance(trail,list) else None,
            'metadata_consistent':journal_ok,'journal_content_sha256':journal_hash,'result_trail_content_sha256':trail_hash,
            'basis':'Opaque exact step equality; no requirement for22 calls or late checkpoints: acting stops further diagnosis in frozen live code.'}
        engine_logs=[]
        for path in sorted((folder/'engines').glob('*/engine.log')):
            clean=public_file(folder,path.relative_to(folder));entry=log_evidence(clean);engine_logs.append(entry)
        row['engine_log_evidence']=engine_logs
        if any(e['emfile_matches'] or e['collector_thread_exception_matches'] for e in engine_logs):row['issues'].append('engine_log_resource_or_collector_failure')
        if any(sha(path)!=row['public_files_sha256'][name] for name,path in files.items()):row['issues'].append('public_files_changed_during_audit')
        row['complete']=not row['issues']
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as error:
        row['issues'].append(error_class(type(error).__name__))
    return row


def audit_study(study,collector_logs=()):
    study=Path(study);selection=load(public_file(study,'dev-selected-escalation.json'))
    if selection.get('arm')!='glimmer_to_spark':raise ValueError('Fixed frozen Glimmer-to-Spark arm required')
    chosen=set(selection['live_ids'].values())
    cases={s['id']:s for s in load(public_file(study,'scenarios.json'))['scenarios'] if s['id'] in chosen}
    if len(chosen)!=6 or set(cases)!=chosen:raise ValueError('Exactly six frozen live IDs required')
    freeze_path=public_file(study,'experiment-freeze.json');freeze=load(freeze_path)
    public_inputs={STUDY+'/'+name:public_file(study,name) for name in ('scenarios.json','dev-selected-escalation.json')}
    public_inputs.update({name:public_file(REPO,name) for name in ('servedoctor/live.py','servedoctor/loadgen.py')})
    input_hashes={name:sha(path) for name,path in public_inputs.items()}
    if any(freeze.get('files_sha256',{}).get(name)!=digest for name,digest in input_hashes.items()):
        raise ValueError('Frozen public schedule/selection/live/loadgen binding differs')
    result={'schema_version':1,'created_at_utc':datetime.now(timezone.utc).isoformat(),'study_dir':str(study),
        'scope':'Live structural completeness only; no answers/scoring/latency/error-rate/recovery selection',
        'expected_runs':12,'expected_counts':{'glimmer_to_spark':6,'rules':6},'runs':[],'missing_pairs':[],
        'duplicate_pairs':[],'untrusted_paths':[],'collector_logs':[],'all_expected_live_runs_complete':False,
        'frozen_public_bindings_verified':True,'freeze_sha256':sha(freeze_path),'public_inputs_sha256':input_hashes,
        'internal_gap_policy':'Gaps above3s require resolution review; they do not prove collector death and never trigger retries or change canonical scores.'}
    found={};live=study/'live'
    if live.is_symlink():raise ValueError('Symlink live directory')
    for path in sorted(live.iterdir()) if live.exists() else []:
        match=NAME.fullmatch(path.name)
        if path.is_symlink() or not path.is_dir() or not match or match[1] not in chosen:
            result['untrusted_paths'].append(str(path));continue
        found.setdefault((match[1],match[2]),[]).append(path)
        result['runs'].append(audit_run(path,cases[match[1]],match[2]))
    for ident in sorted(chosen):
        for arm in ARMS:
            count=len(found.get((ident,arm),[]))
            if not count:result['missing_pairs'].append({'id':ident,'arm':arm})
            if count>1:result['duplicate_pairs'].append({'id':ident,'arm':arm,'attempts':count})
    for path in collector_logs:
        path=Path(path)
        if path.is_symlink() or not path.is_file() or 'answers' in path.parts:raise ValueError('Untrusted collector log')
        result['collector_logs'].append(log_evidence(path))
    errors=any(e['emfile_matches'] or e['collector_thread_exception_matches'] for e in result['collector_logs'])
    result['collector_errors_require_review']=errors
    result['complete_run_counts']=dict(Counter(r['arm'] for r in result['runs'] if r['complete']))
    result['all_expected_live_runs_complete']=(len(result['runs'])==12 and not any(result[k] for k in ('missing_pairs','duplicate_pairs','untrusted_paths'))
        and all(r['complete'] for r in result['runs']) and not errors)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--collector-log',type=Path,action='append',default=[])
    parser.add_argument('--include-stage-collector-logs',action='store_true',help='Require all12 exact local stage collector stdout logs, where key_runner merges remote stderr')
    parser.add_argument('--out',type=Path);args=parser.parse_args()
    discovered=discover_stage_logs() if args.include_stage_collector_logs else []
    args.collector_log=list(dict.fromkeys([*args.collector_log,*[row[0] for row in discovered]]))
    for path in args.collector_log:
        path=path.absolute()
        if not path.is_relative_to(OPS):parser.error('Only explicitly reviewed local OPS collector logs')
        parts=path.relative_to(OPS).parts
        if any(OPS.joinpath(*parts[:i]).is_symlink() for i in range(1,len(parts)+1)):parser.error('Symlink collector-log path')
    report=audit_study(REPO/STUDY,args.collector_log)
    if args.include_stage_collector_logs:
        pairs=Counter((ident,arm) for _,ident,arm in discovered)
        expected={(row['id'],row['arm']) for row in report['runs']}
        covered=len(discovered)==12 and len(pairs)==12 and set(pairs)==expected and all(count==1 for count in pairs.values())
        report['stage_collector_log_coverage']={'required':12,'observed':len(discovered),'exact_case_arm_coverage':covered}
        if not covered:report['all_expected_live_runs_complete']=False
    if args.out:
        path=args.out.absolute()
        if not path.is_relative_to(OPS) or path.exists() or path.is_symlink() or not path.parent.is_dir():parser.error('Use a fresh existing OPS JSON path')
        parts=path.relative_to(OPS).parts
        if any(OPS.joinpath(*parts[:i]).is_symlink() for i in range(1,len(parts))):parser.error('Symlink output parent')
        with path.open('x') as stream:json.dump(report,stream,indent=2,allow_nan=False);stream.write('\n')
        print(json.dumps({'report':str(path),'sha256':sha(path),'all_expected_live_runs_complete':report['all_expected_live_runs_complete']}))
    else:print(json.dumps(report,indent=2,allow_nan=False))


if __name__=='__main__':main()
