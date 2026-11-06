"""A2c. 보강: (1) 펀딩비 절대 구간 (2) 극단 꼬리(IS 기준 상·하위 5%) (3) OI가 변동성 예측에 더하는 설명력 (4) 변동성 국면 표.
탐색용 표다. 판정은 a2/a2b의 가족 단위 규칙을 따른다(여기서 새로 '근거 있음'을 만들지 않는다).
"""
import numpy as np
import pandas as pd

from common import OUT, period_mask

pd.set_option("display.width", 250)
df = pd.read_pickle(OUT + "hourly_plus.pkl")
pre = (df.index >= pd.Timestamp("2020-02-01", tz="UTC")) & (df.index <= pd.Timestamp("2021-11-29", tz="UTC"))
masks = {"P0(2020-02~2021-11)": pre, "IS": period_mask(df.index, "IS", 24), "OOS": period_mask(df.index, "OOS", 24)}

# (1) 펀딩 절대 구간 (마지막 정산값, 8시간당)
def fcat(x):
    if not np.isfinite(x): return np.nan
    if x < 0: return "1 음수(<0)"
    if x < 0.0001 - 1e-9: return "2 0~0.01% 미만"
    if x <= 0.0001 + 1e-9: return "3 =0.01%(기본값)"
    if x <= 0.0003: return "4 0.01~0.03%"
    return "5 >0.03%(과열)"
df["fcat"] = df["fund_last"].map(fcat)
rows = []
for p, m in masks.items():
    d = df.loc[m].dropna(subset=["fcat", "y_24"])
    for c, g in d.groupby("fcat"):
        rows.append(dict(period=p, cat=c, n_hours=len(g), days=round(len(g) / 24, 1), y24_bp=g.y_24.mean() * 1e4,
                         up24=(g.y_24 > 0).mean(), y4_bp=g.y_4.mean() * 1e4, rv24=g.rv_next_24.mean() * 100))
fc = pd.DataFrame(rows)
print("=== 펀딩비 절대 구간별 다음 24h (bp, 상승 비율, 실현변동성 %) ===")
print(fc.round(3).to_string(index=False))
fc.to_csv(OUT + "a2c_funding_cat.csv", index=False)

# (2) 극단 꼬리
feats = ["fund_avg3d", "ls_global_z", "ls_topacc_z", "ls_toppos_z", "doi_24h", "tbr_24h", "atr_rank"]
rows = []
for f in feats:
    ism = masks["IS"]
    lo, hi = df.loc[ism, f].quantile([0.05, 0.95])
    for p in ("IS", "OOS"):
        d = df.loc[masks[p]].dropna(subset=[f, "y_24"])
        for name, sel in (("하위5%", d[f] <= lo), ("가운데90%", (d[f] > lo) & (d[f] < hi)), ("상위5%", d[f] >= hi)):
            g = d[sel]
            rows.append(dict(feature=f, period=p, tail=name, n=len(g), days_approx=round(g.index.normalize().nunique()),
                             y24_bp=g.y_24.mean() * 1e4, up24=(g.y_24 > 0).mean(),
                             surprise24_pct=(np.exp(g.rvres_24.mean()) - 1) * 100 if len(g) else np.nan))
tl = pd.DataFrame(rows)
print("\n=== 극단 꼬리 (IS 5%/95% 경계) ===")
print(tl.round(3).to_string(index=False))
tl.to_csv(OUT + "a2c_tails.csv", index=False)

# (3) OI 변화의 설명력 증가분 (IS 적합 → OOS 평가)
eps = 1e-5
for n in (4, 24):
    y = np.log(df[f"rv_next_{n}"] + eps)
    base = np.log(df[f"rvhat_{n}"] + eps)        # 기준 모델 예측(IS 적합)
    ism = period_mask(df.index, "IS", n); oos = period_mask(df.index, "OOS", n)
    X = pd.DataFrame({"b": base, "d4": df["doi_4h"].clip(-0.1, 0.1), "d24": df["doi_24h"].clip(-0.2, 0.2)})
    ok = X.notna().all(axis=1) & y.notna()
    A = np.column_stack([np.ones(ok.sum()), X[ok].to_numpy()])
    yi = y[ok].to_numpy()
    w_is = (ism & ok)[ok].to_numpy(); w_oos = (oos & ok)[ok].to_numpy()
    b = np.linalg.lstsq(A[w_is], yi[w_is], rcond=None)[0]
    pred = A @ b
    def r2(mask, yhat):
        return 1 - np.var(yi[mask] - yhat[mask]) / np.var(yi[mask])
    b0 = np.linalg.lstsq(A[w_is][:, :2], yi[w_is], rcond=None)[0]
    pred0 = A[:, :2] @ b0
    print(f"\n변동성 {n}h: R2 기준모델 IS {r2(w_is, pred0):.4f} → +OI {r2(w_is, pred):.4f} | OOS {r2(w_oos, pred0):.4f} → +OI {r2(w_oos, pred):.4f}"
          f"  (계수 doi_4h {b[2]:+.2f}, doi_24h {b[3]:+.2f}: OI 1% 증가 → 변동성 약 {(np.exp(b[2]*0.01+b[3]*0.01)-1)*100:+.1f}%)")

# (4) 변동성 국면 (atr_rank 5분위) → 다음 24h 실현 변동성, ATR%
rows = []
for p in ("IS", "OOS"):
    d = df.loc[masks[p]].dropna(subset=["atr_rank", "rv_next_24"])
    d["q"] = pd.cut(d["atr_rank"], [0, 0.2, 0.4, 0.6, 0.8, 1.0], labels=[1, 2, 3, 4, 5], include_lowest=True)
    for q, g in d.groupby("q", observed=True):
        rows.append(dict(period=p, q=int(q), n=len(g), atr_pct=g.atr_pct.mean() * 100, rv24=g.rv_next_24.mean() * 100,
                         range24=g.fut_range_24.mean() * 100, range_atr=g.fut_range_atr.mean(),
                         y24_bp=g.y_24.mean() * 1e4, up24=(g.y_24 > 0).mean()))
vr = pd.DataFrame(rows)
print("\n=== 변동성 국면(ATR 180일 백분위 5분위) ===")
print(vr.round(3).to_string(index=False))
vr.to_csv(OUT + "a2c_vol_regime.csv", index=False)
