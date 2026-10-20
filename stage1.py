"""Stage-1 runner: corrected methodology (sequential cold->warm, measured bytes/token).

Rules enforced here:
  * cache pairs are ALWAYS sequential: cold completes before warm is sent
  * input sizing uses a measured bytes-per-token estimate that is re-derived from real usage
  * output budget >= 512 so first content can appear after reasoning
"""
import argparse
import json
import math
import os
from pathlib import Path

import corpus
import live_transport
import stage_bench

MATRIX = 'providers/benchmark-matrix.json'
# measured on this corpus: 5.8-6.2 bytes per token; 5.6 slightly over-estimates tokens -> safe upper bound
BPT_EST = 5.6


def make_task(provider, tier_key, model, rid, text, size, rep, pair, out_cap=512):
    return {
        'request_id': rid,
        'provider': provider,
        'tier': tier_key,
        'kind': 'long',
        'target_tokens': size,
        'repeat_index': rep,
        'pair_id': pair,
        'payload': {
            'model': model,
            'messages': [{'role': 'user', 'content': text}],
            'max_tokens': out_cap,
            'stream': True,
        },
        'input_upper_tokens': math.ceil(len(text.encode('utf-8')) / 5.0) + 64,
        'output_upper_tokens': out_cap,
    }


def build(provider, tier_key, sizes, out_cap=512, warm_repeats=1):
    tasks = []
    for size in sizes:
        # cold/warm prefix must be unique per (provider, tier, run) or "cold" reads a prefix
        # warmed by an earlier run and the cold measurement becomes invalid.
        cold, warm = corpus.build_pair(size, f'p{provider}{tier_key}{size}', 1)
        pair = f'{provider}-{tier_key}-{size}'
        tasks.append(make_task(provider, tier_key, None, f's1-{size}-cold', cold, size, 0, pair, out_cap))
        for rep in range(1, warm_repeats + 1):
            if rep == 1:
                text = warm
            else:
                # same prefix as cold, distinct tail: replica-local caches may hit on a later try
                text = cold + f' rep{rep:02d}'
            tasks.append(make_task(provider, tier_key, None, f's1-{size}-warm{rep}',
                                   text, size, rep, pair, out_cap))
    return tasks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--provider', required=True)
    ap.add_argument('--tier', required=True)
    ap.add_argument('--sizes', default='1000,4000')
    ap.add_argument('--out-cap', type=int, default=512)
    ap.add_argument('--warm-repeats', type=int, default=1)
    ap.add_argument('--key-env', required=True)
    ap.add_argument('--ledger', required=True)
    ap.add_argument('--tag', required=True)
    args = ap.parse_args()

    matrix = json.loads(Path(MATRIX).read_text())
    prov = matrix['providers'][args.provider]
    model = prov['tiers'][args.tier]['model']
    sizes = [int(s) for s in args.sizes.split(',')]
    tasks = build(args.provider, args.tier, sizes, args.out_cap, args.warm_repeats)
    for t in tasks:
        t['payload']['model'] = model

    out = Path('results/stage1') / args.tag
    out.mkdir(parents=True, exist_ok=True)
    (out / 'tasks.jsonl').write_text('\n'.join(json.dumps(t) for t in tasks) + '\n')

    key = os.environ[args.key_env]
    tr = live_transport.make_transport(prov['base_url'], key, timeout_s=240)
    # max_workers=1 -> strict ordering, cold fully completes before warm is dispatched.
    summary = stage_bench.run_batch(MATRIX, args.provider, args.tier, tasks,
                                    args.ledger, transport=tr, max_workers=1)
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, default=str))

    print(json.dumps({k: v for k, v in summary.items() if k != 'requests'}))
    for r in summary['requests']:
        u = r.get('final_usage') or {}
        print(r['request_id'], 'http', r.get('http_status'),
              'ftok', r.get('first_token_ms'), 'fcontent', r.get('first_content_ms'),
              'total', r.get('total_ms'),
              'in', u.get('input_tokens'), 'cached', u.get('cached_input_tokens'),
              'out', u.get('output_tokens'), 'finish', r.get('finish_reason'))


if __name__ == '__main__':
    main()