"""Extra checks: (1) paired bootstrap of spot-implemented long-only rules vs BH-SPOT,
(2) Calmar / MaxDD comparison counts, (3) yearly funding paid by BH-PERP."""
import pickle
import numpy as np
import pandas as pd
from common import (OUT, IS_START, IS_END, OOS_START, OOS_END, FULL_START, load_klines, bar_inputs, run_engine,
                    to_daily, sl, cbb_idx, metrics)

T = pickle.load(open(f'{OUT}/targets.pkl', 'rb'))
D = pickle.load(open(f'{OUT}/daily_results.pkl', 'rb'))['res']['base']
d1 = load_klines('1d')
ret_nf, F_nf = bar_inputs('1d', with_funding=False)
names = ['B1 SMA50-LO', 'B2 SMA100-LO', 'A5 TSMOM90-LO', 'F1 COMBO-LO', 'D3 VT-SMA100-LO']
spot = {}
for k in names:
    tgt = np.minimum(T[k][1].shift(1).fillna(0.0).values, 1.0)
    spot[k] = to_daily(d1.index, run_engine(tgt, ret_nf, F_nf, 0.0012))
rng = np.random.default_rng(99)
rows = []
for w, (a, b) in {'IS': (IS_START, IS_END), 'OOS': (OOS_START, OOS_END)}.items():
    R = np.column_stack([sl(D['BH-SPOT'], a, b)['r'].values] + [sl(spot[k], a, b)['r'].values for k in names])
    idx = cbb_idx(len(R), 20, 5000, rng)
    SR = np.empty((5000, R.shape[1]))
    for s in range(0, 5000, 500):
        X = R[idx[s:s + 500]]
        SR[s:s + 500] = X.mean(1) / X.std(1, ddof=1) * np.sqrt(365)
    sr0 = R.mean(0) / R.std(0, ddof=1) * np.sqrt(365)
    d = SR[:, 1:] - SR[:, [0]]
    d0 = sr0[1:] - sr0[0]
    Tmax = (d - d0).max(axis=1)
    for j, k in enumerate(names):
        rows.append(dict(win=w, name=k + ' (spot)', SR=sr0[j + 1], SR_BH=sr0[0], dSR=d0[j],
                         lo=np.percentile(d[:, j], 2.5), hi=np.percentile(d[:, j], 97.5),
                         p=((d[:, j] - d0[j]) >= d0[j]).mean(), padj=(Tmax >= d0[j]).mean()))
sp = pd.DataFrame(rows)
sp.to_csv(f'{OUT}/spot_vs_bh_boot.csv', index=False)
pd.set_option('display.width', 200)
print(sp.round(3).to_string())

f = pd.read_csv('/home/user/1111/data/binance/BTCUSDT_fundingRate.csv.gz')
t = pd.to_datetime(f.calc_time, unit='ms', utc=True)
print('funding sum by year (% of notional, actual data):', (f.last_funding_rate.groupby(t.dt.year).sum() * 100).round(1).to_dict())
bp = D['BH-PERP']
print('BH-PERP funding paid by year (% of equity):', (bp['fund'].groupby(bp.index.year).sum() * 100).round(1).to_dict())
