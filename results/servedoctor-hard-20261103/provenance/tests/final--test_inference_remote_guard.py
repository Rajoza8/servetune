"""Synthetic /proc/time/HTTP only; no actual credentials or network."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import inference_remote_guard as g


class GuardContracts(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.addCleanup(patch.stopall)
        self.base=Path(self.t.name).resolve();self.control=self.base/'control';self.control.mkdir();self.repo=self.base/'servetune';self.repo.mkdir()
        self.proc=self.base/'proc';self.proc.mkdir();self.now=1000.;self.mono=0.;self.stops=[]
        patch.object(g,'REPO',self.repo).start()
        self.scope={'project':g.PROJECT,'label':g.PROJECT,'instance_id':999,'allocation_started_epoch':1000.,'allocation_deadline_epoch':11800.,
            'budget_amendment':{'sha256':'8efba5368ca146e45ff55d16fb45567058ae015bcee51a26a5510a0e31c4ee2a'}}
        (self.control/'rental-scope.json').write_text(json.dumps(self.scope))
        self.helpers={}
        for name in g.APPROVED:
            p=self.repo/'runs/servedoctor-hard15-ops-20261102'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('# fixed inference helper '+name)
            self.helpers[str(p)]=g.digest(p)
        self.helpers['/tmp/servedoctor-inference-bootstrap/inference_cold_bootstrap.py']='a'*64
        self.config={'project':g.PROJECT,'instance_id':999,'rental_scope_sha256':g.digest(self.control/'rental-scope.json'),
            'deadline_epoch':11800.,'budget_deadline_epoch':11800.,'approved_helpers_sha256':self.helpers};self.save()
    def save(self):(self.control/'inference-guard-state.json').write_text(json.dumps(self.config))
    def sleep(self,n):self.now+=n;self.mono+=n
    def stop(self,*args,**_):self.stops.append(args);return {'reason':args[2]}
    def process(self,pid,args,cwd,uid=None):
        uid=os.getuid() if uid is None else uid;p=self.proc/str(pid);p.mkdir()
        (p/'status').write_text(f'Uid:\t{uid}\t{uid}\t{uid}\t{uid}\n');(p/'cmdline').write_bytes(b'\0'.join(v.encode() for v in args)+b'\0')
        (p/'cwd').symlink_to(cwd,target_is_directory=True);(p/'stat').write_text(str(pid)+' (worker) '+' '.join(['0']*19+['12345']+['0']*5))
    def scan(self):return g.processes(self.proc,uid=os.getuid(),own_pid=99999,control=self.control,repo=self.repo,base=self.base)
    def test_exact3h_scope_budget_overlay_and_helper_map(self):
        value=g.read_state(self.control,999,11800.);self.assertEqual(value['deadline_epoch'],11800.)
        self.config['deadline_epoch']+=1;self.save()
        with self.assertRaises(ValueError):g.read_state(self.control,999,11801.)
    def test_cannot_extend_deadline_or_revert40_overlay(self):
        self.scope['budget_amendment']['sha256']='b'*64;(self.control/'rental-scope.json').write_text(json.dumps(self.scope))
        self.config['rental_scope_sha256']=g.digest(self.control/'rental-scope.json');self.save()
        with self.assertRaises(ValueError):g.read_state(self.control,999,11800.)
    def test_owned_exact_helper_hash_and_cwd_only_no_recording_role(self):
        helper=next(iter(self.helpers));self.process(1,['python3',helper],self.repo)
        self.process(2,['python3','-m','servedoctor','record'],self.repo)
        self.process(3,['python3',helper],self.base);self.process(4,['python3',helper],self.repo,uid=os.getuid()+1)
        self.assertEqual({r['pid'] for r in self.scan()},{1})
        Path(helper).write_text('# altered helper');self.assertEqual(self.scan(),[])
    def test_native_eval_busy_but_record_calibrate_not_allowed(self):
        for pid,role in enumerate(('evaluate','calibrate','record'),1):self.process(pid,['python3','-m','servedoctor',role],self.repo)
        self.assertEqual({r['pid'] for r in self.scan()},{1})
    def test_idle120_and_fixed3h_stop_once_even_when_busy(self):
        result=g.run(self.control,{'CONTAINER_ID':'999'},lambda:self.now,lambda:self.mono,self.sleep,lambda **_:[],self.stop)
        self.assertEqual(result['reason'],'idle');self.assertEqual(self.mono,120.)
        self.now=1000.;self.mono=0.;self.stops=[]
        result=g.run(self.control,{'CONTAINER_ID':'999'},lambda:self.now,lambda:self.mono,self.sleep,lambda **_:[{}],self.stop)
        self.assertEqual(result['reason'],'budget_deadline');self.assertEqual(self.mono,10800.);self.assertEqual(len(self.stops),1)
    def test_wrong_container_never_reads_or_sends_credential(self):
        with self.assertRaises(ValueError):g.stop_once(self.control,999,'idle','a'*64,environ={'CONTAINER_ID':'998'})
        self.assertFalse((self.control/'guard-stop-intent.json').exists())
    def test_exact_child_code_hash_stays_frozen(self):
        self.assertEqual(g.KEY_REMOTE_CHILD_SHA256,'e016fa0da62bf796c5e830b51e7c5196f2ff0cdd5041d23bb1f69d6b2a8bd23e')
        args=['/venv/main/bin/python','-c','altered','1'*40,'999',str(g.KEY_DEADLINE),'evaluate','--study-dir','runs/sd-hard-partial-attempt1','--split','hard','--arms','spark']
        self.process(1,args,self.repo);self.assertEqual(self.scan(),[])
    def test_actual_final_worker_and_evaluation_code_hashes_match(self):
        import inference_key_runner as key
        import inference_evaluation_stage as stage
        self.assertEqual(g.KEY_REMOTE_CODE_SHA256,hashlib.sha256(key.REMOTE_CODE.encode()).hexdigest())
        self.assertEqual(g.KEY_REMOTE_DIAGNOSTIC_SHA256,hashlib.sha256(key.REMOTE_DIAGNOSTIC.encode()).hexdigest())
        self.assertEqual(g.KEY_REMOTE_CHILD_SHA256,hashlib.sha256(key.REMOTE_CHILD.encode()).hexdigest())
        self.assertEqual(g.PRIVATE_REMOTE_SHA256,{'evaluate_'+n.lower():hashlib.sha256(getattr(stage,n).encode()).hexdigest() for n in ('PREPARE','LEDGER','ARCHIVE')})
    def test_orphan_native_child_uses_actual_scope_allocation_deadline(self):
        import inference_key_runner as key
        until=min(self.scope['allocation_deadline_epoch'],key.CUTOFF,key.PAID_DEADLINE)
        args=['/venv/main/bin/python','-c',key.REMOTE_CHILD,'4'*40,'999',str(until),
            'evaluate','--study-dir','runs/sd-hard-partial-attempt1','--split','hard','--arms','spark']
        self.process(1,args,self.repo)
        wrong=args[:];wrong[5]=str(key.PAID_DEADLINE);self.process(2,wrong,self.repo)
        wrong=args[:];wrong[5]=str(until+1);self.process(3,wrong,self.repo)
        self.assertEqual({v['pid'] for v in self.scan()},{1})
        self.assertEqual(self.scan()[0]['kind'],'trusted_key_runner_cli')


if __name__=='__main__':unittest.main()
