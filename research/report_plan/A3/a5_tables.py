"""A5. 보고서용 표를 CSV에서 마크다운으로 뽑는다 (옮겨 적기 실수 방지)."""
import numpy as np, pandas as pd
OUT = "/tmp/claude-0/-home-user-1111/25e0663c-3dd5-5112-98b0-d8d31ac17dd0/scratchpad/team/A3/"
LABEL = {"fund_last": "펀딩비(마지막 정산)", "fund_avg3d": "펀딩비 3일 평균", "fund_pct90": "펀딩비 90일 백분위",
         "doi_1h": "OI 변화 1h", "doi_4h": "OI 변화 4h", "doi_24h": "OI 변화 24h",
         "tbr_1h": "테이커 매수비율 1h", "tbr_resid_1h": "테이커 1h 잔차", "tbr_4h": "테이커 매수비율 4h", "tbr_24h": "테이커 매수비율 24h",
         "ls_topacc_z": "탑트레이더 계정 롱숏 z", "ls_toppos_z": "탑트레이더 포지션 롱숏 z", "ls_global_z": "전체 계정 롱숏 z",
         "atr_rank": "변동성 국면(ATR 백분위)", "ret_past_1h": "[참고] 지난 1h 수익률", "ret_past_4h": "[참고] 지난 4h 수익률",
         "ret_past_24h": "[참고] 지난 24h 수익률"}
def md(df):
    cols = list(df.columns)
    s = "| " + " | ".join(cols) + " |\n|" + "|".join(["---"] * len(cols)) + "|\n"
    for _, r in df.iterrows():
        s += "| " + " | ".join(str(x) for x in r.values) + " |\n"
    return s
out = []
v = pd.read_csv(OUT + "a2_verdict_strict.csv")
ic = pd.read_csv(OUT + "a2_ic_all.csv")
hit = pd.read_csv(OUT + "a2_hit.csv")
# 방향 표
rows = []
for f in LABEL:
    r = {}
    r["특징"] = LABEL[f]
    for tgt, nm in (("y_4", "4h"), ("y_24", "24h")):
        a = ic[(ic.feature == f) & (ic.target == tgt)].set_index("period")
        r[f"IC {nm} IS (t)"] = f"{a.loc['IS','ic']:+.3f} ({a.loc['IS','t_nw']:+.1f})"
        r[f"IC {nm} OOS (t)"] = f"{a.loc['OOS','ic']:+.3f} ({a.loc['OOS','t_nw']:+.1f})"
    h = hit[(hit.feature == f) & (hit.target == "y_24") & (hit.period == "OOS")].iloc[0]
    r["OOS 24h 적중률(Q1·Q5)"] = f"{h.hit_q15*100:.1f}%"
    r["OOS 24h Q5−Q1(bp)"] = f"{h.spread_bp_signed:+.0f}"
    vv = v[(v.feature == f)]
    if len(vv):
        d = vv[vv.family == "dir"].verdict_strict.tolist()
        r["판정(방향)"] = "근거 있음" if "근거 있음" in d else ("약한 근거" if "약한 근거" in d else "잡음")
    else:
        r["판정(방향)"] = "(참고·판정 제외)"
    rows.append(r)
out.append("### 방향 표\n" + md(pd.DataFrame(rows)))
# 변동성 표
raw = pd.read_csv(OUT + "a2_raw_vol_ic.csv")
rows = []
for f in LABEL:
    r = {"특징": LABEL[f]}
    rr = raw[raw.feature == f].set_index("period")
    r["원시 IC(다음24h 변동성) IS/OOS"] = f"{rr.loc['IS','ic_raw_rv24']:+.2f} / {rr.loc['OOS','ic_raw_rv24']:+.2f}"
    for tgt, nm in (("rvres_4", "4h"), ("rvres_24", "24h")):
        a = ic[(ic.feature == f) & (ic.target == tgt)].set_index("period")
        r[f"잔차 IC {nm} IS (t)"] = f"{a.loc['IS','ic']:+.3f} ({a.loc['IS','t_nw']:+.1f})"
        r[f"잔차 IC {nm} OOS (t)"] = f"{a.loc['OOS','ic']:+.3f} ({a.loc['OOS','t_nw']:+.1f})"
    vv = v[(v.feature == f) & (v.family == "vol")]
    r["판정(변동성)"] = ("근거 있음" if "근거 있음" in vv.verdict_strict.tolist() else ("약한 근거" if "약한 근거" in vv.verdict_strict.tolist() else "잡음")) if len(vv) else "(참고·판정 제외)"
    rows.append(r)
out.append("### 변동성 표\n" + md(pd.DataFrame(rows)))
# 5분위: 주요 특징
qt = pd.read_csv(OUT + "a2_quintiles.csv")
for f in ["fund_avg3d", "doi_24h", "tbr_1h", "ls_global_z", "atr_rank"]:
    q = qt[qt.feature == f].copy()
    t = q.pivot_table(index="q", columns="period", values=["y4_bp", "up4", "y24_bp", "up24", "rv24_pct"])
    rows = []
    for k in sorted(q.q.unique()):
        rows.append({"분위": k,
                     "4h bp IS/OOS": f"{t.loc[k, ('y4_bp','IS')]:+.1f} / {t.loc[k, ('y4_bp','OOS')]:+.1f}",
                     "4h 상승% IS/OOS": f"{t.loc[k, ('up4','IS')]*100:.1f} / {t.loc[k, ('up4','OOS')]*100:.1f}",
                     "24h bp IS/OOS": f"{t.loc[k, ('y24_bp','IS')]:+.0f} / {t.loc[k, ('y24_bp','OOS')]:+.0f}",
                     "24h 상승% IS/OOS": f"{t.loc[k, ('up24','IS')]*100:.1f} / {t.loc[k, ('up24','OOS')]*100:.1f}",
                     "다음24h 변동성% IS/OOS": f"{t.loc[k, ('rv24_pct','IS')]:.2f} / {t.loc[k, ('rv24_pct','OOS')]:.2f}",
                     "OOS 표본(시간)": int(q[(q.q == k) & (q.period == 'OOS')].n.iloc[0]) if len(q[(q.q == k) & (q.period == 'OOS')]) else 0})
    out.append(f"### 5분위: {LABEL[f]}\n" + md(pd.DataFrame(rows)))
# 조합 표
ct = pd.read_csv(OUT + "a2_combo_tab.csv")
for lb in ["4h", "24h"]:
    c = ct[(ct.lookback == lb)]
    t = c.pivot_table(index="group", columns=["target", "period"], values=["mean_bp", "up"])
    rows = []
    for g in ["가격↑OI↑", "가격↑OI↓", "가격↓OI↑", "가격↓OI↓"]:
        rows.append({"조합(지난 " + lb + ")": g,
                     "다음4h bp IS/OOS": f"{t.loc[g, ('mean_bp','y_4','IS')]:+.1f} / {t.loc[g, ('mean_bp','y_4','OOS')]:+.1f}",
                     "다음4h 상승% IS/OOS": f"{t.loc[g, ('up','y_4','IS')]*100:.1f} / {t.loc[g, ('up','y_4','OOS')]*100:.1f}",
                     "다음24h bp IS/OOS": f"{t.loc[g, ('mean_bp','y_24','IS')]:+.0f} / {t.loc[g, ('mean_bp','y_24','OOS')]:+.0f}",
                     "다음24h 상승% IS/OOS": f"{t.loc[g, ('up','y_24','IS')]*100:.1f} / {t.loc[g, ('up','y_24','OOS')]*100:.1f}",
                     "OOS 비중": f"{c[(c.group==g)&(c.target=='y_24')&(c.period=='OOS')].n.iloc[0] / c[(c.target=='y_24')&(c.period=='OOS')].n.sum()*100:.0f}%"})
    out.append(f"### 가격×OI 조합 (지난 {lb})\n" + md(pd.DataFrame(rows)))
# 필터 표
fr = pd.read_csv(OUT + "a3_filter_results.csv")
rows = []
for _, r in fr.iterrows():
    rows.append({"변형": r["filter"], "기간": r.period, "거래": int(r.n), "승률": f"{r.win*100:.0f}%", "기대값 R": f"{r.ev:+.3f}",
                 "t": f"{r.t:+.2f}", "평균 이익/손실 R": f"{r.avg_win:+.2f} / {r.avg_loss:+.2f}", "최대 낙폭 R": f"{r.maxdd:.1f}",
                 "평균 보유(h)": f"{r.hold_h:.0f}", "제외된 거래(기대값)": (f"{int(r.out_n)} ({r.out_ev:+.3f})" if r.out_n > 0 else "-"),
                 "차이 t": (f"{r.t_diff:+.2f}" if np.isfinite(r.t_diff) else "-")})
out.append("### 필터 표\n" + md(pd.DataFrame(rows)))
open(OUT + "a5_tables.md", "w").write("\n\n".join(out))
print("\n\n".join(out))
