"""진입 계획·손절 계산(순수 함수) — 설계 담당 소유 (DESIGN §4.2).

- 손절·R 분모 공식은 ``bot.strategy``(= backtest.trend 재사용)를 그대로 부른다. 식을 옮겨 적지 않는다.
- 수량은 모의 매매(paper.position_size)와 같은 규칙 min(R×r ÷ R분모, R×0.2 ÷ 가격)에 절대 상한·설정 상한을 더하고
  거래소 수량 단위로 **내림**한다. 최소 수량·최소 명목 미달이면 진입하지 않는다(REJECTED — 손절을 좁혀 맞추지 않는다).
- 가격 기준: 진입 계획은 IOC 상한가(최악의 체결가) 기준으로 위험을 계산한다(ARCHITECTURE §2.3 R3).
  실제 보호 손절은 **체결 평균가** 기준으로 다시 계산한다(모의 매매·백테스트와 같은 뜻: 손절 = 체결가 − 2×ATR20).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from bot.orders.types import (
    ABS_MAX_NOTIONAL_USDT,
    ABS_MAX_QTY_BTC,
    MAX_RISK_FRACTION,
    PRICE_TICK,
    QTY_STEP,
    OrdersConfig,
    SymbolRules,
    ceil_to_step,
    floor_to_step,
)


@dataclass(frozen=True)
class EntryPlan:
    mark_price: float
    limit_price: float         # IOC 상한 매수가 = ceil_tick(mark × (1 + cap))
    planned_stop: float        # 상한가 기준 계획 손절(방화벽 위험 검사용)
    qty: float                 # BTC, 수량 단위로 내림
    notional: float            # qty × limit_price
    risk_per_unit: float       # 상한가 기준 R 분모(수수료·슬리피지 포함)
    risk_usdt: float           # qty × (limit − planned_stop)


class PlanRejected(ValueError):
    """진입 불가(사유 코드). 게이트웨이는 REJECTED(사유)로 끝낸다 — 주문 없음."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _pos(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x)) and float(x) > 0


def stop_for_fill(avg_fill_price: float, atr20: float) -> float:
    """체결 평균가 기준 보호 손절 = round_price(체결가 − 2 × ATR20) (paper·backtest와 같은 함수)."""
    from bot.strategy import protective_stop

    if not (_pos(avg_fill_price) and _pos(atr20)):
        raise ValueError("체결가·ATR20은 양의 유한수")
    return float(protective_stop(float(avg_fill_price), float(atr20), 1))


def plan_entry(*, mark_price: float, atr20: float, cfg: OrdersConfig, rules: SymbolRules) -> EntryPlan:
    """마크 가격과 신호 ATR20으로 IOC 상한 진입 계획. 불가하면 PlanRejected(사유)."""
    from backtest.trend import NOTIONAL_CAP_PER_SYSTEM
    from bot.strategy import protective_stop, risk_per_unit

    if not (_pos(mark_price) and _pos(atr20)):
        raise PlanRejected("bad_input")
    limit = ceil_to_step(float(mark_price) * (1 + cfg.ioc_cap_bps / 10_000), PRICE_TICK)
    stop = float(protective_stop(limit, float(atr20), 1))
    if not _pos(stop) or stop >= limit:
        raise PlanRejected("bad_stop")
    rpu = float(risk_per_unit(limit, stop))
    if not _pos(rpu):
        raise PlanRejected("bad_stop")
    r_cap = float(cfg.r_capital_usdt)
    risk_frac = min(float(cfg.risk_fraction), MAX_RISK_FRACTION)
    notional_cap = min(r_cap * NOTIONAL_CAP_PER_SYSTEM, float(cfg.max_notional_usdt), ABS_MAX_NOTIONAL_USDT)
    raw_qty = min(r_cap * risk_frac / rpu, notional_cap / limit, ABS_MAX_QTY_BTC)
    step = max(float(rules.step_size), QTY_STEP)
    qty = floor_to_step(raw_qty, step)
    if qty <= 0 or qty < float(rules.min_qty):
        raise PlanRejected("below_min_qty")
    notional = qty * limit
    if notional < float(rules.min_notional):
        raise PlanRejected("below_min_notional")
    return EntryPlan(mark_price=float(mark_price), limit_price=limit, planned_stop=stop, qty=qty,
                     notional=notional, risk_per_unit=rpu, risk_usdt=qty * (limit - stop))
