"""bot.db — 스키마·원자적 전이·추가 전용 감사 로그·모의 포지션 불변식 (설계 담당)."""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import threading

import pytest

from bot import db
from bot.tests.conftest import T_MS, insert_test_signal, ok_analysis
from bot.types import (
    SIGNAL_TRANSITIONS,
    TERMINAL_STATES,
    Actor,
    AnalystResult,
    AuditEvent,
    Mode,
    SignalState,
    new_signal_id,
)

S = SignalState


def audit_rows(conn, event=None):
    q = "SELECT * FROM audit_log" + (" WHERE event_type = ?" if event else "") + " ORDER BY seq"
    return list(conn.execute(q, (event,) if event else ()))


def walk_to(conn, sid, *states, t=T_MS):
    """NEW에서 주어진 상태들을 차례로 거친다(각 전이는 성공해야 함)."""
    cur = S.NEW
    for i, st in enumerate(states):
        assert db.transition_signal(conn, sid, cur, st, now_ms=t + i, actor=Actor.ENGINE), (cur, st)
        cur = st


def approve(conn, sid, t=T_MS):
    walk_to(conn, sid, S.CARD_SENT, S.CONFIRM_PENDING, S.APPROVED, t=t)


def open_pos(conn, sid, **kw):
    args = dict(signal_id=sid, entry_ms=T_MS + 60_000, entry_price=50_000.0, qty=0.02, stop=47_000.0,
                risk_per_unit=3_060.0, entry_fee=25.0, entry_slippage=10.0, active_from_ms=T_MS + 30_000,
                now_ms=T_MS + 120_000)
    args.update(kw)
    return db.open_position(conn, **args)


# ---------------------------------------------------------------------------
# 연결·스키마
# ---------------------------------------------------------------------------


def test_file_db_wal_private_and_mode_locked(file_db):
    old = os.umask(0o077)
    try:
        c = db.connect(file_db, mode=Mode.PAPER, now_ms=T_MS)
        assert c.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.db_mode(c) == Mode.PAPER
        c.close()
    finally:
        os.umask(old)
    assert stat.S_IMODE(os.stat(file_db).st_mode) == 0o600
    # 같은 모드로 다시 열기: 스키마 재적용 멱등
    c2 = db.connect(file_db, mode=Mode.PAPER, now_ms=T_MS + 1)
    assert c2.execute("SELECT count(*) FROM db_meta").fetchone()[0] == 3
    c2.close()
    # 다른 모드로 열면 거부 (재생 결과가 모의 운영 DB에 섞이는 사고 방지)
    with pytest.raises(db.DbError, match="paper"):
        db.connect(file_db, mode=Mode.REPLAY, now_ms=T_MS)


def test_schema_state_check_matches_enum(conn):
    sid = insert_test_signal(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE signals SET state = 'BOGUS' WHERE signal_id = ?", (sid,))
    # 모든 enum 값이 CHECK를 통과한다
    for st in SignalState:
        conn.execute("UPDATE signals SET state = ? WHERE signal_id = ?", (st.value, sid))


def test_transition_table_shape():
    assert set(SIGNAL_TRANSITIONS) == set(SignalState)
    for st in TERMINAL_STATES:
        assert SIGNAL_TRANSITIONS[st] == frozenset()
    # 모든 비종료 상태는 어떤 종료 상태로 갈 수 있다(갇힘 없음)
    for st in set(SignalState) - TERMINAL_STATES:
        seen, stack = set(), [st]
        while stack:
            x = stack.pop()
            for y in SIGNAL_TRANSITIONS[x]:
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        assert seen & TERMINAL_STATES, st
    # 사람 버튼 없이 APPROVED로 가는 길은 CONFIRM_PENDING 하나뿐(2단계 승인)
    into_approved = {s for s, dsts in SIGNAL_TRANSITIONS.items() if S.APPROVED in dsts}
    assert into_approved == {S.CONFIRM_PENDING}
    into_filled = {s for s, dsts in SIGNAL_TRANSITIONS.items() if S.FILLED in dsts}
    assert into_filled == {S.APPROVED}


# ---------------------------------------------------------------------------
# 신호 삽입·전이
# ---------------------------------------------------------------------------


def test_insert_signal_idempotent_per_day_and_subsystem(conn):
    insert_test_signal(conn, n=20)
    with pytest.raises(AssertionError):
        insert_test_signal(conn, n=20)          # 같은 날·같은 N → insert_signal False
    insert_test_signal(conn, n=55)              # 다른 N은 따로
    assert conn.execute("SELECT count(*) FROM signals").fetchone()[0] == 2
    created = audit_rows(conn, AuditEvent.SIGNAL_CREATED.value)
    assert len(created) == 2 and all(r["to_state"] == "NEW" for r in created)


def test_signal_id_must_be_16_chars(conn):
    with pytest.raises(sqlite3.IntegrityError):
        insert_test_signal(conn, signal_id="SHORT")


def test_transition_success_writes_audit_and_version(conn):
    sid = insert_test_signal(conn)
    ok = db.transition_signal(conn, sid, S.NEW, S.CARD_SENT, now_ms=T_MS + 5, actor=Actor.ENGINE,
                              fields={"card_sent_ms": T_MS + 5, "tg_message_id": 42})
    assert ok
    row = db.get_signal(conn, sid)
    assert row["state"] == "CARD_SENT" and row["state_version"] == 1
    assert row["card_sent_ms"] == T_MS + 5 and row["tg_message_id"] == 42 and row["updated_ms"] == T_MS + 5
    tr = audit_rows(conn, AuditEvent.STATE_TRANSITION.value)
    assert len(tr) == 1
    assert (tr[0]["entity_id"], tr[0]["from_state"], tr[0]["to_state"], tr[0]["actor"]) == (sid, "NEW", "CARD_SENT", "ENGINE")


def test_transition_wrong_state_is_noop(conn):
    sid = insert_test_signal(conn)
    n_audit = len(audit_rows(conn))
    assert not db.transition_signal(conn, sid, S.CARD_SENT, S.CONFIRM_PENDING, now_ms=T_MS, actor=Actor.TELEGRAM_USER)
    assert db.get_signal(conn, sid)["state"] == "NEW"
    assert len(audit_rows(conn)) == n_audit
    assert not db.transition_signal(conn, "A" * 16, S.NEW, S.CARD_SENT, now_ms=T_MS, actor=Actor.ENGINE)


def test_transition_rejects_disallowed_and_unknown_fields(conn):
    sid = insert_test_signal(conn)
    with pytest.raises(ValueError, match="허용되지 않은 전이"):
        db.transition_signal(conn, sid, S.NEW, S.APPROVED, now_ms=T_MS, actor=Actor.ENGINE)   # 승인 단계 건너뛰기
    with pytest.raises(ValueError, match="허용되지 않은 전이"):
        db.transition_signal(conn, sid, [S.CARD_SENT, S.CLOSED], S.PASSED, now_ms=T_MS, actor=Actor.ENGINE)
    with pytest.raises(ValueError, match="바꿀 수 없는 열"):
        db.transition_signal(conn, sid, S.NEW, S.CARD_SENT, now_ms=T_MS, actor=Actor.ENGINE, fields={"close": 1.0})
    assert db.get_signal(conn, sid)["state"] == "NEW"


def test_duplicate_click_only_first_wins(conn):
    sid = insert_test_signal(conn)
    walk_to(conn, sid, S.CARD_SENT)
    results = [db.transition_signal(conn, sid, S.CARD_SENT, S.CONFIRM_PENDING, now_ms=T_MS + i,
                                    actor=Actor.TELEGRAM_USER) for i in range(3)]
    assert results == [True, False, False]
    assert db.get_signal(conn, sid)["state_version"] == 2


def test_multi_expected_states(conn):
    sid = insert_test_signal(conn)
    walk_to(conn, sid, S.CARD_SENT, S.CONFIRM_PENDING)
    assert db.transition_signal(conn, sid, (S.CARD_SENT, S.CONFIRM_PENDING), S.PASSED, now_ms=T_MS, actor=Actor.TELEGRAM_USER)
    assert db.get_signal(conn, sid)["state"] == "PASSED"


def test_concurrent_confirm_from_two_connections(file_db):
    """두 연결(스레드)이 같은 신호를 동시에 APPROVED로 바꾸려 해도 정확히 하나만 성공."""
    c0 = db.connect(file_db, mode=Mode.PAPER, now_ms=T_MS)
    sid = insert_test_signal(c0)
    walk_to(c0, sid, S.CARD_SENT, S.CONFIRM_PENDING)
    c0.close()
    results: list[bool] = []
    barrier = threading.Barrier(8)
    lock = threading.Lock()

    def worker(i):
        c = db.connect(file_db, mode=Mode.PAPER, now_ms=T_MS)
        barrier.wait()
        r = db.transition_signal(c, sid, S.CONFIRM_PENDING, S.APPROVED, now_ms=T_MS + i, actor=Actor.TELEGRAM_USER,
                                 fields={"approved_ms": T_MS + i})
        with lock:
            results.append(r)
        c.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [False] * 7 + [True]
    c = db.connect(file_db, mode=Mode.PAPER, now_ms=T_MS)
    assert db.get_signal(c, sid)["state"] == "APPROVED"
    n = c.execute("SELECT count(*) FROM audit_log WHERE entity_id = ? AND to_state = 'APPROVED'", (sid,)).fetchone()[0]
    assert n == 1
    c.close()


def test_active_signal_for_subsystem(conn):
    assert db.active_signal_for_subsystem(conn, 20) is None
    sid = insert_test_signal(conn, n=20)
    assert db.active_signal_for_subsystem(conn, 20)["signal_id"] == sid
    walk_to(conn, sid, S.CARD_SENT, S.PASSED)
    assert db.active_signal_for_subsystem(conn, 20) is None
    assert [r["signal_id"] for r in db.signals_in_states(conn, [S.PASSED])] == [sid]


# ---------------------------------------------------------------------------
# 감사 로그·스냅샷 (추가 전용)
# ---------------------------------------------------------------------------


def test_audit_log_append_only(conn):
    insert_test_signal(conn)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE audit_log SET actor = 'X'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM audit_log")


def test_config_snapshot_append_only(conn):
    sid = db.save_config_snapshot(conn, config_dict={"mode": "paper"}, fingerprint="ab" * 32, bot_version="t",
                                  now_ms=T_MS)
    assert sid == 1
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM config_snapshots")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE config_snapshots SET fingerprint = 'x'")
    assert audit_rows(conn, AuditEvent.CONFIG_LOADED.value)


def test_audit_payload_redacts_secret_like_keys(conn):
    db.audit(conn, ts_ms=T_MS, actor=Actor.SYSTEM, event=AuditEvent.ALERT,
             payload={"bot_token": "123:abc", "nested": {"api_key": "sk-x", "ok": 1}, "list": [{"password": "p"}]})
    p = json.loads(audit_rows(conn, "ALERT")[0]["payload_json"])
    assert p == {"bot_token": "***", "nested": {"api_key": "***", "ok": 1}, "list": [{"password": "***"}]}


def test_transaction_rolls_back_on_error(conn):
    sid = insert_test_signal(conn)
    with pytest.raises(RuntimeError):
        with db.transaction(conn):
            db.transition_signal(conn, sid, S.NEW, S.CARD_SENT, now_ms=T_MS, actor=Actor.ENGINE)
            raise RuntimeError("중간 실패")
    assert db.get_signal(conn, sid)["state"] == "NEW"
    assert not audit_rows(conn, AuditEvent.STATE_TRANSITION.value)
    assert not conn.in_transaction


# ---------------------------------------------------------------------------
# 버튼·분석
# ---------------------------------------------------------------------------


def test_record_button_dedupes_callback_query_id(conn):
    sid = insert_test_signal(conn)
    kw = dict(signal_id=sid, action="A", update_id=1, from_user_id=1, chat_id=1, message_id=5, clicked_ms=T_MS,
              result="ACCEPTED")
    assert db.record_button(conn, callback_query_id="cq-1", **kw)
    assert not db.record_button(conn, callback_query_id="cq-1", **kw)
    assert db.record_button(conn, callback_query_id="cq-2", **kw)
    assert conn.execute("SELECT count(*) FROM approvals").fetchone()[0] == 2
    assert len(audit_rows(conn, AuditEvent.BUTTON.value)) == 2


def test_insert_analysis_ok_and_failure(conn):
    a1 = db.insert_analysis(conn, ok_analysis(), signal_day="2024-03-01", now_ms=T_MS)
    fail = AnalystResult(ok=False, status="timeout", prompt_version="analyst_v1", model="claude-opus-5-5",
                         input_json='{"x":1}', error="120초 초과")
    a2 = db.insert_analysis(conn, fail, signal_day="2024-03-01", now_ms=T_MS)
    r1 = conn.execute("SELECT * FROM analyses WHERE analysis_id = ?", (a1,)).fetchone()
    r2 = conn.execute("SELECT * FROM analyses WHERE analysis_id = ?", (a2,)).fetchone()
    assert r1["ok"] == 1 and json.loads(r1["output_json"])["opinion"] == "approve"
    assert r2["ok"] == 0 and r2["output_json"] is None and r2["opinion"] is None and r2["status"] == "timeout"
    assert len(audit_rows(conn, AuditEvent.CLAUDE_CALL.value)) == 2
    sid = insert_test_signal(conn)
    assert db.transition_signal(conn, sid, S.NEW, S.CARD_SENT, now_ms=T_MS, actor=Actor.ENGINE,
                                fields={"analysis_id": a1})
    with pytest.raises(sqlite3.IntegrityError):   # 없는 분석 ID는 외래 키 위반
        db.transition_signal(conn, sid, S.CARD_SENT, S.CONFIRM_PENDING, now_ms=T_MS, actor=Actor.ENGINE,
                             fields={"analysis_id": 999})
    assert db.get_signal(conn, sid)["state"] == "CARD_SENT"


# ---------------------------------------------------------------------------
# 모의 포지션
# ---------------------------------------------------------------------------


def test_open_position_requires_approved(conn):
    sid = insert_test_signal(conn)
    walk_to(conn, sid, S.CARD_SENT)
    assert open_pos(conn, sid) is None
    assert db.get_signal(conn, sid)["state"] == "CARD_SENT"
    assert conn.execute("SELECT count(*) FROM paper_positions").fetchone()[0] == 0


def test_open_position_atomic_and_one_per_subsystem(conn):
    sid = insert_test_signal(conn, n=20)
    approve(conn, sid)
    pid = open_pos(conn, sid)
    assert pid is not None
    assert db.get_signal(conn, sid)["state"] == "FILLED"
    pos = db.get_position(conn, pid)
    assert pos["state"] == "OPEN" and pos["subsystem_n"] == 20 and pos["funding"] == 0
    entry = conn.execute("SELECT * FROM paper_trades WHERE position_id = ?", (pid,)).fetchall()
    assert [r["kind"] for r in entry] == ["ENTRY"]
    assert open_pos(conn, sid) is None                               # 같은 신호 두 번 체결 불가
    # 같은 하위 시스템의 두 번째 신호(다른 날): 열린 포지션이 있으면 체결 불가, 신호는 APPROVED 그대로
    sid2 = insert_test_signal(conn, n=20, decision_ns=(T_MS + 86_400_000) * 1_000_000)
    approve(conn, sid2)
    assert open_pos(conn, sid2) is None
    assert db.get_signal(conn, sid2)["state"] == "APPROVED"
    # 다른 하위 시스템은 따로 열 수 있다
    sid3 = insert_test_signal(conn, n=55)
    approve(conn, sid3)
    assert open_pos(conn, sid3) is not None
    assert [r["subsystem_n"] for r in db.open_positions(conn)] == [20, 55]


def test_partial_unique_index_blocks_second_open_row(conn):
    sid = insert_test_signal(conn, n=100)
    approve(conn, sid)
    pid = open_pos(conn, sid)
    row = dict(db.get_position(conn, pid))
    sid2 = insert_test_signal(conn, n=100, decision_ns=(T_MS + 86_400_000) * 1_000_000)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO paper_positions(signal_id, subsystem_n, side, state, active_from_ms, entry_ms,"
                     " entry_price, qty, stop, risk_per_unit, entry_fee, entry_slippage, created_ms, updated_ms)"
                     " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (sid2, 100, 1, "OPEN", row["active_from_ms"], row["entry_ms"], 1.0, 1.0, 1.0, 1.0, 0, 0, 0, 0))


def test_exit_plan_cursor_funding_and_close(conn):
    sid = insert_test_signal(conn)
    approve(conn, sid)
    pid = open_pos(conn, sid)
    # 추세 청산 예약은 한 번만
    assert db.set_exit_plan(conn, pid, exit_signal_close_ms=T_MS + 86_340_000, exit_due_ms=T_MS + 88_200_000, now_ms=T_MS)
    assert not db.set_exit_plan(conn, pid, exit_signal_close_ms=1, exit_due_ms=2, now_ms=T_MS)
    # 커서는 앞으로만
    assert db.advance_cursor(conn, pid, T_MS + 120_000, now_ms=T_MS)
    assert not db.advance_cursor(conn, pid, T_MS + 60_000, now_ms=T_MS)
    assert not db.advance_cursor(conn, pid, T_MS + 120_000, now_ms=T_MS)
    # 펀딩 멱등·누적
    assert db.add_funding(conn, pid, ts_ms=T_MS + 3_600_000, rate=0.0001, price=50_000.0, amount_per_unit=5.0, now_ms=T_MS)
    assert not db.add_funding(conn, pid, ts_ms=T_MS + 3_600_000, rate=0.0001, price=50_000.0, amount_per_unit=5.0, now_ms=T_MS)
    assert db.add_funding(conn, pid, ts_ms=T_MS + 32_400_000, rate=-0.0002, price=50_000.0, amount_per_unit=-10.0, now_ms=T_MS)
    assert db.get_position(conn, pid)["funding"] == pytest.approx(-5.0)
    # 청산
    kw = dict(exit_ms=T_MS + 90_000_000, exit_bar_close_ms=T_MS + 90_060_000, exit_price=52_000.0, exit_reason="trend",
              fees=51.0, slippage=20.4, gross_pnl=2_000.0, net_pnl=1_933.6, r_multiple=0.6319, now_ms=T_MS + 90_060_000,
              exit_fee=26.0, exit_slippage=10.4)
    assert db.close_position(conn, pid, **kw)
    assert not db.close_position(conn, pid, **kw)                    # 두 번 닫기 불가
    pos = db.get_position(conn, pid)
    assert pos["state"] == "CLOSED" and pos["exit_reason"] == "trend"
    assert pos["pnl_usdt"] == pytest.approx(1_933.6 * 0.02)
    assert db.get_signal(conn, sid)["state"] == "CLOSED"
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM paper_trades WHERE position_id = ? ORDER BY ts_ms", (pid,))]
    assert kinds == ["ENTRY", "FUNDING", "FUNDING", "EXIT"]
    assert not db.add_funding(conn, pid, ts_ms=T_MS + 99_000_000, rate=0.0001, price=1.0, amount_per_unit=1.0, now_ms=T_MS)
    assert not db.advance_cursor(conn, pid, T_MS + 99_000_000, now_ms=T_MS)
    with pytest.raises(ValueError):
        db.close_position(conn, pid, **{**kw, "exit_reason": "eod"})


def test_close_position_check_constraint(conn):
    sid = insert_test_signal(conn)
    approve(conn, sid)
    pid = open_pos(conn, sid)
    with pytest.raises(sqlite3.IntegrityError):   # CLOSED인데 exit_ms 없음
        conn.execute("UPDATE paper_positions SET state = 'CLOSED' WHERE position_id = ?", (pid,))


# ---------------------------------------------------------------------------
# 플래그·사이클·백업
# ---------------------------------------------------------------------------


def test_pause_flag(conn):
    assert not db.is_paused(conn)
    assert db.set_paused(conn, True, now_ms=T_MS, actor=Actor.TELEGRAM_USER)
    assert db.is_paused(conn)
    assert not db.set_paused(conn, True, now_ms=T_MS, actor=Actor.TELEGRAM_USER)
    assert db.set_paused(conn, False, now_ms=T_MS + 1, actor=Actor.TELEGRAM_USER)
    assert not db.is_paused(conn)
    rows = audit_rows(conn, AuditEvent.FLAG_CHANGED.value)
    assert [(r["from_state"], r["to_state"]) for r in rows] == [("0", "1"), ("1", "0")]


def test_cycles_idempotent(conn):
    assert db.begin_cycle(conn, "2024-03-02", decision_ms=T_MS, now_ms=T_MS)
    assert db.finish_cycle(conn, "2024-03-02", ok=False, now_ms=T_MS + 1, note="시세 오류")
    assert db.begin_cycle(conn, "2024-03-02", decision_ms=T_MS, now_ms=T_MS + 2)     # FAILED는 재시도 허용
    assert db.finish_cycle(conn, "2024-03-02", ok=True, now_ms=T_MS + 3)
    assert not db.finish_cycle(conn, "2024-03-02", ok=True, now_ms=T_MS + 4)
    assert not db.begin_cycle(conn, "2024-03-02", decision_ms=T_MS, now_ms=T_MS + 5)  # DONE은 다시 돌리지 않음
    assert db.begin_cycle(conn, "2024-03-03", decision_ms=T_MS + 86_400_000, now_ms=T_MS + 86_400_000)


def test_backup_copy_is_private_and_complete(file_db, tmp_path):
    c = db.connect(file_db, mode=Mode.PAPER, now_ms=T_MS)
    sid = insert_test_signal(c)
    dest = tmp_path / "backup" / "b.sqlite3"
    db.backup_to(c, dest)
    c.close()
    assert stat.S_IMODE(os.stat(dest).st_mode) == 0o600
    b = db.connect(dest, mode=Mode.PAPER, now_ms=T_MS)
    assert db.get_signal(b, sid) is not None
    b.close()


def test_new_signal_ids_unique_and_valid():
    ids = {new_signal_id() for _ in range(2000)}
    assert len(ids) == 2000
