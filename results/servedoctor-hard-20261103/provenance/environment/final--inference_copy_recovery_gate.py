#!/usr/bin/env python3
"""Read-only gate for this exact post-evaluation mirror failure and recovery."""
import hashlib
import json
from pathlib import Path

OPS=Path(__file__).resolve().parent;REPO=OPS.parent.parent
PROJECT='servedoctor-hard15-inference-20261103'
LABEL='ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)'
INSTANCE=58905385
SCOPE='7da4c657be8e5e6bf971e5e017a24b02385d6c0f3221daa20ae64e7eb7cedce7'
SOURCE='4b0add12be36cef0d0776607f683310b1641b0f7'
PARENT='62d9b4be48ba341579b84f59dadf47a12c0c84dc758df882c9bc1bac7c9a4a20'
EVALUATION='c41ada9e338f4a0ca4a9365c811b12ca356c9c6a1598f6a7700b652cade48d88'
MANIFEST='807e92fc4d019e5ec52f0cc1491a75717671eccf8f49f02d35b43ea00d3aff8c'
DECLARATION='67d84a0dde43daf9294c9515dad71a9c84a0f0183b3740c55e22865043dfe47f'
LEDGER='7c5fa20826516ae5dc6a17ca92a603516c85eda92248ebf9acfe7ed8d96a8385'
REL='runs/servedoctor-hard15-ops-20261102'


def require(value,message):
    if not value:raise ValueError(message)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path):return json.loads(Path(path).read_text())
def regular(path,repo):
    path=Path(path);require(path.is_absolute() and '..' not in path.parts,'Absolute evidence path required')
    require(path.is_relative_to(repo) and path.is_file(),'Missing repository evidence')
    require(all(not repo.joinpath(*path.relative_to(repo).parts[:i]).is_symlink() for i in range(1,len(path.relative_to(repo).parts)+1)),'Linked evidence refused')
    return path

def desc(path):return {'path':str(Path(path).absolute()),'sha256':sha(path)}
def checked(value,repo):
    path=regular(value['path'],repo);require(sha(path)==value['sha256'],'Recovery descriptor differs');return path

def inventory(root):
    root=Path(root);require(root.is_dir() and not root.is_symlink(),'Recovery mirror missing')
    result={}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(),'Linked recovery member refused')
        if path.is_file():result[path.relative_to(root).as_posix()]=sha(path)
        else:require(path.is_dir(),'Special recovery member refused')
    return result


def verify_recovery(repo=REPO,receipt_path=None):
    repo=Path(repo).resolve();ops=repo/REL
    receipt_path=regular(receipt_path or ops/'inference-copy-recovery-attempt1/materialization-receipt.json',repo);r=load(receipt_path)
    require(r.get('project')==PROJECT and r.get('label')==LABEL and r.get('instance_id')==INSTANCE
        and r.get('rental_scope_sha256')==SCOPE and r.get('source_commit')==SOURCE
        and all(r.get(k) is True for k in ('completed','science_unchanged','no_model_calls'))
        and r.get('acquisition_mode')=='one-start-tar-copy','Exact copy-only recovery receipt required')
    declaration=checked(r['declaration'],repo);require(sha(declaration)==DECLARATION,'Pre-restart copy-only declaration differs')
    original=checked(r['original_parent'],repo);require(sha(original)==PARENT and original==ops/'inference-rental-attempt1/outcome.json','Original failed parent changed')
    old=load(original);commands=old.get('commands',[])
    require(old.get('project')==PROJECT and old.get('instance_id')==INSTANCE and old.get('rental_scope_sha256')==SCOPE
        and old.get('returncode')==1 and old.get('stop_confirmed') is True and old.get('cleanup_confirmed') is True
        and old.get('transport_cleanup_returncode')==0 and len(commands)==6
        and [(x.get('index'),x.get('name'),x.get('returncode')) for x in commands]==[(0,'meta-relay',0),(1,'cold-prepare-validate',0),(2,'authenticated-catalog',0),(3,'all-six-arms',0),(4,'mirror-study',0),(5,'mirror-ops',255)],'Failure was not solely the known post-model copy')
    parent=checked(r['recovery_parent'],repo);new=load(parent)
    require(parent!=original and new.get('project')==PROJECT and new.get('instance_id')==INSTANCE and new.get('rental_scope_sha256')==SCOPE
        and new.get('returncode')==0 and new.get('stop_confirmed') is True and new.get('cleanup_confirmed') is True
        and not any(new.get(k) for k in ('failure','cleanup_errors','watchdog_cleanup_error_class','transport_cleanup_error_class','child_cleanup_error_class'))
        and new.get('no_model_calls') is True and new.get('copy_only') is True,'Successful real copy-only parent required')
    evaluation=checked(r['evaluation_outcome'],repo);manifest=checked(r['study_manifest'],repo)
    require(sha(evaluation)==EVALUATION and sha(manifest)==MANIFEST,'Completed evaluation proof changed')
    evaluated=load(evaluation);sealed=load(manifest)
    require(evaluated.get('completed') is True and not evaluated.get('failure') and not evaluated.get('cleanup_errors')
        and evaluated.get('groups')==['rules-spark-wonder','glimmer-cascades'] and sealed.get('stable') is True
        and sealed.get('study_file_count')==281 and sealed.get('ledger_sha256')==LEDGER,'Native stage was not complete before recovery')
    expected={n:ops/relative for n,relative in [('study','inference-final-study'),('original','inference-final-original-study'),('ops','inference-final-remote-ops'),('old_ops','inference-final-remote-old-ops'),('control','inference-final-remote-control')]}
    require(set(r.get('mirrors',{}))==set(expected),'Exact five final mirror maps required')
    for name,root in expected.items():
        item=r['mirrors'][name];require(Path(item['local_root'])==root and item.get('before_after_equal') is True,'Recovery mirror identity differs')
        actual=inventory(root);require(actual and actual==item.get('files_sha256'),'Recovered local bytes differ')
        source=load(checked(item['source_manifest'],repo))
        known=source.get('files_sha256',source.get('study_files_sha256',source.get('original_inventory_sha256')))
        require(known==actual,'Source materialization map differs')
        if name=='study':require(actual==sealed['study_files_sha256'],'The complete evaluated study changed')
        elif name=='original':require(len(actual)==178,'Original178 inventory incomplete')
        else:
            require(source.get('before_after_equal') is True,'Source copy stability not proven')
            for key in ('before','after'):
                raw=load(checked(source[key],repo));require(raw.get('files_sha256')==actual,'Remote before/after hash map differs')
    ledger=r['ledger'];path=regular(ledger['path'],repo)
    require(path==ops/'inference-final-gpu-ledger.json' and sha(path)==ledger.get('sha256')==ledger.get('remote_sha256')==LEDGER,'Final canonical GPU ledger changed')
    return {'project':PROJECT,'label':LABEL,'instance_id':INSTANCE,'rental_scope_sha256':SCOPE,
        'original_pipeline_outcome':desc(original),'pipeline_outcome':desc(parent),'copy_recovery_receipt':desc(receipt_path),
        'evaluation_outcome':desc(evaluation),'study_manifest':desc(manifest),'declaration':desc(declaration),'science_unchanged':True,'mirrors_verified':True,'no_model_calls':True,
        'canonical_ledger_sha256':LEDGER,'source_commit':SOURCE}
