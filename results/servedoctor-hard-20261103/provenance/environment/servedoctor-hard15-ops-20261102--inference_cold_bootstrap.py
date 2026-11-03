#!/usr/bin/env python3
"""Fresh inference host only: exact source, existing image runtime, public pinned weights.

No study generation, recording, calibration, model prompts, credentials, API or
provider calls. Execute only after the owning controller has reviewed SSH guide.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import subprocess
import sys

SOURCE='4b0add12be36cef0d0776607f683310b1641b0f7'
REV='cec94fcfd6512f2cfe708138c32533b346ea4f69'
REPO=Path('/workspace/servedoctor-hard/servetune')
REL='runs/servedoctor-hard15-ops-20261102'
PROJECT='servedoctor-hard15-inference-20261103'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,v):
    with Path(p).open('x') as f:json.dump(v,f,indent=2);f.write('\n')
def run(args,execute=subprocess.run,version=importlib.metadata.version,environ=os.environ):
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
    outcome={'project':PROJECT,
        'source_commit':SOURCE,'model_revision':REV,'started_at_utc':datetime.now(timezone.utc).isoformat(),'completed':False,'failure':None,'commands':[]}
    def cmd(label,argv,cwd=None,timeout=900):
        item={'label':label,'started_at_utc':datetime.now(timezone.utc).isoformat()};outcome['commands'].append(item)
        with (out/(label+'.stdout')).open('xb') as stdout,(out/(label+'.stderr')).open('xb') as stderr:
            result=execute(argv,cwd=cwd,stdout=stdout,stderr=stderr,timeout=timeout)
        item.update(returncode=result.returncode,finished_at_utc=datetime.now(timezone.utc).isoformat())
        if result.returncode:raise RuntimeError('Cold inference setup command failed')
        return out/(label+'.stdout')
    try:
        binding=json.loads(Path(args.binding).read_text());scope=json.loads(Path(args.scope).read_text())
        if (binding.get('project')!=PROJECT or binding.get('purpose')!='inference-only'
            or binding.get('rental_scope_sha256')!=sha(args.scope) or scope.get('instance_id')!=binding.get('instance_id')
            or environ.get('CONTAINER_ID')!=str(binding.get('instance_id'))):raise ValueError('Inference scope/container differs')
        outcome.update(instance_id=binding['instance_id'],rental_scope_sha256=binding['rental_scope_sha256'])
        soft,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
        if hard!=resource.RLIM_INFINITY and hard<65536:raise ValueError('FD hard limit insufficient')
        resource.setrlimit(resource.RLIMIT_NOFILE,(65536,hard))
        if REPO.exists():raise ValueError('Fresh inference repository required')
        REPO.parent.mkdir(parents=True,exist_ok=True)
        cmd('clone',['git','clone','--no-checkout','https://github.com/Rajoza8/servetune.git',str(REPO)])
        cmd('checkout-exact-source',['git','checkout','--detach',SOURCE],REPO)
        path=cmd('verify-source',['git','rev-parse','HEAD'],REPO,30)
        if path.read_text().strip()!=SOURCE:raise ValueError('Inference source differs')
        if version('vllm')!=args.expected_vllm:raise ValueError('Image vLLM version differs from recorded runtime')
        cmd('install-local-package',[sys.executable,'-m','pip','install','--no-deps','-e','.'],REPO,180)
        cmd('download-pinned-public-model',[sys.executable,'-c',
            "from huggingface_hub import snapshot_download; p=snapshot_download('meta-models/Muse-Glimmer-30B',revision='"+REV+"',token=False); assert p.rstrip('/').endswith('/"+REV+"'); print('pinned_snapshot_ready')"],REPO,1200)
        path=cmd('physical-gpu',['nvidia-smi','-i','0','--query-gpu=uuid,name,memory.total','--format=csv,noheader,nounits'],REPO,30)
        rows=[r.split(',') for r in path.read_text().splitlines() if r.strip()]
        if len(rows)!=1:raise ValueError('One physical GPU required')
        uuid,name,memory=[v.strip() for v in rows[0]]
        if not uuid.startswith('GPU-') or 'RTX PRO 6000' not in name or not 94000<=float(memory)<=100000:raise ValueError('Approved GPU hardware differs')
        folder=REPO/REL;folder.mkdir(parents=True,exist_ok=True)
        hardware={'project':PROJECT,'instance_id':binding['instance_id'],'rental_scope_sha256':binding['rental_scope_sha256'],
           'container_id_matches_scope':True,'source_commit':SOURCE,'model_revision':REV,'dtype':'bf16','vllm_version':version('vllm'),
           'gpu_uuid':uuid,'gpu_name':name,'gpu_memory_mib':float(memory),'fd_soft':65536,'fd_hard':hard,
           'purpose':'inference-only; original recording GPU identity stays in sealed observations','captured_at_utc':datetime.now(timezone.utc).isoformat()}
        write(folder/'inference-hardware.json',hardware);outcome.update(completed=True,hardware_sha256=sha(folder/'inference-hardware.json'))
    except BaseException as error:outcome['failure']=type(error).__name__;raise
    finally:outcome['finished_at_utc']=datetime.now(timezone.utc).isoformat();write(out/'outcome.json',outcome)
    return outcome
def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--binding',required=True);a.add_argument('--scope',required=True);a.add_argument('--out',required=True);a.add_argument('--expected-vllm',required=True);args=a.parse_args()
    print(json.dumps(run(args)));return 0
if __name__=='__main__':raise SystemExit(main())
