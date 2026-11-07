"""Format backtest outputs as Korean-headed markdown tables for the final note."""
import pandas as pd
from common import OUT

S = pd.read_csv(f"{OUT}/s3_summary.csv")
Y = pd.read_csv(f"{OUT}/s3_yearly.csv")
MKT = {2020: 0.1719, 2021: 0.3061, 2022: 0.0416, 2023: 0.0787, 2024: 0.1192, 2025: 0.0513, 2026: 0.0262}
lines = []
P = lines.append
f = lambda x, nd=1: f"{x*100:.{nd}f}%"

main = S[(S.cost == "base") & (S.liq == "mark") & (S.band == "0.5/2.0") & (S.basis == "proxy")]
P("### T1. 변형별 전체 기간 요약 (2x 격리, 봇=8시간 판단·1시간 점검, 기본 비용)\n")
P("| 변형 | 연복리(CAGR) | 최근 24개월 연율 | 최대낙폭(MTM) | 최악의 달 | 전환 횟수 | 리밸런싱 | 시장 참여 | 누적 펀딩 수입 | 누적 비용 |")
P("|---|---|---|---|---|---|---|---|---|---|")
for _, r in main[(main.L == 2) & (main["mode"] == "bot")].iterrows():
    P(f"| {r.variant} | {f(r.cagr,2)} | {f(r.last24_apr,2)} | {f(r.maxdd,2)} | {f(r.worst_month,2)} ({r.worst_month_at}) | {r.switches} | {r.rebal} | "
      f"{f(r.inmkt,0)} | {f(r.fund,1)} | {f(r.costs,1)} |")
P("")
P("### T2. 레버리지·점검 방식별 연복리 / 최근 24개월 연율 / 최대낙폭 / 청산 횟수 (총자본 기준, 기본 비용, 마크가격 프록시)\n")
P("| 변형 | 1x 봇 | 1x 수동(1일1회) | 2x 봇 | 2x 수동 | 3x 봇 | 3x 수동 |")
P("|---|---|---|---|---|---|---|")
for v in main.variant.unique():
    cells = []
    for L in (1, 2, 3):
        for mode in ("bot", "manual"):
            r = main[(main.variant == v) & (main.L == L) & (main["mode"] == mode)].iloc[0]
            cells.append(f"{f(r.cagr,1)} / {f(r.last24_apr,1)} / {f(r.maxdd,1)} / {r.nliq}")
    P(f"| {v} | " + " | ".join(cells) + " |")
P("")

P("### T3. 연도별 결과 — ALWAYS(항상 보유), 봇, 기본 비용\n")
P("| 연도 | 시장 펀딩 APR(명목) | L | 총자본 대비 펀딩 수입(연율) | 비용 | 베이시스·기타 | 순수익률(총자본, 연율) | 최악의 달 | 연중 최대낙폭 | 리밸런싱 |")
P("|---|---|---|---|---|---|---|---|---|---|")
for y in range(2020, 2027):
    for L in (1, 2, 3):
        r = Y[(Y.variant == "ALWAYS") & (Y.L == L) & (Y["mode"] == "bot") & (Y.year == y)].iloc[0]
        tag = " (8개월)" if y == 2026 else (" (1/7~)" if y == 2020 else "")
        P(f"| {y}{tag} | {f(MKT[y])} | {L}x | {f(r.fund_apr)} | -{f(r.cost,2)} | {f(r.basis_other,2)} | **{f(r.apr)}** | {f(r.worst_month,2)} | "
          f"{f(r.maxdd,2)} | {r.rebal} |")
P("")
P("### T4. 연도별 결과 — 모든 변형, 2x 봇, 기본 비용 (순수익률은 총자본 기준 연율)\n")
P("| 연도 | 변형 | 시장 참여 | 펀딩 수입(연율) | 비용 | 순수익률(연율) | 최악의 달 | 연중 최대낙폭 | 전환 | 리밸런싱 |")
P("|---|---|---|---|---|---|---|---|---|---|")
for y in range(2020, 2027):
    for v in ("ALWAYS", "GATE10", "GATE10_HYST", "FLAT_NEG", "FLIP_NEG", "DYN"):
        r = Y[(Y.variant == v) & (Y.L == 2) & (Y["mode"] == "bot") & (Y.year == y)].iloc[0]
        extra = f" (차입 -{f(r.borrow,2)})" if r.borrow > 0 else ""
        P(f"| {y} | {v} | {f(r.inmkt,0)} | {f(r.fund_apr)} | -{f(r.cost,2)}{extra} | **{f(r.apr)}** | {f(r.worst_month,2)} | {f(r.maxdd,2)} | "
          f"{r.switches} | {r.rebal} |")
P("")
P("### T5. 비용 시나리오 민감도 (2x 봇): 연복리 / 최근 24개월 연율\n")
P("| 변형 | 낙관(메이커, 0.093%/편도) | 기본(테이커+BNB, 0.16%/편도) | 보수(테이커, BNB 없음, 0.25%/편도) |")
P("|---|---|---|---|")
sub = S[(S.L == 2) & (S["mode"] == "bot") & (S.liq == "mark") & (S.band == "0.5/2.0") & (S.basis == "proxy")]
for v in main.variant.unique():
    cells = []
    for c in ("optimistic", "base", "conservative"):
        r = sub[(sub.variant == v) & (sub.cost == c)].iloc[0]
        cells.append(f"{f(r.cagr,2)} / {f(r.last24_apr,2)}")
    P(f"| {v} | " + " | ".join(cells) + " |")
P("")
P("### T6. 베이시스 근사 유무 비교 (2x 봇, 기본 비용): 연복리\n")
P("| 변형 | 베이시스=0 (현물=선물) | 베이시스 프록시(펀딩 역산 프리미엄) |")
P("|---|---|---|")
for v in main.variant.unique():
    a = S[(S.variant == v) & (S.L == 2) & (S["mode"] == "bot") & (S.basis == "zero")].iloc[0]
    b = sub[(sub.variant == v) & (sub.cost == "base")].iloc[0]
    P(f"| {v} | {f(a.cagr,2)} (MDD {f(a.maxdd,2)}) | {f(b.cagr,2)} (MDD {f(b.maxdd,2)}) |")
P("")
open(f"{OUT}/s5_tables.md", "w").write("\n".join(lines))
print("\n".join(lines))
