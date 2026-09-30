"""의도 상태 머신·ID·오류 분류·설정·계획·제어 파일·큐 시험 (DESIGN §2, §3, §6, §7, §15.1)."""
from __future__ import annotations

import sqlite3
import threading

import pytest

from bot import db
from bot.orders import queue
from bot.orders.control import load_control, parse_control
from bot.orders.plan import PlanRejected, plan_entry, stop_for_fill
from bot.orders.tests.conftest import (
    ATR,
    MARK,
    T_APPROVED_MS,
    TEST_MODE,
    good_rules,
    make_approved_intent,
    make_orders_config,
    write_control,
)
from bot.orders.types import (
    ERROR_POLICY,
    INTENT_LIVE,
    INTENT_TERMINAL,
    INTENT_TRANSITIONS,
    ConditionalApi,
    ErrorKind,
    ExchangeEnv,
    ExchangeError,
    HaltReason,
    IdPurpose,
    IntentExitReason,
    IntentState,
    OrdersConfig,
    OrdersConfigError,
    StopPlacement,
    can_intent_transition,
    ceil_to_step,
    classify_error,
    env_base_url,
    floor_to_step,
    format_decimal,
    is_multiple,
    make_client_id,
    parse_client_id,
)
from bot.types import ExitReason, SignalState, new_signal_id

I = IntentState


# ---------------------------------------------------------------------------
# 상태 머신
# ---------------------------------------------------------------------------


def test_transition_table_shape():
    assert set(INTENT_TRANSITIONS) == set(IntentState)
    for s in INTENT_TERMINAL:
        assert INTENT_TRANSITIONS[s] == frozenset()
    # 갇힘 없음: 비종료 상태는 전부 종료 상태로 가는 길이 있다
    for s in IntentState:
        if s in INTENT_TERMINAL:
            continue
        seen, todo = set(), [s]
        while todo:
            x = todo.pop()
            if x in seen:
                continue
            seen.add(x)
            todo.extend(INTENT_TRANSITIONS[x])
        assert seen & INTENT_TERMINAL, s
    # 진입 전 거부(REJECTED)는 QUEUED·SUBMITTING에서만, STOP_VERIFIED로 가는 길은 손절 단계에서만
    assert {s for s in IntentState if I.REJECTED in INTENT_TRANSITIONS[s]} == {I.QUEUED, I.SUBMITTING}
    assert {s for s in IntentState if I.STOP_VERIFIED in INTENT_TRANSITIONS[s]} == {I.ENTRY_FILLED, I.STOP_PLACED}
    assert {s for s in IntentState if I.SUBMITTING in INTENT_TRANSITIONS[s]} == {I.QUEUED}
    assert I.QUEUED not in INTENT_LIVE and I.HALTED in INTENT_LIVE
    assert INTENT_LIVE.isdisjoint(INTENT_TERMINAL)
    assert not can_intent_transition(I.CLOSED, I.QUEUED)
    assert IntentExitReason.STOP.value == ExitReason.STOP.value and IntentExitReason.TREND.value == ExitReason.TREND.value


# ---------------------------------------------------------------------------
# clientOrderId
# ---------------------------------------------------------------------------


def test_client_id_roundtrip():
    sid = new_signal_id()
    for p in IdPurpose:
        cid = make_client_id(sid, p)
        assert cid.startswith("sig-") and len(cid) == 23
        parsed = parse_client_id(cid)
        assert parsed is not None and parsed.signal_id == sid and parsed.purpose is p


@pytest.mark.parametrize("cid", [None, 1, "", "sig-", "web_abc", "sig-ABC-e1", "sig-AAAAAAAAAAAAAAAA-e1\n",
                                 "sig-AAAAAAAAAAAAAAAA-x4", "sig-AAAAAAAAAAAAAAAA-tp", "SIG-AAAAAAAAAAAAAAAA-e1",
                                 "x-sig-AAAAAAAAAAAAAAAA-e1", "sig-AAAAAAAAAAAAAAA1-e1"])
def test_client_id_parse_rejects(cid):
    assert parse_client_id(cid) is None


def test_make_client_id_rejects_bad_signal():
    with pytest.raises(ValueError):
        make_client_id("abc", IdPurpose.ENTRY)
    with pytest.raises(ValueError):
        make_client_id(new_signal_id(), "zz")


# ---------------------------------------------------------------------------
# 오류 분류
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status,code,kind", [
    (None, None, ErrorKind.OUTCOME_UNKNOWN),
    (400, -1021, ErrorKind.CLOCK_SKEW),
    (400, -2019, ErrorKind.INSUFFICIENT_MARGIN),
    (400, -4120, ErrorKind.ALGO_ENDPOINT_REQUIRED),
    (400, -4164, ErrorKind.MIN_NOTIONAL),
    (400, -2021, ErrorKind.WOULD_TRIGGER),
    (400, -2022, ErrorKind.REDUCE_ONLY_REJECTED),
    (400, -2013, ErrorKind.ORDER_NOT_FOUND),
    (400, -4116, ErrorKind.DUPLICATE_CLIENT_ID),
    (400, -4061, ErrorKind.ACCOUNT_MODE),
    (400, -4400, ErrorKind.TRADING_RESTRICTED),
    (418, -1003, ErrorKind.IP_BANNED),
    (429, -1003, ErrorKind.RATE_LIMITED),
    (451, None, ErrorKind.REGION_BLOCKED),
    (403, None, ErrorKind.REGION_BLOCKED),
    (401, -2015, ErrorKind.AUTH),
    (400, -2015, ErrorKind.AUTH),
    (400, -1022, ErrorKind.AUTH),
    (503, None, ErrorKind.OUTCOME_UNKNOWN),
    (500, -1007, ErrorKind.OUTCOME_UNKNOWN),
    (400, -1007, ErrorKind.OUTCOME_UNKNOWN),
    (400, -1102, ErrorKind.BAD_REQUEST),
    (302, None, ErrorKind.UNKNOWN),
])
def test_classify_error(status, code, kind):
    assert classify_error(status, code) is kind


def test_error_policy_complete_and_safe():
    assert set(ERROR_POLICY) == set(ErrorKind)
    # 결과 모름·표 밖 오류는 반드시 조회로 판단
    assert ERROR_POLICY[ErrorKind.OUTCOME_UNKNOWN].outcome_unknown
    assert ERROR_POLICY[ErrorKind.UNKNOWN].outcome_unknown and ERROR_POLICY[ErrorKind.UNKNOWN].halt
    for k in (ErrorKind.CLOCK_SKEW, ErrorKind.ALGO_ENDPOINT_REQUIRED, ErrorKind.IP_BANNED, ErrorKind.REGION_BLOCKED,
              ErrorKind.AUTH, ErrorKind.ACCOUNT_MODE, ErrorKind.TRADING_RESTRICTED):
        assert ERROR_POLICY[k].halt, k
    e = ExchangeError(ErrorKind.RATE_LIMITED, http_status=429, code=-1003, msg="x" * 500, retry_after_s=3)
    assert len(e.msg) == 200 and e.policy.retry_read and not e.halts and not e.outcome_unknown


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------


def test_orders_config_defaults_conservative():
    cfg = OrdersConfig()
    assert cfg.env is ExchangeEnv.DEMO and cfg.base_url == "https://demo-fapi.binance.com"
    assert cfg.conditional_api is ConditionalApi.ALGO and cfg.stop_placement is StopPlacement.POST_FILL
    assert cfg.recv_window_ms == 5000 and cfg.stop_deadline_ms == 5000 and cfg.expected_leverage == 3
    assert env_base_url("testnet") == "https://testnet.binancefuture.com"


def test_orders_config_from_mapping_ok():
    cfg = OrdersConfig.from_mapping({"env": "testnet", "conditional_api": "legacy", "stop_placement": "pre_entry",
                                     "r_capital_usdt": 2000, "risk_fraction": 0.0025, "ioc_cap_bps": 5,
                                     "expected_leverage": 2})
    assert cfg.env is ExchangeEnv.TESTNET and cfg.risk_fraction == 0.0025 and cfg.expected_leverage == 2


@pytest.mark.parametrize("raw", [
    {"base_url": "https://fapi.binance.com"}, {"host": "x"}, {"api_key": "abc"}, {"env": "live"}, {"env": "prod"},
    {"risk_fraction": 0.006}, {"risk_fraction": 0.0}, {"risk_fraction": True}, {"max_notional_usdt": 10_001.0},
    {"expected_leverage": 4}, {"expected_leverage": 0}, {"expected_leverage": 3.0}, {"ioc_cap_bps": 31},
    {"reconcile_interval_s": 31}, {"stop_deadline_ms": 5001}, {"claim_max_age_ms": 300_001},
    {"max_clock_skew_ms": 1001}, {"recv_window_ms": 6000}, {"recv_window_ms": 4000},
    {"api_key_file": "relative/path"}, {"control_file": 5}, {"r_capital_usdt": float("inf")},
    {"conditional_api": "v2"}, {"stop_placement": "maybe"}, {"loop_interval_s": 60}, {"http_timeout_s": 120},
])
def test_orders_config_rejects(raw):
    with pytest.raises(OrdersConfigError):
        OrdersConfig.from_mapping(raw)


def test_orders_config_rejects_non_mapping():
    with pytest.raises(OrdersConfigError):
        OrdersConfig.from_mapping([("env", "demo")])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 숫자·계획
# ---------------------------------------------------------------------------


def test_step_helpers():
    assert floor_to_step(0.0139999, 0.001) == 0.013
    assert floor_to_step(0.3, 0.1) == 0.3
    assert ceil_to_step(60_060.01, 0.1) == 60_060.1
    assert ceil_to_step(60_060.0, 0.1) == 60_060.0
    assert is_multiple(62_345.3, 0.1) and not is_multiple(62_345.35, 0.1)
    assert format_decimal(0.001) == "0.001" and format_decimal(65_000.0) == "65000" and format_decimal(1e-7) == "0.0000001"
    with pytest.raises(ValueError):
        format_decimal(float("nan"))


def test_plan_entry_values():
    from backtest.trend import NOTIONAL_CAP_PER_SYSTEM, RISK_R
    from bot.strategy import protective_stop, risk_per_unit

    cfg = make_orders_config()          # R 자본 10,000
    p = plan_entry(mark_price=MARK, atr20=ATR, cfg=cfg, rules=good_rules())
    assert p.limit_price == ceil_to_step(MARK * 1.001, 0.1) == 60_060.0
    assert p.planned_stop == protective_stop(p.limit_price, ATR) == 57_060.0
    assert p.risk_per_unit == pytest.approx(risk_per_unit(p.limit_price, p.planned_stop))
    raw = min(10_000 * RISK_R / p.risk_per_unit, 10_000 * NOTIONAL_CAP_PER_SYSTEM / p.limit_price)
    assert p.qty == floor_to_step(raw, 0.001) and p.qty <= raw
    assert p.risk_usdt <= 10_000 * RISK_R and p.notional <= 2_000.0
    assert stop_for_fill(60_010.0, ATR) == protective_stop(60_010.0, ATR) == 57_010.0


def test_plan_entry_caps_and_rejections():
    big = make_orders_config(r_capital_usdt=10_000_000.0)
    p = plan_entry(mark_price=MARK, atr20=ATR, cfg=big, rules=good_rules())
    assert p.qty <= 0.2 and p.notional <= 10_000.0 + 1e-6
    tiny = make_orders_config(r_capital_usdt=10.0)
    with pytest.raises(PlanRejected) as ei:
        plan_entry(mark_price=MARK, atr20=ATR, cfg=tiny, rules=good_rules())
    assert ei.value.reason == "below_min_qty"
    with pytest.raises(PlanRejected) as ei:
        plan_entry(mark_price=MARK, atr20=ATR, cfg=make_orders_config(), rules=good_rules(min_notional=5_000.0))
    assert ei.value.reason == "below_min_notional"
    for bad in (dict(mark_price=0.0, atr20=ATR), dict(mark_price=MARK, atr20=float("nan")),
                dict(mark_price=MARK, atr20=-1.0)):
        with pytest.raises(PlanRejected):
            plan_entry(cfg=make_orders_config(), rules=good_rules(), **bad)
    with pytest.raises(PlanRejected):     # 손절이 0 이하(ATR이 가격보다 큼)
        plan_entry(mark_price=MARK, atr20=40_000.0, cfg=make_orders_config(), rules=good_rules())
    with pytest.raises(ValueError):
        stop_for_fill(0.0, ATR)


# ---------------------------------------------------------------------------
# 제어 파일
# ---------------------------------------------------------------------------


def test_control_parse_ok():
    c = parse_control('halt = false\n[[release]]\nhalt_id = 3\nat = "2026-10-01T00:00:00Z"\nreason = "확인"\n'
                      '[[release]]\nhalt_id = 7\nreason = "ok"\n')
    assert c.manual_halt is False and c.released == frozenset({3, 7}) and c.error is None
    assert parse_control("").manual_halt is False
    assert parse_control("halt = true").manual_halt is True


@pytest.mark.parametrize("text", ["halt = 1", "halt = \"no\"", "resume = true", "[[release]]\nhalt_id = 0\nreason='x'",
                                  "[[release]]\nhalt_id = true\nreason='x'", "[[release]]\nhalt_id = 3",
                                  "[[release]]\nhalt_id = 3\nreason = '  '", "release = 3",
                                  "[[release]]\nhalt_id = 3\nreason='x'\nextra = 1", "this is = not toml ["])
def test_control_parse_errors_mean_halt(text):
    c = parse_control(text)
    assert c.manual_halt is True and c.error and c.released == frozenset()


def test_control_file_permissions(tmp_path):
    assert load_control(tmp_path / "missing.toml").manual_halt is True
    p = write_control(tmp_path / "c.toml", "halt = false\n", 0o600)
    c = load_control(p)
    assert c.manual_halt is False and c.error is None and str(p) in c.ref
    assert load_control(write_control(tmp_path / "r.toml", "halt = false\n", 0o644)).manual_halt is False
    for mode in (0o620, 0o602, 0o666):
        c = load_control(write_control(tmp_path / f"w{mode:o}.toml", "halt = false\n", mode))
        assert c.manual_halt is True and c.error == "writable_by_others"
    assert load_control(tmp_path).manual_halt is True                    # 디렉터리
    big = write_control(tmp_path / "big.toml", "#" * (65 * 1024))
    assert load_control(big).error == "too_large"


# ---------------------------------------------------------------------------
# 큐
# ---------------------------------------------------------------------------


def _sig_state(conn, sid):
    return db.get_signal(conn, sid)["state"]


def test_enqueue_requires_approved_and_is_idempotent(oconn):
    from bot.tests.conftest import insert_test_signal
    sid = insert_test_signal(oconn, mode=TEST_MODE)
    with pytest.raises(ValueError):
        queue.enqueue(oconn, signal_id=sid, now_ms=T_APPROVED_MS)              # NEW
    with pytest.raises(ValueError):
        queue.enqueue(oconn, signal_id="A" * 16, now_ms=T_APPROVED_MS)        # 없음
    sid2, iid = make_approved_intent(oconn, n=55)
    assert queue.enqueue(oconn, signal_id=sid2, now_ms=T_APPROVED_MS) is None
    row = queue.get_intent(oconn, iid)
    assert row["state"] == "QUEUED" and row["atr20"] == ATR and row["approved_ms"] == T_APPROVED_MS
    assert row["symbol"] == "BTCUSDT" and row["side"] == 1 and row["subsystem_n"] == 55


def test_enqueue_rolls_back_with_confirm(oconn):
    """A가 [확인] 전이와 같은 트랜잭션에서 enqueue — 예외면 둘 다 롤백."""
    from bot.orders.tests.conftest import approve_signal
    from bot.tests.conftest import insert_test_signal
    sid = insert_test_signal(oconn, mode=TEST_MODE)
    with pytest.raises(RuntimeError):
        with db.transaction(oconn):
            approve_signal(oconn, sid)
            queue.enqueue(oconn, signal_id=sid, now_ms=T_APPROVED_MS)
            raise RuntimeError("boom")
    assert _sig_state(oconn, sid) == "NEW" and queue.intent_for_signal(oconn, sid) is None


def test_claim_one_live_at_a_time(oconn):
    s1, i1 = make_approved_intent(oconn, n=20)
    s2, i2 = make_approved_intent(oconn, n=55, approved_ms=T_APPROVED_MS + 1000)
    r = queue.claim_next(oconn, now_ms=T_APPROVED_MS + 5000)
    assert r["intent_id"] == i1 and r["state"] == "SUBMITTING" and r["claimed_ms"] == T_APPROVED_MS + 5000
    assert queue.claim_next(oconn, now_ms=T_APPROVED_MS + 6000) is None     # 노출 의도가 있으면 다음 것 안 가져감
    assert queue.live_intent(oconn)["intent_id"] == i1
    # 인덱스가 직접 UPDATE로도 두 번째 노출 상태를 막는다
    with pytest.raises(sqlite3.IntegrityError):
        oconn.execute("UPDATE order_intents SET state = 'SUBMITTING', claimed_ms = 1 WHERE intent_id = ?", (i2,))
    assert queue.transition(oconn, i1, I.SUBMITTING, I.REJECTED, now_ms=T_APPROVED_MS + 7000, reason="stale")
    assert _sig_state(oconn, s1) == "SKIPPED"
    assert queue.claim_next(oconn, now_ms=T_APPROVED_MS + 8000)["intent_id"] == i2


def test_claim_concurrent_threads_single_winner(tmp_path):
    path = tmp_path / "t.sqlite3"
    c0 = db.connect(path, mode=TEST_MODE, now_ms=T_APPROVED_MS)
    queue.ensure_schema(c0)
    make_approved_intent(c0)
    results, barrier = [], threading.Barrier(6)

    def worker():
        c = db.connect(path, mode=TEST_MODE, now_ms=T_APPROVED_MS)
        barrier.wait()
        r = queue.claim_next(c, now_ms=T_APPROVED_MS + 1)
        results.append(r is not None)
        c.close()

    ts = [threading.Thread(target=worker) for _ in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sum(results) == 1
    c0.close()


def test_full_happy_path_signal_sync(oconn):
    sid, iid = make_approved_intent(oconn)
    t = T_APPROVED_MS + 5000
    queue.claim_next(oconn, now_ms=t)
    assert queue.update_fields(oconn, iid, I.SUBMITTING, {"entry_sent_ms": t, "entry_client_id": make_client_id(sid, "e1"),
                                                          "entry_deadline_ms": t + 5000}, now_ms=t)
    assert not queue.update_fields(oconn, iid, I.QUEUED, {"entry_sent_ms": t}, now_ms=t)
    assert queue.transition(oconn, iid, I.SUBMITTING, I.ENTRY_FILLED, now_ms=t + 100,
                            fields={"filled_qty": 0.013, "avg_fill_price": 60_010.0, "entry_fill_ms": t + 100})
    assert _sig_state(oconn, sid) == "FILLED"
    assert queue.transition(oconn, iid, I.ENTRY_FILLED, I.STOP_PLACED, now_ms=t + 300,
                            fields={"stop_price": 57_010.0, "stop_placed_ms": t + 300})
    assert queue.transition(oconn, iid, I.STOP_PLACED, I.STOP_VERIFIED, now_ms=t + 500,
                            fields={"stop_verified_ms": t + 500, "unprotected_ms": 400})
    assert queue.request_exit(oconn, sid, exit_signal_close_ms=1, exit_due_ms=t + 10_000, now_ms=t + 600)
    assert not queue.request_exit(oconn, sid, exit_signal_close_ms=1, exit_due_ms=t + 20_000, now_ms=t + 700)
    assert queue.get_intent(oconn, iid)["exit_due_ms"] == t + 10_000
    assert queue.transition(oconn, iid, I.STOP_VERIFIED, I.EXITING, now_ms=t + 10_000, fields={"exit_attempts": 1})
    assert queue.transition(oconn, iid, I.EXITING, I.CLOSED, now_ms=t + 10_500,
                            fields={"exit_reason": "trend", "closed_ms": t + 10_500, "exit_price": 58_000.0})
    assert _sig_state(oconn, sid) == "CLOSED"
    assert queue.live_intent(oconn) is None
    # 전이마다 감사 로그
    n = oconn.execute("SELECT COUNT(*) FROM audit_log WHERE entity_type = 'order_intent'").fetchone()[0]
    assert n >= 7


def test_failed_flattened_from_submitting_closes_signal_via_filled(oconn):
    sid, iid = make_approved_intent(oconn)
    t = T_APPROVED_MS + 5000
    queue.claim_next(oconn, now_ms=t)
    queue.update_fields(oconn, iid, I.SUBMITTING, {"entry_sent_ms": t}, now_ms=t)
    assert queue.transition(oconn, iid, I.SUBMITTING, I.FAILED_FLATTENED, now_ms=t + 1,
                            fields={"exit_reason": "flatten", "closed_ms": t + 1})
    assert _sig_state(oconn, sid) == "CLOSED"
    states = [r["to_state"] for r in oconn.execute(
        "SELECT to_state FROM audit_log WHERE entity_type='signal' AND entity_id=? ORDER BY seq", (sid,))]
    assert states[-2:] == ["FILLED", "CLOSED"]


def test_not_filled_requires_sent_and_skips_signal(oconn):
    sid, iid = make_approved_intent(oconn)
    t = T_APPROVED_MS + 5000
    queue.claim_next(oconn, now_ms=t)
    with pytest.raises(sqlite3.IntegrityError):          # 보내지도 않았는데 NOT_FILLED
        queue.transition(oconn, iid, I.SUBMITTING, I.NOT_FILLED, now_ms=t)
    queue.update_fields(oconn, iid, I.SUBMITTING, {"entry_sent_ms": t}, now_ms=t)
    with pytest.raises(sqlite3.IntegrityError):          # 보낸 뒤 REJECTED 금지
        queue.transition(oconn, iid, I.SUBMITTING, I.REJECTED, now_ms=t)
    assert queue.transition(oconn, iid, I.SUBMITTING, I.NOT_FILLED, now_ms=t + 1, reason="entry_not_filled")
    assert _sig_state(oconn, sid) == "SKIPPED"
    assert db.get_signal(oconn, sid)["state_reason"] == "order:entry_not_filled"


def test_holding_requires_fill_fields(oconn):
    _, iid = make_approved_intent(oconn)
    queue.claim_next(oconn, now_ms=T_APPROVED_MS + 1)
    with pytest.raises(sqlite3.IntegrityError):
        queue.transition(oconn, iid, I.SUBMITTING, I.ENTRY_FILLED, now_ms=T_APPROVED_MS + 2)


def test_transition_guards(oconn):
    sid, iid = make_approved_intent(oconn)
    with pytest.raises(ValueError):
        queue.transition(oconn, iid, I.QUEUED, I.STOP_VERIFIED, now_ms=1)        # 금지 전이
    with pytest.raises(ValueError):
        queue.transition(oconn, iid, I.QUEUED, I.SUBMITTING, now_ms=1, fields={"signal_id": "x"})
    with pytest.raises(ValueError):
        queue.update_fields(oconn, iid, I.QUEUED, {"state": "CLOSED"}, now_ms=1)
    assert not queue.transition(oconn, iid, I.SUBMITTING, I.REJECTED, now_ms=1)  # 기대 상태 불일치
    assert not queue.transition(oconn, 9999, I.QUEUED, I.REJECTED, now_ms=1)


def test_cancel_queued_only_before_claim(oconn):
    sid, iid = make_approved_intent(oconn)
    sid2, iid2 = make_approved_intent(oconn, n=55)
    assert queue.cancel_queued(oconn, sid2, now_ms=T_APPROVED_MS + 1, reason="paused")
    assert _sig_state(oconn, sid2) == "SKIPPED"
    queue.claim_next(oconn, now_ms=T_APPROVED_MS + 2)
    assert not queue.cancel_queued(oconn, sid, now_ms=T_APPROVED_MS + 3, reason="paused")
    assert _sig_state(oconn, sid) == "APPROVED"
    assert not queue.cancel_queued(oconn, "B" * 16, now_ms=1, reason="x")


def test_signal_mismatch_does_not_block_intent(oconn):
    """A가 신호를 먼저 SKIPPED로 바꿔도(위조·경쟁) 거래소 사실인 의도 전이는 기록된다 + 경보."""
    sid, iid = make_approved_intent(oconn)
    queue.claim_next(oconn, now_ms=T_APPROVED_MS + 1)
    assert db.transition_signal(oconn, sid, SignalState.APPROVED, SignalState.SKIPPED, now_ms=T_APPROVED_MS + 2,
                                actor="ENGINE", reason="paused")
    queue.update_fields(oconn, iid, I.SUBMITTING, {"entry_sent_ms": T_APPROVED_MS + 3}, now_ms=T_APPROVED_MS + 3)
    assert queue.transition(oconn, iid, I.SUBMITTING, I.ENTRY_FILLED, now_ms=T_APPROVED_MS + 4,
                            fields={"filled_qty": 0.01, "avg_fill_price": 60_000.0, "entry_fill_ms": 1})
    assert queue.get_intent(oconn, iid)["state"] == "ENTRY_FILLED"
    alert = oconn.execute("SELECT payload_json FROM audit_log WHERE event_type='ALERT' ORDER BY seq DESC").fetchone()
    assert "signal_state_mismatch" in alert[0]


def test_events_and_halts_append_only(oconn):
    _, iid = make_approved_intent(oconn)
    eid = queue.add_event(oconn, intent_id=iid, kind="REQUEST", now_ms=1, client_id="c",
                          payload={"path": "/fapi/v1/order", "signature": "abc", "api_key": "k"})
    row = oconn.execute("SELECT payload_json FROM order_events WHERE event_id=?", (eid,)).fetchone()
    assert '"api_key": "***"' in row[0]
    with pytest.raises(ValueError):
        queue.add_event(oconn, intent_id=iid, kind="BOGUS", now_ms=1)
    hid = queue.raise_halt(oconn, reason=HaltReason.STOP_MISSING, now_ms=2, intent_id=iid, detail={"x": 1})
    for sql in ("UPDATE order_events SET kind='NOTE'", "DELETE FROM order_events",
                f"INSERT OR REPLACE INTO order_events(event_id, ts_ms, kind) VALUES ({eid}, 1, 'NOTE')",
                "UPDATE order_halts SET reason='operator'", "DELETE FROM order_halts",
                f"INSERT OR REPLACE INTO order_halts(halt_id, ts_ms, level, reason) VALUES ({hid}, 1, 'T0', 'operator')"):
        with pytest.raises(sqlite3.DatabaseError):
            oconn.execute(sql)
    # 경고가 outbox에 들어갔다(A가 전송)
    ob = oconn.execute("SELECT kind, text FROM outbox ORDER BY outbox_id DESC").fetchone()
    assert ob["kind"] == "alert" and ob["text"].startswith("[TESTNET]") and f"#{hid}" in ob["text"]


def test_halt_release_only_via_control_set(oconn):
    h1 = queue.raise_halt(oconn, reason=HaltReason.CLOCK_SKEW, now_ms=1)
    h2 = queue.raise_halt(oconn, reason=HaltReason.AUTH, now_ms=2)
    assert queue.active_halt_ids(oconn, []) == [h1, h2]
    # DB에 해제 행을 직접 넣어도(A 위조) 판정은 제어 파일 집합만 본다
    oconn.execute("INSERT INTO order_halt_releases(halt_id, ts_ms, control_ref) VALUES (?, 3, 'forged')", (h1,))
    assert queue.active_halt_ids(oconn, []) == [h1, h2]
    assert queue.active_halt_ids(oconn, [h1]) == [h2]
    assert not queue.record_release(oconn, h1, control_ref="file", now_ms=4)     # 이미 기록됨
    assert queue.record_release(oconn, h2, control_ref="file@1", now_ms=5)
    assert not queue.record_release(oconn, 999, control_ref="file", now_ms=6)
    with pytest.raises(sqlite3.DatabaseError):
        oconn.execute("DELETE FROM order_halt_releases")
    with pytest.raises(ValueError):
        queue.raise_halt(oconn, reason="not_a_reason", now_ms=1)


def test_ensure_schema_detects_dropped_trigger(tmp_path):
    path = tmp_path / "x.sqlite3"
    c = db.connect(path, mode=TEST_MODE, now_ms=1)
    queue.ensure_schema(c)
    queue.ensure_schema(c)                                                        # 멱등
    c.execute("DROP TRIGGER order_events_no_delete")
    with pytest.raises(db.DbError):
        queue.ensure_schema(c)
    c.close()


def test_notify_and_runtime(oconn):
    oid = queue.notify(oconn, "체결 0.013 BTC", now_ms=1)
    assert oconn.execute("SELECT text FROM outbox WHERE outbox_id=?", (oid,)).fetchone()[0].startswith("[TESTNET] ")
    queue.set_runtime(oconn, "b_heartbeat_ms", 10, now_ms=10)
    queue.set_runtime(oconn, "b_heartbeat_ms", 20, now_ms=20)
    assert queue.get_runtime(oconn, "b_heartbeat_ms")["value"] == "20"
    with pytest.raises(sqlite3.IntegrityError):
        queue.set_runtime(oconn, "unknown_key", 1, now_ms=1)
