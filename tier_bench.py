#!/usr/bin/env python3
"""Preregistered, single-domain tier comparison; stdlib only."""
from __future__ import annotations
import argparse,gzip,hashlib,json,os,random,time
from pathlib import Path
from decimal import Decimal, InvalidOperation
import bench,budget,transport
TIERS=('base','fast','ultra'); SIZES=(1000,4000,16000,32000); CAP='15'; PHASE='comparison_formal'; PROTOCOL='tier-comparison-v1'
DEFAULT={'base':('deepseek-ai/DeepSeek-V4.1-Flash','0.15','0.003','0.6'),'fast':('deepseek-ai/DeepSeek-V4.1-Flash-fast','0.25','0.005','1'),'ultra':('deepseek-ai/DeepSeek-V4.1-Flash-ultra','0.35','0.007','1.4')}
class TierBenchError(RuntimeError): pass
class AuditWriteFailed(TierBenchError): pass
def canonical(x): return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def sha(x): return hashlib.sha256(x).hexdigest()
def fail(msg): raise TierBenchError(msg)
def prices_from_config(c):
 if not isinstance(c,dict) or not all(k in c for k in ('provider','base_url','api_key_env')): fail('config requires provider, base_url, api_key_env')
 if 'tiers' not in c:
  if c['provider']!='Lithos': fail('non-Lithos config must explicitly define tiers')
  c={**c,'tiers':{t:{'model':v[0],'prices_usd_per_million':dict(zip(('input','cached_input','output'),v[1:]))} for t,v in DEFAULT.items()}}
 if not isinstance(c['tiers'],dict) or set(c['tiers'])!=set(TIERS): fail('config tiers must explicitly contain base, fast, ultra')
 for t in TIERS:
  x=c['tiers'][t]
  if not isinstance(x,dict) or not isinstance(x.get('model'),str) or not x['model'] or not isinstance(x.get('prices_usd_per_million'),dict): fail('tier model/prices missing')
  p=x['prices_usd_per_million']
  if set(('input','cached_input','output'))-set(p): fail('all three price fields required')
  for k in ('input','cached_input','output'):
   try: d=Decimal(str(p[k]))
   except InvalidOperation: fail('invalid price')
   if not d.is_finite() or d<0: fail('invalid price')
 return c['tiers']
def default_config(): return {'provider':'Lithos','base_url':'https://api.invalid/v1','api_key_env':'LITHOS_API_KEY','tiers':{t:{'model':v[0],'prices_usd_per_million':dict(zip(('input','cached_input','output'),v[1:]))} for t,v in DEFAULT.items()}}
def cost(t,prompt,cached,out,tiers):
 p=tiers[t]['prices_usd_per_million']; return Decimal(budget.cost_usd(prompt,cached,out,*[str(p[k]) for k in ('input','cached_input','output')]))
def hold(row,tiers): return str(cost(row['tier'],row['input_upper_tokens'],0,row['output_cap_tokens'],tiers))
def permutations(seed):
 p=[('base','fast','ultra'),('base','ultra','fast'),('fast','base','ultra'),('fast','ultra','base'),('ultra','base','fast'),('ultra','fast','base')]; random.Random(seed).shuffle(p); return p
def _content(seed,nonce,byte_target): return bench.sentences(random.Random(seed),nonce,byte_target)
def _make(run,kind,size,g,rep,t,ix,text,cap):
 nonce=sha(f'{run}|{kind}|{size}|{g}|{t}'.encode())[:24]; text=f'Run nonce {nonce}. '+text+f'\\n\\nTask variation {rep}: compare a distinct consequence and state one additional limitation.'
 payload={'model':None,'messages':[{'role':'user','content':text}],'max_tokens':cap,'stream':True}
 return {'request_id':f'{run}-{kind}-{size}-g{g:05d}-{t}-r{rep:02d}','run_id':run,'tier':t,'pair_id':f'{kind}-{size}-g{g:05d}','group_id':f'{kind}-{size}-g{g:05d}-{t}','phase':PHASE,'kind':kind,'target_tokens':size,'repeat_index':rep,'protocol':PROTOCOL,'payload':payload,'input_upper_tokens':len(text.encode('utf8'))+4096,'output_cap_tokens':cap,'nonce':nonce,'schedule_index':ix}
def _ledger_state(l):
 if not l.snapshot().get('healthy') or l.overrun: fail('ledger unhealthy/overrun')
 holds=[k for k,v in l._requests.items() if v.get('status')=='reserved']
 if holds: fail('unsettled ledger holds present')
 return Decimal(l.snapshot()['committed_usd'])
def plan(config,ledger_path,run_id,seed,output,bpt=6.5,revision=None):
 cp=Path(config); cfg=json.loads(cp.read_text()); tiers=prices_from_config(cfg)
 if not isinstance(run_id,str) or not run_id or bpt<=0: fail('invalid run_id/bpt')
 with budget.BudgetLedger(ledger_path,CAP) as l: committed=_ledger_state(l)
 head=Decimal(CAP)-committed-Decimal('1.5')
 if head<=0: fail('no safety-adjusted headroom')
 # Materialize candidate complete six-permutation units once; exact encoded bytes drive each hold.
 sched=permutations(seed); long_specs=[]; short_specs=[]; unit_cost=Decimal(0)
 for size in SIZES:
  per=[]
  for g in range(6):
   order=sched[g]; specs=[]; base_seed=int.from_bytes(hashlib.sha256(f'{seed}:{size}:{g}'.encode()).digest()[:8],'big')
   shared=_content(base_seed,f'pair-{size}-{g}',int(size*bpt))
   for rep in range(5):
    for ix,t in enumerate(order):
     row=_make(run_id,'long',size,g,rep,t,ix,shared,32); row['payload']['model']=tiers[t]['model']; specs.append(row); unit_cost+=Decimal(hold(row,tiers))
   per.extend(specs)
  long_specs.append(per)
 for g in range(6):
  order=sched[g]; shared=_content(seed+g,f'throughput-{g}',int(1000*bpt))
  for ix,t in enumerate(order):
   row=_make(run_id,'throughput',1000,g,0,t,ix,shared,512); row['payload']['model']=tiers[t]['model']; short_specs.append(row); unit_cost+=Decimal(hold(row,tiers))
 if unit_cost<=0: fail('invalid zero plan cost')
 units=int(head//unit_cost)
 if units<1: fail('headroom cannot fund a complete six-permutation unit')
 # Each unit is six balanced groups at every stratum; duplicate group content with distinct group nonce.
 rows=[]
 for u in range(units):
  for size in SIZES:
   for g in range(6):
    order=sched[g]; shared=_content(int.from_bytes(hashlib.sha256(f'{seed}:{size}:{u}:{g}'.encode()).digest()[:8],'big'),f'pair-{size}-{u}-{g}',int(size*bpt))
    for rep in range(5):
     for ix,t in enumerate(order):
      row=_make(run_id,'long',size,u*6+g,rep,t,ix,shared,32); row['payload']['model']=tiers[t]['model']; rows.append(row)
  for g in range(6):
   order=sched[g]; shared=_content(seed+u*6+g,f'throughput-{u}-{g}',int(1000*bpt))
   for ix,t in enumerate(order):
    row=_make(run_id,'throughput',1000,u*6+g,0,t,ix,shared,512); row['payload']['model']=tiers[t]['model']; rows.append(row)
 raw=b''.join(canonical(r)+b'\n' for r in rows)
 out=Path(output); out.mkdir(parents=True,exist_ok=False)
 with open(out/'tasks.jsonl.gz','xb') as f:
  with gzip.GzipFile(fileobj=f,mode='wb',mtime=0) as z:z.write(raw)
 m={'schema':1,'run_id':run_id,'seed':seed,'provider':cfg['provider'],'base_url':cfg['base_url'],'api_key_env':cfg['api_key_env'],'ledger':str(ledger_path),'cap_usd':CAP,'committed_usd':str(committed),'unsettled_holds_usd':'0','headroom_usd':str(head),'prices':tiers,'config_sha256':sha(cp.read_bytes()),'tasks_file':'tasks.jsonl.gz','tasks_sha256':sha(raw),'task_count':len(rows),'planned_upper_usd':str(sum((Decimal(hold(r,tiers)) for r in rows),Decimal(0))),'schedule':sched,'protocol':PROTOCOL,'phase':PHASE,'timing':{'timeout_seconds':120,'inter_request_seconds':2},'bytes_per_token':bpt,'preregistered_revision':revision,'model_alias_notice':'Model IDs are aliases, not immutable weights.','cache_notice':'Cache unknown/null charged conservatively at full input price.'}
 m['manifest_sha256']=sha(canonical(m))
 with open(out/'manifest.json','x') as f: f.write(json.dumps(m,sort_keys=True,indent=2)+'\n'); f.flush(); os.fsync(f.fileno())
 return m
def _validate(mp,config,revision):
 m=json.loads(Path(mp).read_text()); digest=m.pop('manifest_sha256',None)
 if digest!=sha(canonical(m)): fail('manifest hash mismatch')
 m['manifest_sha256']=digest
 if not isinstance(revision,str) or not revision.strip(): fail('preregistered revision required')
 cp=Path(config); cfg=json.loads(cp.read_text()); tiers=prices_from_config(cfg)
 if sha(cp.read_bytes())!=m.get('config_sha256') or tiers!=m.get('prices') or cfg.get('base_url')!=m.get('base_url'): fail('frozen config mismatch')
 if m.get('protocol')!=PROTOCOL or m.get('phase')!=PHASE: fail('unsupported protocol/phase')
 raw=gzip.open(Path(mp).parent/m['tasks_file'],'rb').read()
 if sha(raw)!=m.get('tasks_sha256'): fail('tasks hash mismatch')
 tasks=[json.loads(x) for x in raw.splitlines()]
 if len(tasks)!=m['task_count'] or any(x.get('protocol')!=PROTOCOL or x.get('phase')!=PHASE or x.get('tier') not in TIERS for x in tasks): fail('invalid task groups/protocol')
 if len({x['request_id'] for x in tasks})!=len(tasks): fail('duplicate task id')
 _verify_sampling(tasks,m)
 return m,cfg,tiers,tasks

def _verify_sampling(tasks,m):
 buckets={}
 for row in tasks:
  if row.get('kind') not in ('long','throughput') or row.get('repeat_index') not in range(5): fail('invalid kind/repeat')
  content=row['payload']['messages'][0]['content']; nonce=row.get('nonce')
  expected=sha(f"{m['run_id']}|{row['kind']}|{row['target_tokens']}|{row['group_id'].split('-')[-1]}|{row['tier']}".encode())[:24]
  # group index is the suffix encoded as gNNNNN; parse from pair_id to avoid tier-specific group IDs.
  import re
  match=re.search(r'-g(\d+)(?:-r\d+)?$',row['pair_id'])
  if not match: fail('malformed pair id')
  g=int(match.group(1)); expected=sha(f"{m['run_id']}|{row['kind']}|{row['target_tokens']}|{g}|{row['tier']}".encode())[:24]
  if nonce!=expected or f'Run nonce {nonce}.' not in content: fail('nonce does not match group/tier')
  if row['input_upper_tokens']!=len(content.encode('utf8'))+4096: fail('input upper bound mismatch')
  buckets.setdefault((row['kind'],row['target_tokens'],g),[]).append(row)
 schedules={}
 for (kind,size,g),rs in buckets.items():
  expected=15 if kind=='long' else 3
  if len(rs)!=expected: fail('incomplete sampling block')
  tier_order=[]
  for rep in ([0] if kind=='throughput' else range(5)):
   matching=[r for r in rs if r['repeat_index']==rep]
   if len(matching)!=3 or {r['tier'] for r in matching}!=set(TIERS): fail('tier/repeat block incomplete')
   tier_order.append(tuple(r['tier'] for r in sorted(matching,key=lambda x:x['schedule_index'])))
  if len(set(tier_order))!=1: fail('repeat tier order changes within block')
  schedules.setdefault((kind,size),[]).append((g,tier_order[0]))
  # For each repeat all bodies match after removing unequal nonce prefix and repeat question.
  bodies=[]
  for r in rs:
   c=r['payload']['messages'][0]['content']; c=c.replace(f"Run nonce {r['nonce']}. ",'',1).split('\\n\\nTask variation ',1)[0]; bodies.append(c)
  if len(set(bodies))!=1: fail('matched shared corpus differs')
 for key,vals in schedules.items():
  vals.sort(); orders=[v for _,v in vals]
  if len(orders)<6 or len(orders)%6: fail(f'incomplete six-permutation schedule: {key}')
  # Candidate tasks can be a single block in mocked-run tests; full plan is strictly balanced.
  if len(orders)>=6:
   for start in range(0,len(orders),6):
    chunk=orders[start:start+6]
    if len(chunk)!=6 or set(chunk)!={tuple(p) for p in m['schedule']}: fail(f'unbalanced six-permutation schedule: {key}')
 return True

def _request_order(tasks):
 # Block-major order; per block each repeat dispatches exactly the scheduled tier triplet.
 grouped={}
 for r in tasks: grouped.setdefault((r['kind'],r['target_tokens'],r['pair_id']),[]).append(r)
 ordered=[]
 for key in sorted(grouped):
  rows=grouped[key]
  ordered.extend(sorted(rows,key=lambda x:(x['repeat_index'],x['schedule_index'])))
 return ordered
def _append(path,obj):
 with open(path,'a',encoding='utf8') as f:f.write(json.dumps(obj,sort_keys=True,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
def run(manifest_path,config_path,revision,api_key=None,mock_transport=None,sleep=time.sleep):
 # All static verification precedes credential lookup and any transport call.
 m,cfg,tiers,tasks=_validate(manifest_path,config_path,revision)
 m['runtime_preregistered_revision']=revision
 key=api_key or os.environ.get(m['api_key_env'])
 if not key: fail('API key unavailable')
 root=Path(manifest_path).parent/'records'; root.mkdir(exist_ok=True)
 recpath=root/'records.jsonl'; evpath=root/'events.jsonl'; notbefore=root/'not-before.json'
 sent=0; failures=0
 if recpath.exists():
  try:
   records=[json.loads(x) for x in recpath.read_text().splitlines()]
   if any(not isinstance(x,dict) or not isinstance(x.get('request_id'),str) for x in records): fail('record journal malformed')
  except Exception: fail('record journal malformed')
 else: records=[]
 done={x['request_id'] for x in records}
 if len(done)!=len(records): fail('duplicate request_id in records journal')
 if notbefore.exists(): fail('persistent rate-limit cooldown present; manual review required')
 with budget.BudgetLedger(m['ledger'],CAP) as led:
  if not led.snapshot().get('healthy') or led.overrun: fail('ledger unhealthy')
  # Records are only an audit trail; all IDs must be traceable to a ledger reservation.
  ledger_ids=set(led._requests)
  if done-ledger_ids: fail('record journal contains IDs absent from trusted ledger')
  # Any unresolved reservation from this task set is ambiguous; stop rather than advancing past it.
  unresolved=[t['request_id'] for t in tasks if t['request_id'] in led._requests and led._requests[t['request_id']].get('status')=='reserved']
  if unresolved: fail('unresolved request reservation; manual reconciliation required')
  # A reservation is authoritative for at-most-once delivery, irrespective of record presence.
  for task in _request_order(tasks):
   rid=task['request_id']
   if rid in led._requests: continue
   upper=hold(task,tiers)
   if not led.reserve(rid,upper): break # hard cap: no transport call
   rec={k:task[k] for k in ('request_id','run_id','tier','pair_id','group_id','phase','kind','target_tokens','repeat_index','protocol')}; rec.update(request=task['payload'],runtime_preregistered_revision=revision)
   tr={}; code=None; actual=None; basis='unknown'; status='unknown'
   try:
    audit=[True]
    def cb(ev):
     try: _append(evpath,{'request_id':rid,'event':ev})
     except Exception: audit[0]=False; raise AuditWriteFailed('event audit write failed') from None
     return True
    sender=mock_transport or (lambda payload,secret,on_event: transport.stream_chat(m['base_url'],secret,payload,timeout_s=120,on_event=on_event))
    tr=sender(task['payload'],key,cb); sent+=1
    if not isinstance(tr,dict): raise TierBenchError('invalid transport record')
    code=tr.get('status'); status='complete' if tr.get('done') else 'transport_error'
    model=tr.get('response_model')
    if model is not None and model!=task['payload']['model']: status='model_mismatch'
    if isinstance(code,int) and not isinstance(code,bool) and code>=400: status='http_error'
    if code in (401,402,404,429): status='http_stop'
    usage=tr.get('final_usage')
    if status=='complete':
     if not isinstance(usage,dict): status='unknown_usage'
     else:
      p=usage.get('prompt_tokens'); o=usage.get('completion_tokens'); c=usage.get('cached_tokens')
      valid=lambda n:isinstance(n,int) and not isinstance(n,bool) and n>=0
      if not valid(p) or not valid(o) or (c is not None and not valid(c)) or (c is not None and c>p): status='invalid_usage'
      elif p+4096>task['input_upper_tokens'] or o>task['output_cap_tokens']: status='usage_bound_violation'
      else:
       actual=str(cost(task['tier'],p,c or 0,o,tiers)); basis='reported_cache' if c is not None else 'cache_unknown_full_input_price'
       if Decimal(actual)>Decimal(upper): status='usage_over_cap'
    if not audit[0]: status='audit_callback_failure'
    rec.update(transport=tr,accounting={'reserved_usd':upper,'computed_usd':actual if status=='complete' else None,'basis':basis if status=='complete' else status},status=status)
    _append(recpath,rec) # durable terminal record before any settlement
    done.add(rid)
    if status=='complete': led.settle(rid,actual)
   except Exception as exc:
    # Do not serialize exception text; failed persistence is fatal and preserves the reservation.
    if isinstance(exc,AuditWriteFailed): raise
    rec.update(transport=tr,accounting={'reserved_usd':upper,'computed_usd':None,'basis':'unknown_hold'},status='execution_exception',error_type=type(exc).__name__)
    try: _append(recpath,rec)
    except Exception: raise TierBenchError('record persistence failed; reservation retained') from None
    break
   if code==429:
    _append(notbefore,{'request_id':rid,'retry_after':(tr.get('headers') or {}).get('retry-after'),'status':'429'}); break
   if code in (401,402,404) or status in ('model_mismatch','invalid_usage','usage_bound_violation','usage_over_cap','audit_callback_failure'): break
   if status!='complete': failures+=1
   else: failures=0
   if failures>=3: break
   if not led.snapshot().get('healthy') or led.overrun: fail('ledger unhealthy/over cap')
   sleep(2)
 return sent

def main(argv=None):
 p=argparse.ArgumentParser(); s=p.add_subparsers(dest='cmd',required=True)
 a=s.add_parser('plan');a.add_argument('--config',required=True);a.add_argument('--ledger',default='results/lithos-budget.jsonl');a.add_argument('--run-id',required=True);a.add_argument('--seed',type=int,required=True);a.add_argument('--output',required=True);a.add_argument('--bpt',type=float,default=6.5);a.add_argument('--preregistered-revision',required=True)
 b=s.add_parser('run');b.add_argument('--manifest',required=True);b.add_argument('--config',required=True);b.add_argument('--preregistered-revision',required=True)
 x=p.parse_args(argv)
 try:
  if x.cmd=='plan':
   m=plan(x.config,x.ledger,x.run_id,x.seed,x.output,x.bpt,x.preregistered_revision); print(json.dumps(m,indent=2))
  else: print('sent',run(x.manifest,x.config,x.preregistered_revision))
 except Exception as e:p.error(f'{type(e).__name__}: {type(e).__name__ if not isinstance(e,TierBenchError) else str(e)}')
if __name__=='__main__':main()
