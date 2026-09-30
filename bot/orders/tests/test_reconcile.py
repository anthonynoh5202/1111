"""대조기·재시작 복구 시험 — DESIGN §8·§9·§15.4-22 (게이트웨이 담당). 거래소는 FakeExchange."""
from __future__ import annotations

import pytest

from bot.orders import queue
from bot.orders.control import ControlState
from bot.orders.fake_exchange import FakeExchange, Fault, FaultKind
from bot.orders.reconcile import recover, reconcile_once, take_snapshot
from bot.orders.tests.conftest import MARK, make_approved_intent
from bot.orders.tests.test_gateway import (
    Crash,
    Hooked,
    cid,
    claimed,
    halt_reasons,
    intent,
    make_gw,
    now_ms,
    outbox_texts,
    signal_state,
    to_verified,
)
from bot.orders.types import IdPurpose, IntentState

S = IntentState
CTL = ControlState(manual_halt=False)


@pytest.fixture
def fx(oclock) -> FakeExchange:
    return FakeExchange(oclock, mark=MARK)


def rec(oconn, gw, fx, oclock, control=CTL):
    return reconcile_once(oconn, gw, fx, oclock, control)


# ---------------------------------------------------------------------------
# 22. 주기 대조
# ---------------------------------------------------------------------------


def test_snapshot_and_healthy_reconcile(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    snap = take_snapshot(fx, oclock, with_balance=True)
    assert snap.position.qty == pytest.approx(0.016) and len(snap.open_conditionals) == 1
    assert snap.balance is not None and snap.clock_offset_ms == 0
    r = rec(oconn, gw, fx, oclock)
    assert r.ok and r.issues == [] and r.actions == [] and r.halt_ids == []
    assert queue.get_runtime(oconn, "last_reconcile_ok")["value"] == "1"
    assert queue.get_runtime(oconn, "last_reconcile_ms") is not None
    assert intent(oconn, iid)["state"] == "STOP_VERIFIED"


def test_empty_account_reconcile_ok(oconn, ocfg, fx, oclock):
    r = rec(oconn, make_gw(oconn, ocfg, fx, oclock), fx, oclock)
    assert r.ok and halt_reasons(oconn) == []


def test_22a_stop_vanished_flatten_t0(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    assert fx.vanish_conditional(suffix="-sl", remove=True) == 1
    r = rec(oconn, gw, fx, oclock)
    assert "stop_missing" in r.issues and not r.ok
    assert intent(oconn, iid)["state"] == "FAILED_FLATTENED" and fx.position_qty == 0
    assert halt_reasons(oconn) == ["stop_missing"] and r.halt_ids
    assert signal_state(oconn, sid) == "CLOSED"


def test_22a2_stop_trigger_changed_flatten(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    fx.vanish_conditional(suffix="-sl")                    # CANCELED(조회엔 남음)
    rec(oconn, gw, fx, oclock)
    assert intent(oconn, iid)["state"] == "FAILED_FLATTENED" and fx.position_qty == 0


def test_22b_stop_fired_closed_stop(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    fx.set_mark(56_900.0)                                  # 손절 57,000 발동
    assert fx.position_qty == 0
    r = rec(oconn, gw, fx, oclock)
    assert "close:stop" in r.actions
    row = intent(oconn, iid)
    assert row["state"] == "CLOSED" and row["exit_reason"] == "stop"
    assert signal_state(oconn, sid) == "CLOSED" and halt_reasons(oconn) == []
    assert any("손절 발동" in t for t in outbox_texts(oconn))


def test_22b2_position_vanished_external(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    fx.plant_foreign_position(qty=-0.016)                  # 사람이 웹에서 청산한 것처럼
    r = rec(oconn, gw, fx, oclock)
    row = intent(oconn, iid)
    assert row["state"] == "CLOSED" and row["exit_reason"] == "external"
    assert "position_vanished" in halt_reasons(oconn) and "position_vanished" in r.issues
    assert fx.active_conditionals() == []                  # 남은 sl 취소


def test_22c_unknown_general_order_cancelled_t0(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    fx.plant_foreign_order()                               # web_foreign1 LIMIT BUY GTC
    r = rec(oconn, gw, fx, oclock)
    assert "unknown_order" in r.issues and "cancel:web_foreign1" in r.actions
    assert [o for o in fx.all_orders() if o.client_id == "web_foreign1"][0].status.value == "CANCELED"
    assert halt_reasons(oconn) == ["unknown_order"]
    assert intent(oconn, iid)["state"] == "STOP_VERIFIED"   # 보유는 유지(손절 있음)
    # 다음 대조에서 같은 T0를 반복하지 않는다
    rec(oconn, gw, fx, oclock)
    assert halt_reasons(oconn) == ["unknown_order"]


def test_22c2_unknown_reduce_only_conditional_kept_t0(oconn, ocfg, fx, oclock):
    gw = make_gw(oconn, ocfg, fx, oclock)
    fx.plant_foreign_order(conditional=True)               # SELL closePosition — 위험을 줄이는 주문
    r = rec(oconn, gw, fx, oclock)
    assert "unknown_order" in r.issues and not any(a.startswith("cancel") for a in r.actions)
    assert len(fx.active_conditionals()) == 1 and halt_reasons(oconn) == ["unknown_order"]


def test_22c3_unknown_buy_conditional_cancelled(oconn, ocfg, fx, oclock):
    gw = make_gw(oconn, ocfg, fx, oclock)
    fx.plant_foreign_order(conditional=True, side="BUY", close_position=False, qty=0.01,
                           trigger_price=66_000.0, client_id="web_buy_stop")
    r = rec(oconn, gw, fx, oclock)
    assert "cancel:web_buy_stop" in r.actions and fx.active_conditionals() == []


def test_22d_unknown_position_t0_no_flatten(oconn, ocfg, fx, oclock):
    gw = make_gw(oconn, ocfg, fx, oclock)
    fx.plant_foreign_position(qty=0.01)
    r = rec(oconn, gw, fx, oclock)
    assert "unknown_position" in r.issues and halt_reasons(oconn) == ["unknown_position"]
    assert fx.position_qty == pytest.approx(0.01) and fx.post_count("place_order") == 0   # O-11
    rec(oconn, gw, fx, oclock)
    assert halt_reasons(oconn) == ["unknown_position"]    # 사유당 1회
    # 해제 뒤에도 남아 있으면 다시 경보
    hid = queue.halts(oconn)[0]["halt_id"]
    rec(oconn, gw, fx, oclock, ControlState(manual_halt=False, released=frozenset({hid})))
    assert halt_reasons(oconn) == ["unknown_position", "unknown_position"]


def test_22e_quantity_mismatch_t0(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    fx.plant_foreign_position(qty=0.01)
    r = rec(oconn, gw, fx, oclock)
    assert "position_mismatch" in r.issues and halt_reasons(oconn) == ["position_mismatch"]
    assert intent(oconn, iid)["state"] == "STOP_VERIFIED" and fx.position_qty == pytest.approx(0.026)


def test_22f_three_snapshot_failures_t0(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    fx.inject(Fault(FaultKind.DISCONNECT))
    for i in range(2):
        r = rec(oconn, gw, fx, oclock)
        assert not r.ok and halt_reasons(oconn) == []
    r = rec(oconn, gw, fx, oclock)
    assert halt_reasons(oconn) == ["reconcile_unavailable"]
    assert queue.get_runtime(oconn, "reconcile_fail_count")["value"] == "3"
    rec(oconn, gw, fx, oclock)
    assert halt_reasons(oconn) == ["reconcile_unavailable"]          # 반복 경보 없음
    assert fx.post_count("place_order") == 1                          # 청산 시도 없음
    fx.reconnect()
    assert rec(oconn, gw, fx, oclock).ok
    assert queue.get_runtime(oconn, "reconcile_fail_count")["value"] == "0"


def test_22g_orphan_stop_cleaned_quietly(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    t = now_ms(oclock)
    queue.request_exit(oconn, sid, exit_signal_close_ms=t, exit_due_ms=t, now_ms=t)
    fx.inject(Fault(FaultKind.TIMEOUT_BEFORE, method="cancel_conditional", times=2))
    assert gw.run_trend_exit(intent(oconn, iid)) is S.CLOSED
    assert len(fx.active_conditionals()) == 1                        # 취소 실패로 남은 sl
    r = rec(oconn, gw, fx, oclock)
    assert f"cancel_orphan:{cid(sid, IdPurpose.STOP)}" in r.actions
    assert fx.active_conditionals() == [] and halt_reasons(oconn) == []


def test_22h_clock_skew_t0(oconn, ocfg, fx, oclock):
    gw = make_gw(oconn, ocfg, fx, oclock)
    fx.set_clock_skew(1500)                                # 서버가 1.5초 앞섬(서명 요청은 아직 통과)
    r = rec(oconn, gw, fx, oclock)
    assert "clock_skew" in r.issues and halt_reasons(oconn) == ["clock_skew"]
    assert queue.get_runtime(oconn, "clock_offset_ms")["value"] == "1500"
    rec(oconn, gw, fx, oclock)
    assert halt_reasons(oconn) == ["clock_skew"]           # 반복 경보 없음


def test_22h2_signed_request_rejected_by_skew(oconn, ocfg, fx, oclock):
    # 서버가 2초 뒤처짐 → 서명 조회가 -1021로 거부 → 조회 실패지만 정책상 halt → T0 clock_skew
    gw = make_gw(oconn, ocfg, fx, oclock)
    fx.set_clock_skew(-2000)
    r = rec(oconn, gw, fx, oclock)
    assert not r.ok and r.issues == ["snapshot_failed:CLOCK_SKEW"] and halt_reasons(oconn) == ["clock_skew"]


def test_halted_intent_flattened_when_stop_missing_then_closed(oconn, ocfg, fx, oclock):
    # 19번 상황(청산 실패 HALTED) → 연결 복구 뒤 대조가 손절 없음을 보고 청산
    fx.inject(Fault(FaultKind.STOP_MISSING))
    ex = Hooked(fx, after={"place_conditional": lambda res, req: fx.inject(Fault(FaultKind.DISCONNECT))})
    sid, iid, row = claimed(oconn, oclock)
    res = make_gw(oconn, ocfg, ex, oclock).process_intent(row, CTL)
    assert res.final_state is S.HALTED
    fx.reconnect()
    gw = make_gw(oconn, ocfg, fx, oclock)
    r = rec(oconn, gw, fx, oclock)
    assert "stop_missing" in r.issues
    assert intent(oconn, iid)["state"] == "FAILED_FLATTENED" and fx.position_qty == 0
    assert gw.is_halted(CTL)                                           # T0는 사람이 풀 때까지 유지


def test_halted_flat_recorded_after_release(oconn, ocfg, fx, oclock):
    ex = Hooked(fx, before={"place_order": lambda req: fx.inject(
        Fault(FaultKind.DISCONNECT, params={"reached": False}))})
    sid, iid, row = claimed(oconn, oclock)
    res = make_gw(oconn, ocfg, ex, oclock).process_intent(row, CTL)
    assert res.final_state is S.HALTED and fx.position_qty == 0
    fx.reconnect()
    gw = make_gw(oconn, ocfg, fx, oclock)
    rec(oconn, gw, fx, oclock)
    assert intent(oconn, iid)["state"] == "HALTED"                     # 해제 전: 자동 처리 없음
    hid = intent(oconn, iid)["halt_id"]
    rec(oconn, gw, fx, oclock, ControlState(manual_halt=False, released=frozenset({hid})))
    assert intent(oconn, iid)["state"] == "FAILED_FLATTENED"


def test_halted_with_valid_stop_left_alone(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    oconn.execute("UPDATE order_intents SET state = 'HALTED' WHERE intent_id = ?", (iid,))
    r = rec(oconn, gw, fx, oclock)
    assert r.ok and fx.post_count("place_order") == 1 and intent(oconn, iid)["state"] == "HALTED"


def test_exiting_continues_in_reconcile(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    t = now_ms(oclock)
    queue.request_exit(oconn, sid, exit_signal_close_ms=t, exit_due_ms=t, now_ms=t)
    fx.inject(Fault(FaultKind.TIMEOUT_BEFORE, method="place_order", times=1))
    fx.inject(Fault(FaultKind.DISCONNECT, after_calls=6))
    gw.run_trend_exit(intent(oconn, iid))
    assert intent(oconn, iid)["state"] in ("EXITING", "CLOSED")
    fx.reconnect()
    rec(oconn, gw, fx, oclock)
    assert intent(oconn, iid)["state"] == "CLOSED" and fx.position_qty == 0


# ---------------------------------------------------------------------------
# 재시작 복구(§8) — 강제 종료 지점별
# ---------------------------------------------------------------------------


def _crash_run(oconn, ocfg, ex, oclock):
    sid, iid, row = claimed(oconn, oclock)
    with pytest.raises(Crash):
        make_gw(oconn, ocfg, ex, oclock).process_intent(row, CTL)
    return sid, iid


def _boom(*a):
    raise Crash()


def test_recover_crash_before_send_record(oconn, ocfg, fx, oclock):
    sid, iid = _crash_run(oconn, ocfg, Hooked(fx, before={"balance": _boom}), oclock)
    assert intent(oconn, iid)["state"] == "SUBMITTING" and intent(oconn, iid)["entry_sent_ms"] is None
    gw = make_gw(oconn, ocfg, fx, oclock)                   # 새 프로세스
    r = recover(oconn, gw, fx, oclock, CTL)
    assert intent(oconn, iid)["state"] == "REJECTED" and intent(oconn, iid)["state_reason"] == "restart_before_send"
    assert fx.post_count("place_order") == 0 and r.halt_ids == []
    assert signal_state(oconn, sid) == "SKIPPED"
    assert any("재시작 복구" in t for t in outbox_texts(oconn))


def test_recover_crash_after_record_before_send(oconn, ocfg, fx, oclock):
    sid, iid = _crash_run(oconn, ocfg, Hooked(fx, before={"place_order": _boom}), oclock)
    assert intent(oconn, iid)["entry_sent_ms"] is not None and fx.post_count("place_order") == 0
    gw = make_gw(oconn, ocfg, fx, oclock)
    recover(oconn, gw, fx, oclock, CTL)
    assert intent(oconn, iid)["state"] == "NOT_FILLED" and fx.post_count("place_order") == 0
    assert halt_reasons(oconn) == []


def test_recover_crash_after_send_before_response(oconn, ocfg, fx, oclock):
    sid, iid = _crash_run(oconn, ocfg, Hooked(fx, after={"place_order": _boom}), oclock)
    assert fx.position_qty == pytest.approx(0.016)          # 체결됐지만 손절 없음
    oclock.advance(20_000 * 1_000_000)                      # 재시작까지 20초
    gw = make_gw(oconn, ocfg, fx, oclock)
    r = recover(oconn, gw, fx, oclock, CTL)
    row = intent(oconn, iid)
    assert row["state"] == "FAILED_FLATTENED" and fx.position_qty == 0
    assert "restart_unprotected" in halt_reasons(oconn) and "restart_unprotected" in r.issues
    assert fx.post_count("place_order", client_id=cid(sid, IdPurpose.ENTRY)) == 1   # 진입 재전송 없음
    assert fx.post_count("place_conditional") == 0          # 새 손절 대신 청산(O-6)


def test_recover_crash_after_stop_before_verify(oconn, ocfg, fx, oclock):
    sid, iid = _crash_run(oconn, ocfg, Hooked(fx, after={"place_conditional": _boom}), oclock)
    assert intent(oconn, iid)["state"] == "ENTRY_FILLED"
    oclock.advance(15_000 * 1_000_000)
    gw = make_gw(oconn, ocfg, fx, oclock)
    r = recover(oconn, gw, fx, oclock, CTL)
    row = intent(oconn, iid)
    assert row["state"] == "STOP_VERIFIED" and row["unprotected_ms"] > 5000
    assert halt_reasons(oconn) == [] and fx.post_count("place_conditional") == 1
    assert any("재시작 복구에서 손절 확인" in t for t in outbox_texts(oconn))
    assert r.ok


def test_recover_after_verified_keeps_holding(oconn, ocfg, fx, oclock):
    sid, iid, _ = to_verified(oconn, ocfg, fx, oclock)
    gw = make_gw(oconn, ocfg, fx, oclock)
    r = recover(oconn, gw, fx, oclock, CTL)
    assert r.ok and intent(oconn, iid)["state"] == "STOP_VERIFIED" and fx.post_count("place_order") == 1


def test_recover_crash_during_exiting(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    t = now_ms(oclock)
    queue.request_exit(oconn, sid, exit_signal_close_ms=t, exit_due_ms=t, now_ms=t)
    ex = Hooked(fx, after={"place_order": _boom})
    with pytest.raises(Crash):
        make_gw(oconn, ocfg, ex, oclock).run_trend_exit(intent(oconn, iid))
    assert intent(oconn, iid)["state"] == "EXITING" and fx.position_qty == 0
    gw2 = make_gw(oconn, ocfg, fx, oclock)
    recover(oconn, gw2, fx, oclock, CTL)
    row = intent(oconn, iid)
    assert row["state"] == "CLOSED" and row["exit_reason"] == "trend"
    assert fx.active_conditionals() == [] and fx.post_count("place_order") == 2


def test_recover_crash_during_exiting_before_send(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    t = now_ms(oclock)
    queue.request_exit(oconn, sid, exit_signal_close_ms=t, exit_due_ms=t, now_ms=t)
    ex = Hooked(fx, before={"place_order": _boom})
    with pytest.raises(Crash):
        make_gw(oconn, ocfg, ex, oclock).run_trend_exit(intent(oconn, iid))
    assert intent(oconn, iid)["state"] == "EXITING" and fx.position_qty > 0
    recover(oconn, make_gw(oconn, ocfg, fx, oclock), fx, oclock, CTL)
    assert intent(oconn, iid)["state"] == "CLOSED" and fx.position_qty == 0
    assert fx.post_count("place_order", client_id=cid(sid, IdPurpose.EXIT2)) == 1   # 다음 번호로


def test_recover_rejects_stale_queued(oconn, ocfg, fx, oclock):
    sid, iid = make_approved_intent(oconn)
    oclock.advance(10 * 60 * 1000 * 1_000_000)
    r = recover(oconn, make_gw(oconn, ocfg, fx, oclock), fx, oclock, CTL)
    assert intent(oconn, iid)["state"] == "REJECTED" and intent(oconn, iid)["state_reason"] == "stale_approval"
    assert any(a.startswith("reject_stale") for a in r.actions)


def test_recover_clock_skew_t0_but_continues(oconn, ocfg, fx, oclock):
    sid, iid, _ = to_verified(oconn, ocfg, fx, oclock)
    fx.set_clock_skew(3000)
    r = recover(oconn, make_gw(oconn, ocfg, fx, oclock), fx, oclock, CTL)
    assert "clock_skew" in halt_reasons(oconn) and intent(oconn, iid)["state"] == "STOP_VERIFIED"
    assert not r.ok


def test_recover_unknown_position_without_intent(oconn, ocfg, fx, oclock):
    fx.plant_foreign_position(qty=0.02)
    r = recover(oconn, make_gw(oconn, ocfg, fx, oclock), fx, oclock, CTL)
    assert "unknown_position" in r.issues and fx.position_qty == pytest.approx(0.02)


def test_position_exists_rejects_other_queued(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    sid2, iid2 = make_approved_intent(oconn, n=55)
    assert queue.claim_next(oconn, now_ms=now_ms(oclock)) is None
    assert gw.reject_queued_if_position_exists() == 1
    assert intent(oconn, iid2)["state_reason"] == "position_exists" and signal_state(oconn, sid2) == "SKIPPED"
