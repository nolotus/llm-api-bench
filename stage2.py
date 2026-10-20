"""Stage-2 experiments: cache growth across turns, cache survival after idle, concurrency degradation.

All batches go through stage_bench.run_batch so every request is reserved before it is sent.
"""
import argparse
import json
import math
import os
import time
from pathlib import Path

import corpus
import live_transport
import stage_bench

MATRIX = 'providers/benchmark-matrix.json'
OUT = Path('results/stage2')


def task(provider, tier, model, rid, text, size, rep, pair, out_cap, kind):
    return {
        'request_id': rid, 'provider': provider, 'tier': tier, 'kind': kind,
        'target_tokens': size, 'repeat_index': rep, 'pair_id': pair,
        'payload': {'model': model, 'messages': [{'role': 'user', 'content': text}],
                    'max_tokens': out_cap, 'stream': True},
        'input_upper_tokens': math.ceil(len(text.encode('utf-8')) / 5.0) + 64,
        'output_upper_tokens': out_cap,
    }


def run(tasks, provider, tier, ledger, workers):
    matrix = json.loads(Path(MATRIX).read_text())
    prov = matrix['providers'][provider]
    key = os.environ[prov['env_name']]
    tr = live_transport.make_transport(prov['base_url'], key, timeout_s=240)
    return stage_bench.run_batch(MATRIX, provider, tier, tasks, ledger, transport=tr, max_workers=workers)


def show(tag, summary):
    print(f'--- {tag} ---')
    for r in summary['requests']:
        u = r.get('final_usage') or {}
        print(r['request_id'], 'http', r.get('http_status'),
              'ftok', round(r['first_token_ms']) if r.get('first_token_ms') else None,
              'fcontent', round(r['first_content_ms']) if r.get('first_content_ms') else None,
              'in', u.get('input_tokens'), 'cached', u.get('cached_input_tokens'),
              'out', u.get('output_tokens'), 'finish', r.get('finish_reason'))


def growth(provider, tier, sizes, out_cap, ledger, tag):
    model = json.loads(Path(MATRIX).read_text())['providers'][provider]['tiers'][tier]['model']
    chain = corpus.build_growth(sizes, f'g{provider}{tier}{tag}')
    tasks = [task(provider, tier, model, f'g-{provider}-turn{i+1}', text, sizes[i], i, f'grow-{provider}-{tier}', out_cap, 'growth')
             for i, text in enumerate(chain)]
    show(f'growth {provider}/{tier}', run(tasks, provider, tier, ledger, 1))


def ttl(provider, tier, size, gaps, out_cap, ledger, tag):
    model = json.loads(Path(MATRIX).read_text())['providers'][provider]['tiers'][tier]['model']
    cold, _ = corpus.build_pair(size, f't{provider}{tier}{tag}', 1)
    tasks = [task(provider, tier, model, 'ttl-cold', cold, size, 0, 'ttl', out_cap, 'ttl')]
    show('ttl cold', run(tasks, provider, tier, ledger, 1))
    for gap in gaps:
        time.sleep(gap)
        warm = cold + f' gap{gap}'
        t = [task(provider, tier, model, f'ttl-warm-{gap}s', warm, size, 1, 'ttl', out_cap, 'ttl')]
        show(f'ttl warm after {gap}s', run(t, provider, tier, ledger, 1))


def conc(provider, tier, size, levels, out_cap, ledger, tag):
    model = json.loads(Path(MATRIX).read_text())['providers'][provider]['tiers'][tier]['model']
    text = corpus.build_text(size, tag=f'c{provider}{tier}{tag}')
    for level in levels:
        tasks = [task(provider, tier, model, f'c{level}-r{i}', text + f' r{i}', size, 1, f'conc-{level}', out_cap, 'conc')
                 for i in range(level)]
        show(f'concurrency {level}', run(tasks, provider, tier, ledger, level))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', required=True, choices=['growth', 'ttl', 'conc'])
    ap.add_argument('--provider', required=True)
    ap.add_argument('--tier', required=True)
    ap.add_argument('--out-cap', type=int, default=512)
    ap.add_argument('--sizes', default='1000,2000,4000,8000,16000')
    ap.add_argument('--size', type=int, default=4000)
    ap.add_argument('--gaps', default='15,60')
    ap.add_argument('--levels', default='1,3,5')
    ap.add_argument('--tag', default='a')
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    ledger = str(OUT / f'{args.provider}-{args.tier}-{args.mode}-{args.tag}.jsonl')
    if args.mode == 'growth':
        growth(args.provider, args.tier, [int(s) for s in args.sizes.split(',')], args.out_cap, ledger, args.tag)
    elif args.mode == 'ttl':
        ttl(args.provider, args.tier, args.size, [int(g) for g in args.gaps.split(',')], args.out_cap, ledger, args.tag)
    else:
        conc(args.provider, args.tier, args.size, [int(x) for x in args.levels.split(',')], args.out_cap, ledger, args.tag)


if __name__ == '__main__':
    main()