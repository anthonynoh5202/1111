"""체결 엔진 — 주문 계획을 실행 봉 위에서 체결·청산하고, 신호를 시간순으로 처리한다 (§8.2, §12.1~12.3).

담당: 체결 엔진. 설계: backtest/DESIGN.md §6.8, 해석 확정 I-19, I-20, I-27~I-36, I-38, I-44, I-48.

- 체결 엔진은 신호 봉 데이터를 모른다. 시간은 Plan의 active_from·valid_until·cancel_effective_time(+max_hold_ns)만 본다.
- 실행 봉(ExecArrays)은 2023-10-01 전 5분봉, 이후 1분봉 (DESIGN §5). 봉 j의 구간은 [open_ns[j], close_ns[j]).
- 금액은 수량 1단위당 USDT. 비용 배수 m(cfg.cost_multiplier)은 수수료·슬리피지·**지불한** 펀딩에만 곱한다.
  R 분모(risk_per_unit)는 실제 진입가·기본 비용이다 (I-29: 지정가는 계획가 = 체결가, L1b IOC 상한·시장가는
  첫 실행 봉 시가 → 손절 = 정확히 −1R, 무작위 기준선과 같은 단위). 수량(size_fraction)은 계획 시점 가격으로 정한다.
  수수료·비용 식은 config의 공용 함수를 쓴다.
- 결정적: 같은 입력이면 같은 결과. 난수 없음.
- 성능: 계획마다 np.searchsorted로 봉 번호를 찾고, 불리언 배열의 argmax로 첫 성립 봉을 찾는다.
  청산 탐색은 짧은 창에서 시작해 늘려 간다(대부분의 거래는 첫 창 안에서 끝난다).
- 무작위 기준선(random_baseline)도 같은 scan_exit·trade_costs·펀딩 규칙을 쓴다(청산·비용 식의 단일 출처).
"""
from __future__ import annotations

import dataclasses

import numpy as np

from backtest import config as C
from backtest.config import ComboConfig
from backtest.types import (Candidate, ExecArrays, Exit, FundingArrays, Plan, Reason, SignalLog, Status,
                            TradeResult, sort_reasons)

OPEN_FILL_TYPES = ("ioc_cap", "market")  # 첫 실행 봉 시가에 진입하는 주문 (I-44). 체결 봉에서도 갭 손절 적용 (I-33)
SCAN_WINDOW = 512                        # 청산 탐색 첫 창(실행 봉 수)
SCAN_GROWTH = 8                          # 창을 넓히는 배수 (512 → 4,096 → 32,768)
RISK_EPS = 1e-9                          # 리스크 검사 경계의 부동소수 오차 허용 (0.1 USDT 격자보다 훨씬 작다)


# ---------------------------------------------------------------------------
# 리스크 검사 (§8.1, §12.2) — 신호 단계에서 부른다
# ---------------------------------------------------------------------------


def stop_band_ok(entry, stop, atr):
    """§8.1 손절 폭: max(0.4% × entry, 1 × ATR) ≤ |entry − stop| ≤ min(2% × entry, 3 × ATR) (양 끝 포함).

    filters.stop_band_ok와 같은 규칙·시그니처. ATR은 신호 봉(L1b는 k_last) ATR (§12.2).
    배열·스칼라 모두 받는다. NaN이 섞이면 실패. 양 끝은 부동소수 오차(RISK_EPS)만큼 포함한다
    (예: 3 × 0.3 = 0.8999999999999999 이어도 d = 0.9는 통과 — "양 끝 포함"을 계산 오차가 뒤집지 않게).
    """
    entry = np.asarray(entry, dtype=np.float64)
    stop = np.asarray(stop, dtype=np.float64)
    atr = np.asarray(atr, dtype=np.float64)
    d = np.abs(entry - stop)
    lo = np.maximum(C.STOP_MIN_PCT * entry, C.STOP_MIN_ATR * atr)  # §8.1 하한 max(0.4%, 1×ATR)
    hi = np.minimum(C.STOP_MAX_PCT * entry, C.STOP_MAX_ATR * atr)  # §8.1 상한 min(2%, 3×ATR)
    ok = (d >= lo - RISK_EPS) & (d <= hi + RISK_EPS)
    return bool(ok) if ok.ndim == 0 else ok


def risk_reasons(side: int, entry: float, stop: float, target: float, atr: float,
                 order_type: str) -> tuple[str, ...]:
    """§8.1 리스크 검사 → 폐기 사유 코드 튜플(REASON_ORDER 순서). 통과면 ().

    - RISK_STOP_BAND: stop_band_ok 실패
    - RISK_RR: 순손익비 = config.net_rr(§12.2 식) < 1.5 (NaN도 실패)
    비용은 항상 기본 비용(배수 1)이다 (I-27). 진입 수수료율 = config.entry_fee_rate(order_type).
    포지션 크기(명목 0.6배 상한)는 폐기 사유가 아니다 (I-28 — simulate_plan이 size_fraction으로 기록).
    filters.risk_reasons와 같은 시그니처·규칙이다(어느 쪽을 불러도 같은 결과).
    """
    out = []
    if not stop_band_ok(entry, stop, atr):
        out.append(Reason.RISK_STOP_BAND)
    with np.errstate(all="ignore"):
        rr = float(C.net_rr(int(side), np.float64(entry), np.float64(stop), np.float64(target),
                            C.entry_fee_rate(order_type)))
    if not rr >= C.MIN_NET_RR - RISK_EPS:  # §8.1, §12.2 순손익비 ≥ 1.5
        out.append(Reason.RISK_RR)
    return tuple(out)


# ---------------------------------------------------------------------------
# 진입 (§12.1, I-30, I-31, I-44)
# ---------------------------------------------------------------------------


def _check_plan(plan: Plan) -> None:
    if plan.side not in (1, -1):
        raise ValueError(f"side는 +1 또는 -1: {plan.side!r}")
    if plan.order_type not in C.ORDER_TYPES:
        raise ValueError(f"알 수 없는 주문 형태: {plan.order_type!r}")


def entry_window(plan: Plan, xb: ExecArrays) -> tuple[int, int]:
    """진입 가능한 실행 봉 번호 범위 [j0, j1) (I-31).

    j0 = open_ns ≥ active_from 인 첫 봉. 지정가: j1 = close_ns ≤ plan.order_end 인 마지막 봉 + 1
    (봉 전체가 주문 수명 안에 있어야 함 → 5분봉 구간에서 보수적). ioc_cap·market: j1 = j0 + 1.
    봉이 없으면 j0 = j1 = len(xb). 지정가 창이 비면 j1 = j0.
    """
    _check_plan(plan)
    n = len(xb)
    j0 = int(np.searchsorted(xb.open_ns, plan.active_from, side="left"))  # §12.1 활성 시각 이후 "시작하는" 봉부터
    if j0 >= n:
        return n, n
    if plan.order_type in OPEN_FILL_TYPES:
        return j0, j0 + 1                                                  # I-44 첫 실행 봉 하나
    j1 = int(np.searchsorted(xb.close_ns, plan.order_end, side="right"))   # I-31 봉 끝 ≤ min(만료, 취소 효력)
    return j0, max(j0, j1)


def find_entry(plan: Plan, xb: ExecArrays) -> tuple[int, float] | None:
    """진입 체결 봉과 체결가 (I-30, I-44). 없으면 None.

    - limit 롱: low[j] < entry_price(엄격) → entry_price에 체결. 숏: high[j] > entry_price.
      활성 뒤 첫 봉 시가가 이미 지정가 너머(즉시 체결될 주문)여도 §12.1 문자 그대로 지정가·메이커로 체결한다
      (simulate_plan이 meta['marketable_open']으로 표시해 건수를 보고한다, 검토 LA-2·F4).
    - ioc_cap 롱: open[j0] ≤ entry_price(상한)면 open[j0]에 체결, 아니면 None. 숏: open[j0] ≥ entry_price.
    - market: open[j0]에 체결.
    """
    j0, j1 = entry_window(plan, xb)
    if j0 >= j1:
        return None
    price = float(plan.entry_price)
    if plan.order_type == "limit":
        # §7·§12.1 관통해야 체결(닿기만 하면 미체결). 가격이 유리하게 갭이 나도 지정가에 체결 (I-33)
        hit = xb.low[j0:j1] < price if plan.side > 0 else xb.high[j0:j1] > price
        k = int(np.argmax(hit))
        return (j0 + k, price) if hit[k] else None
    o = float(xb.open[j0])
    if plan.order_type == "ioc_cap":
        ok = o <= price if plan.side > 0 else o >= price  # §12.1 시가가 상한 이하면 시가 체결, 아니면 폐기
        return (j0, o) if ok else None
    return j0, o                                           # market (무작위 기준선, §12.4)


# ---------------------------------------------------------------------------
# 청산 (§12.1~12.2, I-30, I-32~I-34, I-36)
# ---------------------------------------------------------------------------


def scan_exit(side: int, entry_j: int, stop: float, target: float, time_limit_ns: int, order_type: str,
              xb: ExecArrays) -> tuple[int, float, str]:
    """청산 봉·청산가·사유 (I-30, I-32~I-34, I-36). 반환 (exit_j, exit_price, exit_reason).

    봉 j = entry_j, entry_j+1, … 순서로:
    1) j > entry_j 이고 open_ns[j] ≥ time_limit_ns → open[j]에 'time' 청산
    2) 손절 닿음(롱 low ≤ stop / 숏 high ≥ stop) → 'stop'. 청산가 = stop,
       단 갭: (j > entry_j 또는 order_type ∈ {ioc_cap, market})이고 시가가 이미 손절 너머면 open[j]
    3) j > entry_j 이고 목표 관통(롱 high > target / 숏 low < target) → target에 'target' (같은 봉 손절 우선)
    데이터 끝까지 없으면 마지막 봉 close에 'eod'.
    time_limit_ns = entry_time(체결 봉 open_ns) + plan.max_hold_ns.
    """
    n = len(xb)
    entry_j = int(entry_j)
    if not 0 <= entry_j < n:
        raise IndexError(f"entry_j 범위 밖: {entry_j} (실행 봉 {n}개)")
    is_long = side > 0
    # I-34 시간 청산 봉 jt: 체결 봉 뒤에서 open_ns ≥ time_limit_ns 인 첫 봉. 손절·목표는 [entry_j, jt)에서만 본다
    jt = max(int(np.searchsorted(xb.open_ns, time_limit_ns, side="left")), entry_j + 1)
    end = min(jt, n)
    w0, width = entry_j, SCAN_WINDOW
    while w0 < end:
        w1 = min(end, w0 + width)
        if is_long:
            stop_hit = xb.low[w0:w1] <= stop     # I-30 손절은 닿으면
            tgt_hit = xb.high[w0:w1] > target    # I-30 목표는 관통해야
        else:
            stop_hit = xb.high[w0:w1] >= stop
            tgt_hit = xb.low[w0:w1] < target
        if w0 == entry_j:
            tgt_hit[0] = False                   # §12.1 목표는 체결 다음 실행 봉부터 (I-32)
        ks = int(np.argmax(stop_hit))
        kt = int(np.argmax(tgt_hit))
        s_ok, t_ok = bool(stop_hit[ks]), bool(tgt_hit[kt])
        if s_ok and (not t_ok or ks <= kt):      # §12.1 한 봉에서 둘 다면 손절 먼저
            j = w0 + ks
            price = float(stop)
            if j > entry_j or order_type in OPEN_FILL_TYPES:
                o = float(xb.open[j])            # I-33 시가가 이미 손절 너머(갭)면 더 불리한 시가
                price = min(price, o) if is_long else max(price, o)
            return j, price, Exit.STOP
        if t_ok:
            return w0 + kt, float(target), Exit.TARGET  # §12.2 목표가 지정가 (유리한 갭도 지정가)
        w0, width = w1, width * SCAN_GROWTH
    if jt < n:
        return jt, float(xb.open[jt]), Exit.TIME        # §12.2 신호 봉 72개 뒤 첫 실행 봉 시가
    return n - 1, float(xb.close[n - 1]), Exit.EOD      # I-36 데이터 끝


# ---------------------------------------------------------------------------
# 비용·펀딩 (§8.2, §12.2, I-35)
# ---------------------------------------------------------------------------


def trade_costs(entry_rate, entry_price, exit_price, is_target, cost_multiplier: float = 1.0):
    """(수수료, 슬리피지), 단위당 USDT (§8.2, §12.2). 스칼라·배열 모두 (배열이면 원소별).

    수수료 = (진입 수수료율 × 진입가 + 청산 수수료율 × 청산가) × m — 청산 수수료: 목표 메이커, 손절·시간·끝 테이커
    슬리피지 = 0.02% × 청산가 × m (불리한 방향, 목표 청산은 0)
    """
    exit_rate = np.where(is_target, C.FEE_MAKER, C.FEE_TAKER)
    fees = (entry_rate * entry_price + exit_rate * exit_price) * cost_multiplier
    slippage = np.where(is_target, 0.0, C.SLIPPAGE * exit_price) * cost_multiplier
    return fees, slippage


def funding_prices(xb: ExecArrays, times_ns) -> np.ndarray:
    """펀딩 시각 f의 가격 = f를 포함하는 실행 봉(open_ns ≤ f < close_ns)의 시가 (I-35, "그 시각 가격")."""
    j = np.searchsorted(xb.open_ns, np.asarray(times_ns, dtype=np.int64), side="right") - 1
    return xb.open[np.clip(j, 0, max(len(xb) - 1, 0))]


def funding_start(order_type: str, entry_time_ns, active_from_ns):
    """펀딩 창의 시작(이 시각 < f) (§12.2, I-35). 스칼라·배열 모두.

    지정가: 체결 봉 시작(진입 < f). 시가 체결 주문(ioc_cap·market): min(체결 봉 시작, 활성 시각) —
    5분봉 구간에서는 활성 뒤 첫 5분봉 시가로 체결을 늦춰 잡으므로, 실제로는 활성 시각에 들어가 냈을 그 사이의
    펀딩(예: 활성 07:56, 08:00 봉 시가 체결 → 08:00 펀딩)을 빼지 않는다(검토 F3). 1분봉 구간은 둘이 같다.
    """
    if order_type in OPEN_FILL_TYPES:
        return np.minimum(entry_time_ns, active_from_ns)
    return entry_time_ns


def funding_cost(side: int, entry_time_ns: int, exit_time_ns: int, xb: ExecArrays, fa: FundingArrays,
                 cost_multiplier: float = 1.0) -> float:
    """보유 중 펀딩 비용(단위당, 양수 = 지불) (§12.2, I-35).

    entry_time < f ≤ exit_time 인 펀딩 f마다 x = side × rate_f × price_f (entry_time = funding_start 값),
    price_f = f를 포함하는 실행 봉의 open. 지불(x > 0)은 × cost_multiplier, 수취(x < 0)는 그대로 더한다.
    (2026-09 이후 0.01% 대체값은 data.load_funding이 fa에 넣는다 — 여기서 또 넣지 않는다.)
    """
    k0 = int(np.searchsorted(fa.time_ns, entry_time_ns, side="right"))  # 진입 < f
    k1 = int(np.searchsorted(fa.time_ns, exit_time_ns, side="right"))   # f ≤ 청산
    if k1 <= k0:
        return 0.0
    x = side * fa.rate[k0:k1] * funding_prices(xb, fa.time_ns[k0:k1])   # §12.2 방향 × 비율 × 그 시각 가격
    return float(np.sum(np.where(x > 0, x * cost_multiplier, x)))


def funding_cost_many(side, entry_time_ns, exit_time_ns, xb: ExecArrays, fa: FundingArrays,
                      cost_multiplier: float = 1.0) -> np.ndarray:
    """funding_cost의 배열판(무작위 기준선용): 펀딩 누적합으로 거래 여러 개를 한 번에 계산한다.

    규칙은 funding_cost와 같다(결과는 부동소수 합산 순서 차이 ~1e-12 안에서 같다).
    """
    x = fa.rate * funding_prices(xb, fa.time_ns)            # 롱 1단위 기준 (양수 = 롱이 지불)
    pos = np.r_[0.0, np.cumsum(np.maximum(x, 0.0))]
    neg = np.r_[0.0, np.cumsum(np.minimum(x, 0.0))]
    k0 = np.searchsorted(fa.time_ns, np.asarray(entry_time_ns, dtype=np.int64), side="right")
    k1 = np.searchsorted(fa.time_ns, np.asarray(exit_time_ns, dtype=np.int64), side="right")
    k1 = np.maximum(k1, k0)
    p = pos[k1] - pos[k0]   # 롱이 지불한 합
    q = neg[k1] - neg[k0]   # 롱이 받은 합(음수)
    side = np.asarray(side)
    # 롱: 지불 p × m + 수취 q / 숏: 지불 −q × m + 수취 −p
    return np.where(side > 0, cost_multiplier * p + q, -cost_multiplier * q - p)


# ---------------------------------------------------------------------------
# 계획 하나 시뮬레이션 (I-48)
# ---------------------------------------------------------------------------


def marketable_edge(side: int, limit_price: float, open_price: float) -> float:
    """즉시 체결될 지정가(활성 뒤 첫 봉 시가가 이미 지정가 너머)의 진입 원가 차이, 단위당 USDT (검토 LA-2·F4, 보고용).

    엔진(§12.1): 지정가 × (1 ± 메이커) / 현실적 대안: 첫 봉 시가 × (1 ± 테이커).
    양수 = 엔진이 대안보다 유리(성과를 부풀리는 쪽), 음수 = 엔진이 보수적.
    = side × (시가 × (1 + side × 테이커) − 지정가 × (1 + side × 메이커)).
    """
    return side * (open_price * (1.0 + side * C.FEE_TAKER) - limit_price * (1.0 + side * C.FEE_MAKER))


def simulate_plan(plan: Plan, xb: ExecArrays, fa: FundingArrays, cost_multiplier: float = 1.0) -> TradeResult:
    """계획 하나 → TradeResult (I-48).

    - 미체결: status = cancelled(취소 효력 < 만료) / expired / not_filled(IOC 실패·실행 봉 없음),
      busy_until = 지정가는 plan.order_end, IOC 실패는 시도 봉 close_ns, 봉 없음은 active_from.
      risk_per_unit = 계획 가격 기준(참고값).
    - 체결: 수수료 = (진입 수수료율 × 진입가 + 청산 수수료율 × 청산가) × m
      (진입: limit 메이커, ioc_cap·market 테이커 / 청산: target 메이커, stop·time·eod 테이커),
      슬리피지 = SLIPPAGE × 청산가 × m (stop·time·eod), 펀딩 = funding_cost(funding_start(…) < f ≤ 청산),
      gross = side × (청산가 − 진입가), net = gross − fees − slippage − funding,
      risk_per_unit = config.risk_per_unit(실제 진입가, plan.stop, 진입 수수료율) (I-29),
      r_multiple = net ÷ risk_per_unit,
      size_fraction = min(1, MAX_NOTIONAL_FRAC × 계획 위험 ÷ (RISK_FRACTION × plan.entry_price)) (수량은 계획 시점, I-28),
      busy_until = exit_bar_close_ns = 청산 봉 close_ns.
      즉시 체결될 지정가였으면 meta에 marketable_open(첫 봉 시가)·marketable_edge_r(marketable_edge ÷ R 분모)를 남긴다.
    """
    _check_plan(plan)
    m = float(cost_multiplier)
    entry_rate = C.entry_fee_rate(plan.order_type)
    plan_risk = float(C.risk_per_unit(plan.entry_price, plan.stop, entry_rate))  # 계획 가격 기준 d + c_stop
    # §8.1 수량 = R자본 × r ÷ (d + 비용), 명목 ≤ R자본 × 0.6 → 줄인 비율 (폐기 아님, I-28). 수량은 계획 시점에 정한다
    size_fraction = min(1.0, C.MAX_NOTIONAL_FRAC * plan_risk / (C.RISK_FRACTION * float(plan.entry_price)))
    base = dict(plan_id=plan.plan_id, scenario=plan.scenario, side=int(plan.side), order_type=plan.order_type,
                signal_time=int(plan.signal_time), approval_time=int(plan.approval_time),
                active_from=int(plan.active_from), plan_entry=float(plan.entry_price), stop=float(plan.stop),
                target=float(plan.target), madi_id=plan.madi_id,
                size_fraction=float(size_fraction), cost_multiplier=m, meta=dict(plan.meta))

    n = len(xb)
    j0, _ = entry_window(plan, xb)
    if j0 >= n:  # 활성 시각 뒤에 실행 봉이 없음(데이터 끝)
        return TradeResult(status=Status.NOT_FILLED, busy_until=int(plan.active_from), risk_per_unit=plan_risk,
                           **base)
    fill = find_entry(plan, xb)
    if fill is None:
        if plan.order_type == "limit":
            cet = plan.cancel_effective_time
            cancelled = cet is not None and cet < plan.valid_until
            if cancelled:
                base["meta"]["cancel_reason"] = plan.cancel_reason
            return TradeResult(status=Status.CANCELLED if cancelled else Status.EXPIRED,
                               busy_until=int(plan.order_end), risk_per_unit=plan_risk, **base)
        return TradeResult(status=Status.NOT_FILLED, busy_until=int(xb.close_ns[j0]), risk_per_unit=plan_risk,
                           **base)  # IOC 실패

    entry_j, entry_price = fill
    entry_time = int(xb.open_ns[entry_j])
    # §12.2 R 분모 = d + c_stop, d = |진입가 − 손절가|, 진입가 = 실제 체결가 (I-29, 검토 F1)
    risk = float(C.risk_per_unit(entry_price, plan.stop, entry_rate))
    if plan.order_type == "limit":
        o = float(xb.open[entry_j])
        if entry_j == j0 and (o < entry_price if plan.side > 0 else o > entry_price):
            # 활성 뒤 첫 봉 시가가 이미 지정가 너머 = 실제로는 즉시(테이커) 체결될 주문. §12.1대로 지정가·메이커로
            # 체결하되 표시해 두고 건수·원가 차이를 보고한다 (검토 LA-2·F4)
            base["meta"]["marketable_open"] = o
            base["meta"]["marketable_edge_r"] = marketable_edge(plan.side, entry_price, o) / risk
    exit_j, exit_price, reason = scan_exit(plan.side, entry_j, plan.stop, plan.target,
                                           entry_time + int(plan.max_hold_ns), plan.order_type, xb)
    exit_time = int(xb.open_ns[exit_j])
    exit_close = int(xb.close_ns[exit_j])
    fees, slippage = trade_costs(entry_rate, entry_price, exit_price, reason == Exit.TARGET, m)
    fees, slippage = float(fees), float(slippage)
    f_start = int(funding_start(plan.order_type, entry_time, int(plan.active_from)))  # I-35, 검토 F3
    funding = funding_cost(plan.side, f_start, exit_time, xb, fa, m)
    gross = plan.side * (exit_price - entry_price)
    net = gross - fees - slippage - funding
    return TradeResult(status=Status.FILLED, busy_until=exit_close, risk_per_unit=risk, entry_time=entry_time,
                       entry_price=float(entry_price), exit_time=exit_time, exit_price=float(exit_price),
                       exit_reason=reason, exit_bar_close_ns=exit_close, fees=fees, slippage=slippage,
                       funding=funding, gross_pnl=float(gross), net_pnl=float(net), r_multiple=float(net / risk),
                       **base)


# ---------------------------------------------------------------------------
# 순차 처리 (§12.3)
# ---------------------------------------------------------------------------


def run_sequence(candidates: list[Candidate], xb: ExecArrays, fa: FundingArrays,
                 cfg: ComboConfig) -> tuple[list[TradeResult], list[SignalLog]]:
    """한 조합의 신호를 시간순으로 처리한다 (§12.3, I-19, I-20, I-38).

    후보 순서는 scenarios가 정렬한 그대로. 미리 계산된 사유가 있는 후보는 기록만 한다. 나머지는 차례로:
    F8(같은 madi_id의 'stop' 청산 중 exit_bar_close_ns ≤ 승인 시각인 것이 2건 이상) →
    F9(승인 시각 < 직전 실행 계획의 busy_until) →
    [cfg.apply_availability_mask일 때만] MASK_DND(config.in_dnd) → MASK_DAILY_CAP(그 KST 날짜에 이미 6건 요청) →
    요청 수 +1 → simulate_plan(plan, xb, fa, cfg.cost_multiplier).
    반환: (실행한 계획의 TradeResult 목록(체결 안 된 것 포함), 모든 후보의 SignalLog 목록(입력 순서)).
    통과한 후보의 로그는 status='passed', 폐기는 'discarded' + 사유.

    - F8·F9·MASK_DND는 걸린 것을 모두 기록한다(§6 "걸린 필터는 기록"). MASK_DAILY_CAP은 실제로 보낼
      요청(앞의 셋을 모두 통과)에만 판정한다 — 하루 6건은 실제로 보낸 요청만 센다 (I-38).
    - 실행할 후보의 승인 시각이 거꾸로 가면 ValueError (정렬 누락은 F9 판정을 망친다).
    """
    mask = bool(cfg.apply_availability_mask)
    trades: list[TradeResult] = []
    logs: list[SignalLog] = []
    busy_until: int | None = None           # F9: 실행한 계획이 자리를 차지한 마지막 시각 (I-20, I-48)
    stop_ends: dict[str, list[int]] = {}    # F8: 마디 ID → 'stop' 청산 봉 끝 시각들 (I-19)
    requests: dict[int, int] = {}           # 가용성: KST 날짜 → 보낸 승인 요청 수 (I-38)
    last_t: int | None = None
    for cand in candidates:
        log = cand.log
        if log.reasons:                     # 미리 계산된 사유(WARMUP ~ RISK_RR) → 기록만
            logs.append(log)
            continue
        plan = cand.plan
        t = int(plan.approval_time)
        if last_t is not None and t < last_t:
            raise ValueError(f"후보가 승인 시각 순서가 아님: {plan.plan_id} (scenarios.sort_candidates, I-37)")
        last_t = t

        reasons = []
        if plan.madi_id is not None:        # §6 F8: 같은 마디 근거 신호가 이미 2번 손절 (S3는 madi_id 없음)
            n_stops = sum(1 for e in stop_ends.get(plan.madi_id, ()) if e <= t)
            if n_stops >= C.F8_MAX_STOPS:
                reasons.append(Reason.F8)
        if busy_until is not None and t < busy_until:  # §6 F9: 포지션·대기 주문 보유 중 (같은 시각 끝이면 허용)
            reasons.append(Reason.F9)
        if mask and bool(C.in_dnd(t)):                 # §12.3 방해 금지 KST [00:30, 07:30)
            reasons.append(Reason.MASK_DND)
        day = int(C.kst_day_index(t))
        if mask and not reasons and requests.get(day, 0) >= C.DAILY_APPROVAL_CAP:
            reasons.append(Reason.MASK_DAILY_CAP)      # §12.3 KST 하루 6건 초과분
        if reasons:
            logs.append(dataclasses.replace(log, status="discarded", reasons=sort_reasons(reasons),
                                            plan_id=plan.plan_id))
            continue

        if mask:
            requests[day] = requests.get(day, 0) + 1
        tr = simulate_plan(plan, xb, fa, cfg.cost_multiplier)
        busy_until = tr.busy_until if busy_until is None else max(busy_until, tr.busy_until)
        if tr.exit_reason == Exit.STOP and plan.madi_id is not None:
            stop_ends.setdefault(plan.madi_id, []).append(int(tr.exit_bar_close_ns))
        trades.append(tr)
        logs.append(dataclasses.replace(log, status="passed", reasons=(), plan_id=plan.plan_id))
    return trades, logs
