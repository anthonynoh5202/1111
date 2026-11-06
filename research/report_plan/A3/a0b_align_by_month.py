"""A0b. metrics 시각 규칙을 월별로 확인 (시차 0분 = 구간 시작 표시, 5분 = 구간 끝 표시)."""
import numpy as np, pandas as pd
D = "/home/user/1111/data/binance/"
m = pd.read_csv(D + "BTCUSDT_metrics.csv.gz", usecols=["create_time", "sum_taker_long_short_vol_ratio"])
m["t"] = pd.to_datetime(m["create_time"], utc=True)
m = m.drop_duplicates("t").set_index("t")["sum_taker_long_short_vol_ratio"].astype(float)
k = pd.read_csv(D + "BTCUSDT_5m.csv.gz", usecols=["open_time", "volume", "taker_buy_volume"])
k["t"] = pd.to_datetime(k["open_time"], unit="ms", utc=True)
k = k.set_index("t"); k = k[k.index >= "2021-11-30"]
r = (k["taker_buy_volume"] / (k["volume"] - k["taker_buy_volume"]))
out = {}
for lag in [0, 5]:
    kk = r.copy(); kk.index = kk.index + pd.Timedelta(minutes=lag)
    j = pd.concat([m.rename("m"), kk.rename("k")], axis=1, join="inner").dropna()
    j = j[(j.m > 0) & (j.k > 0) & np.isfinite(j.k)]
    hit = ((j.m / j.k - 1).abs() < 0.001)
    out[f"exact_lag{lag}"] = hit.groupby(j.index.strftime("%Y-%m")).mean()
o = pd.DataFrame(out).round(3)
print(o.to_string())
