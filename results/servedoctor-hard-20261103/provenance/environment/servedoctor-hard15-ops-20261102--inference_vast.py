#!/usr/bin/env python3
"""Isolated inference-only rental under the exact human-authorized $43 overlay.

All prior scientific/control bytes stay untouched. One CREATE and one optional
START per explicit intent; unknown outcomes reconcile by GET only. The fixed
three-hour allocation clock starts at CREATE dispatch, including cold setup,
SSH readiness and cleanup. No model or ledger operation exists here.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

OPS=Path(__file__).resolve().parent
REPO=OPS.parent.parent
ROOT=OPS/'inference-rental-attempt1'
OLD=REPO/'runs/servedoctor-hard-ops-20261102'
sys.path.insert(0,str(OLD))
import hard_vast as old

PROJECT=LABEL='servedoctor-hard15-inference-20261103'
IMAGE=old.IMAGE
CAP=43.0
MAX_RATE=1.65
WINDOW=10800
DEADLINE=datetime(2026,11,3,23,tzinfo=timezone.utc).timestamp()
AMENDMENT_SHA='8efba5368ca146e45ff55d16fb45567058ae015bcee51a26a5510a0e31c4ee2a'
OLD_SCOPE='c941c466f1e56180a66c6ebe98972c8507c4fa94bee6b3c96a419e3e6eed0b4c'
PRIOR_RECEIPT_SHA='57b61384c4494633266c2f5f6fca1fa12f238d118ae08c9901a91df4a49cd76a'
STOP_MARGIN=90
sha=old.sha
write=old.write
pid_birth=old.pid_birth


def require(value,reason):
    if not value:raise ValueError(reason)


def regular(path):
    path=Path(path).absolute()
    require('..' not in path.parts and path.resolve()==path and path.is_relative_to(REPO) and path.is_file(),'Regular local evidence required')
    require(not path.name.startswith(('.env','ssh_ed25519','gemma_vast_pilot')) and path.suffix not in ('.key','.pem','.sock'),'Private identity is not evidence')
    return path


def desc(path):return {'path':str(Path(path).resolve()),'sha256':sha(path)}
def load_json(path):return json.loads(regular(path).read_text())


class Rental:
    def __init__(self,root=ROOT,repo=REPO,api=None,inventory=None,clock=time.time,birth=pid_birth):
        self.root,self.repo,self.clock,self.birth=Path(root),Path(repo),clock,birth
        legacy=old.legacy() if api is None or inventory is None else None
        self.api=legacy.api if api is None else api;self.inventory=legacy.instances if inventory is None else inventory
        self.state_path=self.root/'session.json';self.scope_path=self.root/'rental-scope.json';self.binding_path=self.root/'binding.json'
    @contextmanager
    def lock(self):
        require(self.root.is_dir() and not self.root.is_symlink(),'Prepared inference control directory required')
        with (self.root/'operation.lock').open('a') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX);yield
    stopped=staticmethod(old.Rental.stopped)
    safe_row=staticmethod(old.Rental.safe_row)
    host_cost=staticmethod(old.Rental.host_cost)

    def proof_file(self,path):
        path=Path(path).absolute();name=path.name.lower()
        require('..' not in path.parts and path.resolve()==path and path.is_relative_to(self.repo.resolve()) and path.is_file(),'Regular in-repository proof required')
        require(not name.startswith(('.env','ssh_ed25519','gemma_vast_pilot','id_rsa','id_ed25519'))
            and not any(v in name for v in ('api_key','api-key','credentials')) and path.suffix not in ('.key','.pem','.sock'),'Credential is not proof')
        return path

    def public_key(self):
        path=self.repo/'runs/vast-preflight-20261029/ssh_ed25519.pub'
        require(not path.is_symlink() and path.stat().st_size<=4096,'Bounded original public-key file required')
        public=path.read_text().strip()
        require(re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]+(?: [A-Za-z0-9@._-]+)?',public),'Original public key format required')
        return public

    def amendment(self):
        path=self.repo/'runs/servedoctor-hard15-ops-20261102/gpu-budget-amendment-43-20261102.json'
        require(sha(path)==AMENDMENT_SHA,'Exact $43 authorization required')
        value=json.loads(path.read_text());require(value.get('new_total_gpu_cap_usd')==43 and value.get('previous_total_gpu_cap_usd')==40
            and value.get('api_caps_unchanged')=={'meta':50,'baseten':20} and value.get('scientific_freeze_unchanged') is True,'Budget scope changed')
        return desc(path)

    def prior(self,receipt_path):
        path=self.proof_file(receipt_path);require(sha(path)==PRIOR_RECEIPT_SHA,'Exact finalized fifth-host receipt required');receipt=json.loads(path.read_text())
        require(receipt.get('project')==old.LABEL and receipt.get('instance_id')==58866756 and receipt.get('rental_scope_sha256')==OLD_SCOPE
            and receipt.get('confirmed_absent') is True,'Final deleted original inference-host receipt required')
        state_desc=receipt['final_state'];require(sha(self.proof_file(state_desc['path']))==state_desc['sha256'],'Final prior state changed')
        state=json.loads(Path(state_desc['path']).read_text())
        require(state.get('instance_id')==58866756 and state.get('scope_sha256')==OLD_SCOPE and not state.get('pending_intent')
            and state.get('destroyed_epoch')==receipt.get('destroyed_epoch') and self.stopped(state.get('last_status',{}))
            and all('stop_epoch' in row for row in state['running_intervals']),'Prior rental must be deleted/stopped with closed accounting')
        previous=state.get('prior_hard_hosts',[]);require(len(previous)==4,'All four earlier Hard rentals required')
        total=old.PRIOR_USD+old.NETWORK+old.SLACK;host=self.host_cost(state,state['destroyed_epoch'])
        require(host==receipt.get('host_cost'),'Current original-host cost differs')
        total+=host['compute_usd_upper']+host['disk_usd_upper'];proofs=[]
        for row in previous:
            proof=row['receipt'];require(sha(self.proof_file(proof['path']))==proof['sha256'],'Prior finalized host proof changed')
            value=json.loads(Path(proof['path']).read_text());require(value.get('confirmed_absent') is True and value.get('instance_id')==row['instance_id'],'Prior host not finalized')
            total+=value['host_cost']['compute_usd_upper']+value['host_cost']['disk_usd_upper'];proofs.append(proof)
        require(sha(old.PRIOR_PATH)==old.PRIOR_SHA and math.isclose(total,receipt['gpu_accounting']['total_usd_upper'],abs_tol=1e-9),'V0 plus all five Hard costs differ')
        return {'project':PROJECT,'receipt':desc(path),'final_state':state_desc,'prior_hard_receipts':proofs,
            'prior_v0_receipt':desc(old.PRIOR_PATH),'total_usd_upper':total,'network_and_slack_already_reserved_once':True,
            'recording_instance_id':58866756,'destroyed_epoch':state['destroyed_epoch']}

    def load(self):
        state=json.loads(self.state_path.read_text());require(state.get('project')==PROJECT and state.get('label')==LABEL and state.get('image')==IMAGE,'Inference state identity differs')
        require(state.get('budget_amendment')==self.amendment(),'Budget amendment differs')
        prior=state['prior_accounting'];require(sha(prior['path'])==prior['sha256'],'Prior accounting snapshot differs')
        value=json.loads(Path(prior['path']).read_text());require(self.prior(value['receipt']['path'])==value,'Prior cost lineage differs')
        if state.get('instance_id'):
            require(sha(self.scope_path)==state.get('scope_sha256'),'Immutable scope differs')
            scope=json.loads(self.scope_path.read_text())
            require(scope=={k:state[k] for k in ('project','label','image','instance_id','offer_id','machine_id','budget_amendment','prior_accounting','allocation_started_epoch','allocation_deadline_epoch')},'Scope identity differs')
        require(state['allocation_deadline_epoch']==min(state['allocation_started_epoch']+WINDOW,DEADLINE),'Fixed three-hour allocation clock changed')
        return state

    def cost(self,state,remaining=None):
        current=({'running_hours':0.,'compute_usd_upper':0.,'disk_usd_upper':0.} if state.get('create_rejected_confirmed_absent_epoch')
            else self.host_cost(state,self.clock()));prior=json.loads(Path(state['prior_accounting']['path']).read_text())
        total=prior['total_usd_upper']+current['compute_usd_upper']+current['disk_usd_upper']
        remaining=max(0,state['allocation_deadline_epoch']-self.clock())/3600 if remaining is None else remaining
        return {'prior_v0_and_five_hard_hosts_usd_upper':prior['total_usd_upper'],'inference_host_cost':current,
            'total_usd_upper':total,'remaining_gpu_hours':remaining,'forecast_usd_upper':total+remaining*state['dph_total'],
            'shutdown_margin_usd':STOP_MARGIN*state['dph_total']/3600,'total_cap_usd':CAP,'network_and_slack_reserved_once':True}
    def forecast(self,state):
        cost=self.cost(state);require(self.clock()<state['allocation_deadline_epoch'] and cost['forecast_usd_upper']+cost['shutdown_margin_usd']<CAP,'Fixed allocation deadline or $43 forecast exceeded')
        return cost
    def save(self,state):
        write(self.state_path,state)
        if state.get('live_action_attempted'):
            snapshot=self.root/'gpu-hours-before-inference.md';hours=self.repo/'runs/servedoctor-gpu-hours.md'
            if not snapshot.exists():
                with snapshot.open('xb') as stream:stream.write(hours.read_bytes())
            body=snapshot.read_text()+'\n\n## Authorized inference-only rental ($43 total cap)\n\n'+json.dumps(self.cost(state),indent=2)+'\n'
            temporary=hours.with_suffix('.inference.tmp');temporary.write_text(body);temporary.replace(hours)
    def bind(self,state,instance):
        require(type(instance) is int and instance>0 and instance not in state['existing_instance_ids'] and instance not in (58690026,58716527,58843932,58848277,58851643,58858374,58866756),'Fresh inference rental required')
        require(state.get('instance_id') in (None,instance),'Scope cannot be rebound')
        state['instance_id']=instance;scope={k:state[k] for k in ('project','label','image','instance_id','offer_id','machine_id','budget_amendment','prior_accounting','allocation_started_epoch','allocation_deadline_epoch')}
        if self.scope_path.exists():require(json.loads(self.scope_path.read_text())==scope,'Prior scope differs')
        else:write(self.scope_path,scope,exclusive=True)
        state['scope_sha256']=sha(self.scope_path)
    def seal_binding(self,state,outcome):
        value=json.loads(Path(outcome).read_text())
        require(value.get('operation')=='create' and value.get('phase')=='response' and value.get('success') is True
            and value.get('new_contract')==state['instance_id'],'Known successful CREATE acknowledgement required')
        binding={'project':PROJECT,'instance_id':state['instance_id'],'rental_scope_sha256':state['scope_sha256'],'rental_scope':desc(self.scope_path),
            'budget_amendment':state['budget_amendment'],'prior_accounting':state['prior_accounting'],'recording_instance_id':58866756,'purpose':'inference-only'}
        binding['create_ack']=desc(outcome)
        if self.binding_path.exists():require(json.loads(self.binding_path.read_text())==binding,'Binding differs')
        else:write(self.binding_path,binding,exclusive=True)

    def intent(self,state,operation,path,payload=None,reason='',sidecar=False):
        require(operation in ('create','attach','start','stop','delete'),'Fixed lifecycle operation required')
        require(not state.get('pending_intent') or (sidecar and operation=='attach'),'Pending mutation allows GET only')
        if operation in ('create','attach','start','delete'):
            require(not any(json.loads(p.read_text()).get('operation')==operation for p in self.root.glob('intent-[0-9]*.json')),'One-shot mutation already attempted')
        number=len(list(self.root.glob('intent-[0-9]*.json')))+1;target=self.root/f'intent-{number:04d}-{operation}.json'
        record={'project':PROJECT,'instance_id':state.get('instance_id'),'rental_scope_sha256':state.get('scope_sha256'),'operation':operation,
            'method':'DELETE' if operation=='delete' else ('POST' if operation=='attach' else 'PUT'),'path':path,'requested_epoch':self.clock(),'reason':reason}
        if payload is not None:record['payload_sha256']=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        write(target,record,exclusive=True)
        if not sidecar:state['pending_intent']=target.name
        state['live_action_attempted']=True;self.save(state)
        try:
            response=self.api(record['method'],path,payload)
            result={**record,'phase':'response',**{k:response[k] for k in ('success','http_status','new_contract') if type(response.get(k)) in (bool,int)}}
            for key in ('safe_error_code','safe_error_message'):
                if isinstance(response.get(key),str):result[key]=re.sub(r'(?i)\bBearer\s+[^\s\"\'<>]+','Bearer [REDACTED]',response[key])[:512]
            if operation=='create' and response.get('success') is True:self.bind(state,response['new_contract'])
        except Exception as error:result={**record,'phase':'unknown_outcome','error_class':type(error).__name__}
        outcome=target.with_name(target.stem+'-outcome.json');write(outcome,result,exclusive=True)
        if operation=='create' and result.get('success') is True:self.seal_binding(state,outcome)
        self.save(state);return result

    def create(self,selection,prior_receipt):
        require(not self.state_path.exists() and not self.scope_path.exists() and not list(self.root.glob('intent-*.json')),'Fresh control namespace required')
        owner=json.loads((self.root/'create-owner.json').read_text())
        require(owner.get('project')==PROJECT and self.birth(owner['pid'])==owner.get('birth') and 0<=self.clock()-owner['at_epoch']<=60,'Actual owning controller required before CREATE')
        amendment=self.amendment();selection=self.proof_file(selection);require(selection.stat().st_size<=65536,'Bounded quote required')
        quote=json.loads(selection.read_text());offer=quote['selected_offer'];at=datetime.fromisoformat(quote['at_utc'].replace('Z','+00:00')).timestamp()
        require(quote.get('project')==PROJECT and quote.get('helper_sha256')==sha(__file__) and 0<=self.clock()-at<=10,'Fresh helper-bound offer receipt required')
        self.validate_offer(offer);prior=self.prior(prior_receipt);require(prior['destroyed_epoch']<=self.clock(),'No overlapping prior rental permitted')
        rows=self.inventory();now=self.clock();prior_path=self.root/'prior-accounting.json';write(prior_path,prior,exclusive=True)
        state={'project':PROJECT,'label':LABEL,'image':IMAGE,'offer_id':offer['id'],'machine_id':offer['machine_id'],'instance_id':None,
            'budget_amendment':amendment,'prior_accounting':desc(prior_path),'allocation_started_epoch':now,'allocation_deadline_epoch':min(now+WINDOW,DEADLINE),
            'created_epoch':now,'dph_total':offer['dph_total'],'storage_dph':offer['storage_total_cost'],'existing_instance_ids':[v['id'] for v in rows],
            'running_intervals':[{'start_epoch':now}],'offer_selection_receipt':desc(selection)}
        self.forecast(state);self.save(state)
        # Public key only; the private identity path is never read.
        public=self.public_key()
        onstart=("set -eu\nprintf '%s\\n' 'SERVEDOCTOR_INFERENCE_SSH_SETUP_BEGIN'\nmkdir -p /root/.ssh /workspace/servedoctor-hard\n"
            "touch /root/.ssh/authorized_keys /root/.no_auto_tmux\nchown 0:0 /root /root/.ssh /root/.ssh/authorized_keys\n"
            "chmod go-w /root\nchmod 700 /root/.ssh\nchmod 600 /root/.ssh/authorized_keys\n"
            "printf '%s\\n' '"+public+"' >> /root/.ssh/authorized_keys\n"
            "printf '%s\\n' 'SERVEDOCTOR_INFERENCE_SSH_SETUP_DONE'\nexec /opt/instance-tools/bin/entrypoint.sh\n")
        return self.intent(state,'create',f"/api/v0/asks/{offer['id']}/",{'client_id':'me','image':IMAGE,'disk':150,'runtype':'ssh_direct','target_state':'running','label':LABEL,'onstart':onstart,'cancel_unavail':True},'One explicit inference-only CREATE')

    @staticmethod
    def validate_offer(offer):
        require(type(offer.get('id')) is int and type(offer.get('machine_id')) is int and offer.get('verification')=='verified'
            and offer.get('num_gpus')==1 and offer.get('gpu_name')=='RTX PRO 6000 WS' and offer.get('gpu_ram',0)>=90000
            and offer.get('disk_space',0)>=150 and offer.get('cpu_ram',0)>=64000 and offer.get('reliability',0)>=.99
            and offer.get('cuda_max_good',0)>=13 and offer.get('rentable') is True and offer.get('rented') is False
            and offer.get('external') in (False,None) and not offer.get('is_bid') and str(offer.get('geolocation','')).endswith(', US')
            and 0<offer.get('dph_total',0)<=MAX_RATE and 0<=offer.get('storage_total_cost',-1)<offer['dph_total']
            and 0<=offer.get('inet_down_cost',-1) and 0<=offer.get('inet_up_cost',-1)
            and offer['inet_down_cost']*100+offer['inet_up_cost']*10<=1,'Reviewed verified US96GB/150GB on-demand offer required')

    def attach_early(self):
        state=self.load();require(state.get('instance_id') and state.get('pending_intent'),'Bound acknowledged pending CREATE required')
        binding=json.loads(self.binding_path.read_text());proof=binding['create_ack'];require(sha(proof['path'])==proof['sha256'],'Known CREATE ACK binding differs')
        prior=json.loads((self.root/state['pending_intent']).read_text());require(prior.get('operation')=='create','Early attach preserves CREATE intent')
        public=self.public_key()
        return self.intent(state,'attach',f"/api/v0/instances/{state['instance_id']}/ssh/",{'ssh_key':public},'Immediate public-key attach after CREATE ACK',sidecar=True)

    def reconcile(self):
        state=self.load();rows=self.inventory();pending=json.loads((self.root/state['pending_intent']).read_text()) if state.get('pending_intent') else None
        if not state.get('instance_id'):
            matches=[row for row in rows if row['id'] not in state['existing_instance_ids'] and row.get('label')==LABEL and row.get('machine_id')==state['machine_id']]
            require(len(matches)==1,'Unknown CREATE: exactly one scoped GET match required');self.bind(state,matches[0]['id'])
        row=next((v for v in rows if v['id']==state['instance_id']),None)
        if row is None:
            require(state.get('destroyed_epoch') or pending and pending['operation']=='delete','Absence requires DELETE lineage')
            state.setdefault('destroyed_epoch',self.clock());state.pop('pending_intent',None)
            for interval in state['running_intervals']:
                if 'stop_epoch' not in interval:interval.update(stop_epoch=state['destroyed_epoch'],deletion_confirmed=True,stop_confirmed=False)
        else:
            require(row.get('label')==LABEL and row.get('machine_id')==state['machine_id'],'Scoped inventory identity differs')
            require(not row.get('image_uuid') or row['image_uuid'] in (IMAGE,IMAGE.split('@')[1],IMAGE.split(':')[-1]),'Pinned image differs')
            state['last_status']=self.safe_row(row)
            if row.get('actual_status')=='running':
                for interval in state['running_intervals']:
                    if 'stop_epoch' not in interval:interval.setdefault('running_seen_epoch',self.clock())
            if self.stopped(row):
                for interval in state['running_intervals']:
                    if 'running_seen_epoch' in interval or pending and pending['operation']=='stop':interval.setdefault('stop_epoch',self.clock())
            if pending and ((pending['operation'] in ('create','start') and row.get('actual_status')=='running') or pending['operation']=='stop' and self.stopped(row)):
                write(self.root/(Path(state['pending_intent']).stem+'-reconciled.json'),{'confirmed_epoch':self.clock(),'status':self.safe_row(row)},exclusive=True);state.pop('pending_intent')
        self.save(state);return state

    def stop(self,reason='Finished or idle inference work'):
        state=self.load()
        require(type(state.get('instance_id')) is int and state.get('scope_sha256'),'Cannot cancel an unbound unknown CREATE')
        if state.get('pending_intent'):
            pending=json.loads((self.root/state['pending_intent']).read_text())
            require(pending['operation'] not in ('stop','delete'),'STOP/DELETE pending: GET only')
            # A STOP explicitly cancels one queued CREATE/START, retaining its intent.
            require(pending['operation'] in ('create','start'),'Unknown mutation cannot be superseded')
            state['cancelled_start_intent']=state.pop('pending_intent');self.save(state)
        if self.stopped(state.get('last_status',{})) and all('stop_epoch' in r for r in state['running_intervals']):return {'already_stopped':True}
        return self.intent(state,'stop',f"/api/v0/instances/{state['instance_id']}/",{'state':'stopped'},reason)

    def start(self):
        state=self.load();self.forecast(state)
        require(not state.get('pending_intent') and self.stopped(state.get('last_status',{}))
            and all('stop_epoch' in row for row in state['running_intervals']),'Explicit START requires confirmed stopped/closed rental')
        state['running_intervals'].append({'start_epoch':self.clock()});self.save(state)
        return self.intent(state,'start',f"/api/v0/instances/{state['instance_id']}/",{'state':'running'},'One explicit START within original fixed allocation clock')

    def active(self):
        value=json.loads((self.root/'active-command.json').read_text());now=self.clock()
        require(value.get('project')==PROJECT and self.birth(value['pid'])==value.get('birth') and 0<=now-value['at_epoch']<=60
            and now<value['deadline_epoch']<=self.load()['allocation_deadline_epoch'],'Actual fresh owner required')
        return value
    def heartbeat(self,pid,command):
        state=self.load();require(self.birth(pid),'Actual owner PID required');deadline=state['allocation_deadline_epoch']
        value={'project':PROJECT,'pid':pid,'birth':self.birth(pid),'command':command,'at_epoch':self.clock(),'deadline_epoch':deadline}
        write(self.root/'active-command.json',value);return value


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=('create','reconcile','status','stop','attach','start'))
    p.add_argument('--selection');p.add_argument('--prior-receipt');a=p.parse_args();service=Rental()
    with service.lock():
        if a.operation=='create':result=service.create(a.selection,a.prior_receipt)
        elif a.operation=='attach':result=service.attach_early()
        elif a.operation=='stop':result=service.stop()
        elif a.operation=='start':result=service.start()
        elif a.operation=='reconcile':result=service.reconcile()
        else:result={'state':service.load(),'cost':service.cost(service.load())}
    print(json.dumps(result))


if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit('Inference control refused: '+type(error).__name__) from None
