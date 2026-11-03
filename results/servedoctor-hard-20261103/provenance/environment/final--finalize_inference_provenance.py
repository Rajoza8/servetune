#!/usr/bin/env python3
"""Finalize publication metadata locally after the completed inference cleanup.

Only operator JSON and the safe score projection are parsed. Other artifacts,
including any explicit native artifacts, are hashed/scanned opaquely. This does
not call native scoring/validation, providers, models, or alter ledger bytes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

OPS=Path(__file__).resolve().parent
REPO=OPS.parent.parent
PROJECT='servedoctor-hard15-20261102'
LABEL='ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)'
FREEZE='868fa1c8c8be1bba186937839bdeba0bebeaab7f95623c181a72f42ba0120a68'
SCOPE='7da4c657be8e5e6bf971e5e017a24b02385d6c0f3221daa20ae64e7eb7cedce7'
FLAT_SHA='4b74c1b135c49e4d4ba174e4fc947419e3136d32dbbe39dbcdb0581c60ec0f7c'
FAILURE_SHA='c1bb7bd8006a36fcde4e326406d09f0b51e81959dc8853bc1ec7c3c0758be488'
PACKAGE_SHA='c98b3fc35f111ce4b852d04dfd362687e5b37aa230c7a2165438f1ef8b8386fc'
ARMS={'rules','spark','wonder','glimmer','glimmer_to_spark','glimmer_to_wonder'}
IDS={f'hard-{n:02d}' for n in range(1,16)}
GROUPS={'calibration','kv-refinement','configuration','environment','api-prices','api-access','rental-history','failures','tests','finalization'}


def require(value, message):
    if not value: raise ValueError(message)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def load(path): return json.loads(Path(path).read_text())
def descriptor(path): return {'path':str(Path(path).resolve()),'sha256':sha(path)}
def write_new(path,value):
    with path.open('x') as f: json.dump(value,f,indent=2,allow_nan=False); f.write('\n')


def package_scanner():
    path=OPS/'package_inference_results.py'
    require(sha(path)==PACKAGE_SHA,'Reviewed package scanner source differs')
    sys.path.insert(0,str(OPS))
    spec=importlib.util.spec_from_file_location('_publication_scan',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.scan


def regular(value,repo):
    path=Path(value)
    require(path.is_absolute() and '..' not in path.parts,'Absolute in-repository artifact required')
    path=Path(path.absolute());require(path.is_relative_to(repo),'Artifact outside repository')
    require(all(not repo.joinpath(*path.relative_to(repo).parts[:i]).is_symlink()
                for i in range(1,len(path.relative_to(repo).parts)+1)),'Linked artifact refused')
    require(path.is_file(),'Missing regular artifact')
    return path


def completion(args,repo):
    paths={n:regular(getattr(args,n),repo) for n in ('projection','evaluation','cleanup','ledger','ledger_sync_receipt')}
    projection,evaluation,cleanup=[load(paths[n]) for n in ('projection','evaluation','cleanup')]
    require(projection.get('project')==PROJECT and projection.get('label')==LABEL
            and projection.get('freeze_sha256')==FREEZE
            and projection.get('decision_coverage')=={'expected':90,'present':90},'Final safe90 projection required')
    rows=projection.get('per_case',[])
    require(len(rows)==90 and {(r.get('id'),r.get('arm')) for r in rows}=={(i,a) for i in IDS for a in ARMS},'Exact15x6 final coverage required')
    valid,invalid=projection.get('valid_cases'),projection.get('invalid_cases')
    require(type(valid) is int and type(invalid) is int and valid>=0 and invalid>=0 and valid+invalid==15,'Actual15-case validity required')
    require(projection.get('denominators',{}).get('all',{}).get('cases')==15
            and projection.get('denominators',{}).get('valid_only',{}).get('cases')==valid,'All/valid denominators differ')
    require(evaluation.get('project')==PROJECT and evaluation.get('label')==LABEL
            and evaluation.get('completed') is True and evaluation.get('groups')==['rules-spark-wonder','glimmer-cascades']
            and not evaluation.get('failure') and not evaluation.get('cleanup_errors'),'Completed two-group evaluation required')
    finished=datetime.fromisoformat(evaluation['finished_at_utc'])
    require(finished.tzinfo is not None and finished<=datetime(2026,11,3,23,tzinfo=timezone.utc),'Hard analysis cutoff exceeded')
    require(cleanup.get('project')=='servedoctor-hard15-inference-20261103'
            and cleanup.get('analysis_project')==PROJECT and cleanup.get('label')==LABEL
            and cleanup.get('original_freeze_sha256')==FREEZE
            and cleanup.get('instance_id')==58905385 and cleanup.get('rental_scope_sha256')==SCOPE
            and all(cleanup.get(n) is True for n in ('confirmed_absent','stopped_confirmed','owned_work_quiescent')),'Confirmed scoped final cleanup required')
    cost=cleanup.get('gpu_accounting',{})
    total=cost.get('total_usd_upper')
    require(type(total) in (int,float) and math.isfinite(total) and 0<=total<=43 and cost.get('total_cap_usd')==43,'Final all-host cap43 required')
    summary=cleanup.get('ledger_summary',{})
    require(summary.get('caps_usd')=={'meta':50.0,'baseten':20.0} and not summary.get('warnings'),'Native API caps/warning stop differ')
    digest=sha(paths['ledger']);sync=load(paths['ledger_sync_receipt'])
    require(cleanup.get('canonical_ledger_sha256')==cleanup.get('remote_ledger_sha256')==digest,'Authoritative final ledger differs')
    require(sync.get('project')==PROJECT and sync.get('label')==LABEL
            and sync.get('canonical_ledger_sha256')==sync.get('remote_ledger_sha256')==digest
            and sync.get('seed_prefix_unchanged') is True and sync.get('verified') is True
            and sync.get('already_synchronized') is True and sync.get('inherited_prefix_entries')==443
            and sync.get('final_sha256')==digest and sync.get('source')==descriptor(paths['ledger'])
            and sync.get('cleanup')==descriptor(paths['cleanup']),'Exact final ledger-sync receipt required')
    return paths,{'valid_cases':valid,'invalid_cases':invalid,'final_decisions':90,'gpu_total_usd_upper':total,'canonical_ledger_sha256':digest}


def finalize(args,*,repo=REPO,scanner=None):
    repo=Path(repo).resolve();ops=repo/'runs/servedoctor-hard15-ops-20261102'
    flat_path=regular(args.draft,repo);failure_path=regular(args.failures,repo)
    require(sha(flat_path)==FLAT_SHA and sha(failure_path)==FAILURE_SHA,'Reviewed243/29 drafts differ')
    flat,failure=load(flat_path),load(failure_path)
    require(flat.get('project')==failure.get('project')==PROJECT and flat.get('label')==failure.get('label')==LABEL
            and len(flat.get('files',[]))==243 and len(failure.get('failures',[]))==29 and failure.get('finalized') is False,'Exact unfinalized draft schema required')
    require(flat.get('failure_index')==descriptor(failure_path),'Draft failure-index pointer differs')
    for field,count in [('original_failure_index',18),('prior_partial_failure_index',21),('prior_inference_failure_index',28)]:
        item=failure[field];path=regular(item['path'],repo)
        require(sha(path)==item['sha256'] and failure['failures'][:count]==load(path)['failures'],'Historical failure prefix differs')
    paths,summary=completion(args,repo)
    additions=load(regular(args.additions,repo))
    require(additions.get('project')==PROJECT and additions.get('label')==LABEL
            and isinstance(additions.get('files'),list) and isinstance(additions.get('failures',[]),list),'Explicit additions schema required')
    scan=scanner or package_scanner();files=list(flat['files']);seen={};destinations=set()
    def check(row):
        source=row.get('source',{});path=regular(source.get('path',''),repo)
        require(re.fullmatch('[a-f0-9]{64}',source.get('sha256','')) and sha(path)==source['sha256'],'Selected descriptor SHA differs')
        scan(path);dest=Path(row.get('destination',''))
        require(row.get('group') in GROUPS and not dest.is_absolute() and '..' not in dest.parts
                and dest.parts and dest.parts[0]=='provenance','Unsafe selected group/destination')
        require(str(path) not in seen and str(dest) not in destinations,'Duplicate source/destination')
        seen[str(path)]=source['sha256'];destinations.add(str(dest))
    for row in files:check(row)
    automatic=[{'source':descriptor(paths[n]),'destination':'provenance/finalization/'+name,'group':'finalization'}
               for n,name in [('evaluation','inference-evaluation-outcome.json'),('cleanup','inference-cleanup.json'),('ledger_sync_receipt','inference-final-ledger-sync.json')]]
    automatic.extend({'source':descriptor(path),'destination':'provenance/finalization/'+name,'group':'finalization'}
                     for path,name in [(flat_path,'reviewed243-allowlist-draft.json'),(failure_path,'reviewed29-failure-index-draft.json')])
    for row in additions['files']:
        check(row);files.append(row)
    for row in automatic:
        path=str(Path(row.get('source',{}).get('path','')))
        if path in seen:
            require(seen[path]==row['source'].get('sha256'),'Repeated source SHA differs')
            continue
        check(row);files.append(row)
    require({row['group'] for row in files}==GROUPS,'Ten provenance groups required')
    failures=list(failure['failures'])+additions.get('failures',[]);ids=set()
    for row in failures:
        require(all(isinstance(row.get(k),str) and row[k] for k in ('id','category','summary','reason'))
                and row.get('artifacts') and row['id'] not in ids,'Failure row incomplete/duplicate')
        ids.add(row['id'])
        for item in row['artifacts']:
            require(seen.get(item.get('path'))==item.get('sha256'),'Failure artifact not selected exactly')
    out=Path(args.out).absolute()
    require(out.parent==ops and re.fullmatch('inference-provenance-finalization-attempt[1-9][0-9]*',out.name)
            and not out.exists(),'Fresh direct provenance output required')
    now=datetime.now(timezone.utc).isoformat();failure.update(finalized=True,status='Finalized publication metadata after completed scoped inference cleanup',finalized_at_utc=now,failures=failures,
        pending_appendices=[],current_outcome_not_claimed='Completed evaluation, authoritative ledger sync and scoped cleanup verified by the linked evidence; package creation and publication are separate actions.',
        completion_evidence={name:descriptor(paths[name]) for name in ('projection','evaluation','cleanup','ledger_sync_receipt')})
    out.mkdir()  # Everything above is read-only. Never reuse/delete a partial attempt.
    failure_out=out/'failure-index.json';write_new(failure_out,failure)
    flat.update(status='FINALIZED: completed inference and cleanup verified',finalized=True,finalized_at_utc=now,files=files,
                failure_index=descriptor(failure_out),pending_required_groups=[],append_before_publication=[])
    manifest=out/'published-allowlist.json';write_new(manifest,flat)
    receipt={'project':PROJECT,'label':LABEL,'finalized':True,'draft':descriptor(flat_path),'failure_draft':descriptor(failure_path),
             'failure_index':descriptor(failure_out),'provenance':descriptor(manifest),'retained_draft_files':243,
             'retained_failure_prefix':29,'files':len(files),'failure_rows':len(failures),'completion':summary,
             'answer_or_model_text_parsed':False,'provider_actions':0,'ledger_writes':0}
    write_new(out/'receipt.json',receipt);return receipt


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--draft',default=str(OPS/'inference-flat-provenance-draft.json'))
    a.add_argument('--failures',default=str(OPS/'inference-failure-index-finalization-draft.json'))
    a.add_argument('--evaluation',default=str(OPS/'inference-evaluation-attempt1/outcome.json'))
    a.add_argument('--projection',default=str(OPS/'inference-evaluation-attempt1/hard15-score-projection.json'))
    a.add_argument('--cleanup',default=str(OPS/'inference-final-cleanup-attempt1/cleanup.json'))
    a.add_argument('--ledger',default=str(OPS/'inference-final-gpu-ledger.json'))
    a.add_argument('--out',default=str(OPS/'inference-provenance-finalization-attempt1'))
    a.add_argument('--additions',required=True,help='Exact files[] rows and optional new failures[]; project/label required')
    a.add_argument('--ledger-sync-receipt',required=True,help='Safe project/label, canonical_ledger_sha256, remote_ledger_sha256, seed_prefix_unchanged:true')
    try:print(json.dumps(finalize(a.parse_args())));return 0
    except Exception as e:print(json.dumps({'project':PROJECT,'label':LABEL,'finalized':False,'failure_class':type(e).__name__}));return 1


if __name__=='__main__':raise SystemExit(main())
