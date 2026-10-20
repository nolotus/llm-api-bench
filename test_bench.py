import json, os, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import bench
from budget import BudgetLedger

CONFIG='providers/lithos-deepseek.json'
MODEL='deepseek-ai/DeepSeek-V4.1-Flash'
class BenchTests(unittest.TestCase):
 def make_plan(self,d,groups=1,throughput=2):
  out=Path(d)/'plan'; bench.main(['plan','--provider',CONFIG,'--budget','15','--groups',str(groups),'--throughput',str(throughput),'--run-id','test','--seed','7','--output',str(out)]); return out
 def args(self,out,d,**kw):
  x=dict(plan=str(out),phase='pilot',ledger=str(Path(d)/'ledger'),budget='15',max_requests=100,ack_unverified_pilot=True,preregistered_revision=None,provider=CONFIG); x.update(kw); return SimpleNamespace(**x)
 def test_four_sizes_groups_caps_fields(self):
  with tempfile.TemporaryDirectory() as d:
   _,rows=bench.verify_plan(self.make_plan(d)); long=[r for r in rows if r['kind']=='long']; self.assertEqual(len(long),20)
   for size in bench.SIZES:
    rs=[r for r in rows if r['kind']=='long' and r['target_tokens']==size]; self.assertEqual(len(rs),5); self.assertEqual([r['repeat_index'] for r in rs],[0,1,2,3,4]); self.assertEqual({r['max_tokens'] for r in rs},{32}); self.assertEqual(len({r['group_id'] for r in rs}),1)
   prefixes=[]
   for size in bench.SIZES:
    rs=[r for r in rows if r['kind']=='long' and r['target_tokens']==size]
    contents=[r['messages'][0]['content'] for r in rs]
    common=contents[0].split('\n\nTask variation ')[0]
    self.assertTrue(all(x.startswith(common) for x in contents)); self.assertEqual(len({x.split('\n\nTask variation ')[1].split(':')[0] for x in contents}),5)
    prefixes.append((size,common))
   self.assertEqual(len({p for _,p in prefixes}),4)
   lens=[len(next(r for r in long if r['target_tokens']==s)['messages'][0]['content'].encode()) for s in bench.SIZES]; self.assertEqual(lens,sorted(lens)); self.assertTrue(all(lens[i]<lens[i+1] for i in range(3)))
   short=[r for r in rows if r['kind']=='throughput']; self.assertEqual(len(short),2); self.assertTrue(all(r['max_tokens']==512 for r in short)); self.assertEqual(len({r['group_id'] for r in short}),2)
 def test_multiple_seeds_keep_each_group_repetition_order(self):
  for seed in (3,19,41):
   with self.subTest(seed=seed),tempfile.TemporaryDirectory() as d:
    p=Path(d)/'plan'; bench.main(['plan','--provider',CONFIG,'--budget','15','--groups','2','--throughput','10','--run-id','ordered','--seed',str(seed),'--bytes-per-token','6.5','--output',str(p)])
    _,rows=bench.verify_plan(p)
    for gid in dict.fromkeys(r['group_id'] for r in rows if r['kind']=='long'):
     self.assertEqual([r['repeat_index'] for r in rows if r['group_id']==gid],[0,1,2,3,4])
    self.assertEqual(sum(r['kind']=='throughput' for r in rows),10)
 def test_manifest_integrity_and_budget_extension(self):
  with tempfile.TemporaryDirectory() as d:
   out=self.make_plan(d); p=out/'manifest.json'; m=json.loads(p.read_text()); m['budget_usd']='999'; p.write_text(json.dumps(m))
   with self.assertRaises(bench.BenchError): bench.verify_plan(out)
 def runmock(self,d,out,response,**kwargs):
  calls=[]
  def fake(*args,**kw):
   calls.append(args[2]['model']); ev={'data':'event'}; kw['on_event'](ev); return response(calls)
  with patch.dict(os.environ,{'LITHOSAI_API_KEY':'secret'}),patch('sys.modules',create=True) if False else patch.dict('sys.modules',{'transport':SimpleNamespace(stream_chat=fake)}):
   bench.run(self.args(out,d,**kwargs))
  return calls
 def test_real_ledger_crash_after_reserve_skips_only_reserved_id(self):
  with tempfile.TemporaryDirectory() as d:
   out=self.make_plan(d,1,1); ledger=Path(d)/'ledger'; m,rows=bench.verify_plan(out); first=rows[0]['request_id']
   with BudgetLedger(ledger,'15') as b: b.reserve(first,'0.01')
   got=[]
   def fake(*args,**kw):
    rid=next(x['request_id'] for x in rows if x['payload']==args[2]); got.append(rid); kw['on_event']({'data':'x'}); return {'status':200,'done':True,'response_model':MODEL,'final_usage':{'prompt_tokens':100,'completion_tokens':2}}
   with patch.dict(os.environ,{'LITHOSAI_API_KEY':'secret'}),patch.dict('sys.modules',{'transport':SimpleNamespace(stream_chat=fake)}): bench.run(self.args(out,d,max_requests=1))
   self.assertEqual(len(got),1); self.assertNotEqual(got[0],first); self.assertEqual(sum(1 for x in ledger.read_text().splitlines() if json.loads(x)['type']=='reserve'),2)
 def test_unknown_usage_hold_and_resume_never_resends_unknown_record(self):
  with tempfile.TemporaryDirectory() as d:
   out=self.make_plan(d,1,1); ledger=Path(d)/'ledger'; calls=[]
   def fake(*args,**kw): calls.append(next(x['request_id'] for x in bench.verify_plan(out)[1] if x['payload']==args[2])); return {'status':200,'done':True,'response_model':MODEL,'final_usage':None}
   with patch.dict(os.environ,{'LITHOSAI_API_KEY':'secret'}),patch.dict('sys.modules',{'transport':SimpleNamespace(stream_chat=fake)}): bench.run(self.args(out,d,max_requests=1))
   with BudgetLedger(ledger,'15') as b: before=b.snapshot()['committed_usd']
   with patch.dict(os.environ,{'LITHOSAI_API_KEY':'secret'}),patch.dict('sys.modules',{'transport':SimpleNamespace(stream_chat=fake)}): bench.run(self.args(out,d,max_requests=1))
   self.assertEqual(len(calls),2); self.assertNotEqual(calls[0],calls[1])
   with BudgetLedger(ledger,'15') as b: self.assertNotEqual(b.snapshot()['committed_usd'],'0'); self.assertNotEqual(before,'0')
   records=[json.loads(x) for x in Path(str(ledger)+'.records.jsonl').read_text().splitlines()]; self.assertTrue(all(r['status']=='unknown_usage' for r in records))
 def test_mock_single_record_events_protocol_secret_and_settle_order(self):
  with tempfile.TemporaryDirectory() as d:
   out=self.make_plan(d,1,1); ledger=Path(d)/'ledger'; seen=[]
   def fake(*args,**kw): kw['on_event']({'data':'raw'}); return {'status':200,'done':True,'response_model':MODEL,'final_usage':{'prompt_tokens':100,'completion_tokens':5}}
   real_settle=BudgetLedger.settle
   def settle(obj,rid,actual):
    lines=Path(str(ledger)+'.records.jsonl').read_text().splitlines(); seen.append((rid,len(lines))); return real_settle(obj,rid,actual)
   with patch.dict(os.environ,{'LITHOSAI_API_KEY':'unique-secret'}),patch('budget.BudgetLedger.settle',settle),patch.dict('sys.modules',{'transport':SimpleNamespace(stream_chat=fake)}): bench.run(self.args(out,d,max_requests=1))
   records=[json.loads(x) for x in Path(str(ledger)+'.records.jsonl').read_text().splitlines()]; events=[json.loads(x) for x in Path(str(ledger)+'.events.jsonl').read_text().splitlines()]
   self.assertEqual(len(records),1); self.assertEqual(len(events),1); self.assertEqual(events[0]['event']['data'],'raw'); self.assertEqual(records[0]['protocol'],'openai-compatible-chat-completions'); self.assertEqual(seen[0][1],1)
   self.assertNotIn('unique-secret',Path(str(ledger)+'.records.jsonl').read_text()+Path(str(ledger)+'.events.jsonl').read_text()+ledger.read_text())
 def test_failure_modes_budget_usage_model_429(self):
  cases=[('budget',{'status':200,'done':True,'response_model':MODEL,'final_usage':{'prompt_tokens':100,'completion_tokens':4}},'0.0000000001'),('input',{'status':200,'done':True,'response_model':MODEL,'final_usage':{'prompt_tokens':999999999,'completion_tokens':1}},'15'),('output',{'status':200,'done':True,'response_model':MODEL,'final_usage':{'prompt_tokens':100,'completion_tokens':999999}},'15'),('model',{'status':200,'done':True,'response_model':'wrong','final_usage':{'prompt_tokens':100,'completion_tokens':1}},'15'),('429',{'status':429,'done':False,'response_model':MODEL,'headers':{'retry-after':'1'},'final_usage':None},'15')]
  for name,response,budget in cases:
   with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
    out=self.make_plan(d,1,1); ledger=Path(d)/'ledger'; calls=[]
    def fake(*args,**kw): calls.append(next(x['request_id'] for x in bench.verify_plan(out)[1] if x['payload']==args[2])); return response
    with patch.dict(os.environ,{'LITHOSAI_API_KEY':'secret'}),patch.dict('sys.modules',{'transport':SimpleNamespace(stream_chat=fake)}): bench.run(self.args(out,d,max_requests=1,budget=budget))
    if name=='budget':
     self.assertFalse(Path(str(ledger)+'.records.jsonl').exists()); self.assertEqual(calls,[]); continue
    records=[json.loads(x) for x in Path(str(ledger)+'.records.jsonl').read_text().splitlines()]; self.assertEqual(len(records),1)
    self.assertEqual(records[0]['protocol'],'openai-compatible-chat-completions'); self.assertEqual(len(calls),1)
    if name in ('input','output'): self.assertEqual(records[0]['status'],'usage_bound_violation')
    if name=='model': self.assertEqual(records[0]['status'],'model_mismatch')
    if name=='429':
     self.assertEqual(records[0]['status'],'rate_limited'); self.assertEqual(records[0]['retry_after'],'1')
     # Resume is blocked until persisted not-before; after expiry later IDs may proceed, never replay ID 1.
     task_ids=[r['request_id'] for r in bench.verify_plan(out)[1]]
     deadline=Path(str(ledger)+'.retry.jsonl')
     import datetime
     entry=json.loads(deadline.read_text().splitlines()[0]); entry['not_before_utc']=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(seconds=1)).isoformat(); deadline.write_text(json.dumps(entry)+'\n')
     with patch.dict(os.environ,{'LITHOSAI_API_KEY':'secret'}),patch.dict('sys.modules',{'transport':SimpleNamespace(stream_chat=fake)}): bench.run(self.args(out,d,max_requests=1,budget='15'))
     self.assertEqual(len(calls),2); self.assertEqual(len(set(calls)),2); self.assertNotEqual(calls[0],calls[1]); self.assertTrue(set(calls).issubset(task_ids))
 def test_unsupported_protocol_no_dispatch(self):
  with tempfile.TemporaryDirectory() as d:
   out=self.make_plan(d); p=out/'manifest.json'; m=json.loads(p.read_text()); m['provider']['api_style']='other'; m.pop('manifest_sha256'); m['manifest_sha256']=__import__('hashlib').sha256(bench.canonical(m)).hexdigest(); p.write_text(json.dumps(m))
   with patch.dict(os.environ,{'LITHOSAI_API_KEY':'secret'}):
    with self.assertRaises(bench.BenchError): bench.run(self.args(out,d,max_requests=1))
if __name__=='__main__': unittest.main()
