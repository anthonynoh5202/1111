"""A4. 시간대 효과: KST 시간별 거래량·변동성·수익률, 요일·주말, 미국 지표(08:30 ET) 슬롯, FOMC 발표일.

- 상대 거래량/변동성 = 그 시간 값 ÷ 같은 KST 날짜 24시간 평균 (추세·국면 영향 제거, 설명용이라 미래 정보 문제 없음)
- 기간: P0 2020-01~2021-11, IS 2021-12~2023-12, OOS 2024-01~2026-09
- 수익률의 시간대 패턴은 24개를 한꺼번에 보면 우연히 2~3개는 |t|>2가 나온다 → IS·OOS 시간대 평균의 상관으로 '지속되는 패턴인지'만 본다.
- FOMC 발표일(둘째 날 14:00 ET) 목록: 연준 공표 일정(검색 결과로 대조).
"""
import numpy as np
import pandas as pd

from common import OUT, load_klines

pd.set_option("display.width", 250)
H1 = pd.Timedelta(hours=1)

def period_of(ts: pd.DatetimeIndex) -> np.ndarray:
    return np.where(ts < pd.Timestamp("2021-12-01", tz="UTC"), "P0",
                    np.where(ts < pd.Timestamp("2024-01-01", tz="UTC"), "IS", "OOS"))

# ---------------- 1시간봉 프로파일 ----------------
h = load_klines("1h")
k5 = load_klines("5m", cols=["open_time", "close", "volume"])
r5 = np.log(k5["close"]).diff()
rvh = (r5 ** 2).groupby(k5.index.floor("h")).sum().reindex(h.index)
d = pd.DataFrame(index=h.index)          # index = 봉 시작(UTC)
d["qv"] = h["quote_volume"]; d["rv"] = np.sqrt(rvh)
d["ret"] = np.log(h["close"] / h["open"])
d["absret"] = d["ret"].abs()
kst = d.index + pd.Timedelta(hours=9)
d["kst_hour"] = kst.hour; d["kst_date"] = kst.normalize(); d["kst_dow"] = kst.dayofweek
d["period"] = period_of(d.index)
ny = d.index.tz_convert("America/New_York")
d["us_dst"] = ((ny.tz_localize(None) - d.index.tz_convert(None)) == pd.Timedelta(hours=-4))   # EDT(UTC-4)=여름
for c in ("qv", "rv"):
    d[f"rel_{c}"] = d[c] / d.groupby("kst_date")[c].transform("mean")
d = d[d.groupby("kst_date")["qv"].transform("size") == 24]

prof = d.groupby(["period", "kst_hour"])[["rel_qv", "rel_rv"]].mean().unstack(0)
print("=== KST 시간별 상대 거래량·변동성 (1.00 = 그날 평균) ===")
print(prof.round(2).to_string())
prof.to_csv(OUT + "a4_hour_profile.csv")

# 써머타임(미국) 여부별 — 미국 장 관련 시간이 1시간 이동하는지
sw = d[d.period != "P0"].groupby(["us_dst", "kst_hour"])[["rel_qv", "rel_rv"]].mean().unstack(0)
print("\n=== 미국 써머타임(True=여름) 여부별 상대 거래량·변동성 (2021-12~) ===")
print(sw.round(2).to_string())
sw.to_csv(OUT + "a4_hour_profile_dst.csv")

# 시간대별 평균 수익률 (bp)과 t, IS·OOS 프로파일 상관
rr = d.groupby(["period", "kst_hour"])["ret"].agg(["mean", "std", "count"])
rr["t"] = rr["mean"] / (rr["std"] / np.sqrt(rr["count"]))
rr["bp"] = rr["mean"] * 1e4
tab = rr[["bp", "t"]].unstack(0)
print("\n=== KST 시간별 평균 1시간 수익률(bp)·t ===")
print(tab.round(2).to_string())
for a, b in (("P0", "IS"), ("IS", "OOS"), ("P0", "OOS")):
    x = rr.loc[a, "mean"]; y = rr.loc[b, "mean"]
    print(f"시간대 평균수익률 프로파일 상관 {a}~{b}: {np.corrcoef(x, y)[0,1]:+.3f}")
for p in ("P0", "IS", "OOS"):
    print(p, "|t|>2인 시간 수:", int((rr.loc[p, "t"].abs() > 2).sum()), "/ 24 (우연 기대 약 1.1개)")
tab.to_csv(OUT + "a4_hour_returns.csv")

# 시간대 묶음별 '1시간 움직임이 이어지나 되돌리나' (IC: 이번 1시간 수익률 vs 다음 4시간)
lc = np.log(h["close"])
nxt4 = (lc.shift(-4) - lc).reindex(d.index)        # 봉 마감 기준 다음 4시간 (봉 시작 index → 마감은 +1h; close 기준이므로 shift)
d["y4"] = nxt4
def grp(hk):
    if 9 <= hk < 15: return "A 아시아 낮(09-15)"
    if 15 <= hk < 21: return "B 유럽(15-21)"
    if hk >= 21 or hk < 3: return "C 미국(21-03)"
    return "D 새벽(03-09)"
d["grp"] = d["kst_hour"].map(grp)
rows = []
for (p, g), x in d.dropna(subset=["y4"]).groupby(["period", "grp"]):
    ic = x["ret"].rank().corr(x["y4"].rank())
    rows.append(dict(period=p, group=g, n=len(x), ic_ret1h_next4h=ic, t_approx=ic * np.sqrt(len(x) / 4)))
gi = pd.DataFrame(rows)
print("\n=== 시간대 묶음별: 이번 1시간 수익률 → 다음 4시간 (순위 상관, 음수 = 되돌림) ===")
print(gi.pivot_table(index="group", columns="period", values="ic_ret1h_next4h").round(3).to_string())
gi.to_csv(OUT + "a4_group_reversal.csv", index=False)

# ---------------- 요일 ----------------
dd = pd.DataFrame({"qv": h["quote_volume"].resample("1D").sum(), "rv": np.sqrt((r5 ** 2).resample("1D").sum())})
dd["ret"] = np.log(h["close"].resample("1D").last() / h["open"].resample("1D").first())
dd = dd[dd.index < pd.Timestamp("2026-09-29", tz="UTC")]
dd["dow"] = dd.index.dayofweek      # UTC 날짜 = KST 09:00~다음날 09:00 (일봉과 같음)
dd["period"] = period_of(dd.index)
wk = dd.index.to_period("W")
for c in ("qv", "rv"):
    dd[f"rel_{c}"] = dd[c] / dd.groupby(wk)[c].transform("mean")
dw = dd.groupby(["period", "dow"]).agg(rel_qv=("rel_qv", "mean"), rel_rv=("rel_rv", "mean"),
                                        ret_bp=("ret", lambda x: x.mean() * 1e4),
                                        t=("ret", lambda x: x.mean() / (x.std() / np.sqrt(len(x)))),
                                        up=("ret", lambda x: (x > 0).mean()), n=("ret", "size"))
print("\n=== 요일별 (일봉 기준, 0=월 ... 6=일; 하루 = KST 09:00~다음날 09:00) ===")
print(dw.round(3).to_string())
dw.to_csv(OUT + "a4_dow.csv")

# ---------------- 5분 슬롯 (미국 동부시각 기준) ----------------
z = pd.DataFrame({"r2": r5 ** 2, "vol": k5["volume"]}).dropna()
z = z[z.index >= pd.Timestamp("2021-12-01", tz="UTC")]
et = z.index.tz_convert("America/New_York")
z["et_slot"] = et.hour * 60 + et.minute
z["et_wd"] = et.dayofweek < 5
z["et_date"] = et.normalize().tz_localize(None)
z["rel_r2"] = z["r2"] / z.groupby("et_date")["r2"].transform("mean")
z["rel_vol"] = z["vol"] / z.groupby("et_date")["vol"].transform("mean")
slot = z.groupby(["et_wd", "et_slot"])[["rel_r2", "rel_vol"]].mean().unstack(0)
slot.columns = [f"{a}_{'평일' if b else '주말'}" for a, b in slot.columns]
top = slot.sort_values("rel_r2_평일", ascending=False).head(12)
def fmt(m):
    return f"{m//60:02d}:{m%60:02d}"
top.index = [f"ET {fmt(m)} (KST 여름 {fmt((m+13*60)%1440)} / 겨울 {fmt((m+14*60)%1440)})" for m in top.index]
print("\n=== 평일 5분 변동성(분산) 상위 슬롯 (1.00 = 그날 평균 5분) ===")
print(top.round(2).to_string())
key = [8*60+30, 8*60+35, 9*60+30, 10*60, 14*60, 14*60+30, 16*60]
ks = slot.loc[key].copy(); ks.index = [f"ET {fmt(m)}" for m in key]
print("\n=== 주요 슬롯 ===")
print(ks.round(2).to_string())
slot.to_csv(OUT + "a4_et_slots.csv")

# 08:30 ET 슬롯: 금요일 첫째 주(고용지표 추정) vs 다른 평일
z["fri1"] = (et.dayofweek == 4) & (et.day <= 7)
s830 = z[(z.et_slot == 8*60+30) & z.et_wd]
print("\n08:30 ET 5분 상대분산: 첫째 주 금요일(고용지표 추정) %.1f배, 그 밖 평일 %.1f배, 주말 같은 시각 %.1f배" % (
    s830[s830.fri1].rel_r2.mean(), s830[~s830.fri1].rel_r2.mean(),
    z[(z.et_slot == 8*60+30) & ~z.et_wd].rel_r2.mean()))

# ---------------- FOMC 발표일 ----------------
fomc = ["2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
        "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14", "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
        "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
        "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
        "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16"]
fdates = set(pd.to_datetime(fomc))
z["fomc"] = z["et_date"].isin(fdates)
wins = {"발표 전 2시간(12:00-14:00)": (12*60, 14*60), "발표~30분(14:00-14:30)": (14*60, 14*60+30),
        "기자회견(14:30-15:30)": (14*60+30, 15*60+30), "그 뒤(15:30-20:00)": (15*60+30, 20*60)}
rows = []
wd = z[z.et_wd]
for name, (a, b) in wins.items():
    w = wd[(wd.et_slot >= a) & (wd.et_slot < b)]
    # 날짜별 창 안 분산 합 ÷ 그날 평균 5분 분산 × 창 길이(슬롯 수) → 창의 상대 분산
    g = w.groupby(["et_date", "fomc"])["rel_r2"].mean().reset_index()
    f, nf = g[g.fomc]["rel_r2"], g[~g.fomc]["rel_r2"]
    rows.append(dict(window=name, fomc_days=len(f), fomc_rel=f.mean(), fomc_med=f.median(), other_rel=nf.mean(),
                     other_med=nf.median(), ratio_mean=f.mean() / nf.mean(), ratio_median=f.median() / nf.median()))
fo = pd.DataFrame(rows)
print("\n=== FOMC 발표일 vs 다른 평일 (5분 상대분산; KST로는 발표 = 여름 03:00 / 겨울 04:00) ===")
print(fo.round(2).to_string(index=False))
fo.to_csv(OUT + "a4_fomc.csv", index=False)
# FOMC 날 하루 전체 변동성(UTC 일 기준) vs 다른 평일
dd2 = dd[dd.index >= pd.Timestamp("2021-12-01", tz="UTC")].copy()
dd2["fomc_day"] = dd2.index.tz_convert(None).isin(list(fdates))
# UTC 날짜 D의 18~19시(=ET 14시)가 발표 → UTC 날짜 D 하루에 포함
print("FOMC 발표가 든 UTC 날짜의 일 변동성 ÷ 같은 주 평균: %.2f (다른 평일 %.2f), 일 |수익률| 평균 %.2f%% (다른 평일 %.2f%%)" % (
    dd2[dd2.fomc_day].rel_rv.mean(), dd2[(~dd2.fomc_day) & (dd2.dow < 5)].rel_rv.mean(),
    dd2[dd2.fomc_day].ret.abs().mean() * 100, dd2[(~dd2.fomc_day) & (dd2.dow < 5)].ret.abs().mean() * 100))
