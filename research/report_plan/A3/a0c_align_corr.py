"""A0c. 2025-08~2026-03 구간: 정확 일치가 낮은 달의 시차별 상관 (log 비율)."""
import numpy as np, pandas as pd
D = "/home/user/1111/data/binance/"
m = pd.read_csv(D + "BTCUSDT_metrics.csv.gz", usecols=["create_time", "sum_taker_long_short_vol_ratio"])
m["t"] = pd.to_datetime(m["create_time"], utc=True)
m = m.drop_duplicates("t").set_index("t")["sum_taker_long_short_vol_ratio"].astype(float)
k = pd.read_csv(D + "BTCUSDT_5m.csv.gz", usecols=["open_time", "volume", "taker_buy_volume"])
k["t"] = pd.to_datetime(k["open_time"], unit="ms", utc=True)
k = k.set_index("t"); k = k[k.index >= "2025-06-01"]
r = (k["taker_buy_volume"] / (k["volume"] - k["taker_buy_volume"]))
rows = {}
for lag in [-5, 0, 5, 10]:
    kk = r.copy(); kk.index = kk.index + pd.Timedelta(minutes=lag)
    j = pd.concat([m.rename("m"), kk.rename("k")], axis=1, join="inner").dropna()
    j = j[(j.m > 0) & (j.k > 0) & np.isfinite(j.k)]
    g = j.groupby(j.index.strftime("%Y-%m"))
    rows[f"corr_lag{lag}"] = g.apply(lambda x: np.corrcoef(np.log(x.m), np.log(x.k))[0, 1])
    rows[f"medrel_lag{lag}"] = g.apply(lambda x: (x.m / x.k - 1).abs().median())
print(pd.DataFrame(rows).round(3).to_string())
