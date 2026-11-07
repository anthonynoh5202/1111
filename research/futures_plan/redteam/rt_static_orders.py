import numpy as np, pandas as pd
from common import load_klines, bar_inputs, run_engine, to_daily, metrics, sl, FULL_START, OOS_START, OOS_END, IS_START, IS_END
d1 = load_klines('1d'); ret_nf, F_nf = bar_inputs('1d', with_funding=False)
mask = (d1.index >= FULL_START)
st = to_daily(d1.index, run_engine(np.full(len(d1), 0.40) * mask, ret_nf, F_nf, 0.0012))
d = sl(st, FULL_START, OOS_END)
print('static40 (10% band) order days per year:', (d['trade'] > 1e-12).groupby(d.index.year).sum().to_dict())
# quarterly calendar rebalancing to 40% (no band): simulate manually
r = ret_nf.copy(); idx = d1.index
w = 0.0; eq = 1.0; out = []; n_tr = 0
for i in range(len(r)):
    if idx[i] < FULL_START: out.append(0.0); continue
    first = (len(out) == 0) or idx[i].month in (1, 4, 7, 10) and idx[i].day == 1
    if w == 0.0 or first:
        tr = abs(0.40 - w); w = 0.40; n_tr += tr > 1e-12
    else:
        tr = 0.0
    c = tr * 0.0012
    ri = w * r[i] - c
    out.append(ri)
    w = w * (1 + r[i]) / (1 + ri)
q = pd.Series(out, index=idx)
for name, (a, b) in {'FULL': (FULL_START, OOS_END), 'IS': (IS_START, IS_END), 'OOS': (OOS_START, OOS_END)}.items():
    x = q[(q.index >= a) & (q.index <= b)].values
    yrs = len(x) / 365.25; tot = np.prod(1 + x); eqc = np.cumprod(1 + x); mdd = (eqc / np.maximum.accumulate(eqc) - 1).min()
    print(f'static40 quarterly-rebal {name}: CAGR {(tot**(1/yrs)-1)*100:.1f}% Sharpe {x.mean()/x.std(ddof=1)*np.sqrt(365):.2f} MDD {mdd*100:.1f}%')
