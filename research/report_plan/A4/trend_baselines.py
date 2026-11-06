"""(a) 보유(buy & hold) + (b) 단순 추세 기준선 — 같은 비용, IS 2020~2023 / OOS 2024~2026-09.

단순 추세 규칙(8개 × 손절 유무 2 = 16개, 전부 보고)
- 신호 봉: 1d, 4h. 신호는 봉 마감에 계산, 실행 = 마감 + 5분 첫 실행 봉 시가(시장가, 테이커 + 슬리피지).
- MA  : SMA20 > SMA60 이면 롱, 아니면 숏(롱·숏) 또는 관망(롱·관망)
- MOM : 종가 > 20봉 전 종가 이면 롱, 아니면 숏/관망
- 손절 있음(S): 진입가 ∓ 2×ATR14(신호 봉). 손절되면 신호가 바뀔 때까지 쉰다. R = 이 손절 거리(+비용).
- 손절 없음(N): 신호가 바뀔 때만 청산. R은 같은 2×ATR14 거리의 '가상 R'(손실이 −1R을 넘을 수 있다).
자산 곡선: 1시간봉 종가로 평가(보유 중 평가손 포함). 사이징 두 가지
- '1배'  : 명목 = 자산(레버리지 1배, 매 거래 진입 때 다시 맞춤)
- '위험 1%': 수량 = 자산 × 1% ÷ R분모 (명목 ≤ 3배)
보유(B&H): 현물 보유(수수료 0.1% 1회), 무기한 1배 롱 보유(실제 펀딩 지불).
IS 자산 지표는 워밍업(60일) 뒤 2020-03-01부터 같은 창으로 맞춘다.

출력: out/trend_summary.json, out/trend_trades.csv.gz, out/trend_equity_daily.csv.gz
실행: /home/user/1111/.venv/bin/python trend_baselines.py
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

import common as C

ENTRY_DELAY = 5 * C.NS_MIN
EQ_IS_START = C.utc("2020-03-01")
WINDOWS = {"IS": (EQ_IS_START, C.IS_END), "OOS": (C.OOS_START, C.OOS_END), "ALL": (EQ_IS_START, C.OOS_END)}


def signals(tf: str, kind: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(결정 시각 = 봉 마감, 원신호 +1/−1, ATR14) — NaN 구간은 0."""
    b = C.load_tf(tf)
    if kind == "MA":
        f, s = C.sma(b.c, 20), C.sma(b.c, 60)
        raw = np.where(np.isfinite(f) & np.isfinite(s), np.where(f > s, 1, -1), 0)
    elif kind == "MOM":
        prev = np.concatenate([np.full(20, np.nan), b.c[:-20]])
        raw = np.where(np.isfinite(prev), np.where(b.c > prev, 1, -1), 0)
    else:
        raise ValueError(kind)
    return b.close_t, raw.astype(int), C.atr(b, 14)


def build_trades(eng: C.Engine, tf: str, kind: str, mode: str, stop: bool) -> pd.DataFrame:
    t, raw, a = signals(tf, kind)
    closes = C.load_tf(tf).c
    tgt = raw.copy()
    if mode == "LF":
        tgt[tgt < 0] = 0
    last_exec_t = int(eng.ex.t[-1])
    # 목표 포지션이 바뀌는 지점
    chg = np.nonzero(np.diff(np.concatenate([[0], tgt])) != 0)[0]
    rows = []
    for ci, i in enumerate(chg):
        side = int(tgt[i])
        if side == 0 or t[i] < C.IS_START or not np.isfinite(a[i]):
            continue
        start = int(t[i] + ENTRY_DELAY)
        if start >= last_exec_t:
            break
        nxt = chg[ci + 1] if ci + 1 < len(chg) else None
        exit_at = int(t[nxt] + ENTRY_DELAY) if nxt is not None else last_exec_t
        exit_at = min(exit_at, last_exec_t)
        dist = 2.0 * a[i]
        ref_guess = float(closes[i])
        rden_virtual = dist + C.FEE_TAKER * ref_guess + (C.FEE_TAKER + C.SLIP) * ref_guess
        if stop:
            o = eng.run(side, start, stop_dist=dist, max_hold_ns=50 * 365 * C.NS_DAY, exit_at=exit_at)
        else:
            o = eng.run(side, start, max_hold_ns=50 * 365 * C.NS_DAY, exit_at=exit_at, r_den_override=rden_virtual)
        if o.status != "filled":
            continue
        rows.append(dict(side=side, entry_t=o.entry_t, exit_t=o.exit_t, entry_px=o.entry_px, exit_px=o.exit_px,
                         r_den=o.r_den, r=o.r, kind=o.exit_kind, fund_r=o.fund_r, cost_r=o.cost_r,
                         mfe_r=o.mfe_r, mae_r=o.mae_r, open_at_end=(nxt is None)))
    return pd.DataFrame(rows)


def equity_curve(tr: pd.DataFrame, sizing: str, grid_t: np.ndarray, grid_c: np.ndarray) -> np.ndarray:
    """1시간 격자에서 자산(시작 1). 거래는 겹치지 않는다(규칙 하나 = 포지션 하나)."""
    eq = np.ones(len(grid_t))
    e = 1.0
    pos_from = 0
    for row in tr.itertuples(index=False):
        a = int(np.searchsorted(grid_t, row.entry_t, side="left"))
        b = int(np.searchsorted(grid_t, row.exit_t, side="left"))
        eq[pos_from:a] = e
        if sizing == "1x":
            qty = e / row.entry_px
        else:
            qty = min(e * 0.01 / row.r_den, 3.0 * e / row.entry_px)
        fee_in = C.FEE_TAKER * row.entry_px * qty
        if b > a:
            eq[a:b] = e - fee_in + qty * row.side * (grid_c[a:b] - row.entry_px)
        e = e + qty * row.r * row.r_den
        e = max(e, 1e-9)
        pos_from = b
    eq[pos_from:] = e
    return eq


def bh_curves(grid_t: np.ndarray, grid_c: np.ndarray, eng: C.Engine, t0: int) -> dict:
    """현물 보유·무기한 1배 롱 보유 (t0부터).

    무기한은 '명목 = 자산'을 매시간 유지(1배 재조정)한다고 보고, 그 시간에 낀 펀딩률만큼 자산에서 뺀다.
    (수량을 처음에 고정하면 가격이 오를수록 명목이 커져 펀딩이 시작 자산보다 커지는 왜곡이 생긴다 — 참고로만 따로 계산.)
    """
    i0 = int(np.searchsorted(grid_t, t0, side="left"))
    p0 = grid_c[i0]
    spot = grid_c / p0 * (1 - 0.001)
    fi = np.searchsorted(eng.ft, grid_t, side="right")
    fcum = eng.fcum[fi]                       # 펀딩률 누적합(가격 가중 없음)
    step_f = np.diff(fcum, prepend=fcum[0])   # 각 1시간에 낀 펀딩률
    ret = np.concatenate([[0.0], grid_c[1:] / grid_c[:-1] - 1])
    g = 1 + ret - step_f
    g[: i0 + 1] = 1.0
    perp = np.cumprod(g) * (1 - C.FEE_TAKER - C.SLIP)
    # 참고: 수량 고정(재조정 없음)
    a = int(np.searchsorted(eng.ft, grid_t[i0], side="right"))
    fund_cum = (eng.frpx_cum[fi] - eng.frpx_cum[a]) / p0
    perp_fixed = 1 + (grid_c - p0) / p0 - C.FEE_TAKER - C.SLIP - fund_cum
    for x in (spot, perp, perp_fixed):
        x[:i0] = np.nan
    return {"BH_spot": spot, "BH_perp1x": perp, "BH_perp_fixedqty": perp_fixed}


def win_metrics(grid_t, eq, w):
    a, b = WINDOWS[w]
    m = (grid_t >= a) & (grid_t < b) & np.isfinite(eq)
    return C.equity_metrics(grid_t[m], eq[m])


def main():
    eng = C.Engine()
    b1 = C.load_tf("1h")
    grid_t, grid_c = b1.close_t, b1.c
    rules = [(tf, k, md, st) for tf in ("1d", "4h") for k in ("MA", "MOM") for md in ("LF", "LS") for st in (True, False)]
    summary = {"rules": {}, "bh": {}}
    all_trades = []
    daily = {}
    for tf, k, md, st in rules:
        name = f"{tf}-{k}-{md}-{'S' if st else 'N'}"
        tr = build_trades(eng, tf, k, md, st)
        tr["rule"] = name
        all_trades.append(tr)
        res = {"tf": tf, "kind": k, "mode": md, "stop": st}
        for per, (a, b) in C.PERIODS.items():
            m = (tr["entry_t"] >= a) & (tr["entry_t"] < b)
            sub = tr[m]
            s = C.r_summary(sub["r"].to_numpy(), ((sub["exit_t"] - sub["entry_t"]) / C.NS_HOUR).to_numpy())
            s["trades_per_year"] = len(sub) / ((min(b, C.OOS_END) - max(a, EQ_IS_START if per == "IS" else a)) / (365 * C.NS_DAY))
            s["long_share"] = float((sub["side"] > 0).mean()) if len(sub) else float("nan")
            s["stop_rate"] = float((sub["kind"] == "stop").mean()) if len(sub) else float("nan")
            s["cost_r"] = float(sub["cost_r"].mean()) if len(sub) else float("nan")
            s["time_in_mkt"] = float(((sub["exit_t"] - sub["entry_t"]).sum()) / (min(b, C.OOS_END) - max(a, EQ_IS_START)))
            res[f"R_{per}"] = s
        for sizing in ("1x", "risk1"):
            eq = equity_curve(tr, sizing, grid_t, grid_c)
            for w in WINDOWS:
                res[f"EQ_{sizing}_{w}"] = win_metrics(grid_t, eq, w)
            daily[f"{name}_{sizing}"] = pd.Series(eq, index=pd.to_datetime(grid_t, unit="ns")).resample("1D").last()
        summary["rules"][name] = res
        print(name, "IS meanR", round(res["R_IS"].get("mean", float("nan")), 3), "OOS meanR",
              round(res["R_OOS"].get("mean", float("nan")), 3), "OOS 1x CAGR", round(res["EQ_1x_OOS"]["cagr"], 3), flush=True)
    for w, (a, b) in WINDOWS.items():
        curves = bh_curves(grid_t, grid_c, eng, a)
        for nm, eq in curves.items():
            summary["bh"].setdefault(nm, {})[w] = win_metrics(grid_t, eq, w)
            if w == "ALL":
                daily[nm] = pd.Series(eq, index=pd.to_datetime(grid_t, unit="ns")).resample("1D").last()
    pd.concat(all_trades).to_csv(C.OUT / "trend_trades.csv.gz", index=False)
    dd = pd.DataFrame(daily)
    dd.to_csv(C.OUT / "trend_equity_daily.csv.gz")
    summary["walk_forward"] = walk_forward(dd)
    (C.OUT / "trend_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=float))


def walk_forward(dd: pd.DataFrame) -> dict:
    """과최적화 시연: 지난 24개월 샤프 1등 규칙을 다음 6개월 쓰기 vs 16개 평균 vs IS 1등을 OOS에 그대로.

    사이징 '위험 1%' 곡선 16개를 쓴다(손절 없음 규칙은 가상 R 기준 위험 1%).
    """
    cols = [c for c in dd.columns if c.endswith("_risk1")]
    ret = dd[cols].pct_change()
    out = {}
    # IS(2020-03~2023) 샤프 순위 vs OOS 샤프 순위
    def sharpe(x):
        x = x.dropna()
        return float(x.mean() / x.std() * math.sqrt(365)) if len(x) > 30 and x.std() > 0 else float("nan")
    is_sh = {c: sharpe(ret.loc["2020-03-01":"2023-12-31", c]) for c in cols}
    oos_sh = {c: sharpe(ret.loc["2024-01-01":"2026-09-28", c]) for c in cols}
    s1 = pd.Series(is_sh).rank()
    s2 = pd.Series(oos_sh).rank()
    out["spearman_IS_vs_OOS_sharpe"] = float(np.corrcoef(s1, s2)[0, 1])
    best_is = max(is_sh, key=lambda c: is_sh[c])
    out["IS_best_rule"] = best_is
    out["IS_best_rule_IS_sharpe"] = is_sh[best_is]
    out["IS_best_rule_OOS_sharpe"] = oos_sh[best_is]
    out["OOS_rank_of_IS_best"] = int(pd.Series(oos_sh).rank(ascending=False)[best_is])
    out["OOS_best_rule"] = max(oos_sh, key=lambda c: oos_sh[c])
    out["OOS_best_sharpe"] = max(oos_sh.values())
    out["OOS_median_sharpe"] = float(np.nanmedian(list(oos_sh.values())))
    out["is_sharpe"] = is_sh
    out["oos_sharpe"] = oos_sh
    # 롤링 워크포워드: 2022-01부터 6개월마다, 직전 24개월 샤프 1등을 다음 6개월
    starts = pd.date_range("2022-01-01", "2026-07-01", freq="6MS")
    wf = []
    picks = []
    for s in starts:
        tr0 = s - pd.DateOffset(months=24)
        train = ret.loc[tr0: s - pd.Timedelta(days=1)]
        sh = {c: sharpe(train[c]) for c in cols}
        pick = max(sh, key=lambda c: (sh[c] if np.isfinite(sh[c]) else -9))
        test = ret.loc[s: s + pd.DateOffset(months=6) - pd.Timedelta(days=1)]
        wf.append(test[pick])
        picks.append((str(s.date()), pick, sh[pick], sharpe(test[pick])))
    wf_ret = pd.concat(wf)
    ew = ret.loc[wf_ret.index, cols].mean(axis=1)
    def cagr_mdd(x):
        e = (1 + x.fillna(0)).cumprod()
        yrs = (e.index[-1] - e.index[0]).days / 365
        return dict(cagr=float(e.iloc[-1] ** (1 / yrs) - 1), mdd=float((1 - e / e.cummax()).max()), sharpe=sharpe(x))
    out["wf_picks"] = picks
    out["wf_selected"] = cagr_mdd(wf_ret)
    out["wf_equal_weight_all16"] = cagr_mdd(ew)
    return out


if __name__ == "__main__":
    main()
