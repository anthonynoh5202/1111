"""A0. metrics(5분) 타임스탬프 정렬 확인.

질문: metrics의 create_time t 값은 [t-5m, t) 구간(끝 시각 표시)인가, [t, t+5m) 구간(시작 시각 표시)인가?
방법: metrics의 테이커 매수/매도 비율(sum_taker_long_short_vol_ratio)과
      5분봉에서 직접 계산한 taker_buy / (volume - taker_buy)를 시차별로 비교한다.
      가장 잘 맞는 시차가 metrics 시각의 뜻이다. (시간대가 KST라면 9시간 시차에서 맞을 것)
또 null 셀이 어디에 몰려 있는지 본다.
"""
import sys
import numpy as np
import pandas as pd

D = "/home/user/1111/data/binance/"

m = pd.read_csv(D + "BTCUSDT_metrics.csv.gz")
m["t"] = pd.to_datetime(m["create_time"], utc=True)
m = m.drop_duplicates("t").set_index("t").sort_index()
print("metrics rows", len(m), m.index.min(), m.index.max())

k = pd.read_csv(D + "BTCUSDT_5m.csv.gz", usecols=["open_time", "volume", "taker_buy_volume"])
k["t"] = pd.to_datetime(k["open_time"], unit="ms", utc=True)
k = k.set_index("t")
k = k[k.index >= "2021-11-30"]
k["ratio"] = k["taker_buy_volume"] / (k["volume"] - k["taker_buy_volume"])

mr = m["sum_taker_long_short_vol_ratio"].astype(float)
res = []
for lag_min in [-10, -5, 0, 5, 10, 540, -540]:
    # kline open_time + lag = metrics time  → metrics(t) vs kline(open = t - lag)
    kk = k["ratio"].copy()
    kk.index = kk.index + pd.Timedelta(minutes=lag_min)
    j = pd.concat([mr.rename("m"), kk.rename("k")], axis=1, join="inner").dropna()
    j = j[(j["m"] > 0) & (j["k"] > 0) & np.isfinite(j["k"])]
    rel = (j["m"] / j["k"] - 1).abs()
    res.append((lag_min, len(j), np.corrcoef(np.log(j["m"]), np.log(j["k"]))[0, 1], (rel < 0.001).mean(), (rel < 0.02).mean()))
print("lag_min = metrics_time - kline_open_time")
print(pd.DataFrame(res, columns=["lag_min", "n", "corr_log", "share_|rel|<0.1%", "share_|rel|<2%"]).to_string(index=False))

# null 분포 (연-월별)
cols = ["count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
        "count_long_short_ratio", "sum_taker_long_short_vol_ratio", "sum_open_interest"]
nul = m[cols].isna().groupby(m.index.to_period("M")).mean()
print("\nnull share by month (only months with any null > 1%):")
print(nul[(nul > 0.01).any(axis=1)].round(3).to_string())

# 5분 간격 확인
dt = m.index.to_series().diff().dt.total_seconds().div(60)
print("\ninterval minutes value counts (top):")
print(dt.value_counts().head(8))
