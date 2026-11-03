#!/usr/bin/env python3
"""Verify exact local restoration; unknown remote operator tails stay disclosed."""
import hashlib
import json
from pathlib import Path
import tarfile

OPS=Path(__file__).resolve().parent;REPO=OPS.parent.parent
PROJECT='servedoctor-hard15-inference-20261103';ANALYSIS='servedoctor-hard15-20261102'
LABEL='ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)'
INSTANCE=58905385;SCOPE='7da4c657be8e5e6bf971e5e017a24b02385d6c0f3221daa20ae64e7eb7cedce7'
SOURCE='4b0add12be36cef0d0776607f683310b1641b0f7'
PARENT='62d9b4be48ba341579b84f59dadf47a12c0c84dc758df882c9bc1bac7c9a4a20'
EVALUATION='c41ada9e338f4a0ca4a9365c811b12ca356c9c6a1598f6a7700b652cade48d88'
MANIFEST='807e92fc4d019e5ec52f0cc1491a75717671eccf8f49f02d35b43ea00d3aff8c'
COVERAGE='d96433c46a48507beb9ee8c17fcfa5a4301de65d93f2a5d00cc760d0a0e03420'
LEDGER='7c5fa20826516ae5dc6a17ca92a603516c85eda92248ebf9acfe7ed8d96a8385'
ARCHIVE='f6a57fc04dda93d59a2f68f2beab27c73009bfd355ce0c29322fd2fe7e2744fa'
REL='runs/servedoctor-hard15-ops-20261102'
TARGET_COUNT=326


def require(v,msg):
    if not v:raise ValueError(msg)
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def load(path):return json.loads(Path(path).read_text())
def desc(path):return {'path':str(Path(path).absolute()),'sha256':sha(path)}
def regular(path,repo):
    p=Path(path);require(p.is_absolute() and '..' not in p.parts and p.is_relative_to(repo) and p.is_file(),'Regular repository evidence required')
    require(all(not repo.joinpath(*p.relative_to(repo).parts[:i]).is_symlink() for i in range(1,len(p.relative_to(repo).parts)+1)),'Linked evidence refused');return p

def checked(d,repo):
    p=regular(d['path'],repo);require(sha(p)==d['sha256'],'Offline recovery descriptor differs');return p

def inventory(root):
    root=Path(root);require(root.is_dir() and not root.is_symlink(),'Required local evidence tree missing');out={}
    for p in sorted(root.rglob('*')):
        require(not p.is_symlink(),'Linked local evidence refused')
        if p.is_file():out[p.relative_to(root).as_posix()]=sha(p)
        else:require(p.is_dir(),'Special local evidence refused')
    return out


def verify_recovery(repo=REPO,receipt_path=None):
    repo=Path(repo).resolve();ops=repo/REL;receipt=regular(receipt_path or ops/'inference-offline-materialization-attempt1/receipt.json',repo);r=load(receipt)
    require(r.get('project')==PROJECT and r.get('analysis_project')==ANALYSIS and r.get('label')==LABEL and r.get('instance_id')==INSTANCE
        and r.get('rental_scope_sha256')==SCOPE and r.get('source_commit')==SOURCE
        and all(r.get(k) is True for k in ('completed','science_unchanged','no_model_calls','no_new_start','all_required_scientific_artifacts_backed_up','remote_ops_control_tail_unverified'))
        and r.get('all_remote_artifacts_backed_up') is False,'Honest completed offline-restoration policy required')
    parent=checked(r['original_parent'],repo);require(parent==ops/'inference-rental-attempt1/outcome.json' and sha(parent)==PARENT,'Original failed parent changed')
    old=load(parent);rows=old.get('commands',[])
    require(old.get('returncode')==1 and old.get('stop_confirmed') is True and old.get('cleanup_confirmed') is True and old.get('transport_cleanup_returncode')==0
        and not any(old.get(n) for n in ('watchdog_cleanup_error_class','transport_cleanup_error_class','child_cleanup_error_class'))
        and [(x.get('index'),x.get('name'),x.get('returncode')) for x in rows]==[(0,'meta-relay',0),(1,'cold-prepare-validate',0),(2,'authenticated-catalog',0),(3,'all-six-arms',0),(4,'mirror-study',0),(5,'mirror-ops',255)],'Only the known post-evaluation transfer failure is accepted')
    evaluation=checked(r['evaluation_outcome'],repo);manifest=checked(r['study_manifest'],repo);coverage=checked(r['coverage_proof'],repo)
    require(sha(evaluation)==EVALUATION and sha(manifest)==MANIFEST and sha(coverage)==COVERAGE,'Completed scientific/preservation proofs changed')
    e=load(evaluation);sealed=load(manifest)
    require(e.get('completed') is True and not e.get('failure') and not e.get('cleanup_errors') and e.get('groups')==['rules-spark-wonder','glimmer-cascades']
        and sealed.get('stable') is True and sealed.get('study_file_count')==281 and sealed.get('ledger_sha256')==LEDGER,'Original native stage was not complete')
    expected={n:ops/x for n,x in [('study','inference-final-study'),('original','inference-final-original-study'),('ops','inference-final-remote-ops'),('old_ops','inference-final-remote-old-ops'),('control','inference-final-remote-control')]}
    require(set(r.get('mirrors',{}))==set(expected),'All five explicit local evidence trees required')
    maps={}
    for name,root in expected.items():
        row=r['mirrors'][name];require(Path(row['local_root'])==root,'Local restoration path differs');maps[name]=inventory(root)
        require(maps[name] and maps[name]==row.get('files_sha256'),'Materialized known bytes changed')
    require(maps['study']==sealed['study_files_sha256'] and len(maps['original'])==178,'Evaluated281/original178 inventory differs')
    protocol=load(expected['study']/'inference-analysis-protocol.json');require(maps['original']==protocol['original_inventory_sha256'],'Original frozen bytes changed')
    ledger=r['ledger'];p=regular(ledger['path'],repo)
    require(p==ops/'inference-final-gpu-ledger.json' and sha(p)==ledger.get('sha256')==ledger.get('remote_sha256')==LEDGER,'Authoritative evaluated ledger changed')
    known_rows=load(coverage).get('targets',[])
    known={row['target']:row['sha256'] for row in known_rows}
    require(len(known_rows)==len(known)==TARGET_COUNT,'Exact pinned recovery target set required')
    targets=set();restored={}
    for item in r.get('restored_files',[]):
        target=regular(item['target'],repo);require(target not in targets and sha(target)==item['sha256'],'Restored target differs');targets.add(target)
        require(known.get(str(target))==item['sha256'],'Restoration target not in pinned326 coverage')
        restored[str(target)]=item['sha256']
        src=item['source']
        if src['kind']=='existing-file':require(sha(regular(src['path'],repo))==src['sha256']==item['sha256'],'Existing restoration source differs')
        elif src['kind']=='archive-member':
            archive=checked(src['archive'],repo);require(sha(archive)==ARCHIVE,'Original stage archive differs');member=Path(src['member'])
            require(not member.is_absolute() and '..' not in member.parts,'Unsafe opaque archive member')
            with tarfile.open(archive,'r:gz') as tar:
                entry=tar.getmember(src['member']);require(entry.isfile(),'Nonregular opaque archive member')
                with tar.extractfile(entry) as f:h=hashlib.sha256(f.read()).hexdigest()
            require(h==src['sha256']==item['sha256'],'Opaque archive restoration source differs')
        else:raise ValueError('Unknown restoration source')
    require(restored==known,'Receipt must preserve every pinned recovery target exactly')
    require(r.get('input_verification',{}).get('ready') is True and r['input_verification'].get('final_decisions')==90,'Unchanged c98 science gate proof required')
    return {'project':PROJECT,'label':LABEL,'pipeline_outcome':desc(parent),'original_failed_pipeline_outcome':desc(parent),
        'offline_recovery_receipt':desc(receipt),'coverage_proof':desc(coverage),'input_verification':r['input_verification'],
        'all_required_scientific_artifacts_backed_up':True,'all_remote_artifacts_backed_up':False,'remote_ops_control_tail_unverified':True,
        'science_unchanged':True,'no_model_calls':True,'no_new_start':True}
