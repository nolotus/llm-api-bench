"""Monte-Carlo session simulation from measured per-turn samples.

Each turn draws a TTFT from the measured empirical distribution (bootstrap, with
replacement) plus a decode time derived from measured tok/s. 20 turns per session,
thousands of sessions. Reports session-level P50/P90/P99/max — not an average of
averages, so single 10-20s spikes actually show up in the tail.
"""
import json
import random
from pathlib import Path

SUS = Path('results/sustained/stage_records.jsonl')
random.seed(20261020)

# measured decode tok/s (from earlier analysis)
TPS = {
    'DeepSeek 官方': 177, 'DeepInfra Std': 79, 'Baseten Standard': 210,
    'Fireworks': 107, 'Lithos Base': 327, 'Lithos Ultra': 434, 'Lithos Fast': 425,
}
# measured 128K vs 4K warm-TTFT ratio (only Lithos measured); others use this median
RATIO_128K = {'Lithos Base': 1928 / 1359, 'Lithos Ultra': 2971 / 1985, 'Lithos Fast': 3435 / 2287}
DEFAULT_RATIO = sum(RATIO_128K.values()) / len(RATIO_128K)


def load_samples():
    rows = [json.loads(l) for l in SUS.read_text().splitlines()]
    out = {}
    for r in rows:
        rid = r.get('request_id', '')
        if 'cold' in rid or not r.get('first_token_ms'):
            continue
        key = (r.get('provider'), r.get('tier') or 'standard')
        out.setdefault(key, []).append(r['first_token_ms'])
    return out


def q(a, p):
    a = sorted(a)
    return a[min(len(a) - 1, int(round((len(a) - 1) * p)))]


def simulate(samples, tps, turns=20, out_tok=500, scale=1.0, n_sim=2000):
    per_turn_decode = out_tok / tps * 1000
    totals = []
    for _ in range(n_sim):
        t = 0.0
        for _ in range(turns):
            t += random.choice(samples) * scale + per_turn_decode
        totals.append(t / 1000.0)
    return totals


if __name__ == '__main__':
    s = load_samples()
    print(f"{'provider/tier':26s}{'n':>3s}{'4K会话P50':>11s}{'P90':>7s}{'P99':>8s}{'最长':>8s}{'800K P50':>10s}{'P99':>8s}")
    for key, samples in sorted(s.items()):
        if len(samples) < 10:
            continue
        name = f'{key[0]}/{key[1]}'
        tier_key = None
        for t in TPS:
            if t.split()[0].lower() in key[0].lower() and (t.endswith(key[1].capitalize()) or key[1] == 'standard'):
                tier_key = t
                break
        tps = TPS.get(tier_key, 150)
        base = simulate(samples, tps)
        ratio = RATIO_128K.get(tier_key, DEFAULT_RATIO)
        big = simulate(samples, tps, scale=ratio * 1.35)   # 800K ≈ 128K ratio × extra growth
        print(f"{name:26s}{len(samples):3d}{q(base,.5):10.1f}s{q(base,.9):6.1f}s{q(base,.99):7.1f}s{max(base):7.1f}s"
              f"{q(big,.5):9.1f}s{q(big,.99):7.1f}s")
    print(f"\n128K/4K 首token 比例（实测）：{ {k: round(v,2) for k,v in RATIO_128K.items()} }，其余按中位 {DEFAULT_RATIO:.2f}")
    print('800K 为推算：128K 实测比例 × 1.35（额外增长），未实测')