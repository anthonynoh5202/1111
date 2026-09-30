"""적대적 검토(정확성 감사) — 재현 시험. 소스는 수정하지 않는다.

xfail(strict=True) = 확인된 결함(원하는 동작을 단언; 고쳐지면 XPASS로 알려 준다).
수정 담당 반영: R-1~R-4 수정 후 xfail 표시를 지웠다(이제 회귀 시험).
일반 시험 = 검토 중 확인한 올바른 동작(회귀 방지).

실행: .venv/bin/python -m pytest bot/tests/review_correctness_test.py -q -rxX
"""
from __future__ import annotations

import httpx
import numpy as np
import pandas as pd
import pytest

from backtest import trend as TR
from backtest.types import ExecArrays, FundingArrays, records_frame
from bot import db
from bot import main as M
from bot.config import MarketDataConfig
from bot.engine import Engine
from bot.marketdata import LiveBinance, MarketDataError, Replay
from bot.tests.conftest import FrameMarket, insert_test_signal, make_config
from bot.types import NS_PER_MIN, NS_PER_MS, Actor, FakeClock, Mode, SignalState as S, ns_to_ms


def _replay_cfg(tmp_path):
    return make_config(tmp_path, mode="replay", db_path=":memory:",
                       **{"telegram.enabled": False, "claude.enabled": False})


def _bt_trades(market) -> pd.DataFrame:
    daily = TR.DailyData.from_frame(market.bars["1d"])
    trades, _ = TR.run_trend_combo(daily, TR.TrendConfig("E0", "L"), ExecArrays.from_frame(market.exec_bars),
                                   FundingArrays.from_frame(market.funding))
    f = TR.filled(trades)
    df = records_frame(f)
    df.insert(0, "n", [t.meta.get("n") for t in f])
    return df


def _run(tmp_path, market, decisions):
    cfg = _replay_cfg(tmp_path)
    clock = FakeClock(decisions[0])
    conn = db.connect(":memory:", mode=Mode.REPLAY, now_ms=ns_to_ms(decisions[0]))
    mk = Replay.from_frames(market.bars["1d"], market.exec_bars, market.funding, clock)
    eng = Engine(conn, cfg, mk, None, clock)
    M.run_replay_loop(eng, clock, M.RecordingTransport(), decisions, auto_approve_latency_min=30,
                      end_ns=int(market.bars["1d"]["close_ns"].iloc[-1]))
    return conn


# ---------------------------------------------------------------------------
# R-1 판단 하루를 놓치면(봇 정지·하루 종일 사이클 실패) 추세 청산 신호가 영구히 사라진다
# ---------------------------------------------------------------------------


def test_missed_exit_day_is_recovered(tmp_path, trend_market_small):
    bt = _bt_trades(trend_market_small)
    tr = bt[bt["exit_reason"] == "trend"].iloc[0]
    exit_decision = int(tr["exit_time_ns"]) - 30 * NS_PER_MIN        # 1분봉 시장: 청산 봉 = 판단 + 30분
    cfg = _replay_cfg(tmp_path)
    decisions = M.replay_decision_times(cfg, trend_market_small.bars["1d"]["close_ns"].to_numpy())
    assert exit_decision in decisions
    decisions = [d for d in decisions if d != exit_decision]         # 그날 하루 봇이 꺼져 있었다
    conn = _run(tmp_path, trend_market_small, decisions)
    p = conn.execute("SELECT * FROM paper_positions WHERE entry_ms = ? AND subsystem_n = ?",
                     (int(tr["entry_time_ns"]) // NS_PER_MS, int(tr["n"]))).fetchone()
    assert p is not None
    # 원하는 동작: 다음 날 복구 때라도 청산(늦어도 하루 안). 실제: 다음 청산 신호나 손절까지 계속 보유.
    assert p["exit_ms"] is not None and int(p["exit_ms"]) * NS_PER_MS <= int(tr["exit_time_ns"]) + 86_400 * 10**9 + \
        30 * NS_PER_MIN, f"청산 누락: exit_ms={p['exit_ms']} reason={p['exit_reason']}"


# ---------------------------------------------------------------------------
# R-2 사이클이 한 번 실패한 뒤(재시도 사이) tick이 커서를 판단 시각 뒤로 옮기면,
#     판단 뒤 손절이 신호 계산에 섞여 같은 날 재진입 신호가 생긴다(백테스트는 다음 날부터 검사: T-2)
# ---------------------------------------------------------------------------


def _find_breakout_day(market):
    daily = TR.DailyData.from_frame(market.bars["1d"])
    sig = TR.channel_signals(daily, 20)
    m = market.exec_bars
    for d in np.flatnonzero(sig.long_entry):
        dec = int(daily.decision_ns[d])
        prev_bar = m[m["open_ns"] == dec - NS_PER_MIN]
        bar = m[m["open_ns"] == dec]
        if len(prev_bar) and len(bar) and float(bar["low"].iloc[0]) + 1.0 < float(prev_bar["open"].iloc[0]):
            return dec, float(prev_bar["open"].iloc[0]), float(bar["low"].iloc[0])
    raise AssertionError("조건에 맞는 날 없음")


def _setup_open_position(conn, dec, entry_price, stop):
    """N20 포지션: 판단 1분 전 체결, 커서 = 판단 시각(그 전 봉은 이미 감시함)."""
    sid = insert_test_signal(conn, n=20, decision_ns=dec - 3 * 86_400 * 10**9, mode=Mode.REPLAY,
                             close=entry_price, entry_level=entry_price - 10, exit_level=entry_price - 5000,
                             atr20=(entry_price - stop) / 2)
    now = ns_to_ms(dec)
    db.transition_signal(conn, sid, S.NEW, S.CARD_SENT, now_ms=now, actor=Actor.ENGINE)
    db.transition_signal(conn, sid, S.CARD_SENT, S.CONFIRM_PENDING, now_ms=now, actor=Actor.ENGINE)
    db.transition_signal(conn, sid, S.CONFIRM_PENDING, S.APPROVED, now_ms=now, actor=Actor.ENGINE,
                         fields=dict(approved_ms=now - 2 * 60_000))
    pid = db.open_position(conn, signal_id=sid, entry_ms=now - 60_000, entry_price=entry_price, qty=0.01,
                           stop=stop, risk_per_unit=entry_price - stop, entry_fee=0.0, entry_slippage=0.0,
                           active_from_ms=now - 2 * 60_000, now_ms=now)
    db.advance_cursor(conn, pid, now, now_ms=now)
    return pid


def _n20_signals_at(conn, dec):
    return conn.execute("SELECT * FROM signals WHERE subsystem_n = 20 AND decision_ms = ?",
                        (ns_to_ms(dec),)).fetchall()


def test_on_time_cycle_holds_position_no_same_day_entry(tmp_path, trend_market_small):
    """대조군: 판단 시각에 제때 돈 사이클 — 포지션 보유(HOLD), 같은 날 N20 신호 없음(백테스트와 같음)."""
    dec, entry, low = _find_breakout_day(trend_market_small)
    cfg = _replay_cfg(tmp_path)
    clock = FakeClock(dec)
    conn = db.connect(":memory:", mode=Mode.REPLAY, now_ms=ns_to_ms(dec))
    eng = Engine(conn, cfg, FrameMarket(trend_market_small.bars["1d"], trend_market_small.exec_bars,
                                        trend_market_small.funding, clock), None, clock)
    _setup_open_position(conn, dec, entry, low + 0.5)
    rep = eng.run_daily_cycle()
    assert rep.skipped_reason is None
    assert _n20_signals_at(conn, dec) == []


class _FailOnceDaily(FrameMarket):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fail = True

    def daily_bars(self, until_ns):
        if self.fail:
            self.fail = False
            raise MarketDataError("일시적 429")
        return super().daily_bars(until_ns)


def test_retried_cycle_ignores_post_decision_stop(tmp_path, trend_market_small):
    dec, entry, low = _find_breakout_day(trend_market_small)
    cfg = _replay_cfg(tmp_path)
    clock = FakeClock(dec)
    conn = db.connect(":memory:", mode=Mode.REPLAY, now_ms=ns_to_ms(dec))
    mk = _FailOnceDaily(trend_market_small.bars["1d"], trend_market_small.exec_bars, trend_market_small.funding,
                        clock)
    eng = Engine(conn, cfg, mk, None, clock)
    pid = _setup_open_position(conn, dec, entry, low + 0.5)
    # paper_loop 한 바퀴: 사이클(실패) → tick
    assert eng.run_daily_cycle().skipped_reason == "data_error"
    eng.tick()
    # 다음 바퀴(2분 뒤): tick이 00:01~00:02 봉 손절을 먼저 처리한 상태에서 사이클 재시도
    clock.set(dec + 2 * NS_PER_MIN)
    eng.tick()
    assert db.get_position(conn, pid)["state"] == "CLOSED"            # 손절은 판단 시각 뒤(00:02 마감)
    rep = eng.run_daily_cycle()
    assert rep.skipped_reason is None
    # 백테스트 T-2: 손절 마감(00:02) > 판단(00:01) → 다음 날부터 진입 검사. 그날 N20 신호가 있으면 안 된다.
    assert _n20_signals_at(conn, dec) == []


# ---------------------------------------------------------------------------
# R-3 실패한 사이클은 1분마다 재시도되고 매번 경고를 만든다(텔레그램 폭주)
# ---------------------------------------------------------------------------


class _AlwaysFailDaily(FrameMarket):
    def daily_bars(self, until_ns):
        raise MarketDataError("HTTP 503")


def test_failed_cycle_alert_is_not_repeated_every_retry(tmp_path, trend_market_small):
    dec, _, _ = _find_breakout_day(trend_market_small)
    cfg = _replay_cfg(tmp_path)
    clock = FakeClock(dec)
    conn = db.connect(":memory:", mode=Mode.REPLAY, now_ms=ns_to_ms(dec))
    eng = Engine(conn, cfg, _AlwaysFailDaily(trend_market_small.bars["1d"], trend_market_small.exec_bars,
                                             trend_market_small.funding, clock), None, clock)
    alerts = 0
    for i in range(5):
        clock.set(dec + i * NS_PER_MIN)
        alerts += sum(1 for m in eng.run_daily_cycle().outgoing if m.kind == "alert")
    assert alerts <= 1, f"경고 {alerts}건"


# ---------------------------------------------------------------------------
# R-4 LiveBinance 1분봉 응답에 거래소 빈 구간이 하나라도 있으면 커서 이후 모든 요청이 영구 실패
# ---------------------------------------------------------------------------


def _live_with_rows(rows, now_ns):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return LiveBinance(MarketDataConfig(max_retries=0), FakeClock(now_ns), client, sleep=lambda s: None)


def test_live_minute_gap_does_not_freeze_monitoring():
    t0 = 1_725_000_000_000 // 60_000 * 60_000
    rows = []
    for k in list(range(0, 5)) + list(range(8, 12)):                    # 5~7분 봉 없음(거래소 점검)
        o = t0 + k * 60_000
        rows.append([o, "100", "101", "99", "100.5", "1", o + 59_999, "0", 0, "0", "0", "0"])
    md = _live_with_rows(rows, (t0 + 12 * 60_000) * NS_PER_MS)
    bars = md.minute_bars(t0 * NS_PER_MS, (t0 + 12 * 60_000) * NS_PER_MS)
    assert len(bars) == 9


# ---------------------------------------------------------------------------
# 확인한 올바른 동작 (회귀 방지)
# ---------------------------------------------------------------------------


def test_restart_during_running_cycle_no_duplicate_signal(tmp_path, trend_market_small):
    """사이클 도중 죽어 RUNNING으로 남아도, 재시작 뒤 사이클은 신호를 중복 만들지 않는다."""
    daily = TR.DailyData.from_frame(trend_market_small.bars["1d"])
    sig = TR.channel_signals(daily, 20)
    d = int(np.flatnonzero(sig.long_entry)[0])
    dec = int(daily.decision_ns[d])
    cfg = _replay_cfg(tmp_path)
    clock = FakeClock(dec)
    conn = db.connect(":memory:", mode=Mode.REPLAY, now_ms=ns_to_ms(dec))
    mk = FrameMarket(trend_market_small.bars["1d"], trend_market_small.exec_bars, trend_market_small.funding, clock)
    e1 = Engine(conn, cfg, mk, None, clock)
    e1.run_daily_cycle()
    n1 = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    assert n1 >= 1
    conn.execute("UPDATE cycles SET status = 'RUNNING'")              # 죽은 것처럼
    clock.set(dec + 5 * NS_PER_MIN)
    e2 = Engine(conn, cfg, mk, None, clock)
    rep = e2.run_daily_cycle()
    assert rep.skipped_reason is None
    assert conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == n1
    assert conn.execute("SELECT status FROM cycles").fetchone()[0] == "DONE"


def test_confirm_window_and_approval_window_boundaries(tmp_path, trend_market_small):
    daily = TR.DailyData.from_frame(trend_market_small.bars["1d"])
    dec = int(daily.decision_ns[150])
    cfg = _replay_cfg(tmp_path)
    clock = FakeClock(dec)
    conn = db.connect(":memory:", mode=Mode.REPLAY, now_ms=ns_to_ms(dec))
    mk = FrameMarket(trend_market_small.bars["1d"], trend_market_small.exec_bars, trend_market_small.funding, clock)
    eng = Engine(conn, cfg, mk, None, clock)
    sid = insert_test_signal(conn, decision_ns=dec, mode=Mode.REPLAY)
    assert eng.mark_card_sent(sid, 1)
    assert eng.request_confirm(sid)
    clock.set(dec + 60 * 10**9)                                       # 정확히 60초: 허용
    assert eng.confirm(sid)
    assert db.get_signal(conn, sid)["approval_latency_ms"] == 60_000
    sid2 = insert_test_signal(conn, n=55, decision_ns=dec, mode=Mode.REPLAY)
    clock.set(dec)
    assert eng.mark_card_sent(sid2, 2)
    clock.set(dec + 7200 * 10**9)                                     # 정확히 2시간: 만료
    assert not eng.request_confirm(sid2)
    assert db.get_signal(conn, sid2)["state"] == "EXPIRED"
