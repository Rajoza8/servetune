#!/usr/bin/env python3
"""Render only completed safe projections and financial proofs; no answer reads."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re

LABEL='ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)'
ARMS=('rules','glimmer','spark','wonder','glimmer_to_spark','glimmer_to_wonder')
IDS=tuple(f'hard-{n:02d}' for n in range(1,16))
FREEZE='868fa1c8c8be1bba186937839bdeba0bebeaab7f95623c181a72f42ba0120a68'
SOURCE='4b0add12be36cef0d0776607f683310b1641b0f7'


def require(v,s):
    if not v:raise ValueError(s)
def load(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def table(headers,rows):
    def cell(x):return ('—' if x is None else str(x)).replace('|','\\|').replace('\n',' ')
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join('---' for _ in headers)+' |',
        *['| '+' | '.join(cell(x) for x in row)+' |' for row in rows]])


def render(template,projection,cleanup,protocol,hardware,hardware_progress,prior,v0,failures,evaluation,optional):
    require(projection.get('label')==LABEL and projection.get('freeze_sha256')==FREEZE
        and projection.get('decision_coverage')=={'expected':90,'present':90},'Completed frozen90-cell projection required')
    rows=projection['per_case'];require(len(rows)==90 and {(r['id'],r['arm']) for r in rows}=={(i,a) for i in IDS for a in ARMS},'Exact15x6 coverage required')
    require(projection['valid_cases']+projection['invalid_cases']==15,'Immutable15-case validity required')
    require(protocol.get('source_commit')==SOURCE and protocol.get('label')==LABEL and protocol.get('excluded_ids')==['hard-16']
        and protocol.get('scientific_inputs_changed') is False,'Frozen partial operator protocol required')
    require(cleanup.get('confirmed_absent') is True and cleanup.get('stopped_confirmed') is True
        and cleanup.get('owned_work_quiescent') is True,'Confirmed finished rental required')
    cost=cleanup['gpu_accounting'];total=cost['total_usd_upper'];require(0<=total<=43,'GPU cap43 required')
    require(optional.get('status')=='not-run-budget-below-5' and 0<=43-total<5,'Optional live eligibility must be satisfied')
    require(failures.get('finalized') is True and failures.get('label')==LABEL,'Final failure index required')
    require(evaluation.get('completed') is True and evaluation.get('groups')==['rules-spark-wonder','glimmer-cascades']
        and not evaluation.get('failure') and not evaluation.get('cleanup_errors'),'Both evaluation groups required')
    finished=datetime.fromisoformat(evaluation['finished_at_utc']);require(finished<=datetime(2026,11,3,23,tzinfo=timezone.utc),'Hard cutoff exceeded')
    require(finished<=datetime(2026,11,4,4,59,59,tzinfo=timezone.utc),'Paid cutoff exceeded')
    gpu=[x.strip() for x in hardware_progress['gpu'].split(',')]
    require(len(gpu)==4 and gpu[0]==hardware['gpu_uuid'] and hardware_progress['vllm_version']==hardware['vllm_version'],'Hardware proofs differ')
    ledger=cleanup['ledger_summary'];require(ledger['caps_usd']=={'meta':50.,'baseten':20.} and not ledger['warnings'],'Native ledger caps/warnings differ')
    fields=('detected','false_alarms','diagnosis_correct','fix_proposed','complete_fix','compound_complete_fix','harmful','stopped_decoy','invalid_outputs','call_failures','median_time_to_detect_s','api_calls','api_cost_usd')
    titles=('Arm','Detected','False alarms','Diagnosis correct','Fix proposed','Complete fix','Compound complete fix','Harmful','Decoy stops','Invalid JSON','Failed calls','Median detection s','Model calls','API USD')
    def board(name):
        value=projection['scoreboards'][name]
        return table(titles,[[a,*[value[a][k] for k in fields]] for a in ARMS]) if value else 'No cases passed the predeclared validity rule; native valid-only scoreboard is empty.'
    den=projection['denominators'];by={(r['id'],r['arm']):r for r in rows}
    cases=[]
    for i in IDS:
        first=by[i,ARMS[0]]
        cases.append([i,first['valid'],first['compound'],first['has_decoy'],
            *['/'.join(str(int(by[i,a][k])) for k in ('diagnosis_correct','complete_fix','harmful','stopped_decoy')) for a in ARMS]])
    old_hard=prior['gpu_accounting']['hard_running_hours'];new_hours=cost['inference_host_cost']['running_hours'];hard_hours=old_hard+new_hours
    hours=v0['cost']['running_hours']+hard_hours
    accounting=f'{hours:.6f} total rental hours ({hard_hours:.6f} Hard hours, including failed allocations); ${total:.6f} total upper estimate of $43. Inference rental was stopped and deleted, confirmed by provider GET. All prior costs and network/slack reserves remain included. Final ledger SHA256 `{cleanup["canonical_ledger_sha256"]}`.'
    values={'INFERENCE_GPU_UUID':hardware['gpu_uuid'],'INFERENCE_DRIVER_AND_VLLM':gpu[3]+' / '+hardware['vllm_version'],
        'INFERENCE_PROTOCOL_SHA256':None,'VALID_CASES':projection['valid_cases'],'INVALID_CASES':projection['invalid_cases'],
        'FINAL_DECISION_COVERAGE':'90 of90 decisions: all six arms across the fifteen retained incidents',
        'ALL_SCOREBOARD':board('all'),'VALID_SCOREBOARD':board('valid_only'),
        'CATEGORY_DENOMINATORS':table(('Subset','Cases','Healthy controls','Nonhealthy cases','Compounds','Cases with decoys'),
            [[n,*[den[n][k] for k in ('cases','healthy_controls','nonhealthy_cases','compound_cases','decoy_cases')]] for n in ('all','valid_only')]),
        'PER_CASE_DFHX_TABLE':table(('Case','Valid','Compound','Has decoy',*ARMS),cases),
        'OPTIONAL_LIVE_STATUS':'not run; less than $5 of GPU budget remained',
        'FINAL_GPU_ACCOUNTING_AND_CLEANUP':accounting,
        'FINAL_LEDGER_SUMMARY':f'Meta ${ledger["accounted_usd"]["meta"]:.6f}/$50; Baseten ${ledger["accounted_usd"]["baseten"]:.6f}/$20; {ledger["calls"]} ledger records; no warnings. The original history was retained; the authoritative final GPU ledger is included byte-for-byte.',
        'PAID_CUTOFF_EVIDENCE':f'Both model groups and their final snapshots completed by `{evaluation["finished_at_utc"]}`, before the 18:00 Eastern analysis cutoff on November3 and23:59 Eastern paid-call cutoff on November3.',
        'PUBLICATION_COMMIT_OR_LATER_COMMIT_DISCLOSURE':'this README was written before its publication commit; the package commit is recorded in Git history. The experiment used the source commit above.'}
    return values


def main():
    a=argparse.ArgumentParser()
    for name in ('template','projection','cleanup','protocol','hardware','hardware-progress','prior','v0','failures','evaluation','optional','out'):a.add_argument('--'+name,required=True)
    args=a.parse_args();template=Path(args.template).read_text();values=render(template,*[load(getattr(args,n)) for n in ('projection','cleanup','protocol','hardware','hardware_progress','prior','v0','failures','evaluation','optional')])
    values['INFERENCE_PROTOCOL_SHA256']=sha(args.protocol)
    template='\n'.join(line for line in template.splitlines() if not line.startswith('**DRAFT —'))
    for k,value in values.items():template=template.replace('{{'+k+'}}',str(value))
    for before,after in [('original16','original 16'),('sixteen-case','sixteen-case'),('All15','All 15'),('all15','all 15'),('of15','of 15'),('contain90','contain 90'),('of90','of 90'),('to6RPS','to 6 RPS'),('used8192','used 8192'),('left2MiB','left 2 MiB'),('compound standalone KV values0.61632','compound standalone KV values 0.61632'),('with268/268','with 268/268'),('Blackwell96GB','Blackwell 96 GB'),('PRO6000','PRO 6000'),('Glimmer30B','Glimmer 30B'),('at$','at $'),('original$','original $'),('added$','added $'),('of$','of $'),('to3h','to 3 h'),('native50%','native 50%'),('existing443','existing 443'),('first18','first 18'),('subsequent21','subsequent 21'),('remain4b/868','remain 4b/868'),('fifteen-case','fifteen-case'),('on November3','on November 3'),('and23:59','and 23:59')]:template=template.replace(before,after)
    require(LABEL in template and not re.search(r'\{\{|\bDRAFT\b|\bPENDING\b|\bTODO\b|\bTBD\b',template,re.I),'Unfinished report text')
    with Path(args.out).open('x') as f:f.write(template+'\n')
    print(json.dumps({'written':args.out,'label':LABEL,'sha256':sha(args.out)}))
if __name__=='__main__':main()
