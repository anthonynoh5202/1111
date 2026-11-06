"""A1. 1시간 결정 시각(T = 1시간봉 마감) 격자에 특징과 목표값을 만든다 → hourly.pkl

특징(모두 T 이전 정보만):
- 가격: ret_past_{1,4,24}h (참고용 '가격만' 특징)
- 펀딩: fund_last(마지막 정산값), fund_avg3d(최근 9회 평균), fund_pct90(3일 평균의 최근 90일 백분위)
- OI: doi_{1,4,24}h = 코인 수량 기준 미결제약정 변화율 (metrics, T-5분 이전 표시분)
- 테이커: tbr_{1,4,24}h = 테이커 매수량 / 거래량 (klines), tbr_resid_1h = 같은 봉 가격 변화로 설명 안 되는 부분
- 롱숏: ls_topacc_z, ls_toppos_z, ls_global_z = log 비율의 최근 30일 z점수
- 변동성: atr_pct(4시간봉 ATR14 / 종가), atr_rank(최근 180일 백분위)
목표(T 이후):
- y_{1,4,24}: 다음 1·4·24시간 로그 수익률, rv_next_{4,24}: 다음 4·24시간 실현 변동성(5분 수익률 제곱합의 제곱근)
"""
import numpy as np
import pandas as pd

from common import (OUT, IS_START, IS_END, asof_on_grid, load_funding, load_klines, load_metrics)

H1 = pd.Timedelta(hours=1)

# ---------------- 1시간봉 ----------------
h = load_klines("1h")
h.index = h.index + H1          # index = 결정 시각 T (봉 마감)
h.index.name = "T"
grid = h.index
assert (pd.Series(grid).diff().dropna() == H1).all(), "1h grid has gaps"
lc = np.log(h["close"])
df = pd.DataFrame(index=grid)
df["close"] = h["close"]
df["quote_vol"] = h["quote_volume"]
df["volume"] = h["volume"]
df["range_pct"] = (h["high"] - h["low"]) / h["open"]
for n in (1, 4, 24, 168):
    df[f"ret_past_{n}h"] = lc - lc.shift(n)
for n in (1, 4, 24):
    df[f"y_{n}"] = lc.shift(-n) - lc

# ---------------- 5분봉 → 시간별 실현 분산 ----------------
k5 = load_klines("5m", cols=["open_time", "close"])
r5 = np.log(k5["close"]).diff()
rvh = (r5 ** 2).groupby(k5.index.floor("h")).sum()
rvh.index = rvh.index + H1       # 5분봉 open in [T-1h, T) → T
rvh = rvh.reindex(grid)
df["rv_1h"] = np.sqrt(rvh)
for n in (4, 24, 168):
    s = rvh.rolling(n).sum()
    df[f"rv_past_{n}"] = np.sqrt(s)
for n in (4, 24):
    s = rvh.rolling(n).sum().shift(-n)     # 시간 [T, T+n)
    df[f"rv_next_{n}"] = np.sqrt(s)

# ---------------- 테이커 매수 비율 ----------------
tb = h["taker_buy_volume"]; vol = h["volume"]
df["tbr_1h"] = tb / vol
df["tbr_4h"] = tb.rolling(4).sum() / vol.rolling(4).sum()
df["tbr_24h"] = tb.rolling(24).sum() / vol.rolling(24).sum()

# ---------------- 펀딩 ----------------
f = load_funding()
fs = pd.DataFrame({"fund_last": f, "fund_avg3d": f.rolling(9).mean()})
fs["fund_pct90"] = fs["fund_avg3d"].rolling(270, min_periods=200).rank(pct=True)
fg = asof_on_grid(fs, grid, lag=pd.Timedelta(0), tolerance=pd.Timedelta(hours=9))
df = df.join(fg)

# ---------------- metrics (OI·롱숏) : T-5분 이전 표시분만 ----------------
m = load_metrics()
mg = asof_on_grid(m, grid, lag=pd.Timedelta(minutes=5), tolerance=pd.Timedelta(minutes=30))
oi = mg["sum_open_interest"]
df["oi"] = oi
for n in (1, 4, 24):
    df[f"doi_{n}h"] = oi / oi.shift(n) - 1
for col, name in [("count_toptrader_long_short_ratio", "ls_topacc"),
                  ("sum_toptrader_long_short_ratio", "ls_toppos"),
                  ("count_long_short_ratio", "ls_global")]:
    x = np.log(mg[col].where(mg[col] > 0))
    df[name] = mg[col]
    mu = x.rolling(720, min_periods=360).mean(); sd = x.rolling(720, min_periods=360).std()
    df[f"{name}_z"] = (x - mu) / sd

# ---------------- 4시간봉 ATR ----------------
q = load_klines("4h")
q.index = q.index + pd.Timedelta(hours=4); q.index.name = "T"
pc = q["close"].shift(1)
tr = pd.concat([q["high"] - q["low"], (q["high"] - pc).abs(), (q["low"] - pc).abs()], axis=1).max(axis=1)
atr = tr.rolling(14).mean()
qa = pd.DataFrame({"atr4h": atr, "atr_pct": atr / q["close"]})
qa["atr_rank"] = qa["atr_pct"].rolling(1080, min_periods=540).rank(pct=True)
df = df.join(asof_on_grid(qa, grid, lag=pd.Timedelta(0), tolerance=pd.Timedelta(hours=4)))

# ---------------- 테이커 잔차 (IS에서만 적합) ----------------
sd1 = df["ret_past_1h"].rolling(168, min_periods=100).std()
z = (df["ret_past_1h"] / sd1).clip(-6, 6)
ism = (df.index >= IS_START) & (df.index < IS_END)
X = np.column_stack([np.ones(len(df)), z, z ** 3])
ok = ism & np.isfinite(X).all(axis=1) & df["tbr_1h"].notna().to_numpy()
b = np.linalg.lstsq(X[ok], df["tbr_1h"].to_numpy()[ok], rcond=None)[0]
df["tbr_resid_1h"] = df["tbr_1h"] - X @ b
print("tbr_1h ~ 1 + z + z^3 (IS):", np.round(b, 5),
      "R2=", round(1 - np.nanvar(df.loc[ok, "tbr_resid_1h"]) / np.nanvar(df.loc[ok, "tbr_1h"]), 3))

# ---------------- 시간 ----------------
kst_open = df.index - H1 + pd.Timedelta(hours=9)     # 방금 마감된 봉의 KST 시작 시각
df["bar_hour_kst"] = kst_open.hour
df["dec_hour_kst"] = (df.index + pd.Timedelta(hours=9)).hour
df["dow_kst"] = (df.index + pd.Timedelta(hours=9)).dayofweek   # 결정 시각 기준 요일 (0=월)

df = df[df.index >= pd.Timestamp("2020-01-08", tz="UTC")]
df.to_pickle(OUT + "hourly.pkl")
print(df.shape)
print(df.loc["2021-12-01":].describe().T[["count", "mean", "std", "min", "max"]].to_string())
