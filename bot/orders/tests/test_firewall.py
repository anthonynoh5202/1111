"""주문 방화벽 시험 (DESIGN §5, §15.1)."""
from __future__ import annotations

import dataclasses

import pytest

from bot.orders.firewall import (
    FirewallRejected,
    OrderPurpose,
    check_conditional,
    check_order,
    enforce_conditional,
    enforce_order,
)
from bot.orders.plan import plan_entry, stop_for_fill
from bot.orders.types import (
    ConditionalInfo,
    ConditionalRequest,
    ConditionalStatus,
    IdPurpose,
    OrderInfo,
    OrderRequest,
    OrderStatus,
    OrderType,
    Side,
    StopPlacement,
    TimeInForce,
    WorkingType,
    make_client_id,
)
from bot.orders.tests.conftest import (
    ATR,
    DEMO_URL,
    MARK,
    fw_ctx,
    good_account,
    good_balance,
    good_rules,
    make_orders_config,
)
from bot.types import new_signal_id

SID = new_signal_id()


def _entry_setup(cfg=None, mark=MARK, atr=ATR):
    cfg = cfg or make_orders_config()
    plan = plan_entry(mark_price=mark, atr20=atr, cfg=cfg, rules=good_rules())
    req = OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.LIMIT, qty=plan.qty,
                       client_id=make_client_id(SID, IdPurpose.ENTRY), price=plan.limit_price,
                       time_in_force=TimeInForce.IOC)
    ctx = fw_ctx(cfg, SID, planned_stop=plan.planned_stop, mark_price=mark)
    return cfg, plan, req, ctx


def _stop_req(trigger: float, **kw):
    base = dict(symbol="BTCUSDT", side=Side.SELL, type=OrderType.STOP_MARKET, trigger_price=trigger,
                client_algo_id=make_client_id(SID, IdPurpose.STOP))
    base.update(kw)
    return ConditionalRequest(**base)


def _exit_req(qty: float, purpose=IdPurpose.EXIT1, **kw):
    base = dict(symbol="BTCUSDT", side=Side.SELL, type=OrderType.MARKET, qty=qty,
                client_id=make_client_id(SID, purpose), reduce_only=True)
    base.update(kw)
    return OrderRequest(**base)


# ---------------------------------------------------------------------------
# 진입
# ---------------------------------------------------------------------------


def test_entry_ok():
    _, plan, req, ctx = _entry_setup()
    v = enforce_order(req, OrderPurpose.ENTRY, ctx)
    assert v.ok and v.violations == ()
    assert v.detail["risk_usdt"] <= v.detail["risk_cap_usdt"] + 1e-9


@pytest.mark.parametrize("mark,atr", [(60_000.0, 1_500.0), (25_000.3, 400.0), (110_000.0, 3_000.0),
                                      (60_000.0, 150.0), (60_000.0, 7_000.0)])
def test_plan_entry_always_passes_firewall(mark, atr):
    _, plan, req, ctx = _entry_setup(mark=mark, atr=atr)
    v = check_order(req, OrderPurpose.ENTRY, ctx)
    assert v.ok, v.violations
    assert plan.qty > 0 and plan.limit_price >= mark


def _viol(req, ctx, purpose=OrderPurpose.ENTRY):
    v = check_order(req, purpose, ctx)
    assert not v.ok
    return set(v.violations)


@pytest.mark.parametrize("url", ["https://fapi.binance.com", "http://demo-fapi.binance.com",
                                 "https://testnet.binancefuture.com", "https://evil.example.com", "not a url"])
def test_entry_env_mismatch(url):
    _, _, req, ctx = _entry_setup()
    assert "FW-ENV" in _viol(req, dataclasses.replace(ctx, client_base_url=url))


def test_entry_symbol():
    _, _, req, ctx = _entry_setup()
    assert "FW-SYMBOL" in _viol(dataclasses.replace(req, symbol="ETHUSDT"), ctx)


@pytest.mark.parametrize("cid", ["x-abc", f"sig-{SID}-sl", f"sig-{new_signal_id()}-e1", f"sig-{SID}-e2",
                                 f"sig-{SID.lower()}-e1"])
def test_entry_client_id(cid):
    _, _, req, ctx = _entry_setup()
    assert "FW-CLIENT-ID" in _viol(dataclasses.replace(req, client_id=cid), ctx)


def test_entry_short_rejected():
    _, _, req, ctx = _entry_setup()
    assert "FW-SIDE" in _viol(dataclasses.replace(req, side=Side.SELL), ctx)


def test_entry_market_or_gtc_rejected():
    _, _, req, ctx = _entry_setup()
    assert "FW-TYPE" in _viol(dataclasses.replace(req, type=OrderType.MARKET), ctx)
    assert "FW-TIF" in _viol(dataclasses.replace(req, time_in_force=TimeInForce.GTC), ctx)
    assert "FW-TIF" in _viol(dataclasses.replace(req, time_in_force=TimeInForce.GTX), ctx)
    assert "FW-REDUCE-ONLY" in _viol(dataclasses.replace(req, reduce_only=True), ctx)


def test_entry_halted_and_once():
    _, _, req, ctx = _entry_setup()
    assert "FW-HALTED" in _viol(req, dataclasses.replace(ctx, halted=True))
    assert "FW-ENTRY-ONCE" in _viol(req, dataclasses.replace(ctx, entry_already_sent=True))


@pytest.mark.parametrize("acc,code", [
    (good_account(dual_side_position=True), "FW-ACCOUNT-MODE"),
    (good_account(multi_assets_margin=True), "FW-ACCOUNT-MODE"),
    (good_account(can_trade=False), "FW-ACCOUNT-MODE"),
    (good_account(can_withdraw=True), "FW-ACCOUNT-MODE"),
    (good_account(leverage=5), "FW-LEVERAGE"),
    (good_account(leverage=2), "FW-LEVERAGE"),         # 설정 기대값(3)과 다름
    (good_account(leverage=True), "FW-LEVERAGE"),
    (good_account(margin_type="cross"), "FW-MARGIN"),
    (None, "FW-ACCOUNT-MODE"),
])
def test_entry_account(acc, code):
    _, _, req, ctx = _entry_setup()
    assert code in _viol(req, dataclasses.replace(ctx, account=acc))


def test_entry_unknown_withdraw_permission_allowed():
    _, _, req, ctx = _entry_setup()
    assert check_order(req, OrderPurpose.ENTRY, dataclasses.replace(ctx, account=good_account(can_withdraw=None))).ok


@pytest.mark.parametrize("rules", [good_rules(tick_size=0.01), good_rules(step_size=0.0001),
                                   good_rules(status="BREAK"), good_rules(symbol="ETHUSDT"), None])
def test_entry_rules_changed(rules):
    _, _, req, ctx = _entry_setup()
    assert "FW-RULES" in _viol(req, dataclasses.replace(ctx, rules=rules))


def _foreign_order():
    return OrderInfo(client_id="web_123", exchange_order_id="1", symbol="BTCUSDT", side=Side.BUY,
                     type=OrderType.LIMIT, status=OrderStatus.NEW, orig_qty=0.01, executed_qty=0.0, avg_price=0.0)


def _cond(cid, trigger=50_000.0):
    return ConditionalInfo(client_algo_id=cid, algo_id="9", symbol="BTCUSDT", side=Side.SELL,
                           type=OrderType.STOP_MARKET, status=ConditionalStatus.NEW, trigger_price=trigger,
                           close_position=True, working_type=WorkingType.MARK_PRICE, price_protect=False)


def test_entry_requires_flat_and_no_orders():
    _, _, req, ctx = _entry_setup()
    assert "FW-POSITION-NOT-FLAT" in _viol(req, dataclasses.replace(ctx, position_qty=0.01))
    assert "FW-POSITION-NOT-FLAT" in _viol(req, dataclasses.replace(ctx, position_qty=-0.01))
    assert "FW-OPEN-ORDERS" in _viol(req, dataclasses.replace(ctx, open_orders=(_foreign_order(),)))
    own_sl = _cond(make_client_id(SID, IdPurpose.STOP))
    assert "FW-OPEN-ORDERS" in _viol(req, dataclasses.replace(ctx, open_conditionals=(own_sl,)))


def test_entry_pre_entry_path_allows_own_stop_only():
    cfg = make_orders_config(stop_placement=StopPlacement.PRE_ENTRY)
    _, _, req, ctx = _entry_setup(cfg)
    own_sl = _cond(make_client_id(SID, IdPurpose.STOP))
    assert check_order(req, OrderPurpose.ENTRY, dataclasses.replace(ctx, open_conditionals=(own_sl,))).ok
    other = _cond(make_client_id(new_signal_id(), IdPurpose.STOP))
    assert "FW-OPEN-ORDERS" in _viol(req, dataclasses.replace(ctx, open_conditionals=(own_sl, other)))


def test_entry_qty_rules():
    _, _, req, ctx = _entry_setup()
    assert "FW-QTY-STEP" in _viol(dataclasses.replace(req, qty=req.qty + 0.0005), ctx)
    assert "FW-QTY" in _viol(dataclasses.replace(req, qty=0.0), ctx)
    assert "FW-QTY" in _viol(dataclasses.replace(req, qty=float("nan")), ctx)
    assert "FW-QTY-MIN" in _viol(req, dataclasses.replace(ctx, rules=good_rules(min_qty=req.qty + 0.001)))
    big = make_orders_config(r_capital_usdt=1_000_000.0)
    _, _, req2, ctx2 = _entry_setup(big)
    assert "FW-QTY-ABS" in _viol(dataclasses.replace(req2, qty=0.201), ctx2)


def test_entry_price_band():
    _, plan, req, ctx = _entry_setup()
    assert "FW-PRICE-TICK" in _viol(dataclasses.replace(req, price=req.price + 0.05), ctx)
    assert "FW-PRICE-BAND" in _viol(dataclasses.replace(req, price=MARK - 10.0), ctx)          # 마크 아래
    assert "FW-PRICE-BAND" in _viol(dataclasses.replace(req, price=round(MARK * 1.002, 1)), ctx)  # 상한 10bp 초과
    assert "FW-PRICE-BAND" in _viol(dataclasses.replace(req, price=None), ctx)
    assert "FW-MARK" in _viol(req, dataclasses.replace(ctx, mark_price=None))


def test_entry_price_band_hard_cap_even_if_config_wide():
    cfg = make_orders_config(ioc_cap_bps=30)
    _, _, req, ctx = _entry_setup(cfg)
    assert check_order(req, OrderPurpose.ENTRY, ctx).ok
    assert "FW-PRICE-BAND" in _viol(dataclasses.replace(req, price=round(MARK * 1.005, 1)), ctx)


def test_entry_notional_caps():
    cfg, plan, req, ctx = _entry_setup()
    # R자본 10,000 × 0.2 = 2,000 USDT 상한
    assert "FW-NOTIONAL" in _viol(dataclasses.replace(req, qty=0.04), dataclasses.replace(ctx, planned_stop=MARK - 30_000))
    assert "FW-NOTIONAL-MIN" in _viol(req, dataclasses.replace(ctx, rules=good_rules(min_notional=1e9)))
    small = make_orders_config(max_notional_usdt=500.0)
    _, _, req3, ctx3 = _entry_setup(small)
    assert check_order(req3, OrderPurpose.ENTRY, ctx3).ok
    assert "FW-NOTIONAL" in _viol(dataclasses.replace(req3, qty=req3.qty + 0.01), ctx3)


def test_entry_stop_plan_and_distance():
    _, plan, req, ctx = _entry_setup()
    assert "FW-STOP-PLAN" in _viol(req, dataclasses.replace(ctx, planned_stop=None))
    assert "FW-STOP-PLAN" in _viol(req, dataclasses.replace(ctx, planned_stop=req.price + 1))
    assert "FW-STOP-DIST" in _viol(req, dataclasses.replace(ctx, planned_stop=req.price - 10.0))       # 0.017%
    assert "FW-STOP-DIST" in _viol(req, dataclasses.replace(ctx, planned_stop=req.price * 0.7))        # 30%


def test_entry_risk_cap():
    _, plan, req, ctx = _entry_setup()
    # 수량을 계획보다 키우면(명목 상한 안에서) 위험 상한을 넘는다: 손절 거리 5%, 위험 상한 50 USDT
    cfg = make_orders_config(max_notional_usdt=10_000.0, r_capital_usdt=10_000.0)
    ctx2 = dataclasses.replace(ctx, cfg=cfg, planned_stop=round(req.price * 0.95, 1))
    assert "FW-RISK" in _viol(dataclasses.replace(req, qty=0.033), ctx2)


def test_entry_balance():
    _, _, req, ctx = _entry_setup()
    assert "FW-BALANCE" in _viol(req, dataclasses.replace(ctx, balance=None))
    assert "FW-BALANCE" in _viol(req, dataclasses.replace(ctx, balance=good_balance(1.0)))
    assert "FW-BALANCE" in _viol(req, dataclasses.replace(ctx, balance=good_balance(float("nan"))))


def test_enforce_raises_and_reports():
    _, _, req, ctx = _entry_setup()
    with pytest.raises(FirewallRejected) as ei:
        enforce_order(dataclasses.replace(req, side=Side.SELL, symbol="X"), OrderPurpose.ENTRY, ctx)
    js = ei.value.verdict.as_json()
    assert js["ok"] is False and {"FW-SIDE", "FW-SYMBOL"} <= set(js["violations"])


def test_check_order_rejects_stop_purpose():
    _, _, req, ctx = _entry_setup()
    with pytest.raises(ValueError):
        check_order(req, OrderPurpose.STOP, ctx)


# ---------------------------------------------------------------------------
# 손절
# ---------------------------------------------------------------------------


def _stop_ctx(fill=60_050.0, qty=0.013, **kw):
    cfg = make_orders_config()
    stop = stop_for_fill(fill, ATR)
    base = dict(position_qty=qty, planned_stop=stop, position_entry_price=fill, mark_price=MARK)
    base.update(kw)
    return stop, fw_ctx(cfg, SID, **base)


def test_stop_ok_even_when_halted_or_account_bad():
    stop, ctx = _stop_ctx()
    assert enforce_conditional(_stop_req(stop), ctx).ok
    ctx2 = dataclasses.replace(ctx, halted=True, account=good_account(leverage=5, dual_side_position=True),
                               balance=None, rules=None)
    assert check_conditional(_stop_req(stop), ctx2).ok


@pytest.mark.parametrize("kw,code", [
    (dict(side=Side.BUY), "FW-SIDE"),
    (dict(type=OrderType.MARKET), "FW-TYPE"),
    (dict(close_position=False), "FW-CLOSE-POSITION"),
    (dict(working_type=WorkingType.CONTRACT_PRICE), "FW-WORKING-TYPE"),
    (dict(price_protect=True), "FW-PRICE-PROTECT"),
    (dict(symbol="ETHUSDT"), "FW-SYMBOL"),
    (dict(client_algo_id=f"sig-{SID}-e1"), "FW-CLIENT-ID"),
])
def test_stop_shape(kw, code):
    stop, ctx = _stop_ctx()
    v = check_conditional(_stop_req(stop, **kw), ctx)
    assert not v.ok and code in v.violations


def test_stop_trigger_rules():
    stop, ctx = _stop_ctx()
    assert "FW-TRIGGER" in check_conditional(_stop_req(stop - 0.1), ctx).violations        # 계획과 다름
    assert "FW-TRIGGER-TICK" in check_conditional(_stop_req(stop + 0.05),
                                                  dataclasses.replace(ctx, planned_stop=stop + 0.05)).violations
    v = check_conditional(_stop_req(stop), dataclasses.replace(ctx, mark_price=stop - 1))      # 이미 마크 아래
    assert "FW-TRIGGER-MARK" in v.violations
    far = round(60_050.0 * 0.7, 1)
    assert "FW-STOP-DIST" in check_conditional(_stop_req(far), dataclasses.replace(ctx, planned_stop=far)).violations
    assert "FW-STOP-DIST" in check_conditional(_stop_req(stop),
                                               dataclasses.replace(ctx, position_entry_price=None)).violations
    assert "FW-TRIGGER" in check_conditional(_stop_req(float("inf")), ctx).violations


def test_stop_requires_long_position_unless_pre_entry():
    stop, ctx = _stop_ctx(qty=0.0)
    assert "FW-POSITION" in check_conditional(_stop_req(stop), ctx).violations
    assert "FW-POSITION" in check_conditional(_stop_req(stop), dataclasses.replace(ctx, position_qty=-0.01)).violations
    # 선배치 경로: 설정이 pre_entry이고 포지션 0일 때만
    assert "FW-POSITION" in check_conditional(_stop_req(stop), dataclasses.replace(ctx, pre_entry_stop=True)).violations
    cfg = make_orders_config(stop_placement=StopPlacement.PRE_ENTRY)
    ok_ctx = dataclasses.replace(ctx, cfg=cfg, pre_entry_stop=True)
    assert check_conditional(_stop_req(stop), ok_ctx).ok
    assert "FW-POSITION" in check_conditional(_stop_req(stop), dataclasses.replace(ok_ctx, position_qty=0.01)).violations


def test_stop_env_live_rejected():
    stop, ctx = _stop_ctx()
    v = check_conditional(_stop_req(stop), dataclasses.replace(ctx, client_base_url="https://fapi.binance.com"))
    assert "FW-ENV" in v.violations
    with pytest.raises(FirewallRejected):
        enforce_conditional(_stop_req(stop), dataclasses.replace(ctx, client_base_url="https://fapi.binance.com"))


# ---------------------------------------------------------------------------
# 청산
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("purpose,idp", [(OrderPurpose.EXIT, IdPurpose.EXIT1), (OrderPurpose.EXIT, IdPurpose.EXIT3),
                                         (OrderPurpose.FLATTEN, IdPurpose.FLAT1), (OrderPurpose.FLATTEN, IdPurpose.FLAT3)])
def test_exit_ok_even_when_halted(purpose, idp):
    cfg = make_orders_config()
    ctx = fw_ctx(cfg, SID, position_qty=0.013, halted=True, account=good_account(dual_side_position=True),
                 balance=None, rules=None, mark_price=None)
    assert enforce_order(_exit_req(0.013, idp), purpose, ctx).ok


def test_exit_violations():
    cfg = make_orders_config()
    ctx = fw_ctx(cfg, SID, position_qty=0.013)
    assert "FW-SIDE" in _viol(_exit_req(0.013, side=Side.BUY), ctx, OrderPurpose.EXIT)
    assert "FW-REDUCE-ONLY" in _viol(_exit_req(0.013, reduce_only=False), ctx, OrderPurpose.EXIT)
    assert "FW-TYPE" in _viol(_exit_req(0.013, type=OrderType.LIMIT, price=60_000.0,
                                        time_in_force=TimeInForce.IOC), ctx, OrderPurpose.EXIT)
    assert "FW-QTY-OVER-POSITION" in _viol(_exit_req(0.014), ctx, OrderPurpose.EXIT)
    assert "FW-QTY-STEP" in _viol(_exit_req(0.0125), ctx, OrderPurpose.EXIT)
    assert "FW-POSITION" in _viol(_exit_req(0.013), dataclasses.replace(ctx, position_qty=0.0), OrderPurpose.EXIT)
    assert "FW-POSITION" in _viol(_exit_req(0.013), dataclasses.replace(ctx, position_qty=-0.013), OrderPurpose.FLATTEN)
    # 용도와 ID가 맞아야 한다
    assert "FW-CLIENT-ID" in _viol(_exit_req(0.013, IdPurpose.FLAT1), ctx, OrderPurpose.EXIT)
    assert "FW-CLIENT-ID" in _viol(_exit_req(0.013, IdPurpose.EXIT1), ctx, OrderPurpose.FLATTEN)
    assert "FW-ENV" in _viol(_exit_req(0.013), dataclasses.replace(ctx, client_base_url="https://fapi.binance.com"),
                             OrderPurpose.FLATTEN)


def test_testnet_env_config_matches_host():
    from bot.orders.types import ExchangeEnv
    cfg = make_orders_config(env=ExchangeEnv.TESTNET)
    ctx = fw_ctx(cfg, SID, position_qty=0.01, client_base_url="https://testnet.binancefuture.com")
    assert check_order(_exit_req(0.01), OrderPurpose.EXIT, ctx).ok
    assert "FW-ENV" in _viol(_exit_req(0.01), dataclasses.replace(ctx, client_base_url=DEMO_URL), OrderPurpose.EXIT)
