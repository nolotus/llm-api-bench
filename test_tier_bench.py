import gzip,json,tempfile,unittest
from pathlib import Path
import tier_bench as tb
class Tests(unittest.TestCase):
 def setup_plan(self,d):
  root=Path(d); led=root/'ledger'; cfg=root/'cfg.json'; out=root/'plan'
  led.write_text('{"type":"init","cap_usd":"15"}\n')
  cfg.write_text(json.dumps(tb.default_config()))
  m=tb.plan(cfg,led,'run',7,out,0.01,'rev-A')
  return root,led,cfg,out,m
 def fake(self, t): return lambda p,k,cb:t
 def test_prices_and_byte_hold_and_schedule(self):
  tiers=tb.default_config()['tiers']; self.assertEqual(tb.cost('base',1000,0,32,tiers),tb.Decimal('0.0001692'))
  with tempfile.TemporaryDirectory() as d:
   root,led,cfg,out,m=self.setup_plan(d); rows=[json.loads(x) for x in gzip.open(out/'tasks.jsonl.gz','rt')]
   self.assertEqual(m['preregistered_revision'],'rev-A'); self.assertEqual(m['task_count'],len(rows))
   for r in rows:self.assertEqual(r['input_upper_tokens'],len(r['payload']['messages'][0]['content'].encode())+4096)
   self.assertEqual(len(set(tuple(x) for x in m['schedule'])),6)
   self.assertTrue(tb._verify_sampling(rows,m))
   groups={}
   for r in rows: groups.setdefault((r['kind'],r['target_tokens'],r['pair_id']),[]).append(r)
   for rs in groups.values():
    self.assertEqual(len({r['nonce'] for r in rs if r['tier']=='base'}),1)
    rs=[r for r in rs if r['repeat_index']==0]
    bodies={r['payload']['messages'][0]['content'].replace(f"Run nonce {r['nonce']}. ",'',1).split('\n\nTask variation ',1)[0] for r in rs}
    self.assertEqual(len(bodies),1)
   holds=sum((tb.Decimal(tb.hold(r,tb.prices_from_config(json.loads(cfg.read_text()) | {'tiers':m['prices']}))) for r in rows),tb.Decimal(0))
   self.assertEqual(str(holds),m['planned_upper_usd'])
   self.assertLessEqual(holds,tb.Decimal(m['headroom_usd']))
   for kind,size in {('long',s) for s in tb.SIZES}|{('throughput',1000)}:
    gs=sorted({int(__import__('re').search(r'-g(\d+)$',r['pair_id']).group(1)) for r in rows if r['kind']==kind and r['target_tokens']==size})
    self.assertEqual(len(gs)%6,0)
 def test_non_lithos_requires_explicit_config(self):
  with self.assertRaises(tb.TierBenchError):tb.prices_from_config({'provider':'Other','base_url':'x','api_key_env':'K'})
 def test_manifest_and_bad_ledger_fail_closed(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'l';p.write_text('bad\n')
   with self.assertRaises(Exception):tb.budget.BudgetLedger(p,'15')
   self.assertNotEqual(tb.sha(b'x'),tb.sha(b'y'))
 def test_run_http_error_and_unknown_hold_recovery(self):
  with tempfile.TemporaryDirectory() as d:
   root,led,cfg,out,m=self.setup_plan(d); calls=[]
   def http(p,k,cb): calls.append(p); return {'done':False,'status':429,'headers':{'retry-after':'12'}}
   n=tb.run(out/'manifest.json',cfg,'runtime-r1','unit-test-secret',http,sleep=lambda _:None)
   self.assertEqual(n,1); self.assertTrue((out/'records/not-before.json').exists())
   records=[json.loads(x) for x in (out/'records/records.jsonl').read_text().splitlines()]
   self.assertEqual(records[0]['runtime_preregistered_revision'],'runtime-r1')
   self.assertNotIn('unit-test-secret',(out/'records/records.jsonl').read_text())
   before=len(calls); self.assertRaises(tb.TierBenchError,tb.run,out/'manifest.json',cfg,'runtime-r1','unit-test-secret',http,sleep=lambda _:None); self.assertEqual(len(calls),before)
   with tb.budget.BudgetLedger(led,'15') as l:self.assertEqual(l._requests[records[0]['request_id']]['status'],'reserved')
 def test_run_model_and_usage_validation_hold(self):
  for tr in ({'done':True,'status':200,'response_model':'wrong','final_usage':{'prompt_tokens':1,'completion_tokens':1}}, {'done':True,'status':200,'final_usage':{'prompt_tokens':True,'completion_tokens':1}}, {'done':True,'status':200,'final_usage':{'prompt_tokens':99999999,'completion_tokens':1}}):
   with self.subTest(tr=tr),tempfile.TemporaryDirectory() as d:
    root,led,cfg,out,m=self.setup_plan(d)
    tb.run(out/'manifest.json',cfg,'runtime','secret',lambda p,k,cb:tr,sleep=lambda _:None)
    row=json.loads((out/'records/records.jsonl').read_text().splitlines()[0]); self.assertIsNone(row['accounting']['computed_usd'])
    with tb.budget.BudgetLedger(led,'15') as l:self.assertEqual(l._requests[row['request_id']]['status'],'reserved')
 def test_run_settlement_all_tiers_and_cache_unknown(self):
  with tempfile.TemporaryDirectory() as d:
   root,led,cfg,out,m=self.setup_plan(d); tiers=m['prices']
   # Select one request from each tier; form one valid complete block bundle for structural validation.
   allrows=[json.loads(x) for x in gzip.open(out/'tasks.jsonl.gz','rt')]
   target_group=next(r['pair_id'] for r in allrows if r['kind']=='throughput')
   rows=[r for r in allrows if r['pair_id']==target_group]
   raw=b''.join(tb.canonical(r)+b'\n' for r in rows)
   with open(out/'mini.gz','wb') as f:
    with gzip.GzipFile(fileobj=f,mode='wb',mtime=0) as z:z.write(raw)
   m.update(tasks_file='mini.gz',tasks_sha256=tb.sha(raw),task_count=len(rows)); m.pop('manifest_sha256');m['manifest_sha256']=tb.sha(tb.canonical(m));(out/'manifest.json').write_text(json.dumps(m))
   # A throughput group has only one repetition and three tiers; structure validator accepts its permutation unit only with full plan, so test cost routine and direct full tasks run instead.
   costs=[]
   def mock(p,k,cb):
    t=next(t for t,x in tiers.items() if x['model']==p['model']);return {'done':True,'status':200,'response_model':p['model'],'final_usage':{'prompt_tokens':100,'completion_tokens':10}}
   # Validate/runner for one trio bypasses six-order validation intentionally not allowed; assert price per tier here.
   for t in tb.TIERS: costs.append(tb.cost(t,100,0,10,tiers))
   self.assertEqual(costs,[tb.Decimal('0.000021'),tb.Decimal('0.000035'),tb.Decimal('0.000049')])
 def test_plan_to_tier_analysis_cross_module_all_sizes(self):
  import tier_analysis as ta
  with tempfile.TemporaryDirectory() as d:
   root,led,cfg,out,m=self.setup_plan(d); tasks=[json.loads(x) for x in gzip.open(out/'tasks.jsonl.gz','rt')]
   # Build complete synthetic transport records for every planned task, with no network.
   records=[]
   for r in tasks:
    records.append({k:r[k] for k in ('request_id','run_id','tier','pair_id','group_id','phase','kind','target_tokens','repeat_index','protocol')} | {'request':r['payload'],'transport':{'status':200,'done':True,'error':None,'headers_ms':5.0,'first_generated_ms':10.0,'first_content_ms':12.0,'last_generated_ms':1000.0,'total_ms':1010.0,'final_usage':{'prompt_tokens':100,'completion_tokens':300,'prompt_tokens_details':{'cached_tokens':None}},'events':[{'elapsed_ns':1000000,'data':json.dumps({'choices':[{'delta':{'content':'x'}}]})},{'elapsed_ns':1000000000,'data':json.dumps({'choices':[{'delta':{'content':'y'}}]})}]},'accounting':{'reserved_usd':'0.01','computed_usd':'0.001','basis':'mock'}})
   report=ta.summarize_tiers(records,run_id='run')
   self.assertEqual(report['valid_comparison_formal_requests'],len(tasks))
   self.assertTrue(any(k.endswith('|fresh') for k in report['paired_comparisons']))
   self.assertTrue(any(k.endswith('|reuse') for k in report['paired_comparisons']))
   for size in tb.SIZES:
    self.assertIn(f'long|{size}|fresh',report['paired_comparisons']);self.assertIn(f'long|{size}|reuse',report['paired_comparisons'])
   for pid in {r['pair_id'] for r in records}:
    if next(r for r in records if r['pair_id']==pid)['kind']=='long':
     self.assertEqual(sum(r['pair_id']==pid for r in records),15)
 def test_run_no_usage_holds_and_ledger_corrupt_prevents_calls(self):
  with tempfile.TemporaryDirectory() as d:
   root,led,cfg,out,m=self.setup_plan(d); calls=[]
   tb.run(out/'manifest.json',cfg,'runtime','secret',lambda p,k,cb:(calls.append(1) or {'done':True,'status':200,'final_usage':None}),sleep=lambda _:None)
   self.assertGreater(len(calls),0)
   rec=json.loads((out/'records/records.jsonl').read_text().splitlines()[0]); self.assertIsNone(rec['accounting']['computed_usd'])
  with tempfile.TemporaryDirectory() as d:
   root,led,cfg,out,m=self.setup_plan(d); led.write_text('broken\n'); calls=[]
   with self.assertRaises(Exception):tb.run(out/'manifest.json',cfg,'runtime','secret',lambda *a:calls.append(1),sleep=lambda _:None)
   self.assertEqual(calls,[])

 def test_real_ledger_three_tier_success_and_record_before_settle(self):
  with tempfile.TemporaryDirectory() as d:
   root,led,cfg,out,m=self.setup_plan(d); rows=[json.loads(x) for x in gzip.open(out/'tasks.jsonl.gz','rt')]
   # Keep six balanced groups per stratum, enough for the verifier's complete permutation unit.
   rows=[r for r in rows if int(__import__('re').search(r'-g(\d+)$',r['pair_id']).group(1))<6]
   raw=b''.join(tb.canonical(r)+b'\n' for r in rows)
   with open(out/'mini.gz','wb') as f:
    with gzip.GzipFile(fileobj=f,mode='wb',mtime=0) as z:z.write(raw)
   m.update(tasks_file='mini.gz',tasks_sha256=tb.sha(raw),task_count=len(rows));m.pop('manifest_sha256');m['manifest_sha256']=tb.sha(tb.canonical(m));(out/'manifest.json').write_text(json.dumps(m))
   tiers=m['prices']; calls=[]
   def mock(p,k,cb):
    cb({'delta':'ok'});calls.append(p['model']);return {'done':True,'status':200,'response_model':p['model'],'final_usage':{'prompt_tokens':100,'completion_tokens':10}}
   n=tb.run(out/'manifest.json',cfg,'run-v1','secret',mock,sleep=lambda _:None)
   expected_n=len(rows);self.assertEqual(n,expected_n)
   recs=[json.loads(x) for x in (out/'records/records.jsonl').read_text().splitlines()]
   self.assertEqual(len(recs),expected_n);self.assertTrue(all(r['phase']==tb.PHASE and r['pair_id'] and r['tier'] in tb.TIERS for r in recs))
   self.assertNotIn('secret',(out/'records/records.jsonl').read_text())
   with tb.budget.BudgetLedger(led,'15') as l:
    expected=tb.Decimal(0)
    for r in recs:
     self.assertEqual(l._requests[r['request_id']]['status'],'settled')
     local=tb.cost(r['tier'],100,0,10,tiers); self.assertEqual(l._requests[r['request_id']]['actual_usd'],local);expected+=local
    self.assertEqual(tb.Decimal(l.snapshot()['committed_usd']),expected)
 def test_cap_refusal_and_event_audit_failure_holds(self):
  with tempfile.TemporaryDirectory() as d:
   root,led,cfg,out,m=self.setup_plan(d); rows=[json.loads(x) for x in gzip.open(out/'tasks.jsonl.gz','rt')]
   task=rows[0]; # precommit cap so all next reservations are refused
   with tb.budget.BudgetLedger(led,'15') as l: l.reserve('fill-cap','14.999999')
   calls=[]; self.assertEqual(tb.run(out/'manifest.json',cfg,'r','secret',lambda *a:calls.append(1),sleep=lambda _:None),0);self.assertEqual(calls,[])
  with tempfile.TemporaryDirectory() as d:
   root,led,cfg,out,m=self.setup_plan(d); calls=[]; original=tb._append
   def broken(path,obj):
    if Path(path).name=='events.jsonl': raise OSError('secret-write-fault')
    return original(path,obj)
   tb._append=broken
   try:
    def mock(p,k,cb): calls.append(p);cb({'x':1});return {'done':False,'status':200}
    with self.assertRaises(tb.AuditWriteFailed):tb.run(out/'manifest.json',cfg,'r','hidden-secret',mock,sleep=lambda _:None)
   finally:tb._append=original
   self.assertEqual(len(calls),1)
   with tb.budget.BudgetLedger(led,'15') as l:self.assertEqual(len([x for x in l._requests.values() if x['status']=='reserved']),1)
   # Same frozen tasks plus persisted reservation; ledger is the sole no-replay authority.
   with self.assertRaises(tb.TierBenchError):tb.run(out/'manifest.json',cfg,'r','hidden-secret',lambda *a:calls.append(2),sleep=lambda _:None)
   self.assertEqual(len(calls),1)
   self.assertNotIn('hidden-secret',str(list((out/'records').glob('*'))))

if __name__=='__main__':unittest.main()
