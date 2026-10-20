"""Coding-session model grounded in measured data.

Every parameter is either MEASURED (with the context size it was measured at) or
EXTRAPOLATED (log-linear fit on the measured points, flagged as such).
"""
import json
from decimal import Decimal as D
from math import log

# ---- measured cache ratios (identical prompt repeated, DeepSeek family behaviour) ----
CACHE_MEASURED = {4000: 0.936, 16000: 0.989, 32000: 0.990, 128000: 0.9997}

# ---- measured warm TTFT (ms) per tier by context ----
# 4K: sustained runs (n=30) — P50 ; 32K: batch run ; 128K: batch run
TTFT = {
    'DeepSeek 官方':     {4000: 673, 32000: 814},
    'DeepInfra Std':     {4000: 867, 32000: 878},
    'DeepInfra Priority':{4000: 927, 32000: 878},
    'Baseten Standard':  {4000: 649, 32000: 984},
    'Fireworks':         {4000: 1277, 32000: 4526},
    'Lithos Base':       {4000: 1359, 32000: 1915, 128000: 1928},
    'Lithos Ultra':      {4000: 1985, 32000: 2976, 128000: 2971},
    'Lithos Fast':       {4000: 2287, 32000: 3165, 128000: 3435},
}

# ---- measured decode speed (tok/s, includes reasoning) ----
TPS = {
    'DeepSeek 官方': 177, 'DeepInfra Std': 79, 'DeepInfra Priority': 87,
    'Baseten Standard': 210, 'Fireworks': 107, 'Lithos Base': 327,
    'Lithos Ultra': 434, 'Lithos Fast': 425,
}

# ---- official prices: input / output / cached, USD per 1M ----
PRICE = {
    'DeepSeek 官方':      ('0.14', '0.28', '0.014'),
    'DeepInfra Std':      ('0.14', '0.42', '0.004'),
    'DeepInfra Priority': ('0.21', '0.63', '0.0063'),
    'Baseten Standard':   ('0.30', '1.20', '0.007'),
    'Fireworks':          ('0.30', '1.20', '0.006'),
    'Lithos Base':        ('0.15', '0.60', '0.003'),
    'Lithos Ultra':       ('0.35', '1.40', '0.007'),
    'Lithos Fast':        ('0.25', '1.00', '0.005'),
}


def cache_ratio(ctx: int) -> tuple[float, bool]:
    if ctx in CACHE_MEASURED:
        return CACHE_MEASURED[ctx], False
    xs = sorted(CACHE_MEASURED)
    if ctx < xs[0]:
        return CACHE_MEASURED[xs[0]], True
    if ctx > xs[-1]:
        return CACHE_MEASURED[xs[-1]], True
    for a, b in zip(xs, xs[1:]):
        if a <= ctx <= b:
            t = (log(ctx) - log(a)) / (log(b) - log(a))
            return CACHE_MEASURED[a] + t * (CACHE_MEASURED[b] - CACHE_MEASURED[a]), True
    return CACHE_MEASURED[xs[-1]], True


def ttft_ms(tier: str, ctx: int) -> tuple[float, bool]:
    pts = TTFT[tier]
    if ctx in pts:
        return pts[ctx], False
    xs = sorted(pts)
    if ctx <= xs[0]:
        return pts[xs[0]], True
    if ctx >= xs[-1]:
        a, b = xs[-2], xs[-1]
        slope = (pts[b] - pts[a]) / (log(b) - log(a))
        return pts[b] + slope * (log(ctx) - log(b)), True
    for a, b in zip(xs, xs[1:]):
        if a <= ctx <= b:
            t = (log(ctx) - log(a)) / (log(b) - log(a))
            return pts[a] + t * (pts[b] - pts[a]), True
    return pts[xs[-1]], True


def session(tier: str, ctx: int, new_per_turn: int = 2000, out_per_turn: int = 500, turns: int = 20):
    pi, po, pc = (D(x) for x in PRICE[tier])
    ratio, rflag = cache_ratio(ctx)
    t_ms, tflag = ttft_ms(tier, ctx)
    cost = D(0)
    wall_ms = 0.0
    for _ in range(turns):
        cached = D(ctx) * D(str(ratio))
        uncached = D(ctx) - cached
        cost += (uncached * pi + cached * pc + D(out_per_turn) * po) / D(10 ** 6)
        wall_ms += t_ms + out_per_turn / TPS[tier] * 1000
        ctx += new_per_turn
    return cost, wall_ms, rflag, tflag


if __name__ == '__main__':
    print(f"{'档位':18s}{'20K会话':>10s}{'200K会话':>11s}{'800K会话':>11s}{'20K墙钟':>9s}{'800K墙钟':>10s}")
    for tier in PRICE:
        c20, w20, _, _ = session(tier, 20000)
        c200, w200, _, _ = session(tier, 200000)
        c800, w800, rf, tf = session(tier, 800000)
        print(f"{tier:18s}{c20:10.4f}{c200:11.4f}{c800:11.4f}{w20/1000:8.1f}s{w800/1000:9.1f}s")
    print('\n800K 行为推算(未实测)：缓存率取 128K 实测 0.9997；首token 按实测点对数线性外推')