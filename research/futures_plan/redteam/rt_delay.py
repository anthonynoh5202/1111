"""Execution-delay sensitivity of spot F1 (signal at 00:00 UTC daily close, fill delta hours later),
plus bootstrap risk/KRW P&L for spot F1 vs a static 40% BTC mix (same method as the note: 20-day blocks)."""
import numpy as np, pandas as pd
from common import load_klines, bar_inputs, run_engine, to_daily, metrics, sl, cbb_idx, IS_START, IS_END, OOS_START, OOS_END, FULL_START
from strategies import build_all
S = build_all()
d1 = load_klines('1d'); h1 = load_klines('1h')
COST = 0.0012
sig = np.minimum(S['F1 COMBO-LO'][2].fillna(0.0), 1.0)     # decision at close of day t (known 00:00 UTC of t+1)
rows = []
for dh in [0, 3, 9, 12]:
    t_exec = d1.index + pd.Timedelta(hours=dh)               # fill time for "day" i: 00:00+dh UTC
    o = h1['open'].reindex(t_exec).values
    ok = ~np.isnan(o)
    o = o[ok]; idx = d1.index[ok]
    ret = np.empty(len(o)); ret[:-1] = o[1:] / o[:-1] - 1; ret[-1] = 0.0
    tgt = sig.shift(1).reindex(idx).fillna(0.0).values * (idx >= FULL_START)
    dd = to_daily(idx, run_engine(tgt, ret, np.zeros(len(o)), COST))
    for w, (a, b) in {'FULL': (FULL_START, OOS_END), 'OOS': (OOS_START, OOS_END), 'IS': (IS_START, IS_END)}.items():
        m = metrics(sl(dd, a, b))
        rows.append(dict(delay_h=dh, kst=f'{(9+dh)%24:02d}:00', win=w, CAGR=round(m['CAGR']*100, 1), Sharpe=round(m['Sharpe'], 2), MDD=round(m['MaxDD']*100, 1)))
print(pd.DataFrame(rows).pivot_table(index=['delay_h', 'kst'], columns='win', values=['CAGR', 'Sharpe', 'MDD']).to_string())

# ---- bootstrap: spot F1 vs static 40% (full-period daily returns; and OOS-only; and full with mean halved)
ret_nf, F_nf = bar_inputs('1d', with_funding=False)
mask = (d1.index >= FULL_START)
f1 = to_daily(d1.index, run_engine(np.minimum(S['F1 COMBO-LO'][2].shift(1).fillna(0.0).values, 1.0) * mask, ret_nf, F_nf, COST))
st = to_daily(d1.index, run_engine(np.full(len(d1), 0.40) * mask, ret_nf, F_nf, COST))
bh = to_daily(d1.index, run_engine(np.ones(len(d1)) * mask, ret_nf, F_nf, COST))
rng = np.random.default_rng(7)
def boot(r, yrs, n_paths=10000):
    n = int(365 * yrs)
    idx = cbb_idx(len(r), 20, n_paths, rng)
    reps = int(np.ceil(n / len(r)))
    p = r[np.concatenate([idx] * reps, axis=1)[:, :n]]
    eq = np.cumprod(1 + p, axis=1)
    pk = np.maximum.accumulate(np.concatenate([np.ones((len(eq), 1)), eq], axis=1), axis=1)[:, 1:]
    return eq[:, -1], (eq / pk - 1).min(axis=1)
out = []
for name, d in [('F1 spot', f1), ('static 40%', st), ('BH spot 100%', bh)]:
    for scen, (a, b, half) in {'OOS-resample': (OOS_START, OOS_END, False), 'FULL': (FULL_START, OOS_END, False), 'FULL mean/2': (FULL_START, OOS_END, True)}.items():
        r = sl(d, a, b)['r'].values
        if half: r = r - r.mean() / 2
        e1, m1 = boot(r, 1); e3, m3 = boot(r, 3)
        out.append(dict(name=name, scen=scen,
                        med1y=f'{(np.median(e1)-1)*1000:.0f}만', p5_1y=f'{(np.percentile(e1,5)-1)*1000:.0f}만', p95_1y=f'{(np.percentile(e1,95)-1)*1000:.0f}만',
                        ploss1y=f'{np.mean(e1<1)*100:.0f}%',
                        mdd3y_med=f'{np.median(m3)*100:.0f}%', mdd3y_p10=f'{np.percentile(m3,10)*100:.0f}%', mdd3y_p5=f'{np.percentile(m3,5)*100:.0f}%',
                        P3y_mdd30=f'{np.mean(m3<=-0.30)*100:.0f}%', P3y_mdd50=f'{np.mean(m3<=-0.50)*100:.0f}%'))
pd.set_option('display.width', 250)
print('\n(1,000만 원 기준 1년 손익; 3년 최대낙폭 분포)\n', pd.DataFrame(out).to_string(index=False))
