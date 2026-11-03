#!/usr/bin/env python3
"""Isolated Hard rental control. Mutations are explicit, journaled once, never retried.

Only api()/instances() are reused from the frozen v0 helper. Importing this module
does not read credentials or write files. CLI commands hold a separate Hard lock.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
LABEL = 'servedoctor-hard-20261102'
IMAGE = 'vastai/vllm@sha256:d17aa376347c086ce53d9f9ac3a70e904acbc37882a7ee0b1ba4f7f538f8d843'
OFFER, MACHINE = 49799372, 141678
REGION = 'Colorado, US'
MAX_RATE, CAP = 1.85, 40.0
PRIOR_USD = 25.90010443543525
PRIOR_PATH = REPO / 'runs/servedoctor-ops-20261101/destroy-receipt-58716527.json'
PRIOR_SHA = '9c28a7d7b972a89cc9e25f079db45310066afacd4e7d3bd300c4ed87894483de'
DEADLINE = datetime(2026, 11, 3, 23, tzinfo=timezone.utc).timestamp()
NETWORK, SLACK, REMAINING_HOURS = 4.0, 1.0, 5.0
HEARTBEAT_TTL, STOP_MARGIN = 60, 90
INVENTORY_FAILURE_GRACE = 120


def sha(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Regular nonsymlink proof required')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value, exclusive=False):
    path = Path(path)
    raw = (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()
    if exclusive:
        with path.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    else:
        temporary = path.with_suffix('.tmp')
        with temporary.open('wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(path)


def legacy():
    spec = importlib.util.spec_from_file_location('_hard_v0_transport', REPO / 'runs/servedoctor-ops-20261101/vast_ops.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pid_birth(pid):
    if type(pid) is not int or pid <= 1:
        return None
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart='], capture_output=True, text=True, timeout=5)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


class Rental:
    def __init__(self, root=ROOT, repo=REPO, api=None, inventory=None, clock=time.time, birth=pid_birth):
        self.root, self.repo, self.clock, self.birth = Path(root), Path(repo), clock, birth
        old = legacy() if api is None or inventory is None else None
        self.api = api if api is not None else old.api
        self.inventory = inventory if inventory is not None else old.instances
        self.state_path, self.scope_path = self.root/'session.json', self.root/'rental-scope.json'

    @contextmanager
    def lock(self):
        with (self.root/'operation.lock').open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def baseline(self):
        if sha(PRIOR_PATH) != PRIOR_SHA:
            raise ValueError('Final v0 rental proof changed')
        value = json.loads(PRIOR_PATH.read_text())
        if (value.get('project') != 'servedoctor' or value.get('instance_id') != 58716527
                or value.get('confirmed_absent') is not True
                or value.get('cost', {}).get('total_projected_usd_upper') != PRIOR_USD):
            raise ValueError('Final v0 accounting is not established')
        return {'path': str(PRIOR_PATH), 'sha256': PRIOR_SHA, 'usd_upper': PRIOR_USD}

    def load(self):
        state = json.loads(self.state_path.read_text())
        expected = {'project': LABEL, 'label': LABEL, 'offer_id': OFFER, 'machine_id': MACHINE, 'image': IMAGE}
        if any(state.get(k) != v for k, v in expected.items()) or state.get('prior_baseline') != self.baseline():
            raise ValueError('Hard rental identity or prior accounting changed')
        if state.get('instance_id'):
            binding = {**expected, 'instance_id': state['instance_id'], 'prior_baseline': state['prior_baseline']}
            if 'prior_hard_hosts' in state:binding['prior_hard_hosts']=state['prior_hard_hosts']
            if 'prior_hard_history' in state:binding['prior_hard_history']=state['prior_hard_history']
            if 'offer_selection_receipt' in state:binding['offer_selection_receipt']=state['offer_selection_receipt']
            if sha(self.scope_path) != state.get('scope_sha256') or json.loads(self.scope_path.read_text()) != binding:
                raise ValueError('Immutable Hard rental scope changed')
        if state.get('prior_hard_hosts',[])!=self.history():raise ValueError('Prior Hard rental history changed')
        if 'prior_hard_history' in state and state['prior_hard_history']!=self.history_manifest():raise ValueError('Pinned prior Hard history version changed')
        if state.get('offer_selection_receipt'):
            proof=state['offer_selection_receipt']
            if sha(proof['path'])!=proof['sha256']:raise ValueError('Pinned offer selection receipt changed')
        return state

    def history_documents(self):
        """Follow an append-only v1,v2,... chain; never rewrites an old receipt."""
        paths={}
        for path in self.root.glob('prior-hard-hosts*.json'):
            match=re.fullmatch(r'prior-hard-hosts(?:-([1-9][0-9]*))?\.json',path.name)
            if not match or match.group(1)=='1' or path.is_symlink():raise ValueError('Unexpected Hard history version or symlink')
            version=int(match.group(1) or 1)
            if version in paths:raise ValueError('Duplicate Hard history version')
            paths[version]=path
        if not paths:return []
        if sorted(paths)!=list(range(1,max(paths)+1)):raise ValueError('Hard history version chain has a missing parent')
        documents=[];previous=None
        for version in sorted(paths):
            path=paths[version];value=json.loads(path.read_text())
            if (value.get('project')!=LABEL or value.get('network_slack_reserved_once') is not True
                    or not isinstance(value.get('hosts'),list) or len(value['hosts'])!=version
                    or (version==1 and value.get('version',1)!=1)
                    or (version>1 and (type(value.get('version')) is not int or value['version']!=version))):
                raise ValueError('Shared Hard history identity/version differs')
            if previous is not None:
                expected={'path':str(previous[0].resolve()),'sha256':sha(previous[0])}
                if value.get('parent')!=expected or value['hosts'][:-1]!=previous[1]['hosts']:
                    raise ValueError('Hard history parent hash or exact host prefix changed')
            documents.append((path,value));previous=(path,value)
        return documents

    def history_manifest(self):
        documents=self.history_documents()
        return {'path':str(documents[-1][0].resolve()),'sha256':sha(documents[-1][0])} if documents else None

    def history(self):
        documents=self.history_documents()
        if not documents:return []
        value=documents[-1][1]
        ids=set();last_destroyed=None
        for index,item in enumerate(value['hosts']):
            if type(item.get('instance_id')) is not int or item['instance_id']<=0 or item['instance_id'] in ids:raise ValueError('Unique prior Hard hosts required')
            ids.add(item['instance_id'])
            proof=Path(item['receipt']['path'])
            if (not proof.resolve().is_relative_to((self.root/'rental-history').resolve())
                    or sha(proof)!=item['receipt']['sha256']):raise ValueError('Prior Hard receipt changed')
            receipt=json.loads(proof.read_text())
            final=receipt['final_state'];final_path=Path(final['path'])
            if sha(final_path)!=final['sha256']:raise ValueError('Prior Hard final state changed')
            old=json.loads(final_path.read_text())
            scope=receipt['rental_scope'];scope_path=Path(scope['path'])
            if sha(scope_path)!=scope['sha256'] or scope['sha256']!=receipt.get('rental_scope_sha256') or old.get('scope_sha256')!=scope['sha256']:
                raise ValueError('Prior Hard scope binding changed')
            scoped=json.loads(scope_path.read_text())
            if (receipt.get('project')!=LABEL or receipt.get('confirmed_absent') is not True
                    or receipt.get('instance_id')!=item['instance_id'] or old.get('instance_id')!=item['instance_id']
                    or scoped.get('instance_id')!=item['instance_id'] or scoped.get('project')!=LABEL
                    or scoped.get('image')!=IMAGE or scoped.get('prior_baseline')!=self.baseline()
                    or any(scoped.get(k)!=old.get(k) for k in ('project','label','offer_id','machine_id','image','instance_id'))
                    or scoped.get('prior_hard_hosts',[])!=value['hosts'][:index] or old.get('prior_hard_hosts',[])!=value['hosts'][:index]
                    or not old.get('destroyed_epoch') or any('stop_epoch' not in x for x in old['running_intervals'])
                    or receipt.get('destroyed_epoch')!=old['destroyed_epoch'] or receipt.get('network_slack_reserved_once') is not True
                    or receipt.get('host_cost')!=self.host_cost(old,old['destroyed_epoch'])):
                raise ValueError('Prior Hard finalized billing proof differs')
            if last_destroyed is not None and old['created_epoch']<last_destroyed:
                raise ValueError('Prior Hard rentals overlap')
            last_destroyed=old['destroyed_epoch']
        return value['hosts']

    def verify_host_archives(self):
        documents=self.history_documents();hosts=self.history();expected=set(range(1,len(hosts)+1))
        found={}
        for path in self.root.glob('host*-archive-intent.json'):
            match=re.fullmatch(r'host([1-9][0-9]*)-archive-intent\.json',path.name)
            if not match or int(match.group(1)) in found:raise ValueError('Unexpected or duplicate host archive intent')
            found[int(match.group(1))]=path
        completed={}
        for path in self.root.glob('host*-archive-complete.json'):
            match=re.fullmatch(r'host([1-9][0-9]*)-archive-complete\.json',path.name)
            if not match:raise ValueError('Unexpected host archive completion')
            completed[int(match.group(1))]=path
        if set(found)!=expected or set(completed)!=expected:raise ValueError('Prior Hard host archival incomplete or history missing')
        for number,item in enumerate(hosts,1):
            intent=found[number];final=completed[number]
            if (self.root/f'host{number}-archive-failure.json').exists():raise ValueError('Prior Hard archive has a retained failure')
            plan=json.loads(intent.read_text());proof=json.loads(final.read_text());history_path=documents[number-1][0]
            history_proof={'path':str(history_path.resolve()),'sha256':sha(history_path)}
            if (plan.get('project')!=LABEL or proof.get('project')!=LABEL or plan.get('instance_id')!=item['instance_id']
                    or proof.get('instance_id')!=item['instance_id'] or proof.get('intent_sha256')!=sha(intent)
                    or proof.get('history_manifest')!=history_proof):raise ValueError('Prior Hard host archive proof changed')
            if number>1:
                parent={'path':str(documents[number-2][0].resolve()),'sha256':sha(documents[number-2][0])}
                if plan.get('parent_history')!=parent or proof.get('parent_history')!=parent:raise ValueError('Host archival parent chain differs')
            directory=self.root/'rental-history'/f'host{number}-{item["instance_id"]}'
            if directory.is_symlink() or (self.root/'rental-history').is_symlink():raise ValueError('Unsafe host archive directory')
            files=proof.get('archived_files_sha256',{})
            actual={p.relative_to(self.root).as_posix() for p in directory.rglob('*') if p.is_file() or p.is_symlink()}
            if not files or actual!=set(files):raise ValueError('Host archive file coverage differs')
            for relative,digest in files.items():
                p=Path(relative);path=self.root/p
                if p.is_absolute() or '..' in p.parts or not path.resolve().is_relative_to(directory.resolve()) or sha(path)!=digest:
                    raise ValueError('Archived Hard host alias changed')
            for name,digest in plan['files_sha256'].items():
                if Path(name).name!=name or files.get((directory/name).relative_to(self.root).as_posix())!=digest:
                    raise ValueError('Original host control files were not preserved exactly')
            receipt=Path(item['receipt']['path'])
            if receipt.resolve()!=(directory/'billing-receipt.json').resolve() or sha(receipt)!=item['receipt']['sha256']:
                raise ValueError('Archived billing proof path differs')
        return hosts

    @staticmethod
    def host_cost(state,epoch):
        fields=(state['created_epoch'],epoch,state['dph_total'],state['storage_dph'])
        if (any(type(v) not in (int,float) or not math.isfinite(v) for v in fields)
                or not 0<=state['storage_dph']<=state['dph_total'] or state.get('destroyed_epoch',epoch)<state['created_epoch']):
            raise ValueError('Finite positive host accounting required')
        end=state.get('destroyed_epoch',epoch);previous=state['created_epoch']
        for item in state.get('running_intervals',[]):
            start,stop=item['start_epoch'],item.get('stop_epoch',end)
            if (any(type(v) not in (int,float) or not math.isfinite(v) for v in (start,stop))
                    or not previous<=start<=stop<=end):raise ValueError('Running intervals overlap or leave retained period')
            previous=stop
        running=sum(max(0,item.get('stop_epoch',state.get('destroyed_epoch',epoch))-item['start_epoch'])
                    for item in state.get('running_intervals',[]))/3600
        retained=max(0,state.get('destroyed_epoch',epoch)-state['created_epoch'])/3600
        return {'running_hours':running,'compute_usd_upper':running*(state['dph_total']-state['storage_dph']),
                'disk_usd_upper':retained*state['storage_dph']}

    def bind(self, state, instance):
        if type(instance) is not int or instance <= 0 or instance in state['existing_instance_ids']:
            raise ValueError('New positive instance identity required')
        if state.get('instance_id') not in (None, instance):
            raise ValueError('Cannot rebind Hard rental')
        if instance in {item['instance_id'] for item in state.get('prior_hard_hosts',[])}:
            raise ValueError('New rental cannot reuse a finalized prior Hard identity')
        scope = {k: state[k] for k in ('project', 'label', 'offer_id', 'machine_id', 'image', 'prior_baseline')}
        if 'prior_hard_hosts' in state:scope['prior_hard_hosts']=state['prior_hard_hosts']
        if 'prior_hard_history' in state:scope['prior_hard_history']=state['prior_hard_history']
        if 'offer_selection_receipt' in state:scope['offer_selection_receipt']=state['offer_selection_receipt']
        scope['instance_id'] = instance
        if self.scope_path.exists():
            if self.scope_path.is_symlink() or json.loads(self.scope_path.read_text()) != scope:
                raise ValueError('Existing immutable scope differs')
        else:
            write(self.scope_path, scope, exclusive=True)
        state.update(instance_id=instance, scope_sha256=sha(self.scope_path))

    def cost(self, state, remaining=None):
        now = self.clock()
        current=self.host_cost(state,now);previous={'running_hours':0.,'compute_usd_upper':0.,'disk_usd_upper':0.}
        history=self.history()
        if state.get('prior_hard_hosts',[])!=history:raise ValueError('Frozen prior Hard history differs')
        for item in history:
            old_receipt=json.loads(Path(item['receipt']['path']).read_text())
            if state.get('instance_id')==item['instance_id'] or state['created_epoch']<old_receipt['destroyed_epoch']:
                raise ValueError('Current and finalized Hard rentals overlap')
            old=old_receipt['host_cost']
            for key in previous:previous[key]+=old[key]
        running=current['running_hours']+previous['running_hours']
        compute=current['compute_usd_upper']+previous['compute_usd_upper']
        disk=current['disk_usd_upper']+previous['disk_usd_upper']
        total = PRIOR_USD + compute + disk + NETWORK + SLACK
        hours = state.get('remaining_gpu_hours', REMAINING_HOURS) if remaining is None else remaining
        return {'prior_v0_usd_upper': PRIOR_USD, 'hard_running_hours': running,
                'hard_compute_usd_upper': compute, 'hard_disk_usd_upper': disk,
                'current_host_cost':current,'prior_hard_host_cost':previous,
                'new_network_reserve_usd': NETWORK, 'new_slack_reserve_usd': SLACK,
                'total_usd_upper': total, 'remaining_gpu_hours': hours,
                'forecast_usd_upper': total + hours*state['dph_total'],
                'shutdown_margin_usd': state['dph_total']*STOP_MARGIN/3600}

    def forecast(self, state):
        value = self.cost(state)
        if self.clock() >= DEADLINE or value['forecast_usd_upper']+value['shutdown_margin_usd'] >= CAP:
            raise ValueError('Hard deadline or projected shared $40 cap would be exceeded')
        return value

    def save(self, state):
        write(self.state_path, state)
        if not state.get('live_action_attempted'):
            return
        hours = self.repo/'runs/servedoctor-gpu-hours.md'
        snapshot = self.root/'v0-gpu-hours-before-hard.md'
        if not snapshot.exists():
            with snapshot.open('xb') as stream:
                stream.write(hours.read_bytes())
        value = self.cost(state)
        body = (snapshot.read_text() + '\n\n## ServeIncidents-Hard rental accounting\n\n'
                + f"Prior v0 fixed upper: ${PRIOR_USD:.12f}; proof SHA256 {PRIOR_SHA}.\n\n"
                + f"Hard instance: {state.get('instance_id', 'unresolved')}; as of UTC "
                + datetime.fromtimestamp(self.clock(), timezone.utc).isoformat() + '.\n\n'
                + json.dumps(value, indent=2) + '\n\nStartup/shutdown uncertainty is charged until GET confirms stopped; retained disk continues until GET confirms deletion.\n')
        temporary = hours.with_suffix('.hard.tmp'); temporary.write_text(body); temporary.replace(hours)

    @staticmethod
    def safe_row(row):
        return {k: row.get(k) for k in ('id', 'label', 'machine_id', 'actual_status', 'cur_state', 'intended_status',
                'status_msg', 'public_ipaddr', 'ports', 'image_uuid')}

    def offers(self):
        query = {'limit': 100, 'type': 'on-demand', 'verified': {'eq': True}, 'external': {'eq':False}, 'rentable': {'eq': True},
                 'rented': {'eq': False}, 'num_gpus': {'eq': 1}, 'gpu_name': {'eq': 'RTX PRO 6000 WS'},
                 'gpu_ram': {'gte': 90000}, 'disk_space': {'gte': 150}, 'cuda_max_good': {'gte': 13},
                 'reliability': {'gte': .99}, 'cpu_ram': {'gte': 64000},
                 'allocated_storage': 150, 'order': [['dph_total', 'asc']]}
        data = self.api('POST', '/api/v0/bundles', query)
        if not isinstance(data.get('offers'), list):
            raise ValueError('Offer query failed')
        keys = ('id', 'machine_id', 'verification', 'gpu_name', 'num_gpus', 'gpu_ram', 'disk_space', 'dph_total',
                'storage_total_cost', 'inet_down_cost', 'inet_up_cost', 'rentable', 'rented', 'is_bid', 'geolocation',
                'cuda_max_good', 'reliability', 'cpu_ram', 'external', 'ask_contract_id', 'bundle_id')
        return [{k: row.get(k) for k in keys} for row in data['offers']]

    def intent(self, state, operation, path, payload=None, reason='',retain_pending_create=False):
        retained=state.get('pending_intent') if retain_pending_create else None
        if retain_pending_create and (operation!='attach' or not retained or state.get('pending_attachment')):
            raise ValueError('Early attachment requires one retained CREATE and no attachment replay')
        if state.get('pending_intent') and not retain_pending_create:
            raise ValueError('Unresolved mutation: GET-only reconcile; do not retry')
        count = len(list(self.root.glob('intent-*.json')))
        record_path = self.root/f'intent-{count:04d}-{operation}.json'
        record = {'project': LABEL, 'instance_id': state.get('instance_id'), 'operation': operation,
                  'method': 'DELETE' if operation == 'delete' else ('POST' if operation=='attach' else 'PUT'), 'path': path,
                  'requested_epoch': self.clock(), 'phase': 'requested', 'reason': reason}
        if state.get('scope_sha256'):record['rental_scope_sha256']=state['scope_sha256']
        if state.get('offer_selection_receipt'):record['offer_selection_receipt']=state['offer_selection_receipt']
        if retained:
            record.update(early_after_create=True,pending_create={'path':str((self.root/retained).resolve()),'sha256':sha(self.root/retained)})
        if payload is not None:
            encoded=json.dumps(payload,sort_keys=True).encode()
            record.update(payload_sha256=hashlib.sha256(encoded).hexdigest(),payload_bytes=len(encoded))
            if operation=='create':record['onstart_bytes']=len(payload.get('onstart','').encode())
            if operation=='attach':record['public_key_sha256']=hashlib.sha256(payload['ssh_key'].encode()).hexdigest()
        write(record_path, record, exclusive=True)
        state['pending_attachment' if retained else 'pending_intent'] = record_path.name
        self.save(state)  # Write-ahead intent survives process interruption before dispatch.
        state['live_action_attempted'] = True
        try:
            result = self.api(record['method'], path, payload)
            record.update(phase='response', **{k: result[k] for k in ('success', 'http_status', 'new_contract')
                                             if type(result.get(k)) in (bool, int)})
            # api() has already removed the exact credential and Bearer values.
            # Retain its bounded diagnostic fields rather than losing the sole
            # server explanation of a rejected mutation. Never retain raw body.
            for key in ('safe_error_code','safe_error_message'):
                if isinstance(result.get(key),str):
                    text=re.sub(r'(?i)\bBearer\s+[^\s\"\'<>]+','Bearer [REDACTED]',result[key])
                    record[key]=text[:512]
            if operation == 'create' and result.get('success') is True:
                self.bind(state, result.get('new_contract'))
            if operation == 'attach' and result.get('success') is True:
                # A successful POST acknowledgement is the attachment proof.
                # Unknown/failed outcomes retain pending_intent and never retry.
                state.pop('pending_attachment' if retained else 'pending_intent')
        except Exception as exc:
            record.update(phase='unknown_outcome', error_class=type(exc).__name__)
        write(self.root/(record_path.stem+'-outcome.json'), record, exclusive=True)
        self.save(state)
        return record

    def attach_early(self,reason='explicit immediate key attachment after CREATE'):
        """One sidecar POST after a bound CREATE ACK; never consumes its intent."""
        state=self.load();self.active();self.forecast(state)
        name=state.get('pending_intent','')
        if Path(name).name!=name or not re.fullmatch(r'intent-[0-9]+-create\.json',name):
            raise ValueError('Immediate attachment requires the still-pending CREATE')
        intent_path=self.root/name;intent=json.loads(intent_path.read_text())
        outcome_path=intent_path.with_name(intent_path.stem+'-outcome.json');outcome=json.loads(outcome_path.read_text())
        endpoint=f'/api/v0/asks/{OFFER}/'
        if (not state.get('instance_id') or any(v.get('operation')!='create' or v.get('path')!=endpoint or v.get('method')!='PUT' for v in (intent,outcome))
                or outcome.get('phase')!='response' or outcome.get('success') is not True or outcome.get('new_contract')!=state['instance_id']):
            raise ValueError('Known successful bound CREATE acknowledgement required')
        for path in self.root.glob('intent-*-attach.json'):
            if json.loads(path.read_text()).get('instance_id')==state['instance_id']:
                raise ValueError('Attachment already attempted; preserve its outcome without retry')
        public_path=self.repo/'runs/vast-preflight-20261029/ssh_ed25519.pub'
        if public_path.is_symlink() or public_path.stat().st_size>4096:raise ValueError('Bounded original public-key file required')
        public=public_path.read_text().strip()
        if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]+(?: [A-Za-z0-9@._-]+)?',public):raise ValueError('Unexpected original public-key format')
        return self.intent(state,'attach',f"/api/v0/instances/{state['instance_id']}/ssh/",{'ssh_key':public},reason,retain_pending_create=True)

    def selection(self,path,expected_offer):
        """One operator-produced, <=10s-old offer row; never another search."""
        path=Path(path)
        if (path.is_symlink() or path.parent.resolve()!=self.root.resolve()
                or not re.fullmatch(r'offer-selection-attempt[1-9][0-9]*\.json',path.name)
                or path.stat().st_size>65536 or expected_offer!=OFFER):
            raise ValueError('Exact fresh Hard selection receipt and expected offer required')
        before=sha(path);value=json.loads(path.read_text());offer=value.get('selected_offer',{})
        at=datetime.fromisoformat(value['at_utc'].replace('Z','+00:00'))
        code_sha=sha(Path(__file__))
        if (at.tzinfo is None or at.utcoffset().total_seconds()!=0 or not 0<=self.clock()-at.timestamp()<=10
                or value.get('project',LABEL)!=LABEL or value.get('helper_after_sha256')!=code_sha
                or value.get('maximum_accepted_rate_usd')!=MAX_RATE
                or (offer.get('id'),offer.get('machine_id'),offer.get('geolocation'))!=(OFFER,MACHINE,REGION)
                or sha(path)!=before):
            raise ValueError('Offer selection timestamp, source hash or reviewed target differs')
        return offer,{'path':str(path.resolve()),'sha256':before,'at_utc':value['at_utc']}

    def no_dispatch(self,destination):
        if self.state_path.exists() or self.scope_path.exists() or any(self.root.glob('intent-*.json')):
            raise ValueError('A canonical rental or mutation intent exists')
        rows=self.inventory()
        if rows:raise ValueError('Complete inventory is not empty; manual reconciliation required')
        value={'project':LABEL,'operation':'confirm-no-dispatch','no_dispatch':True,'complete_inventory':True,
               'inventory_count':0,'canonical_state_absent':True,'scope_absent':True,'new_mutation_intents_absent':True,
               'checked_epoch':self.clock(),'stop_confirmed':True}
        write(destination,value,exclusive=True)
        return value

    def create(self,expected_offer=None,selection_receipt=None,remaining_hours=None):
        if expected_offer is not None and expected_offer!=OFFER:
            raise ValueError('Expected offer differs from reviewed helper pin')
        planned=REMAINING_HOURS if remaining_hours is None else remaining_hours
        if type(planned) not in (int,float) or not math.isfinite(planned) or not 0<=planned<=REMAINING_HOURS:
            raise ValueError('Explicit remaining-work estimate must stay within 0..5 hours')
        self.verify_host_archives()
        for archival in self.root.glob('archive-*-intent.json'):
            plan=json.loads(archival.read_text());archive=Path(plan['archive_path'])
            if (archive.parent.resolve()!=self.root.resolve() or archive.is_symlink()
                    or not re.fullmatch(r'provisioning-attempt[1-9][0-9]*-rejected',archive.name)):
                raise ValueError('Rejected-create archive path differs')
            final=archive/'archive-complete.json'
            failure=self.root/(archival.stem.removesuffix('-intent')+'-failure.json')
            if not final.exists() or failure.exists():
                raise ValueError('Rejected-create archival incomplete; manual review required')
            value=json.loads(final.read_text())
            expected_files={**plan['source_files_sha256'],'inspection.json':plan['inspection']['sha256']}
            if (value.get('project')!=LABEL or value.get('failed_rental_cost_usd')!=0
                    or value.get('prior_baseline')!=self.baseline()
                    or value.get('archive_intent_sha256')!=sha(archival)
                    or value.get('archived_files_sha256')!=expected_files):
                raise ValueError('Rejected-create archival proof differs')
            for name,expected in value['archived_files_sha256'].items():
                if Path(name).name!=name or sha(final.parent/name)!=expected:raise ValueError('Rejected-create history changed')
        if self.state_path.exists() or self.scope_path.exists():
            raise ValueError('Create already attempted; GET-only reconciliation required')
        prior = self.baseline()
        selection=None
        if selection_receipt:
            offer,selection=self.selection(selection_receipt,expected_offer)
        else:
            selected = [row for row in self.offers() if row['id'] == OFFER]
            if len(selected) != 1:raise ValueError('Selected offer unavailable')
            offer = selected[0]
        numeric = ('dph_total', 'storage_total_cost', 'inet_down_cost', 'inet_up_cost')
        if (any(type(offer.get(k)) not in (int,float) or not math.isfinite(offer[k]) or offer[k] < 0 for k in numeric)
                or not 0 < offer['dph_total'] <= MAX_RATE or offer['storage_total_cost'] > offer['dph_total']
                or offer['machine_id'] != MACHINE or offer['verification'] != 'verified' or offer['gpu_name'] != 'RTX PRO 6000 WS'
                or offer['num_gpus'] != 1 or offer['gpu_ram'] < 90000 or offer['disk_space'] < 150
                or offer['cuda_max_good'] < 13 or offer['rentable'] is not True or offer['rented'] is not False
                or offer['is_bid'] is not False or offer['geolocation'] != REGION
                or offer.get('external') not in (False,None)
                or (offer.get('ask_contract_id') is not None
                    and (type(offer['ask_contract_id']) is not int or offer['ask_contract_id']!=offer['id']))
                or type(offer.get('reliability')) not in (int,float) or not math.isfinite(offer['reliability']) or offer['reliability'] < .99
                or type(offer.get('cpu_ram')) not in (int,float) or not math.isfinite(offer['cpu_ram']) or offer['cpu_ram'] < 64000
                or offer['inet_down_cost']*100 + offer['inet_up_cost']*10 > NETWORK):
            raise ValueError('Selected verified on-demand offer or network terms changed')
        public = (self.repo/'runs/vast-preflight-20261029/ssh_ed25519.pub').read_text().strip()
        if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]+(?: [A-Za-z0-9@._-]+)?', public):
            raise ValueError('Unexpected public SSH key format')
        now = self.clock()
        state = {'project': LABEL, 'label': LABEL, 'offer_id': OFFER, 'machine_id': MACHINE, 'image': IMAGE,
                 'prior_baseline': prior, 'created_epoch': now, 'dph_total': offer['dph_total'],
                 'storage_dph': offer['storage_total_cost'], 'inet_down_cost': offer['inet_down_cost'],
                 'inet_up_cost': offer['inet_up_cost'], 'remaining_gpu_hours': planned,
                 'selected_offer_identifiers':{k:offer.get(k) for k in ('id','ask_contract_id','bundle_id','external')},
                 'running_intervals': [{'start_epoch': now, 'reason': 'create including provisioning'}],
                 'existing_instance_ids': [row['id'] for row in self.inventory()]}
        state['prior_hard_hosts']=self.history()
        if state['prior_hard_hosts']:state['prior_hard_history']=self.history_manifest()
        if selection:state['offer_selection_receipt']=selection
        self.forecast(state)
        self.active()  # A running, bounded owning process must exist before rental.
        startup = ("set -eu\nprintf '%s\\n' 'SERVEDOCTOR_HARD_SSH_SETUP_BEGIN'\nmkdir -p /root/.ssh /workspace/servedoctor-hard\n"
                   "touch /root/.ssh/authorized_keys /root/.no_auto_tmux\nchown 0:0 /root /root/.ssh /root/.ssh/authorized_keys\n"
                   "chmod go-w /root\nchmod 700 /root/.ssh\nchmod 600 /root/.ssh/authorized_keys\n"
                   "printf '%s\\n' '"+public+"' >> /root/.ssh/authorized_keys\n"
                   "printf '%s\\n' 'SERVEDOCTOR_HARD_SSH_SETUP_DONE'\nexec /opt/instance-tools/bin/entrypoint.sh\n")
        if selection:
            _,fresh=self.selection(selection_receipt,expected_offer)
            if fresh!=selection:raise ValueError('Selection receipt changed before dispatch')
        return self.intent(state, 'create', f'/api/v0/asks/{OFFER}/', {'client_id': 'me', 'image': IMAGE,
            'disk': 150, 'runtype': 'ssh_direct', 'target_state': 'running', 'cancel_unavail': True,
            'label': LABEL, 'onstart': startup})

    def inspect_rejected_create(self,destination):
        """GET-only provider inspection; old state/intent/outcome bytes stay intact."""
        state=self.load()
        if state.get('instance_id') or self.scope_path.exists():raise ValueError('Unbound failed create required')
        name=state.get('pending_intent','')
        if Path(name).name!=name or not name.startswith('intent-'):raise ValueError('Pending create proof missing')
        intent_path=self.root/name;intent=json.loads(intent_path.read_text())
        outcome_path=self.root/(intent_path.stem+'-outcome.json');outcome=json.loads(outcome_path.read_text())
        if (intent.get('operation')!='create' or intent.get('path')!=f"/api/v0/asks/{state['offer_id']}/"
                or outcome.get('operation')!='create' or outcome.get('path')!=intent['path']):
            raise ValueError('Create intent/outcome binding differs')
        rows=self.inventory()  # Complete paginated inventory supplied by v0 instances().
        safe=[{k:r.get(k) for k in ('id','label','machine_id','actual_status','cur_state','intended_status')} for r in rows]
        rejected=outcome.get('phase')=='response' and outcome.get('http_status')==400 and outcome.get('success') is False
        receipt={'project':LABEL,'operation':'inspect-rejected-create','inspected_epoch':self.clock(),
                 'instance_id':None,'offer_id':state['offer_id'],'machine_id':state['machine_id'],
                 'complete_inventory':True,'inventory_count':len(rows),'safe_inventory':safe,
                 'http_400_success_false':rejected,'confirmed_no_instances':not rows,
                 'prior_baseline':self.baseline(),
                 'source_files_sha256':{p.name:sha(p) for p in (self.state_path,intent_path,outcome_path)}}
        write(destination,receipt,exclusive=True)
        return receipt

    def archive_rejected_create(self,inspection,archive_name='provisioning-attempt2-rejected'):
        """Explicit one-shot local transition only; no rental mutation or retry.

        Requires a fresh known-400/empty-inventory receipt AND another complete
        GET inventory. Moves the rejected bytes intact; no state is rewritten.
        Any interrupted archive blocks create until manually reviewed.
        """
        if not re.fullmatch(r'provisioning-attempt[1-9][0-9]*-rejected',archive_name):
            raise ValueError('Explicit safe rejected-attempt archive name required')
        inspection=Path(inspection);receipt=json.loads(inspection.read_text());state=self.load()
        if (receipt.get('project')!=LABEL or receipt.get('operation')!='inspect-rejected-create'
                or receipt.get('complete_inventory') is not True or receipt.get('inventory_count')!=0
                or receipt.get('safe_inventory')!=[] or receipt.get('confirmed_no_instances') is not True
                or receipt.get('http_400_success_false') is not True
                or receipt.get('prior_baseline')!=self.baseline()
                or not 0<=self.clock()-receipt['inspected_epoch']<=60
                or (receipt.get('offer_id'),receipt.get('machine_id'))!=(state['offer_id'],state['machine_id'])
                or state.get('instance_id') or self.scope_path.exists()):
            raise ValueError('Fresh definitive rejection plus zero-inventory proof required')
        files=receipt['source_files_sha256']
        expected={self.state_path.name,state['pending_intent'],Path(state['pending_intent']).stem+'-outcome.json'}
        if set(files)!=expected:raise ValueError('Rejected attempt must include exactly session/intent/outcome')
        for name,expected_sha in files.items():
            if Path(name).name!=name or sha(self.root/name)!=expected_sha:raise ValueError('Rejected attempt changed')
        intent=json.loads((self.root/state['pending_intent']).read_text())
        outcome=json.loads((self.root/(Path(state['pending_intent']).stem+'-outcome.json')).read_text())
        if (intent.get('operation')!='create' or intent.get('path')!=f"/api/v0/asks/{state['offer_id']}/"
                or outcome.get('operation')!='create' or outcome.get('path')!=intent['path']
                or outcome.get('phase')!='response' or outcome.get('http_status')!=400 or outcome.get('success') is not False):
            raise ValueError('Independent original HTTP400 rejection proof required')
        if self.inventory():raise ValueError('Inventory is no longer empty; archive refused')
        snapshot=self.root/'v0-gpu-hours-before-hard.md'
        if not snapshot.exists():raise ValueError('Preserved v0 hours snapshot missing')
        archive=self.root/archive_name
        plan_path=self.root/('archive-rejected-create-intent.json' if archive_name=='provisioning-attempt2-rejected'
                             else 'archive-'+archive_name+'-intent.json')
        if archive.exists() or plan_path.exists():raise FileExistsError('Archival was already attempted')
        plan={'project':LABEL,'operation':'archive-definitively-rejected-create','at_epoch':self.clock(),
              'inspection':{'path':str(inspection.resolve()),'sha256':sha(inspection)},
              'archive_path':str(archive),'source_files_sha256':files,'failed_rental_cost_usd':0.0,
              'reason':'HTTP400 successfalse and two complete zero-inventory observations; no confirmed rental'}
        write(plan_path,plan,exclusive=True)
        archive.mkdir();moved=[]
        try:
            for name in sorted(files):
                (self.root/name).rename(archive/name);moved.append(name)
                if sha(archive/name)!=files[name]:raise ValueError('Archived bytes differ')
            with (archive/'inspection.json').open('xb') as stream:stream.write(inspection.read_bytes())
            archived={**files,'inspection.json':sha(archive/'inspection.json')}
            final={'project':LABEL,'archive_intent_sha256':sha(plan_path),'archived_files_sha256':archived,
                   'failed_rental_cost_usd':0.0,'prior_baseline':self.baseline(),'completed_epoch':self.clock()}
            hours=self.repo/'runs/servedoctor-gpu-hours.md'
            content=(snapshot.read_text()+f'\n\n## Hard {archive_name}\n\n'
                     +f'HTTP400 successfalse; two complete inventories confirmed zero instances. Failed rental cost $0; prior v0 upper ${PRIOR_USD:.12f}.\n\n'
                     +f'Immutable rejection archive: {archive}; archive-intent SHA256 {sha(plan_path)}.\n')
            temporary=hours.with_suffix('.hard.tmp');temporary.write_text(content);temporary.replace(hours)
            final.update(v0_gpu_hours_snapshot_sha256=sha(snapshot),aggregate_gpu_hours_sha256=sha(hours))
            write(archive/'archive-complete.json',final,exclusive=True)
            return final
        except Exception as exc:
            write(self.root/(plan_path.stem.removesuffix('-intent')+'-failure.json'),
                  {'error_class':type(exc).__name__,'moved_files':moved,'archive_intent_sha256':sha(plan_path)},exclusive=True)
            raise

    def identity(self, row, state):
        if (row.get('id'), row.get('label'), row.get('machine_id')) != (state['instance_id'], LABEL, MACHINE):
            raise ValueError('Inventory rental identity differs')
        if row.get('image_uuid') and row['image_uuid'] not in (IMAGE, IMAGE.split('@')[1], IMAGE.split(':')[-1]):
            raise ValueError('Inventory image differs')

    @staticmethod
    def stopped(row):
        return row.get('actual_status') in ('stopped','exited') and row.get('cur_state') in ('stopped','exited') and row.get('intended_status') != 'running'

    def reconcile(self):
        state, rows = self.load(), self.inventory()
        if not state.get('instance_id'):
            candidates = [r for r in rows if r['id'] not in state['existing_instance_ids'] and r.get('label') == LABEL and r.get('machine_id') == MACHINE]
            if len(candidates) != 1:
                raise ValueError('Create unresolved: exactly one scoped new inventory row required')
            self.bind(state, candidates[0]['id'])
        row = next((r for r in rows if r['id'] == state['instance_id']), None)
        pending = json.loads((self.root/state['pending_intent']).read_text()) if state.get('pending_intent') else None
        if row is None:
            if not ((pending and pending['operation'] == 'delete') or state.get('destroyed_epoch')):
                raise ValueError('Scoped instance absent without DELETE intent')
            state.setdefault('destroyed_epoch', self.clock())
            state.pop('pending_intent', None)
        else:
            self.identity(row, state)
            state['last_status'] = self.safe_row(row)
            if row.get('actual_status') == 'running':
                for interval in state['running_intervals']:
                    if 'stop_epoch' not in interval:
                        interval.setdefault('running_seen_epoch', self.clock())
            if self.stopped(row):
                for interval in state['running_intervals']:
                    if 'running_seen_epoch' in interval or (pending and pending['operation'] == 'stop'):
                        interval.setdefault('stop_epoch', self.clock())
            if pending and ((pending['operation'] in ('create','start') and row.get('actual_status') == 'running')
                            or (pending['operation'] == 'stop' and self.stopped(row))):
                write(self.root/(Path(state['pending_intent']).stem+'-reconciled.json'),
                      {'operation': pending['operation'], 'confirmed_epoch': self.clock(), 'status': self.safe_row(row)}, exclusive=True)
                state.pop('pending_intent')
        state['live_action_attempted'] = True
        self.save(state)
        return {'instance_id': state['instance_id'], 'status': state.get('last_status'),
                'destroyed_epoch': state.get('destroyed_epoch'), 'pending_intent': state.get('pending_intent'), 'cost': self.cost(state)}

    def heartbeat(self, pid, until, remaining=None):
        birth = self.birth(pid)
        if not birth or not self.clock() < until <= min(DEADLINE, self.clock()+7200):
            raise ValueError('Live process and deadline within two hours required')
        if remaining is not None:
            if type(remaining) not in (int,float) or not math.isfinite(remaining) or not 0 <= remaining <= REMAINING_HOURS:
                raise ValueError('Remaining GPU estimate outside 0..5 hours')
            state = self.load(); state['remaining_gpu_hours'] = remaining; self.forecast(state); self.save(state)
        value = {'project': LABEL, 'pid': pid, 'birth': birth, 'deadline_epoch': until, 'at_epoch': self.clock()}
        write(self.root/'active-command.json', value)
        return value

    def active(self):
        value = json.loads((self.root/'active-command.json').read_text())
        if (value.get('project') != LABEL
                or any(type(value.get(k)) not in (int,float) or not math.isfinite(value[k]) for k in ('at_epoch','deadline_epoch'))
                or not 0 <= self.clock()-value['at_epoch'] <= HEARTBEAT_TTL
                or self.clock() >= value['deadline_epoch'] or self.clock() >= DEADLINE
                or self.birth(value['pid']) != value['birth']):
            raise ValueError('Idle, expired or dead owning process')
        return value

    @staticmethod
    def startup_window_at(root,path,state,clock=time.time):
        """Read-only exception policy for one explicitly selected SSH window."""
        if not path:return None
        root=Path(root).resolve();path=Path(path).resolve()
        if (path.name!='plan.json' or path.parent.parent!=root
                or not re.fullmatch(r'startup-ssh-window-attempt[1-9][0-9]*',path.parent.name)):
            raise ValueError('Fixed scoped startup window plan required')
        if not path.exists():return None
        plan=json.loads(path.read_text())
        times=(plan.get('started_epoch'),plan.get('deadline_epoch'))
        if (path.is_symlink() or plan.get('project')!=LABEL or plan.get('instance_id')!=state.get('instance_id')
                or plan.get('rental_scope_sha256')!=state.get('scope_sha256')
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in times)
                or plan.get('window_seconds')!=600 or plan['deadline_epoch']!=plan['started_epoch']+600
                or plan.get('terminal_receipt_path')!=str(path.parent/'terminal.json')
                or plan.get('allowed_remote_argv')!=['cat','/etc/vast-agents-guide.md']
                or plan.get('no_create_start_attach_retries') is not True
                or plan.get('helper_sha256')!=sha(root/'startup_ssh_window.py')):
            raise ValueError('Startup window scope, clock or helper binding differs')
        if plan.get('mode')=='pre-generation-restart' and (plan.get('restart_helper_sha256')!=sha(root/'restart_ssh_window.py')
                or plan.get('no_setup_commands_in_this_window') is not True):
            raise ValueError('Restart-window helper or read-only policy changed')
        if plan.get('mode')=='partial-bootstrap-restart' and (plan.get('partial_helper_sha256')!=sha(root/'partial_bootstrap_ssh_window.py')
                or plan.get('no_setup_commands_in_this_window') is not True
                or plan.get('known_partial_bootstrap') is not True or plan.get('completed_calibration') is not False):
            raise ValueError('Partial-bootstrap window helper or read-only policy changed')
        if plan.get('mode')=='calibrated-host5-restart' and (plan.get('calibrated_helper_sha256')!=sha(root/'calibrated_host5_ssh_window.py')
                or plan.get('no_setup_commands_in_this_window') is not True
                or plan.get('known_completed_bootstrap') is not True or plan.get('completed_calibration') is not True):
            raise ValueError('Calibrated window helper or read-only policy changed')
        if plan.get('mode')=='frozen-host5-restart' and (plan.get('frozen_helper_sha256')!=sha(root/'frozen_host5_ssh_window.py')
                or plan.get('no_setup_commands_in_this_window') is not True
                or plan.get('remote_frozen_study_exists') is not True
                or plan.get('no_recording_or_model_dispatch_observed') is not True):
            raise ValueError('Frozen-study window helper or read-only policy changed')
        if plan.get('mode')=='partial-analysis-host5-restart' and (plan.get('partial_analysis_helper_sha256')!=sha(root/'partial_analysis_ssh_window.py')
                or plan.get('no_setup_commands_in_this_window') is not True
                or plan.get('completed_hard_incidents')!=15):
            raise ValueError('Authorized fifteen-case window helper or read-only policy changed')
        authenticated=False;proof_path=path.parent/'authenticated.json'
        if proof_path.exists():
            proof=json.loads(proof_path.read_text());expected={'path':str(path),'sha256':sha(path)}
            if (proof.get('project')!=LABEL or proof.get('instance_id')!=state['instance_id']
                    or proof.get('rental_scope_sha256')!=state['scope_sha256'] or proof.get('guide_authenticated') is not True
                    or proof.get('plan')!=expected):raise ValueError('Startup authentication proof differs')
            for key in ('probe_outcome','guide'):
                descriptor=proof[key];target=Path(descriptor['path'])
                if not target.resolve().is_relative_to(path.parent) or sha(target)!=descriptor['sha256']:raise ValueError('Authentication payload differs')
            authenticated=True
        return {'path':str(path),'plan':plan,'authenticated':authenticated,'expired':clock()>=plan['deadline_epoch']}

    def startup_window(self,path,state):return self.startup_window_at(self.root,path,state,self.clock)

    def mutate(self, operation, reason='', backup=None):
        if operation == 'stop':
            from continuation_stop_guard import decline_legacy_stop
            handoff = decline_legacy_stop(self, reason)
            if handoff is not None:
                return handoff
        self.reconcile()
        state = self.load()
        pending=json.loads((self.root/state['pending_intent']).read_text()) if state.get('pending_intent') else None
        if pending and pending['operation']=='delete':raise ValueError('DELETE pending: GET-only reconciliation, no later mutation')
        if state.get('destroyed_epoch'):
            raise ValueError('Rental was deleted')
        row = state['last_status']
        if operation=='attach':
            self.forecast(state)
            for path in self.root.glob('intent-*-attach.json'):
                previous=json.loads(path.read_text())
                if previous.get('instance_id')==state['instance_id']:
                    raise ValueError('Public-key attachment already attempted; preserve/reconcile its outcome')
            public_path=self.repo/'runs/vast-preflight-20261029/ssh_ed25519.pub'
            if public_path.is_symlink() or public_path.stat().st_size>4096:
                raise ValueError('Expected bounded regular public-key file')
            public=public_path.read_text().strip()
            if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]+(?: [A-Za-z0-9@._-]+)?',public):
                raise ValueError('Unexpected SSH public key format')
            return self.intent(state,'attach',f"/api/v0/instances/{state['instance_id']}/ssh/",{'ssh_key':public},reason)
        if operation == 'stop':
            pending = json.loads((self.root/state['pending_intent']).read_text()) if state.get('pending_intent') else None
            if self.stopped(row) and not (pending and pending['operation'] in ('create','start')):
                return {'already_stopped': True, 'cost': self.cost(state)}
            if state.get('pending_intent'):
                old = json.loads((self.root/state['pending_intent']).read_text())
                if old['operation'] == 'stop':
                    raise ValueError('Stop already attempted; GET-only reconcile')
                state.setdefault('superseded_for_emergency_stop', []).append(state.pop('pending_intent'))
        elif operation == 'start':
            if not self.stopped(row):
                raise ValueError('Start requires confirmed stopped state')
            self.active(); self.forecast(state)
            state['running_intervals'].append({'start_epoch': self.clock(), 'reason': reason})
        elif operation == 'delete':
            if not self.stopped(row) or any('stop_epoch' not in i for i in state['running_intervals']):
                raise ValueError('Deletion requires confirmed stopped state')
            self.backup(state, backup)
        else:
            raise ValueError('Unsupported mutation')
        path = f"/api/v0/instances/{state['instance_id']}/"
        return self.intent(state, operation, path, None if operation == 'delete' else {'state': 'running' if operation == 'start' else 'stopped'}, reason)

    def backup(self, state, path):
        if not path:
            raise ValueError('Final verified backup receipt required before deletion')
        receipt = json.loads(Path(path).read_text())
        if (receipt.get('project') != LABEL or receipt.get('instance_id') != state['instance_id']
                or receipt.get('rental_scope_sha256') != state['scope_sha256']
                or receipt.get('all_remote_artifacts_backed_up') is not True
                or receipt.get('last_stop_epoch') != state['running_intervals'][-1]['stop_epoch']):
            raise ValueError('Final backup scope or stopped accounting differs')
        descriptor = receipt['evidence_manifest']; manifest_path = Path(descriptor['path'])
        if sha(manifest_path) != descriptor['sha256']:
            raise ValueError('Backup manifest hash differs')
        manifest = json.loads(manifest_path.read_text()); base = Path(manifest['root']).resolve()
        files = manifest['files']
        if not files:
            raise ValueError('Empty backup manifest')
        verified = set()
        for relative, expected in files.items():
            p = Path(relative)
            if p.is_absolute() or '..' in p.parts or not (base/p).resolve().is_relative_to(base) or sha(base/p) != expected:
                raise ValueError('Backup file changed or outside manifest root')
            verified.add((base/p).resolve())
        ledger = receipt['canonical_ledger']; ledger_path = Path(ledger['path'])
        if ledger_path.resolve() not in verified or sha(ledger_path) != ledger['sha256'] or ledger['remote_sha256'] != ledger['sha256']:
            raise ValueError('Canonical remote ledger bytes are not backed up')
        if self.scope_path.resolve() not in verified:
            raise ValueError('Immutable rental scope not backed up')
        study = self.repo/'runs/sd-hard'
        if (study.is_symlink() or not study.is_dir()
                or not all(p.resolve() in verified and not p.is_symlink() for p in study.rglob('*') if p.is_file())):
            raise ValueError('Entire final Hard study must be hash-verified in the backup')
        required = ('study.json','scenarios.json','commitment.json','answers/answer_keys.json','report.json','report.html')
        if any((study/name).resolve() not in verified for name in required):
            raise ValueError('Final Hard study, opaque keys and reports must be backed up')
        names = {'reference', *(f'hard-{n:02d}' for n in range(1,17))}
        incident_root = study/'incidents'
        if incident_root.is_symlink() or {p.name for p in incident_root.iterdir()} != names:
            raise ValueError('Exactly reference plus 16 Hard incidents required')
        sealed = {'engine_config.json','engine_identity.json','events.json','slo.json',
                  'telemetry.jsonl','requests.jsonl','recording.json'}
        for name in names:
            folder = incident_root/name
            if folder.is_symlink(): raise ValueError('Incident directory cannot be a symlink')
            seal = json.loads((folder/'manifest.json').read_text())['files']
            if (set(seal) != sealed or {p.name for p in folder.iterdir()} != sealed|{'manifest.json'}
                    or json.loads((folder/'recording.json').read_text()).get('status') != 'completed'
                    or any(sha(folder/item) != digest for item,digest in seal.items())):
                raise ValueError('Every Hard recording must retain all seven sealed payloads')
        state['delete_backup_receipt'] = {'path': str(Path(path).resolve()), 'sha256': sha(path)}

    def inventory_failure(self,state,exc):
        """Journal safe classes and one bounded outage window; no provider retry."""
        now=self.clock();path=self.root/'inventory-read-error-window.json'
        window=json.loads(path.read_text()) if path.exists() else None
        binding={'project':LABEL,'instance_id':state.get('instance_id'),'rental_scope_sha256':state.get('scope_sha256')}
        if window and any(window.get(k)!=v for k,v in binding.items()):raise ValueError('Inventory outage scope changed')
        if not window or window.get('recovered_epoch') is not None:
            window={**binding,'first_failure_epoch':now,'failures':0}
        if not 0<=now-window['first_failure_epoch']:raise ValueError('Inventory outage clock moved backwards')
        window.update(last_failure_epoch=now,failures=window['failures']+1,error_class=type(exc).__name__)
        write(path,window)
        with (self.root/'inventory-read-errors.jsonl').open('a') as stream:
            stream.write(json.dumps({**window,'event':'read_failure'},allow_nan=False)+'\n');stream.flush();os.fsync(stream.fileno())
        return window

    def inventory_recovered(self):
        path=self.root/'inventory-read-error-window.json'
        if path.exists():
            window=json.loads(path.read_text())
            if window.get('recovered_epoch') is None:
                window['recovered_epoch']=self.clock();write(path,window)
                with (self.root/'inventory-read-errors.jsonl').open('a') as stream:
                    stream.write(json.dumps({**window,'event':'read_recovered'},allow_nan=False)+'\n');stream.flush();os.fsync(stream.fileno())

    def watchdog_step(self,startup_window_plan=None):
        try:
            self.reconcile()
        except Exception as exc:
            # A transient GET failure is retained. A fresh real owner can keep
            # working for at most120s; budget/deadline and dead owners still win.
            state = self.load()
            outage=self.inventory_failure(state,exc)
            pending = json.loads((self.root/state['pending_intent']).read_text()) if state.get('pending_intent') else None
            if state.get('destroyed_epoch') or (pending and pending['operation'] in ('stop','delete')):
                return {'finished': bool(state.get('destroyed_epoch')), 'inventory_error_class': type(exc).__name__,
                        'awaiting_read_only_reconciliation': True}
            if startup_window_plan:
                try:
                    self.forecast(state);window=self.startup_window(startup_window_plan,state)
                    if window and not window['authenticated']:
                        return {'finished':False,'startup_window_preserved':True,'budget_guard_active':True,
                                'awaiting_read_only_reconciliation':True,'inventory_error_class':type(exc).__name__}
                    if window is None:
                        self.active()
                        return {'finished':False,'provisioning_owner_active':True,'budget_guard_active':True,
                                'awaiting_read_only_reconciliation':True,'inventory_error_class':type(exc).__name__}
                except (ValueError,OSError,KeyError,TypeError):pass
            try:
                self.forecast(state);owner=self.active()
                if self.clock()-outage['first_failure_epoch']<INVENTORY_FAILURE_GRACE:
                    return {'finished':False,'inventory_error_class':type(exc).__name__,
                            'awaiting_read_only_reconciliation':True,'active_owner_preserved':True,
                            'owner_pid':owner['pid'],'inventory_failure_first_epoch':outage['first_failure_epoch'],
                            'inventory_grace_deadline_epoch':outage['first_failure_epoch']+INVENTORY_FAILURE_GRACE}
            except (ValueError,OSError,KeyError,TypeError):pass
            if not state.get('instance_id'):
                raise ValueError('Cannot stop an unbound create; reconcile inventory') from None
            if state.get('pending_intent'):
                state.setdefault('superseded_for_emergency_stop', []).append(state.pop('pending_intent'))
            return self.intent(state, 'stop', f"/api/v0/instances/{state['instance_id']}/", {'state':'stopped'},
                               reason='inventory unavailable; conservative shutdown')
        self.inventory_recovered()
        state = self.load()
        pending = json.loads((self.root/state['pending_intent']).read_text()) if state.get('pending_intent') else None
        if pending and pending['operation']=='delete':
            return {'finished':False,'awaiting_delete_confirmation':True,'awaiting_read_only_reconciliation':True}
        if state.get('destroyed_epoch') or (self.stopped(state['last_status'])
                and not (pending and pending['operation'] in ('create','start'))
                and all('stop_epoch' in item for item in state['running_intervals'])):
            return {'finished': True}
        try:
            self.forecast(state)
            if startup_window_plan:
                window=self.startup_window(startup_window_plan,state)
                if window and not window['authenticated']:
                    return {'finished':False,'startup_window_preserved':True,'budget_guard_active':True,'awaiting_backup_delete':window['expired']}
            self.active()
            return {'finished': False, 'active': True}
        except (ValueError, OSError, KeyError, TypeError):
            if state.get('pending_intent'):
                pending = json.loads((self.root/state['pending_intent']).read_text())
                if pending['operation'] in ('stop','delete'):
                    return {'finished': False, 'awaiting_stop_confirmation':pending['operation']=='stop',
                            'awaiting_delete_confirmation':pending['operation']=='delete','awaiting_read_only_reconciliation':True}
            return self.mutate('stop', reason='idle/deadline/budget guard')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['offers','status','create','start','stop','delete','attach','attach-early','reconcile','heartbeat','watchdog',
                                             'inspect-rejected-create','archive-rejected-create','confirm-no-dispatch'])
    parser.add_argument('--reason', default='explicit operator request')
    parser.add_argument('--pid', type=int); parser.add_argument('--until-utc')
    parser.add_argument('--remaining-hours', type=float); parser.add_argument('--backup-receipt')
    parser.add_argument('--inspection-receipt')
    parser.add_argument('--archive-name',default='provisioning-attempt2-rejected')
    parser.add_argument('--expected-offer',type=int)
    parser.add_argument('--offer-selection-receipt')
    parser.add_argument('--startup-window-plan')
    args = parser.parse_args(); service = Rental()
    if args.operation == 'watchdog':
        while True:
            with service.lock(): result = service.watchdog_step(args.startup_window_plan)
            if result.get('finished'): break
            time.sleep(5)  # Own process death is checked at least every inventory cycle.
    else:
        with service.lock():
            if args.operation == 'offers': result = service.offers()
            elif args.operation in ('status','reconcile'): result = service.reconcile()
            elif args.operation == 'create': result = service.create(args.expected_offer,args.offer_selection_receipt,args.remaining_hours)
            elif args.operation == 'attach-early':result=service.attach_early(args.reason)
            elif args.operation == 'confirm-no-dispatch':result=service.no_dispatch(args.inspection_receipt)
            elif args.operation == 'inspect-rejected-create': result=service.inspect_rejected_create(args.inspection_receipt)
            elif args.operation == 'archive-rejected-create': result=service.archive_rejected_create(args.inspection_receipt,args.archive_name)
            elif args.operation == 'heartbeat':
                parsed = datetime.fromisoformat(args.until_utc.replace('Z','+00:00'))
                if parsed.tzinfo is None: raise ValueError('Timezone-aware deadline required')
                result = service.heartbeat(args.pid, parsed.timestamp(), args.remaining_hours)
            else: result = service.mutate(args.operation, args.reason, args.backup_receipt)
    print(json.dumps(result, indent=2, allow_nan=False))
    handed_off = (args.operation == 'stop' and result.get('continuation_handoff') is True
                  and result.get('stop_requested') is False and result.get('provider_request_dispatched') is False)
    return 1 if args.operation in ('create','start','stop','delete','attach','attach-early') and result.get('success') is not True and result.get('already_stopped') is not True and not handed_off else 0


if __name__ == '__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        # Static exception class only: never provider text, public keys or secrets.
        raise SystemExit('Hard operation failed: '+type(exc).__name__) from None
