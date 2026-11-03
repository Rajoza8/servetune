"""Invented safe projection/cleanup objects only; no study or provider access."""
from copy import deepcopy
import unittest
import render_inference_readme as r


def fixture():
    cases=[]
    for n,i in enumerate(r.IDS):
        for arm in r.ARMS:cases.append({'id':i,'arm':arm,'valid':n<14,'compound':n<4,'has_decoy':n%2==0,
            'diagnosis_correct':False,'complete_fix':False,'harmful':False,'stopped_decoy':False})
    fields=('detected','false_alarms','diagnosis_correct','fix_proposed','complete_fix','compound_complete_fix','harmful',
        'stopped_decoy','invalid_outputs','call_failures','median_time_to_detect_s','api_calls','api_cost_usd')
    board={arm:{k:0 for k in fields} for arm in r.ARMS}
    projection={'label':r.LABEL,'freeze_sha256':r.FREEZE,'decision_coverage':{'expected':90,'present':90},'per_case':cases,
        'valid_cases':14,'invalid_cases':1,'scoreboards':{'all':board,'valid_only':deepcopy(board)},
        'denominators':{'all':{'cases':15,'healthy_controls':3,'nonhealthy_cases':12,'compound_cases':4,'decoy_cases':8},
            'valid_only':{'cases':14,'healthy_controls':2,'nonhealthy_cases':12,'compound_cases':4,'decoy_cases':7}}}
    cleanup={'confirmed_absent':True,'stopped_confirmed':True,'owned_work_quiescent':True,'canonical_ledger_sha256':'f'*64,
        'gpu_accounting':{'total_usd_upper':40,'inference_host_cost':{'running_hours':1.5}},
        'ledger_summary':{'caps_usd':{'meta':50.,'baseten':20.},'warnings':[],'accounted_usd':{'meta':15.,'baseten':0.},'calls':600}}
    protocol={'source_commit':r.SOURCE,'label':r.LABEL,'excluded_ids':['hard-16'],'scientific_inputs_changed':False}
    hardware={'gpu_uuid':'GPU-invented','vllm_version':'invented'}
    progress={'gpu':'GPU-invented, invented96GB, 97887, 610.43.02','vllm_version':'invented'}
    prior={'gpu_accounting':{'hard_running_hours':3.8}};v0={'cost':{'running_hours':14.3}}
    failures={'finalized':True,'label':r.LABEL}
    evaluation={'completed':True,'groups':['rules-spark-wonder','glimmer-cascades'],'failure':None,'cleanup_errors':[],
        'finished_at_utc':'2026-11-03T04:00:00+00:00'}
    optional={'status':'not-run-budget-below-5'}
    return ['',projection,cleanup,protocol,hardware,progress,prior,v0,failures,evaluation,optional]


class RenderContracts(unittest.TestCase):
    def test_completed_native_tables_and90_cells(self):
        v=r.render(*fixture());self.assertEqual(v['VALID_CASES'],14)
        self.assertEqual(v['ALL_SCOREBOARD'].count('| rules |'),1)
        self.assertEqual(v['VALID_SCOREBOARD'].count('| rules |'),1)
        self.assertEqual(v['PER_CASE_DFHX_TABLE'].count('0/0/0/0'),90)
        self.assertIn('19.600000',v['FINAL_GPU_ACCOUNTING_AND_CLEANUP'])
    def test_unfinished_cleanup_refuses(self):
        f=fixture();f[2]['confirmed_absent']=False
        with self.assertRaises(ValueError):r.render(*f)
    def test_gpu_cap43_remains_hard(self):
        f=fixture();f[2]['gpu_accounting']['total_usd_upper']=43.01
        with self.assertRaises(ValueError):r.render(*f)
    def test_missing_arm_case_refuses(self):
        f=fixture();f[1]['per_case'].pop()
        with self.assertRaises(ValueError):r.render(*f)
    def test_late_analysis_refuses(self):
        f=fixture();f[9]['finished_at_utc']='2026-11-03T23:00:01+00:00'
        with self.assertRaises(ValueError):r.render(*f)


if __name__=='__main__':unittest.main()
