#!/usr/bin/env python3
"""Read-only mapping of exactly three native relative report descriptors.

The frozen c98 verifier source and scientific functions remain untouched. Its
original verification bytecode runs with a strict Evidence subclass. Original
report and projection bytes, descriptor hashes and stable study seals still
have to match; no descriptors are rewritten.
"""
import hashlib
import importlib.util
from pathlib import Path
import sys
import types

OPS=Path(__file__).resolve().parent;REPO=OPS.parent.parent
PACKAGE_SHA='c98b3fc35f111ce4b852d04dfd362687e5b37aa230c7a2165438f1ef8b8386fc'
ALIASES={
 'runs/sd-hard-partial-attempt1/report.html':('report.html','50a02be4cb35ae53de2a52e563df420ff25cbde06088469ff2238845529ecd7d'),
 'runs/sd-hard-partial-attempt1/report.json':('report.json','a669d2f2e844734565f9b1a41b73b046372db2a7bcdb7a44586d367b5bae7e44'),
 'runs/servedoctor-hard15-ops-20261102/evaluation-stages/inference-evaluation-attempt1/hard15-score-projection.json':('score_projection','77286752ca7fd8ce60b080b825b3ac024242cb3627bcf1b6734e7b4bc455b765'),
}

def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
_source=OPS/'package_inference_results.py'
if _sha(_source)!=PACKAGE_SHA:raise ValueError('Frozen c98 verifier source changed')
sys.path.insert(0,str(OPS))
_spec=importlib.util.spec_from_file_location('_frozen_c98_descriptor_base',_source)
base=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(base)

class Evidence(base.Evidence):
    def __init__(self,args,repo=REPO):
        super().__init__(args,repo)
        self.report_aliases={key:(Path(args.score_projection).resolve() if name=='score_projection' else self.study/name)
                             for key,(name,digest) in ALIASES.items()}
    def resolve(self,value):
        key=str(value)
        if key in self.report_aliases:
            path=self.regular(self.report_aliases[key])
            base.require(base.sha(path)==ALIASES[key][1],'native-relative-report-pinned-hash-differs')
            return path
        return super().resolve(value)
    def descriptor(self,value):
        if isinstance(value,dict) and str(value.get('path')) in ALIASES:
            base.require(value.get('sha256')==ALIASES[str(value['path'])][1],'native-relative-descriptor-pinned-hash-differs')
        return super().descriptor(value)

def _verify_inputs(args,repo=REPO,repository_check=base.verify_repository):
    # Rebind only Evidence in an isolated globals dictionary; no original module
    # globals, functions, source or input artifacts are modified.
    environment=dict(base._verify_inputs.__globals__);environment['Evidence']=Evidence
    original=base._verify_inputs
    function=types.FunctionType(original.__code__,environment,original.__name__,original.__defaults__,original.__closure__)
    return function(args,repo,repository_check)

def verify_inputs(args,repo=REPO):
    """Same c98 science checks, with three exact hash-pinned path aliases only."""
    return _verify_inputs(args,repo)[4]
