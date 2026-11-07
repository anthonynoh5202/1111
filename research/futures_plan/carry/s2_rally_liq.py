"""Task 4a: largest rallies over holding windows and liquidation of an UN-rebalanced isolated short.

Liquidation (isolated short, qty Q, entry P0, margin M = Q*P0/L, maintenance rate mmr):
    M + Q*(P0 - P) = mmr*Q*P  ->  P_liq/P0 = (1 + 1/L)/(1 + mmr)
Funding received (usually positive in rallies) would push P_liq slightly higher; ignored (conservative).
Two price series for the "high": mark proxy (max of 5m closes in the hour) and raw last-price high.
"""
import numpy as np
import pandas as pd
from common import load_klines, mark_proxy_hourly, OUT

MMR = 0.005
h = load_klines("1h").join(mark_proxy_hourly())
assert h.mhi.notna().all()
C = h.close
lines = []
P = lines.append

P("## A. Worst rallies / drops from any hourly close (2020-01-01 .. 2026-09-28)\n")
P("| window | worst rally (mark proxy) | start (close) | p99 | p95 | worst rally (raw high) | start | worst drop (mark proxy) | start |")
P("|---|---|---|---|---|---|---|---|---|")
wins = [(1, "1h"), (4, "4h"), (8, "8h"), (24, "24h"), (72, "3d"), (168, "7d"), (720, "30d"), (2160, "90d"),
        (4320, "180d"), (8760, "365d")]
R = {}
for W, name in wins:
    fm = h.mhi.rolling(W).max().shift(-W) / C - 1
    fr = h.high.rolling(W).max().shift(-W) / C - 1
    fd = h.mlo.rolling(W).min().shift(-W) / C - 1
    R[name] = fm
    P(f"| {name} | +{fm.max()*100:.1f}% | {fm.idxmax():%Y-%m-%d %H:%M} | +{fm.quantile(.99)*100:.1f}% | +{fm.quantile(.95)*100:.1f}% | "
      f"+{fr.max()*100:.1f}% | {fr.idxmax():%Y-%m-%d %H:%M} | {fd.min()*100:.1f}% | {fd.idxmin():%Y-%m-%d %H:%M} |")
P("")

P("## B. Liquidation distance of an isolated short at entry (no rebalancing, mmr 0.5%)\n")
Ls = [1, 2, 3, 5]
dL = {L: (1 + 1 / L) / (1 + MMR) - 1 for L in Ls}
P("| leverage | margin / notional | notional / total capital (spot fully paid) | rally to liquidation |")
P("|---|---|---|---|")
for L in Ls:
    P(f"| {L}x | {100/L:.0f}% | {L/(L+1)*100:.1f}% | +{dL[L]*100:.1f}% |")
P("")

P("## C. Share of entry times whose un-rebalanced short would have been liquidated within the window (mark proxy)\n")
P("| leverage | 1d | 7d | 30d | 90d | 180d | 365d |")
P("|---|---|---|---|---|---|---|")
for L in Ls:
    cells = []
    for name in ("24h", "7d", "30d", "90d", "180d", "365d"):
        x = R[name].dropna()
        cells.append(f"{(x >= dL[L]).mean()*100:.1f}%")
    P(f"| {L}x | " + " | ".join(cells) + " |")
P("")

# time to liquidation from each daily 00:00 start (hourly highs, mark proxy)
P("## D. Time until liquidation without any rebalancing (start at every daily 00:00 UTC close)\n")
hi = h.mhi.values
cl = C.values
times = h.index
starts = np.where(times.hour == 23)[0]  # bar opening 23:00 closes at 00:00
P("| leverage | starts | liquidated eventually | median days to liq. (if liq.) | fastest | share liq. within 90d | within 365d | example fastest start |")
P("|---|---|---|---|---|---|---|---|")
for L in Ls:
    k = 1 + dL[L]
    days = []
    for i in starts:
        seg = hi[i + 1:] >= k * cl[i]
        j = np.argmax(seg) if seg.any() else -1
        days.append(np.nan if j < 0 else (j + 1) / 24)
    d = pd.Series(days, index=times[starts])
    liq = d.notna()
    P(f"| {L}x | {len(d)} | {liq.mean()*100:.0f}% | {d.median():.0f} | {d.min():.2f}d | {(d<=90).mean()*100:.0f}% | {(d<=365).mean()*100:.0f}% | "
      f"{d.idxmin():%Y-%m-%d} |")
P("")

P("## E. Margin buffer needed to survive the worst observed rally between two checks\n")
P("Required liquidation distance d >= worst rally R over the reaction window. Since P_liq/P = (1+mr)/(1+mmr),\n"
  "the margin ratio (margin equity / notional) must never fall below mr_min = (1+R)(1+mmr) - 1 at a check time.\n")
P("| reaction window | worst rally (mark proxy) | mr_min | max effective leverage at a check | worst rally (raw high) | mr_min (raw) |")
P("|---|---|---|---|---|---|")
for W, name in wins[:5]:
    fm = R[name].max()
    fr = (h.high.rolling(W).max().shift(-W) / C - 1).max()
    mm = (1 + fm) * (1 + MMR) - 1
    mr = (1 + fr) * (1 + MMR) - 1
    P(f"| {name} | +{fm*100:.1f}% | {mm*100:.1f}% | {1/mm:.2f}x | +{fr*100:.1f}% | {mr*100:.1f}% |")
P("")
# excluding March 2020 (to show how much one event drives the result)
P("Same, excluding starts in 2020-03 (to show how much the COVID crash/rebound drives it):\n")
mask = ~((h.index.year == 2020) & (h.index.month == 3))
for W, name in wins[:5]:
    fm = R[name][mask].max()
    mm = (1 + fm) * (1 + MMR) - 1
    P(f"- {name}: worst rally +{fm*100:.1f}% (start {R[name][mask].idxmax():%Y-%m-%d %H:%M}) -> mr_min {mm*100:.1f}% (max eff. lev {1/mm:.2f}x)")
P("")

open(f"{OUT}/s2_rally.md", "w").write("\n".join(lines))
print("\n".join(lines))
