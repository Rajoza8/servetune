#!/usr/bin/env python3
"""Declare Hard recording readiness once, after calibration and before generation.

Collection/identity only: no answers, study generation, model/API calls, ledger
or lifecycle changes. The only GPU query is a fixed read-only GPU0 UUID probe.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import hard_integrity as gate
from servetune.engine import engine_command

VLLM_PIN='0.26.1rc1.dev608+g99a10304d'
ALLOWANCE=30
POLL=1
EXPECTED=[{'module':module,'seconds':10,'duty':duty,'matrix_size':size,'period':period}
    for module in gate.JOB_MODULES for duty,size,period in ((.6,8192,.2),(.02,1024,1.0))]


def file_inventory(directory):
    result={}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():raise ValueError('Calibration evidence contains a symlink')
        if path.is_file():result[path.relative_to(directory).as_posix()]=gate.sha(path)
    return result


def job_evidence(calibration_dir,index,row):
    if row.get('spec')!=EXPECTED[index]:raise ValueError('Exact ordered eight-job preflight plan differs')
    pid=row.get('job_pid');status=row.get('job_proc_status',{})
    if (row.get('status')!='completed' or type(pid) is not int or pid<=0 or row.get('job_returncode')!=0
            or row.get('job_stopped') is not True or row.get('owner_marker_verified') is not True
            or row.get('job_visible_with_local_pid') is not True or row.get('job_uid')!=0
            or not re.fullmatch('[0-9a-f]{64}',row.get('owner_marker_sha256',''))
            or not str(row.get('job_start_ticks','')).isdecimal() or int(row['job_start_ticks'])<=0
            or row.get('error_class') or row.get('failure_reason')):raise ValueError('Preflight job ownership/start/exit proof failed')
    try:
        namespace=[int(v) for v in status['NSpid'].split()]
        if int(status['Pid'])!=pid or not namespace or namespace[-1]!=pid or min(namespace)<=0:raise ValueError()
        if 'NStgid' in status and int(status['NStgid'].split()[-1])!=pid:raise ValueError()
    except (KeyError,TypeError,ValueError,IndexError):raise ValueError('Local PID namespace proof differs') from None
    folder=calibration_dir/f'preflight-job-{index:02d}'
    samples_path=gate.regular(folder,'preflight-gpu.jsonl');samples=gate.jsonl(samples_path)
    times=[v.get('elapsed_s') for v in samples]
    if not times or any(not gate.numeric(v) or v<0 for v in times) or any(b<a for a,b in zip(times,times[1:])):
        raise ValueError('Invalid preflight sample time')
    seen=[v['elapsed_s'] for v in samples if any(p.get('pid')==pid and EXPECTED[index]['module'] in str(p.get('command',''))
        for p in v.get('gpu',{}).get('processes',[]))]
    if not seen or seen[0]>ALLOWANCE:raise ValueError('Own job GPU sighting absent or later than predeclared allowance')
    if row.get('gpu_samples')!=len(samples):raise ValueError('Preflight sample count differs')
    elapsed=row.get('job_elapsed_s')
    if not gate.numeric(elapsed) or elapsed<EXPECTED[index]['seconds'] or seen[-1]>elapsed+1:raise ValueError('Preflight elapsed/exit timing differs')
    required=['preflight-gpu.jsonl','preflight-nvidia-smi.jsonl','preflight-contention.log']
    artifacts={name:gate.descriptor(gate.regular(folder,name)) for name in required}
    return {'job_index':index,'module':EXPECTED[index]['module'],'spec':EXPECTED[index],
        'first_local_pid_gpu_sighting_s':seen[0],'last_local_pid_gpu_sighting_s':seen[-1],
        'startup_within_declared_allowance':True,'local_pid_namespace_verified':True,
        'owned_uid0_start_ticks_and_marker_verified':True,'job_stopped_returncode':0,
        'gpu_samples':len(samples),'artifacts':artifacts}


def declare(calibration_dir,expected_source_commit,out,*,repo=gate.REPO,ops=gate.OPS,environ=None,
            run=subprocess.run,git_output=subprocess.check_output):
    repo=Path(repo).resolve();ops=Path(ops).resolve();out=Path(out).absolute();calibration_dir=Path(calibration_dir).resolve()
    if not out.is_relative_to(ops) or out.is_symlink():raise ValueError('Fresh readiness output must stay under Hard OPS')
    declaration=out.with_name(out.stem+'-declaration.json');failure=out.with_name(out.stem+'-failure.json')
    if any(p.exists() or p.is_symlink() for p in (out,declaration,failure)):raise ValueError('Readiness attempt already exists; preserve it, never overwrite')
    gate.write_new(declaration,{'project':gate.PROJECT,'created_at_utc':gate.utc(),'calibration_directory':str(calibration_dir),
        'expected_recording_source_commit':expected_source_commit,'calibration_source_commit':gate.BASE_SOURCE,
        'startup_allowance_s':ALLOWANCE,'observer_poll_s':POLL,'declarer_sha256':gate.sha(Path(__file__))})
    stage='pre_generation_source';probe=None
    try:
        if (repo/gate.PRIMARY).exists() or (repo/gate.PRIMARY).is_symlink():raise ValueError('Declare infrastructure readiness before first Hard generation')
        current=gate.verify_source_policy(repo,expected_source_commit)
        relative=calibration_dir.relative_to(repo).as_posix()
        if not re.fullmatch(r'runs/sd-hard-calibration-[a-z0-9-]+',relative):raise ValueError('Use canonical Hard calibration evidence only')
        original=git_output(['git','show',gate.BASE_SOURCE+':configs/servedoctor-hard.json'],cwd=repo)
        config=repo/'configs/servedoctor-hard.json';base_study=json.loads(original)
        gate.allowed_host_config_transition(base_study,gate.load(config))
        stage='calibration_identity'
        cal_path=gate.regular(calibration_dir,'calibration.json');cal=gate.load(cal_path)
        actual_path=gate.regular(calibration_dir,'preflight.json');actual=gate.load(actual_path)
        metadata_path=gate.regular(calibration_dir,'engine/engine_metadata.json');metadata=gate.load(metadata_path)
        expected_command=engine_command({'model_id':'meta-models/Muse-Glimmer-30B','model_revision':gate.REV,
            'gpu_index':0,'port':8000,'use_engine_defaults':False,**base_study['engine_base']},'bf16')
        if (cal.get('status')!='completed' or not gate.numeric(cal.get('capacity_rps')) or cal['capacity_rps']<=0
                or cal.get('failure') or cal.get('cleanup_failure') or cal.get('engine')!=VLLM_PIN
                or metadata.get('model_id')!='meta-models/Muse-Glimmer-30B' or metadata.get('model_revision')!=gate.REV
                or metadata.get('tokenizer_revision')!=gate.REV or metadata.get('dtype')!='bf16'
                or metadata.get('vllm_version')!=VLLM_PIN or metadata.get('gpu_index')!=0
                or metadata.get('argv')!=expected_command or metadata.get('identity_complete') is not True
                or metadata.get('cleanup_status')!='completed' or metadata.get('returncode') is None):raise ValueError('Canonical calibrated engine/runtime identity differs')
        if actual.get('status')!='completed' or actual.get('stage')!='preflight_passed' or actual.get('gpu_index')!=0 or len(actual.get('preflight_jobs',[]))!=8:
            raise ValueError('All eight exact preflight jobs must have completed')
        stage='eight_job_collection_proofs'
        jobs=[job_evidence(calibration_dir,i,row) for i,row in enumerate(actual['preflight_jobs'])]
        stage='physical_scope'
        scope_path=gate.regular(ops,'rental-scope.json');scope=gate.load(scope_path)
        environment=os.environ if environ is None else environ
        instance=scope.get('instance_id')
        if (scope.get('project')!=gate.PROJECT or scope.get('label')!=gate.PROJECT or type(instance) is not int or instance<=0
                or instance in (58690026,58716527) or environment.get('CONTAINER_ID')!=str(instance)):
            raise ValueError('Foreign or missing Hard rental namespace')
        session_path=gate.regular(ops,'session.json');session=gate.load(session_path)
        fields=('project','label','instance_id','machine_id','offer_id','image')
        if session.get('scope_sha256')!=gate.sha(scope_path) or any(session.get(k)!=scope.get(k) for k in fields):
            raise ValueError('Current Hard session/scope binding differs')
        stage='physical_gpu_probe'
        command=['nvidia-smi','--id=0','--query-gpu=uuid','--format=csv,noheader']
        try:
            completed=run(command,capture_output=True,text=True,timeout=10)
            values=completed.stdout.strip().splitlines();probe={'command':command,'returncode':completed.returncode}
            if completed.returncode or len(values)!=1 or not re.fullmatch(r'GPU-[A-Za-z0-9-]+',values[0]):raise ValueError('Physical GPU0 UUID probe failed')
        except BaseException as exc:
            probe=probe or {'command':command};probe['error_class']=type(exc).__name__;raise
        physical={'verified':True,'instance_id':instance,'gpu_index':0,'gpu_uuid':values[0],
            'rental_scope_sha256':gate.sha(scope_path),'container_id_matches_scope':True}
        probe['gpu_uuid']=values[0]
        stage='final_hashes'
        result={'project':gate.PROJECT,'declared_at_utc':gate.utc(),'declared_before_generation':True,'recording_ready':True,
            'source_commit':current,'config_sha256':gate.sha(config),'calibration_source_commit':gate.BASE_SOURCE,
            'calibration_config_sha256':hashlib.sha256(original).hexdigest(),'model_revision':gate.REV,'vllm_version':VLLM_PIN,
            'rental_scope_sha256':gate.sha(scope_path),'gpu_uuid':values[0],
            'gpu_namespace_local_pids_verified':True,'all4_job_modules_verified':True,'culprit_and_decoy_startup_verified':True,
            'startup_allowance_s':ALLOWANCE,'observer_poll_s':POLL,'actual_preflight':gate.descriptor(actual_path),
            'calibration':gate.descriptor(cal_path),'calibration_engine_metadata':gate.descriptor(metadata_path),
            'calibration_directory':str(calibration_dir),'calibration_files_sha256':file_inventory(calibration_dir),
            'job_timing_evidence':jobs,'physical_gpu_binding':physical,'physical_gpu_probe':probe,
            'declaration':gate.descriptor(declaration),
            'calibration_source_attestation':'Operator-declared baseline execution; exact runtime/base-engine command and unchanged base workload are independently checked.',
            'scope':'Infrastructure collection readiness only; no SLO, fault-validity or arm-performance filter.'}
        # Recheck the public source after probe/IO before committing the declaration.
        gate.verify_source_policy(repo,expected_source_commit)
        gate.write_new(out,result);return result
    except BaseException as exc:
        gate.write_new(failure,{'project':gate.PROJECT,'finished_at_utc':gate.utc(),'failure_stage':stage,
            'error_class':type(exc).__name__,'physical_gpu_probe':probe,'declaration':gate.descriptor(declaration)})
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--calibration-dir',type=Path,required=True)
    parser.add_argument('--expected-source-commit',required=True);parser.add_argument('--out',type=Path,default=gate.OPS/'preflight-readiness.json')
    args=parser.parse_args();value=declare(args.calibration_dir,args.expected_source_commit,args.out)
    print(json.dumps({'recording_ready':value['recording_ready'],'source_commit':value['source_commit'],
        'job_proofs':len(value['job_timing_evidence']),'gpu_uuid':value['gpu_uuid'],'readiness_sha256':gate.sha(args.out)}))


if __name__=='__main__':
    try:main()
    except Exception as exc:sys.exit('Hard readiness declaration failed: '+type(exc).__name__)
