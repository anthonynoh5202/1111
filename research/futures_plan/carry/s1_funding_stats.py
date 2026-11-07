"""Task 1: funding statistics for Binance BTCUSDT perpetual (8h funding), 2020-01-01 .. 2026-08-31."""
import os
import numpy as np
import pandas as pd
from common import load_funding, daily_regime, BASE, PER_YEAR, TOL, OUT, pct

os.makedirs(OUT, exist_ok=True)
f = load_funding()
r = f.rate
lines = []
P = lines.append


def apr(x):
    return x.mean() * PER_YEAR


def cats(x):
    return {
        "neg(<0)": (x < -TOL).mean(),
        "zero": (x.abs() <= TOL).mean(),
        "(0,base)": ((x > TOL) & (x < BASE - TOL)).mean(),
        "=base 0.01%": ((x - BASE).abs() <= TOL).mean(),
        ">base": (x > BASE + TOL).mean(),
        ">=0.03%": (x >= 0.0003 - TOL).mean(),
        ">=0.05%": (x >= 0.0005 - TOL).mean(),
        ">=0.10%": (x >= 0.0010 - TOL).mean(),
    }


# ---------- 1. overall ----------
P(f"## 1. Overall ({r.index[0]:%Y-%m-%d} .. {r.index[-1]:%Y-%m-%d %H:%M}, n={len(r)} intervals)\n")
P(f"- mean per 8h = {r.mean()*100:.4f}%  -> simple APR = {pct(apr(r))}; median = {r.median()*100:.4f}%; std = {r.std()*100:.4f}%")
P(f"- compounded (reinvested every 8h) APR = {pct((1+r).prod()**(PER_YEAR/len(r))-1)}")
q = r.quantile([.01, .05, .10, .25, .5, .75, .90, .95, .99])
P("- percentiles (per 8h): " + ", ".join(f"p{int(k*100)}={v*100:.4f}%" for k, v in q.items()))
P(f"- min {r.min()*100:.3f}% at {r.idxmin():%Y-%m-%d %H:%M}; max {r.max()*100:.3f}% at {r.idxmax():%Y-%m-%d %H:%M}")
P("- share of intervals: " + ", ".join(f"{k} {pct(v,1)}" for k, v in cats(r).items()))
P("")

# ---------- 2. by year ----------
P("## 2. By calendar year\n")
P("| year | n | APR (simple) | median/8h | std/8h | neg share | =0.01% share | >0.01% share | (0,0.01%) share | worst 7d-avg APR | best 7d-avg APR |")
P("|---|---|---|---|---|---|---|---|---|---|---|")
m7 = r.rolling(21).mean()
for y, x in r.groupby(r.index.year):
    c = cats(x)
    mm = m7[m7.index.year == y]
    P(f"| {y} | {len(x)} | {pct(apr(x))} | {x.median()*100:.4f}% | {x.std()*100:.4f}% | {pct(c['neg(<0)'],1)} | "
      f"{pct(c['=base 0.01%'],1)} | {pct(c['>base'],1)} | {pct(c['(0,base)'],1)} | {pct(mm.min()*PER_YEAR,1)} | {pct(mm.max()*PER_YEAR,1)} |")
P("")

# ---------- 3. year x month APR ----------
P("## 3. Annualised funding APR by month (simple, mean x 1095)\n")
mon = r.groupby([r.index.year, r.index.month]).mean() * PER_YEAR
tab = mon.unstack()
P("| year | " + " | ".join(f"{m:02d}" for m in range(1, 13)) + " |")
P("|---|" + "---|" * 12)
for y, row in tab.iterrows():
    P(f"| {y} | " + " | ".join("" if pd.isna(v) else f"{v*100:.1f}" for v in row.values) + " |")
P("")
P(f"- months: {mon.size}; negative-APR months: {(mon<0).sum()} ({pct((mon<0).mean(),1)}); months below 5% APR: {(mon<0.05).sum()}; "
  f"months >= 20% APR: {(mon>=0.20).sum()}")
P(f"- worst month {mon.idxmin()} {pct(mon.min(),1)}; best month {mon.idxmax()} {pct(mon.max(),1)}; median month {pct(mon.median(),1)}")
P("")

# ---------- 4. negative streaks ----------
def streaks(mask: pd.Series, values: pd.Series):
    out, start, n = [], None, 0
    idx = mask.index
    arr = mask.values
    for i, v in enumerate(arr):
        if v:
            if start is None:
                start = i
            n += 1
        elif start is not None:
            out.append((start, i - 1))
            start, n = None, 0
    if start is not None:
        out.append((start, len(arr) - 1))
    rows = []
    for a, b in out:
        seg = values.iloc[a:b + 1]
        rows.append(dict(start=idx[a], end=idx[b], n=b - a + 1, days=(b - a + 1) / 3,
                         cum=seg.sum(), worst=seg.min()))
    return pd.DataFrame(rows).sort_values("n", ascending=False)


neg = streaks(r < -TOL, r)
P("## 4. Longest streaks of consecutive negative funding intervals\n")
P(f"- number of negative streaks: {len(neg)}; streaks >= 9 intervals (3 days): {(neg.n>=9).sum()}; >= 21 (7 days): {(neg.n>=21).sum()}")
P("| rank | first negative settlement | last | intervals | days | cumulative funding (short pays) | worst single |")
P("|---|---|---|---|---|---|---|")
for i, row in enumerate(neg.head(10).itertuples(), 1):
    P(f"| {i} | {row.start:%Y-%m-%d %H:%M} | {row.end:%Y-%m-%d %H:%M} | {row.n} | {row.days:.1f} | {row.cum*100:.3f}% | {row.worst*100:.3f}% |")
P("")
negm7 = streaks(m7 < -TOL, m7)
P("### 4b. Episodes with trailing-7d average funding < 0\n")
P(f"- share of settlements with 7d avg < 0: {pct((m7 < -TOL).mean(),1)}; episodes: {len(negm7)}")
P("| rank | start | end | days | worst 7d avg (APR) |")
P("|---|---|---|---|---|")
for i, row in enumerate(negm7.head(6).itertuples(), 1):
    P(f"| {i} | {row.start:%Y-%m-%d} | {row.end:%Y-%m-%d} | {row.days:.1f} | {pct(row.worst*PER_YEAR,1)} |")
P("")
# worst rolling windows of cumulative funding (what a short-perp holder pays in the worst stretch)
P("### 4c. Worst cumulative funding over rolling windows (always-short perp, % of notional)\n")
for d in (1, 7, 30, 90, 180, 365):
    s = r.rolling(3 * d).sum()
    P(f"- worst {d}d: {s.min()*100:.3f}% (window ending {s.idxmin():%Y-%m-%d}); best {d}d: {s.max()*100:.2f}%")
P("")

# ---------- 5. regimes ----------
reg = daily_regime()
start_day = (r.index - pd.Timedelta(hours=8)).floor("D")
bull = pd.Series(reg.reindex(start_day).values, index=r.index)
P("## 5. Bull vs bear regime (previous daily close vs its 200-day SMA; defined from "
  f"{bull.first_valid_index():%Y-%m-%d})\n")
P("| regime | share of time | APR | median/8h | neg share | >0.01% share | p05/8h | p95/8h |")
P("|---|---|---|---|---|---|---|---|")
valid = bull.notna()
for name, mask in (("above SMA200 (bull)", valid & (bull == True)), ("below SMA200 (bear)", valid & (bull == False)),
                   ("SMA200 n/a (2020 H1)", ~valid)):
    x = r[mask]
    c = cats(x)
    P(f"| {name} | {pct(mask.mean(),1)} | {pct(apr(x))} | {x.median()*100:.4f}% | {pct(c['neg(<0)'],1)} | {pct(c['>base'],1)} | "
      f"{x.quantile(.05)*100:.4f}% | {x.quantile(.95)*100:.4f}% |")
P("")
P("By year and regime (APR):\n")
P("| year | bull APR | bull share | bear APR | bear share |")
P("|---|---|---|---|---|")
for y in sorted(set(r.index.year)):
    yb = (r.index.year == y)
    xb, xr = r[yb & valid.values & (bull == True).values], r[yb & valid.values & (bull == False).values]
    P(f"| {y} | {pct(apr(xb),1) if len(xb) else '-'} | {pct(len(xb)/yb.sum(),0)} | {pct(apr(xr),1) if len(xr) else '-'} | {pct(len(xr)/yb.sum(),0)} |")
P("")

# ---------- 6. last 24 months vs earlier ----------
cut = pd.Timestamp("2024-09-01", tz="UTC")
P(f"## 6. Last 24 months ({cut:%Y-%m-%d} .. 2026-08-31) vs earlier\n")
P("| period | n | APR | median/8h | std/8h | neg share | =0.01% | >0.01% | (0,0.01%) | >=0.03% |")
P("|---|---|---|---|---|---|---|---|---|---|")
for name, x in (("2020-01..2024-08", r[r.index < cut]), ("2024-09..2026-08 (last 24m)", r[r.index >= cut]),
                ("last 12m (2025-09..2026-08)", r[r.index >= pd.Timestamp('2025-09-01', tz='UTC')])):
    c = cats(x)
    P(f"| {name} | {len(x)} | {pct(apr(x))} | {x.median()*100:.4f}% | {x.std()*100:.4f}% | {pct(c['neg(<0)'],1)} | "
      f"{pct(c['=base 0.01%'],1)} | {pct(c['>base'],1)} | {pct(c['(0,base)'],1)} | {pct(c['>=0.03%'],1)} |")
P("")

# ---------- 7. persistence (is funding predictable enough to time?) ----------
P("## 7. Persistence of the 7-day average (for timing rules)\n")
nxt = m7.shift(-21)  # the NEXT non-overlapping 7d average
ok = m7.notna() & nxt.notna()
for name, cond in (("7d avg < 0", m7 < -TOL), ("0 <= 7d avg < 0.01%", (m7 >= -TOL) & (m7 < BASE - TOL)),
                   ("7d avg >= 0.01%", m7 >= BASE - TOL), ("7d avg >= 0.02%", m7 >= 2 * BASE - TOL)):
    c = cond & ok
    P(f"- now {name} ({pct(c.mean(),1)} of time): next-7d avg APR mean {pct(nxt[c].mean()*PER_YEAR,1)}, "
      f"P(next<0)={pct((nxt[c] < -TOL).mean(),0)}, P(next>=0.01%)={pct((nxt[c] >= BASE-TOL).mean(),0)}")
P(f"- corr(7d avg, next 7d avg) = {m7[ok].corr(nxt[ok]):.2f}")
P("")

open(f"{OUT}/s1_funding.md", "w").write("\n".join(lines))
print("\n".join(lines))
