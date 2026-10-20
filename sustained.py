"""Sustained load runner: measures speed + cache + stability over a time window.

Design:
  * one cold request warms the prefix, then N warm requests at a fixed rate
  * every request carries x-session-affinity so replica routing stays sticky
  * each wave goes through stage_bench.run_batch -> reserve before send, settle after
  * output: per-request records + time-bucket drift + tail percentiles
"""
import argparse
import json
import math
import os
import time
import uuid
from collections import defaultdict
from pathlib import Path

import corpus
import live_transport
import stage_bench

MATRIX = 'providers/benchmark-matrix.json'
OUT = Path('results/sustained')


def q(a, p):
    a = sorted(a)
    return a[min(len(a) - 1, int(round((len(a) - 1) * p)))] if a else None


def one(provider, tier_key, model, rid, text, size, rep, pair, cap):
    return {
        'request_id': rid, 'provider': provider, 'tier': tier_key, 'kind': 'sustained',
        'target_tokens': size, 'repeat_index': rep, 'pair_id': pair,
        'payload': {'model': model, 'messages': [{'role': 'user', 'content': text}],
                    'max_tokens': cap, 'stream': True},
        'input_upper_tokens': math.ceil(len(text.encode('utf-8')) / 5.0) + 64,
        'output_upper_tokens': cap,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--provider', required=True)
    ap.add_argument('--tier', required=True)
    ap.add_argument('--size', type=int, default=4000)
    ap.add_argument('--minutes', type=float, default=10)
    ap.add_argument('--per-minute', type=float, default=6)
    ap.add_argument('--out-cap', type=int, default=512)
    ap.add_argument('--tag', required=True)
    args = ap.parse_args()

    matrix = json.loads(Path(MATRIX).read_text())
    prov = matrix['providers'][args.provider]
    model = prov['tiers'][args.tier]['model']
    key = os.environ[prov['env_name']]
    session = str(uuid.uuid4())
    tr = live_transport.make_transport(prov['base_url'], key, timeout_s=240,
                                       extra_headers={'x-session-affinity': session})

    OUT.mkdir(parents=True, exist_ok=True)
    ledger = str(OUT / f'{args.provider}-{args.tier}-{args.tag}.jsonl')
    cold, _ = corpus.build_pair(args.size, f'sus{args.provider}{args.tier}{args.tag}', 1)
    pair = f'sus-{args.provider}-{args.tier}'

    # 1) cold: warms prefix, must show 0 cache
    t0 = time.time()
    s = stage_bench.run_batch(MATRIX, args.provider, args.tier,
                             [one(args.provider, args.tier, model, f'sus-{args.tag}-cold', cold,
                                  args.size, 0, pair, args.out_cap)],
                             ledger, transport=tr, max_workers=1)
    rows = list(s['requests'])

    # 2) steady warm stream at fixed rate
    interval = 60.0 / max(args.per_minute, 0.1)
    n = int(args.minutes * args.per_minute)
    for i in range(1, n + 1):
        target = t0 + i * interval
        wait = target - time.time()
        if wait > 0:
            time.sleep(wait)
        text = cold + f' s{i:04d}'
        s = stage_bench.run_batch(MATRIX, args.provider, args.tier,
                                 [one(args.provider, args.tier, model, f'sus-{args.tag}-w{i:04d}', text,
                                      args.size, i, pair, args.out_cap)],
                                 ledger, transport=tr, max_workers=1)
        rows.extend(s['requests'])

    # 3) summarize
    warm = [r for r in rows if 'warm' in r['request_id'] or '-w' in r['request_id']]
    def vals(key, src):
        out = []
        for r in src:
            v = r.get(key)
            if v is not None:
                out.append(v)
        return out
    ftok = vals('first_token_ms', warm)
    total = vals('total_ms', warm)
    cache = []
    for r in warm:
        u = r.get('final_usage') or {}
        i, c = u.get('input_tokens'), u.get('cached_input_tokens')
        if i and c is not None and c <= i:
            cache.append(c / i * 100)
    nocontent = sum(1 for r in warm if r.get('first_content_ms') is None)
    errs = sum(1 for r in warm if r.get('http_status') != 200)
    bad3 = sum(1 for v in total if v > 3000)

    print(json.dumps({
        'provider': args.provider, 'tier': args.tier, 'session': session,
        'n_warm': len(warm),
        'ftok': {'p50': q(ftok, .5), 'p90': q(ftok, .9), 'p95': q(ftok, .95), 'p99': q(ftok, .99), 'max': max(ftok) if ftok else None},
        'total': {'p50': q(total, .5), 'p95': q(total, .95), 'max': max(total) if total else None},
        'cache_p50': q(cache, .5), 'cache_min': min(cache) if cache else None,
        'no_content': nocontent, 'errors': errs, 'bad_over_3s': bad3,
    }, ensure_ascii=False))

    # 4) 10-minute buckets for drift
    buckets = defaultdict(list)
    for r in warm:
        t = r.get('started_at_utc')
        if not t or not r.get('first_token_ms'):
            continue
        buckets[t[11:15] + '0'][0:0] = []
        buckets[t[11:15] + '0'] = buckets[t[11:15] + '0']
    # simpler: bucket by index order
    buckets = defaultdict(list)
    for idx, r in enumerate(warm):
        b = idx // max(int(args.per_minute * 10), 1)
        if r.get('first_token_ms'):
            buckets[b].append(r['first_token_ms'])
    for b in sorted(buckets):
        v = buckets[b]
        print(f'bucket{b}: n={len(v)} p50={q(v,.5):.0f} p95={q(v,.95):.0f} max={max(v):.0f}')


if __name__ == '__main__':
    main()