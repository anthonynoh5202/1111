"""주문 방화벽 — 거래소로 나가는 **모든** 주문이 마지막으로 통과하는 순수 함수 검사 (설계 담당 소유, DESIGN §5).

원칙
- 입력은 요청 + 같은 루프에서 거래소로 조회한 사실(FirewallContext)뿐. DB·네트워크·시계를 직접 보지 않는다.
- 위반이 하나라도 있으면 거부(``FirewallVerdict.ok == False``). 게이트웨이는 거부된 주문을 **절대 보내지 않는다**.
- 위험을 늘리는 주문(진입)은 전부 검사. 위험을 줄이는 주문(손절·추세 청산·비상 청산)은 **환경·심볼·방향·reduceOnly/
  closePosition·ID 규칙만** 검사하고, 계정 모드·정지(T0)·잔고 때문에 막지 않는다(막으면 손절 없는 포지션이 남는다).
- 코드 상수(types.py ① 층)는 설정보다 강하다. 설정 값은 코드 상수 이하일 때만 쓰인다(OrdersConfig.validate).

검사 코드(위반 문자열, 감사 로그·order_events에 그대로 남긴다)
  공통   FW-ENV(실서버·모르는 호스트, 설정 환경과 다른 클라이언트) · FW-SYMBOL · FW-CLIENT-ID(형식·신호·용도)
  진입   FW-HALTED · FW-ENTRY-ONCE · FW-ACCOUNT-MODE · FW-LEVERAGE · FW-MARGIN · FW-RULES · FW-SIDE · FW-TYPE
         FW-TIF · FW-REDUCE-ONLY · FW-POSITION-NOT-FLAT · FW-OPEN-ORDERS · FW-QTY · FW-QTY-STEP · FW-QTY-MIN
         FW-QTY-ABS · FW-PRICE-TICK · FW-PRICE-BAND · FW-NOTIONAL · FW-NOTIONAL-MIN · FW-STOP-PLAN · FW-STOP-DIST
         FW-RISK · FW-BALANCE · FW-MARK
  손절   FW-SIDE · FW-TYPE · FW-CLOSE-POSITION · FW-WORKING-TYPE · FW-PRICE-PROTECT · FW-TRIGGER · FW-TRIGGER-TICK
         FW-TRIGGER-MARK · FW-STOP-DIST · FW-POSITION(롱 포지션 없음, 선배치 경로 제외)
  청산   FW-SIDE · FW-TYPE · FW-REDUCE-ONLY · FW-QTY · FW-QTY-STEP · FW-QTY-OVER-POSITION · FW-POSITION
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Iterable
from urllib.parse import urlparse

from bot.orders.types import (
    ABS_MAX_NOTIONAL_USDT,
    ABS_MAX_QTY_BTC,
    ENV_HOSTS,
    EXIT_PURPOSES,
    FLAT_PURPOSES,
    LIVE_HOSTS,
    MAX_LEVERAGE,
    MAX_PRICE_DEVIATION,
    MAX_RISK_FRACTION,
    MAX_STOP_DISTANCE_FRAC,
    MIN_STOP_DISTANCE_FRAC,
    PRICE_TICK,
    QTY_STEP,
    SYMBOL,
    AccountConfig,
    Balance,
    ConditionalInfo,
    ConditionalRequest,
    IdPurpose,
    OrderInfo,
    OrderRequest,
    OrdersConfig,
    OrderType,
    Side,
    SymbolRules,
    TimeInForce,
    WorkingType,
    is_multiple,
    parse_client_id,
)

_EPS = 1e-9                     # 상대 허용 오차(부동소수 비교)
MARGIN_BUFFER = 1.02            # 필요 증거금(명목 ÷ 레버리지)에 수수료·가격 변동 여유 2%


class OrderPurpose(str, Enum):
    ENTRY = "ENTRY"        # 진입(위험 증가) — IOC 상한 지정가 매수
    STOP = "STOP"          # 보호 손절(조건부 STOP_MARKET closePosition 매도)
    EXIT = "EXIT"          # 추세 청산(reduceOnly 시장가 매도)
    FLATTEN = "FLATTEN"    # 비상 청산(reduceOnly 시장가 매도)


@dataclass(frozen=True)
class FirewallContext:
    """판정 입력: 설정 + 같은 루프에서 조회한 거래소 사실 + 의도(신호) 정보."""

    cfg: OrdersConfig
    client_base_url: str                     # 실제로 요청을 보낼 클라이언트의 주소(모드 = 키 환경, PV-16 #9)
    signal_id: str                           # 이 주문이 속한 의도의 신호 ID
    mark_price: float | None
    position_qty: float                      # 거래소 조회 순포지션(롱 +). 모르면 호출하지 말 것(fail-closed)
    account: AccountConfig | None = None     # 진입에 필수
    rules: SymbolRules | None = None         # 진입에 필수
    balance: Balance | None = None           # 진입에 필수
    open_orders: tuple[OrderInfo, ...] = ()
    open_conditionals: tuple[ConditionalInfo, ...] = ()
    halted: bool = False                     # 풀리지 않은 T0가 있음
    entry_already_sent: bool = False         # 이 의도의 entry_sent_ms가 이미 기록됨(I6: 진입은 한 번)
    planned_stop: float | None = None        # 진입: 이 가격(=상한가) 기준 계획 손절 / 손절: 등록할 트리거
    position_entry_price: float | None = None  # 손절: 체결 평균가(손절 거리 검사 기준)
    pre_entry_stop: bool = False             # 손절 선배치 경로(K1=가능)에서 포지션 0인 상태의 손절 등록


@dataclass(frozen=True)
class FirewallVerdict:
    ok: bool
    purpose: OrderPurpose
    violations: tuple[str, ...]
    detail: dict

    def as_json(self) -> dict:
        return {"ok": self.ok, "purpose": self.purpose.value, "violations": list(self.violations),
                "detail": self.detail}


class FirewallRejected(RuntimeError):
    def __init__(self, verdict: FirewallVerdict) -> None:
        self.verdict = verdict
        super().__init__(f"방화벽 거부 {verdict.purpose.value}: {', '.join(verdict.violations)}")


def _finite_pos(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x)) and float(x) > 0


def _check_env(ctx: FirewallContext, out: list[str]) -> None:
    try:
        host = urlparse(str(ctx.client_base_url)).hostname or ""
        scheme = urlparse(str(ctx.client_base_url)).scheme
    except ValueError:
        out.append("FW-ENV")
        return
    if scheme != "https" or host in LIVE_HOSTS or host != ENV_HOSTS[ctx.cfg.env]:
        out.append("FW-ENV")


def _check_client_id(cid: str, ctx: FirewallContext, allowed: Iterable[IdPurpose], out: list[str]) -> None:
    parsed = parse_client_id(cid)
    if parsed is None or parsed.signal_id != ctx.signal_id or parsed.purpose not in tuple(allowed):
        out.append("FW-CLIENT-ID")


def check_order(req: OrderRequest, purpose: OrderPurpose | str, ctx: FirewallContext) -> FirewallVerdict:
    """일반 주문(진입 / 추세 청산 / 비상 청산) 판정."""
    purpose = OrderPurpose(purpose)
    if purpose is OrderPurpose.STOP:
        raise ValueError("손절은 check_conditional로 검사한다")
    v: list[str] = []
    detail: dict = {}
    _check_env(ctx, v)
    if req.symbol != SYMBOL:
        v.append("FW-SYMBOL")
    if purpose is OrderPurpose.ENTRY:
        _check_entry(req, ctx, v, detail)
    else:
        allowed = EXIT_PURPOSES if purpose is OrderPurpose.EXIT else FLAT_PURPOSES
        _check_client_id(req.client_id, ctx, allowed, v)
        if req.side is not Side.SELL:
            v.append("FW-SIDE")                         # 롱 청산은 매도뿐
        if req.type is not OrderType.MARKET or req.price is not None or req.time_in_force is not None:
            v.append("FW-TYPE")
        if req.reduce_only is not True:
            v.append("FW-REDUCE-ONLY")                  # I7
        if not _finite_pos(req.qty):
            v.append("FW-QTY")
        elif not is_multiple(req.qty, QTY_STEP):
            v.append("FW-QTY-STEP")
        if not (_finite_pos(ctx.position_qty)):
            v.append("FW-POSITION")                     # 줄일 롱 포지션이 없다(숏·0)
        elif _finite_pos(req.qty) and float(req.qty) > float(ctx.position_qty) * (1 + _EPS):
            v.append("FW-QTY-OVER-POSITION")
        detail.update(qty=req.qty, position_qty=ctx.position_qty)
    return FirewallVerdict(not v, purpose, tuple(dict.fromkeys(v)), detail)


def _check_entry(req: OrderRequest, ctx: FirewallContext, v: list[str], detail: dict) -> None:
    from backtest.trend import NOTIONAL_CAP_PER_SYSTEM  # 하위 시스템당 명목 ≤ 0.2 × R 자본

    cfg = ctx.cfg
    _check_client_id(req.client_id, ctx, (IdPurpose.ENTRY,), v)
    if ctx.halted:
        v.append("FW-HALTED")
    if ctx.entry_already_sent:
        v.append("FW-ENTRY-ONCE")                      # I6: 신호당 진입 1회
    acc = ctx.account
    if acc is None:
        v.append("FW-ACCOUNT-MODE")
    else:
        if acc.dual_side_position is not False or acc.multi_assets_margin is not False or acc.can_trade is not True:
            v.append("FW-ACCOUNT-MODE")                 # One-way + Single-Asset(I4)
        if acc.can_withdraw is True:
            v.append("FW-ACCOUNT-MODE")                 # 출금 권한 있는 키 금지(모르면 None — K10)
        if isinstance(acc.leverage, bool) or not isinstance(acc.leverage, int) \
                or not 1 <= acc.leverage <= MAX_LEVERAGE or acc.leverage != cfg.expected_leverage:
            v.append("FW-LEVERAGE")
        if str(acc.margin_type).lower() != "isolated":
            v.append("FW-MARGIN")
    rules = ctx.rules
    if rules is None or rules.symbol != SYMBOL or rules.status != "TRADING" \
            or not math.isclose(rules.tick_size, PRICE_TICK) or not math.isclose(rules.step_size, QTY_STEP):
        v.append("FW-RULES")
    if req.side is not Side.BUY:
        v.append("FW-SIDE")                             # 롱만
    if req.type is not OrderType.LIMIT:
        v.append("FW-TYPE")                             # 순수 시장가 진입 금지(ARCHITECTURE §3.4)
    if req.time_in_force is not TimeInForce.IOC:
        v.append("FW-TIF")                              # 이 단계는 IOC 상한 지정가만(대기 지정가 없음)
    if req.reduce_only:
        v.append("FW-REDUCE-ONLY")
    if not (isinstance(ctx.position_qty, (int, float)) and float(ctx.position_qty) == 0.0):
        v.append("FW-POSITION-NOT-FLAT")                # 진입 전 포지션 0(I6)
    if ctx.open_orders:
        v.append("FW-OPEN-ORDERS")
    own_sl = [c for c in ctx.open_conditionals
              if (p := parse_client_id(c.client_algo_id)) is not None and p.signal_id == ctx.signal_id
              and p.purpose is IdPurpose.STOP]
    if len(ctx.open_conditionals) != (len(own_sl) if ctx.cfg.stop_placement.value == "pre_entry" else 0):
        v.append("FW-OPEN-ORDERS")                      # 선배치 경로의 자기 손절 말고는 조건부 주문도 없어야 한다

    mark = ctx.mark_price
    if not _finite_pos(mark):
        v.append("FW-MARK")
        mark = None
    qty, price = req.qty, req.price
    if not _finite_pos(qty):
        v.append("FW-QTY")
        qty = None
    else:
        if not is_multiple(qty, QTY_STEP):
            v.append("FW-QTY-STEP")
        if rules is not None and float(qty) < float(rules.min_qty) * (1 - _EPS):
            v.append("FW-QTY-MIN")
        if float(qty) > ABS_MAX_QTY_BTC * (1 + _EPS):
            v.append("FW-QTY-ABS")
    if not _finite_pos(price):
        v.append("FW-PRICE-BAND")
        price = None
    else:
        if not is_multiple(price, PRICE_TICK):
            v.append("FW-PRICE-TICK")
        if mark is not None:
            cap = mark * (1 + cfg.ioc_cap_bps / 10_000) + PRICE_TICK      # 올림 한 틱 허용
            hard = mark * (1 + MAX_PRICE_DEVIATION)
            if not (mark * (1 - _EPS) <= float(price) <= min(cap, hard)):
                v.append("FW-PRICE-BAND")               # 매수 상한가는 마크 이상 ~ 마크×(1+폭) (PV-16 #3)
    if qty is not None and price is not None:
        notional = float(qty) * float(price)
        cap_notional = min(cfg.max_notional_usdt, ABS_MAX_NOTIONAL_USDT,
                           cfg.r_capital_usdt * NOTIONAL_CAP_PER_SYSTEM)
        detail.update(notional=notional, notional_cap=cap_notional)
        if notional > cap_notional * (1 + _EPS):
            v.append("FW-NOTIONAL")
        if rules is not None and notional < float(rules.min_notional):
            v.append("FW-NOTIONAL-MIN")
        stop = ctx.planned_stop
        if not _finite_pos(stop) or float(stop) >= float(price):
            v.append("FW-STOP-PLAN")                    # I1: 손절 없는 계획은 통과 불가
        else:
            dist = (float(price) - float(stop)) / float(price)
            detail.update(stop=stop, stop_distance_frac=dist)
            if not MIN_STOP_DISTANCE_FRAC <= dist <= MAX_STOP_DISTANCE_FRAC:
                v.append("FW-STOP-DIST")
            risk = float(qty) * (float(price) - float(stop))                # 최악 체결가(상한가) 기준
            risk_cap = cfg.r_capital_usdt * min(cfg.risk_fraction, MAX_RISK_FRACTION)
            detail.update(risk_usdt=risk, risk_cap_usdt=risk_cap)
            if risk > risk_cap * (1 + 1e-6):
                v.append("FW-RISK")                     # I5
        bal = ctx.balance
        need = notional / max(1, int(acc.leverage) if acc is not None and isinstance(acc.leverage, int) else 1)
        detail.update(margin_needed=need * MARGIN_BUFFER)
        if bal is None or bal.asset != "USDT" or not math.isfinite(bal.available_balance) \
                or bal.available_balance < need * MARGIN_BUFFER:
            v.append("FW-BALANCE")                      # PV-16 #7
    detail.update(qty=req.qty, price=req.price, mark=ctx.mark_price)


def check_conditional(req: ConditionalRequest, ctx: FirewallContext) -> FirewallVerdict:
    """보호 손절(조건부 STOP_MARKET closePosition SELL) 판정. 정지(T0)·계정 모드로는 막지 않는다."""
    v: list[str] = []
    _check_env(ctx, v)
    if req.symbol != SYMBOL:
        v.append("FW-SYMBOL")
    _check_client_id(req.client_algo_id, ctx, (IdPurpose.STOP,), v)
    if req.side is not Side.SELL:
        v.append("FW-SIDE")
    if req.type is not OrderType.STOP_MARKET:
        v.append("FW-TYPE")                             # 지정가형 STOP은 손절에 쓰지 않는다(08 §2.5)
    if req.close_position is not True:
        v.append("FW-CLOSE-POSITION")                   # I7
    if req.working_type is not WorkingType.MARK_PRICE:
        v.append("FW-WORKING-TYPE")
    if req.price_protect is not False:
        v.append("FW-PRICE-PROTECT")
    trig = req.trigger_price
    detail: dict = {"trigger": trig, "mark": ctx.mark_price, "position_qty": ctx.position_qty}
    if not _finite_pos(trig):
        v.append("FW-TRIGGER")
    else:
        if not is_multiple(trig, PRICE_TICK):
            v.append("FW-TRIGGER-TICK")
        if ctx.planned_stop is None or not math.isclose(float(trig), float(ctx.planned_stop), rel_tol=0, abs_tol=1e-9):
            v.append("FW-TRIGGER")                      # 게이트웨이가 계산한 계획 손절과 같아야 한다
        if _finite_pos(ctx.mark_price) and float(trig) >= float(ctx.mark_price):
            v.append("FW-TRIGGER-MARK")                 # 매도 손절은 마크 아래(아니면 즉시 발동 — 게이트웨이가 따로 처리)
        ref = ctx.position_entry_price
        if not _finite_pos(ref):
            v.append("FW-STOP-DIST")
        else:
            dist = (float(ref) - float(trig)) / float(ref)
            detail["stop_distance_frac"] = dist
            # 체결가가 상한가보다 낮으면 거리가 조금 짧아질 수 있다 → 하한은 절반까지 허용
            if not (MIN_STOP_DISTANCE_FRAC * 0.5 <= dist <= MAX_STOP_DISTANCE_FRAC):
                v.append("FW-STOP-DIST")
    if ctx.pre_entry_stop:
        if ctx.cfg.stop_placement.value != "pre_entry" or float(ctx.position_qty) != 0.0:
            v.append("FW-POSITION")
    elif not _finite_pos(ctx.position_qty):
        v.append("FW-POSITION")                         # 롱 포지션이 있어야 한다(숏이면 closePosition SELL이 맞지 않음)
    return FirewallVerdict(not v, OrderPurpose.STOP, tuple(dict.fromkeys(v)), detail)


def enforce_order(req: OrderRequest, purpose: OrderPurpose | str, ctx: FirewallContext) -> FirewallVerdict:
    verdict = check_order(req, purpose, ctx)
    if not verdict.ok:
        raise FirewallRejected(verdict)
    return verdict


def enforce_conditional(req: ConditionalRequest, ctx: FirewallContext) -> FirewallVerdict:
    verdict = check_conditional(req, ctx)
    if not verdict.ok:
        raise FirewallRejected(verdict)
    return verdict
