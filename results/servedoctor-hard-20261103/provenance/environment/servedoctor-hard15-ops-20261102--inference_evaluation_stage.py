#!/usr/bin/env python3
"""Run the explicitly approved fifteen-case analysis after one-shot validation.

No retries, ledger initialization, source updates, transport staging or GPU
lifecycle operations. All raw command streams are retained privately; progress
contains only stage names, aggregate metrics and safe exception classes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time

from inference_report_common import OPS, REPO, IDS, LABEL, PROJECT, RENTAL_PROJECT, approved_root, load, sha, write_new
import inference_key_runner as key_runner

REMOTE_REPO = '/workspace/servedoctor-hard/servetune'
REMOTE_OPS = 'runs/servedoctor-hard15-ops-20261102'
REMOTE_TOOL = OPS/'inference_remote.py'
HELPER_PROOF = 'inference-evaluation-stage-fixtures.json'
REV = key_runner.REV
CUTOFF = datetime(2026, 11, 3, 23, tzinfo=timezone.utc).timestamp()
SEED = '13f777ed328bb0c71bb2063b6b12cf3b6cb8024d78b0ab46b9e374521a566123'
HELPERS = ('inference_report_common.py', 'inference_measure_contexts.py', 'inference_response_guard.py', 'inference_export_scores.py')

PREPARE = r'''
import hashlib,json,sys
from pathlib import Path
out=Path(sys.argv[1]);expected=json.loads(sys.argv[2]);root=Path(sys.argv[3])
for name,h in expected.items():
    path=Path('runs/servedoctor-hard15-ops-20261102')/name
    assert path.is_file() and not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest()==h
sys.path.insert(0,'runs/servedoctor-hard15-ops-20261102')
from inference_report_common import evaluation_gate
proof=evaluation_gate(root)
assert not (root/'decisions').is_symlink()
assert not any(p.is_file() or p.is_symlink() for p in (root/'decisions').rglob('*')) if (root/'decisions').exists() else True
out.mkdir(parents=True,exist_ok=False)
print(json.dumps(proof))
'''
LEDGER = r'''
import hashlib,json
from pathlib import Path
from servedoctor.llm import Ledger
path=Path('runs/servedoctor-ledger.json')
assert path.is_file() and not path.is_symlink()
summary=Ledger(path).summary()
print(json.dumps({'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'summary':summary}))
'''
ARCHIVE = r'''
import hashlib,json,sys,tarfile
from pathlib import Path
root,out=map(Path,sys.argv[1:]);ledger=Path('runs/servedoctor-ledger.json')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def inventory():
    result={}
    for path in sorted(root.rglob('*')):
        assert not path.is_symlink()
        if path.is_file():result[path.relative_to(root).as_posix()]=sha(path)
    return result
before=inventory();h=sha(ledger);target=out/'study-ledger.tar.gz'
with tarfile.open(target,'x:gz') as archive:
    archive.add(root,arcname='study');archive.add(ledger,arcname='canonical-ledger.json')
    proofs=Path('runs/servedoctor-hard15-ops-20261102/inference-key-runner-dispatches')
    for path in sorted(proofs.glob('*/proofs.jsonl')):
        assert not path.is_symlink()
        archive.add(path,arcname='dispatch-proofs/'+path.parent.name+'/proofs.jsonl')
    for name in ('contexts.json','rules-spark-wonder-responses.json','glimmer-cascades-responses.json','hard15-score-projection.json'):
        path=out/name
        if path.exists():
            assert path.is_file() and not path.is_symlink()
            archive.add(path,arcname='evaluation-proof/'+name)
assert inventory()==before and sha(ledger)==h
manifest=out/'mirror-manifest.json'
value={'study_files_sha256':before,'ledger_sha256':h,'archive_sha256':sha(target),
       'archive_bytes':target.stat().st_size,'study_file_count':len(before),'stable':True}
with manifest.open('x') as stream:json.dump(value,stream,indent=2);stream.write('\n')
print(json.dumps({'archive':str(target),'archive_sha256':value['archive_sha256'],
                 'manifest':str(manifest),'manifest_sha256':sha(manifest),
                 'ledger_sha256':h,'study_file_count':len(before),'stable':True}))
'''


LABEL_REPORT = r'''
import hashlib,html,json,sys
from pathlib import Path
root,projection=map(Path,sys.argv[1:]);label='ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)'
score=json.loads(projection.read_text());assert score['label']==label and score['decision_coverage']=={'expected':90,'present':90}
def descriptor(path):
    assert path.is_file() and not path.is_symlink()
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
value={'project':'servedoctor-hard15-20261102','label':label,'native_report_html':descriptor(root/'report.html'),
       'native_report_json':descriptor(root/'report.json'),'score_projection':descriptor(projection),
       'scoreboards':score['scoreboards'],'denominators':score['denominators'],
       'interpretation':'The original sixteen-case frozen specification and failed hard-16 evidence are retained. This report covers only the fifteen predeclared retained incidents; it is not a full sixteen-case result.'}
with (root/'analysis-report.json').open('x') as stream:json.dump(value,stream,indent=2);stream.write('\n')
with (root/'analysis-report.html').open('x') as stream:
    stream.write('<!doctype html><meta charset="utf-8"><title>'+html.escape(label)+'</title><h1>'+html.escape(label)+'</h1><p>'+html.escape(value['interpretation'])+'</p><p>The embedded native report is unchanged provenance for this fifteen-case analysis.</p><iframe title="Native fifteen-case report" src="report.html" style="width:100%;height:90vh;border:0"></iframe>')
print(json.dumps({'project':value['project'],'label':label,'analysis_report_json':descriptor(root/'analysis-report.json'),'analysis_report_html':descriptor(root/'analysis-report.html')}))
'''


def readiness(ops=OPS, clock=time.time):
    active = load(Path(ops) / 'inference-rental-attempt1' / 'active-command.json')
    now = clock()
    until, at = active.get('deadline_epoch'), active.get('at_epoch')
    if (active.get('project') != RENTAL_PROJECT or active.get('pid') not in (os.getpid(), os.getppid())
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in (until, at))
            or not 0 <= now-at <= 90 or not now+360 < until <= min(CUTOFF, now+10800)):
        raise ValueError('A fresh owning Hard phase with cleanup allowance is required')
    info = key_runner.SOCKET.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError('The private Hard key server must be ready')
    return until-360, until-180


def execute(args, *, ops=OPS, repo=REPO, run=subprocess.run, clock=time.time, ready=readiness):
    ops, repo = Path(ops).resolve(), Path(repo).resolve()
    study = approved_root(args.study_dir, repo).relative_to(repo).as_posix()
    out = Path(args.out)
    if not out.is_absolute(): out = repo/out
    if out.parent.resolve()!=ops or not re.fullmatch('[a-z0-9][a-z0-9-]{0,95}',out.name):
        raise ValueError('Fresh direct Hard OPS output directory required')
    if not re.fullmatch('[0-9a-f]{64}',args.expected_ledger_sha256):
        raise ValueError('Exact expected canonical ledger SHA required')
    work_deadline, cleanup_deadline = ready(ops, clock)
    max_work = getattr(args, 'max_work_seconds', 7800)
    if type(max_work) is not int or not 300 <= max_work <= 9000:
        raise ValueError('Model work must fit a fixed 300 to 9000 second envelope')
    work_deadline = min(work_deadline, clock()+max_work)
    cleanup_deadline = min(cleanup_deadline, work_deadline+180)
    out.mkdir(exist_ok=False)
    remote_out = REMOTE_OPS+'/evaluation-stages/'+out.name
    remote = [sys.executable,str(REMOTE_TOOL if repo==REPO else repo/'runs/servedoctor-hard15-ops-20261102/inference_remote.py')]
    runner = [sys.executable,str(ops/'inference_key_runner.py'),'submit','--']
    result = {'project':PROJECT,'label':LABEL,'study_dir':study,'completed':False,
              'failure':None,'cleanup_errors':[],'groups':[], 'work_deadline_epoch':work_deadline,
              'evidence_directory':str(out), 'cleanup_deadline_epoch':cleanup_deadline,
              'max_model_work_seconds':max_work,'inference_only':True,'recording_instance_id':58866756}
    deadline = work_deadline
    prepared = False

    def command(label, argv, timeout=180):
        remaining = deadline-clock()
        if remaining<=0: raise TimeoutError('Bounded stage deadline reached')
        with (out/(label+'.stdout')).open('xb') as stdout, (out/(label+'.stderr')).open('xb') as stderr:
            finished = run(argv,cwd=repo,stdout=stdout,stderr=stderr,timeout=min(timeout,remaining))
        if finished.returncode: raise subprocess.CalledProcessError(finished.returncode,argv)
        return out/(label+'.stdout')

    def json_command(label, argv, timeout=180):
        text = command(label,argv,timeout).read_text()
        return json.loads(text[text.index('{'):])  # Only fixed safe JSON commands enter here.

    def remote_run(label, argv, timeout=180):
        return command(label,[*remote,'run',*argv],timeout)

    def snapshot(label, scores=True):
        value = json_command(label+'-ledger', [*remote,'run','python3','-c',LEDGER])
        summary = value['summary']
        if summary['caps_usd']!={'meta':50.0,'baseten':20.0}: raise ValueError('Canonical ledger caps differ')
        target = out/(label+'-canonical-ledger.json')
        command(label+'-ledger-mirror', [*remote,'get',REMOTE_REPO+'/runs/servedoctor-ledger.json',str(target)])
        if sha(target)!=value['sha256']: raise ValueError('Canonical ledger changed during mirror')
        if scores:
            value['scoreboards'] = {}
            for name, extra in [('all',[]),('valid_only',['--valid-only'])]:
                value['scoreboards'][name] = json_command(label+'-score-'+name,
                    [*remote,'run','python3','-m','servedoctor','score','--study-dir',study,'--split','hard',*extra])
        value.update(project=PROJECT,label=LABEL)
        write_new(out/(label+'-summary.json'),value)
        print(json.dumps({'stage':label, **value}),flush=True)
        if summary['warnings']: raise RuntimeError('Ledger warning; later work halted')
        return value

    try:
        hashes = {name:sha(ops/name) for name in HELPERS}
        tested = load(ops/HELPER_PROOF)
        if (tested.get('returncode')!=0 or tested.get('py_compile')!='passed'
                or any(tested.get('files_sha256',{}).get(name)!=digest for name,digest in hashes.items())):
            raise ValueError('Uploaded helper bytes lack the passing fixture proof')
        remote_run('prepare-private-directory', ['python3','-c',
            "from pathlib import Path; p=Path('runs/servedoctor-hard15-ops-20261102'); assert not p.is_symlink(); p.mkdir(exist_ok=True)"])
        for name in HELPERS:
            command('upload-'+name.replace('.py',''),[*remote,'put',str(ops/name),REMOTE_REPO+'/'+REMOTE_OPS+'/'+name])
        gate = json_command('integrity-preflight', [*remote,'run','python3','-c',PREPARE,
                                                  remote_out,json.dumps(hashes),study])
        if gate.get('evaluation_ready') is not True or gate.get('total')!=15 or gate.get('label')!=LABEL or gate.get('project')!=PROJECT:
            raise ValueError('GPU immutable validation proof incomplete')
        prepared = True
        initial = snapshot('initial',scores=False)
        if initial['sha256']!=args.expected_ledger_sha256: raise ValueError('Canonical ledger lineage expectation differs')
        context = json_command('contexts', [*remote,'run','python3',REMOTE_OPS+'/inference_measure_contexts.py',
                                           '--study-dir',study,'--out',remote_out+'/contexts.json'],timeout=600)
        if (context.get('incidents')!=15 or context.get('label')!=LABEL or context.get('project')!=PROJECT or context.get('fits_8192') is not True
                or set(context.get('per_incident_maximum',{}))!=set(IDS)
                or context.get('model_revision')!=REV):
            raise ValueError('All fifteen retained Hard contexts must fit the unchanged evaluation capacity')
        write_new(out/'contexts.json',context)
        groups = [('rules-spark-wonder','rules,spark,wonder',[]),
                  ('glimmer-cascades','glimmer,glimmer_to_spark,glimmer_to_wonder',
                   ['--start-glimmer','--model-revision',REV])]
        for label, arms, extra in groups:
            print(json.dumps({'project':PROJECT,'label':LABEL,'stage':label,'event':'dispatching'}),flush=True)
            failure = None
            try:
                command(label+'-evaluate', [*runner,'evaluate','--study-dir',study,'--split','hard',
                                          '--arms',arms,*extra],timeout=9000)
            except BaseException as exc: failure = exc
            try: snapshot(label)
            except BaseException as exc:
                result['cleanup_errors'].append({'stage':label+'-snapshot','class':type(exc).__name__})
                if failure is None: failure = exc
            if failure is not None: raise failure
            checked = json_command(label+'-responses', [*remote,'run','python3',REMOTE_OPS+'/inference_response_guard.py',
                '--study-dir',study,'--arms',arms,'--out',remote_out+'/'+label+'-responses.json'])
            if (checked.get('ready_for_next_group') is not True or checked.get('label')!=LABEL
                    or checked.get('project')!=PROJECT): raise ValueError('Response group incomplete')
            result['groups'].append(label)
        projection = json_command('score-export', [*remote,'run','python3',REMOTE_OPS+'/inference_export_scores.py',
            '--study-dir',study,'--out',remote_out+'/hard15-score-projection.json'])
        write_new(out/'score-export-summary.json',projection)
        command('score-export-mirror', [*remote,'get',REMOTE_REPO+'/'+remote_out+'/hard15-score-projection.json',
                                       str(out/'hard15-score-projection.json')])
        remote_run('native-report', ['python3','-m','servedoctor','report','--study-dir',study])
        remote_run('label-report', ['python3','-c',LABEL_REPORT,study,remote_out+'/hard15-score-projection.json'])
        result['completed'] = True
    except BaseException as exc:
        result['failure'] = {'class':type(exc).__name__,'returncode':getattr(exc,'returncode',None)}
    finally:
        deadline = cleanup_deadline
        try: snapshot('final',scores=prepared)
        except BaseException as exc: result['cleanup_errors'].append({'stage':'final-ledger-snapshot','class':type(exc).__name__})
        if prepared:
            try:
                mirror = json_command('archive-prepare', [*remote,'run','python3','-c',ARCHIVE,study,remote_out])
                for key, filename in [('archive','study-ledger.tar.gz'),('manifest','mirror-manifest.json')]:
                    target = out/filename
                    command(key+'-mirror', [*remote,'get',REMOTE_REPO+'/'+mirror[key],str(target)])
                    if sha(target)!=mirror[key+'_sha256']: raise ValueError('Opaque mirror hash differs')
                result['opaque_mirror'] = mirror
            except BaseException as exc: result['cleanup_errors'].append({'stage':'opaque-study-mirror','class':type(exc).__name__})
        result['finished_at_utc'] = datetime.fromtimestamp(clock(),timezone.utc).isoformat()
        result['completed'] = result['completed'] and not result['cleanup_errors']
        write_new(out/'outcome.json',result)
        print(json.dumps(result),flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study-dir',default='runs/sd-hard-partial-attempt1')
    parser.add_argument('--out',required=True)
    parser.add_argument('--expected-ledger-sha256',default=SEED)
    parser.add_argument('--max-work-seconds',type=int,default=7800)
    args = parser.parse_args()
    def interrupted(*_): raise InterruptedError()
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    return int(not execute(args)['completed'])


if __name__ == '__main__':
    try: raise SystemExit(main())
    except Exception as exc: raise SystemExit('Labelled Hard15 evaluation stage failed: '+type(exc).__name__) from None
