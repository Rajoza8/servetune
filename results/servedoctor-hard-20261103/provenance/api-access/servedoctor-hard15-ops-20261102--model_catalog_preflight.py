#!/usr/bin/env python3
"""Authenticated GET-only catalog preflight using the existing private worker."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent.parent
sys.path.insert(0,str(REPO/'runs/servedoctor-hard-ops-20261102'))
from prepare_preflight_hard_study import verify_catalog
LABEL='ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)'

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args()
    out=Path(a.out).resolve()
    if out.parent!=ROOT:raise ValueError('Direct OPS15 output required')
    out.mkdir(exist_ok=False)
    with (out/'catalog.stdout').open('xb') as stdout,(out/'catalog.stderr').open('xb') as stderr:
        done=subprocess.run([sys.executable,str(ROOT/'key_runner.py'),'submit','--','diagnose-models'],cwd=REPO,stdout=stdout,stderr=stderr,timeout=110)
    report={'project':'servedoctor-hard15-20261102','label':LABEL,'get_only':True,'paid_call':False,'returncode':done.returncode,'passed':False}
    try:
        if done.returncode:raise RuntimeError('Catalog request failed')
        value=json.loads((out/'catalog.stdout').read_text())
        verify_catalog(value,'4b0add12be36cef0d0776607f683310b1641b0f7')
        report.update(passed=True,models=['muse-spark-1.3','muse-wonder-1.0'])
    except BaseException as error:report['failure']=type(error).__name__
    with (out/'outcome.json').open('x') as f:json.dump(report,f,indent=2);f.write('\n')
    print(json.dumps(report),flush=True);return int(not report['passed'])

if __name__=='__main__':raise SystemExit(main())
