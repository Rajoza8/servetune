#!/usr/bin/env python3
"""Read-only progress: counts, ledger totals, scope and rental accounting only."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import subprocess

import inference_remote as remote
import inference_vast as rental

OPS=Path(__file__).resolve().parent
CODE="""from pathlib import Path
import json
from servedoctor.llm import Ledger
root=Path('runs/sd-hard-partial-attempt1/decisions')
arms=('rules','spark','wonder','glimmer','glimmer_to_spark','glimmer_to_wonder')
counts={a:len(list((root/a).glob('*.json'))) for a in arms}
print(json.dumps({'ledger':Ledger('runs/servedoctor-ledger.json').summary(),'decision_file_counts':counts}))
"""


def main():
    p=argparse.ArgumentParser();p.add_argument('--tag',required=True);args=p.parse_args()
    if not re.fullmatch('snapshot-[0-9]{4}',args.tag):raise ValueError('Numbered fresh snapshot required')
    out=OPS/'inference-progress-attempt1';out.mkdir(exist_ok=True)
    service=rental.Rental(api=lambda *_a,**_k:None,inventory=lambda:[]);state=service.load()
    value={'at_utc':datetime.now(timezone.utc).isoformat(),'instance_id':state['instance_id'],
        'status':state.get('last_status',{}).get('actual_status'),'cost':service.cost(state),'remote_requested':False}
    for path in out.glob(args.tag+'.*'):raise ValueError('Snapshot exists; never overwrite')
    if not state.get('destroyed_epoch') and value['status']=='running':
        value['remote_requested']=True
        with (out/(args.tag+'.stdout')).open('xb') as stdout,(out/(args.tag+'.stderr')).open('xb') as stderr:
            result=subprocess.run(remote.command('run',['python3','-c',CODE]),stdout=stdout,stderr=stderr,timeout=35)
        value['returncode']=result.returncode
        if result.returncode==0:value.update(json.loads((out/(args.tag+'.stdout')).read_text()))
    with (out/(args.tag+'.json')).open('x') as f:json.dump(value,f,indent=2);f.write('\n')
    print(json.dumps(value))
if __name__=='__main__':main()
