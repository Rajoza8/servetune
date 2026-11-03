"""Invented443-row ledger/files only; no actual synchronization or API calls."""
import argparse
import copy
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import sync_inference_ledger as s


class SyncContracts(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.addCleanup(patch.stopall)
        self.repo=Path(self.t.name).resolve();self.ops=self.repo/'runs/servedoctor-hard15-ops-20261102';self.ops.mkdir(parents=True)
        self.args=argparse.Namespace(out=str(self.ops/'inference-ledger-sync-attempt1'),sync=False,verify_only=True)
        self.p=s.paths(self.args,self.repo)
        entries=[{'id':f'old-{i:04d}','provider':'meta','status':'reserved' if i%3==0 else 'settled','reserved_usd':'0.02','accounted_usd':'0.01'} for i in range(443)]
        self.seed={'project':'servedoctor','caps_usd':{'meta':'50','baseten':'20'},'entries':entries}
        self.put(self.p['seed'],self.seed);self.p['canonical'].write_bytes(self.p['seed'].read_bytes());self.p['canonical'].chmod(0o640)
        patch.object(s,'SEED',s.sha(self.p['seed'])).start()
        self.final=copy.deepcopy(self.seed);self.final['entries'] += [
            {'id':'new-spark','provider':'meta','status':'settled','reserved_usd':'0.20','accounted_usd':'0.10'},
            {'id':'new-wonder','provider':'meta','status':'settled','reserved_usd':'0.40','accounted_usd':'0.20'}]
        self.p['final'].write_bytes(json.dumps(self.final,separators=(',\t',': ')).encode()+b'\n')
        self.put(self.p['parent'],{'project':s.PROJECT,'instance_id':s.INSTANCE,'rental_scope_sha256':s.SCOPE,
            'returncode':0,'stop_confirmed':True,'cleanup_confirmed':True,'transport_cleanup_returncode':0,'failure':None})
        state=self.p['cleanup'].parent/'final-state.json';self.put(state,{'project':s.PROJECT,'instance_id':s.INSTANCE,'scope_sha256':s.SCOPE,
            'destroyed_epoch':1300.,'running_intervals':[{'start_epoch':1000.,'stop_epoch':1100.}],
            'last_status':{'actual_status':'exited','cur_state':'stopped','intended_status':'stopped'}})
        rec=state.with_name('delete-reconciliation.json');self.put(rec,{'instance_id':s.INSTANCE,'destroyed_epoch':1300.,'confirmed_absent':True,'pending_intent':None})
        row={'operation':'delete','method':'DELETE','instance_id':s.INSTANCE,'rental_scope_sha256':s.SCOPE,'path':f'/api/v0/instances/{s.INSTANCE}/'}
        intent=self.ops/'inference-rental-attempt1/intent-9999-delete.json';self.put(intent,row)
        outcome=intent.with_name(intent.stem+'-outcome.json');self.put(outcome,{**row,'phase':'response'})
        self.put(self.p['dispatch'],{'project':s.PROJECT,'instance_id':s.INSTANCE,'rental_scope_sha256':s.SCOPE,
            'method':'DELETE','path':f'/api/v0/instances/{s.INSTANCE}/','helper_sha256':s.FINALIZER})
        self.put(self.p['cleanup'],{'project':s.PROJECT,'instance_id':s.INSTANCE,'rental_scope_sha256':s.SCOPE,
            'confirmed_absent':True,'stopped_confirmed':True,'owned_work_quiescent':True,'gpu_accounting':{'total_usd_upper':41.5},'destroyed_epoch':1300.,
            'final_state':s.desc(state),'delete_reconciliation':s.desc(rec),'delete_intent':s.desc(intent),'delete_outcome':s.desc(outcome)})
        self.refresh()
    def put(self,p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+'\n')
    def refresh(self):
        h=s.sha(self.p['final']);summary=s.ReadOnlyLedger(self.p['final']).summary()
        self.put(self.p['native'],{'sha256':h,'summary':summary})
        c=s.load(self.p['cleanup']);c.update(canonical_ledger_sha256=h,remote_ledger_sha256=h,ledger_summary=summary);self.put(self.p['cleanup'],c)
    def mode(self):args=copy.deepcopy(self.args);args.sync=True;args.verify_only=False;return args
    def execute(self,sync=False):return s.execute(self.mode() if sync else self.args,self.repo)
    def tree(self):return {str(p.relative_to(self.repo)):p.read_bytes() for p in self.repo.rglob('*') if p.is_file()}
    def test_default_verify_no_files_no_lock_no_bytes_changed(self):
        before=self.tree();value=self.execute();self.assertTrue(value['verified']);self.assertFalse(value['already_synchronized'])
        self.assertEqual(value['inherited_prefix_entries'],443);self.assertEqual(value['writes'],0);self.assertEqual(before,self.tree())
        self.assertFalse(self.p['final'].with_name(self.p['final'].name+'.lock').exists())
    def test_atomic_exact_bytes_seed_and_permissions_preserved(self):
        before=self.p['canonical'].read_bytes();seed=self.p['seed'].read_bytes();source=self.p['final'].read_bytes()
        result=self.execute(True);self.assertTrue(result['synchronized']);self.assertEqual(self.p['canonical'].read_bytes(),source)
        self.assertEqual(self.p['seed'].read_bytes(),seed);self.assertEqual((self.p['out']/'canonical-before-sync.json').read_bytes(),before)
        self.assertEqual(stat.S_IMODE(self.p['canonical'].stat().st_mode),0o640)
        self.assertEqual(s.load(self.p['out']/'outcome.json')['final_sha256'],s.sha(self.p['final']))
    def test_exact_final_already_present_returns_no_change_even_sync(self):
        self.p['canonical'].write_bytes(self.p['final'].read_bytes());before=self.tree();value=self.execute(True)
        self.assertTrue(value['already_synchronized']);self.assertEqual(value['writes'],0);self.assertEqual(before,self.tree())
    def test_incomplete_parent_or_unconfirmed_delete_blocks(self):
        value=s.load(self.p['parent']);value['returncode']=1;self.put(self.p['parent'],value)
        with self.assertRaises(ValueError):self.execute(True)
        self.assertFalse(self.p['out'].exists());self.assertEqual(s.sha(self.p['canonical']),s.SEED)
    def test_delete_scope_or_finalizer_dispatch_mismatch_blocks(self):
        value=s.load(self.p['dispatch']);value['helper_sha256']='0'*64;self.put(self.p['dispatch'],value)
        with self.assertRaises(ValueError):self.execute(True)
        self.assertEqual(s.sha(self.p['canonical']),s.SEED)
    def test_modified_prefix_blocks_even_when_final_summary_and_sha_match(self):
        self.final['entries'][0]['accounted_usd']='0.00';self.put(self.p['final'],self.final);self.refresh()
        with self.assertRaises(ValueError):self.execute(True)
        self.assertFalse(self.p['out'].exists())
    def test_duplicate_ids_or_changed_caps_block(self):
        self.final['entries'][-1]['id']=self.final['entries'][0]['id'];self.put(self.p['final'],self.final);self.refresh()
        with self.assertRaises(ValueError):self.execute(True)
        self.assertEqual(s.sha(self.p['canonical']),s.SEED)
    def test_native_warning_halts_without_canonical_write(self):
        self.final['entries'][-1]['accounted_usd']='25';self.put(self.p['final'],self.final);self.refresh()
        with self.assertRaises(ValueError):self.execute(True)
        self.assertEqual(s.sha(self.p['canonical']),s.SEED)
    def test_wrong_native_summary_and_cleanup_sha_rejected(self):
        value=s.load(self.p['native']);value['summary']['calls']=0;self.put(self.p['native'],value)
        with self.assertRaises(ValueError):self.execute(True)
        self.assertEqual(s.sha(self.p['canonical']),s.SEED)
    def test_independently_changed_local_ledger_never_overwritten(self):
        self.p['canonical'].write_bytes(b'independent local state')
        with self.assertRaises(ValueError):self.execute(True)
        self.assertEqual(self.p['canonical'].read_bytes(),b'independent local state')
    def test_ledger_payload_never_json_reserialized(self):
        original=json.dump
        def guarded(value,*args,**kwargs):
            if isinstance(value,dict) and value.get('project')=='servedoctor' and 'entries' in value:raise AssertionError('ledger JSON serialization forbidden')
            return original(value,*args,**kwargs)
        with patch.object(json,'dump',guarded):self.execute(True)
        self.assertEqual(self.p['canonical'].read_bytes(),self.p['final'].read_bytes())
    def test_copy_failure_retains_intent_backup_and_temp_never_changes_canonical(self):
        original=s.shutil.copyfileobj;calls=[]
        def broken(source,target,*args,**kwargs):
            calls.append(1)
            if len(calls)==2:target.write(b'interrupted byte copy');raise OSError('invented')
            return original(source,target,*args,**kwargs)
        with patch.object(s.shutil,'copyfileobj',broken):
            with self.assertRaises(OSError):self.execute(True)
        self.assertTrue((self.p['out']/'failure.json').is_file());self.assertTrue((self.p['out']/'intent.json').is_file())
        self.assertEqual(s.sha(self.p['canonical']),s.SEED);self.assertEqual(s.sha(self.p['seed']),s.SEED)
        self.assertTrue(list(self.p['canonical'].parent.glob('servedoctor-ledger.json.inference-sync-*.tmp')))
    def test_noncooperating_canonical_change_detected_before_replace(self):
        original=s.shutil.copyfileobj;calls=[]
        def changed(source,target,*args,**kwargs):
            original(source,target,*args,**kwargs);calls.append(1)
            if len(calls)==2:self.p['canonical'].write_bytes(b'concurrent independent update')
        with patch.object(s.shutil,'copyfileobj',changed):
            with self.assertRaises(ValueError):self.execute(True)
        self.assertEqual(self.p['canonical'].read_bytes(),b'concurrent independent update')
    def test_symlink_canonical_or_lock_never_followed(self):
        saved=self.repo/'other.json';saved.write_bytes(self.p['canonical'].read_bytes());self.p['canonical'].unlink();self.p['canonical'].symlink_to(saved)
        with self.assertRaises(ValueError):self.execute(True)
        self.assertEqual(s.sha(saved),s.SEED)
    def test_seed_remains_exact_and_all443_required(self):
        self.p['seed'].write_bytes(b'changed seed')
        with self.assertRaises(ValueError):self.execute(True)
        self.assertFalse(self.p['out'].exists())


if __name__=='__main__':unittest.main()
