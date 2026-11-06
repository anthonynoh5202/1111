"""A2d. 사후 탐색(결과를 본 뒤 고른 것): '숏 쏠림' 지표 → 다음 24h 수익률. Newey-West t (L=72). 판정 가족에 넣지 않는다."""
import numpy as np, pandas as pd
from common import OUT, period_mask, ols_nw
df = pd.read_pickle(OUT + "hourly_plus.pkl")
pre = (df.index >= pd.Timestamp("2020-02-01", tz="UTC")) & (df.index <= pd.Timestamp("2021-11-29", tz="UTC"))
masks = {"P0": pre, "IS": period_mask(df.index, "IS", 24), "OOS": period_mask(df.index, "OOS", 24)}
ism = masks["IS"]
q05g = df.loc[ism, "ls_global_z"].quantile(0.05); q05a = df.loc[ism, "ls_topacc_z"].quantile(0.05)
ind = {"펀딩 음수": df["fund_last"] < 0, "전체롱숏z 하위5%": df["ls_global_z"] <= q05g,
       "탑계정롱숏z 하위5%": df["ls_topacc_z"] <= q05a}
nan_src = {"펀딩 음수": "fund_last", "전체롱숏z 하위5%": "ls_global_z", "탑계정롱숏z 하위5%": "ls_topacc_z"}
rows = []
for name, s in ind.items():
    for p, m in masks.items():
        d = pd.DataFrame({"x": s.astype(float), "y": df["y_24"]})[m & df[nan_src[name]].notna()].dropna()
        if len(d) < 1000 or d.x.sum() < 50:
            continue
        X = np.column_stack([np.ones(len(d)), d.x]); b, t = ols_nw(d.y.to_numpy(), X, 72)
        # 에피소드 수: 지표가 켜진 연속 구간 수
        ep = int(((d.x == 1) & (d.x.shift(1, fill_value=0) == 0)).sum())
        rows.append(dict(indicator=name, period=p, hours_on=int(d.x.sum()), episodes=ep, diff_bp=b[1] * 1e4, t_nw=t[1]))
print(pd.DataFrame(rows).round(2).to_string(index=False))
