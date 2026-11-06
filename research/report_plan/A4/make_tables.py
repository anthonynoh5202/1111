"""모든 결과 JSON → 보고서용 마크다운 표(out/tables.md). 손으로 옮겨 적지 않기 위해 만든다."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

import common as C

KRW = 1400
P_NOW = 83461.0          # 2026-09-28 종가
MIN_QTY = 0.001          # 퀀트① 확인: 지금 규칙 0.001 BTC(명목 50 USDT 이상)
E0 = 35.7

J = lambda n: json.loads((C.OUT / n).read_text())  # noqa: E731
T = J("trend_summary.json")
R = J("random_summary.json")
X = J("extra_summary.json")
S = J("stats_summary.json")
L = J("llm_summary.json")
TT = pd.read_csv(C.OUT / "trend_trades.csv.gz")

f3 = lambda x: "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:+.3f}"  # noqa: E731
f2 = lambda x: "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:+.2f}"  # noqa: E731
pc = lambda x: "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x*100:.1f}%"  # noqa: E731
pcs = lambda x: "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x*100:+.1f}%"  # noqa: E731
won = lambda usdt: f"{usdt*KRW:,.0f}원"  # noqa: E731

lines = []
P = lines.append

# ---------------- (a) B&H ----------------
P("#### T1. 보유(buy & hold)")
P("| 방식 | 기간 | 연 수익(CAGR) | 최대 낙폭 | 연 변동성 | 샤프 | 5만 원 → |")
P("|---|---|---:|---:|---:|---:|---:|")
for nm, lab in (("BH_spot", "현물 보유"), ("BH_perp1x", "무기한 1배 롱(매시간 1배 유지, 펀딩 냄)"), ("BH_perp_fixedqty", "(참고) 무기한 수량 고정")):
    for w, wl in (("IS", "IS 2020-03~2023"), ("OOS", "OOS 2024~2026-09")):
        m = T["bh"][nm][w]
        P(f"| {lab} | {wl} | {pcs(m['cagr'])} | {pc(m['mdd'])} | {pc(m['vol'])} | {m['sharpe']:.2f} | {50000*(1+m['total']):,.0f}원 |")

# ---------------- (b) trend ----------------
P("")
P("#### T2. 단순 추세(신호 바뀔 때만 매매) — R 지표 (거래당, 비용·펀딩 포함)")
P("| 규칙 | IS 거래 | IS 평균 R [95% 하한] | OOS 거래 | OOS 평균 R [95% 하한, 상한] | OOS 승률 | OOS 손익비 | OOS 최대 낙폭(R) | OOS 평균 보유 | 손절 폭 중앙(OOS) |")
P("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
for name, r in T["rules"].items():
    a, b = r["R_IS"], r["R_OOS"]
    sub = TT[(TT["rule"] == name) & (TT["entry_t"] >= C.OOS_START)]
    sp = float(np.median(sub["r_den"] / sub["entry_px"])) if len(sub) else float("nan")
    P(f"| `{name}` | {a['n']} | {f3(a['mean'])} [{f3(a['ci_lo'])}] | {b['n']} | {f3(b['mean'])} [{f3(b['ci_lo'])}, {f3(b['ci_hi'])}] | {pc(b['win'])} | {b['payoff']:.2f} | {b['mdd_r']:.1f} | {b.get('hold_h', float('nan'))/24:.1f}일 | {pc(sp)} |")
P("")
P("#### T3. 단순 추세 — 자산 곡선 (1시간봉 평가)")
P("| 규칙 | IS 1배 CAGR / 낙폭 | OOS 1배 CAGR / 낙폭 / 샤프 | IS 위험1% CAGR / 낙폭 | OOS 위험1% CAGR / 낙폭 / 샤프 | OOS 시장 참여 시간 |")
P("|---|---:|---:|---:|---:|---:|")
for name, r in T["rules"].items():
    i1, o1, i2, o2 = r["EQ_1x_IS"], r["EQ_1x_OOS"], r["EQ_risk1_IS"], r["EQ_risk1_OOS"]
    P(f"| `{name}` | {pcs(i1['cagr'])} / {pc(i1['mdd'])} | {pcs(o1['cagr'])} / {pc(o1['mdd'])} / {o1['sharpe']:.2f} | {pcs(i2['cagr'])} / {pc(i2['mdd'])} | {pcs(o2['cagr'])} / {pc(o2['mdd'])} / {o2['sharpe']:.2f} | {pc(r['R_OOS'].get('time_in_mkt'))} |")

# ---------------- (c) random ----------------
P("")
P("#### T4. 무작위 진입(매시간, 같은 손절·목표·보유) — 거래당 R")
P("| 사양 | 기간 | 롱 평균 R [95%] | 숏 평균 R [95%] | 무작위 방향(롱·숏 평균) | 롱 승률 | 목표/손절/시간 비율(롱) | 비용 ÷ R(롱) | 손절 폭 중앙 | 평균 보유 |")
P("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
for key, v in R.items():
    for per, pl in (("IS", "IS"), ("OOS", "OOS"), ("CLEAN", "2026-07~09")):
        lg, sh = v["periods"][per]["long"], v["periods"][per]["short"]
        mix = X[key]["mix_mean_allfills"][per]
        P(f"| {key} {v['label']} | {pl} | {f3(lg['mean'])} [{f3(lg['ci_lo'])}, {f3(lg['ci_hi'])}] | {f3(sh['mean'])} [{f3(sh['ci_lo'])}, {f3(sh['ci_hi'])}] | {f3(mix)} | {pc(lg['win'])} | {pc(lg['target_rate'])}/{pc(lg['stop_rate'])}/{pc(lg['time_rate'])} | {lg['cost_r']:.3f} | {pc(lg['stop_pct_med'])} | {lg['hold_h']:.0f}h |")
P("")
P("#### T5. 겹치지 않는 무작위 전략 1,000개(포지션 없을 때 평균 24시간 기다렸다 무작위 진입, 위험 1%)")
P("| 사양 | 기간·방향 | 거래 수(중앙) | 평균 R 5% / 50% / **95%** | CAGR 5% / 50% / 95% | 최대 낙폭 50% / 95% | R 낙폭 50% / 95% |")
P("|---|---|---:|---:|---:|---:|---:|")
for key, v in R.items():
    for kk, s in v["random_strategies_wait24_risk1pct"].items():
        a, b, c = s["mean_r_p05_p50_p95"]
        P(f"| {key} | {kk} | {s['n_trades_median']:.0f} | {f3(a)} / {f3(b)} / **{f3(c)}** | {pcs(s['cagr_p05_p50_p95'][0])} / {pcs(s['cagr_p05_p50_p95'][1])} / {pcs(s['cagr_p05_p50_p95'][2])} | {pc(s['mdd_p05_p50_p95'][1])} / {pc(s['mdd_p05_p50_p95'][2])} | {s['mdd_r_p05_p50_p95'][1]:.0f} / {s['mdd_r_p05_p50_p95'][2]:.0f} |")
P("")
P("#### T6. (b)+(c) 결합: 이평 방향(20/60) + 같은 손절·목표·보유, 겹치지 않게(청산 뒤 바로 다음 정시 진입)")
P("| 사양 | 방향 규칙 | IS 거래 / 평균 R [95%] | OOS 거래 / 평균 R [95%] | OOS 위험1% CAGR / 낙폭 | 2026-07~09 거래 / 평균 R |")
P("|---|---|---:|---:|---:|---:|")
for key in ("R1", "R2", "R3", "RL"):
    for nm, rr in X[key]["trend_dir_same_exits"].items():
        i, o, c = rr["IS"]["seq"], rr["OOS"]["seq"], rr["CLEAN"]["seq"]
        P(f"| {key} | {nm} | {i['n']} / {f3(i['mean'])} [{f3(i['ci_lo'])}, {f3(i['ci_hi'])}] | {o['n']} / {f3(o['mean'])} [{f3(o['ci_lo'])}, {f3(o['ci_hi'])}] | {pcs(o['cagr_risk1'])} / {pc(o['mdd_risk1'])} | {c['n']} / {f3(c['mean'])} |")
P("")
P("#### T7. 관망 채점 기준 비율(시장가 사양, 같은 시각 롱·숏 탐침)")
P("| 사양 | 기간 | 두 방향 모두 손절(휩쏘) | 한쪽이 목표 도달(놓칠 수 있는 움직임) | 둘 다 시간 청산(조용) | 사후 최선 방향 평균 R | 사후 최악 방향 평균 R |")
P("|---|---|---:|---:|---:|---:|---:|")
for key in ("R1", "R2", "R3"):
    for per in ("IS", "OOS", "CLEAN"):
        w = X[key]["watch_base"][per]
        P(f"| {key} | {per} | {pc(w['both_stopped'])} | {pc(w['one_target'])} | {pc(w['both_time'])} | {f2(w['best_of_two_mean'])} | {f2(w['worst_of_two_mean'])} |")
P("")
P("#### T8. 연도별 무작위 평균 R (롱 / 숏)")
P("| 사양 | " + " | ".join(str(y) for y in range(2020, 2027)) + " |")
P("|---|" + "---:|" * 7)
for key in ("R1", "R2", "R3", "RL"):
    yr = X[key]["yearly"]
    P(f"| {key} | " + " | ".join(f"{yr[str(y)]['long']:+.2f} / {yr[str(y)]['short']:+.2f}" for y in range(2020, 2027)) + " |")

# ---------------- 원화 환산 ----------------
P("")
P("#### T9. 원화 환산 — 5만 원(35.7 USDT), 최소 수량 0.001 BTC 강제(BTC 83,461 기준)")
P("| 기준선(OOS) | 손절 폭(중앙, 비용 포함 R분모) | 1R = 0.001 BTC 손실 | 계좌 대비 1회 위험 | OOS 평균 R | 연 거래 수 | 연 기대 손익(원) | 계좌 1% 위험이 가능한 최소 계좌 |")
P("|---|---:|---:|---:|---:|---:|---:|---:|")
rows = []
for key in ("R1", "R2", "R3"):
    lg = R[key]["periods"]["OOS"]["long"]
    rden = lg["stop_pct_med"] + 0.0012
    rows.append((f"무작위 {key} 롱", rden, lg["mean"], 365 * 24 / max(lg["hold_h"], 1) * 0 + float(R[key]["random_strategies_wait24_risk1pct"]["OOS_long"]["n_trades_median"]) / 2.745))
for nm in ("4h-MA-LF-S", "4h-MOM-LF-S", "1d-MA-LF-S", "1d-MOM-LF-S"):
    sub = TT[(TT["rule"] == nm) & (TT["entry_t"] >= C.OOS_START)]
    rows.append((f"추세 {nm}", float(np.median(sub["r_den"] / sub["entry_px"])), float(sub["r"].mean()), len(sub) / 2.745))
for lab, rden, mr, tpy in rows:
    one_r = MIN_QTY * P_NOW * rden
    P(f"| {lab} | {pc(rden)} | {one_r:.2f} USDT ({won(one_r)}) | {pc(one_r / E0)} | {f3(mr)} | {tpy:.0f} | {won(mr * tpy * one_r)} | {won(one_r / 0.01)} |")

# ---------------- 통계 ----------------
P("")
P("#### T10. 거래당 R의 흩어짐(표준편차)")
P("| 대상 | 표준편차(R) | 왜도 | 비고 |")
P("|---|---:|---:|---|")
for k, v in S["sigma"].items():
    if "sd" in v:
        P(f"| {k} | {v['sd']:.2f} | {v['skew']:.1f} | 평균 {v['mean']:+.3f}{', ' + str(v['n']) + '건' if 'n' in v else ''} |")
P("")
P("#### T11. 평균 R의 95% 신뢰구간 폭(±) — 거래 수별")
ns = list(S["ci_halfwidth"]["sd1.2"].keys())
P("| 표준편차 | " + " | ".join(f"N={n}" for n in ns) + " |")
P("|---|" + "---:|" * len(ns))
for k, v in S["ci_halfwidth"].items():
    P(f"| {k[2:]}R | " + " | ".join(f"±{v[n]:.2f}" for n in ns) + " |")
P("")
P("#### T12. 우위 δ를 확인하는 데 필요한 '독립' 거래 수 (단측 5%, 검정력 80%) / 16개 시험 본페로니 / 관측 평균=δ일 때 95% 하한>0")
P("| 표준편차 | " + " | ".join(f"δ=+{d}R" for d in S["required_n"]["sd1.2"]) + " |")
P("|---|" + "---:|" * len(S["required_n"]["sd1.2"]))
for k, v in S["required_n"].items():
    P(f"| {k[2:]}R | " + " | ".join(f"{x['power80_alpha5_one']:,.0f} / {x['power80_alpha5_bonf16']:,.0f} / {x['lower_bound_gt0_at_mean']:,.0f}" for x in v.values()) + " |")
ep = S["empirical_power"]
P("")
P(f"실제 R 분포(R2 무작위, 평균만 옮김)로 확인: δ=+0.1R일 때 95% 하한>0이 나올 확률 — N=100: {pc(ep['d0.1_n100'])}, N=300: {pc(ep['d0.1_n300'])}, N=1000: {pc(ep['d0.1_n1000'])}. "
  f"δ=+0.2R — N=100: {pc(ep['d0.2_n100'])}, N=300: {pc(ep['d0.2_n300'])}. 우위 0인데 평균이 +0.1R 이상으로 '보일' 확률 — N=100: {pc(ep['null_mean_ge_0.1_n100'])}, N=300: {pc(ep['null_mean_ge_0.1_n300'])}, N=1000: {pc(ep['null_mean_ge_0.1_n1000'])}.")
P("")
P("#### T13. 매시간 보고의 겹침 — 독립 표본 수")
P("| 사양(보유) | 1시간 뒤 결과 상관 | 6시간 뒤 | 24시간 뒤 | 적분 자기상관 시간 τ | 하루 독립 표본 | 한 달 독립 표본 |")
P("|---|---:|---:|---:|---:|---:|---:|")
for k, v in S["overlap"].items():
    P(f"| {k} | {v['rho_lag1']:.2f} | {v['rho_lag6']:.2f} | {('%.2f' % v['rho_lag24']) if v['rho_lag24'] is not None else '—'} | {v['tau_long_h']:.0f}시간 | {v['indep_per_day_long']:.2f} | {v['indep_per_month_long']:.0f} |")
P("")
P("#### T14. 표본 간격별 독립 표본 수(롱 결과 기준)")
P("| 사양·구간 | 시간 수 | 1h | 2h | 4h | 6h | 12h | 24h | 48h |")
P("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
for k, v in S["neff_spacing"].items():
    P(f"| {k} | {v['hours']:,} | " + " | ".join(f"{v[str(s)]['n_eff']:.0f}" for s in (1, 2, 4, 6, 12, 24, 48)) + " |")
P("")
P("#### T15. 다중 검정: 우위 0인 설정 M개를 시험하고 '제일 좋은 것'을 고르면 (표준편차 1.2R)")
P("| 시험 수 M | 본페로니 z | 1등 평균 R 기대값 N=100 / 300 / 1000 | 1등 평균 R 95% 선 N=100 / 300 / 1000 |")
P("|---:|---:|---:|---:|")
for M, v in S["multiple_testing"].items():
    P(f"| {M} | {v['bonf_z']:.2f} | {v['luck_best_meanR_n100']:+.3f} / {v['luck_best_meanR_n300']:+.3f} / {v['luck_best_meanR_n1000']:+.3f} | {v['p95_best_meanR_n100']:+.3f} / {v['p95_best_meanR_n300']:+.3f} / {v['p95_best_meanR_n1000']:+.3f} |")
wf = T["walk_forward"]
P("")
P(f"과최적화 실측(16개 추세 규칙, 위험 1% 곡선): IS 샤프 순위와 OOS 샤프 순위의 스피어만 상관 = **{wf['spearman_IS_vs_OOS_sharpe']:+.2f}**. "
  f"IS 1등 `{wf['IS_best_rule'].replace('_risk1','')}`(IS 샤프 {wf['IS_best_rule_IS_sharpe']:.2f}) → OOS 샤프 {wf['IS_best_rule_OOS_sharpe']:.2f}, OOS 순위 {wf['OOS_rank_of_IS_best']}/16. "
  f"롤링 워크포워드(직전 24개월 1등을 다음 6개월, 2022-01~2026-09): CAGR {pcs(wf['wf_selected']['cagr'])}, 낙폭 {pc(wf['wf_selected']['mdd'])}, 샤프 {wf['wf_selected']['sharpe']:.2f} "
  f"vs 16개 똑같이 나눠 담기: CAGR {pcs(wf['wf_equal_weight_all16']['cagr'])}, 낙폭 {pc(wf['wf_equal_weight_all16']['mdd'])}, 샤프 {wf['wf_equal_weight_all16']['sharpe']:.2f}.")
sp = S["sprt"]
P("")
P(f"#### T16. 순차 검정(SPRT) 관문표 — 귀무 0R vs 대립 +{sp['mu1']}R, 표준편차 {sp['sd']}R, α=5%, β=20% (거래가 서로 겹치지 않을 때)")
P(f"통과: 누적 R ≥ {sp['a_up']:.1f} + {sp['slope']:.3f}×N · 중단: 누적 R ≤ −{sp['c_dn']:.1f} + {sp['slope']:.3f}×N · 그 사이면 계속.")
P("| 거래 수 N | 통과 누적 R (평균) | 중단 누적 R (평균) |")
P("|---:|---:|---:|")
for n, v in sp["table"].items():
    P(f"| {n} | ≥ {v['pass_cum_r']:+.1f} ({v['pass_mean']:+.2f}) | ≤ {v['stop_cum_r']:+.1f} ({v['stop_mean']:+.2f}) |")
P("")
P(f"실제 R 분포로 본 성질(최대 {sp['n_max']}건에서 끊음):")
P("| 참 우위 | 통과 확률 | 중단 확률 | 미결 | 결정까지 거래 수(중앙) |")
P("|---:|---:|---:|---:|---:|")
for mu, v in sp["oc"].items():
    P(f"| {float(mu):+.2f}R | {pc(v['p_pass'])} | {pc(v['p_stop'])} | {pc(v['p_undecided'])} | {v['median_n']:.0f} |")
P("")
P("#### T17. 5만 원 단계 모의 실험(최소 수량 강제 → 1회 위험 고정, R 분포 = R2 무작위 모양, 2만 회)")
P("| 포지션 | 손절 폭(퀀트① 중앙) | 1R(비용 포함) | 계좌 대비 | 참 우위 | 30건 안에 누적 −12R | 50건 안에 −50% | 100건 안에 −50% | 100건 안에 낙폭 ≥15R | 50건 뒤 이익 확률 | 100건 뒤 이익 확률 |")
P("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
for k, v in S["small_account"].items():
    N, rp, mu = k.split("_")
    stop_lab = "1h 1.00%" if rp.startswith("rden1.1") else "4h 2.20%"
    P(f"| {'0.001 BTC(83.5 USDT)' if N == 'N83' else '0.002 BTC(167 USDT, 옛 규칙)'} | {stop_lab} | {v['one_r_usdt']:.2f} USDT ({won(v['one_r_usdt'])}) | {pc(v['one_r_pct_of_equity'])} | {mu[2:]}R | {pc(v['p_cum_m12_by_30'])} | {pc(v['p_half_by_50'])} | {pc(v['p_half_by_100'])} | {pc(v['p_dd15_by_100'])} | {pc(v['p_profit_50'])} | {pc(v['p_profit_100'])} |")

# ---------------- LLM ----------------
P("")
P("#### T18. Claude 호출 1회 비용(추정) — 접두부 52K(캐시) + 바뀌는 입력 7.5K + 출력 6K 토큰")
P("| 모델 | 일반·캐시 적중 | 일반·캐시 없음 | 배치·캐시 적중 | 배치·캐시 없음 | 매시간 실운영 한 달(720회 + 캐시 유지) |")
P("|---|---:|---:|---:|---:|---:|")
for m, v in L["costs"].items():
    P(f"| {m} | ${v['std_cached']:.3f} | ${v['std_nocache']:.3f} | ${v['batch_cached']:.3f} | ${v['batch_nocache']:.3f} | ${v['live_month_hourly']:.0f} |")
ps = L["paired_sigma"]
P("")
P(f"짝 차이(엔진+Claude − 엔진)의 표준편차(R2 규칙 실측): 거부 30% → {ps['veto_f0.3']:.2f}R, 뒤집기 20% → {ps['flip_f0.2']:.2f}R (같은 시각 롱·숏 결과 상관 {ps['corr_long_short_same_hour']:+.2f}).")
P("")
P("#### T19. LLM 층 실험 후보 — 표본·검출 가능한 최소 효과(MDE, 단측 5%·검정력 80%)·비용")
P("| 실험 | 판단 시점 | 호출 수 | 비용(Opus 배치, 캐시 적중~없음) | Sonnet 배치 | 독립 표본 R1형 / R2형 | MDE 거부30% R1형 / R2형 | MDE 뒤집기20% R1형 / R2형 |")
P("|---|---:|---:|---:|---:|---:|---:|---:|")
for k, v in L["designs"].items():
    nn = lambda x: "—" if not np.isfinite(x) else f"{x:.0f}"  # noqa: E731
    mm = lambda x: "—" if not np.isfinite(x) else f"{x:.2f}R"  # noqa: E731
    P(f"| {k} | {v['points']:,} | {v['calls']:,} | ${v['cost_opus_batch_cached']:.0f}~{v['cost_opus_batch_nocache']:.0f} | ${v['cost_sonnet_batch_cached']:.0f} | {nn(v['n_eff_R1'])} / {nn(v['n_eff_R2'])} | {mm(v['mde_R1_veto30'])} / {mm(v['mde_R2_veto30'])} | {mm(v['mde_R1_flip20'])} / {mm(v['mde_R2_flip20'])} |")

(C.OUT / "tables.md").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
