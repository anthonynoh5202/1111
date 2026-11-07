import numpy as np, pandas as pd
from common import load_klines, bar_inputs, run_engine, to_daily, metrics, sl, cbb_idx, IS_START, IS_END, OOS_START, OOS_END, FULL_START
from strategies import build_all
S = build_all(); d1 = load_klines('1d'); ret_nf, F_nf = bar_inputs('1d', with_funding=False)
mask = (d1.index >= FULL_START); COST = 0.0012
f1 = to_daily(d1.index, run_engine(np.minimum(S['F1 COMBO-LO'][2].shift(1).fillna(0.0).values, 1.0) * mask, ret_nf, F_nf, COST))
rng = np.random.default_rng(11)
for w in [0.40, 0.45]:
    st = to_daily(d1.index, run_engine(np.full(len(d1), w) * mask, ret_nf, F_nf, COST))
    for win, (a, b) in {'FULL': (FULL_START, OOS_END), 'IS': (IS_START, IS_END), 'OOS': (OOS_START, OOS_END)}.items():
        R = np.column_stack([sl(f1, a, b)['r'].values, sl(st, a, b)['r'].values])
        idx = cbb_idx(len(R), 20, 5000, rng)
        X = R[idx]
        sr = X.mean(1) / X.std(1, ddof=1) * np.sqrt(365)
        d = sr[:, 0] - sr[:, 1]
        sr0 = R.mean(0) / R.std(0, ddof=1) * np.sqrt(365)
        d0 = sr0[0] - sr0[1]
        p = ((d - d0) >= d0).mean()
        print(f'static {w:.2f} {win}: F1 SR {sr0[0]:.2f} vs static {sr0[1]:.2f}, diff {d0:+.2f} [95% {np.percentile(d,2.5):+.2f}, {np.percentile(d,97.5):+.2f}], one-sided p={p:.2f}')
# excluding 2022
st = to_daily(d1.index, run_engine(np.full(len(d1), 0.40) * mask, ret_nf, F_nf, COST))
for lab, sel in {'FULL ex-2022': lambda x: x[(x.index.year != 2022)], '2022 only': lambda x: x[x.index.year == 2022]}.items():
    a = sel(sl(f1, FULL_START, OOS_END)); b_ = sel(sl(st, FULL_START, OOS_END))
    ma, mb = metrics(a), metrics(b_)
    print(f'{lab}: F1 CAGR {ma["CAGR"]*100:.1f}% SR {ma["Sharpe"]:.2f} MDD {ma["MaxDD"]*100:.0f}% | static40 CAGR {mb["CAGR"]*100:.1f}% SR {mb["Sharpe"]:.2f} MDD {mb["MaxDD"]*100:.0f}%')
# 2025-10-06 peak to 2026-07-01 trough window
a = f1.loc['2025-10-06':'2026-07-01']; b_ = st.loc['2025-10-06':'2026-07-01']
print('2025-10-06..2026-07-01: F1 %.1f%%, static40 %.1f%%' % ((np.prod(1+a.r)-1)*100, (np.prod(1+b_.r)-1)*100))
