"""검토 지적 수정의 회귀 시험 — 수정 담당 (DESIGN §16 R 표).

review_security_test.py·review_chaos_test.py의 재현 시험(xfail을 지운 것)에 더해, 새로 넣은 부품을 직접 시험한다:
B 전용 원장(ledger), DB 무결성 검사, 제어 파일 해제의 T0 결합(F8), 누적 한도(SEC-04), 429 대기 창(F2),
B 단일 실행 잠금(F6), 미래 승인 거부(SEC-05), 끝난 의도의 손절 보존(SEC-01).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading

import pytest

from bot import db
from bot.orders import queue
from bot.orders import worker as W
from bot.orders.control import ControlState, parse_control
from bot.orders.fake_exchange import FakeExchange, Fault, FaultKind
from bot.orders.gateway import Gateway, realized_pnl
from bot.orders.ledger import Ledger, LedgerError
from bot.orders.reconcile import reconcile_once
from bot.orders.tests.conftest import DEMO_URL, MARK, T_APPROVED_MS, make_approved_intent, make_orders_config
from bot.orders.tests.test_gateway import halt_reasons, intent, now_ms, to_verified
from bot.orders.types import (
    MAX_ENTRIES_PER_UTC_DAY,
    UTC_DAY_MS,
    ErrorKind,
    ExchangeError,
    IdPurpose,
    IntentState,
    make_client_id,
)
from bot.tests.conftest import T_DECISION_NS, T_MS
from bot.types import FakeClock, Mode, NS_PER_MS

S = IntentState
CTL = ControlState(manual_halt=False)
DAY_NS = 86_400 * 10**9


def mk_worker(conn, cfg, ex, clock, *, control=CTL, ledger: Ledger | None = None) -> W.Worker:
    return W.Worker(conn, cfg, ex, clock, control_loader=lambda: control, ledger=ledger)


def forge_approval(conn, clock, k: int) -> tuple[str, int]:
    """침해된 A 흉내: 지금 시각의 새 APPROVED 신호(하위 시스템·판단 시각을 바꿔 고유 제약 회피)."""
    return make_approved_intent(conn, n=(20, 55, 100)[k % 3], approved_ms=now_ms(clock),
                                decision_ns=T_DECISION_NS + (k + 1) * DAY_NS)


# ---------------------------------------------------------------------------
# B 전용 원장
# ---------------------------------------------------------------------------


def test_ledger_file_roundtrip_permissions_and_corruption(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    p = d / "orders_ledger.json"
    lg = Ledger(p)
    assert lg.error is None and p.exists() and (p.stat().st_mode & 0o777) == 0o600
    lg.record_entry("AAAAAAAAAAAAAAAA", 1_000)
    lg.record_halt(7, 2_000, "stop_missing", 3)
    lg.record_close("AAAAAAAAAAAAAAAA", 3_000, "stop", -12.5)
    lg.record_close("AAAAAAAAAAAAAAAA", 4_000, "stop", -99.0)          # 신호당 한 번
    assert lg.release_first_seen(7, 5_000) == 5_000 and lg.release_first_seen(7, 9_000) == 5_000
    again = Ledger(p)
    assert again.error is None
    assert [e["sid"] for e in again.entries()] == ["AAAAAAAAAAAAAAAA"]
    assert [(h["id"], h["reason"]) for h in again.halts()] == [(7, "stop_missing")]
    assert [c["pnl"] for c in again.closes()] == [-12.5]
    assert again.release_first_seen(7, 99_000) == 5_000                  # 재시작 뒤에도 '처음 본 시각' 유지
    os.chmod(p, 0o644)
    assert Ledger(p).error == "permissions_too_open"
    os.chmod(p, 0o600)
    p.write_text("{not json", encoding="utf-8")
    assert Ledger(p).error is not None
    p.write_text(json.dumps({"version": 1, "entries": "x"}), encoding="utf-8")
    assert Ledger(p).error == "corrupt"
    missing = Ledger(tmp_path / "nope" / "l.json")
    assert missing.error == "dir_missing"
    with pytest.raises(LedgerError):
        missing.record_entry("AAAAAAAAAAAAAAAA", 1)


def test_ledger_error_blocks_new_entries_but_protection_continues(tmp_path, oconn, ocfg, oclock):
    fx = FakeExchange(oclock, mark=MARK)
    bad = Ledger(tmp_path / "missing-dir" / "l.json")
    w = mk_worker(oconn, ocfg, fx, oclock, ledger=bad)
    w.startup()
    sid, iid = make_approved_intent(oconn, approved_ms=now_ms(oclock))
    w.run_once()
    assert intent(oconn, iid)["state"] == S.REJECTED.value
    assert intent(oconn, iid)["state_reason"] == "ledger_unavailable"
    assert fx.post_count("place_order") == 0
    alerts = [r["text"] for r in oconn.execute("SELECT text FROM outbox WHERE kind = 'alert'")]
    assert any("원장" in t for t in alerts)


# ---------------------------------------------------------------------------
# SEC-02: T0는 DB에서 지워져도 B 원장에 남는다 + 무결성 검사
# ---------------------------------------------------------------------------


def test_ledger_keeps_t0_even_if_a_deletes_rows_and_rewinds_sequence(tmp_path, ocfg, oclock):
    """A가 트리거를 지우고 T0 행을 지운 뒤 sqlite_sequence까지 되돌려 빈 번호를 없애도 B 원장의 T0로 정지가 유지된다."""
    path = tmp_path / "t.sqlite3"
    conn_b = db.connect(path, mode=Mode.TESTNET, now_ms=T_MS)
    queue.ensure_schema(conn_b)
    fx = FakeExchange(oclock, mark=MARK)
    w = mk_worker(conn_b, ocfg, fx, oclock)
    w.startup()
    fx.plant_foreign_order()                                   # 대조 → 취소 + T0 unknown_order (B가 건다 → 원장)
    oclock.advance(31_000 * NS_PER_MS)
    w.run_once()
    assert halt_reasons(conn_b) == ["unknown_order"]
    conn_a = db.connect(path, mode=Mode.TESTNET, now_ms=T_MS)
    body = conn_a.execute("SELECT sql FROM sqlite_master WHERE name='order_halts_no_delete'").fetchone()[0]
    conn_a.execute("DROP TRIGGER order_halts_no_delete")
    conn_a.execute("DELETE FROM order_halts")
    conn_a.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'order_halts'")
    conn_a.execute(body)
    assert queue.integrity_problems(conn_a) == []              # DB만 보면 흔적이 없다
    make_approved_intent(conn_a, approved_ms=now_ms(oclock))
    w.run_once()
    assert fx.post_count("place_order") == 0, "원장의 T0가 DB 삭제로 풀렸다"


def test_integrity_t0_can_be_released_then_new_tampering_raises_again(tmp_path, ocfg, oclock):
    path = tmp_path / "t.sqlite3"
    conn = db.connect(path, mode=Mode.TESTNET, now_ms=T_MS)
    queue.ensure_schema(conn)
    queue.raise_halt(conn, reason="auth", now_ms=now_ms(oclock))           # 행 1
    body = conn.execute("SELECT sql FROM sqlite_master WHERE name='order_halts_no_delete'").fetchone()[0]
    conn.execute("DROP TRIGGER order_halts_no_delete")
    conn.execute("DELETE FROM order_halts")
    conn.execute(body)
    assert queue.integrity_problems(conn) == ["order_halts_gap:1"]
    fx = FakeExchange(oclock, mark=MARK)
    ctl = {"c": CTL}
    w = W.Worker(conn, ocfg, fx, oclock, control_loader=lambda: ctl["c"])
    w.startup()
    tamper = [r for r in queue.halts(conn) if r["reason"] == "order_error"]
    assert len(tamper) == 1 and "db_integrity" in tamper[0]["detail_json"]
    hid = int(tamper[0]["halt_id"])
    oclock.advance(1_000 * NS_PER_MS)
    ctl["c"] = ControlState(manual_halt=False, released=frozenset({hid}), ref="ctl@1")
    w.run_once()
    w.run_once()
    assert len(queue.halts(conn)) == 1 and not w.gw.is_halted(ctl["c"])     # 확인된 문제로 반복하지 않는다
    # 더 지우면(빈 번호가 늘면) 새 문제 → 새 T0
    extra = queue.raise_halt(conn, reason="auth", now_ms=now_ms(oclock))    # 새 T0(아직 안 풀림)를 A가 지운다
    conn.execute("DROP TRIGGER order_halts_no_delete")
    conn.execute("DELETE FROM order_halts WHERE halt_id = ?", (extra,))
    conn.execute(body)
    assert queue.integrity_problems(conn) == ["order_halts_gap:2"]
    w.run_once()
    assert w.gw.is_halted(ctl["c"])


def test_altered_protect_trigger_body_refuses_start(tmp_path):
    path = tmp_path / "t.sqlite3"
    conn = db.connect(path, mode=Mode.TESTNET, now_ms=T_MS)
    queue.ensure_schema(conn)
    conn.execute("DROP TRIGGER order_halts_no_delete")
    conn.execute("CREATE TRIGGER order_halts_no_delete BEFORE DELETE ON order_halts WHEN 0 "
                 "BEGIN SELECT RAISE(ABORT, 'order_halts is append-only'); END")
    assert "trigger_altered:order_halts_no_delete" in queue.integrity_problems(conn)
    with pytest.raises(db.DbError):
        queue.ensure_schema(conn)


# ---------------------------------------------------------------------------
# F8: 해제는 그 T0 뒤에 처음 본 것만, at이 T0보다 이르면 무시
# ---------------------------------------------------------------------------


def test_release_with_at_before_halt_is_ignored(oconn, ocfg, oclock):
    fx = FakeExchange(oclock, mark=MARK)
    gw = Gateway(oconn, ocfg, fx, oclock, base_url=DEMO_URL)
    hid = gw._halt(queue.HaltReason.AUTH, intent_id=None)
    oclock.advance(5 * 60_000 * NS_PER_MS)
    old = parse_control(f'halt = false\n[[release]]\nhalt_id = {hid}\nat = "2020-01-01T00:00:00Z"\nreason = "옛날"\n')
    assert old.error is None and gw.is_halted(old)
    ok = parse_control(f'halt = false\n[[release]]\nhalt_id = {hid}\nat = "2030-01-01T00:00:00Z"\nreason = "확인"\n')
    assert not gw.is_halted(ok)


def test_stale_release_stays_ignored_across_restart_with_file_ledger(tmp_path, oconn, ocfg, oclock):
    """F8의 재시작 구멍: 옛 해제(id 1)를 T0 #1이 생기기 전에 본 B가 재시작해도 원장의 '처음 본 시각'으로 계속 무시."""
    (tmp_path / "state").mkdir()
    lp = tmp_path / "state" / "l.json"
    stale = ControlState(manual_halt=False, released=frozenset({1}), ref="old")
    fx = FakeExchange(oclock, mark=MARK)
    w = mk_worker(oconn, ocfg, fx, oclock, control=stale, ledger=Ledger(lp))
    w.startup()
    fx.plant_foreign_order()
    oclock.advance(31_000 * NS_PER_MS)
    w.run_once()
    assert [int(r["halt_id"]) for r in queue.halts(oconn)] == [1]
    oclock.advance(60_000 * NS_PER_MS)
    w2 = mk_worker(oconn, ocfg, fx, oclock, control=stale, ledger=Ledger(lp))   # 재시작
    w2.startup()
    sid, iid = make_approved_intent(oconn, approved_ms=now_ms(oclock))
    w2.run_once()
    assert fx.post_count("place_order", client_id=make_client_id(sid, IdPurpose.ENTRY)) == 0
    assert intent(oconn, iid)["state_reason"] == "halted"


# ---------------------------------------------------------------------------
# SEC-04: 누적 한도(하루 진입 수·T1·T2) — B 원장 기준, 다음 UTC 00:00 자동 해제
# ---------------------------------------------------------------------------


def test_daily_entry_cap_blocks_then_clears_next_utc_day(oconn, ocfg, oclock):
    fx = FakeExchange(oclock, mark=MARK)
    w = mk_worker(oconn, ocfg, fx, oclock)
    w.startup()
    for k in range(MAX_ENTRIES_PER_UTC_DAY):
        fx.inject(Fault(FaultKind.NO_FILL, method="place_order"))           # IOC 0 체결(손실 없음)
        _, iid = forge_approval(oconn, oclock, k)
        w.run_once()
        assert intent(oconn, iid)["state"] == S.NOT_FILLED.value
    _, iid = forge_approval(oconn, oclock, 10)
    w.run_once()
    assert intent(oconn, iid)["state"] == S.REJECTED.value and intent(oconn, iid)["state_reason"] == "daily_entry_cap"
    assert fx.post_count("place_order") == MAX_ENTRIES_PER_UTC_DAY
    # A가 DB 기록을 지워도(NOT_FILLED 행을 없던 것처럼) B 원장이 센다
    oconn.execute("UPDATE order_intents SET state = 'REJECTED', entry_sent_ms = NULL WHERE state = 'NOT_FILLED'")
    assert w.gw.aggregate_block(now_ms(oclock)) == "daily_entry_cap"
    # 다음 UTC 00:00 뒤에는 자동 해제
    now = now_ms(oclock)
    oclock.advance((UTC_DAY_MS - now % UTC_DAY_MS + 60_000) * NS_PER_MS)
    _, iid = forge_approval(oconn, oclock, 11)
    w.run_once()
    assert intent(oconn, iid)["state"] == S.STOP_VERIFIED.value


def test_t1_three_stops_block_until_next_utc_day(oconn, ocfg, oclock):
    gw = Gateway(oconn, ocfg, FakeExchange(oclock, mark=MARK), oclock, base_url=DEMO_URL)
    now = now_ms(oclock)
    for k in range(3):                                           # 같은 UTC 날(00:31) 안의 손절 3번
        gw.ledger.record_close(f"AAAAAAAAAAAAAAA{k}", now - (3 - k) * 300_000, "stop", -1.0)
    assert gw.aggregate_block(now) == "t1_stop_streak"
    next_day = now - now % UTC_DAY_MS + UTC_DAY_MS
    assert gw.aggregate_block(next_day + 1) is None


def test_t2_daily_loss_blocks(oconn, ocfg, oclock):
    cfg = make_orders_config(r_capital_usdt=10_000.0, risk_fraction=0.005)     # 1R = 50 USDT
    gw = Gateway(oconn, cfg, FakeExchange(oclock, mark=MARK), oclock, base_url=DEMO_URL)
    now = now_ms(oclock)
    gw.ledger.record_close("AAAAAAAAAAAAAAAA", now - 1_000, "flatten", -100.0)
    assert gw.aggregate_block(now) is None
    gw.ledger.record_close("AAAAAAAAAAAAAAAB", now - 500, "trend", -60.0)       # 합계 −160 ≤ −150(3R)
    assert gw.aggregate_block(now) == "t2_daily_loss"


def test_realized_pnl_estimates():
    row = {"avg_fill_price": 60_000.0, "filled_qty": 0.01, "exit_qty": None, "exit_price": None,
           "exit_reason": "stop", "stop_price": 57_000.0}
    p = realized_pnl(row)
    assert p is not None and p == pytest.approx(-30.0 - 0.0005 * 0.01 * 117_000.0)
    assert realized_pnl({**row, "exit_reason": "external"}) is None


# ---------------------------------------------------------------------------
# SEC-05: 미래 승인
# ---------------------------------------------------------------------------


def test_future_approval_rejected_in_queue_before_claim(oconn, ocfg, oclock):
    fx = FakeExchange(oclock, mark=MARK)
    gw = Gateway(oconn, ocfg, fx, oclock, base_url=DEMO_URL)
    _, iid = make_approved_intent(oconn, approved_ms=now_ms(oclock) + 60_000)
    assert gw.reject_stale_queued() == 1
    assert intent(oconn, iid)["state_reason"] == "future_approval"


# ---------------------------------------------------------------------------
# F2: 429 대기 창 — 창 안에서는 어떤 요청도 보내지 않는다
# ---------------------------------------------------------------------------


def test_rate_limit_window_is_honoured_by_every_call(oconn, ocfg, oclock):
    fx = FakeExchange(oclock, mark=MARK)
    gw = Gateway(oconn, ocfg, fx, oclock, base_url=DEMO_URL)
    fx.inject(Fault(FaultKind.RATE_LIMIT, method="position", params={"retry_after_s": 3.0}))
    t0 = now_ms(oclock)
    with pytest.raises(ExchangeError) as ei:
        gw._x(None, "position")
    assert getattr(ei.value, "kind", None) is ErrorKind.RATE_LIMITED
    gw._x(None, "open_orders")                                   # 다른 메서드여도 창이 끝날 때까지 기다린 뒤 보낸다
    assert now_ms(oclock) - t0 >= 3_000
    assert [c.outcome for c in fx.calls].count("fault:rate_limit") == 1


# ---------------------------------------------------------------------------
# SEC-01: 포지션이 있으면 '끝난' 의도의 손절도 취소하지 않는다 / 포지션 0이면 고아 손절 정리(기존 동작 유지)
# ---------------------------------------------------------------------------


def test_orphan_stop_cancelled_only_when_flat(oconn, ocfg, oclock):
    fx = FakeExchange(oclock, mark=MARK)
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    oconn.execute("UPDATE order_intents SET state='CLOSED', exit_reason='trend', closed_ms=? WHERE intent_id=?",
                  (now_ms(oclock), iid))
    r = reconcile_once(oconn, gw, fx, oclock, CTL)
    assert len(fx.active_conditionals()) == 1 and fx.position_qty > 0
    assert "terminal_intent_stop_with_position" in r.issues and "position_mismatch" in halt_reasons(oconn)
    # 사람이 거래소에서 포지션을 정리한 뒤에는 고아 손절로 정리된다
    fx.set_mark(float(fx.active_conditionals()[0].trigger_price) - 50.0)    # 손절 발동 → 포지션 0
    fx.tick(1_000)
    fx.set_mark(MARK)
    fx.tick(0)
    if fx.active_conditionals():
        reconcile_once(oconn, gw, fx, oclock, CTL)
    assert fx.position_qty == 0 and not fx.active_conditionals()


# ---------------------------------------------------------------------------
# F6: B 단일 실행 잠금
# ---------------------------------------------------------------------------


def test_main_refuses_second_instance(tmp_path, monkeypatch):
    from bot.orders.tests.test_worker import _write_toml

    old = os.umask(0o022)
    try:
        p = _write_toml(tmp_path)
        dbp = tmp_path / "data" / "testnet.sqlite3"
        dbp.parent.mkdir(parents=True, exist_ok=True)
        fd = W._acquire_single_instance_lock(dbp)
        assert fd is not None and fd >= 0
        try:
            assert W._acquire_single_instance_lock(dbp) is None
            clock = FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)
            stop = threading.Event()
            stop.set()
            code = W.main(["--config", str(p), "run"], environ={}, clock=clock,
                          client_factory=lambda c, k: FakeExchange(k, mark=MARK), stop=stop)
            assert code == W.EXIT_CONFIG
        finally:
            os.close(fd)
        code = W.main(["--config", str(p), "run"], environ={}, clock=FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS),
                      client_factory=lambda c, k: FakeExchange(k, mark=MARK), stop=stop)
        assert code == W.EXIT_OK
    finally:
        os.umask(old)


# ---------------------------------------------------------------------------
# SEC-03 보강: 이벤트 기록 실패는 모았다가 나중에 쓴다
# ---------------------------------------------------------------------------


def test_event_backlog_flushed_after_db_recovers(oconn, ocfg, oclock, monkeypatch):
    fx = FakeExchange(oclock, mark=MARK)
    gw = Gateway(oconn, ocfg, fx, oclock, base_url=DEMO_URL)
    real = queue.add_event
    fail = {"on": True}

    def flaky(conn, **kw):
        if fail["on"]:
            raise sqlite3.OperationalError("database is locked")
        return real(conn, **kw)

    monkeypatch.setattr(queue, "add_event", flaky)
    gw._event(None, "NOTE", payload={"n": 1})
    gw._event(None, "NOTE", payload={"n": 2})
    assert len(gw._event_backlog) == 2
    fail["on"] = False
    gw._event(None, "NOTE", payload={"n": 3})
    rows = [json.loads(r["payload_json"])["n"] for r in oconn.execute(
        "SELECT payload_json FROM order_events WHERE kind = 'NOTE' ORDER BY event_id")]
    assert rows == [1, 2, 3] and gw._event_backlog == []


def test_long_ban_window_fails_fast_without_sending(oconn, ocfg, oclock):
    """418 금지(Retry-After 10분)는 호출 안에서 기다리지 않는다: 보내지 않고 곧바로 같은 종류로 실패(루프는 계속)."""
    fx = FakeExchange(oclock, mark=MARK)
    gw = Gateway(oconn, ocfg, fx, oclock, base_url=DEMO_URL)
    gw.note_exchange_error(ExchangeError(ErrorKind.IP_BANNED, http_status=418, retry_after_s=600.0))
    n = len(fx.calls)
    t0 = now_ms(oclock)
    with pytest.raises(ExchangeError) as ei:
        gw._x(None, "position")
    assert ei.value.kind is ErrorKind.IP_BANNED and len(fx.calls) == n and now_ms(oclock) == t0
    oclock.advance(601_000 * NS_PER_MS)
    gw._x(None, "position")                                        # 창이 끝나면 정상
    assert len(fx.calls) == n + 1
