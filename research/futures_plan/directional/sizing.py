"""Leverage / Kelly / bootstrap drawdown / liquidation analysis for the sizing candidates."""
import pickle
import numpy as np
import pandas as pd
from common import (OUT, COSTS, IS_START, IS_END, OOS_START, OOS_END, FULL_START, load_klines, bar_inputs,
                    run_engine, to_daily, metrics, sl, cbb_idx, max_dd)

T = pickle.load(open(f'{OUT}/targets.pkl', 'rb'))
D = pickle.load(open(f'{OUT}/daily_results.pkl', 'rb'))['res']
A = pickle.load(open(f'{OUT}/analysis.pkl', 'rb'))
d1 = load_klines('1d')
ret, F = bar_inputs('1d')
ret_nf, F_nf = bar_inputs('1d', with_funding=False)
op, lo, hi = d1.open.values, d1.low.values, d1.high.values
MMR = 0.005

# data-driven pick: highest min(IS, OOS) Sharpe, distinct families
VAR = list(A['summary']['IS'].index[2:])
mins = pd.Series({k: min(A['tables'][('base', 'IS')].loc[k, 'Sharpe'], A['tables'][('base', 'OOS')].loc[k, 'Sharpe'])
                  for k in VAR}).sort_values(ascending=False)
print('min(IS,OOS) Sharpe ranking:\n', mins.round(3).head(8).to_string())
picked, fams = [], set()
for k in mins.index:
    if k[0] not in fams:
        picked.append(k); fams.add(k[0])
    if len(picked) == 2:
        break
CANDS = ['F1 COMBO-LO'] + [k for k in picked if k != 'F1 COMBO-LO']
print('sizing candidates:', CANDS)
REFS = ['BH-PERP', 'D1 VT-BH']


def target_of(name):
    if name in ('BH-PERP', 'BH-SPOT'):
        return np.ones(len(d1))
    tf, dec = T[name]
    return dec.shift(1).fillna(0.0).values


# ------------------------------------------------ 1. historical leverage runs (with intrabar liquidation check)
LEVS = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
rows = []
lev_daily = {}
START_MASK = (d1.index >= FULL_START)
for name in CANDS + REFS:
    tgt = target_of(name) * START_MASK          # everyone starts on the same day (2020-07-20)
    for L in LEVS:
        out = run_engine(tgt, ret, F, COSTS['base'], lev=L, op=op, lo=lo, hi=hi, mmr=MMR, liq=True)
        dd = to_daily(d1.index, out)
        lev_daily[(name, L)] = dd
        for w, (a, b) in {'FULL': (FULL_START, OOS_END), 'IS': (IS_START, IS_END), 'OOS': (OOS_START, OOS_END)}.items():
            s = sl(dd, a, b)
            m = metrics(s)
            rows.append(dict(name=name, L=L, win=w, CAGR=m['CAGR'], Vol=m['Vol'], Sharpe=m['Sharpe'], MaxDD=m['MaxDD'],
                             Calmar=m['Calmar'], liq=int(s['liq'].sum()), FundYr=m['FundYr'], TCYr=m['TCYr']))
levtab = pd.DataFrame(rows)
levtab.to_csv(f'{OUT}/leverage_hist.csv', index=False)

# ------------------------------------------------ 2. Kelly from mean log growth
def growth_curve(r, Ls):
    g = []
    for L in Ls:
        x = 1 + L * r
        g.append(-np.inf if (x <= 0).any() else np.log(x).mean())
    return np.array(g)


Lgrid = np.round(np.arange(0.0, 8.01, 0.05), 2)
kelly = []
for name in CANDS + REFS + ['BH-SPOT']:
    for w, (a, b) in {'FULL': (FULL_START, OOS_END), 'IS': (IS_START, IS_END), 'OOS': (OOS_START, OOS_END)}.items():
        r = sl(D['base'][name], a, b)['r'].values
        g = growth_curve(r, Lgrid)
        Ls = Lgrid[int(np.argmax(g))]
        cont = r.mean() / r.var()
        rec = dict(name=name, win=w, kelly_L=Ls, kelly_cont=cont, half_kelly=Ls / 2)
        for L in [0.5, 1, 1.5, 2, 3]:
            gi = growth_curve(r, [L])[0]
            rec[f'g{L}'] = np.exp(365 * gi) - 1 if np.isfinite(gi) else -1.0
        kelly.append(rec)
kelly = pd.DataFrame(kelly)
kelly.to_csv(f'{OUT}/kelly.csv', index=False)

# ------------------------------------------------ 3. block bootstrap of leveraged paths
rng = np.random.default_rng(7)
NP = 10000
boot_rows = []
for name in CANDS + REFS + ['BH-SPOT']:
    r = sl(D['base'][name], FULL_START, OOS_END)['r'].values
    for block in [20, 60]:
        for H in [365, 1095]:
            nb = int(np.ceil(H / block))
            st = rng.integers(0, len(r), size=(NP, nb))
            idx = ((st[:, :, None] + np.arange(block)) % len(r)).reshape(NP, -1)[:, :H]
            X = r[idx]
            for L in [1.0, 2.0, 3.0]:
                Y = np.maximum(1 + L * X, 0.0)
                eq = np.cumprod(Y, axis=1)
                peak = np.maximum.accumulate(np.concatenate([np.ones((NP, 1)), eq], axis=1), axis=1)[:, 1:]
                mdd = (eq / np.maximum(peak, 1e-300) - 1).min(axis=1)
                term = eq[:, -1]
                cagr = np.where(term > 0, term ** (365.25 / H) - 1, -1.0)
                boot_rows.append(dict(name=name, block=block, H=H, L=L,
                                      med_CAGR=np.median(cagr), p05_CAGR=np.percentile(cagr, 5),
                                      p95_CAGR=np.percentile(cagr, 95), mean_term=term.mean(),
                                      P_loss=(term < 1).mean(), med_MDD=np.median(mdd),
                                      P_DD50=(mdd <= -0.5).mean(), P_DD80=(mdd <= -0.8).mean(),
                                      P_ruin=(term <= 0.01).mean()))
boot = pd.DataFrame(boot_rows)
boot.to_csv(f'{OUT}/leverage_boot.csv', index=False)

# ------------------------------------------------ 4. liquidation thresholds and history
def thr(L, mmr=MMR):
    """adverse move from entry (fraction) that triggers isolated liquidation when margin = notional / L."""
    return (mmr * L - 1.0) / (L * (1.0 - mmr))


LL = [1, 2, 3, 5, 10]
th = {L: thr(L) for L in LL}
# (a) generic: long held with fixed quantity for H days from each day's open (2020-01-01 .. ), adverse excursion via daily lows
lows = pd.Series(lo, index=d1.index); highs = pd.Series(hi, index=d1.index); opens = pd.Series(op, index=d1.index)
gen = []
for H in [1, 7, 30, 90]:
    mn = lows[::-1].rolling(H, min_periods=H).min()[::-1]       # min low over [t, t+H-1]
    mx = highs[::-1].rolling(H, min_periods=H).max()[::-1]
    mae_l = (mn / opens - 1).dropna(); mae_s = (mx / opens - 1).dropna()
    rec = dict(H=H, n=len(mae_l), worst_long=mae_l.min(), worst_short=mae_s.max())
    for L in LL:
        rec[f'long_L{L}'] = (mae_l <= th[L]).mean()
        rec[f'short_L{L}'] = (mae_s >= -th[L]).mean()
    gen.append(rec)
gen = pd.DataFrame(gen)
gen.to_csv(f'{OUT}/liq_generic.csv', index=False)

# (b) per-trade set-and-forget for binary candidates (+ BH): margin fixed at entry, no top-ups
def trades_of(name):
    tgt = target_of(name)
    s = np.sign(tgt)
    tr = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] != 0:
            j = i
            while j + 1 < n and s[j + 1] == s[i]:
                j += 1
            tr.append((i, j, s[i]))      # held during bars i..j, exit at open of j+1
            i = j + 1
        else:
            i += 1
    return tr


trade_rows = []
for name in [c for c in CANDS if c[0] in 'ABC'] + ['BH-PERP']:
    tr = trades_of(name)
    for (i, j, sgn) in tr:
        if d1.index[i] < FULL_START and name != 'BH-PERP':
            continue
        entry = op[i]
        if sgn > 0:
            mae = lo[i:j + 1].min() / entry - 1
        else:
            mae = -(hi[i:j + 1].max() / entry - 1)
        exitp = op[j + 1] if j + 1 < len(op) else d1.close.values[-1]
        pnl = sgn * (exitp / entry - 1)
        trade_rows.append(dict(name=name, entry=d1.index[i].date(), days=j - i + 1, side=int(sgn), mae=mae, pnl=pnl))
trades = pd.DataFrame(trade_rows)
trades.to_csv(f'{OUT}/trades_mae.csv', index=False)
liq_trades = []
for name, g in trades.groupby('name'):
    rec = dict(name=name, n_trades=len(g), worst_mae=g.mae.min(), median_mae=g.mae.median())
    for L in LL:
        rec[f'liq_L{L}'] = int((g.mae <= th[L]).sum())
    liq_trades.append(rec)
liq_trades = pd.DataFrame(liq_trades)
liq_trades.to_csv(f'{OUT}/liq_trades.csv', index=False)

# (c) daily re-margined: days on which an L-levered position (actual strategy weight) would be liquidated
liq_daily = []
for name in CANDS + REFS:
    for L in [1, 2, 3, 5]:
        out = run_engine(target_of(name), ret, F, COSTS['base'], lev=L, op=op, lo=lo, hi=hi, mmr=MMR, liq=True)
        days = d1.index[out['liq']]
        liq_daily.append(dict(name=name, L=L, n_liq=len(days), dates=';'.join(str(x.date()) for x in days[:5])))
liq_daily = pd.DataFrame(liq_daily)
liq_daily.to_csv(f'{OUT}/liq_daily.csv', index=False)

# worst intraday adverse moves (from open) on days the candidate was long, post warm-up
worst = {}
for name in CANDS + REFS:
    tgt = target_of(name)
    m = (tgt > 0) & (d1.index >= FULL_START)
    x = lo[m] / op[m] - 1
    k = np.argsort(x)[:3]
    worst[name] = [(str(d1.index[m][q].date()), round(float(x[q]), 3), round(float(tgt[m][q]), 2)) for q in k]
x_all = lo / op - 1
k_all = np.argsort(x_all)[:5]
worst['ALL DAYS (any)'] = [(str(d1.index[q].date()), round(float(x_all[q]), 3)) for q in k_all]

# ------------------------------------------------ 5. spot implementation of long-only rules (no funding, 0.12%/side)
spot_rows = []
for name in ['BH-SPOT', 'B1 SMA50-LO', 'B2 SMA100-LO', 'A5 TSMOM90-LO', 'F1 COMBO-LO', 'D3 VT-SMA100-LO']:
    tgt = target_of('BH-PERP') if name == 'BH-SPOT' else target_of(name)
    tgt = np.minimum(tgt, 1.0)                  # spot cannot exceed 1x
    out = run_engine(tgt, ret_nf, F_nf, 0.0012)
    dd = to_daily(d1.index, out)
    for w, (a, b) in {'IS': (IS_START, IS_END), 'OOS': (OOS_START, OOS_END)}.items():
        m = metrics(sl(dd, a, b))
        perp = A['tables'][('base', w)].loc[name]
        spot_rows.append(dict(name=name, win=w, spot_CAGR=m['CAGR'], spot_Sharpe=m['Sharpe'], spot_MDD=m['MaxDD'],
                              perp_CAGR=perp['CAGR'], perp_Sharpe=perp['Sharpe'], perp_MDD=perp['MaxDD']))
spot = pd.DataFrame(spot_rows)
spot.to_csv(f'{OUT}/spot_impl.csv', index=False)

with open(f'{OUT}/sizing.pkl', 'wb') as f:
    pickle.dump(dict(cands=CANDS, refs=REFS, levtab=levtab, kelly=kelly, boot=boot, gen=gen, trades=trades,
                     liq_trades=liq_trades, liq_daily=liq_daily, worst=worst, spot=spot, th=th, mins=mins), f)

pd.set_option('display.width', 250); pd.set_option('display.max_columns', 40); pd.set_option('display.max_rows', 500)
print('\nthresholds', {L: round(v, 4) for L, v in th.items()})
print('\n=== leverage (historical engine runs, base cost, liquidation check)')
print(levtab.round(3).to_string())
print('\n=== Kelly')
print(kelly.round(3).to_string())
print('\n=== bootstrap')
print(boot.round(3).to_string())
print('\n=== generic liquidation frequency (fixed-quantity holds)')
print(gen.round(4).to_string())
print('\n=== per-trade set-and-forget liquidation counts')
print(liq_trades.round(3).to_string())
print('\n=== daily re-margined liquidation counts')
print(liq_daily.to_string())
print('\n=== worst intraday adverse moves while long')
for k, v in worst.items():
    print(k, v)
print('\n=== spot implementation')
print(spot.round(3).to_string())
