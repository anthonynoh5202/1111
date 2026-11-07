"""Task 7: KRW income per capital tier and minimum capital under Binance order-size rules (ASSUMED, unverified):
perp BTCUSDT min notional 50 USDT, qty step / min qty 0.001 BTC; spot BTCUSDT step 0.00001 BTC, min notional 5 USDT.
FX assumption: 1 USDT = 1,400 KRW (no kimchi premium). Income = pre-tax, before KRW<->USDT transfer costs.
APR inputs come from s3/s3c results (ALWAYS, bot, base costs)."""
import math
from common import OUT

FX = 1400.0
P = 83461.0  # last BTCUSDT perp close in the data (2026-09-28 23:00 UTC)
STEP = 0.001
apr = {  # (1x, 2x) net APR on total capital, from the backtest
    "full 2020-01..2026-08 CAGR": (0.0633, 0.0814),
    "best year 2021 (fresh entry)": (0.1707, 0.2237),
    "2024 (fresh entry)": (0.0674, 0.0830),
    "2025 (fresh entry)": (0.0270, 0.0321),
    "last 24m annualised": (0.0246, 0.0328),
    "last 12m (2025-09..2026-08)": (0.0133, 0.0186),
    "2026 YTD annualised": (0.0104, 0.0132),
}
lines = []
W = lines.append
W(f"Assumptions: 1 USDT = {FX:,.0f} KRW; BTC = {P:,.0f} USDT; perp qty step {STEP} BTC; min notional 50 USDT (unverified).\n")
W("## S1. Position size actually placeable per capital tier\n")
W("| capital (KRW) | USDT | L | target notional | perp qty (rounded down to 0.001) | placed notional | capital utilisation vs target | 1 step as % of position |")
W("|---|---|---|---|---|---|---|---|")
for krw in (1_000_000, 10_000_000, 100_000_000):
    usd = krw / FX
    for L in (1, 2):
        N = usd * L / (L + 1)
        q = math.floor(N / P / STEP + 1e-9) * STEP
        W(f"| {krw:,} | {usd:,.0f} | {L}x | {N:,.0f} | {q:.3f} | {q*P:,.0f} | {q*P/N*100:.0f}% | {STEP/q*100 if q else float('nan'):.1f}% |")
W("")
W("## S2. Monthly income in KRW (pre-tax; scales with placed notional)\n")
W("| scenario | 100만 1x | 100만 2x | 1,000만 1x | 1,000만 2x | 1억 1x | 1억 2x |")
W("|---|---|---|---|---|---|---|")
for name, (a1, a2) in apr.items():
    cells = []
    for krw in (1_000_000, 10_000_000, 100_000_000):
        usd = krw / FX
        for L, a in ((1, a1), (2, a2)):
            N = usd * L / (L + 1)
            q = math.floor(N / P / STEP + 1e-9) * STEP
            util = q * P / N
            cells.append(f"{krw * a * util / 12:,.0f}")
    W(f"| {name} | " + " | ".join(cells) + " |")
W("")
W("## S3. Minimum capital\n")
for L in (1, 2, 3):
    q_min = max(STEP, math.ceil(50 / P / STEP) * STEP)
    cap = q_min * P * (1 + 1 / L)
    q_prac = 0.02
    cap_p = q_prac * P * (1 + 1 / L)
    W(f"- {L}x: smallest hedge {q_min:.3f} BTC = {q_min*P:,.0f} USDT notional -> capital {cap:,.0f} USDT (~{cap*FX/1e4:,.0f}만 원) "
      f"+ ~5-10 USDT of BNB for fees. Practical minimum so one 0.001 step is <=5% of the position (0.02 BTC): "
      f"{cap_p:,.0f} USDT (~{cap_p*FX/1e4:,.0f}만 원).")
W("- If the old 100 USDT min notional still applied, the smallest perp order would be 0.002 BTC "
  f"({0.002*P:,.0f} USDT): minimums double.")
W("")
W("## S4. Fixed transfer costs vs income (illustrative; fees are ASSUMPTIONS)\n")
for krw in (1_000_000, 10_000_000, 100_000_000):
    usd = krw / FX
    fixed = 2 * 1.0 + 2 * 0.0005 * usd  # 1 USDT network fee each way + 0.05% KRW-market fee each way
    for L, a in ((2, 0.0186),):
        monthly = usd * a / 12
        W(f"- {krw:,} KRW: round-trip fixed cost ~{fixed:,.1f} USDT ({fixed/usd*100:.2f}% of capital) = "
          f"{fixed/monthly:.1f} months of last-12m income at 2x; a 1%p kimchi-premium swing = {0.01*usd:,.0f} USDT "
          f"= {0.01*usd/monthly:.1f} months of income.")
W("")
open(f"{OUT}/s4_scale.md", "w").write("\n".join(lines))
print("\n".join(lines))
