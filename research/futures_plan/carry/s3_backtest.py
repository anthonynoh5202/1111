"""Tasks 2-5: hourly backtest of BTC cash-and-carry (long spot + short BTCUSDT perp, isolated margin).

PRE-DECLARED VARIANTS (fixed before any backtest was run; signal m7 = mean of the last 21 settled
funding rates = trailing 7 days, evaluated right after each settlement; weight w applies until next decision):
  ALWAYS       w = 1 always
  GATE10       w = 1 if m7 >= 0.0100%/8h (~10.95% APR) else 0
  GATE10_HYST  enter when m7 >= 0.0100%, exit when m7 < 0.0050% (hysteresis to cut switching)
  FLAT_NEG     w = 1 unless m7 < 0 (then flat)
  FLIP_NEG     w = 1 if m7 >= 0 else -1 (reverse carry: borrowed spot short + long perp; BTC borrow 3% APR assumed)
  DYN          w = floor(4*clip(m7/0.0100%, 0, 1))/4  in {0, .25, .5, .75, 1}
Capital split for weight w and isolated leverage L:  notional N = |w| * E * L/(L+1) (spot fully paid),
perp margin = N/L, the rest idle USDT (0% yield assumed).
Rebalancing (pre-declared): at each check time, if margin ratio mr = margin equity / perp notional leaves
[0.5/L, 2/L], trade both legs back to target (fees on traded quantity). Bot: decisions every 8h, checks
hourly.  Manual: decisions and checks once a day at 00:00 UTC.
Spot approximation: spot S = perp close / (1 + basis proxy), basis proxy = funding-implied 8h-average premium
(see common.implied_premium). basis='zero' -> S = perp close.
Liquidation: isolated; mmr 0.5%; checked every hour against the mark-price proxy (max/min of 5m closes) or the
raw last-price high/low (stress). Liquidated margin is lost entirely; the spot leg stays unhedged until the next
check, then the book is re-established.
"""
import math
import os
import numpy as np
import pandas as pd
from common import load_funding, load_klines, mark_proxy_hourly, implied_premium, BASE, TOL, OUT, PER_YEAR

os.makedirs(OUT, exist_ok=True)
MMR = 0.005
COSTS = {  # per leg, per unit notional traded: (spot fee, perp fee, slippage per leg)
    "base": (0.00075, 0.00045, 0.0002),          # taker both legs, BNB discount, 2 bp slip/leg -> 0.16% one-way
    "conservative": (0.0010, 0.0005, 0.0005),    # taker, no BNB, 5 bp slip/leg -> 0.25% one-way
    "optimistic": (0.00075, 0.00018, 0.0),       # spot 0.075% (VIP0 maker=taker), perp maker w/ BNB, no slip -> 0.093%
}
BORROW_APR = 0.03


def rule(name):
    if name == "ALWAYS":
        return lambda m7, w: 1.0
    if name == "GATE10":
        return lambda m7, w: 1.0 if m7 >= BASE - TOL else 0.0
    if name == "GATE10_HYST":
        return lambda m7, w: (1.0 if m7 >= BASE - TOL else 0.0) if w == 0 else (1.0 if m7 >= 0.5 * BASE - TOL else 0.0)
    if name == "FLAT_NEG":
        return lambda m7, w: 1.0 if m7 >= -TOL else 0.0
    if name == "FLIP_NEG":
        return lambda m7, w: 1.0 if m7 >= -TOL else -1.0
    if name == "DYN":
        return lambda m7, w: math.floor(4 * min(max(m7 / BASE, 0.0), 1.0) + 1e-9) / 4
    raise ValueError(name)


VARIANTS = ["ALWAYS", "GATE10", "GATE10_HYST", "FLAT_NEG", "FLIP_NEG", "DYN"]


def build():
    f = load_funding()
    h = load_klines("1h").join(mark_proxy_hourly())
    h.index = h.index + pd.Timedelta(hours=1)  # index = bar CLOSE time
    h["rate"] = f.rate.reindex(h.index)
    h["m7"] = f.rate.rolling(21).mean().reindex(h.index)
    h["basis"] = implied_premium(f.rate).reindex(h.index, method="bfill")
    t0, t1 = f.index[20], f.index[-1]
    h = h.loc[(h.index >= t0 - pd.Timedelta(hours=1)) & (h.index <= t1)].copy()
    h["m7ff"] = h.m7.ffill()
    h["settle"] = h.rate.notna()
    h["midnight"] = h.index.hour == 0
    return h


H = build()


def simulate(variant="ALWAYS", L=2, mode="bot", cost="base", basis="proxy", liq="mark", band=(0.5, 2.0),
             keep_series=False, idle_apr=0.0, start=None, end=None):
    Hx = H
    if start is not None or end is not None:
        a = pd.Timestamp(start, tz="UTC") if start else H.index[0]
        b = pd.Timestamp(end, tz="UTC") if end else H.index[-1]
        Hx = H.loc[(H.index >= a - pd.Timedelta(hours=1)) & (H.index <= b)]
    fs, fp, sl = COSTS[cost]
    cs, cp = fs + sl, fp + sl
    F = Hx.close.values
    HI = (Hx.mhi if liq == "mark" else Hx.high).values
    LO = (Hx.mlo if liq == "mark" else Hx.low).values
    B = Hx.basis.values if basis == "proxy" else np.zeros(len(Hx))
    S_ = F / (1 + B)
    RATE = Hx.rate.values
    M7 = Hx.m7.values
    SET = Hx.settle.values
    MID = Hx.midnight.values
    idx = Hx.index
    n = len(Hx)
    if mode == "bot":
        decide, check = SET, np.ones(n, bool)
    elif mode == "manual":
        decide, check = SET & MID, MID
    elif mode.startswith("manual@"):
        hr = idx.hour == int(mode.split("@")[1])
        decide, check, M7 = hr, hr, Hx.m7ff.values
    else:
        raise ValueError(mode)
    rl = rule(variant)
    lo_b, hi_b = band[0] / L, band[1] / L

    u, sq, pq, m, w = 1.0, 0.0, 0.0, 0.0, 0.0
    pending = False
    E = np.empty(n)
    fund_acc = cost_acc = borrow_acc = 0.0
    ev = []  # (time, kind, amount)
    switches = onoff = rebal = nliq = 0
    inmkt = np.zeros(n, bool)
    E[0] = 1.0

    def trade_to(i, wt):
        nonlocal u, sq, pq, m, cost_acc
        S, Fx = S_[i], F[i]
        Eq = u + sq * S + m
        N = abs(wt) * Eq * L / (L + 1)
        sq_t = (N / S) * (1 if wt > 0 else -1) if wt != 0 else 0.0
        pq_t = -sq_t
        m_t = abs(pq_t) * Fx / L
        c = abs(sq_t - sq) * S * cs + abs(pq_t - pq) * Fx * cp
        u = u - (sq_t - sq) * S - (m_t - m) - c
        sq, pq, m = sq_t, pq_t, m_t
        cost_acc += c
        ev.append((idx[i], "cost", c))

    for i in range(1, n):
        Fx, Fprev = F[i], F[i - 1]
        liq_now = False
        if pq != 0.0:
            Q = abs(pq)
            if pq < 0:
                pl = (m + Q * Fprev) / (Q * (1 + MMR))
                liq_now = HI[i] >= pl
            else:
                pl = (Q * Fprev - m) / (Q * (1 - MMR))
                liq_now = LO[i] <= pl
            if liq_now:
                ev.append((idx[i], "liq", m + pq * (pl - Fprev)))  # margin left at liquidation (lost)
                m, pq = 0.0, 0.0
                nliq += 1
                pending = True
            else:
                m += pq * (Fx - Fprev)
        if SET[i] and pq != 0.0:
            fu = -pq * Fx * RATE[i]
            m += fu
            fund_acc += fu
            ev.append((idx[i], "fund", fu))
        if idle_apr and sq >= 0 and u > 0:
            iy = u * idle_apr / 8760
            u += iy
            ev.append((idx[i], "idle", iy))
        if sq < 0:
            b_ = (-sq) * S_[i] * BORROW_APR / 8760
            u -= b_
            borrow_acc += b_
            ev.append((idx[i], "borrow", b_))
        acted = False
        if decide[i] and not np.isnan(M7[i]):
            wn = rl(M7[i], w)
            if wn != w:
                switches += 1
                onoff += int((wn == 0) != (w == 0) or (wn * w < 0))
                ev.append((idx[i], "switch", 1.0))
                w = wn
                trade_to(i, w)
                acted = True
                pending = False
        if not acted and pending and (check[i] or decide[i]):
            trade_to(i, w)
            pending = False
            acted = True
        if not acted and check[i] and pq != 0.0:
            mr = m / (abs(pq) * Fx)
            if mr < lo_b or mr > hi_b:
                trade_to(i, w)
                rebal += 1
                ev.append((idx[i], "rebal", 1.0))
        inmkt[i] = pq != 0.0
        E[i] = u + sq * S_[i] + m
    # final exit
    Efinal_mtm = E[-1]
    if pq != 0.0 or sq != 0.0:
        trade_to(n - 1, 0.0)
    Eend = u + sq * S_[-1] + m
    Es = pd.Series(E, index=idx)
    evdf = pd.DataFrame(ev, columns=["t", "kind", "amt"])
    res = dict(variant=variant, L=L, mode=mode, cost=cost, basis=basis, liq=liq, band=f"{band[0]}/{band[1]}",
               Eend=Eend, Emtm=Efinal_mtm, switches=switches, onoff=onoff, rebal=rebal, nliq=nliq,
               inmkt=inmkt[1:].mean(), fund=fund_acc, costs=cost_acc, borrow=borrow_acc)
    res.update(metrics(Es, Eend))
    if keep_series:
        res["E"] = Es
        res["ev"] = evdf
        res["inmkt_s"] = pd.Series(inmkt, index=idx)
    res["_E"], res["_ev"], res["_in"] = Es, evdf, pd.Series(inmkt, index=idx)
    return res


def maxdd(s):
    return (s / s.cummax() - 1).min()


def metrics(Es, Eend):
    yrs = (Es.index[-1] - Es.index[0]).total_seconds() / (365 * 86400)
    cut = max(pd.Timestamp("2024-09-01", tz="UTC"), Es.index[0])
    e24a = Es[Es.index <= cut].iloc[-1]
    y24 = (Es.index[-1] - cut).total_seconds() / (365 * 86400)
    me = Es.resample("ME").last()
    mret = me.pct_change()
    mret.iloc[0] = me.iloc[0] / Es.iloc[0] - 1
    return dict(years=yrs, total=Eend - 1, cagr=Eend ** (1 / yrs) - 1, apr_simple=(Eend - 1) / yrs,
                last24_apr=(Es.iloc[-1] / e24a) ** (1 / y24) - 1, maxdd=maxdd(Es), worst_month=mret.min(),
                worst_month_at=mret.idxmin().strftime("%Y-%m"), neg_months=int((mret < 0).sum()))


def yearly(r):
    Es, ev, inm = r["_E"], r["_ev"], r["_in"]
    ev = ev.copy()
    ev["y"] = pd.DatetimeIndex(ev.t).year
    rows = []
    prev_end = Es.iloc[0]
    for y in sorted(set(Es.index.year)):
        s = Es[Es.index.year == y]
        start_val = prev_end
        end_val = s.iloc[-1]
        last = y == Es.index[-1].year
        if last:
            end_val = r["Eend"]  # include final exit cost in the last (partial) year
        days = (s.index[-1] - max(s.index[0] - pd.Timedelta(hours=1), Es.index[0])).total_seconds() / 86400
        e = ev[ev.y == y]
        fund = e[e.kind == "fund"].amt.sum() / start_val
        cost = e[e.kind == "cost"].amt.sum() / start_val
        brw = e[e.kind == "borrow"].amt.sum() / start_val
        ret = end_val / start_val - 1
        path = pd.concat([pd.Series([start_val]), s.reset_index(drop=True)])
        me = s.resample("ME").last()
        mret = pd.concat([pd.Series([start_val]), me.reset_index(drop=True)]).pct_change().dropna()
        rows.append(dict(year=y, days=round(days), ret=ret, apr=ret * 365 / days, fund_apr=fund * 365 / days,
                         cost=cost, borrow=brw, basis_other=ret - fund + cost + brw,
                         liq_margin_lost=e[e.kind == "liq"].amt.sum() / start_val, worst_month=mret.min(),
                         maxdd=maxdd(path), inmkt=inm[inm.index.year == y].mean(),
                         switches=int((e.kind == "switch").sum()), rebal=int((e.kind == "rebal").sum()),
                         nliq=int((e.kind == "liq").sum())))
        prev_end = s.iloc[-1]
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import itertools, time
    t = time.time()
    runs = []
    keep = {}
    for v, L, mode in itertools.product(VARIANTS, (1, 2, 3), ("bot", "manual")):
        r = simulate(v, L, mode)
        runs.append(r)
        keep[(v, L, mode, "base", "proxy", "mark", "0.5/2.0")] = r
    for L, mode in itertools.product((1, 2, 3), ("bot", "manual")):
        runs.append(simulate("ALWAYS", L, mode, liq="raw"))
        runs.append(simulate("GATE10_HYST", L, mode, liq="raw"))
    for v, c in itertools.product(VARIANTS, ("conservative", "optimistic")):
        runs.append(simulate(v, 2, "bot", cost=c))
    for v, L, mode in itertools.product(("ALWAYS", "GATE10_HYST", "FLAT_NEG"), (2, 3), ("bot", "manual")):
        runs.append(simulate(v, L, mode, band=(0.8, 1.5)))
    for v in VARIANTS:
        runs.append(simulate(v, 2, "bot", basis="zero"))
    cols = [k for k in runs[0] if not k.startswith("_")]
    df = pd.DataFrame([{k: r[k] for k in cols} for r in runs])
    df.to_csv(f"{OUT}/s3_summary.csv", index=False)
    # yearly tables for every main-grid run
    allyr = []
    for key, r in keep.items():
        y = yearly(r)
        for c in ("variant", "L", "mode"):
            y[c] = r[c]
        allyr.append(y)
    pd.concat(allyr).to_csv(f"{OUT}/s3_yearly.csv", index=False)
    import pickle
    pickle.dump({k: (r["_E"], r["_ev"]) for k, r in keep.items()}, open(f"{OUT}/s3_series.pkl", "wb"))
    print(f"{len(runs)} runs in {time.time()-t:.0f}s")
    pd.set_option("display.width", 250)
    print(df.drop(columns=["basis"]).to_string(float_format=lambda x: f"{x:.4f}"))
