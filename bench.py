#!/usr/bin/env python3
"""Frozen synthetic benchmark planner and explicit single-concurrency runner."""
from __future__ import annotations
import argparse, hashlib, json, os, random, sys, time, datetime, email.utils
from pathlib import Path
from decimal import Decimal, InvalidOperation

SIZES=(1000,4000,16000,32000)
class BenchError(Exception): pass

def canonical(x): return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def digest_tasks(rows): return hashlib.sha256(b'\n'.join(canonical(x) for x in rows)).hexdigest()
def fsappend(path, obj):
    with open(path,'a',encoding='utf-8') as f: f.write(json.dumps(obj,ensure_ascii=False,sort_keys=True)+'\n'); f.flush(); os.fsync(f.fileno())
def sentences(rng, nonce, target_bytes):
    words=['careful observation','small green valley','distant morning light','quiet river crossing','patient craft worker','unexpected weather change','bright wooden window','old market square','gentle mechanical rhythm','useful shared discovery']
    chunks=[f'Run nonce {nonce}. ']
    while len(''.join(chunks).encode())<target_bytes:
        chunks.append(f'{rng.choice(words)} {rng.choice(("continues","appears","moves","changes","matters"))} near {rng.choice(words)}; ')
    text=''.join(chunks)
    # Natural sentence boundary truncation; leave intact final sentence.
    sentences=text.split('; '); out=''
    for sentence in sentences:
        candidate=out+sentence+('; ' if sentence else '')
        if len(candidate.encode())>target_bytes and out: break
        out=candidate
    return out.rstrip()
def load_config(p):
    c=json.loads(Path(p).read_text(encoding='utf-8'))
    for k in ('provider','base_url','model','model_status','prices_usd_per_million','api_key_env'):
        if k not in c: raise BenchError('provider config missing required fields')
    c['_source_sha256']=hashlib.sha256(Path(p).read_bytes()).hexdigest()
    c['_source_path']=str(Path(p).resolve())
    return c
def money(v):
    try: d=Decimal(str(v))
    except (InvalidOperation,ValueError): raise BenchError('invalid decimal budget')
    if not d.is_finite() or d<0: raise BenchError('budget must be finite and nonnegative')
    return d
def token_price(c,key): return money(c['prices_usd_per_million'][key])
def cost(prompt,output,c): return (Decimal(prompt)*token_price(c,'input')+Decimal(output)*token_price(c,'output'))/Decimal(1000000)
def create_task(run_id,group_id,kind,target,cap,repeat,prefix):
    suffix=f'\n\nTask variation {repeat}: compare a distinct consequence and state one additional limitation.'
    text=prefix+suffix+'\n\nAnalyze this scenario and provide a structured evidence-based answer. State assumptions, alternatives, and limitations.'
    return {'request_id':f'{group_id}-{kind}-r{repeat:02d}','group_id':group_id,'kind':kind,'latency':None,'target_tokens':target,'repeat_index':repeat,'messages':[{'role':'user','content':text}],'max_tokens':cap,'payload':{'model':None,'messages':[{'role':'user','content':text}],'max_tokens':cap,'stream':True}}
def plan(a):
    c=load_config(a.provider); budget=money(a.budget); bpt=a.bytes_per_token
    if not isinstance(bpt,(int,float)) or isinstance(bpt,bool) or not Decimal(str(bpt)).is_finite() or bpt<=0 or a.groups<1 or a.throughput<1: raise BenchError('groups, throughput and bytes-per-token must be positive')
    bpt_decimal=Decimal(str(bpt))
    rng=random.Random(a.seed); wanted_groups=a.groups; wanted_short=a.throughput
    def materialize(g,t):
        by_group={}
        for size in SIZES:
            for gi in range(g):
                gid=f'{a.run_id}-{size}-g{gi:05d}'
                target_bytes=int(Decimal(size)*bpt_decimal)
                prefix=sentences(rng,gid,target_bytes)
                by_group[gid]=[create_task(a.run_id,gid,'long',size,32,rep,prefix) for rep in range(5)]
        for i in range(t):
            gid=f'{a.run_id}-throughput-{i:05d}'; prefix=sentences(rng,gid,int(Decimal(1000)*bpt_decimal))
            by_group[gid]=[create_task(a.run_id,gid,'throughput',1000,512,0,prefix)]
        for row in (r for group in by_group.values() for r in group): row['payload']['model']=c['model']
        group_ids=list(by_group); rng.shuffle(group_ids)
        rows=[]
        for gid in group_ids: rows.extend(by_group[gid])
        return rows
    # Enumerate decreasing allocations using exact materialized payload byte lengths.
    groups=wanted_groups; throughput=min(wanted_short,groups*5); rows=None
    while groups>=1:
        throughput=min(wanted_short,groups*5)
        trial=materialize(groups,throughput)
        total=Decimal(0)
        for row in trial:
            prompt=sum(len(m['content'].encode('utf-8')) for m in row['messages'])+4096
            total+=cost(prompt,row['max_tokens'],c)
        if total<=budget*Decimal('0.90'): rows=trial; break
        groups-=1
    if rows is None: raise BenchError('budget cannot fund minimum plan with 10% reserve')
    # Per request reservation input is raw UTF-8 bytes + fixed 4096 token envelope.
    for row in rows:
        row['input_upper_tokens']=sum(len(m['content'].encode('utf-8')) for m in row['messages'])+4096
    tasks_hash=digest_tasks(rows)
    manifest={'schema':2,'run_id':a.run_id,'seed':a.seed,'provider':c,'config_sha256':c['_source_sha256'],'budget_usd':str(budget),'bytes_per_token':bpt,'estimate_note':'UTF-8 corpus targets use bytes_per_token as approximate generation sizing; reservation uses complete prompt UTF-8 byte count plus 4096 tokens under the stated byte-level tokenizer assumption. Pilot upper-bound violation stops. max_tokens includes reasoning only when config verification says so.','groups_per_size':groups,'throughput_requests':throughput,'task_count':len(rows),'tasks_file':'tasks.jsonl','tasks_sha256':tasks_hash,'planned_upper_usd':str(total),'preregistered_revision':a.preregistered_revision}
    out=Path(a.output)
    if out.exists(): raise BenchError(f'output already exists: {out}')
    out.mkdir(parents=True)
    with (out/'tasks.jsonl').open('x',encoding='utf-8') as f:
        for row in rows: f.write(json.dumps(row,sort_keys=True,ensure_ascii=False)+'\n')
        f.flush(); os.fsync(f.fileno())
    manifest['manifest_sha256']=hashlib.sha256(canonical(manifest)).hexdigest()
    fd=os.open(out/'manifest.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as f: f.write(json.dumps(manifest,sort_keys=True,indent=2)+'\n'); f.flush(); os.fsync(f.fileno())
def verify_plan(directory):
    d=Path(directory); m=json.loads((d/'manifest.json').read_text()); claimed=m.pop('manifest_sha256',None)
    if claimed!=hashlib.sha256(canonical(m)).hexdigest(): raise BenchError('manifest integrity mismatch')
    m['manifest_sha256']=claimed
    rows=[json.loads(x) for x in (d/m['tasks_file']).read_text().splitlines() if x]
    if len(rows)!=m['task_count'] or digest_tasks(rows)!=m['tasks_sha256']: raise BenchError('task integrity mismatch')
    cfg=m['provider']; source=Path(cfg.get('_source_path',''))
    return m,rows
def request_lock_path(ledger): return Path(str(ledger)+'.lockids.jsonl')
def run(a):
    from budget import BudgetLedger,cost_usd
    m,tasks=verify_plan(a.plan); phase=a.phase; budget=money(a.budget)
    if budget>money(m['budget_usd']): raise BenchError('run budget cannot exceed frozen plan budget')
    cfg=m['provider']
    if cfg['model_status']!='verified' and (phase!='pilot' or not a.ack_unverified_pilot): raise BenchError('unverified model is pilot-only and requires acknowledgement')
    if phase=='formal' and (cfg.get('model_status')!='verified' or not cfg.get('reasoning_cap_verified') or not a.preregistered_revision): raise BenchError('formal requires verified model/reasoning cap and preregistered revision')
    if a.max_requests<1: raise BenchError('max-requests must be positive')
    protocol=cfg.get('api_style')
    if protocol!='openai-compatible-chat-completions': raise BenchError(f'unsupported protocol: {protocol}')
    try:
        from transport import stream_chat as adapter
    except ImportError as e: raise BenchError('transport module unavailable; no request attempted') from e
    stream_chat=adapter
    key=os.environ.get(cfg['api_key_env'])
    if not key: raise BenchError('credential environment variable is not set')
    # Verify config file contents are unchanged against the frozen snapshot when source path recorded.
    config_path=Path(a.provider) if a.provider else None
    if config_path and hashlib.sha256(config_path.read_bytes()).hexdigest()!=m['config_sha256']: raise BenchError('provider config changed since plan')
    ledger_path=Path(a.ledger); records=Path(str(ledger_path)+'.records.jsonl'); events=Path(str(ledger_path)+'.events.jsonl'); ids=request_lock_path(ledger_path)
    seen=set(); terminal=set()
    if records.exists():
        for line in records.read_text().splitlines():
            try:
                record=json.loads(line); rid=record['request_id']; seen.add(rid)
                if record.get('status') in ('rate_limited','model_mismatch','http_stop','usage_bound_violation'): terminal.add(rid)
            except Exception: raise BenchError('corrupt records journal')
    reserved=set()
    if ids.exists():
        for line in ids.read_text().splitlines():
            try:
                rid=json.loads(line)['request_id']; seen.add(rid); reserved.add(rid)
            except Exception: raise BenchError('corrupt request journal')
    # Replay actual BudgetLedger journal. Its reserve rows use request_id and upper_usd.
    if ledger_path.exists():
        raw=ledger_path.read_bytes()
        if raw and not raw.endswith(b'\n'): raise BenchError('incomplete budget journal tail')
        for number,line in enumerate(raw.splitlines(),1):
            try:
                rec=json.loads(line)
                if rec.get('type')=='reserve':
                    rid=rec.get('request_id')
                    if not isinstance(rid,str) or not rid: raise ValueError('invalid request_id')
                    reserved.add(rid)
            except (ValueError,TypeError,json.JSONDecodeError) as e: raise BenchError(f'corrupt budget journal line {number}') from e
        seen.update(reserved)
    seen.update(reserved)
    retry_path=Path(str(ledger_path)+'.retry.jsonl')
    if retry_path.exists():
        for line in retry_path.read_text().splitlines():
            try:
                entry=json.loads(line); deadline=datetime.datetime.fromisoformat(entry['not_before_utc'])
            except Exception as e: raise BenchError('corrupt retry deadline journal') from e
            if datetime.datetime.now(datetime.timezone.utc)<deadline: raise BenchError(f"rate limited; resume after {entry['not_before_utc']}")
    failures=0; stop=False; sent_this_run=0

    with BudgetLedger(ledger_path,str(budget)) as ledger:
      for task in tasks:
        rid=task['request_id']
        if rid in terminal: continue
        if rid in reserved and rid not in seen: continue
        if rid in seen: continue
        if sent_this_run>=a.max_requests: break
        payload=task['payload']; upper=task['input_upper_tokens']; cap=task['max_tokens']; prices=cfg['prices_usd_per_million']
        hold=cost_usd(upper,0,cap,prices['input'],prices['cached_input'],prices['output'])
        if sent_this_run>=a.max_requests: break
        if not ledger.reserve(rid,hold):
            stop=True
            break
        fsappend(ids,{'request_id':rid,'status':'reserved'}); reserved.add(rid)
        rec={k:task[k] for k in ('request_id','group_id','kind','target_tokens','repeat_index')}; rec.update({'protocol':protocol,'phase':phase,'started_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'unknown'})
        def on_event(ev): fsappend(events,{'request_id':rid,'event':ev})
        try:
            sent_this_run+=1
            tr=stream_chat(cfg['base_url'],key,payload,on_event=on_event)
            rec['transport']=tr
            status=tr.get('status'); usage=tr.get('final_usage')
            model=tr.get('response_model')
            if model!=cfg['model'] and model not in cfg.get('model_aliases',[]): rec.update(status='model_mismatch',stop_reason='response model mismatch'); stop=True
            if status in (401,402,404): rec.update(status='http_stop',stop_reason=f'HTTP {status}'); stop=True
            if status==429:
                headers=tr.get('headers') or {}; retry=headers.get('retry-after') or headers.get('Retry-After'); rec.update(status='rate_limited',retry_after=retry); stop=True
                delay=0
                if isinstance(retry,str):
                    try: delay=max(0,int(retry))
                    except ValueError:
                        try: delay=max(0,int((email.utils.parsedate_to_datetime(retry)-datetime.datetime.now(datetime.timezone.utc)).total_seconds()))
                        except Exception: delay=0
                deadline=datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=delay)
                fsappend(retry_path,{'request_id':rid,'not_before_utc':deadline.isoformat(),'retry_after':retry})
            p=usage.get('prompt_tokens',usage.get('input_tokens')) if isinstance(usage,dict) else None
            o=usage.get('completion_tokens',usage.get('output_tokens')) if isinstance(usage,dict) else None
            det=usage.get('prompt_tokens_details') if isinstance(usage,dict) else None
            cache=det.get('cached_tokens') if isinstance(det,dict) else usage.get('prompt_cache_hit_tokens') if isinstance(usage,dict) else None
            valid=lambda x:isinstance(x,int) and not isinstance(x,bool) and x>=0
            if status==429:
                rec['status']='rate_limited'; failures+=1
            elif not valid(p) or not valid(o) or (cache is not None and not valid(cache)) or (cache is not None and cache>p):
                rec['status']='unknown_usage'; rec['cache_estimate']='unknown; held at full input price'; failures+=1
            elif p>upper or o>cap:
                rec.update(status='usage_bound_violation',stop_reason='reported usage exceeds reserved prompt/output bound'); stop=True; failures+=1
            elif rec['status'] not in ('model_mismatch','http_stop','rate_limited') and tr.get('done'):
                cache_n=cache or 0
                actual=cost_usd(p,cache_n,o,prices['input'],prices['cached_input'],prices['output'])
                rec.update(status='complete',usage={'prompt_tokens':p,'completion_tokens':o,'cached_tokens':cache,'cache_cost_basis':'full input price; cache unknown' if cache is None else 'reported cache usage'},actual_usd=actual)
            else: failures+=1
        except Exception as e:
            rec.update(status='transport_error',error_type=type(e).__name__); failures+=1
        # Durable result before settlement; exception/invalid results retain reservation.
        fsappend(records,rec); seen.add(rid)
        if rec.get('status')=='complete': ledger.settle(rid,rec['actual_usd'])
        if rec.get('status') in ('rate_limited','model_mismatch','http_stop','usage_bound_violation'): seen.add(rid)
        if failures>=3: stop=True
        if stop: break
        if rec.get('status')=='rate_limited': break
        time.sleep(2)
def main(argv=None):
 p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True)
 q=sub.add_parser('plan'); q.add_argument('--provider',required=True); q.add_argument('--budget',default='15'); q.add_argument('--groups',type=int,default=200); q.add_argument('--throughput',type=int,default=1000); q.add_argument('--run-id',required=True); q.add_argument('--seed',type=int,required=True); q.add_argument('--output',required=True); q.add_argument('--bytes-per-token',type=float,default=4.0); q.add_argument('--preregistered-revision'); q.set_defaults(fn=plan)
 q=sub.add_parser('run'); q.add_argument('--plan',required=True); q.add_argument('--phase',choices=('pilot','formal'),required=True); q.add_argument('--ledger',required=True); q.add_argument('--budget',default='15'); q.add_argument('--max-requests',type=int,default=0); q.add_argument('--provider'); q.add_argument('--ack-unverified-pilot',action='store_true'); q.add_argument('--preregistered-revision'); q.set_defaults(fn=run)
 a=p.parse_args(argv)
 try: a.fn(a); return 0
 except Exception as e: print(f'bench: {type(e).__name__}: {str(e) if isinstance(e,BenchError) else type(e).__name__}',file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
