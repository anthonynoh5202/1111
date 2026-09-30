"""가짜 거래소(fake_exchange) 시험 — DESIGN §12·§15.3: 바이낸스 규칙 각각 + 장애 종류 각각의 효과."""
from __future__ import annotations

import pytest

from bot.orders.fake_exchange import ALL_METHODS, FakeExchange, Fault, FaultKind
from bot.orders.tests.conftest import MARK
from bot.orders.types import (
    SYMBOL,
    ConditionalApi,
    ConditionalRequest,
    ConditionalStatus,
    ErrorKind,
    ExchangeClient,
    ExchangeEnv,
    ExchangeError,
    OrderRequest,
    OrderStatus,
    OrderType,
    Side,
    TimeInForce,
    WorkingType,
    env_base_url,
)
from bot.types import NS_PER_MS

SID = "ABCDEFGHIJKLMNOP"
E1 = f"sig-{SID}-e1"
SL = f"sig-{SID}-sl"
F1 = f"sig-{SID}-f1"
X1 = f"sig-{SID}-x1"


def entry(qty: float = 0.05, price: float = 60_060.0, cid: str = E1, **kw) -> OrderRequest:
    return OrderRequest(symbol=SYMBOL, side=Side.BUY, type=OrderType.LIMIT, qty=qty, client_id=cid, price=price,
                        time_in_force=TimeInForce.IOC, **kw)


def sell_ro(qty: float, cid: str = F1) -> OrderRequest:
    return OrderRequest(symbol=SYMBOL, side=Side.SELL, type=OrderType.MARKET, qty=qty, client_id=cid,
                        reduce_only=True)


def stop(trigger: float = 57_000.0, cid: str = SL, **kw) -> ConditionalRequest:
    return ConditionalRequest(symbol=SYMBOL, side=Side.SELL, type=OrderType.STOP_MARKET, trigger_price=trigger,
                              client_algo_id=cid, **kw)


def code_of(excinfo) -> int | None:
    return excinfo.value.code


@pytest.fixture
def fx(fake_exchange) -> FakeExchange:
    return fake_exchange


# ---------------------------------------------------------------------------
# 기본·인터페이스
# ---------------------------------------------------------------------------


def test_protocol_and_env(fx):
    assert isinstance(fx, ExchangeClient)
    assert fx.env is ExchangeEnv.DEMO
    assert fx.base_url == env_base_url(ExchangeEnv.DEMO)
    assert fx.symbol_rules().tick_size == 0.1
    acc = fx.account_config()
    assert (acc.dual_side_position, acc.multi_assets_margin, acc.leverage, acc.margin_type) == (
        False, False, 3, "isolated")
    assert fx.mark_price() == MARK
    assert fx.position().qty == 0
    assert fx.open_orders() == [] and fx.open_conditional_orders() == []


def test_base_url_override_and_testnet_env(oclock):
    fx = FakeExchange(oclock, env=ExchangeEnv.TESTNET)
    assert fx.base_url == "https://testnet.binancefuture.com"
    fx2 = FakeExchange(oclock, base_url="https://fapi.binance.com")
    assert fx2.base_url == "https://fapi.binance.com"   # 방화벽 시험용(실서버 주소 거부 확인)


def test_server_time_follows_clock(fx, oclock):
    t0 = fx.server_time_ms()
    fx.tick(1500)
    assert fx.server_time_ms() == t0 + 1500
    assert t0 == oclock.now_ns() // NS_PER_MS - 1500


# ---------------------------------------------------------------------------
# 일반 주문
# ---------------------------------------------------------------------------


def test_ioc_full_fill_updates_position_and_balance(fx):
    before = fx.balance()
    info = fx.place_order(entry(0.05))
    assert info.status is OrderStatus.FILLED
    assert info.executed_qty == 0.05 and info.avg_price == 60_000.0
    assert info.time_in_force == "IOC" and info.client_id == E1
    pos = fx.position()
    assert pos.qty == 0.05 and pos.entry_price == 60_000.0 and pos.leverage == 3
    bal = fx.balance()
    fee = 0.05 * 60_000 * 0.0005
    assert bal.wallet_balance == pytest.approx(before.wallet_balance - fee)
    assert bal.available_balance == pytest.approx(bal.wallet_balance - 0.05 * 60_000 / 3)
    assert fx.get_order(E1).status is OrderStatus.FILLED
    assert fx.open_orders() == []          # IOC는 걸리지 않는다


def test_ioc_below_ask_no_fill(fx):
    info = fx.place_order(entry(0.05, price=59_990.0))
    assert info.status is OrderStatus.EXPIRED and info.executed_qty == 0 and info.avg_price == 0
    assert fx.position().qty == 0


def test_ioc_partial_by_book_depth_is_expired_with_fill(fx):
    fx.set_book(asks=[(60_000.0, 0.02), (60_050.0, 0.01), (60_100.0, 5.0)])
    info = fx.place_order(entry(0.05, price=60_060.0))
    assert info.status is OrderStatus.EXPIRED        # K6: 부분 체결 IOC = EXPIRED + executedQty > 0
    assert info.executed_qty == 0.03
    assert info.avg_price == pytest.approx((0.02 * 60_000 + 0.01 * 60_050) / 0.03)
    assert fx.position().qty == 0.03
    fx.set_book()                                    # 자동 호가 복귀
    assert fx.place_order(entry(0.01, cid=f"sig-{SID}-x2")).status is OrderStatus.FILLED


def test_reduce_only_rules_and_pnl(fx):
    with pytest.raises(ExchangeError) as ei:
        fx.place_order(sell_ro(0.01))
    assert code_of(ei) == -2022 and ei.value.kind is ErrorKind.REDUCE_ONLY_REJECTED
    fx.place_order(entry(0.05))
    with pytest.raises(ExchangeError) as ei:
        fx.place_order(sell_ro(0.06))
    assert code_of(ei) == -2022
    fx.set_mark(61_000.0)
    info = fx.place_order(sell_ro(0.05))
    assert info.status is OrderStatus.FILLED and info.reduce_only
    assert info.avg_price == 60_999.9                 # bid = ask − 1틱
    assert fx.position().qty == 0
    assert fx.realized_pnl == pytest.approx(0.05 * 999.9)


def test_market_buy_and_non_reduce_sell_open_short(fx):
    # 거래소는 숏을 막지 않는다(막는 것은 방화벽). 순포지션 계산 확인.
    fx.place_order(OrderRequest(symbol=SYMBOL, side=Side.BUY, type=OrderType.MARKET, qty=0.01, client_id="m1"))
    fx.place_order(OrderRequest(symbol=SYMBOL, side=Side.SELL, type=OrderType.MARKET, qty=0.03, client_id="m2"))
    pos = fx.position()
    assert pos.qty == -0.02 and pos.entry_price == 59_999.9


@pytest.mark.parametrize("req, code", [
    (OrderRequest(symbol="ETHUSDT", side=Side.BUY, type=OrderType.LIMIT, qty=0.01, client_id=E1, price=60_000.0,
                  time_in_force=TimeInForce.IOC), -1121),
    (entry(price=60_000.05), -4014),
    (entry(price=63_500.0), -4016),
    (entry(qty=0.0015), -1111),
    (entry(qty=0.0), -4003),
    (entry(qty=0.05, cid="bad id!"), -1100),
    (OrderRequest(symbol=SYMBOL, side=Side.BUY, type=OrderType.LIMIT, qty=0.01, client_id=E1), -1102),
    (OrderRequest(symbol=SYMBOL, side=Side.BUY, type=OrderType.MARKET, qty=0.01, client_id=E1, price=1.0), -1106),
    (OrderRequest(symbol=SYMBOL, side=Side.SELL, type=OrderType.STOP_MARKET, qty=0.01, client_id=SL), -4120),
    (entry(qty=0.9), -2019),                          # 0.9×60060/3 = 18,018 > 10,000
])
def test_order_validation_codes(fx, req, code):
    with pytest.raises(ExchangeError) as ei:
        fx.place_order(req)
    assert code_of(ei) == code
    rec = fx.calls[-1]
    assert rec.method == "place_order" and rec.outcome.startswith("error:") and rec.reached_exchange
    assert fx.position().qty == 0


def test_min_qty_and_min_notional(oclock):
    from bot.orders.tests.conftest import good_rules

    fx = FakeExchange(oclock, mark=MARK, rules=good_rules(min_qty=0.002, min_notional=100.0))
    with pytest.raises(ExchangeError) as ei:
        fx.place_order(entry(qty=0.001))
    assert code_of(ei) == -4004
    assert fx.place_order(entry(qty=0.002)).status is OrderStatus.FILLED   # 0.002 × 60,000 = 120 ≥ 100
    fx2 = FakeExchange(oclock, mark=MARK, rules=good_rules(min_notional=200.0))
    with pytest.raises(ExchangeError) as ei:
        fx2.place_order(entry(qty=0.003))
    assert code_of(ei) == -4164 and ei.value.kind is ErrorKind.MIN_NOTIONAL
    # reduceOnly는 최소 명목 예외
    fx2.place_order(entry(qty=0.004, cid="big"))
    assert fx2.place_order(sell_ro(0.001)).status is OrderStatus.FILLED


def test_account_mode_and_permissions(fx):
    fx.set_account(dual_side_position=True)
    with pytest.raises(ExchangeError) as ei:
        fx.place_order(entry())
    assert code_of(ei) == -4061 and ei.value.kind is ErrorKind.ACCOUNT_MODE
    with pytest.raises(ExchangeError) as ei:
        fx.place_conditional(stop())
    assert code_of(ei) == -4061
    fx.set_account(dual_side_position=False, can_trade=False)
    with pytest.raises(ExchangeError) as ei:
        fx.place_order(entry())
    assert ei.value.kind is ErrorKind.AUTH
    fx.set_account(can_trade=True)
    fx.set_rules(status="BREAK")
    with pytest.raises(ExchangeError) as ei:
        fx.place_order(entry())
    assert ei.value.kind is ErrorKind.BAD_REQUEST


def test_client_id_unique_only_among_open_orders(fx):
    gtc = OrderRequest(symbol=SYMBOL, side=Side.BUY, type=OrderType.LIMIT, qty=0.01, client_id="rest1",
                       price=59_000.0, time_in_force=TimeInForce.GTC)
    assert fx.place_order(gtc).status is OrderStatus.NEW
    with pytest.raises(ExchangeError) as ei:
        fx.place_order(gtc)
    assert code_of(ei) == -4116 and ei.value.outcome_unknown
    # 끝난 IOC와 같은 ID로 다시 보내면 새 주문으로 체결된다(재전송 금지 I15가 필요한 이유)
    fx.place_order(entry(0.01))
    fx.place_order(entry(0.01))
    assert fx.position().qty == 0.02
    assert len([o for o in fx.all_orders() if o.client_id == E1]) == 2
    assert fx.get_order(E1).exchange_order_id == [o for o in fx.all_orders() if o.client_id == E1][-1].exchange_order_id


def test_resting_limit_fills_when_price_reaches(fx):
    gtc = OrderRequest(symbol=SYMBOL, side=Side.BUY, type=OrderType.LIMIT, qty=0.01, client_id="rest1",
                       price=59_000.0, time_in_force=TimeInForce.GTC)
    fx.place_order(gtc)
    assert [o.client_id for o in fx.open_orders()] == ["rest1"]
    fx.set_mark(58_950.0)
    assert fx.open_orders() == []
    assert fx.get_order("rest1").status is OrderStatus.FILLED
    assert fx.position().qty == 0.01


def test_gtx_crossing_expires(fx):
    req = OrderRequest(symbol=SYMBOL, side=Side.BUY, type=OrderType.LIMIT, qty=0.01, client_id="px",
                       price=60_010.0, time_in_force=TimeInForce.GTX)
    assert fx.place_order(req).status is OrderStatus.EXPIRED
    assert fx.position().qty == 0


def test_cancel_order_semantics(fx):
    gtc = OrderRequest(symbol=SYMBOL, side=Side.BUY, type=OrderType.LIMIT, qty=0.01, client_id="rest1",
                       price=59_000.0, time_in_force=TimeInForce.GTC)
    fx.place_order(gtc)
    assert fx.cancel_order("rest1").status is OrderStatus.CANCELED
    assert fx.open_orders() == []
    assert fx.cancel_order("nope") is None
    fx.place_order(entry())
    with pytest.raises(ExchangeError) as ei:
        fx.cancel_order(E1)
    assert code_of(ei) == -2011 and ei.value.kind is ErrorKind.CANCEL_REJECTED
    assert fx.get_order("nope") is None


# ---------------------------------------------------------------------------
# 조건부(algo) 주문
# ---------------------------------------------------------------------------


def test_conditional_place_list_get_cancel(fx):
    fx.place_order(entry())
    info = fx.place_conditional(stop(57_000.0))
    assert info.status is ConditionalStatus.NEW and info.close_position and info.trigger_price == 57_000.0
    assert info.working_type is WorkingType.MARK_PRICE and info.price_protect is False and info.qty == 0
    lst = fx.open_conditional_orders()
    assert [c.client_algo_id for c in lst] == [SL]
    assert fx.get_conditional(SL) == lst[0]
    assert fx.open_orders() == []                    # 일반 주문 목록에는 없다
    assert fx.cancel_conditional(SL).status is ConditionalStatus.CANCELED
    assert fx.open_conditional_orders() == []
    assert fx.get_conditional(SL).status is ConditionalStatus.CANCELED
    assert fx.cancel_conditional("nope") is None
    with pytest.raises(ExchangeError) as ei:
        fx.cancel_conditional(SL)
    assert code_of(ei) == -2011


def test_conditional_would_trigger(fx):
    fx.place_order(entry())
    with pytest.raises(ExchangeError) as ei:
        fx.place_conditional(stop(60_000.0))
    assert code_of(ei) == -2021 and ei.value.kind is ErrorKind.WOULD_TRIGGER and not ei.value.halts
    with pytest.raises(ExchangeError) as ei:
        fx.place_conditional(stop(57_000.05))
    assert code_of(ei) == -4014


def test_conditional_duplicates(fx):
    fx.place_order(entry())
    fx.place_conditional(stop())
    with pytest.raises(ExchangeError) as ei:
        fx.place_conditional(stop())
    assert code_of(ei) == -4116
    with pytest.raises(ExchangeError) as ei:
        fx.place_conditional(stop(cid="sig-ABCDEFGHIJKLMNOQ-sl"))
    assert code_of(ei) == -4130                      # 같은 방향 closePosition 이미 있음
    assert len(fx.open_conditional_orders()) == 1


def test_legacy_endpoint_minus_4120_and_supported(oclock):
    fx = FakeExchange(oclock, mark=MARK, conditional_api=ConditionalApi.LEGACY)
    fx.place_order(entry())
    with pytest.raises(ExchangeError) as ei:
        fx.place_conditional(stop())
    assert code_of(ei) == -4120 and ei.value.kind is ErrorKind.ALGO_ENDPOINT_REQUIRED and ei.value.halts
    fx2 = FakeExchange(oclock, mark=MARK, conditional_api=ConditionalApi.LEGACY, legacy_conditional_supported=True)
    fx2.place_order(entry())
    assert fx2.place_conditional(stop()).status is ConditionalStatus.NEW


def test_k1_prearm_both_paths(oclock):
    ok = FakeExchange(oclock, mark=MARK)                           # 가능 경로
    assert ok.place_conditional(stop()).status is ConditionalStatus.NEW
    no = FakeExchange(oclock, mark=MARK, prearm_close_position_allowed=False)   # 불가 경로
    with pytest.raises(ExchangeError) as ei:
        no.place_conditional(stop())
    assert code_of(ei) == -2022
    no.place_order(entry())
    assert no.place_conditional(stop()).status is ConditionalStatus.NEW


def test_k7_price_protect_false_rejected(oclock):
    fx = FakeExchange(oclock, mark=MARK, price_protect_false_allowed=False)
    fx.place_order(entry())
    with pytest.raises(ExchangeError):
        fx.place_conditional(stop())
    assert fx.place_conditional(stop(price_protect=True)).price_protect is True


def test_conditional_requires_close_position_and_stop_market(fx):
    fx.place_order(entry())
    with pytest.raises(ExchangeError) as ei:
        fx.place_conditional(stop(close_position=False))
    assert code_of(ei) == -1102
    with pytest.raises(ExchangeError) as ei:
        fx.place_conditional(ConditionalRequest(symbol=SYMBOL, side=Side.SELL, type=OrderType.LIMIT,
                                                trigger_price=57_000.0, client_algo_id=SL))
    assert code_of(ei) == -1116


def test_stop_triggers_and_closes_position(fx):
    fx.place_order(entry(0.05))
    fx.place_conditional(stop(57_000.0))
    fx.set_mark(57_000.1)
    assert fx.position().qty == 0.05
    fx.set_book(bids=[(56_900.0, 0.03), (56_800.0, 10.0)])       # 급락 슬리피지
    fx.set_mark(56_990.0)
    assert fx.position().qty == 0
    c = fx.get_conditional(SL)
    assert c.status is ConditionalStatus.FINISHED
    assert fx.open_conditional_orders() == []
    trig = fx.triggered_orders()
    assert len(trig) == 1 and trig[0].status is OrderStatus.FILLED and trig[0].close_position
    assert trig[0].avg_price == pytest.approx((0.03 * 56_900 + 0.02 * 56_800) / 0.05)
    assert fx.open_orders() == []
    assert fx.realized_pnl < 0


def test_stop_fired_without_position_expires_and_orphan_kept(fx):
    fx.place_order(entry(0.05))
    fx.place_conditional(stop(57_000.0))
    fx.place_order(sell_ro(0.05))                    # 추세 청산 → 고아 손절(K14 기본: 자동 취소 없음)
    assert [c.client_algo_id for c in fx.open_conditional_orders()] == [SL]
    fx.set_mark(56_000.0)
    assert fx.get_conditional(SL).status is ConditionalStatus.EXPIRED
    assert fx.position().qty == 0


def test_k14_auto_cancel_on_flat(oclock):
    fx = FakeExchange(oclock, mark=MARK, auto_cancel_close_position_on_flat=True)
    fx.place_order(entry(0.05))
    fx.place_conditional(stop())
    fx.place_order(sell_ro(0.05))
    assert fx.open_conditional_orders() == []
    assert fx.get_conditional(SL).status is ConditionalStatus.CANCELED


def test_k5_fired_status_and_retention(oclock):
    fx = FakeExchange(oclock, mark=MARK, fired_status=ConditionalStatus.TRIGGERED, algo_query_retention_ms=60_000)
    fx.place_order(entry())
    fx.place_conditional(stop())
    fx.set_mark(56_000.0)
    assert fx.get_conditional(SL).status is ConditionalStatus.TRIGGERED
    fx.tick(60_001)
    assert fx.get_conditional(SL) is None


# ---------------------------------------------------------------------------
# 서명 시각(-1021)
# ---------------------------------------------------------------------------


def test_signed_requests_minus_1021_when_local_ahead(fx):
    fx.client_offset_ms = 1_500                       # 로컬(timestamp)이 서버보다 1.5초 앞섬
    with pytest.raises(ExchangeError) as ei:
        fx.place_order(entry())
    assert code_of(ei) == -1021 and ei.value.kind is ErrorKind.CLOCK_SKEW
    assert fx.server_time_ms() > 0                    # 공개 요청은 영향 없음
    assert fx.position_qty == 0
    fx.client_offset_ms = -5_001                      # timestamp가 recvWindow보다 오래됨
    with pytest.raises(ExchangeError) as ei:
        fx.position()
    assert code_of(ei) == -1021
    fx.client_offset_ms = 0
    assert fx.position().qty == 0


# ---------------------------------------------------------------------------
# 장애 주입
# ---------------------------------------------------------------------------


def test_fault_timeout_before_not_delivered(fx):
    fx.inject(Fault(FaultKind.TIMEOUT_BEFORE, method="place_order"))
    with pytest.raises(ExchangeError) as ei:
        fx.place_order(entry())
    assert ei.value.kind is ErrorKind.OUTCOME_UNKNOWN and ei.value.http_status is None
    assert fx.get_order(E1) is None and fx.position().qty == 0
    assert fx.post_count("place_order") == 1 and fx.post_count("place_order", reached_only=True) == 0
    assert fx.calls_for("place_order")[0].outcome == "fault:timeout_before"


def test_fault_timeout_after_processed(fx):
    fx.inject(Fault(FaultKind.TIMEOUT_AFTER, method="place_order"))
    with pytest.raises(ExchangeError) as ei:
        fx.place_order(entry(0.05))
    assert ei.value.outcome_unknown
    assert fx.get_order(E1).executed_qty == 0.05 and fx.position().qty == 0.05
    assert fx.post_count("place_order", reached_only=True) == 1


def test_fault_timeout_after_on_conditional_and_cancel(fx):
    fx.place_order(entry())
    fx.inject(Fault(FaultKind.TIMEOUT_AFTER, method="place_conditional"))
    with pytest.raises(ExchangeError):
        fx.place_conditional(stop())
    assert fx.get_conditional(SL).status is ConditionalStatus.NEW
    fx.inject(Fault(FaultKind.TIMEOUT_AFTER, method="cancel_conditional"))
    with pytest.raises(ExchangeError):
        fx.cancel_conditional(SL)
    assert fx.open_conditional_orders() == []


def test_fault_duplicate_response_replay(fx):
    fx.inject(Fault(FaultKind.DUPLICATE_RESPONSE, method="place_order"))
    info = fx.place_order(entry(0.05))
    assert fx.duplicates == [info]
    assert fx.position().qty == 0.05                 # 효과는 한 번
    assert fx.post_count("place_order") == 1


def test_fault_duplicate_resend_ioc_double_fills_and_algo_dedup(fx):
    fx.inject(Fault(FaultKind.DUPLICATE_RESPONSE, method="place_order", params={"mode": "resend"}))
    fx.place_order(entry(0.05))
    assert fx.position().qty == 0.1                   # 네트워크 중복 도착 → IOC는 다시 체결(실제 규칙)
    assert fx.post_count("place_order") == 1 and fx.post_count("place_order#dup") == 1
    fx.inject(Fault(FaultKind.DUPLICATE_RESPONSE, method="place_conditional", params={"mode": "resend"}))
    fx.place_conditional(stop())
    assert len(fx.open_conditional_orders()) == 1     # 두 번째는 -4116
    assert fx.calls_for("place_conditional#dup")[0].outcome == "error:DUPLICATE_CLIENT_ID"


def test_fault_partial_and_no_fill(fx):
    fx.inject(Fault(FaultKind.PARTIAL_FILL, fill_ratio=0.4))
    info = fx.place_order(entry(0.05))
    assert info.status is OrderStatus.EXPIRED and info.executed_qty == 0.02
    fx.inject(Fault(FaultKind.NO_FILL))
    info = fx.place_order(entry(0.05, cid=f"sig-{SID}-x2"))
    assert info.status is OrderStatus.EXPIRED and info.executed_qty == 0
    assert fx.position().qty == 0.02
    fx.inject(Fault(FaultKind.PARTIAL_FILL, fill_ratio=0.001))   # 0이 되면 최소 1 step
    assert fx.place_order(entry(0.05, cid=f"sig-{SID}-x3")).executed_qty == 0.001


@pytest.mark.parametrize("code, kind, halts", [
    (-2019, ErrorKind.INSUFFICIENT_MARGIN, True),
    (-4164, ErrorKind.MIN_NOTIONAL, False),
    (-1021, ErrorKind.CLOCK_SKEW, True),
    (-4400, ErrorKind.TRADING_RESTRICTED, True),
    (-4061, ErrorKind.ACCOUNT_MODE, True),
    (-1007, ErrorKind.OUTCOME_UNKNOWN, False),
])
def test_fault_reject_codes(fx, code, kind, halts):
    fx.inject(Fault(FaultKind.REJECT, method="place_order", code=code))
    with pytest.raises(ExchangeError) as ei:
        fx.place_order(entry())
    assert ei.value.kind is kind and ei.value.halts is halts and ei.value.code == code
    assert fx.position().qty == 0 and fx.get_order(E1) is None
    fx.place_order(entry())                           # 1회만
    assert fx.position().qty == 0.05


def test_fault_stop_missing(fx):
    fx.place_order(entry())
    fx.inject(Fault(FaultKind.STOP_MISSING))
    info = fx.place_conditional(stop())
    assert info.status is ConditionalStatus.NEW       # 접수 응답은 정상
    assert fx.open_conditional_orders() == [] and fx.get_conditional(SL) is None
    fx.set_mark(50_000.0)
    assert fx.position().qty == 0.05                  # 발동도 없음(무방비)


def test_fault_stop_vanish(fx):
    fx.place_order(entry())
    fx.place_conditional(stop())
    fx.inject(Fault(FaultKind.STOP_VANISH, method="open_conditional_orders"))
    assert fx.open_conditional_orders() == []
    assert fx.get_conditional(SL).status is ConditionalStatus.CANCELED
    fx.set_mark(50_000.0)
    assert fx.position().qty == 0.05
    # remove=True: 조회에도 없음
    fx.set_mark(MARK)
    fx.place_conditional(stop(cid=f"sig-{SID}-x1"))
    fx.vanish_conditional(suffix="-x1", remove=True)
    assert fx.get_conditional(f"sig-{SID}-x1") is None


def test_fault_stop_field_ignored(fx):
    fx.place_order(entry())
    fx.inject(Fault(FaultKind.STOP_FIELD_IGNORED, params={"trigger_offset": -500.0}))
    resp = fx.place_conditional(stop(57_000.0))
    assert resp.trigger_price == 57_000.0             # 응답은 요청대로
    assert fx.get_conditional(SL).trigger_price == 56_500.0
    fx.set_mark(56_800.0)
    assert fx.position().qty == 0.05                  # 저장된 값 기준으로만 발동
    fx.set_mark(56_400.0)
    assert fx.position().qty == 0


def test_fault_stop_field_ignored_other_fields(fx):
    fx.place_order(entry())
    fx.inject(Fault(FaultKind.STOP_FIELD_IGNORED, params={"trigger_offset": 0.0, "working_type": "CONTRACT_PRICE",
                                                          "price_protect": True, "echo": True}))
    resp = fx.place_conditional(stop())
    assert resp.working_type is WorkingType.CONTRACT_PRICE and resp.price_protect is True


def test_fault_clock_skew(fx, oclock):
    fx.inject(Fault(FaultKind.CLOCK_SKEW, offset_ms=1_500))
    assert fx.server_time_ms() - oclock.now_ns() // NS_PER_MS == 1_500
    fx.place_order(entry())                           # 서버가 앞선 1.5초 < recvWindow → 받아 준다(검출은 게이트웨이 몫)
    fx.inject(Fault(FaultKind.CLOCK_SKEW, offset_ms=-1_500))   # 서버가 뒤짐 = timestamp가 1.5초 앞섬
    with pytest.raises(ExchangeError) as ei:
        fx.position()
    assert ei.value.kind is ErrorKind.CLOCK_SKEW
    fx.inject(Fault(FaultKind.CLOCK_SKEW, offset_ms=6_000))    # 서버가 6초 앞섬 > recvWindow
    with pytest.raises(ExchangeError) as ei:
        fx.position()
    assert ei.value.code == -1021
    fx.set_clock_skew(0)
    assert fx.position().qty == 0.05


def test_fault_rate_limit_then_ban(fx):
    fx.inject(Fault(FaultKind.RATE_LIMIT, method="position", params={"retry_after_s": 2.0, "ban_after": 2}))
    with pytest.raises(ExchangeError) as ei:
        fx.position()
    assert ei.value.kind is ErrorKind.RATE_LIMITED and ei.value.retry_after_s == 2.0 and ei.value.http_status == 429
    with pytest.raises(ExchangeError) as ei:
        fx.open_orders()                               # 창 안 재호출 1회 → 429
    assert ei.value.kind is ErrorKind.RATE_LIMITED
    with pytest.raises(ExchangeError) as ei:
        fx.open_orders()                               # 2회 → 418
    assert ei.value.kind is ErrorKind.IP_BANNED and ei.value.halts
    fx.tick(119_000)
    with pytest.raises(ExchangeError) as ei:
        fx.server_time_ms()
    assert ei.value.kind is ErrorKind.IP_BANNED
    fx.tick(1_000)
    assert fx.position().qty == 0


def test_fault_rate_limit_respected_no_ban(fx):
    fx.inject(Fault(FaultKind.RATE_LIMIT, method="position", params={"retry_after_s": 1.0}))
    with pytest.raises(ExchangeError):
        fx.position()
    fx.tick(1_000)
    assert fx.position().qty == 0


def test_read_retries_follow_retry_after(oclock):
    fx = FakeExchange(oclock, mark=MARK, read_retries=2)
    fx.inject(Fault(FaultKind.RATE_LIMIT, method="position", params={"retry_after_s": 1.0}))
    t0 = oclock.now_ns()
    assert fx.position().qty == 0
    assert oclock.now_ns() - t0 == 1_000 * NS_PER_MS
    assert len(fx.calls_for("position")) == 2
    # 주문 POST는 재시도하지 않는다
    fx.inject(Fault(FaultKind.TIMEOUT_BEFORE, method="place_order"))
    with pytest.raises(ExchangeError):
        fx.place_order(entry())
    assert fx.post_count("place_order") == 1


def test_fault_disconnect_persistent_until_reconnect(fx):
    fx.inject(Fault(FaultKind.DISCONNECT, after_calls=1))
    assert fx.position().qty == 0                      # 1회는 통과
    for call in (fx.position, fx.open_orders, fx.server_time_ms, lambda: fx.place_order(entry())):
        with pytest.raises(ExchangeError) as ei:
            call()
        assert ei.value.kind is ErrorKind.OUTCOME_UNKNOWN
    assert fx.position_qty == 0                        # 도달 안 함
    fx.reconnect()
    assert fx.get_order(E1) is None


def test_fault_disconnect_reached(fx):
    fx.inject(Fault(FaultKind.DISCONNECT, params={"reached": True}))
    with pytest.raises(ExchangeError):
        fx.place_order(entry(0.05))
    assert fx.position_qty == 0.05
    assert fx.calls[-1].reached_exchange


def test_fault_fill_delay(fx):
    fx.inject(Fault(FaultKind.FILL_DELAY, method="place_order", delay_ms=1_500))
    with pytest.raises(ExchangeError) as ei:
        fx.place_order(entry(0.05))
    assert ei.value.outcome_unknown
    assert fx.get_order(E1) is None and fx.open_orders() == []
    assert fx.position().qty == 0.05                   # 포지션은 보인다(기본)
    fx.tick(1_500)
    assert fx.get_order(E1).executed_qty == 0.05


def test_fault_fill_delay_hide_position_and_respond(fx):
    fx.inject(Fault(FaultKind.FILL_DELAY, delay_ms=1_000, params={"respond": True, "hide_position": True}))
    info = fx.place_order(entry(0.05))
    assert info.executed_qty == 0.05
    assert fx.position().qty == 0 and fx.get_order(E1) is None
    fx.tick(1_000)
    assert fx.position().qty == 0.05


def test_fault_fill_delay_conditional(fx):
    fx.place_order(entry())
    fx.inject(Fault(FaultKind.FILL_DELAY, method="place_conditional", delay_ms=800, params={"respond": True}))
    fx.place_conditional(stop())
    assert fx.open_conditional_orders() == [] and fx.get_conditional(SL) is None
    fx.tick(800)
    assert fx.get_conditional(SL).status is ConditionalStatus.NEW


@pytest.mark.parametrize("params, code", [
    ({"dual_side_position": True}, -4061),
    ({"multi_assets_margin": True}, None),
    ({"margin_type": "cross"}, None),
    ({"leverage": 5}, None),
])
def test_fault_account_mode(fx, params, code):
    fx.inject(Fault(FaultKind.ACCOUNT_MODE, params=params))
    acc = fx.account_config()
    for k, v in params.items():
        assert getattr(acc, k) == v
    if code is not None:
        with pytest.raises(ExchangeError) as ei:
            fx.place_order(entry())
        assert ei.value.code == code
    if "leverage" in params or "margin_type" in params:
        assert (fx.position().leverage, fx.position().margin_type) == (acc.leverage, acc.margin_type)


def test_fault_foreign_order_and_position(fx):
    fx.inject(Fault(FaultKind.FOREIGN_ORDER))
    assert [o.client_id for o in fx.open_orders()] == ["web_foreign1"]
    fx.inject(Fault(FaultKind.FOREIGN_ORDER, params={"conditional": True}))
    assert [c.client_algo_id for c in fx.open_conditional_orders()] == ["web_foreign_sl"]
    fx.inject(Fault(FaultKind.FOREIGN_POSITION, params={"qty": 0.02, "price": 59_000.0}))
    pos = fx.position()
    assert pos.qty == 0.02 and pos.entry_price == 59_000.0
    fx.set_mark(53_900.0)                              # 모르는 걸린 매수가 체결(무방비 체결 위험), 모르는 손절 발동
    assert fx.get_order("web_foreign1").status is OrderStatus.FILLED
    assert fx.get_conditional("web_foreign_sl").status is ConditionalStatus.FINISHED


@pytest.mark.parametrize("status, kind", [
    (451, ErrorKind.REGION_BLOCKED), (403, ErrorKind.REGION_BLOCKED), (401, ErrorKind.AUTH),
    (418, ErrorKind.IP_BANNED), (503, ErrorKind.OUTCOME_UNKNOWN),
])
def test_fault_http_status(fx, status, kind):
    fx.inject(Fault(FaultKind.HTTP_STATUS, http_status=status))
    with pytest.raises(ExchangeError) as ei:
        fx.account_config()
    assert ei.value.kind is kind and ei.value.http_status == status
    assert not fx.calls[-1].reached_exchange
    assert fx.account_config().leverage == 3


def test_fault_delayed_arrival_within_window_is_processed(fx):
    fx.inject(Fault(FaultKind.DELAYED_ARRIVAL, method="place_order", delay_ms=3_000))
    with pytest.raises(ExchangeError) as ei:
        fx.place_order(entry(0.05))
    assert ei.value.outcome_unknown
    assert fx.get_order(E1) is None and fx.pending_count() == 1
    fx.tick(3_000)
    assert fx.get_order(E1).executed_qty == 0.05
    assert fx.calls_for("place_order#late")[0].outcome == "ok"
    assert fx.post_count("place_order") == 1


def test_fault_delayed_arrival_after_recv_window_is_dropped(fx):
    fx.inject(Fault(FaultKind.DELAYED_ARRIVAL, method="place_order", delay_ms=5_001))
    with pytest.raises(ExchangeError):
        fx.place_order(entry(0.05))
    fx.tick(10_000)
    assert fx.get_order(E1) is None and fx.position().qty == 0 and fx.pending_count() == 0
    assert fx.calls_for("place_order#late")[0].outcome == "error:CLOCK_SKEW"


# ---------------------------------------------------------------------------
# 장애 대상 지정(method·client_id·times·after_calls)
# ---------------------------------------------------------------------------


def test_fault_targeting_by_client_id_suffix_and_times(fx):
    fx.place_order(entry(0.05))
    fx.inject(Fault(FaultKind.REJECT, method="place_order", code=-4400, times=2,
                    params={"client_id_suffix": "-f1"}))
    with pytest.raises(ExchangeError):
        fx.place_order(sell_ro(0.01, cid=F1))
    fx.place_order(sell_ro(0.01, cid=X1))             # 다른 ID는 영향 없음
    with pytest.raises(ExchangeError):
        fx.place_order(sell_ro(0.01, cid=F1))
    fx.place_order(sell_ro(0.01, cid=F1))             # 2회 소진
    assert fx.position().qty == 0.03


def test_fault_after_calls_and_persistent(fx):
    fx.inject(Fault(FaultKind.TIMEOUT_BEFORE, method="get_order", after_calls=2, times=-1))
    assert fx.get_order(E1) is None
    assert fx.get_order(E1) is None
    for _ in range(3):
        with pytest.raises(ExchangeError):
            fx.get_order(E1)
    fx.clear_faults()
    assert fx.get_order(E1) is None


def test_fault_method_none_applies_to_next_any_call(fx):
    fx.inject(Fault(FaultKind.TIMEOUT_BEFORE))
    with pytest.raises(ExchangeError):
        fx.server_time_ms()
    assert fx.server_time_ms() > 0


def test_inject_validation(fx):
    with pytest.raises(ValueError):
        fx.inject(Fault(FaultKind.REJECT))
    with pytest.raises(ValueError):
        fx.inject(Fault(FaultKind.HTTP_STATUS))
    with pytest.raises(ValueError):
        fx.inject(Fault(FaultKind.TIMEOUT_BEFORE, method="nope"))
    with pytest.raises(ValueError):
        fx.inject(Fault(FaultKind.TIMEOUT_BEFORE, times=0))
    assert "place_order" in ALL_METHODS


def test_calls_record_every_attempt(fx):
    fx.place_order(entry())
    fx.get_order(E1)
    fx.position()
    rec = fx.calls
    assert [c.method for c in rec] == ["place_order", "get_order", "position"]
    assert rec[0].client_id == E1 and rec[0].outcome == "ok" and rec[0].reached_exchange
    assert fx.post_count("place_order", client_id=E1) == 1
    assert fx.post_count("place_conditional") == 0
