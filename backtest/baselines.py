"""추세추종 기준선 — 일봉 돈치안 채널 앙상블 (§8.4, §12.4). 비교용 보고만 한다.

담당: 통계·기준선. 설계: backtest/DESIGN.md §6.11, 해석 확정 I-43.

규칙 (I-43)
- 기간 N ∈ (20, 55, 100), 청산 기간 M = N // 2 (10, 27, 50). 일봉 종가 기준, 현재 봉 제외 창:
  상단 = max(close[t−N..t−1]), 하단 = min(close[t−N..t−1]) (청산은 M으로 같은 방식).
- 봉 t 마감에 판단: 보유 중이면 먼저 청산 검사(롱: close[t] < M일 최저, 숏: close[t] > M일 최고),
  그다음 무포지션이면 진입 검사(close[t] > 상단 → 롱, < 하단 → 숏). 같은 봉에서 청산 후 반대 진입 가능.
- 체결: 다음 일봉 시가(open[t+1]), 테이커 수수료(명목 × FEE_TAKER), 슬리피지 없음(명세에 없음).
- 크기: 전략마다 진입 시점 자산의 0.2배 명목(세 전략 합 ≤ 0.6배), 청산까지 수량 고정.
- 펀딩: 보유 중 지나간 펀딩마다 −side × rate × 수량 × 그 시각 실행 봉 시가.
- 자산 곡선: 일봉 종가로 평가(시작 1.0). 보고: 연 수익률(CAGR, 365일), 최대 낙폭, 샤프(일간 수익률 × √365).

명목 상한 (§12.4 "전체 명목 ≤ 0.6배"와 I-43 "수량 고정"의 조정 — cap_mode)
- 수량을 끝까지 고정하면 추세가 이어질 때 명목 ÷ 자산이 0.6을 크게 넘는다(실데이터 최대 약 1.10배).
  명세 문장(전체 명목 ≤ 0.6배)이 설계 해석보다 우선이므로 기본값 cap_mode='trim'은:
  수량은 고정하되, 매일 시가(체결 시각)에 전략 하나의 명목이 예산(0.2 × 그 시점 자산)을 넘으면 넘는 만큼만
  테이커로 줄인다(늘리지는 않는다 = 물타기 없음). 그래서 체결 시각마다 합 ≤ 0.6 × 자산(진입 수수료만큼의 오차).
- cap_mode='entry_only' = 설계 I-43 문장 그대로(진입 때만 0.2배, 이후 수량 고정). 비교·감사용.

구현 세부 (이 모듈에서 정한 것)
- 시작: 세 채널이 모두 준비되는 봉 s = max(기간) = 100. 봉 s 마감에 자산 1.0(무포지션)으로 시작하고, 모든 전략이
  봉 s부터 판단한다(기간별 결과도 같은 구간). 신호는 판단 시각까지 마감된 종가만 쓴다(미래 참조 없음).
- 하루 d의 순서: ① 전날 종가 → d 시가 평가 ② d 시가에 전날 판단대로 청산 → 진입(크기 = 청산 뒤 자산 E × 0.2 ÷
  시가, 같은 날 진입끼리는 같은 E) → (trim) 예산 E × 0.2를 넘는 전략 줄이기 ③ d 시가 → d 종가 평가
  ④ (open_ns[d], close_ns[d]]의 펀딩(§12.2 "진입 < 펀딩 ≤ 청산", 시가 체결이므로 하루 구간과 같다).
- 마지막 봉 판단은 다음 시가가 없어 체결하지 않는다. 데이터 끝에 남은 포지션은 마지막 종가에 테이커로 청산한다
  (I-36과 같은 방식, 보수적).
- 기간별 결과(per_period)는 그 기간 하나만 같은 명목 상한(0.6배)으로 돌린 것이다.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from backtest import config as C
from backtest.types import ExecArrays, FundingArrays

DAYS_PER_YEAR = 365                 # §12.4 연율화: 코인 선물은 365일 거래 (CAGR 365일, 샤프 × √365)
CAP_MODES = ("trim", "entry_only")  # 명목 상한 적용 방식 (모듈 설명 참고)
_TRIM_RTOL = 1e-9                   # 예산 초과 판정의 부동소수 허용 오차(예: (0.6/111)×111 > 0.6 같은 반올림은 초과 아님)
_NAN = float("nan")


# ---------------------------------------------------------------------------
# 채널과 목표 포지션
# ---------------------------------------------------------------------------


def trailing_extremes(close: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """현재 봉을 뺀 직전 n개 종가의 (최고, 최저): hi[t] = max(close[t−n..t−1]) (t ≥ n), 앞부분 NaN (I-43)."""
    close = np.asarray(close, dtype=np.float64)
    n = int(n)
    if n < 1:
        raise ValueError(f"기간은 1 이상: {n!r}")
    hi = np.full(close.shape[0], np.nan)
    lo = np.full(close.shape[0], np.nan)
    if close.shape[0] > n:
        win = sliding_window_view(close, n)[:-1]   # win[k] = close[k..k+n−1] → t = k + n 의 직전 n개
        hi[n:] = win.max(axis=1)
        lo[n:] = win.min(axis=1)
    return hi, lo


def _positions(close: np.ndarray, period: int, exit_period: int, start: int) -> np.ndarray:
    """봉 t(≥ max(start, period)) 마감의 목표 포지션(+1/0/−1). 그 전은 0."""
    close = np.asarray(close, dtype=np.float64)
    period, exit_period = int(period), int(exit_period)
    if exit_period < 1 or period < 1:
        raise ValueError(f"기간은 1 이상: period={period}, exit_period={exit_period}")
    up, dn = trailing_extremes(close, period)             # 진입: 직전 N일 최고·최저 종가
    ex_hi, ex_lo = trailing_extremes(close, exit_period)  # 청산: 직전 M일 최고·최저 종가
    out = np.zeros(close.shape[0], dtype=np.int8)
    p = 0
    for t in range(max(int(start), period, exit_period), close.shape[0]):
        c = close[t]
        if p > 0 and c < ex_lo[t]:      # I-43 롱 청산: 종가 < 직전 M일 최저
            p = 0
        elif p < 0 and c > ex_hi[t]:    # I-43 숏 청산: 종가 > 직전 M일 최고
            p = 0
        if p == 0:                       # 같은 봉에서 청산 후 반대 진입 가능
            if c > up[t]:                # §12.4 신고가(직전 N일 최고 종가) 돌파 → 롱
                p = 1
            elif c < dn[t]:              # §12.4 신저가 돌파 → 숏
                p = -1
        out[t] = p
    return out


def donchian_positions(close: np.ndarray, period: int, exit_period: int) -> np.ndarray:
    """봉 t 마감에 정해진 목표 포지션(+1/0/−1, int8). 실제 보유는 t+1 시가부터.

    t < period(직전 N개 종가가 없음)는 0. 판단에는 close[..t]만 쓴다(close[t+1:]를 바꿔도 결과[..t]는 같다).
    """
    return _positions(close, period, exit_period, start=0)


# ---------------------------------------------------------------------------
# 펀딩
# ---------------------------------------------------------------------------


def _funding_prices(xb: ExecArrays, times_ns: np.ndarray) -> np.ndarray:
    """펀딩 시각의 가격 = 그 시각을 포함하는 실행 봉의 시가 (I-35; execution.funding_prices와 같은 규칙)."""
    if len(xb) == 0:
        raise ValueError("실행 봉이 없어 펀딩 가격을 정할 수 없다")
    j = np.searchsorted(xb.open_ns, np.asarray(times_ns, dtype=np.int64), side="right") - 1
    return xb.open[np.clip(j, 0, len(xb) - 1)]


def funding_per_day(open_ns: np.ndarray, close_ns: np.ndarray, fa: FundingArrays, xb: ExecArrays) -> np.ndarray:
    """일봉 d마다 롱 1단위가 낸 펀딩 합 = Σ rate_f × price_f, f ∈ (open_ns[d], close_ns[d]] (§12.2, I-35).

    양수 = 롱이 지불(숏은 수취). 일봉은 이어져 있어야 한다(close_ns[d] = open_ns[d+1]).
    """
    open_ns = np.asarray(open_ns, dtype=np.int64)
    close_ns = np.asarray(close_ns, dtype=np.int64)
    n = open_ns.shape[0]
    out = np.zeros(n, dtype=np.float64)
    if n == 0 or fa.time_ns.shape[0] == 0:
        return out
    t = np.asarray(fa.time_ns, dtype=np.int64)
    m = (t > open_ns[0]) & (t <= close_ns[-1])
    if not m.any():
        return out
    t, rate = t[m], np.asarray(fa.rate, dtype=np.float64)[m]
    d = np.searchsorted(close_ns, t, side="left")      # close_ns[d−1] < f ≤ close_ns[d]
    return np.bincount(d, weights=rate * _funding_prices(xb, t), minlength=n)


# ---------------------------------------------------------------------------
# 시뮬레이션
# ---------------------------------------------------------------------------


def _simulate(open_: np.ndarray, close: np.ndarray, fund_unit: np.ndarray, targets: np.ndarray,
              weight: float, start: int, trim: bool = True) -> dict:
    """목표 포지션 묶음(k × n) → 일별 자산 곡선 (봉 start 마감 = 1.0부터 마지막 봉 마감까지).

    targets[i, t] = 전략 i가 봉 t 마감에 정한 포지션 → t+1 시가에 체결. 진입 크기 = weight × E ÷ 시가
    (E = 그날 청산 뒤 자산). trim이면 체결 뒤 |수량| × 시가 > weight × E인 전략을 weight × E로 줄인다.
    반환: equity(길이 n − start), n_trades(진입 수), n_trims, fills(체결 기록), total_fees, total_funding,
    max_notional_ratio(시가 체결 직후 Σ|명목| ÷ 자산의 최댓값), open_notional(k × 일수: 시가 체결 직후 전략별 명목),
    open_budget(일수: 그날 예산 기준 자산 E × weight).
    """
    n = close.shape[0]
    k = targets.shape[0]
    days = max(n - start, 0)
    q = np.zeros(k, dtype=np.float64)       # 전략별 보유 수량(부호 = 방향)
    equity = np.empty(days, dtype=np.float64)
    open_notional = np.zeros((k, days), dtype=np.float64)
    open_budget = np.zeros(days, dtype=np.float64)
    fills: list[dict] = []
    e = 1.0
    fees = funding = 0.0
    n_trades = n_trims = 0
    max_ratio = 0.0
    if days == 0:
        return dict(equity=equity, n_trades=0, n_trims=0, fills=fills, total_fees=0.0, total_funding=0.0,
                    max_notional_ratio=_NAN, open_notional=open_notional, open_budget=open_budget)
    equity[0] = e                                            # 봉 start 마감: 무포지션, 자산 1.0
    for d in range(start + 1, n):
        o = open_[d]
        e += float(q.sum()) * (o - close[d - 1])             # ① 전날 종가 → 오늘 시가 평가 (q는 부호 있는 수량)
        want = targets[:, d - 1]                             # 전날 마감 판단 → 오늘 시가 체결 (I-43)
        for i in range(k):                                   # ② 청산 먼저
            if q[i] != 0 and want[i] != np.sign(q[i]):
                fee = C.FEE_TAKER * abs(q[i]) * o            # §12.4 테이커 수수료 = 명목 × 0.05%
                e -= fee
                fees += fee
                fills.append(dict(strategy=i, day=d, action="exit", side=int(np.sign(q[i])), qty=abs(q[i]),
                                  price=o, fee=fee))
                q[i] = 0.0
        e_size = e                                           # 진입·예산 기준 자산(같은 날 진입끼리 같은 기준)
        budget = weight * e_size                             # 전략 하나의 명목 예산 = 0.2 × 자산
        for i in range(k):                                   # ② 그다음 진입
            if want[i] != 0 and q[i] == 0 and e_size > 0:
                qty = budget / o                             # 전략마다 자산 × 0.2 명목
                fee = C.FEE_TAKER * qty * o
                e -= fee
                fees += fee
                q[i] = int(want[i]) * qty
                n_trades += 1
                fills.append(dict(strategy=i, day=d, action="enter", side=int(want[i]), qty=qty, price=o,
                                  fee=fee, equity=e_size))
        if trim:
            for i in range(k):                               # §12.4 전체 명목 ≤ 0.6배: 예산 넘는 만큼만 줄인다
                if q[i] != 0 and abs(q[i]) * o > budget * (1.0 + _TRIM_RTOL):
                    new_qty = max(budget, 0.0) / o
                    cut = abs(q[i]) - new_qty
                    fee = C.FEE_TAKER * cut * o
                    e -= fee
                    fees += fee
                    fills.append(dict(strategy=i, day=d, action="trim", side=int(np.sign(q[i])), qty=cut,
                                      price=o, fee=fee, equity=e_size))
                    q[i] = np.sign(q[i]) * new_qty
                    n_trims += 1
        open_notional[:, d - start] = np.abs(q) * o
        open_budget[d - start] = budget
        if e > 0:
            max_ratio = max(max_ratio, float(np.abs(q).sum() * o / e))
        e += float(q.sum()) * (close[d] - o)                 # ③ 오늘 시가 → 오늘 종가 평가
        f = float(q.sum()) * float(fund_unit[d])             # ④ 펀딩 비용(롱은 양수 비율이면 지불, 숏은 수취)
        e -= f
        funding += f
        equity[d - start] = e
    last = close[n - 1]
    for i in range(k):                                       # 데이터 끝: 마지막 종가에 테이커 청산 (보수적)
        if q[i] != 0:
            fee = C.FEE_TAKER * abs(q[i]) * last
            e -= fee
            fees += fee
            fills.append(dict(strategy=i, day=n - 1, action="eod", side=int(np.sign(q[i])), qty=abs(q[i]),
                              price=last, fee=fee))
            q[i] = 0.0
    equity[-1] = e
    return dict(equity=equity, n_trades=n_trades, n_trims=n_trims, fills=fills, total_fees=fees,
                total_funding=funding, max_notional_ratio=max_ratio, open_notional=open_notional,
                open_budget=open_budget)


def performance(equity: np.ndarray, days: float) -> dict:
    """자산 곡선(일별, 시작값 기준) → cagr(365일), max_drawdown(양수 비율), sharpe(일간 수익률 평균 ÷ 표준편차 × √365).

    계산할 수 없으면 NaN(곡선 길이 < 2, 기간 0, 자산 ≤ 0, 수익률 표준편차 0).
    """
    eq = np.asarray(equity, dtype=np.float64)
    if eq.shape[0] < 2 or not np.all(np.isfinite(eq)) or not days > 0:
        return {"cagr": _NAN, "max_drawdown": _NAN, "sharpe": _NAN}
    peak = np.maximum.accumulate(eq)
    mdd = float(np.max(1.0 - eq / peak)) if np.all(peak > 0) else _NAN
    if np.any(eq <= 0):
        return {"cagr": _NAN, "max_drawdown": mdd, "sharpe": _NAN}
    cagr = float((eq[-1] / eq[0]) ** (DAYS_PER_YEAR / days) - 1.0)
    ret = eq[1:] / eq[:-1] - 1.0
    sd = float(np.std(ret, ddof=1)) if ret.shape[0] >= 2 else 0.0
    sharpe = float(np.mean(ret) / sd * math.sqrt(DAYS_PER_YEAR)) if sd > 0 else _NAN
    return {"cagr": cagr, "max_drawdown": mdd, "sharpe": sharpe}


def donchian_ensemble(daily: pd.DataFrame, fa: FundingArrays, xb: ExecArrays, *,
                      periods: tuple[int, ...] = C.DONCHIAN_PERIODS,
                      notional_cap: float = C.DONCHIAN_NOTIONAL_CAP, cap_mode: str = "trim") -> dict:
    """세 전략 동일 비중 앙상블의 성과.

    반환 dict: cagr, max_drawdown(양수 비율), sharpe, n_trades, final_equity, start_utc, end_utc,
    per_period({N: {n_trades, cagr, max_drawdown, sharpe}}), equity(일별 자산 np.ndarray, JSON에는 넣지 않음).

    cap_mode: 'trim'(기본, 체결 시각마다 전략별 명목 ≤ 상한 ÷ 전략 수) | 'entry_only'(설계 I-43 문장 그대로).
    덧붙인 값(스칼라·목록만, JSON 가능): cap_mode, periods, exit_periods, notional_per_strategy(= 상한 ÷ 전략 수 = 0.2),
    n_days, n_trims, total_fees, total_funding(자산 1.0 기준, 양수 = 지불), max_notional_ratio(시가 체결 직후
    Σ|명목| ÷ 자산의 최댓값). per_period[N]에는 final_equity도 넣는다. 일봉이 부족하면(≤ max(기간)) 성과 값은 NaN.
    """
    if cap_mode not in CAP_MODES:
        raise ValueError(f"cap_mode는 {CAP_MODES} 중 하나: {cap_mode!r}")
    periods = tuple(int(p) for p in periods)
    if not periods:
        raise ValueError("periods가 비었다")
    exit_periods = tuple(p // C.DONCHIAN_EXIT_DIVISOR for p in periods)   # I-43 청산 기간 M = N // 2
    open_ = daily["open"].to_numpy(dtype=np.float64)
    close = daily["close"].to_numpy(dtype=np.float64)
    open_ns = daily["open_ns"].to_numpy(dtype=np.int64)
    close_ns = daily["close_ns"].to_numpy(dtype=np.int64)
    n = close.shape[0]
    if n > 1 and np.any(close_ns[:-1] != open_ns[1:]):
        raise ValueError("일봉이 이어져 있지 않다(빈 날)")
    start = max(periods)                                                  # 세 채널이 모두 준비되는 봉
    targets = np.stack([_positions(close, p, m, start) for p, m in zip(periods, exit_periods)])
    fund_unit = funding_per_day(open_ns, close_ns, fa, xb)
    weight = float(notional_cap) / len(periods)                          # 동일 비중: 전략마다 0.2배
    trim = cap_mode == "trim"
    days = (close_ns[-1] - close_ns[start]) / C.NS_PER_DAY if n > start else 0.0

    sim = _simulate(open_, close, fund_unit, targets, weight, start, trim)
    perf = performance(sim["equity"], days)
    per_period = {}
    for i, p in enumerate(periods):
        s_i = _simulate(open_, close, fund_unit, targets[i:i + 1], float(notional_cap), start, trim)  # 하나만, 같은 상한
        perf_i = performance(s_i["equity"], days)
        per_period[p] = {"n_trades": int(s_i["n_trades"]), "cagr": perf_i["cagr"],
                         "max_drawdown": perf_i["max_drawdown"], "sharpe": perf_i["sharpe"],
                         "final_equity": float(s_i["equity"][-1]) if s_i["equity"].shape[0] else _NAN}
    eq = sim["equity"]
    return {
        "cagr": perf["cagr"],
        "max_drawdown": perf["max_drawdown"],
        "sharpe": perf["sharpe"],
        "n_trades": int(sim["n_trades"]),
        "final_equity": float(eq[-1]) if eq.shape[0] else _NAN,
        "start_utc": C.ns_to_iso(int(close_ns[start])) if n > start else "",
        "end_utc": C.ns_to_iso(int(close_ns[-1])) if n else "",
        "per_period": per_period,
        "equity": eq,
        "cap_mode": cap_mode,
        "periods": list(periods),
        "exit_periods": list(exit_periods),
        "notional_per_strategy": weight,
        "n_days": int(max(eq.shape[0] - 1, 0)),
        "n_trims": int(sim["n_trims"]),
        "total_fees": float(sim["total_fees"]),
        "total_funding": float(sim["total_funding"]),
        "max_notional_ratio": float(sim["max_notional_ratio"]),
    }
