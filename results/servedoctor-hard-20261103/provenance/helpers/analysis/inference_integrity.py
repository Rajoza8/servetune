#!/usr/bin/env python3
"""Portable operator gates for unchanged recorded Hard15 inputs on a new inference host.

Historical GPU descriptors map to verified copies; none are rewritten. Two
unavailable ancillary JSON files remain explicitly unavailable. This adapter
does not claim the old full verify_freeze gate passed. Native science is unchanged.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys

import cpu_rules_adapter as portable
p=portable.p
OPS=Path(__file__).resolve().parent;REPO=OPS.parent.parent
PROJECT=p.PROJECT;LABEL=p.LABEL;SOURCE=p.HEAD;PRIMARY=p.PRIMARY
PROTOCOL='inference-analysis-protocol.json';MARKER='inference-validation-dispatch.json'
EVIDENCE='portable-recording-evidence';BINDING='inference-rental-attempt1/binding.json'
AMEND='8efba5368ca146e45ff55d16fb45567058ae015bcee51a26a5510a0e31c4ee2a'
DECLARED='88300ba18c5fb4a4cd5478794261fab4c3a724791df9f6e880501b742c9fc0fa'
CLOSURE='8daefb611817aaa8a460bd10c255ba262623bafbf679437210bf442dbfe6ba97'
PRESERVED='505d7d74d4a978f1de9058380c3d38b85826d7c06affe1d7cffcabe16032d068'
MISSING=(('preflight-readiness.json','142e8954be0e8a31414ccfbf6bdc973944f7783e04dba113d1e946dd06f152a5'),
 ('preflight-readiness-declaration.json','8b5534f7b3cb315e6ed8ac25f154ec8e529ae460f1775aabd7c7e2f6da6c5b99'))
HELPERS=('inference_integrity.py','inference_key_runner.py','inference_report_common.py','inference_measure_contexts.py',
 'inference_response_guard.py','inference_export_scores.py','inference_evaluation_stage.py')
TRANSPORT=p.legacy.TRANSPORT
ARCHIVED_TRANSPORT='operator-provenance/original-api-transport'
def require(v,msg):
    if not v:raise ValueError(msg)
def load(x):return p.load(x)
def sha(x):return p.sha(x)
def desc(x):return p.desc(x)
def utc():return datetime.now(timezone.utc).isoformat()
def write(x,v):return p.write_new(x,v)
def regular(x):return p.gate.regular(x)
def inventory(x):return p.gate.inventory(x)
def verify_source_policy(repo=REPO,expected_commit=None):
    require(expected_commit in (None,SOURCE),'inference-source-must-stay4b')
    return p.gate.verify_source_policy(repo,SOURCE)
def root_at(root,repo):
    repo=Path(repo).resolve();root=Path(root).absolute()
    require(root==repo/PRIMARY and not root.is_symlink(),'canonical-fresh-analysis-path-required');return root,repo
def mapper(root,repo):
    from argparse import Namespace
    ops=repo/p.OPS_REL;folder=ops/EVIDENCE;prefix=p.REMOTE+'/'+p.OLD_OPS_REL+'/record-stages/'
    a=Namespace(study_dir=str(root),original_study_dir=str(repo/p.ORIGINAL),remote_ops=str(ops),remote_old_ops=str(repo/p.OLD_OPS_REL),
       remote_control=str(folder/'control'),calibration_mirror=str(folder/'calibration'),map=[
       (prefix+'record-first9-attempt1',str(folder/'first9-proofs/recording-stage')),
       (prefix+'record-last8-attempt1',str(folder/'latest/recording-stage'))])
    return portable.evidence(a,repo)
def binding(repo):
    ops=repo/p.OPS_REL;path=regular(ops/BINDING);value=load(path)
    scope=regular(ops/'inference-rental-attempt1/rental-scope.json');s=load(scope)
    require(value.get('project')=='servedoctor-hard15-inference-20261103' and value.get('purpose')=='inference-only'
       and value.get('recording_instance_id')==p.INSTANCE and type(value.get('instance_id')) is int
       and value['instance_id']>0 and value['instance_id'] not in (p.INSTANCE,58690026,58716527)
       and value.get('rental_scope_sha256')==sha(scope) and s.get('instance_id')==value['instance_id']
       and s.get('project')==value['project'] and value.get('budget_amendment',{}).get('sha256')==AMEND
       and sha(regular(ops/'gpu-budget-amendment-43-20261102.json'))==AMEND,'new-inference-binding-differs')
    return path,value
def recording_gate(root,repo=REPO):
    root,repo=root_at(root,repo);verify_source_policy(repo)
    require(sha(p.__file__)=='a183e08da6dbf174e2a8f632afb84b5285939ea0357bfedc6cb59f12b9a617b0'
       and sha(portable.__file__)=='26f175ab374416f2147ea085f1de7c18c5bb440ada93361c0790148d51e95c97'
       and sha(p.gate.__file__)=='eca7c03250aa7b75439ce9b6505c648d4584c3f5fbdba48b341d42ab78b813c5','portable-verifier-dependency-differs')
    e=mapper(root,repo);folder=repo/p.OPS_REL/EVIDENCE;origin=e.original
    require(sha(regular(folder/'preserved-files-manifest.json'))==PRESERVED and sha(regular(folder/'preservation-receipt.json'))==p.PRESERVATION,'preservation-commitment-differs')
    saved=load(folder/'preserved-files-manifest.json')['files'];before={n[len('latest/study/'):]:h for n,h in saved.items() if n.startswith('latest/study/')}
    require(len(before)==178 and inventory(origin)==before,'original178-byte-inventory-differs')
    frozen=load(regular(origin/p.legacy.FREEZE))
    require(sha(origin/p.legacy.FREEZE)==p.FREEZE and frozen.get('source_commit')==SOURCE and frozen.get('study_dir')==p.ORIGINAL
       and frozen.get('project')==p.RENTAL_PROJECT and sha(repo/'configs/servedoctor-hard.json')==p.CONFIG,'original-freeze-or-source-differs')
    for relative,digest in frozen['files_sha256'].items():require(sha(e.frozen_file(relative))==digest,'frozen-source-or-input-differs')
    require(p.legacy.transport_inventory(origin)==frozen['optional_transport_sha256'] and p.legacy.commitments(origin)==frozen['scientific_commitments'],'frozen-commitment-or-transport-differs')
    p.legacy.no_decisions(origin)
    require(not (origin/'answers/validity.json').exists() and not (origin/'incidents/hard-16').exists()
       and sha(regular(origin/'engines/engine-06-hard-16/engine.log'))==p.FAILURE_LOG,'original16-attempt-changed')
    missing=[]
    def descriptors(v):
        if isinstance(v,dict):
            if {'path','sha256'}<=v.keys():
                known=next((h for n,h in MISSING if v['path']==p.REMOTE+'/'+p.OLD_OPS_REL+'/'+n),None)
                if known:require(v['sha256']==known,'missing-metadata-commitment-differs');missing.append(v)
                else:e.descriptor(v)
            for item in v.values():descriptors(item)
        elif isinstance(v,list):
            for item in v:descriptors(item)
    descriptors({k:frozen.get(k) for k in ('preflight','calibration','calibration_provenance','reason_receipt')})
    require(len(missing)==2,'exact-two-historical-metadata-gaps-required')
    history=regular(folder/'declare-readiness.stdout');require(sha(history)==DECLARED,'historical-readiness-attestation-differs');attested=load(history)
    require(attested.get('recording_ready') is True and attested.get('source_commit')==SOURCE and attested.get('gpu_uuid')==p.GPU
       and attested.get('readiness_sha256')==MISSING[0][1],'historical-readiness-fields-differ')
    require(sha(regular(folder/'original-portable-closure-audit.json'))==CLOSURE,'original-closure-audit-differs')
    closure=load(folder/'original-portable-closure-audit.json')
    for item in closure['failed_stopped_export'].values():
        candidate=regular(folder/'stopped-preflight-recovery-attempt1'/Path(item['path']).name);require(sha(candidate)==item['sha256'],'failed-export-evidence-differs')
    origin_cal=frozen['calibration_provenance'];cal=e.descriptor(frozen['calibration'])
    if 'calibration_files_sha256' in origin_cal:require(inventory(cal.parent)==origin_cal['calibration_files_sha256'],'original-calibration-inventory-differs')
    proofs=[];prefix=p.REMOTE+'/'+p.OLD_OPS_REL+'/record-stages/'
    for name in p.gate.OWNED:
        raw=prefix+name;path=e.resolve(raw)
        local=path.relative_to(folder).as_posix();require(saved.get(local)==sha(path),'owned-proof-not-in-preserved-manifest')
        proofs.append({'path':raw,'sha256':sha(path)})
    quality=portable.quality(e,frozen,proofs)
    require(inventory(origin)==before,'original-mutated-during-quality-audit')
    return e,frozen,{'project':PROJECT,'label':LABEL,'complete':True,'quality':quality,'original_inventory_sha256':before,
       'missing_ancillary_metadata':missing,'old_full_verify_freeze_claimed':False,'historical_readiness_stdout':desc(history),
       'original_closure_audit':desc(folder/'original-portable-closure-audit.json'),'source_commit':SOURCE,'original_freeze_sha256':p.FREEZE}
def inference_hardware(repo,frozen):
    path,value=binding(repo);hardware=regular(repo/p.OPS_REL/'inference-hardware.json');v=load(hardware)
    require(v.get('project')==value['project'] and v.get('instance_id')==value['instance_id']
      and v.get('rental_scope_sha256')==value['rental_scope_sha256'] and v.get('container_id_matches_scope') is True
      and v.get('source_commit')==SOURCE and v.get('model_revision')==p.legacy.REV and v.get('dtype')=='bf16'
      and v.get('vllm_version')==frozen['job_policy']['vllm_version'] and isinstance(v.get('gpu_uuid'),str)
      and v['gpu_uuid'].startswith('GPU-'),'inference-hardware-or-runtime-differs')
    return desc(path),desc(hardware)
def helper_hashes(repo):return {n:sha(regular(repo/p.OPS_REL/n)) for n in HELPERS}
def transport(root,repo):
    _,bound=binding(repo);files={n:sha(regular(root/n)) for n in TRANSPORT}
    config=load(root/TRANSPORT[0]);ready=load(root/TRANSPORT[1]);channel=load(root/TRANSPORT[2])
    require(set(config)=={'project','instance_id','meta_https_connect_proxy'} and config['project']=='servedoctor'
      and config['instance_id']==bound['instance_id'],'inference-transport-config-scope-differs')
    from servedoctor.llm import _meta_proxy_address
    _meta_proxy_address(config['meta_https_connect_proxy'])
    require(ready.get('instance_id')==bound['instance_id'] and ready.get('source_commit')==SOURCE
      and ready.get('transport_config_sha256')==files[TRANSPORT[0]] and ready.get('origin')=='local_mac'
      and ready.get('allowed_target')=='api.meta.ai:443' and ready.get('tls_end_to_end') is True
      and ready.get('keys_visible_to_relay') is False and bound['rental_scope_sha256'] in ready.get('evidence_sha256',{}).values(),
      'inference-transport-ready-proof-differs')
    require(channel.get('instance_id')==bound['instance_id'] and channel.get('source_commit')==SOURCE
      and channel.get('transport_config_sha256')==files[TRANSPORT[0]] and channel.get('transport_ready_sha256')==files[TRANSPORT[1]]
      and channel.get('origin')=='local_mac' and channel.get('method')=='GET' and channel.get('url')=='https://api.meta.ai/v1/models'
      and channel.get('http_status')==401 and channel.get('tls_verified') is True and channel.get('authenticated') is False
      and channel.get('authorization_sent') is False and channel.get('body_read') is False
      and channel.get('through_configured_transport') is True and channel.get('verified') is True,'inference-transport-channel-proof-differs')
    return files
def install_analysis_transport(root,origin,repo):
    fresh=repo/p.OPS_REL/'inference-transport-attempt1';transport(fresh,repo)
    old=p.legacy.transport_inventory(origin);archive=root/ARCHIVED_TRANSPORT;archive.mkdir(parents=True)
    for name,digest in old.items():
        if digest is not None:
            shutil.move(str(root/name),str(archive/name));require(sha(archive/name)==digest,'archived-original-transport-differs')
    for name in TRANSPORT:shutil.copyfile(regular(fresh/name),root/name)
    return {'mode':'meta-https-connect-local-mac','original_files_sha256':old,
       'archived_original_directory':ARCHIVED_TRANSPORT,'analysis_files_sha256':transport(root,repo)}
def prepare(root,repo=REPO):
    root,repo=root_at(root,repo);require(not root.exists(),'fresh-analysis-directory-required')
    e,frozen,proof=recording_gate(root,repo);b,h=inference_hardware(repo,frozen)
    exclusion=regular(repo/p.OPS_REL/'exclusion.json');p.gate.exclusion(exclusion)
    transport(repo/p.OPS_REL/'inference-transport-attempt1',repo)
    before=proof['original_inventory_sha256'];shutil.copytree(e.original,root)
    require(inventory(root)==before,'opaque-copy-differs')
    selected_transport=install_analysis_transport(root,e.original,repo)
    value={'project':PROJECT,'label':LABEL,'created_at_utc':utc(),'source_commit':SOURCE,'study_dir':PRIMARY,'original_study_dir':p.ORIGINAL,
       'included_hard_ids':list(p.IDS),'excluded_ids':['hard-16'],'original_inventory_sha256':before,'scientific_inputs_changed':False,
       'old_helpers_changed':False,'recording_gpu_uuid':p.GPU,'recording_instance_id':p.INSTANCE,'inference_binding':b,'inference_hardware':h,
       'budget_amendment_sha256':AMEND,'private_helpers_sha256':helper_hashes(repo),'portable_recording_gate':proof,
       'api_transport':selected_transport,
       'exclusion':desc(exclusion),'operator_changes':'Path, provenance and new inference-host bindings only; original sealed observations, native validity, prompts, rules, scoring and model settings unchanged.'}
    write(root/PROTOCOL,value);(root/'analysis-label.txt').write_text(LABEL+'\n');verify_freeze(root,repo)
    return {'project':PROJECT,'label':LABEL,'prepared':True,'total':15,'protocol_sha256':sha(root/PROTOCOL),'inference_binding_sha256':b['sha256']}
def verify_freeze(root,repo=REPO):
    root,repo=root_at(root,repo);e,frozen,proof=recording_gate(root,repo);v=load(regular(root/PROTOCOL));b,h=inference_hardware(repo,frozen)
    require(v.get('project')==PROJECT and v.get('label')==LABEL and v.get('study_dir')==PRIMARY and v.get('source_commit')==SOURCE
       and v.get('included_hard_ids')==list(p.IDS) and v.get('excluded_ids')==['hard-16'] and v.get('scientific_inputs_changed') is False
       and v.get('old_helpers_changed') is False and v.get('original_inventory_sha256')==proof['original_inventory_sha256']
       and v.get('inference_binding')==b and v.get('inference_hardware')==h and v.get('private_helpers_sha256')==helper_hashes(repo)
       and v.get('portable_recording_gate')==proof and v.get('budget_amendment_sha256')==AMEND,'portable-inference-protocol-differs')
    authorized=p.gate.exclusion(regular(v['exclusion']['path']));require(desc(v['exclusion']['path'])==v['exclusion'],'exclusion-changed')
    require(datetime.fromisoformat(v['created_at_utc'])>=datetime.fromisoformat(authorized['recorded_at_utc']),'protocol-precedes-user-exclusion')
    selected=transport(root,repo);original_transport=p.legacy.transport_inventory(e.original)
    require(v.get('api_transport')=={'mode':'meta-https-connect-local-mac','original_files_sha256':original_transport,
       'archived_original_directory':ARCHIVED_TRANSPORT,'analysis_files_sha256':selected},'inference-transport-protocol-differs')
    for name,digest in proof['original_inventory_sha256'].items():
        copied=root/ARCHIVED_TRANSPORT/name if name in TRANSPORT else root/name
        require(sha(regular(copied))==digest,'copied-original-byte-differs')
    require((root/'analysis-label.txt').read_text()==LABEL+'\n' and {x.name for x in (root/'incidents').iterdir()}==set(p.ALL_IDS),'analysis-label-or-recording-coverage-differs')
    return {**frozen,'project':PROJECT,'label':LABEL,'protocol_sha256':sha(root/PROTOCOL),'inference_binding_sha256':b['sha256']}
def validate_once(root,out,repo=REPO,run=subprocess.run):
    root,repo=root_at(root,repo);out=Path(out).absolute();frozen=verify_freeze(root,repo)
    require(out.parent==repo/p.OPS_REL and not out.exists(),'fresh-direct-inference-validation-output-required')
    p.legacy.no_decisions(root);require(not (root/'answers/validity.json').exists() and not (root/MARKER).exists(),'native-validation-already-dispatched-never-retry')
    out.mkdir();before=p.gate.bytes_inventory(root);dispatch={'project':PROJECT,'label':LABEL,'created_at_utc':utc(),'protocol':desc(root/PROTOCOL),'recording_bytes_sha256':before,'inference_binding_sha256':frozen['inference_binding_sha256']}
    write(out/'dispatch.json',dispatch);write(root/MARKER,{'project':PROJECT,'label':LABEL,'dispatch':desc(out/'dispatch.json')})
    result={'project':PROJECT,'label':LABEL,'completed':False,'returncode':None,'failure':None,'dispatch':desc(out/'dispatch.json'),'study_dispatch_sha256':sha(root/MARKER)}
    try:
        with (out/'validate.stdout').open('xb') as stdout,(out/'validate.stderr').open('xb') as stderr:
            done=run([sys.executable,'-m','servedoctor','validate','--study-dir',PRIMARY],cwd=repo,stdout=stdout,stderr=stderr)
        result['returncode']=done.returncode;require(done.returncode==0,'native-validation-failed')
        require(p.gate.bytes_inventory(root)==before,'recordings-mutated-during-validation');verify_freeze(root,repo)
        result.update(p.gate.validity_summary(root));result['completed']=True
    except BaseException as error:result['failure']=type(error).__name__
    result.update(stdout_sha256=sha(out/'validate.stdout'),stderr_sha256=sha(out/'validate.stderr'),finished_at_utc=utc());write(out/'result.json',result);return result
def verify_evaluation(root,validation_dir,repo=REPO):
    root,repo=root_at(root,repo);frozen=verify_freeze(root,repo);directory=Path(validation_dir).absolute()
    require(directory.parent==repo/p.OPS_REL,'inference-validation-output-scope-differs')
    marker=load(regular(root/MARKER));dispatch=load(regular(directory/'dispatch.json'));result=load(regular(directory/'result.json'))
    require(marker.get('project')==PROJECT and marker.get('label')==LABEL and marker.get('dispatch')==desc(directory/'dispatch.json')
      and dispatch.get('project')==PROJECT and dispatch.get('label')==LABEL and result.get('project')==PROJECT and result.get('label')==LABEL
      and dispatch.get('protocol')==desc(root/PROTOCOL) and dispatch.get('inference_binding_sha256')==frozen['inference_binding_sha256']
      and result.get('completed') is True and result.get('returncode')==0 and not result.get('failure') and result.get('dispatch')==desc(directory/'dispatch.json')
      and result.get('study_dispatch_sha256')==sha(root/MARKER) and p.gate.bytes_inventory(root)==dispatch['recording_bytes_sha256'],'immutable-inference-validation-incomplete')
    require(datetime.fromisoformat(dispatch['created_at_utc'])>=datetime.fromisoformat(load(root/PROTOCOL)['created_at_utc']),'validation-dispatch-precedes-protocol')
    for n in ('stdout','stderr'):require(result.get(n+'_sha256')==sha(regular(directory/('validate.'+n))),'validation-stream-differs')
    require(all(result.get(k)==v for k,v in p.gate.validity_summary(root).items()),'native-validity-mutated')
    return {'project':PROJECT,'label':LABEL,'source_commit':SOURCE,'evaluation_ready':True,'total':15,'protocol_sha256':frozen['protocol_sha256'],'validation_sha256':sha(directory/'result.json'),'inference_binding_sha256':frozen['inference_binding_sha256']}
def evaluation_gate(root,repo=REPO):
    root=Path(root).absolute();marker=load(regular(root/MARKER));return verify_evaluation(root,Path(marker['dispatch']['path']).parent,repo)
def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('operation',choices=('prepare','verify-freeze','validate-once','verify-evaluation'));a.add_argument('--study-dir',default=PRIMARY);a.add_argument('--out');args=a.parse_args();root=Path(args.study_dir);root=root if root.is_absolute() else REPO/root
    if args.operation=='prepare':v=prepare(root)
    elif args.operation=='verify-freeze':f=verify_freeze(root);v={'project':PROJECT,'label':LABEL,'source_commit':SOURCE,'protocol_sha256':f['protocol_sha256'],'inference_binding_sha256':f['inference_binding_sha256']}
    elif args.operation=='validate-once':v=validate_once(root,args.out)
    else:v=verify_evaluation(root,args.out)
    print(json.dumps(v));return 0 if v.get('completed',True) else 1
if __name__=='__main__':raise SystemExit(main())
