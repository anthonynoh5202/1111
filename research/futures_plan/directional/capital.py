"""Capital tiers: discrete lot simulation (0.001 BTC step, 50 USDT min notional) and KRW P&L ranges."""
import pickle
import numpy as np
import pandas as pd
from common import (OUT, COSTS, BAND, IS_START, OOS_START, OOS_END, FULL_START, load_klines, bar_inputs,
                    sl, max_dd)

KRW_PER_USDT = 1400.0
STEP, MIN_NOTIONAL = 0.001, 50.0
TIERS_KRW = {'100만': 1_000_000, '1,000만': 10_000_000, '1억': 100_000_000}

T = pickle.load(open(f'{OUT}/targets.pkl', 'rb'))
D = pickle.load(open(f'{OUT}/daily_results.pkl', 'rb'))['res']['base']
d1 = load_klines('1d')
ret, F = bar_inputs('1d')
op = d1.open.values
nxt = np.r_[op[1:], d1.close.values[-1]]


def target_of(name):
    if name == 'BH-PERP':
        return np.ones(len(d1))
    return T[name][1].shift(1).fillna(0.0).values


def run_discrete(target, E0, lev=1.0, cost=COSTS['base'], start=FULL_START):
    n = len(target)
    E, q = E0, 0.0
    r = np.zeros(n); wt = np.zeros(n); skipped = 0; ntr = 0; err = []
    active = d1.index >= start
    for i in range(n):
        if not active[i]:
            continue
        P = op[i]
        if E <= 0:
            r[i] = 0.0
            continue
        wd = q * P / E
        tgt = target[i] * lev
        if tgt == 0.0 or wd == 0.0 or (tgt > 0) != (wd > 0) or abs(tgt - wd) > BAND * abs(tgt):
            want = tgt
        else:
            want = wd
        q_new = np.round(want * E / P / STEP) * STEP
        if abs(q_new - q) > 1e-12:
            increasing = abs(q_new) > abs(q) + 1e-12 or (q_new * q < 0)
            if increasing and abs(q_new - q) * P < MIN_NOTIONAL:
                q_new = q
                skipped += 1
        c = abs(q_new - q) * P * cost
        if abs(q_new - q) > 1e-12:
            ntr += 1
        q = q_new
        E0d = E
        E = E - c + q * (nxt[i] - P) - q * P * F[i]
        r[i] = E / E0d - 1.0
        wt[i] = q * P / E0d
        if tgt != 0:
            err.append(abs(wt[i] - tgt) / abs(tgt))
    return r, wt, skipped, ntr, np.array(err)


CANDS = ['F1 COMBO-LO', 'B1 SMA50-LO', 'A5 TSMOM90-LO', 'D3 VT-SMA100-LO', 'BH-PERP']
caps_usdt = [100, 200, 300, 500, 714, 1000, 2000, 3000, 5000, 7143, 20000, 71429]
rows = []
for name in CANDS:
    tgt = target_of(name)
    ideal = sl(D[name], OOS_START, OOS_END)['r'].values
    for E0 in caps_usdt:
        r, wt, sk, ntr, err = run_discrete(tgt, float(E0), start=OOS_START)
        rr = pd.Series(r, index=d1.index)
        rr = rr[(rr.index >= OOS_START) & (rr.index <= OOS_END)].values
        te = np.std(rr - ideal, ddof=1) * np.sqrt(365)
        yrs = len(rr) / 365.25
        cagr = np.prod(1 + rr) ** (1 / yrs) - 1
        cagr_i = np.prod(1 + ideal) ** (1 / yrs) - 1
        rows.append(dict(name=name, capital_usdt=E0, capital_krw=E0 * KRW_PER_USDT, CAGR=cagr, CAGR_ideal=cagr_i,
                         TE=te, med_size_err=np.median(err) if len(err) else np.nan,
                         p90_size_err=np.percentile(err, 90) if len(err) else np.nan,
                         skipped=sk, trades=ntr))
disc = pd.DataFrame(rows)
disc.to_csv(f'{OUT}/discrete_tiers.csv', index=False)

# ------------------------------------------------ KRW P&L ranges via block bootstrap of 1-year returns
rng = np.random.default_rng(11)
NP, H, BLOCK = 10000, 365, 20
pl_rows = []
for name, L in [('F1 COMBO-LO', 1.0), ('F1 COMBO-LO', 2.0), ('B1 SMA50-LO', 1.0), ('A5 TSMOM90-LO', 1.0),
                ('D3 VT-SMA100-LO', 1.0), ('BH-PERP', 1.0), ('BH-SPOT', 1.0)]:
    for src, (a, b) in {'FULL': (FULL_START, OOS_END), 'OOS': (OOS_START, OOS_END),
                        'FULL_half': (FULL_START, OOS_END)}.items():
        x = sl(D[name], a, b)['r'].values
        if src == 'FULL_half':                  # haircut: keep the shape/vol, halve the historical mean return
            x = x - x.mean() / 2
        nb = int(np.ceil(H / BLOCK))
        st = rng.integers(0, len(x), size=(NP, nb))
        idx = ((st[:, :, None] + np.arange(BLOCK)) % len(x)).reshape(NP, -1)[:, :H]
        R1 = np.prod(np.maximum(1 + L * x[idx], 0), axis=1) - 1
        for tier, krw in TIERS_KRW.items():
            pl = R1 * krw
            pl_rows.append(dict(name=name, L=L, src=src, tier=tier, mean=pl.mean(), median=np.median(pl),
                                p05=np.percentile(pl, 5), p25=np.percentile(pl, 25), p75=np.percentile(pl, 75),
                                p95=np.percentile(pl, 95), P_loss=(R1 < 0).mean(), P_loss20=(R1 < -0.2).mean()))
pl = pd.DataFrame(pl_rows)
pl.to_csv(f'{OUT}/krw_pnl.csv', index=False)

with open(f'{OUT}/capital.pkl', 'wb') as f:
    pickle.dump(dict(disc=disc, pl=pl, krw=KRW_PER_USDT), f)

pd.set_option('display.width', 250); pd.set_option('display.max_columns', 40); pd.set_option('display.max_rows', 500)
print('BTC open price OOS range', d1.open[d1.index >= OOS_START].min(), d1.open[d1.index >= OOS_START].max(),
      'last close', d1.close.iloc[-1], ' 0.001 BTC notional now =', round(0.001 * d1.close.iloc[-1], 1), 'USDT')
print(disc.round(4).to_string())
print(pl[pl.tier == '1,000만'].round(3).to_string())
