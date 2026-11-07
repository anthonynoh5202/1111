"""Red-team checks: spot F1 vs. static BTC/cash mixes with the same average exposure.

Uses the same engine/cost assumptions as the note's spot implementation (extra.py):
  spot cost 0.12%/side, no funding, weight capped at 1, 10% band.
Static mix: constant target weight w (rebalanced by the same 10% band rule).
Cash interest: 0% (note's assumption) and 3%/yr on the uninvested part (KRW deposit-like), as a sensitivity.
"""
import numpy as np
import pandas as pd
from common import (load_klines, bar_inputs, run_engine, to_daily, metrics, sl, cbb_idx, max_dd,
                    IS_START, IS_END, OOS_START, OOS_END, FULL_START)
from strategies import build_all

S = build_all()
d1 = load_klines('1d')
ret_nf, F_nf = bar_inputs('1d', with_funding=False)
COST = 0.0012
start_mask = (d1.index >= FULL_START).astype(float)

f1_tgt = np.minimum(S['F1 COMBO-LO'][2].shift(1).fillna(0.0).values, 1.0) * start_mask
runs = {}
runs['F1 spot'] = to_daily(d1.index, run_engine(f1_tgt, ret_nf, F_nf, COST))
runs['BH spot (w=1)'] = to_daily(d1.index, run_engine(np.ones(len(d1)) * start_mask, ret_nf, F_nf, COST))

# average exposure of F1 spot in each window
for w_name, (a, b) in {'FULL': (FULL_START, OOS_END), 'IS': (IS_START, IS_END), 'OOS': (OOS_START, OOS_END)}.items():
    s = sl(runs['F1 spot'], a, b)
    print(f'F1 spot avg |w| {w_name}: {s.absw.mean():.3f}   in-market share {s.inmkt.mean():.3f}')

for w in [0.35, 0.40, 0.45, 0.50]:
    runs[f'static w={w:.2f}'] = to_daily(d1.index, run_engine(np.full(len(d1), w) * start_mask, ret_nf, F_nf, COST))


def with_cash_interest(d, rate):
    """add interest on the uninvested share (1-|w|) at an annual rate (simple daily accrual)."""
    out = d.copy()
    out['r'] = (1 + d['r']) * (1 + (1 - d['absw'].clip(0, 1)) * rate / 365) - 1
    return out


rows = []
for name, d in runs.items():
    for rate in [0.0, 0.03]:
        dd = with_cash_interest(d, rate) if rate else d
        for w_name, (a, b) in {'FULL': (FULL_START, OOS_END), 'IS': (IS_START, IS_END), 'OOS': (OOS_START, OOS_END)}.items():
            m = metrics(sl(dd, a, b))
            rows.append(dict(name=name, cash=f'{int(rate*100)}%', win=w_name, CAGR=m['CAGR'], Vol=m['Vol'],
                             Sharpe=m['Sharpe'], MDD=m['MaxDD'], Calmar=m['Calmar'], AvgExp=m['AvgExp'],
                             Turn=m['Turnover']))
t = pd.DataFrame(rows)
pd.set_option('display.width', 220)
for win in ['OOS', 'IS', 'FULL']:
    print(f'\n===== {win}')
    x = t[t.win == win].copy()
    for c in ['CAGR', 'Vol', 'MDD']:
        x[c] = (x[c] * 100).round(1)
    x['Sharpe'] = x['Sharpe'].round(2)
    x['Calmar'] = x['Calmar'].round(2)
    x['AvgExp'] = x['AvgExp'].round(2)
    x['Turn'] = x['Turn'].round(1)
    print(x.drop(columns='win').to_string(index=False))

# number of trading days (orders) per year for F1 spot -> manual burden
d = sl(runs['F1 spot'], FULL_START, OOS_END)
ntr = (d['trade'] > 1e-12).groupby(d.index.year).sum()
print('\nF1 spot: days with an order per calendar year:', ntr.to_dict())
dd = sl(runs['F1 spot'], OOS_START, OOS_END)
print('F1 spot OOS: orders/yr = %.1f, median |trade| = %.3f of equity' % (
    (dd['trade'] > 1e-12).sum() / (len(dd) / 365.25), dd.loc[dd['trade'] > 1e-12, 'trade'].median()))

# calendar-year returns: F1 spot vs static 0.40
cy = pd.DataFrame({k: (1 + sl(runs[k], FULL_START, OOS_END)['r']).groupby(sl(runs[k], FULL_START, OOS_END).index.year).prod() - 1
                   for k in ['F1 spot', 'static w=0.40', 'BH spot (w=1)']})
print('\ncalendar-year returns (%):\n', (cy * 100).round(1).to_string())

# block bootstrap of F1 spot: P(MDD <= -30%) and P(MDD <= -20%) over 1y / 3y, full-period daily returns
rng = np.random.default_rng(20261107)
r = sl(runs['F1 spot'], FULL_START, OOS_END)['r'].values
for yrs in [1, 3]:
    n = 365 * yrs
    idx = cbb_idx(len(r), 20, 10000, rng)
    # cbb_idx returns n=len(r) columns; tile to horizon
    reps = int(np.ceil(n / len(r)))
    paths = r[np.concatenate([idx] * reps, axis=1)[:, :n]]
    eq = np.cumprod(1 + paths, axis=1)
    peak = np.maximum.accumulate(np.concatenate([np.ones((len(eq), 1)), eq], axis=1), axis=1)[:, 1:]
    mdd = (eq / peak - 1).min(axis=1)
    print(f'F1 spot bootstrap {yrs}y: median MDD {np.median(mdd)*100:.1f}%, P(MDD<=-20%) {np.mean(mdd<=-0.20)*100:.0f}%, '
          f'P(MDD<=-30%) {np.mean(mdd<=-0.30)*100:.0f}%, P(loss) {np.mean(eq[:,-1]<1)*100:.0f}%, '
          f'median CAGR {(np.median(eq[:,-1])**(1/yrs)-1)*100:.1f}%')
# also with mean halved (conservative, like the note)
rc = r - r.mean() / 2
for yrs in [1, 3]:
    n = 365 * yrs
    idx = cbb_idx(len(rc), 20, 10000, rng)
    reps = int(np.ceil(n / len(rc)))
    paths = rc[np.concatenate([idx] * reps, axis=1)[:, :n]]
    eq = np.cumprod(1 + paths, axis=1)
    peak = np.maximum.accumulate(np.concatenate([np.ones((len(eq), 1)), eq], axis=1), axis=1)[:, 1:]
    mdd = (eq / peak - 1).min(axis=1)
    print(f'F1 spot bootstrap (mean halved) {yrs}y: median MDD {np.median(mdd)*100:.1f}%, P(MDD<=-30%) {np.mean(mdd<=-0.30)*100:.0f}%, '
          f'P(loss) {np.mean(eq[:,-1]<1)*100:.0f}%, median CAGR {(np.median(eq[:,-1])**(1/yrs)-1)*100:.1f}%')

# 3-month paper-trading window: how many 3-month windows (OOS) had F1 spot fully in cash, or < 3 orders?
d = sl(runs['F1 spot'], FULL_START, OOS_END)
roll_orders = (d['trade'] > 1e-12).astype(int).rolling(91).sum()
roll_inmkt = d['inmkt'].rolling(91).mean()
print('\n91-day windows: share with <=2 orders: %.0f%%, share fully in cash: %.0f%%, min orders %d, median orders %d' % (
    (roll_orders.dropna() <= 2).mean() * 100, (roll_inmkt.dropna() == 0).mean() * 100, roll_orders.min(), roll_orders.median()))
