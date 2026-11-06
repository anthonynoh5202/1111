"""A2b. (1) 판정 규칙 보완: IS에서도 |t|>=2 여야 '발견'으로 인정 (더 엄격한 방향으로만 고침)
(2) OI 변화 → 다음 변동성 결과의 강건성: 연도별 IC, |OI 변화|, 다른 특징과 함께 넣은 다변량 회귀, 5분위 표(변동성 놀람 %)
(3) IS 이전 구간(2020-01~2021-11) 재확인: metrics 없이 만들 수 있는 특징(펀딩·테이커·ATR)
"""
import numpy as np
import pandas as pd

from common import (OUT, IS_START, add_vol_residuals, ic_stats, load_klines, ols_nw, period_mask, holm)

pd.set_option("display.width", 250)
df = pd.read_pickle(OUT + "hourly.pkl")
df = add_vol_residuals(df)

# 다음 24시간 고가-저가 폭 (1시간봉)
h = load_klines("1h"); h.index = h.index + pd.Timedelta(hours=1)
hh = h["high"].reindex(df.index); ll = h["low"].reindex(df.index)
fmax = hh[::-1].rolling(24).max()[::-1].shift(-1)    # 봉 T+1h..T+24h 마감분 = 시간 [T, T+24h)
fmin = ll[::-1].rolling(24).min()[::-1].shift(-1)
df["fut_range_24"] = (fmax - fmin) / df["close"]
df["fut_range_atr"] = (fmax - fmin) / df["atr4h"]

# ---------------- (1) 판정 보완 ----------------
ver = pd.read_csv(OUT + "a2_verdict.csv")
hit = pd.read_csv(OUT + "a2_hit.csv")
def tight(r):
    disc = abs(r.t_is) >= 2 and abs(r.tm_is) >= 2
    if r.verdict == "근거 있음" and disc:
        return "근거 있음"
    if r.verdict in ("근거 있음", "약한 근거") and (disc or abs(r.t_is) >= 2):
        return "약한 근거"
    return "잡음"
ver["verdict_strict"] = ver.apply(tight, axis=1)
ver.to_csv(OUT + "a2_verdict_strict.csv", index=False)
print("=== 판정(원래 규칙 → 보완 규칙) 중 잡음 아닌 것 ===")
print(ver[(ver.verdict != "잡음") | (ver.verdict_strict != "잡음")].round(3).to_string(index=False))

# ---------------- (2) OI → 변동성 강건성 ----------------
print("\n=== 연도별 IC: OI 변화 → 변동성 잔차 ===")
rows = []
for feat in ["doi_1h", "doi_4h", "doi_24h", "fund_last", "tbr_1h"]:
    for tgt in ["rvres_4", "rvres_24"]:
        hz = int(tgt.split("_")[1])
        for y in range(2022, 2027):
            msk = (df.index.year == y) & (df.index >= IS_START)
            msk &= df.index <= pd.Timestamp("2026-09-28", tz="UTC")
            s = ic_stats(df.loc[msk, feat], df.loc[msk, tgt], L=336)
            rows.append(dict(feature=feat, target=tgt, year=y, ic=s["ic"], t=s["t_nw"]))
yr = pd.DataFrame(rows)
print(yr.pivot_table(index=["feature", "target"], columns="year", values="ic").round(3).to_string())
yr.to_csv(OUT + "a2b_yearly_ic.csv", index=False)

df["absdoi_4h"] = df["doi_4h"].abs(); df["absdoi_24h"] = df["doi_24h"].abs()
df["absret_4h"] = df["ret_past_4h"].abs()
print("\n=== |OI 변화| vs 부호 있는 OI 변화 (rvres_24 IC) ===")
for feat in ["doi_4h", "absdoi_4h", "doi_24h", "absdoi_24h"]:
    for per in ("IS", "OOS"):
        m = period_mask(df.index, per, 24)
        s = ic_stats(df.loc[m, feat], df.loc[m, "rvres_24"], L=336)
        print(f"{feat:11s} {per:3s} ic={s['ic']:+.3f} t={s['t_nw']:+.2f} t_m={s['t_m']:+.2f}")

print("\n=== 다변량(순위 표준화) 회귀: rvres ~ 여러 특징, NW t (L=336) ===")
mv_feats = ["doi_4h", "doi_24h", "ret_past_4h", "absret_4h", "ret_past_24h", "atr_rank", "fund_last", "tbr_4h", "ls_global_z"]
mv = []
for tgt in ("rvres_4", "rvres_24"):
    hz = int(tgt.split("_")[1])
    for per in ("IS", "OOS"):
        m = period_mask(df.index, per, hz)
        d = df.loc[m, mv_feats + [tgt]].dropna()
        Z = np.column_stack([np.ones(len(d))] + [((d[c].rank() - d[c].rank().mean()) / d[c].rank().std()).to_numpy() for c in mv_feats])
        yv = d[tgt].to_numpy()
        b, t = ols_nw(yv, Z, 336)
        mv.append(dict(target=tgt, period=per, n=len(d), **{f"t_{c}": t[i + 1] for i, c in enumerate(mv_feats)},
                       **{f"b_{c}": b[i + 1] for i, c in enumerate(mv_feats)}))
mv = pd.DataFrame(mv)
print(mv[["target", "period", "n"] + [f"t_{c}" for c in mv_feats]].round(2).to_string(index=False))
mv.to_csv(OUT + "a2b_multivar.csv", index=False)

print("\n=== 5분위(IS 경계): OI 변화 → 다음 24h 변동성 ===")
qrows = []
for feat in ["doi_1h", "doi_4h", "doi_24h"]:
    ism = period_mask(df.index, "IS", 24)
    edges = np.unique(df.loc[ism, feat].dropna().quantile([0.2, 0.4, 0.6, 0.8]).to_numpy())
    for per in ("IS", "OOS"):
        m = period_mask(df.index, per, 24)
        d = df.loc[m, [feat, "rv_next_24", "rvhat_24", "rvres_24", "rvres_4", "fut_range_24", "fut_range_atr"]].dropna()
        d["q"] = np.searchsorted(edges, d[feat].to_numpy(), side="right") + 1
        for q, g in d.groupby("q"):
            qrows.append(dict(feature=feat, period=per, q=q, n=len(g), x_lo=g[feat].min() * 100, x_hi=g[feat].max() * 100,
                              rv24_pct=g.rv_next_24.mean() * 100, rvhat24_pct=g.rvhat_24.mean() * 100,
                              surprise24_pct=(np.exp(g.rvres_24.mean()) - 1) * 100,
                              surprise4_pct=(np.exp(g.rvres_4.mean()) - 1) * 100,
                              share_above=(g.rvres_24 > 0).mean(),
                              range24_pct=g.fut_range_24.mean() * 100, range_atr=g.fut_range_atr.mean()))
qd = pd.DataFrame(qrows)
print(qd.round(3).to_string(index=False))
qd.to_csv(OUT + "a2b_doi_quint.csv", index=False)
print("IS 경계(%):")
for feat in ["doi_1h", "doi_4h", "doi_24h"]:
    ism = period_mask(df.index, "IS", 24)
    print(feat, np.round(df.loc[ism, feat].dropna().quantile([0.2, 0.4, 0.6, 0.8]).to_numpy() * 100, 3))

# ---------------- (3) IS 이전 구간 (2020-01-08 ~ 2021-11-30) ----------------
print("\n=== IS 이전(2020-01~2021-11) 재확인: 방향 IC ===")
pre = (df.index >= pd.Timestamp("2020-02-01", tz="UTC")) & (df.index <= pd.Timestamp("2021-11-29", tz="UTC"))
rows = []
for feat in ["fund_last", "fund_avg3d", "fund_pct90", "tbr_1h", "tbr_4h", "tbr_24h", "tbr_resid_1h", "atr_rank", "ret_past_1h", "ret_past_4h", "ret_past_24h"]:
    for tgt, L in (("y_4", 24), ("y_24", 72)):
        s = ic_stats(df.loc[pre, feat], df.loc[pre, tgt], L=L)
        rows.append(dict(feature=feat, target=tgt, n=s["n"], ic=s["ic"], t_nw=s["t_nw"], t_m=s["t_m"]))
pr = pd.DataFrame(rows)
print(pr.round(3).to_string(index=False))
pr.to_csv(OUT + "a2b_pre_is.csv", index=False)
df.to_pickle(OUT + "hourly_plus.pkl")
