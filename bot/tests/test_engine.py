"""엔진 시험 — 핵심 담당 (DESIGN §2, §4, §10).

모의 매매(paper) 함수는 대부분 가짜로 바꿔 끼운다(호출 순서·인자 기록). paper가 구현돼 있으면 마지막 시험이
실제 paper와 함께 재생 한 바퀴를 돈다(구현 전이면 건너뜀).
"""
from __future__ import annotations

import threading

import numpy as np
import pytest

from backtest import trend as TR
from bot import db, paper
from bot.engine import Engine, fallback_card
from bot.marketdata import MarketDataError
from bot.tests.conftest import FakeAnalyst, frame_market_from, make_config, ok_analysis
from bot.types import (
    NS_PER_DAY,
    NS_PER_MIN,
    NS_PER_SEC,
    AnalystResult,
    FakeClock,
    Mode,
    SignalState as S,
    SubsystemAction as A,
    make_callback_data,
    CallbackAction,
    ns_to_ms,
)

DELAY = 60 * NS_PER_SEC


@pytest.fixture(scope="module")
def sigs(trend_market_small):
    daily = TR.DailyData.from_frame(trend_market_small.bars["1d"])
    return daily, {n: TR.channel_signals(daily, n) for n in TR.PERIODS}


@pytest.fixture
def calls(monkeypatch):
    """paper 함수를 기록용 가짜로 교체."""
    log: list[tuple] = []
    monkeypatch.setattr(paper, "catch_up", lambda conn, cfg, market, until: log.append(("catch_up", until)) or [])
    monkeypatch.setattr(paper, "fill_approved", lambda conn, cfg, market, now: log.append(("fill", now)) or [])
    monkeypatch.setattr(paper, "monitor", lambda conn, cfg, market, now: log.append(("monitor", now)) or [])
    monkeypatch.setattr(paper, "daily_report", lambda conn, cfg, now: (_ for _ in ()).throw(NotImplementedError()))
    return log


class Rig:
    def __init__(self, conn, market_data, t: int, *, analyst=None, tmp_path=None, **cfg_over):
        self.conn = conn
        daily = market_data.bars["1d"]
        self.decision_ns = int(daily["close_ns"].iloc[t]) + DELAY
        self.clock = FakeClock(self.decision_ns)
        self.market = frame_market_from(market_data, self.clock)
        self.cfg = make_config(tmp_path, **cfg_over)
        self.analyst = analyst if analyst is not None else FakeAnalyst()
        self.engine = Engine(conn, self.cfg, self.market, self.analyst, self.clock)

    def set(self, t_ns: int):
        self.clock.set(t_ns)

    def state(self, sid: str) -> str:
        return db.get_signal(self.conn, sid)["state"]


def entry_day(sigs, n: int = 20, k: int = 0) -> int:
    return int(np.flatnonzero(sigs[1][n].long_entry)[k])


@pytest.fixture
def rig(conn, trend_market_small, sigs, calls, tmp_path):
    return Rig(conn, trend_market_small, entry_day(sigs), tmp_path=tmp_path)


def run_and_send(rig: Rig):
    rep = rig.engine.run_daily_cycle()
    for i, m in enumerate(rep.outgoing):
        if m.kind == "card":
            assert rig.engine.mark_card_sent(m.signal_id, 5000 + i)
    return rep


# ---------------------------------------------------------------------------
# 일일 사이클
# ---------------------------------------------------------------------------


def test_cycle_creates_signals_after_catch_up(rig, calls, sigs):
    order = []
    orig = rig.market.daily_bars
    rig.market.daily_bars = lambda until: order.append(("daily", until)) or orig(until)
    calls_before = list(calls)
    rep = rig.engine.run_daily_cycle()
    assert rep.skipped_reason is None and rep.decision_ns == rig.decision_ns
    assert calls[len(calls_before)] == ("catch_up", rig.decision_ns)
    assert order == [("daily", rig.decision_ns)]
    entries = [s for s in rep.signals if s.action == A.ENTRY]
    assert entries and len(rep.created_signal_ids) == len(entries)
    cards = [m for m in rep.outgoing if m.kind == "card"]
    assert sorted(m.signal_id for m in cards) == sorted(rep.created_signal_ids)
    for m in cards:
        assert m.text.startswith("[PAPER]")
        flat = [b.callback_data for row in m.buttons for b in row]
        assert make_callback_data(CallbackAction.APPROVE, m.signal_id) in flat
        row = db.get_signal(rig.conn, m.signal_id)
        assert row["state"] == S.NEW.value and row["decision_ms"] == ns_to_ms(rig.decision_ns)
        assert row["expires_ms"] == ns_to_ms(rig.decision_ns) + 7200 * 1000
    # Claude 1회, 입력은 수치 JSON
    assert len(rig.analyst.calls) == 1 and rig.analyst.calls[0]["schema"] == "analyst_input_v1"
    an = rig.conn.execute("SELECT * FROM analyses").fetchall()
    assert len(an) == 1 and an[0]["ok"] == 1
    cyc = rig.conn.execute("SELECT * FROM cycles").fetchone()
    assert cyc["status"] == "DONE"


def test_cycle_rerun_is_idempotent(rig):
    rep1 = rig.engine.run_daily_cycle()
    rig.set(rig.decision_ns + 5 * NS_PER_MIN)
    rep2 = rig.engine.run_daily_cycle()
    assert rep2.skipped_reason == "already_done" and rep2.outgoing == []
    n = rig.conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    assert n == len(rep1.created_signal_ids) and len(rig.analyst.calls) == 1


def test_failed_cycle_retry_does_not_duplicate(rig):
    orig = rig.market.daily_bars
    state = {"fail": True}

    def flaky(until):
        if state["fail"]:
            raise MarketDataError("가짜 시세 이상")
        return orig(until)

    rig.market.daily_bars = flaky
    rep = rig.engine.run_daily_cycle()
    assert rep.skipped_reason == "data_error" and [m.kind for m in rep.outgoing] == ["alert"]
    assert rig.conn.execute("SELECT status FROM cycles").fetchone()[0] == "FAILED"
    assert rig.conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 0
    state["fail"] = False
    rep = rig.engine.run_daily_cycle()
    assert rep.skipped_reason is None and rep.created_signal_ids
    assert rig.conn.execute("SELECT status FROM cycles").fetchone()[0] == "DONE"


def test_before_decision_time_rejected(rig):
    rig.set(rig.decision_ns - DELAY + 30 * NS_PER_SEC)     # 00:00:30 UTC
    rep = rig.engine.run_daily_cycle()
    assert rep.skipped_reason == "too_early"
    assert rig.conn.execute("SELECT COUNT(*) FROM cycles").fetchone()[0] == 0


def test_paused_signals_skipped_without_claude(rig):
    rig.engine.pause("OPERATOR")
    rep = rig.engine.run_daily_cycle()
    assert rep.created_signal_ids and not [m for m in rep.outgoing if m.kind == "card"]
    for sid in rep.created_signal_ids:
        row = db.get_signal(rig.conn, sid)
        assert row["state"] == S.SKIPPED.value and row["state_reason"] == "paused"
    assert rig.analyst.calls == []


def test_late_start_skipped(rig):
    rig.set(rig.decision_ns + 7200 * NS_PER_SEC)            # 승인 창이 이미 닫힘
    rep = rig.engine.run_daily_cycle()
    assert rep.created_signal_ids
    for sid in rep.created_signal_ids:
        row = db.get_signal(rig.conn, sid)
        assert row["state"] == S.SKIPPED.value and row["state_reason"] == "late_start"
    assert not [m for m in rep.outgoing if m.kind == "card"]


@pytest.mark.parametrize("bad", ["result", "raise"])
def test_claude_failure_still_sends_card(conn, trend_market_small, sigs, calls, tmp_path, bad):
    class Broken:
        calls = []

        def analyze(self, payload):
            if bad == "raise":
                raise TimeoutError("hang")
            return AnalystResult(ok=False, status="timeout", prompt_version="analyst_v1", model="claude-opus-5-5",
                                 input_json="{}", error="timeout")

    r = Rig(conn, trend_market_small, entry_day(sigs), analyst=Broken(), tmp_path=tmp_path)
    rep = r.engine.run_daily_cycle()
    cards = [m for m in rep.outgoing if m.kind == "card"]
    assert cards and all("Claude 분석 없음" in m.text for m in cards)
    an = conn.execute("SELECT * FROM analyses").fetchone()
    assert an["ok"] == 0 and an["status"] == ("error" if bad == "raise" else "timeout")
    for m in cards:
        assert r.engine.mark_card_sent(m.signal_id, 42)
        assert db.get_signal(conn, m.signal_id)["analysis_id"] == an["analysis_id"]


def test_mark_card_sent_records_and_rejects_after_expiry(rig):
    rep = rig.engine.run_daily_cycle()
    sid = rep.created_signal_ids[0]
    assert rig.engine.mark_card_sent(sid, 777)
    row = db.get_signal(rig.conn, sid)
    assert row["state"] == S.CARD_SENT.value and row["tg_message_id"] == 777
    assert row["card_sent_ms"] == ns_to_ms(rig.decision_ns) and row["analysis_id"] is not None
    assert not rig.engine.mark_card_sent(sid, 778)          # 두 번째는 거부
    if len(rep.created_signal_ids) > 1:
        other = rep.created_signal_ids[1]
        rig.set(rig.decision_ns + 7200 * NS_PER_SEC)
        assert not rig.engine.mark_card_sent(other, 779)


def test_send_failure_retry_via_unsent_cards(rig):
    rep = rig.engine.run_daily_cycle()                      # 카드를 보내지 않음(전송 실패 가정)
    rig.set(rig.decision_ns + NS_PER_MIN)
    out = rig.engine.tick()
    retry = [m for m in out if m.kind == "card"]
    assert sorted(m.signal_id for m in retry) == sorted(rep.created_signal_ids)
    for m in retry:
        assert rig.engine.mark_card_sent(m.signal_id, 1)
    assert not [m for m in rig.engine.tick() if m.kind == "card"]


def test_unsent_cards_wait_while_cycle_running(rig):
    rep = rig.engine.run_daily_cycle()
    day = rig.conn.execute("SELECT cycle_day FROM cycles").fetchone()[0]
    rig.conn.execute("UPDATE cycles SET status = 'RUNNING' WHERE cycle_day = ?", (day,))
    assert rig.engine.unsent_cards() == []
    rig.conn.execute("UPDATE cycles SET status = 'DONE' WHERE cycle_day = ?", (day,))
    assert len(rig.engine.unsent_cards()) == len(rep.created_signal_ids)


def test_new_signal_expires_if_never_sent(rig):
    rep = rig.engine.run_daily_cycle()
    rig.set(rig.decision_ns + 7200 * NS_PER_SEC)
    out = rig.engine.tick()
    assert not [m for m in out if m.kind == "card"]
    assert all(rig.state(s) == S.EXPIRED.value for s in rep.created_signal_ids)


def test_clock_skew_holds_cycle(conn, trend_market_small, sigs, calls, tmp_path):
    r = Rig(conn, trend_market_small, entry_day(sigs), tmp_path=tmp_path)
    state = {"bad": True}

    def check_clock():
        if state["bad"]:
            raise MarketDataError("시계 오차 5000 ms > 허용 1000 ms")
        return 3

    r.market.check_clock = check_clock
    rep = r.engine.run_daily_cycle()
    assert rep.skipped_reason == "clock_skew" and rep.outgoing[0].kind == "alert"
    assert conn.execute("SELECT status FROM cycles").fetchone()[0] == "FAILED"
    assert conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 0
    assert ("catch_up", r.decision_ns) not in calls
    state["bad"] = False
    rep = r.engine.run_daily_cycle()
    assert rep.skipped_reason is None and rep.created_signal_ids


def test_engine_rejects_mode_mismatch(replay_conn, trend_market_small, tmp_path):
    cfg = make_config(tmp_path)
    clock = FakeClock(0)
    with pytest.raises(ValueError):
        Engine(replay_conn, cfg, frame_market_from(trend_market_small, clock), None, clock)


# ---------------------------------------------------------------------------
# 버튼 전이 (2단계 승인)
# ---------------------------------------------------------------------------


@pytest.fixture
def sent(rig):
    rep = run_and_send(rig)
    return rep.created_signal_ids[0]


def test_two_step_approval(rig, sent):
    rig.set(rig.decision_ns + 10 * NS_PER_MIN)
    assert not rig.engine.confirm(sent)                     # 승인 전 확인은 무효
    assert rig.engine.request_confirm(sent)
    assert rig.state(sent) == S.CONFIRM_PENDING.value
    assert not rig.engine.request_confirm(sent)             # 중복 클릭
    rig.set(rig.decision_ns + 10 * NS_PER_MIN + 59 * NS_PER_SEC)
    assert rig.engine.confirm(sent)
    row = db.get_signal(rig.conn, sent)
    assert row["state"] == S.APPROVED.value
    assert row["approved_ms"] == ns_to_ms(rig.clock.now_ns())
    assert row["approval_latency_ms"] == (10 * 60 + 59) * 1000
    assert not rig.engine.confirm(sent) and not rig.engine.pass_signal(sent)


def test_confirm_after_60s_reverts_to_card_sent(rig, sent):
    rig.set(rig.decision_ns + NS_PER_MIN)
    assert rig.engine.request_confirm(sent)
    rig.set(rig.decision_ns + 2 * NS_PER_MIN + NS_PER_SEC)  # 61초 뒤
    assert not rig.engine.confirm(sent)
    row = db.get_signal(rig.conn, sent)
    assert row["state"] == S.CARD_SENT.value and row["state_reason"] == "confirm_timeout"
    assert rig.engine.request_confirm(sent)                 # 승인 창 안이면 다시 가능
    assert rig.engine.confirm(sent)


def test_cancel_and_pass(rig, sent):
    assert rig.engine.request_confirm(sent)
    assert rig.engine.cancel_confirm(sent)
    assert rig.state(sent) == S.CARD_SENT.value
    assert not rig.engine.cancel_confirm(sent)
    assert rig.engine.pass_signal(sent)
    assert rig.state(sent) == S.PASSED.value
    assert not rig.engine.request_confirm(sent)
    assert not rig.engine.request_confirm("AAAAAAAAAAAAAAAA")  # 없는 신호


def test_clicks_after_expiry_expire_signal(rig, sent):
    assert rig.engine.request_confirm(sent)
    rig.set(rig.decision_ns + 7200 * NS_PER_SEC)             # 11:01 KST 정각 = 만료
    assert not rig.engine.confirm(sent)
    assert rig.state(sent) == S.EXPIRED.value
    assert not rig.engine.pass_signal(sent)


def test_tick_expires_and_edits_card(rig, sent):
    rig.set(rig.decision_ns + 7200 * NS_PER_SEC - 1)
    assert not [m for m in rig.engine.tick() if m.kind == "expired"]
    rig.set(rig.decision_ns + 7200 * NS_PER_SEC)
    out = rig.engine.tick()
    exp = [m for m in out if m.kind == "expired"]
    assert rig.state(sent) == S.EXPIRED.value
    assert any(m.signal_id == sent and m.edit_message_id is not None and m.buttons == () for m in exp)


def test_tick_confirm_timeout_restores_card(rig, sent):
    assert rig.engine.request_confirm(sent)
    rig.set(rig.decision_ns + 61 * NS_PER_SEC)
    out = rig.engine.tick()
    assert rig.state(sent) == S.CARD_SENT.value
    restore = [m for m in out if m.signal_id == sent and m.kind == "card"]
    assert len(restore) == 1 and restore[0].edit_message_id == db.get_signal(rig.conn, sent)["tg_message_id"]
    assert restore[0].buttons


def test_tick_calls_paper_fill_then_monitor(rig, calls):
    rig.set(rig.decision_ns + 3 * NS_PER_MIN)
    del calls[:]
    rig.engine.tick()
    assert calls == [("fill", rig.decision_ns + 3 * NS_PER_MIN), ("monitor", rig.decision_ns + 3 * NS_PER_MIN)]


def test_tick_market_error_alerts_once(rig, monkeypatch):
    def boom(*a):
        raise MarketDataError("down")

    monkeypatch.setattr(paper, "fill_approved", boom)
    a1 = [m for m in rig.engine.tick() if m.kind == "alert"]
    a2 = [m for m in rig.engine.tick() if m.kind == "alert"]
    assert len(a1) == 1 and a2 == []


def test_concurrent_confirm_only_one_wins(rig, sent):
    assert rig.engine.request_confirm(sent)
    results = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        results.append(rig.engine.confirm(sent))

    ts = [threading.Thread(target=worker) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert results.count(True) == 1


# ---------------------------------------------------------------------------
# 일시정지·청산 예약·문구
# ---------------------------------------------------------------------------


def _fill(conn, sid, entry_ms, price=30000.0):
    for a, b, f in ((S.NEW, S.CARD_SENT, None), (S.CARD_SENT, S.CONFIRM_PENDING, None),
                    (S.CONFIRM_PENDING, S.APPROVED, dict(approved_ms=entry_ms))):
        if db.get_signal(conn, sid)["state"] == a.value:
            assert db.transition_signal(conn, sid, a, b, now_ms=entry_ms, actor="ENGINE", fields=f)
    return db.open_position(conn, signal_id=sid, entry_ms=entry_ms, entry_price=price, qty=0.01, stop=price - 3000,
                            risk_per_unit=3050.0, entry_fee=15.0, entry_slippage=6.0, active_from_ms=entry_ms,
                            now_ms=entry_ms)


def test_pause_skips_pending_and_approved_but_keeps_positions(rig, conn):
    rep = run_and_send(rig)
    ids = rep.created_signal_ids
    assert rig.engine.request_confirm(ids[0])
    assert rig.engine.confirm(ids[0])                        # APPROVED(체결 전)
    skipped = rig.engine.pause("TELEGRAM_USER")
    assert sorted(skipped) == sorted(ids)
    assert all(rig.state(s) == S.SKIPPED.value for s in ids)
    assert db.is_paused(conn)
    assert rig.engine.pause("TELEGRAM_USER") == []
    assert rig.engine.resume("TELEGRAM_USER") and not db.is_paused(conn)
    assert not rig.engine.resume("TELEGRAM_USER")


def test_pause_does_not_touch_filled(rig, conn):
    rep = run_and_send(rig)
    sid = rep.created_signal_ids[0]
    pid = _fill(conn, sid, ns_to_ms(rig.decision_ns) + 30 * 60_000)
    assert pid is not None
    rig.engine.pause("OPERATOR")
    assert rig.state(sid) == S.FILLED.value
    assert db.get_position(conn, pid)["state"] == "OPEN"


def test_exit_signal_schedules_trend_exit(conn, trend_market_small, sigs, calls, tmp_path):
    daily, s = sigs
    t_entry = entry_day(sigs)
    t_exit = int(np.flatnonzero(s[20].long_exit[t_entry + 1:])[0]) + t_entry + 1
    r = Rig(conn, trend_market_small, t_entry, tmp_path=tmp_path)
    rep = run_and_send(r)
    sid20 = next(x for x in rep.created_signal_ids if db.get_signal(conn, x)["subsystem_n"] == 20)
    for x in rep.created_signal_ids:
        if x != sid20:
            r.engine.pass_signal(x)
    pid = _fill(conn, sid20, ns_to_ms(r.decision_ns) + 30 * 60_000)
    # 청산 신호 전날까지는 HOLD
    for t in range(t_entry + 1, t_exit + 1):
        r.set(int(daily.decision_ns[t]))
        rep = r.engine.run_daily_cycle()
        s20 = rep.signals[0]
        assert s20.n == 20
        if t < t_exit:
            assert s20.action == A.HOLD and rep.exit_position_ids == []
    assert s20.action == A.EXIT and rep.exit_position_ids == [pid]
    pos = db.get_position(conn, pid)
    assert pos["exit_due_ms"] == ns_to_ms(int(daily.decision_ns[t_exit])) + 30 * 60_000
    assert pos["exit_signal_close_ms"] == ns_to_ms(int(daily.close_ns[t_exit]))


def test_status_and_positions_text(rig, conn):
    rep = run_and_send(rig)
    txt = rig.engine.status_text()
    assert txt.startswith("[PAPER]") and "E0-L-ENS" in txt and "KST" in txt
    assert "열린 모의 포지션 없음" in rig.engine.positions_text()
    _fill(conn, rep.created_signal_ids[0], ns_to_ms(rig.decision_ns) + 30 * 60_000)
    ptxt = rig.engine.positions_text()
    assert "1개" in ptxt and "30,000.0" in ptxt
    rig.engine.pause("OPERATOR")
    assert "일시정지" in rig.engine.status_text()


def test_fallback_card_has_buttons_and_no_analysis_marker(rig):
    rep = rig.engine.run_daily_cycle()
    row = db.get_signal(rig.conn, rep.created_signal_ids[0])
    msg = fallback_card(row, None, rig.cfg)
    assert msg.kind == "card" and msg.signal_id == row["signal_id"] and "Claude 분석 없음" in msg.text
    assert len(msg.buttons[0]) == 3


def test_render_error_falls_back(conn, trend_market_small, sigs, calls, tmp_path):
    r = Rig(conn, trend_market_small, entry_day(sigs), tmp_path=tmp_path)

    def broken(*a):
        raise RuntimeError("render bug")

    r.engine.render_card = broken
    rep = r.engine.run_daily_cycle()
    assert [m for m in rep.outgoing if m.kind == "card"]


# ---------------------------------------------------------------------------
# 실제 paper와 한 바퀴 (paper 구현 뒤에만)
# ---------------------------------------------------------------------------


def _paper_ready() -> bool:
    try:
        paper.position_size(10_000.0, 30_000.0, 3_000.0)
        return True
    except NotImplementedError:
        return False


@pytest.mark.skipif(not _paper_ready(), reason="paper 모듈 구현 전")
def test_replay_loop_with_real_paper_auto_approve(replay_conn, trend_market_small, sigs, tmp_path):
    """재생: 매일 사이클 → 카드 전송 → 판단 + 30분 자동 확인 → tick. 체결된 거래 수가 백테스트와 같아야 한다."""
    from backtest.types import ExecArrays, FundingArrays

    daily, _ = sigs
    cfg = make_config(tmp_path, mode="replay", **{"telegram.enabled": False, "claude.enabled": False})
    clock = FakeClock(int(daily.decision_ns[0]))
    eng = Engine(replay_conn, cfg, frame_market_from(trend_market_small, clock), None, clock)
    for t in range(len(daily)):
        dec = int(daily.decision_ns[t])
        clock.set(dec)
        rep = eng.run_daily_cycle()
        for m in rep.outgoing:
            if m.kind == "card":
                eng.mark_card_sent(m.signal_id, 1)
        clock.set(dec + 29 * NS_PER_MIN)
        for sig in db.signals_in_states(replay_conn, [S.CARD_SENT]):
            if sig["decision_ms"] == ns_to_ms(dec):
                assert eng.request_confirm(sig["signal_id"])
        clock.set(dec + 30 * NS_PER_MIN)
        for sig in db.signals_in_states(replay_conn, [S.CONFIRM_PENDING]):
            assert eng.confirm(sig["signal_id"])
        if t + 1 < len(daily):
            clock.set(int(daily.decision_ns[t + 1]) - DELAY)
            eng.tick()
    trades, _ = TR.run_trend_combo(daily, TR.TrendConfig("E0", "L"),
                                   ExecArrays.from_frame(trend_market_small.exec_bars),
                                   FundingArrays.from_frame(trend_market_small.funding))
    n_bt = len(TR.filled(trades))
    n_bot = replay_conn.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0]
    assert n_bot == n_bt
