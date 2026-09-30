"""검증 V2 — 한도 밖 주문 시도가 모두 차단되는가 (독립 검증관).

두 층으로 본다.
1) 게이트웨이 경유(실제 워커 루프 + 가짜 거래소): 한도 밖 조건을 만들고(거래소 상태·A가 위조할 수 있는 DB 값·
   계획 함수를 망가뜨려 방화벽만 남긴 경우) 워커를 돌린 뒤 **거래소에 도착한 진입/손절 POST가 0**인지,
   포지션이 0인지, 의도가 끝 상태(REJECTED 등)인지, 어느 층(사전 점검·방화벽·정지)이 막았는지 기록한다.
2) 방화벽 단독(순수 함수): 통과하는 기준 요청을 만들고 필드를 하나씩 한도 밖으로 바꿔 거부 코드를 확인
   (손절·추세 청산·비상 청산 주문 포함 — 게이트웨이가 스스로 만들 수 없는 형태).

실행: .venv/bin/python -m bot.orders.verify.firewall_limits  → results/firewall_limits.json
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable
from unittest import mock

from bot import db
from bot.orders import gateway as G
from bot.orders import queue
from bot.orders import worker as W
from bot.orders.control import ControlState
from bot.orders.fake_exchange import FakeExchange, Fault, FaultKind
from bot.orders.firewall import OrderPurpose, check_conditional, check_order
from bot.orders.ledger import Ledger
from bot.orders.plan import EntryPlan, plan_entry
from bot.orders.tests.conftest import (
    ATR,
    DEMO_URL,
    MARK,
    T_APPROVED_MS,
    TEST_MODE,
    fw_ctx,
    make_approved_intent,
    make_orders_config,
)
from bot.orders.types import (
    Balance,
    ConditionalRequest,
    HaltReason,
    IdPurpose,
    IntentState,
    OrderRequest,
    OrderType,
    Side,
    TimeInForce,
    WorkingType,
    make_client_id,
)
from bot.tests.conftest import T_MS
from bot.types import FakeClock, NS_PER_MS

OUT = Path(__file__).resolve().parent / "results" / "firewall_limits.json"
CTL = ControlState(manual_halt=False)


def _bad_plan(**over: Any) -> Callable[..., EntryPlan]:
    """정상 계획을 만든 뒤 필드를 덮어쓴다(계획 함수의 버그·조작을 흉내 — 방화벽만 남는다)."""

    def f(**kw: Any) -> EntryPlan:
        p = plan_entry(**kw)
        return replace(p, **over)

    return f


# 이름, 설명, 설정 kw, 준비 함수(fx, conn, sid, iid, tmp) , 계획 덮어쓰기
SCENARIOS: list[dict[str, Any]] = [
    dict(name="qty_over_abs_0.2BTC", what="수량 0.25 BTC(절대 상한 0.2 초과)", plan=dict(qty=0.25)),
    dict(name="notional_over_cap", what="명목 6,000 USDT(R자본×0.2=2,000 초과)", plan=dict(qty=0.1)),
    dict(name="risk_over_r", what="명목 한도 안이지만 위험 > R×0.5%(qty 0.03, 손절 3,000 아래)",
         plan=dict(qty=0.03)),
    dict(name="price_band_+1.5pct", what="상한가 = 마크 +1.5%(±1%·IOC 폭 초과)",
         plan=dict(limit_price=round(MARK * 1.015, 1), planned_stop=round(MARK * 1.015 - 3000, 1))),
    dict(name="price_below_mark", what="매수 상한가 < 마크", plan=dict(limit_price=MARK - 100.0)),
    dict(name="price_not_tick", what="가격이 틱(0.1) 배수 아님", plan=dict(limit_price=60_060.05)),
    dict(name="qty_not_step", what="수량이 0.001 배수 아님", plan=dict(qty=0.0105)),
    dict(name="qty_zero", what="수량 0", plan=dict(qty=0.0)),
    dict(name="no_stop_plan", what="계획 손절 없음(0)", plan=dict(planned_stop=0.0)),
    dict(name="stop_above_entry", what="계획 손절 ≥ 진입가", plan=dict(planned_stop=MARK * 1.01)),
    dict(name="forged_huge_atr_stop_33pct", what="A가 위조한 ATR20=10,000 → 손절 거리 33%(>25%)", atr=10_000.0),
    dict(name="forged_tiny_atr_stop_0.05pct", what="A가 위조한 ATR20=15 → 손절 거리 0.05%(<0.2%)", atr=15.0),
    dict(name="insufficient_balance", what="가용 잔고 300 USDT(필요 증거금 부족)", bal=300.0),
    dict(name="leverage_5x", what="거래소 레버리지 5배(>3·설정과 다름)", account=dict(leverage=5)),
    dict(name="cross_margin", what="교차(cross) 마진", account=dict(margin_type="cross")),
    dict(name="hedge_mode", what="Hedge 모드(dualSidePosition=true)", account=dict(dual_side_position=True)),
    dict(name="multi_assets", what="Multi-Asset 마진", account=dict(multi_assets_margin=True)),
    dict(name="withdraw_enabled_key", what="출금 권한 있는 키", account=dict(can_withdraw=True)),
    dict(name="live_host_client", what="클라이언트 주소가 실서버 fapi.binance.com", base_url="https://fapi.binance.com"),
    dict(name="forged_short_signal", what="A가 신호를 숏(side=-1)으로 위조", tamper="short"),
    dict(name="position_already_open", what="거래소에 포지션이 이미 있음(1포지션 한도)", foreign_pos=0.01),
    dict(name="foreign_open_order", what="거래소에 우리 것이 아닌 미체결 주문", foreign_order=True),
    dict(name="symbol_rules_changed", what="심볼 규칙 변경(tick 1.0)", rules=dict(tick_size=1.0)),
    dict(name="t0_active", what="풀리지 않은 킬 스위치 T0", t0=True),
    dict(name="manual_halt", what="제어 파일 수동 정지", manual=True),
    dict(name="daily_entry_cap", what="UTC 하루 진입 3회 이미 기록(B 원장)", ledger_entries=3),
    dict(name="stale_approval", what="승인 6분 전(claim_max_age 5분 초과)", approved_delta_ms=-6 * 60_000),
    dict(name="future_approval", what="미래 시각 승인(위조)", approved_delta_ms=+60_000),
    dict(name="clock_skew_2s", what="서버 시각 오차 2초", skew=2_000),
    dict(name="resend_after_unknown", what="진입 결과 모름 뒤 재시작 — 두 번째 진입 POST 시도 금지",
         special="resend"),
    dict(name="second_signal_while_holding", what="보유 중 두 번째 승인 신호", special="second"),
]


def run_scenario(sc: dict[str, Any], tmp: Path) -> dict[str, Any]:
    clock = FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)
    conn = db.connect(":memory:", mode=TEST_MODE, now_ms=T_MS)
    queue.ensure_schema(conn)
    cfg = make_orders_config()
    fx_kw: dict[str, Any] = {}
    if "base_url" in sc:
        fx_kw["base_url"] = sc["base_url"]
    if "bal" in sc:
        fx_kw["balance"] = Balance(asset="USDT", wallet_balance=sc["bal"], available_balance=sc["bal"])
    fx = FakeExchange(clock, mark=MARK, **fx_kw)
    if "rules" in sc:
        fx.set_rules(**sc["rules"])
    ledger = Ledger(tmp / f"{sc['name']}.ledger.json")
    if sc.get("ledger_entries"):
        for k in range(sc["ledger_entries"]):
            ledger.record_entry(f"prev{k:013d}", T_APPROVED_MS - 1000 * (k + 1))
    control = ControlState(manual_halt=bool(sc.get("manual")))
    w = W.Worker(conn, cfg, fx, clock, control_loader=lambda: control, ledger=ledger, sleep_ms=lambda ms: clock.advance(ms * NS_PER_MS))
    w.startup()
    if sc.get("t0"):
        w.gw._halt(HaltReason.ORDER_ERROR, intent_id=None, detail={"verify": "t0_active"})
    approved = T_APPROVED_MS + int(sc.get("approved_delta_ms", 0))
    if approved > T_APPROVED_MS:
        clock.advance(0)
    sid, iid = make_approved_intent(conn, atr20=float(sc.get("atr", ATR)), approved_ms=approved)
    if sc.get("tamper") == "short":
        try:
            conn.execute("UPDATE signals SET side = -1 WHERE signal_id = ?", (sid,))
            conn.commit()
            tamper_note = "UPDATE 성공(트리거 없음) — B의 재확인이 막아야 함"
        except Exception as exc:  # noqa: BLE001
            tamper_note = f"DB가 UPDATE 거부: {type(exc).__name__}"
    else:
        tamper_note = None
    if "account" in sc:
        fx.set_account(**sc["account"])
    if sc.get("foreign_pos"):
        fx.plant_foreign_position(qty=sc["foreign_pos"])
    if sc.get("foreign_order"):
        fx.plant_foreign_order()
    if sc.get("skew"):
        fx.inject(Fault(FaultKind.CLOCK_SKEW, offset_ms=sc["skew"]))

    e1 = make_client_id(sid, IdPurpose.ENTRY)
    pos_before = fx.position_qty
    patcher = mock.patch.object(G, "plan_entry", _bad_plan(**sc["plan"])) if "plan" in sc else None
    extra: dict[str, Any] = {}
    try:
        if patcher:
            patcher.start()
        if sc.get("special") == "resend":
            fx.inject(Fault(FaultKind.TIMEOUT_BEFORE, method="place_order", times=1))

            class Boom(BaseException):
                pass

            real_get = fx.get_order
            calls = {"n": 0}

            def crash_on_get(cid):
                calls["n"] += 1
                raise Boom()

            fx.get_order = crash_on_get          # 결과 모름 → 조회 직전 강제 종료
            try:
                w.run_once()
            except Boom:
                pass
            fx.get_order = real_get
            conn2 = conn                         # 메모리 DB — 같은 연결로 새 워커(재시작)
            clock.advance(10_000 * NS_PER_MS)
            w = W.Worker(conn2, cfg, fx, clock, control_loader=lambda: control, ledger=ledger,
                         sleep_ms=lambda ms: clock.advance(ms * NS_PER_MS))
            w.startup()
            for _ in range(5):
                w.run_once()
                clock.advance(2_000 * NS_PER_MS)
        elif sc.get("special") == "second":
            w.run_once()                         # 첫 신호 → 진입·손절
            sid2, iid2 = make_approved_intent(conn, n=55, approved_ms=clock.now_ns() // NS_PER_MS)
            for _ in range(3):
                w.run_once()
                clock.advance(2_000 * NS_PER_MS)
            e1b = make_client_id(sid2, IdPurpose.ENTRY)
            extra = dict(second_intent_state=queue.get_intent(conn, iid2)["state"],
                         second_reason=queue.get_intent(conn, iid2)["state_reason"],
                         second_e1_posts=fx.post_count("place_order", client_id=e1b))
        else:
            w.run_once()
    finally:
        if patcher:
            patcher.stop()
    row = queue.get_intent(conn, iid)
    halts = [dict(id=h["halt_id"], reason=h["reason"]) for h in queue.halts(conn)]
    fw_events = [json.loads(r["payload_json"]) for r in conn.execute(
        "SELECT payload_json FROM order_events WHERE kind = 'FIREWALL' AND client_id = ?", (e1,))]
    violations = sorted({v for e in fw_events for v in e.get("violations", [])})
    res = dict(name=sc["name"], what=sc["what"], state=row["state"], reason=row["state_reason"],
               e1_posts=fx.post_count("place_order", client_id=e1),
               e1_reached=fx.post_count("place_order", client_id=e1, reached_only=True),
               any_order_posts=len(fx.calls_for("place_order")),
               stop_posts=len(fx.calls_for("place_conditional")),
               position=fx.position_qty, halts=halts, fw_violations=violations, tamper=tamper_note, **extra)
    if sc.get("special") == "resend":
        res["blocked"] = res["e1_posts"] == 1 and res["e1_reached"] == 0 and fx.position_qty == 0
    elif sc.get("special") == "second":
        res["blocked"] = extra["second_e1_posts"] == 0 and extra["second_intent_state"] in ("REJECTED",)
    else:
        res["blocked"] = (res["e1_posts"] == 0 and res["any_order_posts"] == 0 and res["stop_posts"] == 0
                          and fx.position_qty == pos_before and row["state"] in ("REJECTED",))
        res["position_before"] = pos_before
    conn.close()
    return res


def baseline() -> dict[str, Any]:
    """대조군: 같은 준비에서 한도 안이면 진입이 실제로 나간다(시험이 헛돌지 않음)."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        clock = FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)
        conn = db.connect(":memory:", mode=TEST_MODE, now_ms=T_MS)
        queue.ensure_schema(conn)
        fx = FakeExchange(clock, mark=MARK)
        w = W.Worker(conn, make_orders_config(), fx, clock, control_loader=lambda: CTL, ledger=Ledger(Path(d) / "l.json"),
                     sleep_ms=lambda ms: clock.advance(ms * NS_PER_MS))
        w.startup()
        sid, iid = make_approved_intent(conn)
        w.run_once()
        row = queue.get_intent(conn, iid)
        return dict(state=row["state"], e1_posts=fx.post_count("place_order"), position=fx.position_qty,
                    stop_posts=len(fx.calls_for("place_conditional")), filled_qty=row["filled_qty"],
                    limit_price=row["limit_price"], planned_stop=row["planned_stop"])


# ---------------------------------------------------------------------------
# 방화벽 단독: 손절·청산 주문 형태(게이트웨이가 스스로 만들지 않는 모양)
# ---------------------------------------------------------------------------


def direct_matrix() -> list[dict[str, Any]]:
    cfg = make_orders_config()
    sid = "ABCDEFGHIJKLMNOP"
    e1, sl, x1, f1 = (make_client_id(sid, p) for p in (IdPurpose.ENTRY, IdPurpose.STOP, IdPurpose.EXIT1,
                                                        IdPurpose.FLAT1))
    good_entry = OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.LIMIT, qty=0.01, client_id=e1,
                              price=60_060.0, time_in_force=TimeInForce.IOC, reduce_only=False)
    ectx = fw_ctx(cfg, sid, planned_stop=57_060.0)
    good_sl = ConditionalRequest(symbol="BTCUSDT", side=Side.SELL, type=OrderType.STOP_MARKET, trigger_price=57_000.0,
                                 client_algo_id=sl, close_position=True, working_type=WorkingType.MARK_PRICE,
                                 price_protect=False)
    sctx = fw_ctx(cfg, sid, position_qty=0.01, planned_stop=57_000.0, position_entry_price=60_000.0)
    good_x = OrderRequest(symbol="BTCUSDT", side=Side.SELL, type=OrderType.MARKET, qty=0.01, client_id=x1,
                          reduce_only=True)
    xctx = fw_ctx(cfg, sid, position_qty=0.01)
    rows: list[dict[str, Any]] = []

    def add(name: str, kind: str, verdict) -> None:
        rows.append(dict(name=name, kind=kind, ok=verdict.ok, violations=list(verdict.violations)))

    add("BASE entry(통과해야 함)", "entry", check_order(good_entry, OrderPurpose.ENTRY, ectx))
    add("BASE stop(통과해야 함)", "stop", check_conditional(good_sl, sctx))
    add("BASE exit(통과해야 함)", "exit", check_order(good_x, OrderPurpose.EXIT, xctx))
    add("BASE flatten(통과해야 함)", "flatten", check_order(replace(good_x, client_id=f1), OrderPurpose.FLATTEN, xctx))
    E = OrderPurpose.ENTRY
    add("entry symbol ETHUSDT", "entry", check_order(replace(good_entry, symbol="ETHUSDT"), E, ectx))
    add("entry SELL(숏 진입)", "entry", check_order(replace(good_entry, side=Side.SELL), E, ectx))
    add("entry MARKET", "entry", check_order(replace(good_entry, type=OrderType.MARKET, price=None), E, ectx))
    add("entry GTC(대기 지정가)", "entry", check_order(replace(good_entry, time_in_force=TimeInForce.GTC), E, ectx))
    add("entry clientOrderId 'manual-1'", "entry", check_order(replace(good_entry, client_id="manual-1"), E, ectx))
    add("entry 다른 신호의 ID", "entry",
        check_order(replace(good_entry, client_id=make_client_id("QRSTUVWXYZ234567", IdPurpose.ENTRY)), E, ectx))
    add("entry 실서버 주소", "entry", check_order(good_entry, E, replace(ectx, client_base_url="https://fapi.binance.com")))
    add("entry http(비 TLS)", "entry", check_order(good_entry, E, replace(ectx, client_base_url=DEMO_URL.replace("https", "http"))))
    add("entry 두 번째(entry_already_sent)", "entry", check_order(good_entry, E, replace(ectx, entry_already_sent=True)))
    add("entry reduceOnly=True", "entry", check_order(replace(good_entry, reduce_only=True), E, ectx))
    add("entry NaN 수량", "entry", check_order(replace(good_entry, qty=float("nan")), E, ectx))
    add("entry 마크 모름", "entry", check_order(good_entry, E, replace(ectx, mark_price=None)))
    add("stop BUY", "stop", check_conditional(replace(good_sl, side=Side.BUY), sctx))
    add("stop closePosition=false", "stop", check_conditional(replace(good_sl, close_position=False), sctx))
    add("stop CONTRACT_PRICE", "stop", check_conditional(replace(good_sl, working_type=WorkingType.CONTRACT_PRICE), sctx))
    add("stop priceProtect=true", "stop", check_conditional(replace(good_sl, price_protect=True), sctx))
    add("stop 지정가형(LIMIT)", "stop", check_conditional(replace(good_sl, type=OrderType.LIMIT), sctx))
    add("stop 트리거 ≥ 마크", "stop", check_conditional(replace(good_sl, trigger_price=60_100.0),
                                                   replace(sctx, planned_stop=60_100.0)))
    add("stop 트리거 ≠ 계획 손절", "stop", check_conditional(replace(good_sl, trigger_price=50_000.0), sctx))
    add("stop 거리 30%", "stop", check_conditional(replace(good_sl, trigger_price=42_000.0),
                                                 replace(sctx, planned_stop=42_000.0)))
    add("stop 포지션 없음(post_fill)", "stop", check_conditional(good_sl, replace(sctx, position_qty=0.0)))
    add("stop 숏 포지션", "stop", check_conditional(good_sl, replace(sctx, position_qty=-0.01)))
    add("stop ID 용도 e1", "stop", check_conditional(replace(good_sl, client_algo_id=e1), sctx))
    X = OrderPurpose.EXIT
    add("exit reduceOnly=False", "exit", check_order(replace(good_x, reduce_only=False), X, xctx))
    add("exit BUY", "exit", check_order(replace(good_x, side=Side.BUY), X, xctx))
    add("exit 수량 > 포지션", "exit", check_order(replace(good_x, qty=0.02), X, xctx))
    add("exit 포지션 0", "exit", check_order(good_x, X, replace(xctx, position_qty=0.0)))
    add("exit LIMIT", "exit", check_order(replace(good_x, type=OrderType.LIMIT, price=60_000.0,
                                                  time_in_force=TimeInForce.GTC), X, xctx))
    add("exit ID가 f1(용도 불일치)", "exit", check_order(replace(good_x, client_id=f1), X, xctx))
    add("flatten reduceOnly=False", "flatten",
        check_order(replace(good_x, client_id=f1, reduce_only=False), OrderPurpose.FLATTEN, xctx))
    add("flatten 수량 > 포지션", "flatten",
        check_order(replace(good_x, client_id=f1, qty=0.5), OrderPurpose.FLATTEN, xctx))
    return rows


def main() -> int:
    import tempfile

    base = baseline()
    with tempfile.TemporaryDirectory() as d:
        results = [run_scenario(sc, Path(d)) for sc in SCENARIOS]
    direct = direct_matrix()
    direct_bad = [r for r in direct if (r["name"].startswith("BASE") and not r["ok"])
                  or (not r["name"].startswith("BASE") and r["ok"])]
    out = dict(baseline=base, gateway=results, direct=direct,
               gateway_blocked=sum(r["blocked"] for r in results), gateway_total=len(results),
               direct_wrong=direct_bad)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"baseline: {base}")
    for r in results:
        print(f"{'BLOCK' if r['blocked'] else '!!PASS!!'}  {r['name']:32s} state={r['state']:9s} "
              f"reason={r['reason']} e1={r['e1_posts']} orders={r['any_order_posts']} stops={r['stop_posts']} "
              f"pos={r['position']} fw={r['fw_violations']} halts={[h['reason'] for h in r['halts']]}"
              + (f" extra={ {k: r[k] for k in r if k.startswith('second')} }" if 'second_e1_posts' in r else "")
              + (f" tamper={r['tamper']}" if r['tamper'] else ""))
    print(f"gateway: {out['gateway_blocked']}/{out['gateway_total']} blocked")
    for r in direct:
        print(f"  direct {'OK  ' if r['ok'] else 'DENY'} {r['name']:30s} {r['violations']}")
    print(f"direct wrong verdicts: {direct_bad}")
    return 0 if out["gateway_blocked"] == out["gateway_total"] and not direct_bad \
        and base["state"] == "STOP_VERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main())
