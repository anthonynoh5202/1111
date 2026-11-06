"""A2. 특징의 예측력: 5분위 평균·적중률·순위 상관(IC), IS/OOS 분리, 다중 검정 보정.

판정 규칙(결과 보기 전에 고정):
  방향(다음 4h·24h 수익률) 가족, 변동성(다음 4h·24h 실현 변동성 '잔차') 가족 각각에서
  [근거 있음]  IS·OOS IC 부호 같음  AND  OOS Newey-West p의 Holm 보정값 < 0.05  AND  OOS 월별 IC |t| >= 2
               AND (방향이면) OOS 5분위 Q5-Q1 24h 수익률 차가 왕복 비용 14bp보다 큼
  [약한 근거]  IS·OOS 부호 같음 AND OOS |t_nw| >= 2 AND OOS |t_m| >= 2 이지만 위 조건 일부 미달
  [잡음]       그 밖
변동성 '잔차' = log(다음 실현 변동성) 에서 '과거 실현 변동성(4h·24h·7d) + 요일·시간(168칸)'으로 설명되는 부분을 뺀 것(IS에서 적합).
  → 변동성은 원래 뭉치므로(어제 크게 움직이면 오늘도 큼), 그 당연한 부분을 빼고도 남는 정보가 있는지 본다.
"""
import numpy as np
import pandas as pd

from common import (OUT, IS_START, IS_END, OOS_START, OOS_END, bh, holm, ic_stats, ols_nw, period_mask)

df = pd.read_pickle(OUT + "hourly.pkl")
df = df[df.index >= IS_START]

CANDS = ["fund_last", "fund_avg3d", "fund_pct90",
         "doi_1h", "doi_4h", "doi_24h",
         "tbr_1h", "tbr_resid_1h", "tbr_4h", "tbr_24h",
         "ls_topacc_z", "ls_toppos_z", "ls_global_z",
         "atr_rank"]
REFS = ["ret_past_1h", "ret_past_4h", "ret_past_24h"]
LABEL = {
    "fund_last": "펀딩비(마지막 정산)", "fund_avg3d": "펀딩비 3일 평균", "fund_pct90": "펀딩비 3일평균의 90일 백분위",
    "doi_1h": "OI 변화 1h", "doi_4h": "OI 변화 4h", "doi_24h": "OI 변화 24h",
    "tbr_1h": "테이커 매수비율 1h", "tbr_resid_1h": "테이커 매수비율 1h 잔차(가격 반영분 제외)",
    "tbr_4h": "테이커 매수비율 4h", "tbr_24h": "테이커 매수비율 24h",
    "ls_topacc_z": "탑트레이더 계정 롱숏 z(30일)", "ls_toppos_z": "탑트레이더 포지션 롱숏 z(30일)",
    "ls_global_z": "전체 계정 롱숏 z(30일)", "atr_rank": "변동성 국면(ATR 180일 백분위)",
    "ret_past_1h": "[참고] 지난 1h 수익률", "ret_past_4h": "[참고] 지난 4h 수익률", "ret_past_24h": "[참고] 지난 24h 수익률",
}

# ---------------- 변동성 잔차 목표 (IS 적합) ----------------
eps = 1e-5
how = (df.index.dayofweek * 24 + df.index.hour).to_numpy()
D = np.zeros((len(df), 168)); D[np.arange(len(df)), how] = 1.0
base = np.column_stack([np.log(df[c].to_numpy() + eps) for c in ["rv_past_4", "rv_past_24", "rv_past_168"]])
X = np.column_stack([base, D])            # 168 더미가 상수항 역할
for n in (4, 24):
    y = np.log(df[f"rv_next_{n}"].to_numpy() + eps)
    ism = period_mask(df.index, "IS", n) & np.isfinite(y) & np.isfinite(X).all(axis=1)
    b = np.linalg.lstsq(X[ism], y[ism], rcond=None)[0]
    res = y - X @ b
    df[f"rvres_{n}"] = res
    r2_is = 1 - np.nanvar(res[ism]) / np.nanvar(y[ism])
    oos = period_mask(df.index, "OOS", n) & np.isfinite(y) & np.isfinite(X).all(axis=1)
    r2_oos = 1 - np.nanvar(res[oos]) / np.nanvar(y[oos])
    print(f"vol baseline n={n}: coef(log rv4,24,168)={np.round(b[:3],3)}  R2 IS={r2_is:.3f} OOS={r2_oos:.3f}")

TARGETS = {"y_4": ("dir", 24), "y_24": ("dir", 72), "rvres_4": ("vol", 336), "rvres_24": ("vol", 336)}

rows = []
for feat in CANDS + REFS:
    for tgt, (fam, L) in TARGETS.items():
        hzn = int(tgt.split("_")[1])
        for per in ("IS", "OOS"):
            msk = period_mask(df.index, per, hzn)
            s = ic_stats(df.loc[msk, feat], df.loc[msk, tgt], L=L)
            rows.append(dict(feature=feat, target=tgt, family=fam, period=per, **s))
ic = pd.DataFrame(rows)

# 원시 변동성 IC (설명용)
raw = []
for feat in CANDS + REFS:
    for per in ("IS", "OOS"):
        msk = period_mask(df.index, per, 24)
        s = ic_stats(df.loc[msk, feat], df.loc[msk, "rv_next_24"], L=336)
        raw.append(dict(feature=feat, period=per, ic_raw_rv24=s["ic"], t_raw=s["t_nw"]))
raw = pd.DataFrame(raw)

# ---------------- 5분위 (IS 경계를 OOS에 그대로) ----------------
def quint_edges(x_is: pd.Series):
    qs = x_is.dropna().quantile([0.2, 0.4, 0.6, 0.8]).to_numpy()
    return np.unique(qs)


def bin_of(x: pd.Series, edges) -> pd.Series:
    return pd.Series(np.searchsorted(edges, x.to_numpy(), side="right"), index=x.index).where(x.notna())


qrows = []
for feat in CANDS + REFS:
    ism = period_mask(df.index, "IS", 24)
    edges = quint_edges(df.loc[ism, feat])
    for per in ("IS", "OOS"):
        msk = period_mask(df.index, per, 24)
        d = df.loc[msk, [feat, "y_4", "y_24", "rv_next_24", "rvres_24"]].dropna()
        d["q"] = bin_of(d[feat], edges)
        for q, g in d.groupby("q"):
            qrows.append(dict(feature=feat, period=per, q=int(q) + 1, nq=len(edges) + 1, n=len(g),
                              x_med=g[feat].median(),
                              y4_bp=g["y_4"].mean() * 1e4, up4=(g["y_4"] > 0).mean(),
                              y24_bp=g["y_24"].mean() * 1e4, up24=(g["y_24"] > 0).mean(),
                              rv24_pct=g["rv_next_24"].mean() * 100, rvres24=g["rvres_24"].mean()))
qt = pd.DataFrame(qrows)

# 적중률: IS IC 부호로 방향을 정하고, OOS의 맨 아래·맨 위 구간에서 맞힌 비율
hit = []
for feat in CANDS + REFS:
    for tgt in ("y_4", "y_24"):
        sgn = np.sign(ic[(ic.feature == feat) & (ic.target == tgt) & (ic.period == "IS")]["ic"].iloc[0])
        ism = period_mask(df.index, "IS", 24)
        edges = quint_edges(df.loc[ism, feat])
        for per in ("IS", "OOS"):
            msk = period_mask(df.index, per, 24)
            d = df.loc[msk, [feat, tgt]].dropna()
            qb = bin_of(d[feat], edges)
            top, bot = qb == len(edges), qb == 0
            pred = pd.Series(0.0, index=d.index); pred[top] = sgn; pred[bot] = -sgn
            sel = top | bot
            h = (np.sign(d.loc[sel, tgt]) == pred[sel]).mean() if sel.any() else np.nan
            base_up = (d[tgt] > 0).mean()
            spread = (d.loc[top, tgt].mean() - d.loc[bot, tgt].mean()) * 1e4 * (sgn if sgn != 0 else 1)
            hit.append(dict(feature=feat, target=tgt, period=per, hit_q15=h, base_up=base_up,
                            spread_bp_signed=spread, n_sel=int(sel.sum())))
hit = pd.DataFrame(hit)

# ---------------- 가격×OI 4가지 조합 ----------------
crow, ctab = [], []
for n in (1, 4, 24):
    sP = np.sign(df[f"ret_past_{n}h"]); sO = np.sign(df[f"doi_{n}h"])
    for tgt, L in (("y_4", 24), ("y_24", 72)):
        hzn = int(tgt.split("_")[1])
        for per in ("IS", "OOS"):
            msk = period_mask(df.index, per, hzn) & (sP != 0) & (sO != 0)
            d = pd.DataFrame({"sP": sP[msk], "sO": sO[msk], "y": df.loc[msk, tgt]}).dropna()
            Xc = np.column_stack([np.ones(len(d)), d.sP, d.sO, d.sP * d.sO])
            b, t = ols_nw(d.y.to_numpy(), Xc, L)
            crow.append(dict(lookback=f"{n}h", target=tgt, period=per, n=len(d),
                             b_mom_bp=b[1] * 1e4, t_mom=t[1], b_oi_bp=b[2] * 1e4, t_oi=t[2],
                             b_inter_bp=b[3] * 1e4, t_inter=t[3]))
            for (a, o), g in d.groupby(["sP", "sO"]):
                name = ("가격↑" if a > 0 else "가격↓") + ("OI↑" if o > 0 else "OI↓")
                ctab.append(dict(lookback=f"{n}h", target=tgt, period=per, group=name, n=len(g),
                                 mean_bp=g.y.mean() * 1e4, up=(g.y > 0).mean()))
combo = pd.DataFrame(crow); ctab = pd.DataFrame(ctab)

# ---------------- 다중 검정 보정과 판정 ----------------
oos = ic[(ic.period == "OOS") & ic.feature.isin(CANDS)].copy()
fam_p = {}
for fam in ("dir", "vol"):
    sub = oos[oos.family == fam]
    pl = sub["p_nw"].tolist()
    if fam == "dir":   # 조합 회귀의 OI 항·상호작용 항도 같은 가족에 넣는다
        cc = combo[combo.period == "OOS"]
        from common import norm_p_two_sided as P
        extra = [P(x) for x in cc["t_oi"]] + [P(x) for x in cc["t_inter"]]
    else:
        extra = []
    allp = pl + extra
    hol = holm(allp); q = bh(allp)
    oos.loc[sub.index, "p_holm"] = hol[:len(pl)]
    oos.loc[sub.index, "q_bh"] = q[:len(pl)]
    fam_p[fam] = dict(m=len(allp), extra_holm=hol[len(pl):], extra_bh=q[len(pl):])
    print(f"family {fam}: {len(allp)} tests")

isic = ic[(ic.period == "IS")].set_index(["feature", "target"])
verdict = []
for _, r in oos.iterrows():
    i = isic.loc[(r.feature, r.target)]
    same = np.sign(i.ic) == np.sign(r.ic) and np.isfinite(i.ic)
    hs = hit[(hit.feature == r.feature) & (hit.target == "y_24") & (hit.period == "OOS")]
    spread24 = float(hs["spread_bp_signed"].iloc[0]) if r.family == "dir" else np.nan
    strong = same and r.p_holm < 0.05 and abs(r.t_m) >= 2 and (r.family == "vol" or spread24 > 14)
    weak = same and abs(r.t_nw) >= 2 and abs(r.t_m) >= 2
    verdict.append(dict(feature=r.feature, target=r.target, family=r.family,
                        ic_is=i.ic, t_is=i.t_nw, tm_is=i.t_m, ic_oos=r.ic, t_oos=r.t_nw, tm_oos=r.t_m,
                        pos_m_oos=r.pos_m, p_holm=r.p_holm, q_bh=r.q_bh,
                        verdict="근거 있음" if strong else ("약한 근거" if weak else "잡음")))
ver = pd.DataFrame(verdict)

# 참고 특징(가격만)은 판정 가족에 넣지 않고 따로 표시
refv = ic[ic.feature.isin(REFS)].pivot_table(index=["feature", "target"], columns="period", values=["ic", "t_nw", "t_m"])

# ---------------- 저장 ----------------
ic.to_csv(OUT + "a2_ic_all.csv", index=False)
qt.to_csv(OUT + "a2_quintiles.csv", index=False)
hit.to_csv(OUT + "a2_hit.csv", index=False)
combo.to_csv(OUT + "a2_combo_reg.csv", index=False)
ctab.to_csv(OUT + "a2_combo_tab.csv", index=False)
ver.to_csv(OUT + "a2_verdict.csv", index=False)
raw.to_csv(OUT + "a2_raw_vol_ic.csv", index=False)
pd.to_pickle(fam_p, OUT + "a2_fam_p.pkl")

pd.set_option("display.width", 250)
print("\n=== 판정 (OOS, 후보 특징) ===")
print(ver.round(3).to_string(index=False))
print("\n=== 참고: 가격만 쓴 특징 ===")
print(refv.round(3).to_string())
print("\n=== 가격×OI 조합 회귀 (bp, NW t) ===")
print(combo.round(2).to_string(index=False))
print("extra holm (dir family, OI항 then 상호작용항, OOS 순서):", np.round(fam_p["dir"]["extra_holm"], 3))
print("\n=== 원시 변동성 IC (다음 24h 실현 변동성) ===")
print(raw.pivot_table(index="feature", columns="period", values="ic_raw_rv24").round(3).to_string())
print("\n=== 적중률 (Q1·Q5) ===")
print(hit.pivot_table(index=["feature", "target"], columns="period", values=["hit_q15", "spread_bp_signed"]).round(3).to_string())
