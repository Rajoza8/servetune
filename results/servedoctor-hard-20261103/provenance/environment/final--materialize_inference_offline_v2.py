#!/usr/bin/env python3
"""Restore only cryptographically known local bytes; default is read-only audit.

Never parses answers/model bodies. Never calls models/providers or changes the
canonical ledger. The original failed parent and partial OPS tree are retained.
Unknown remote operator tails remain explicitly unverified.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile

OPS=Path(__file__).resolve().parent;REPO=OPS.parent.parent
PROJECT='servedoctor-hard15-inference-20261103';ANALYSIS='servedoctor-hard15-20261102'
LABEL='ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)'
COVERAGE='d96433c46a48507beb9ee8c17fcfa5a4301de65d93f2a5d00cc760d0a0e03420'
PARENT='62d9b4be48ba341579b84f59dadf47a12c0c84dc758df882c9bc1bac7c9a4a20'
EVALUATION='c41ada9e338f4a0ca4a9365c811b12ca356c9c6a1598f6a7700b652cade48d88'
MANIFEST='807e92fc4d019e5ec52f0cc1491a75717671eccf8f49f02d35b43ea00d3aff8c'
PRESERVED='505d7d74d4a978f1de9058380c3d38b85826d7c06affe1d7cffcabe16032d068'
PACKAGE='fdaf66af25327c4501c8e66b2fa56708600d4c4acc8b5585a32724d3b5f0ae91'
SOURCE='4b0add12be36cef0d0776607f683310b1641b0f7'
SCOPE='7da4c657be8e5e6bf971e5e017a24b02385d6c0f3221daa20ae64e7eb7cedce7'
TARGET_COUNT=326
def require(v,s):
    if not v:raise ValueError(s)
def sha(q):
    h=hashlib.sha256()
    with Path(q).open('rb') as f:
        for x in iter(lambda:f.read(1048576),b''):h.update(x)
    return h.hexdigest()
def load(q):return json.loads(Path(q).read_text())
def desc(q):return {'path':str(Path(q).resolve()),'sha256':sha(q)}
def write(q,v):
    with Path(q).open('x') as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def regular(q,repo):
    q=Path(q).absolute();require(q.is_relative_to(repo) and '..' not in q.parts and q.is_file()
       and all(not x.is_symlink() for x in (q,*q.parents)),'Regular in-repository source required');return q
def inventory(q):
    require(q.is_dir() and not q.is_symlink(),'Regular directory required');result={}
    for x in sorted(q.rglob('*')):
        require(not x.is_symlink(),'Linked evidence refused')
        if x.is_file():result[x.relative_to(q).as_posix()]=sha(x)
        else:require(x.is_dir(),'Special evidence refused')
    return result
def defaults(repo=REPO):
    p=Path(repo)/'runs/servedoctor-hard15-ops-20261102'
    return argparse.Namespace(coverage=str(p/'offline-inference-recovery-coverage.json'),out=str(p/'inference-offline-materialization-attempt2'),restore=False)
def verify(args,repo=REPO):
    repo=Path(repo).resolve();p=repo/'runs/servedoctor-hard15-ops-20261102';coverage=regular(args.coverage,repo)
    require(sha(coverage)==COVERAGE,'Reviewed offline coverage differs');v=load(coverage)
    parent=regular(p/'inference-rental-attempt1/outcome.json',repo);evaluation=regular(p/'inference-evaluation-attempt1/outcome.json',repo)
    require(sha(parent)==PARENT and sha(evaluation)==EVALUATION,'Original failed parent/evaluation changed')
    m=regular(v['model_stage_manifest']['path'],repo);archive=regular(v['model_stage_archive']['path'],repo)
    require(sha(m)==MANIFEST==v['model_stage_manifest']['sha256'] and sha(archive)==v['model_stage_archive']['sha256'],'Archive/manifest commitment differs')
    expected=load(m);require(expected.get('stable') is True and archive.stat().st_size==expected['archive_bytes'] and sha(archive)==expected['archive_sha256'],'Model archive differs')
    require(inventory(p/'inference-final-study')==expected['study_files_sha256'],'Final scientific study changed')
    preserved=repo/'runs/servedoctor-hard-ops-20261102/blocked-hard-study-attempt1/preserved-files-manifest.json'
    require(sha(regular(preserved,repo))==PRESERVED,'Original505 preservation differs')
    original={n[len('latest/study/'):]:h for n,h in load(preserved)['files'].items() if n.startswith('latest/study/')}
    require(len(original)==178 and inventory(preserved.parent/'latest/study')==original,'Original178 bytes differ')
    members={}
    with tarfile.open(archive) as t:
        for member in t.getmembers():
            if member.isdir():continue
            require(member.isfile() and not member.issym() and not member.islnk() and not Path(member.name).is_absolute()
               and '..' not in Path(member.name).parts and member.name not in members,'Unsafe archive member')
            h=hashlib.sha256();f=t.extractfile(member)
            for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
            members[member.name]=h.hexdigest()
    require({n[len('study/'):]:h for n,h in members.items() if n.startswith('study/')}==expected['study_files_sha256'],'Archived study differs')
    plan=[]
    for row in v['targets']:
        target=Path(row['target']).absolute();require(target.is_relative_to(repo) and '..' not in target.parts,'Unsafe target')
        source=None
        for candidate in row['candidates']:
            if candidate['kind']=='existing-file':
                q=Path(candidate['path'])
                if q.is_file() and not q.is_symlink() and sha(regular(q,repo))==row['sha256']:
                    source={'kind':'existing-file','path':str(q),'sha256':row['sha256']};break
            elif candidate['kind']=='archive-member' and candidate['archive']==str(archive) and members.get(candidate['member'])==row['sha256']:
                source={'kind':'archive-member','archive':desc(archive),'member':candidate['member'],'sha256':row['sha256']};break
        require(source is not None,'A required exact byte source is unavailable')
        require(all(not q.is_symlink() for q in (target,*target.parents)),'Linked target refused')
        plan.append({'target':str(target),'sha256':row['sha256'],'source':source})
    require(len(plan)==TARGET_COUNT and len({x['target'] for x in plan})==TARGET_COUNT,'Exact reviewed target set differs')
    ledger=p/'inference-final-gpu-ledger.json'
    require(not ledger.exists() or sha(regular(ledger,repo))==expected['ledger_sha256'],'Existing final-ledger replica differs; never overwrite')
    return p,v,expected,plan,archive
def input_args(p):
    return argparse.Namespace(study_dir=str(p/'inference-final-study'),original_study_dir=str(p/'inference-final-original-study'),
       remote_ops=str(p/'inference-final-remote-ops'),remote_old_ops=str(p/'inference-final-remote-old-ops'),remote_control=str(p/'inference-final-remote-control'),
       calibration_mirror=str(p/'inference-final-remote-ops/portable-recording-evidence/calibration'),evaluation_dir=str(p/'inference-evaluation-attempt1'),
       score_projection=str(p/'inference-evaluation-attempt1/hard15-score-projection.json'),ledger=str(p/'inference-final-gpu-ledger.json'),
       ledger_seed=str(p.parent/'servedoctor-hard-ops-20261102/prepare-next-attempt1/upload/ledger.seed'))
def execute(args,repo=REPO,gate=None):
    repo=Path(repo).resolve();p,v,expected,plan,archive=verify(args,repo)
    if not args.restore:return {'verified':True,'restores':0,'targets':len(plan),'full_remote_mirror_claimed':False}
    out=Path(args.out).absolute();require(out.parent==p and re.fullmatch('inference-offline-materialization-attempt[1-9][0-9]*',out.name)
       and not out.exists(),'Fresh direct materialization output required');out.mkdir()
    write(out/'intent.json',{'project':PROJECT,'label':LABEL,'coverage_proof':desc(args.coverage),'original_parent':desc(p/'inference-rental-attempt1/outcome.json'),
       'mode':'offline-exact-byte-materialization','targets':plan,'no_model_calls':True,'no_new_start':True,'full_remote_mirror_claimed':False})
    try:
        stage=out/'staged';stage.mkdir()
        with tarfile.open(archive) as t:
            for row in plan:
                dst=stage/Path(row['target']).relative_to(repo);dst.parent.mkdir(parents=True,exist_ok=True);source=row['source']
                stream=regular(source['path'],repo).open('rb') if source['kind']=='existing-file' else t.extractfile(source['member'])
                with stream, dst.open('xb') as f:shutil.copyfileobj(stream,f)
                require(sha(dst)==row['sha256'],'Staged exact bytes differ')
        roots={'study':p/'inference-final-study','original':p/'inference-final-original-study','ops':p/'inference-final-remote-ops',
            'old_ops':p/'inference-final-remote-old-ops','control':p/'inference-final-remote-control'}
        kept=[]
        def rebind(previous,preserved,directory):
            for row in plan:
                source=row['source']
                if source['kind']!='existing-file':continue
                path=Path(source['path'])
                if path==previous or (directory and path.is_relative_to(previous)):
                    actual=preserved/path.relative_to(previous) if directory else preserved
                    require(sha(regular(actual,repo))==source['sha256'],'Preserved restoration source differs')
                    source['original_path']=source['path'];source['path']=str(actual)
        for name,target in roots.items():
            if name=='study':continue
            wanted={str(Path(x['target']).relative_to(target)):x['sha256'] for x in plan if Path(x['target']).is_relative_to(target)}
            require(wanted,'Missing reviewed target root')
            if target.exists() and inventory(target)==wanted:continue
            if target.exists():
                old=inventory(target);keep=out/'preserved-existing'/target.name;keep.parent.mkdir(parents=True,exist_ok=True)
                target.rename(keep);require(inventory(keep)==old,'Retained partial mirror changed');kept.append({'path':str(keep),'files_sha256':old});rebind(target,keep,True)
            shutil.copytree(stage/target.relative_to(repo),target);require(inventory(target)==wanted,'Materialized known tree differs')
        for row in plan:
            target=Path(row['target'])
            if any(target.is_relative_to(root) for root in roots.values()):continue
            if target.exists() and sha(regular(target,repo))==row['sha256']:continue
            if target.exists():
                keep=out/'preserved-existing'/target.relative_to(repo);keep.parent.mkdir(parents=True,exist_ok=True);target.rename(keep);rebind(target,keep,False)
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(stage/target.relative_to(repo),target)
            require(sha(target)==row['sha256'],'Materialized individual file differs')
        require(inventory(roots['study'])==expected['study_files_sha256'],'Scientific study changed during materialization')
        sys.path.insert(0,str(p))
        if gate is None:
            import inference_descriptor_adapter as package
            require(sha(package.__file__)==PACKAGE,'Reviewed exact-three-descriptor adapter changed');gate=package.verify_inputs
        proof=gate(input_args(p),repo=repo)
        require(proof.get('ready') is True and proof.get('recordings')==16 and proof.get('final_decisions')==90,'Unchanged full scientific gate did not pass')
        receipt={'project':PROJECT,'analysis_project':ANALYSIS,'label':LABEL,'instance_id':58905385,'rental_scope_sha256':SCOPE,'completed':True,
           'acquisition_mode':'offline-verified-byte-materialization','original_parent':desc(p/'inference-rental-attempt1/outcome.json'),
           'evaluation_outcome':desc(p/'inference-evaluation-attempt1/outcome.json'),'study_manifest':desc(p/'inference-evaluation-attempt1/mirror-manifest.json'),
           'coverage_proof':desc(args.coverage),'source_commit':SOURCE,'restored_files':plan,'preserved_partial_mirrors':kept,
           'mirrors':{name:{'local_root':str(root),'files_sha256':inventory(root),'complete_remote_mirror':name in ('study','original')} for name,root in roots.items()},
           'ledger':{'path':str(p/'inference-final-gpu-ledger.json'),'sha256':expected['ledger_sha256'],'remote_sha256':expected['ledger_sha256']},
           'input_verification':proof,'descriptor_adapter':desc(p/'inference_descriptor_adapter.py'),'all_required_scientific_artifacts_backed_up':True,'all_remote_artifacts_backed_up':False,
           'remote_ops_control_tail_unverified':True,'no_model_calls':True,'no_new_start':True,'science_unchanged':True,
           'unknown_operator_tails':v['unknown_final_operator_tails'],'finished_at_utc':datetime.now(timezone.utc).isoformat()}
        write(out/'receipt.json',receipt);return {'completed':True,'receipt':desc(out/'receipt.json'),'restored_known_targets':len(plan),'full_remote_mirror_claimed':False}
    except BaseException as error:write(out/'failure.json',{'failure_class':type(error).__name__,'partial_output_preserved':True,'no_automatic_retry':True});raise
def main():
    a=argparse.ArgumentParser(description=__doc__);d=defaults();a.add_argument('--coverage',default=d.coverage);a.add_argument('--out',default=d.out);a.add_argument('--restore',action='store_true')
    print(json.dumps(execute(a.parse_args())));return 0
if __name__=='__main__':raise SystemExit(main())
