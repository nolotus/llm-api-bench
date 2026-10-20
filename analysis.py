#!/usr/bin/env python3
"""Summarize benchmark JSONL. Timings are client receive-time, not server token-time."""
from __future__ import annotations
import argparse, json, math, random, statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

BOOTSTRAPS = 500
TIMING_FIELDS = ("headers_ms", "first_generated_ms", "first_content_ms", "last_generated_ms", "total_ms")


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _transport(r: dict) -> dict:
    t = r.get("transport")
    return t if isinstance(t, dict) else {}


def _usage(r: dict) -> dict:
    t = _transport(r)
    u = t.get("final_usage")
    if u is None: u = r.get("final_usage", r.get("usage"))
    if not isinstance(u, dict): return {"prompt": None, "completion": None, "cached": None}
    p = u.get("prompt_tokens", u.get("input_tokens"))
    c = u.get("completion_tokens", u.get("output_tokens"))
    details = u.get("prompt_tokens_details")
    a = details.get("cached_tokens") if isinstance(details, dict) else None
    b = u.get("prompt_cache_hit_tokens")
    cached = None
    if a is not None and b is not None and a != b: return {"prompt": p, "completion": c, "cached": None}
    cached = a if a is not None else b
    if not _valid_count(p): p = None
    if not _valid_count(c): c = None
    if not _valid_count(cached) or (p is not None and cached > p): cached = None
    return {"prompt": p, "completion": c, "cached": cached}


def _valid_count(x):
    return isinstance(x, int) and not isinstance(x, bool) and x >= 0


def _events(r: dict) -> list[dict]:
    es = _transport(r).get("events", r.get("events", []))
    if not isinstance(es, list): return []
    out = []
    for e in es:
        if not isinstance(e, dict): continue
        data = e.get("data", e.get("raw_data"))
        if isinstance(data, str):
            try: e = {**e, **json.loads(data)}
            except (ValueError, TypeError): continue
        out.append(e)
    return out


def _summary(values: list[float], groups: dict, seed: int) -> dict:
    vals = sorted(values)
    n = len(vals)
    if n:
        q = statistics.quantiles(vals, n=4, method="inclusive") if n > 1 else [vals[0]] * 3
        p50 = float(statistics.median(vals)); mean = float(statistics.mean(vals))
        iqr = float(q[2] - q[0]); lo=float(vals[0]); hi=float(vals[-1])
    else: mean=p50=iqr=lo=hi=None
    p95 = _percentile(vals, .95) if n >= 100 and len(groups) >= 100 else None
    p99 = _percentile(vals, .99) if len(groups) >= 1000 else None
    ci = _median_ci(groups, seed)
    return {"n": n, "mean": mean, "min":lo, "max":hi, "p50":p50, "IQR":iqr,
            "p95":p95,"p99":p99,"median95_ci":ci}


def _percentile(vals, p):
    if not vals: return None
    if len(vals)==1: return float(vals[0])
    return float(_interp(vals, (len(vals)-1)*p))


def _interp(vals, x):
    i=int(x); frac=x-i
    return vals[i] if i+1>=len(vals) else vals[i]*(1-frac)+vals[i+1]*frac


def _median_ci(groups, seed):
    if len(groups)<20: return None
    ids=sorted(groups); rng=random.Random(seed); meds=[]
    for _ in range(BOOTSTRAPS):
        sample=[]
        for _ in ids: sample.extend(groups[ids[rng.randrange(len(ids))]])
        if sample: meds.append(float(statistics.median(sample)))
    meds.sort()
    return [meds[12],meds[487]] if len(meds)==BOOTSTRAPS else None


def _timing(r, field):
    return _transport(r).get(field)


def _times(records, seed, field="total_ms", success_only=True):
    valid=[]; groups=defaultdict(list)
    for r in records:
        t=_transport(r); ok=t.get("status")==200 and t.get("done") is True and not t.get("error")
        if success_only and not ok: continue
        v=t.get(field)
        if _finite(v) and v>=0:
            valid.append(float(v))
            if r.get("group_id") is not None: groups[str(r["group_id"])].append(float(v))
    return _summary(valid, groups, seed)


def _speed(records):
    rates=[]
    for r in records:
        t=_transport(r); u=_usage(r); n=u["completion"]
        if t.get("status")!=200 or t.get("done") is not True or t.get("error") or not _valid_count(n) or n<256: continue
        es=_events(r); content=[]; reasoning=False
        for e in es:
            choices=e.get("choices")
            if not isinstance(choices,list): continue
            for ch in choices:
                delta=ch.get("delta",{}) if isinstance(ch,dict) else {}
                if not isinstance(delta,dict): continue
                if delta.get("reasoning_content"): reasoning=True
                text=delta.get("content")
                if isinstance(text,str) and text: content.append(e.get("elapsed_ns"))
        if reasoning or len(content)<2 or any(not _finite(x) for x in content): continue
        duration=(content[-1]-content[0])/1e9
        if duration>0: rates.append(n/duration)
    return {"n":len(rates),"mean_completion_tokens_per_s_approx":statistics.mean(rates) if rates else None,
            "note":"completion_tokens/(last nonempty content event - first); includes first-chunk token timing bias and is not server token-time"}


def summarize(records, seed=20261020) -> dict:
    rows=list(records); excluded=sum(r.get("phase")=="pilot" for r in rows)
    formal=[r for r in rows if r.get("phase")=="formal"]
    buckets=defaultdict(list)
    errors=defaultdict(int)
    for r in formal:
        buckets[(r.get("kind","unknown"),r.get("target_tokens","unknown"),"reuse" if r.get("repeat_index",0) else "new")].append(r)
        t=_transport(r); ok=t.get("status")==200 and t.get("done") is True and not t.get("error")
        errors["protocol_success" if ok else "protocol_failure"]+=1
        if ok and any(any(isinstance(ch,dict) and isinstance(ch.get("delta"),dict) and isinstance(ch["delta"].get("content"),str) and ch["delta"]["content"] for ch in e.get("choices",[])) for e in _events(r)):
            errors["body_success"]+=1
    strata={}
    for key,rs in sorted(buckets.items(),key=lambda x:tuple(map(str,x[0]))):
        name="|".join(map(str,key)); times={f:_times(rs,seed,field=f) for f in TIMING_FIELDS}
        failed_rs=[r for r in rs if _transport(r).get("status")!=200 or _transport(r).get("done") is not True or _transport(r).get("error")]
        times["failed_total_ms"]=_times(failed_rs,seed,field="total_ms",success_only=False)
        usage=[_usage(r) for r in rs]
        known_prompt=[u["prompt"] for u in usage if u["prompt"] is not None]
        known_completion=[u["completion"] for u in usage if u["completion"] is not None]
        known_cache=[u for u in usage if u["cached"] is not None]
        input_total=sum(u["prompt"] for u in usage if u["prompt"] is not None and u["cached"] is not None)
        cache_total=sum(u["cached"] for u in known_cache)
        strata[name]={"requests":len(rs),"protocol_success":sum(_transport(r).get("status")==200 and _transport(r).get("done") is True and not _transport(r).get("error") for r in rs),
          "time_ms":times,"chunk_speed":_speed(rs),"usage":{"prompt_tokens_known":len(known_prompt),"completion_tokens_known":len(known_completion),
          "usage_coverage_per_request":sum(u["prompt"] is not None and u["completion"] is not None for u in usage)/len(rs) if rs else None,
          "cache_known_requests":len(known_cache),"cache_coverage_per_request":len(known_cache)/len(rs) if rs else None,
          "cache_hit_requests":sum(u["cached"]>0 for u in known_cache),"cache_hit_rate":sum(u["cached"]>0 for u in known_cache)/len(known_cache) if known_cache else None,
          "token_weighted_cached_rate":cache_total/input_total if input_total else None}}
    return {"excluded_pilot":excluded,"excluded_non_formal":sum(r.get("phase") not in ("pilot","formal") for r in rows),"formal_requests":len(formal),"strata":strata,
      "errors":dict(errors),"measurement_policy":"Client receive-time measurements, not server token-time. Quantile cutoffs are conservative reporting policy, not stability guarantees. Chunk speed is completion_tokens divided by first-to-last nonempty content-event interval; includes first-chunk token timing bias. Unsupported metrics are null."}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("input",type=Path); p.add_argument("--output",type=Path,required=True); args=p.parse_args(argv)
    records=[]
    with args.input.open(encoding="utf-8") as f:
        for i,line in enumerate(f,1):
            if line.strip():
                try: records.append(json.loads(line))
                except json.JSONDecodeError as e: p.error(f"line {i}: invalid JSON: {e.msg}")
    args.output.write_text(json.dumps(summarize(records),indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
    print(f"wrote {args.output}")
if __name__=="__main__": main()
