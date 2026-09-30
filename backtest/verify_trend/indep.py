"""TREND_SPEC v1.0 독립 재구현 (검증용). backtest 패키지를 import 하지 않는다.

원자료(data/binance/*.csv.gz)와 docs/TREND_SPEC.md, 그리고 명세가 위임한 RULES_SPEC §12 / DESIGN.md 해석
(I-29 R 분모, I-31 진입 봉 경계, I-33 갭 손절, I-35 펀딩 창·가격, I-36 데이터 끝)만 보고 다시 짠 것이다.
구현(backtest/trend.py)과 일부러 다른 구조를 쓴다: 하위 시스템을 '하루씩 넘기는 상태 기계'로 돌린다
(구현은 '다음에 볼 날로 건너뛰기' 방식).

규칙 요약 (근거)
- U_N[t] = max(close[t-N..t-1]), D_N[t] = min(...)            TREND §1 (당일 제외)
- 롱 진입 close[t] > U_N, 숏 진입 close[t] < D_N               TREND §1
- 롱 청산 close[t] < D_M, 숏 청산 close[t] > U_M, M = 10/28/50  TREND §1
- ATR20[t] = mean(TR[t-20..t-1]), TR[0] 없음                    TREND §2 + RULES §3 (현재 봉 제외)
- 판단 = close_ns[t] + 60초, 활성 = 판단 + L                     TREND §1·§2
- 실행 봉: open < 2023-10-01 → 5분봉, 이후 1분봉                  RULES §12.1
- E0: 활성 이후 '시작하는' 첫 실행 봉 시가, 테이커 0.05% + 슬리피지 0.02%
- E1: 지정가 = round(돌파 레벨, 0.1), 롱 low < 지정가(관통), 봉 끝 ≤ 주문 수명(I-31),
      수명 = min(신호 마감 + 5일, 청산 신호 판단 시각), 메이커 0.02%
- 손절 = round(진입가 ∓ k × ATR20[t], 0.1). 닿으면(롱 low ≤ 손절) 청산, 체결 봉부터.
  갭: 체결 봉 뒤(또는 시장가 체결 봉)에서 시가가 이미 너머면 시가(I-33)
- 추세 청산: 청산 신호 봉 k의 판단 + L 이후 시작하는 첫 실행 봉 시가(체결 봉 뒤), 테이커 + 슬리피지
- 데이터 끝: 마지막 실행 봉 종가(I-36)
- 펀딩: start < f ≤ 청산 봉 시작, start = 체결 봉 시작(시장가는 min(체결 봉 시작, 활성)), 가격 = f를 포함하는
  실행 봉 시가, 지불분만 × 비용 배수 (RULES §12.2, I-35). 2026-09-01 이후 실데이터 없는 8시간 격자 = 0.0001
- R 분모 = |진입 − 손절| + 진입 수수료 + (테이커 + 슬리피지) × 손절 [+ E0 진입 슬리피지 (구현 T-6)], 기본 비용
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA = os.path.join(ROOT, "data", "binance")
NS_MIN = 60 * 10**9
NS_DAY = 86400 * 10**9
SWITCH_NS = int(pd.Timestamp("2023-10-01", tz="UTC").value)
FUND_FALLBACK_FROM = int(pd.Timestamp("2026-09-01", tz="UTC").value)
TAKER, MAKER, SLIP = 0.0005, 0.0002, 0.0002
FUND_FALLBACK = 0.0001


def _read(name, cols=("open_time", "open", "high", "low", "close")):
    df = pd.read_csv(os.path.join(DATA, name), usecols=list(cols))
    return df


def _bars(df, dur_ns):
    o_ns = df["open_time"].to_numpy(np.int64) * 10**6
    return dict(open_ns=o_ns, close_ns=o_ns + dur_ns, open=df["open"].to_numpy(np.float64),
                high=df["high"].to_numpy(np.float64), low=df["low"].to_numpy(np.float64),
                close=df["close"].to_numpy(np.float64))


def load_all(cache_path: str | None = None):
    """(daily, exec, funding) dict 3개. cache_path가 있으면 npz로 저장·재사용(원자료 크기·시각 서명)."""
    files = ["BTCUSDT_1d.csv.gz", "BTCUSDT_5m.csv.gz", "BTCUSDT_fundingRate.csv.gz"] + \
            [f"BTCUSDT_1m_{y}.csv.gz" for y in (2023, 2024, 2025, 2026)]
    sig = "|".join(f"{f}:{os.path.getsize(os.path.join(DATA, f))}:{int(os.path.getmtime(os.path.join(DATA, f)))}"
                   for f in files)
    if cache_path and os.path.exists(cache_path):
        z = np.load(cache_path, allow_pickle=False)
        if str(z["sig"]) == sig:
            d = {k[2:]: z[k] for k in z.files if k.startswith("d_")}
            x = {k[2:]: z[k] for k in z.files if k.startswith("x_")}
            f = {k[2:]: z[k] for k in z.files if k.startswith("f_")}
            return d, x, f
    daily = _bars(_read("BTCUSDT_1d.csv.gz"), NS_DAY)
    b5 = _bars(_read("BTCUSDT_5m.csv.gz"), 5 * NS_MIN)
    keep = b5["open_ns"] < SWITCH_NS
    b5 = {k: v[keep] for k, v in b5.items()}
    m1 = [_bars(_read(f"BTCUSDT_1m_{y}.csv.gz"), NS_MIN) for y in (2023, 2024, 2025, 2026)]
    ex = {k: np.concatenate([b5[k]] + [m[k] for m in m1]) for k in b5}
    ex_keep = np.r_[True, np.diff(ex["open_ns"]) > 0]
    assert ex_keep.all(), "실행 봉 중복"
    assert (ex["close_ns"][:-1] == ex["open_ns"][1:]).all(), "실행 봉 빈 구간"
    assert (ex["open_ns"][ex["open_ns"] >= SWITCH_NS][0] == SWITCH_NS)
    fr = pd.read_csv(os.path.join(DATA, "BTCUSDT_fundingRate.csv.gz"))
    t = (fr["calc_time"].to_numpy(np.int64) // 3_600_000) * 3_600_000 * 10**6   # 정시로 내림
    r = fr["last_funding_rate"].to_numpy(np.float64)
    until = int(ex["close_ns"][-1])
    g = max(FUND_FALLBACK_FROM, int(t[-1]) + 1)
    # 8시간 격자(00·08·16 UTC)에서 g 이상 첫 시각
    g = ((g + 8 * 3600 * 10**9 - 1) // (8 * 3600 * 10**9)) * (8 * 3600 * 10**9)
    syn = np.arange(g, until + 1, 8 * 3600 * 10**9, dtype=np.int64)
    fund = dict(time_ns=np.r_[t, syn], rate=np.r_[r, np.full(syn.size, FUND_FALLBACK)],
                synthetic=np.r_[np.zeros(t.size, bool), np.ones(syn.size, bool)])
    if cache_path:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        np.savez(cache_path, sig=np.array(sig), **{"d_" + k: v for k, v in daily.items()},
                 **{"x_" + k: v for k, v in ex.items()}, **{"f_" + k: v for k, v in fund.items()})
    return daily, ex, fund


# ---------------------------------------------------------------------------
# 일봉 신호 (반복문으로 직접 계산 — 슬라이딩 창 라이브러리 안 씀)
# ---------------------------------------------------------------------------

def exit_len(n: int) -> int:
    return {20: 10, 55: 28, 100: 50}.get(n, int(math.floor(n / 2 + 0.5)))


def prior_max_min(close: np.ndarray, n: int):
    """hi[t] = max(close[t-n..t-1]), lo[t] = min(...) (t ≥ n), 앞은 NaN."""
    L = close.size
    hi = np.full(L, np.nan)
    lo = np.full(L, np.nan)
    for t in range(n, L):
        w = close[t - n:t]
        hi[t] = w.max()
        lo[t] = w.min()
    return hi, lo


def atr_prior(high, low, close, n=20):
    L = close.size
    tr = np.full(L, np.nan)
    for t in range(1, L):
        tr[t] = max(high[t] - low[t], abs(high[t] - close[t - 1]), abs(low[t] - close[t - 1]))
    out = np.full(L, np.nan)
    for t in range(n + 1, L):          # tr[t-n..t-1] 모두 존재하려면 t-n ≥ 1
        out[t] = tr[t - n:t].mean()
    return out


@dataclass
class Sig:
    n: int
    m: int
    up: np.ndarray
    dn: np.ndarray
    xup: np.ndarray
    xdn: np.ndarray
    atr: np.ndarray
    valid: np.ndarray
    le: np.ndarray
    se: np.ndarray
    lx: np.ndarray
    sx: np.ndarray


def signals(daily: dict, n: int, atr: np.ndarray | None = None) -> Sig:
    c = daily["close"]
    m = exit_len(n)
    up, dn = prior_max_min(c, n)
    xup, xdn = prior_max_min(c, m)
    if atr is None:
        atr = atr_prior(daily["high"], daily["low"], c, 20)
    valid = np.isfinite(up) & np.isfinite(dn) & np.isfinite(xup) & np.isfinite(xdn) & np.isfinite(atr)
    with np.errstate(invalid="ignore"):
        return Sig(n, m, up, dn, xup, xdn, atr, valid,
                   valid & (c > up), valid & (c < dn), valid & (c < xdn), valid & (c > xup))


# ---------------------------------------------------------------------------
# 거래 하나
# ---------------------------------------------------------------------------

def rnd(x: float) -> float:
    return float(np.round(x, 1))


def funding_paid(side, start_ns, exit_open_ns, ex, fund, m):
    ft, fr = fund["time_ns"], fund["rate"]
    sel = (ft > start_ns) & (ft <= exit_open_ns)
    if not sel.any():
        return 0.0
    tot = 0.0
    for f, r in zip(ft[sel], fr[sel]):
        j = int(np.searchsorted(ex["open_ns"], f, side="right")) - 1   # f를 포함하는 실행 봉
        x = side * r * float(ex["open"][j])
        tot += x * m if x > 0 else x
    return tot


def sim_trade(daily, sig: Sig, t: int, side: int, ex, fund, *, mode="E0", lat_min=30, k_atr=2.0, cost=1.0,
              maker_variant=False):
    """신호 봉 t → 거래 dict. maker_variant=True면 E0 체결·청산 그대로, 진입 비용만 메이커·슬리피지 없음(무작위 비교용)."""
    dec = int(daily["close_ns"][t]) + NS_MIN
    act = dec + lat_min * NS_MIN
    atr = float(sig.atr[t])
    level = float(sig.up[t] if side > 0 else sig.dn[t])
    xarr = sig.lx if side > 0 else sig.sx
    ks = np.flatnonzero(xarr[t + 1:])
    k = int(t + 1 + ks[0]) if ks.size else None
    k_dec = int(daily["close_ns"][k]) + NS_MIN if k is not None else None
    n_x = ex["open_ns"].size
    j0 = int(np.searchsorted(ex["open_ns"], act, side="left"))
    rec = dict(n=sig.n, side=side, t=t, signal_ns=int(daily["close_ns"][t]), active_ns=act, atr20=atr, level=level,
               exit_signal_day=k, mode=mode)
    if mode == "E0":
        if j0 >= n_x:
            rec.update(status="not_filled", busy_until=act)
            return rec
        je, entry = j0, float(ex["open"][j0])
        e_rate, e_slip = TAKER, SLIP
    else:
        lim = rnd(level)
        vu = int(daily["close_ns"][t]) + 5 * NS_DAY
        order_end = vu
        cancelled = False
        if k_dec is not None and k_dec < vu:
            order_end, cancelled = k_dec, True
        rec.update(limit=lim, order_end=order_end)
        je = None
        j = j0
        # 선형 탐색 (구현의 searchsorted 창과 다른 방식)
        while j < n_x and ex["close_ns"][j] <= order_end:
            if (side > 0 and ex["low"][j] < lim) or (side < 0 and ex["high"][j] > lim):
                je = j
                break
            j += 1
        if je is None:
            if j0 >= n_x or order_end > int(ex["close_ns"][-1]):
                st = "not_filled"
            else:
                st = "cancelled" if cancelled else "expired"
            rec.update(status=st, busy_until=order_end, stop=rnd(lim - side * k_atr * atr))
            return rec
        entry = lim
        e_rate, e_slip = MAKER, 0.0
    if maker_variant:
        e_rate_c, e_slip_c = MAKER, 0.0
    else:
        e_rate_c, e_slip_c = e_rate, e_slip
    stop = rnd(entry - side * k_atr * atr)
    # 추세 청산 봉
    if k_dec is not None:
        jt = int(np.searchsorted(ex["open_ns"], k_dec + lat_min * NS_MIN, side="left"))
        jt = max(jt, je + 1)
    else:
        jt = n_x
    end = min(jt, n_x)
    seg = ex["low"][je:end] <= stop if side > 0 else ex["high"][je:end] >= stop
    hit = np.flatnonzero(seg)
    if hit.size:
        jx = je + int(hit[0])
        px = stop
        if jx > je or mode == "E0":
            o = float(ex["open"][jx])
            px = min(px, o) if side > 0 else max(px, o)
        reason = "stop"
    elif jt < n_x:
        jx, px, reason = jt, float(ex["open"][jt]), "trend"
    else:
        jx, px, reason = n_x - 1, float(ex["close"][n_x - 1]), "eod"
    m = cost
    entry_time = int(ex["open_ns"][je])
    exit_time = int(ex["open_ns"][jx])
    fees = (e_rate_c * entry + TAKER * px) * m
    slip = (SLIP * px + e_slip_c * entry) * m
    f_start = min(entry_time, act) if mode == "E0" else entry_time
    fund_c = funding_paid(side, f_start, exit_time, ex, fund, m)
    gross = side * (px - entry)
    net = gross - fees - slip - fund_c
    risk = abs(entry - stop) + e_rate_c * entry + (TAKER + SLIP) * stop + e_slip_c * entry
    risk_lit = abs(entry - stop) + e_rate_c * entry + (TAKER + SLIP) * stop   # RULES §12.2 문자 그대로(진입 슬리피지 없음)
    rec.update(status="filled", entry_j=je, entry_time=entry_time, entry_price=entry, stop=stop, exit_j=jx,
               exit_time=exit_time, exit_price=px, exit_reason=reason, busy_until=int(ex["close_ns"][jx]),
               fees=fees, slippage=slip, funding=fund_c, gross=gross, net=net, risk=risk, r=net / risk,
               r_literal=net / risk_lit)
    return rec


# ---------------------------------------------------------------------------
# 하위 시스템: 하루씩 넘기는 상태 기계
# ---------------------------------------------------------------------------

def run_system(daily, n, ex, fund, *, mode="E0", allow_short=True, lat_min=30, k_atr=2.0, cost=1.0, sig=None):
    sig = signals(daily, n) if sig is None else sig
    out = []
    busy_until = -1          # 포지션(청산 봉 끝) 또는 대기 주문(order_end)이 끝나는 시각
    exit_day = None          # 보유 포지션의 청산 신호 날 (그날 판단 때 반대 진입 검사)
    first = int(np.flatnonzero(sig.valid)[0])
    stopped_all = False
    for d in range(first, len(daily["close"])):
        if stopped_all:
            break
        dec = int(daily["close_ns"][d]) + NS_MIN
        flat = busy_until <= dec or (exit_day is not None and exit_day == d)
        if not flat:
            continue
        side = 1 if sig.le[d] else (-1 if (sig.se[d] and allow_short) else 0)
        if side == 0:
            continue
        rec = sim_trade(daily, sig, d, side, ex, fund, mode=mode, lat_min=lat_min, k_atr=k_atr, cost=cost)
        out.append(rec)
        if rec["status"] == "filled":
            busy_until = rec["busy_until"]
            exit_day = rec["exit_signal_day"]
            if rec["exit_reason"] == "eod":
                stopped_all = True
        else:
            busy_until = rec["busy_until"]
            exit_day = None
            if rec["status"] == "not_filled":
                stopped_all = True
    return out


def run_combo(daily, ex, fund, *, mode, direction, periods, lat_min=30, k_atr=2.0, cost=1.0, sigs=None):
    res = []
    for n in periods:
        s = None if sigs is None else sigs[n]
        res += run_system(daily, n, ex, fund, mode=mode, allow_short=(direction == "LS"), lat_min=lat_min,
                          k_atr=k_atr, cost=cost, sig=s)
    return res
