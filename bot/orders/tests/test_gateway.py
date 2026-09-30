"""게이트웨이 시험 — DESIGN §4·§15.4 (게이트웨이 담당). 거래소는 전부 FakeExchange(장애 주입).

시나리오 번호는 DESIGN §15.4 목록과 같다. 대조(22)·재시작 복구는 test_reconcile.py.
"""
from __future__ import annotations

from typing import Any, Callable

import pytest

from bot.orders import queue
from bot.orders.control import ControlState
from bot.orders.fake_exchange import FakeExchange, Fault, FaultKind
from bot.orders.gateway import Gateway, stop_mismatches
from bot.orders.tests.conftest import ATR, DEMO_URL, MARK, make_approved_intent, make_orders_config
from bot.orders.types import (
    ConditionalApi,
    ConditionalInfo,
    ConditionalStatus,
    ErrorKind,
    IdPurpose,
    IntentState,
    OrderType,
    OrdersConfig,
    Side,
    StopPlacement,
    WorkingType,
    make_client_id,
)

S = IntentState
CTL = ControlState(manual_halt=False)

# ---------------------------------------------------------------------------
# 도우미 (test_reconcile.py도 쓴다)
# ---------------------------------------------------------------------------
EX_METHODS = frozenset({"server_time_ms", "symbol_rules", "account_config", "balance", "mark_price", "position",
                        "open_orders", "open_conditional_orders", "place_order", "get_order", "cancel_order",
                        "place_conditional", "get_conditional", "cancel_conditional"})


class Crash(BaseException):
    """프로세스 강제 종료 흉내(게이트웨이의 어떤 except에도 잡히지 않는다)."""


class Hooked:
    """ExchangeClient 프록시: before[name](*args) / after[name](result, *args). '호출 사이' 사건을 만든다."""

    def __init__(self, inner: Any, *, before: dict[str, Callable[..., Any]] | None = None,
                 after: dict[str, Callable[..., Any]] | None = None) -> None:
        self.inner = inner
        self.before = dict(before or {})
        self.after = dict(after or {})

    @property
    def env(self):
        return self.inner.env

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self.inner, name)
        if name not in EX_METHODS:
            return attr

        def wrapped(*args: Any) -> Any:
            if name in self.before:
                self.before[name](*args)
            res = attr(*args)
            if name in self.after:
                self.after[name](res, *args)
            return res

        return wrapped


def now_ms(clock) -> int:
    return clock.now_ns() // 1_000_000


def make_gw(conn, cfg: OrdersConfig, ex, clock) -> Gateway:
    return Gateway(conn, cfg, ex, clock, base_url=DEMO_URL)


def claimed(conn, clock, **kw):
    """APPROVED 신호 + QUEUED → claim(SUBMITTING). (signal_id, intent_id, row)."""
    sid, iid = make_approved_intent(conn, **kw)
    row = queue.claim_next(conn, now_ms=now_ms(clock))
    assert row is not None and int(row["intent_id"]) == iid
    return sid, iid, row


def cid(sid: str, purpose: IdPurpose) -> str:
    return make_client_id(sid, purpose)


def intent(conn, iid: int):
    return queue.get_intent(conn, iid)


def signal_state(conn, sid: str) -> str:
    return conn.execute("SELECT state FROM signals WHERE signal_id = ?", (sid,)).fetchone()["state"]


def halt_reasons(conn) -> list[str]:
    return [r["reason"] for r in queue.halts(conn)]


def outbox_texts(conn) -> list[str]:
    return [r["text"] for r in conn.execute("SELECT text FROM outbox ORDER BY rowid")]


def run(conn, cfg, ex, clock, control: ControlState = CTL, **kw):
    sid, iid, row = claimed(conn, clock, **kw)
    gw = make_gw(conn, cfg, ex, clock)
    res = gw.process_intent(row, control)
    return sid, iid, gw, res


def to_verified(conn, cfg, fx, clock):
    sid, iid, gw, res = run(conn, cfg, fx, clock)
    assert res.final_state is S.STOP_VERIFIED, (res, halt_reasons(conn))
    return sid, iid, gw


def posts(fx: FakeExchange, method: str = "place_order", *, sid: str | None = None,
          purpose: IdPurpose | None = None) -> int:
    c = cid(sid, purpose) if sid is not None and purpose is not None else None
    return fx.post_count(method, client_id=c)


@pytest.fixture
def fx(oclock) -> FakeExchange:
    return FakeExchange(oclock, mark=MARK)


# ---------------------------------------------------------------------------
# 1. 정상
# ---------------------------------------------------------------------------


def test_01_happy_path(oconn, ocfg, fx, oclock):
    sid, iid, gw, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.STOP_VERIFIED and res.halt_ids == []
    assert res.unprotected_ms is not None and 0 <= res.unprotected_ms <= 5000
    # 주문 POST 정확히 2건(e1, sl)
    assert fx.post_count("place_order") == 1 and posts(fx, sid=sid, purpose=IdPurpose.ENTRY) == 1
    assert fx.post_count("place_conditional") == 1
    r = intent(oconn, iid)
    assert r["filled_qty"] == pytest.approx(0.016) and r["avg_fill_price"] == pytest.approx(60_000.0)
    assert r["stop_price"] == pytest.approx(57_000.0)          # 체결가 − 2×ATR20
    assert r["entry_sent_ms"] is not None and r["stop_verified_ms"] is not None
    assert signal_state(oconn, sid) == "FILLED"
    assert fx.position_qty == pytest.approx(0.016)
    act = fx.active_conditionals()
    assert len(act) == 1 and act[0].client_algo_id == cid(sid, IdPurpose.STOP) and act[0].close_position
    assert any("진입 체결" in t for t in outbox_texts(oconn))
    kinds = [e["kind"] for e in queue.events_for(oconn, iid)]
    assert "REQUEST" in kinds and "RESPONSE" in kinds and "FIREWALL" in kinds
    # 기록에 서명·키 없음
    blob = " ".join(str(e["payload_json"]) for e in queue.events_for(oconn, iid)).lower()
    assert "signature" not in blob and "apikey" not in blob


def test_process_intent_ignores_non_submitting(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    res = gw.process_intent(intent(oconn, iid), CTL)
    assert res.final_state is S.STOP_VERIFIED and fx.post_count("place_order") == 1


# ---------------------------------------------------------------------------
# 2~4. 사전 점검
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("acc,reason", [
    (dict(dual_side_position=True), "account_mode"),
    (dict(multi_assets_margin=True), "account_mode"),
    (dict(can_withdraw=True), "account_mode"),
    (dict(margin_type="cross"), "leverage_margin"),
    (dict(leverage=5), "leverage_margin"),
    (dict(leverage=2), "leverage_margin"),                     # 설정(3)과 다름
])
def test_02_account_mode_rejects_with_t0(oconn, ocfg, fx, oclock, acc, reason):
    fx.inject(Fault(FaultKind.ACCOUNT_MODE, params=acc))
    sid, iid, gw, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.REJECTED and res.reason == reason
    assert fx.post_count("place_order") == 0 and fx.post_count("place_conditional") == 0
    assert halt_reasons(oconn) == [reason] and intent(oconn, iid)["halt_id"] == res.halt_ids[0]
    assert signal_state(oconn, sid) == "SKIPPED"


def test_03_clock_skew_rejects_with_t0(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.CLOCK_SKEW, offset_ms=1500))
    sid, iid, gw, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.REJECTED and res.reason == "clock_skew"
    assert fx.post_count("place_order") == 0 and halt_reasons(oconn) == ["clock_skew"]


def test_clock_skew_within_limit_ok(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.CLOCK_SKEW, offset_ms=800))
    _, _, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.STOP_VERIFIED


def test_04_min_notional_rejects_without_t0(oconn, ocfg, fx, oclock):
    fx.set_rules(min_notional=5_000.0)
    sid, iid, gw, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.REJECTED and res.reason == "below_min_notional"
    assert fx.post_count("place_order") == 0 and halt_reasons(oconn) == []
    assert signal_state(oconn, sid) == "SKIPPED"


def test_symbol_rules_changed_t0(oconn, ocfg, fx, oclock):
    fx.set_rules(tick_size=0.5)
    _, _, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.REJECTED and halt_reasons(oconn) == ["symbol_rules"]
    assert fx.post_count("place_order") == 0


def test_unknown_position_and_order_before_entry_t0(oconn, ocfg, fx, oclock):
    fx.plant_foreign_position(qty=0.01)
    _, _, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.REJECTED and halt_reasons(oconn) == ["unknown_position"]
    assert fx.post_count("place_order") == 0


def test_unknown_open_order_before_entry_t0(oconn, ocfg, fx, oclock):
    fx.plant_foreign_order()
    _, _, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.REJECTED and halt_reasons(oconn) == ["unknown_order"]
    assert fx.post_count("place_order") == 0


def test_signal_mismatch_and_stale(oconn, ocfg, fx, oclock):
    sid, iid, row = claimed(oconn, oclock)
    oconn.execute("UPDATE signals SET atr20 = 99 WHERE signal_id = ?", (sid,))
    res = make_gw(oconn, ocfg, fx, oclock).process_intent(row, CTL)
    assert res.final_state is S.REJECTED and res.reason == "signal_mismatch" and halt_reasons(oconn) == []
    # 낡은 승인
    oclock.advance(10 * 60 * 1000 * 1_000_000)
    sid2, iid2 = make_approved_intent(oconn, n=55, approved_ms=now_ms(oclock) - 6 * 60 * 1000)
    row2 = queue.claim_next(oconn, now_ms=now_ms(oclock))
    res2 = make_gw(oconn, ocfg, fx, oclock).process_intent(row2, CTL)
    assert res2.final_state is S.REJECTED and res2.reason == "stale_approval"
    assert fx.post_count("place_order") == 0


def test_precheck_network_error_rejects_without_t0(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.TIMEOUT_BEFORE, method="account_config"))
    _, _, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.REJECTED and res.reason.startswith("precheck_account")
    assert halt_reasons(oconn) == [] and fx.post_count("place_order") == 0


def test_firewall_rejection_is_t0(oconn, fx, oclock):
    # 잔고 부족 → 방화벽(FW-BALANCE) 거부 → 주문 0건 + T0
    fx.set_balance(10.0)
    cfg = make_orders_config()
    _, iid, _, res = run(oconn, cfg, fx, oclock)
    assert res.final_state is S.REJECTED and res.reason == "firewall"
    assert halt_reasons(oconn) == ["firewall"] and fx.post_count("place_order") == 0
    fw = [e for e in queue.events_for(oconn, iid) if e["kind"] == "FIREWALL"]
    assert fw and "FW-BALANCE" in fw[-1]["payload_json"]


# ---------------------------------------------------------------------------
# 5~10. 진입 결과
# ---------------------------------------------------------------------------


def test_05_ioc_no_fill(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.NO_FILL))
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.NOT_FILLED and res.reason == "entry_not_filled"
    assert signal_state(oconn, sid) == "SKIPPED" and fx.post_count("place_conditional") == 0
    assert halt_reasons(oconn) == [] and fx.position_qty == 0


def test_06_ioc_partial_fill(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.PARTIAL_FILL, fill_ratio=0.5))
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.STOP_VERIFIED
    assert intent(oconn, iid)["filled_qty"] == pytest.approx(0.008) == fx.position_qty
    assert fx.active_conditionals()[0].close_position is True


def test_07_entry_timeout_not_delivered(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.TIMEOUT_BEFORE, method="place_order"))
    t0 = now_ms(oclock)
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.NOT_FILLED and res.reason == "entry_not_found_after_deadline"
    assert posts(fx, sid=sid, purpose=IdPurpose.ENTRY) == 1          # 재전송 없음
    r = intent(oconn, iid)
    assert now_ms(oclock) - t0 > 5000 + 2000                          # 도착 기한 + GRACE 뒤에야 확정
    assert now_ms(oclock) > r["entry_deadline_ms"] + 2000
    assert fx.position_qty == 0 and halt_reasons(oconn) == []


def test_07b_delayed_arrival_after_deadline_is_discarded(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.DELAYED_ARRIVAL, method="place_order", delay_ms=9000))
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.NOT_FILLED
    fx.tick(0)
    assert fx.position_qty == 0 and posts(fx, sid=sid, purpose=IdPurpose.ENTRY) == 1


def test_07c_delayed_arrival_within_deadline_found(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.DELAYED_ARRIVAL, method="place_order", delay_ms=1200))
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.STOP_VERIFIED and fx.position_qty == pytest.approx(0.016)
    assert posts(fx, sid=sid, purpose=IdPurpose.ENTRY) == 1


def test_08_entry_timeout_processed(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.TIMEOUT_AFTER, method="place_order"))
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.STOP_VERIFIED
    assert posts(fx, sid=sid, purpose=IdPurpose.ENTRY) == 1
    assert intent(oconn, iid)["state_reason"] == "stop_verified"
    assert intent(oconn, iid)["filled_qty"] == pytest.approx(0.016)


def test_09_duplicate_response_processed_once(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.DUPLICATE_RESPONSE, method="place_order"))
    sid, iid, gw, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.STOP_VERIFIED and len(fx.duplicates) == 1
    assert fx.position_qty == pytest.approx(0.016) and posts(fx, sid=sid, purpose=IdPurpose.ENTRY) == 1
    # 같은 응답이 다시 와도(중복) 게이트웨이는 다시 처리하지 않는다: 이미 SUBMITTING이 아니다
    again = gw.process_intent(intent(oconn, iid), CTL)
    assert again.final_state is S.STOP_VERIFIED and fx.post_count("place_order") == 1
    assert fx.post_count("place_conditional") == 1


def test_09b_duplicate_request_resend_detected_as_mismatch(oconn, ocfg, fx, oclock):
    # 같은 요청이 거래소에 두 번 도착(끝난 IOC는 다시 체결된다) → 포지션 2배 → T0(손절은 전체를 덮으므로 유지)
    fx.inject(Fault(FaultKind.DUPLICATE_RESPONSE, method="place_order", params={"mode": "resend"}))
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.STOP_VERIFIED
    assert fx.position_qty == pytest.approx(0.032)
    assert "position_mismatch" in halt_reasons(oconn)
    assert len(fx.active_conditionals()) == 1


@pytest.mark.parametrize("code,halt", [(-2019, "balance_mismatch"), (-4400, "trading_restricted"),
                                       (-4061, "account_mode"), (-1021, "clock_skew"), (-4164, None)])
def test_10_entry_confirmed_reject(oconn, ocfg, fx, oclock, code, halt):
    fx.inject(Fault(FaultKind.REJECT, method="place_order", code=code))
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.NOT_FILLED and posts(fx, sid=sid, purpose=IdPurpose.ENTRY) == 1
    assert halt_reasons(oconn) == ([halt] if halt else [])
    assert signal_state(oconn, sid) == "SKIPPED" and fx.position_qty == 0


# ---------------------------------------------------------------------------
# 11~18. 손절
# ---------------------------------------------------------------------------


def test_11_stop_timeout_processed_found_by_query(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.TIMEOUT_AFTER, method="place_conditional"))
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.STOP_VERIFIED
    assert fx.post_count("place_conditional") == 1 and len(fx.active_conditionals()) == 1
    assert halt_reasons(oconn) == []


def test_11b_stop_timeout_not_delivered_retried_same_id(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.TIMEOUT_BEFORE, method="place_conditional"))
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.STOP_VERIFIED
    assert posts(fx, "place_conditional", sid=sid, purpose=IdPurpose.STOP) == 2
    assert intent(oconn, iid)["stop_attempts"] == 2


def test_12_stop_rejected_three_times_flattens(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.REJECT, method="place_conditional", code=-1106, times=3))
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.FAILED_FLATTENED
    assert fx.post_count("place_conditional") == 3
    assert posts(fx, sid=sid, purpose=IdPurpose.FLAT1) == 1
    assert fx.position_qty == 0 and halt_reasons(oconn) == ["stop_not_verified"]
    r = intent(oconn, iid)
    assert r["exit_reason"] == "flatten" and r["closed_ms"] is not None and r["halt_id"] is not None
    assert signal_state(oconn, sid) == "CLOSED"
    flat = fx.get_order(cid(sid, IdPurpose.FLAT1))
    assert flat.reduce_only and flat.type is OrderType.MARKET and flat.side is Side.SELL


def test_13_stop_missing_flattens(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.STOP_MISSING))
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.FAILED_FLATTENED and fx.position_qty == 0
    assert halt_reasons(oconn) == ["stop_not_verified"]


def test_14_stop_trigger_field_ignored_flattens(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.STOP_FIELD_IGNORED, params={"trigger_offset": -100.0}))
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.FAILED_FLATTENED and fx.position_qty == 0
    assert halt_reasons(oconn) == ["stop_not_verified"]
    assert fx.active_conditionals() == []                        # 잘못 저장된 손절도 취소
    assert "trigger_price" in " ".join(str(e["payload_json"]) for e in queue.events_for(oconn, iid))


def test_15_algo_endpoint_required_flattens(oconn, ocfg, oclock):
    fx = FakeExchange(oclock, mark=MARK, conditional_api=ConditionalApi.LEGACY)
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.FAILED_FLATTENED and fx.position_qty == 0
    assert halt_reasons(oconn) == ["algo_endpoint"]
    assert fx.post_count("place_conditional") == 1              # 재시도·자동 전환 없음


def test_16_would_trigger_flattens_without_t0(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.REJECT, method="place_conditional", code=-2021))
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.FAILED_FLATTENED and halt_reasons(oconn) == []
    assert intent(oconn, iid)["exit_reason"] == "stop_immediate" and fx.position_qty == 0
    assert any("stop_immediate" in t for t in outbox_texts(oconn))


def test_16b_mark_below_stop_after_fill(oconn, ocfg, fx, oclock):
    # 체결 직후 급락: 손절가(57,000) 아래 → 등록하지 않고 즉시 청산
    ex = Hooked(fx, after={"place_order": lambda res, req: fx.set_mark(56_000.0)
                           if req.client_id.endswith("-e1") else None})
    sid, iid, _, res = run(oconn, ocfg, ex, oclock)
    assert res.final_state is S.FAILED_FLATTENED and halt_reasons(oconn) == []
    assert fx.post_count("place_conditional") == 0 and fx.position_qty == 0


def test_17_fill_delay_found_within_grace(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.FILL_DELAY, method="place_order", delay_ms=2500, params={"hide_position": True}))
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.STOP_VERIFIED
    assert posts(fx, sid=sid, purpose=IdPurpose.ENTRY) == 1
    assert res.unprotected_ms <= 5000


def test_18_stop_confirmation_over_deadline_flattens(oconn, ocfg, fx, oclock):
    # 손절 등록 응답이 6초 걸림(느린 거래소) → 확인 시점이 체결 뒤 5초 초과
    ex = Hooked(fx, before={"place_conditional": lambda req: oclock.advance(6_000 * 1_000_000)})
    sid, iid, _, res = run(oconn, ocfg, ex, oclock)
    assert res.final_state is S.FAILED_FLATTENED and fx.position_qty == 0
    assert halt_reasons(oconn) == ["unprotected_timeout"]
    assert fx.active_conditionals() == []


def test_18b_deadline_passed_before_stop_attempt(oconn, ocfg, fx, oclock):
    # 진입 결과 확인이 오래 걸려 이미 5초를 넘김 → 손절을 새로 걸지 않고 청산
    fx.inject(Fault(FaultKind.FILL_DELAY, method="place_order", delay_ms=5000, params={"hide_position": True}))
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.FAILED_FLATTENED and halt_reasons(oconn) == ["unprotected_timeout"]
    assert fx.post_count("place_conditional") == 0 and fx.position_qty == 0


def test_19_flatten_fails_halted_and_no_new_claim(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.STOP_MISSING))
    ex = Hooked(fx, after={"place_conditional": lambda res, req: fx.inject(Fault(FaultKind.DISCONNECT))})
    sid, iid, _, res = run(oconn, ocfg, ex, oclock)
    assert res.final_state is S.HALTED
    assert "flatten_failed" in halt_reasons(oconn)
    assert fx.position_qty == pytest.approx(0.016)              # 거래소에 남아 있다(사람)
    assert any("수동 청산" in t for t in outbox_texts(oconn))
    # 새 claim 없음(HALTED는 노출 의도)
    make_approved_intent(oconn, n=55)
    assert queue.claim_next(oconn, now_ms=now_ms(oclock)) is None
    gw = make_gw(oconn, ocfg, fx, oclock)
    assert gw.is_halted(CTL)
    assert gw.reject_queued_if_halted(CTL) == 1


def test_entry_outcome_unresolved_halts(oconn, ocfg, fx, oclock):
    # 진입 응답 유실 뒤 연결 끊김 지속 → 30초 안에 확정 못 함 → HALTED + T0
    ex = Hooked(fx, before={"place_order": lambda req: fx.inject(Fault(FaultKind.DISCONNECT, params={"reached": True}))})
    sid, iid, _, res = run(oconn, ocfg, ex, oclock)
    assert res.final_state is S.HALTED and "outcome_unresolved" in halt_reasons(oconn)
    assert fx.post_count("place_order") == 1


# ---------------------------------------------------------------------------
# 20. T0 정지·해제
# ---------------------------------------------------------------------------


def test_20_halt_rejects_queued_then_release(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.CLOCK_SKEW, offset_ms=1500))
    _, _, gw, res = run(oconn, ocfg, fx, oclock)
    hid = res.halt_ids[0]
    fx.set_clock_skew(0)
    sid2, iid2 = make_approved_intent(oconn, n=55)
    assert gw.reject_queued_if_halted(CTL) == 1
    assert intent(oconn, iid2)["state"] == "REJECTED" and intent(oconn, iid2)["state_reason"] == "halted"
    assert signal_state(oconn, sid2) == "SKIPPED" and fx.post_count("place_order") == 0
    # 수동 정지(제어 파일)도 같은 효과
    assert gw.is_halted(ControlState(manual_halt=True, released=frozenset({hid})))
    # 제어 파일에서 해제 → 다음 신호 정상
    released = ControlState(manual_halt=False, released=frozenset({hid}))
    assert not gw.is_halted(released) and gw.reject_queued_if_halted(released) == 0
    sid3, iid3 = make_approved_intent(oconn, n=100)
    row = queue.claim_next(oconn, now_ms=now_ms(oclock))
    assert gw.process_intent(row, released).final_state is S.STOP_VERIFIED


def test_20b_process_intent_refuses_when_halted(oconn, ocfg, fx, oclock):
    queue.raise_halt(oconn, reason="operator", now_ms=now_ms(oclock))
    _, _, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.REJECTED and res.reason == "halted" and fx.post_count("place_order") == 0


# ---------------------------------------------------------------------------
# 21. 레이트 리밋
# ---------------------------------------------------------------------------


def test_21_rate_limit_reads_retried(oconn, ocfg, oclock):
    fx = FakeExchange(oclock, mark=MARK, read_retries=2)
    fx.inject(Fault(FaultKind.RATE_LIMIT, method="account_config", params={"retry_after_s": 1.0}))
    _, _, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.STOP_VERIFIED and halt_reasons(oconn) == []
    assert len(fx.calls_for("account_config")) == 2


def test_21b_rate_limit_on_order_post_not_resent(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.RATE_LIMIT, method="place_order"))
    sid, iid, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.NOT_FILLED and posts(fx, sid=sid, purpose=IdPurpose.ENTRY) == 1


def test_21c_ip_ban_418_t0(oconn, ocfg, fx, oclock):
    fx.inject(Fault(FaultKind.HTTP_STATUS, method="account_config", http_status=418))
    _, _, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.REJECTED and halt_reasons(oconn) == ["exchange_block"]
    assert fx.post_count("place_order") == 0


@pytest.mark.parametrize("status,reason", [(451, "exchange_block"), (403, "exchange_block"), (401, "auth")])
def test_region_and_auth_blocks_t0(oconn, ocfg, fx, oclock, status, reason):
    fx.inject(Fault(FaultKind.HTTP_STATUS, method="position", http_status=status))
    _, _, _, res = run(oconn, ocfg, fx, oclock)
    assert res.final_state is S.REJECTED and halt_reasons(oconn) == [reason]


# ---------------------------------------------------------------------------
# 23~24. 추세 청산
# ---------------------------------------------------------------------------


def _request_exit(conn, sid, clock, due_in_ms=0):
    t = now_ms(clock)
    assert queue.request_exit(conn, sid, exit_signal_close_ms=t - 60_000, exit_due_ms=t + due_in_ms, now_ms=t)


def test_23_trend_exit(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    _request_exit(oconn, sid, oclock, due_in_ms=30 * 60 * 1000)
    assert gw.run_trend_exit(intent(oconn, iid)) is S.STOP_VERIFIED       # 기한 전: 아무것도 안 함
    assert fx.post_count("place_order") == 1
    oclock.advance(30 * 60 * 1000 * 1_000_000)
    fx.set_mark(62_000.0)
    assert gw.run_trend_exit(intent(oconn, iid)) is S.CLOSED
    r = intent(oconn, iid)
    assert r["exit_reason"] == "trend" and r["exit_price"] == pytest.approx(61_999.9) and r["exit_qty"] == 0.016
    assert fx.position_qty == 0 and fx.active_conditionals() == []         # sl 취소
    assert signal_state(oconn, sid) == "CLOSED"
    assert posts(fx, sid=sid, purpose=IdPurpose.EXIT1) == 1


def test_24_trend_exit_races_stop(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    _request_exit(oconn, sid, oclock)
    # 청산 주문 직전 손절 발동 → reduceOnly가 -2022로 거부
    ex = Hooked(fx, before={"place_order": lambda req: fx.set_mark(56_900.0)})
    gw2 = make_gw(oconn, ocfg, ex, oclock)
    assert gw2.run_trend_exit(intent(oconn, iid)) is S.CLOSED
    r = intent(oconn, iid)
    assert r["exit_reason"] == "stop"
    assert any(c.outcome == "error:REDUCE_ONLY_REJECTED" for c in fx.calls_for("place_order"))
    assert fx.position_qty == 0 and halt_reasons(oconn) == []


def test_trend_exit_response_lost_then_resolved(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    _request_exit(oconn, sid, oclock)
    fx.inject(Fault(FaultKind.TIMEOUT_AFTER, method="place_order"))
    assert gw.run_trend_exit(intent(oconn, iid)) is S.CLOSED
    assert intent(oconn, iid)["exit_reason"] == "trend" and fx.position_qty == 0
    assert fx.post_count("place_order") == 2                                # e1 + x1


def test_trend_exit_failures_keep_exiting_with_t0(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    _request_exit(oconn, sid, oclock)
    fx.inject(Fault(FaultKind.REJECT, method="place_order", code=-1106, times=3))
    assert gw.run_trend_exit(intent(oconn, iid)) is S.EXITING
    assert "flatten_failed" in halt_reasons(oconn)
    assert len(fx.active_conditionals()) == 1 and fx.position_qty > 0      # 손절은 남아 보호
    # 다시 불러도 x 번호를 넘겨 보내지 않고 T0도 한 번만
    assert gw.run_trend_exit(intent(oconn, iid)) is S.EXITING
    assert halt_reasons(oconn).count("flatten_failed") == 1
    assert fx.post_count("place_order") == 4


# ---------------------------------------------------------------------------
# K1 선배치 경로(stop_placement = pre_entry)
# ---------------------------------------------------------------------------


def test_pre_entry_stop_path(oconn, fx, oclock):
    cfg = make_orders_config(stop_placement=StopPlacement.PRE_ENTRY)
    sid, iid, _, res = run(oconn, cfg, fx, oclock)
    assert res.final_state is S.STOP_VERIFIED and res.unprotected_ms == 0
    order = [c.method for c in fx.calls if c.method in ("place_order", "place_conditional")]
    assert order == ["place_conditional", "place_order"]
    assert intent(oconn, iid)["stop_price"] == pytest.approx(57_060.0)       # 상한가 기준 계획 손절


def test_pre_entry_not_filled_cancels_stop(oconn, fx, oclock):
    cfg = make_orders_config(stop_placement=StopPlacement.PRE_ENTRY)
    fx.inject(Fault(FaultKind.NO_FILL))
    _, _, _, res = run(oconn, cfg, fx, oclock)
    assert res.final_state is S.NOT_FILLED and fx.active_conditionals() == []


def test_pre_entry_not_supported_rejects_with_t0(oconn, oclock):
    fx = FakeExchange(oclock, mark=MARK, prearm_close_position_allowed=False)
    cfg = make_orders_config(stop_placement=StopPlacement.PRE_ENTRY)
    _, _, _, res = run(oconn, cfg, fx, oclock)
    assert res.final_state is S.REJECTED and halt_reasons(oconn) == ["stop_not_verified"]
    assert fx.post_count("place_order") == 0                                 # 자동 전환(사후 손절) 없음


# ---------------------------------------------------------------------------
# 순수 함수
# ---------------------------------------------------------------------------


def _ci(**kw) -> ConditionalInfo:
    base = dict(client_algo_id="sig-AAAAAAAAAAAAAAAA-sl", algo_id="1", symbol="BTCUSDT", side=Side.SELL,
                type=OrderType.STOP_MARKET, status=ConditionalStatus.NEW, trigger_price=57_000.0,
                close_position=True, working_type=WorkingType.MARK_PRICE, price_protect=False)
    base.update(kw)
    return ConditionalInfo(**base)


@pytest.mark.parametrize("kw,bad", [
    ({}, []), ({"trigger_price": 57_000.1}, ["trigger_price"]), ({"side": Side.BUY}, ["side"]),
    ({"close_position": False}, ["close_position"]), ({"working_type": WorkingType.CONTRACT_PRICE}, ["working_type"]),
    ({"price_protect": True}, ["price_protect"]), ({"status": ConditionalStatus.CANCELED}, ["status"]),
])
def test_stop_mismatches(kw, bad):
    assert stop_mismatches(_ci(**kw), client_algo_id="sig-AAAAAAAAAAAAAAAA-sl", stop_price=57_000.0) == bad
    assert stop_mismatches(None, client_algo_id="x", stop_price=1.0) == ["missing"]
