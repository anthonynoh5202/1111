"""Robustness: (a) daily manual check at each hour of the day (is 'no liquidation' luck?),
(b) idle-cash yield, (c) fresh entry/exit each calendar year, (d) liquidation event detail, (e) start-now windows."""
import itertools
import pandas as pd
from s3_backtest import simulate, VARIANTS
from common import OUT

lines = []
P = lines.append

P("## R1. Daily manual check at hour X (UTC), ALWAYS, band 0.5/2.0 — liquidations across the 24 possible check hours\n")
P("| L | liq price | check hours with >=1 liquidation | worst CAGR | best CAGR | worst max DD | dates of liquidations (first few) |")
P("|---|---|---|---|---|---|---|")
for L, liq in itertools.product((1, 2, 3), ("mark", "raw")):
    res = [simulate("ALWAYS", L, f"manual@{X}", liq=liq) for X in range(24)]
    bad = [X for X, r in zip(range(24), res) if r["nliq"] > 0]
    dates = sorted({str(t.date()) for r in res for t in r["_ev"].loc[r["_ev"].kind == "liq", "t"]})
    P(f"| {L}x | {liq} | {len(bad)}/24 {bad[:8]} | {min(r['cagr'] for r in res)*100:.2f}% | {max(r['cagr'] for r in res)*100:.2f}% | "
      f"{min(r['maxdd'] for r in res)*100:.1f}% | {', '.join(dates[:4])} |")
P("")
P("Same for a bot (hourly checks) with the tighter band 0.8/1.5 and the pre-declared 0.5/2.0:\n")
P("| L | band | liq price | liquidations | CAGR | max DD | rebalances |")
P("|---|---|---|---|---|---|---|")
for L, band, liq in itertools.product((2, 3), ((0.5, 2.0), (0.8, 1.5)), ("mark", "raw")):
    r = simulate("ALWAYS", L, "bot", liq=liq, band=band)
    P(f"| {L}x | {band[0]}/{band[1]} | {liq} | {r['nliq']} | {r['cagr']*100:.2f}% | {r['maxdd']*100:.1f}% | {r['rebal']} |")
P("")

P("## R2. Idle-cash yield sensitivity (L=2 bot, base costs): CAGR full period / last-24m APR\n")
P("| variant | idle 0% | idle 3% | idle 4% | time in market |")
P("|---|---|---|---|---|")
for v in VARIANTS:
    rs = [simulate(v, 2, "bot", idle_apr=a) for a in (0.0, 0.03, 0.04)]
    P(f"| {v} | " + " | ".join(f"{r['cagr']*100:.2f}% / {r['last24_apr']*100:.2f}%" for r in rs) + f" | {rs[0]['inmkt']*100:.0f}% |")
P("(FLIP_NEG: idle yield only applied while not short spot.)\n")

P("## R3. Fresh entry on Jan 1 and full exit on Dec 31 each year (ALWAYS, bot, base costs) — return on total capital\n")
P("| year | 1x | 2x | 3x |")
P("|---|---|---|---|")
for y in range(2020, 2027):
    a, b = (f"{y}-01-01", f"{y}-12-31 23:00") if y < 2026 else ("2026-01-01", "2026-08-31 16:00")
    if y == 2020:
        a = "2020-01-08"
    cells = []
    for L in (1, 2, 3):
        r = simulate("ALWAYS", L, "bot", start=a, end=b)
        cells.append(f"{r['total']*100:.2f}%" + (" (8m)" if y == 2026 else ""))
    P(f"| {y} | " + " | ".join(cells) + " |")
P("")

P("## R4. Start-now style windows (ALWAYS, bot, base costs, incl. entry+exit)\n")
P("| window | 1x | 2x | 3x |")
P("|---|---|---|---|")
for a, name in (("2024-09-01", "last 24m (2024-09..2026-08), annualised"), ("2025-09-01", "last 12m (2025-09..2026-08)"),
                ("2026-01-01", "2026 YTD (8 months), annualised")):
    cells = []
    for L in (1, 2, 3):
        r = simulate("ALWAYS", L, "bot", start=a)
        cells.append(f"{r['cagr']*100:.2f}%")
    P(f"| {name} | " + " | ".join(cells) + " |")
P("")

P("## R5. Liquidation event detail (raw last-price stress, ALWAYS 3x bot)\n")
r = simulate("ALWAYS", 3, "bot", liq="raw")
ev = r["_ev"]
E = r["_E"]
for t in ev.loc[ev.kind == "liq", "t"]:
    before = E[E.index < t].iloc[-1]
    after = E[E.index >= t].iloc[0]
    P(f"- {t}: equity {before:.4f} -> {after:.4f} ({(after/before-1)*100:.1f}% of total capital in that hour); "
      f"margin lost {ev[(ev.kind=='liq')&(ev.t==t)].amt.iloc[0]:.4f}")
P("")
open(f"{OUT}/s3c_robust.md", "w").write("\n".join(lines))
print("\n".join(lines))
