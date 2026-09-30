"""bot/paper.py 시험 — 모의 매매 담당 (DESIGN §3.3~3.4, §6, §10 test_paper).

핵심: 모의 체결·손절·추세 청산·펀딩이 backtest.trend.simulate_trend_trade(E0, market)와 **같은 값**이고,
감시 주기(1분 / 하루 1회)와 무관하다.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backtest import config as C
from backtest import execution as X
from backtest import trend as TR
from backtest import types as BT
from bot import db, paper
from bot import strategy as ST
from bot.tests.conftest import (
    T_DECISION_NS,
    FrameMarket,
    frame_market_from,
    insert_test_signal,
    make_config,
)
from bot.types import (
    MS_PER_DAY,
    NS_PER_DAY,
    NS_PER_MIN,
    NS_PER_SEC,
    Actor,
    FakeClock,
    Mode,
    SignalState,
    ms_to_ns,
    ns_to_ms,
)

S = SignalState
H = 60 * NS_PER_MIN
T0 = T_DECISION_NS - 60 * NS_PER_SEC     # 2024-03-02 00:00 UTC (분 경계)


# ---------------------------------------------------------------------------
# 도우미
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg(tmp_path):
    return make_config(tmp_path)


def minute_frame(opens, highs=None, lows=None, closes=None, start_ns: int = T0) -> pd.DataFrame:
    """start_ns부터 연속 1분봉. 지정 안 한 high/low/close는 open ± 10 / open."""
    o = np.asarray(opens, dtype=np.float64)
    h = o + 10.0 if highs is None else np.asarray(highs, dtype=np.float64)
    lo = o - 10.0 if lows is None else np.asarray(lows, dtype=np.float64)
    c = o if closes is None else np.asarray(closes, dtype=np.float64)
    t = start_ns + np.arange(len(o), dtype=np.int64) * NS_PER_MIN
    return BT.make_bars_frame(t, o, h, lo, c, np.ones(len(o)), NS_PER_MIN)


def funding_frame(times_ns=(), rates=()) -> pd.DataFrame:
    return BT.make_funding_frame(np.asarray(times_ns, dtype=np.int64), np.asarray(rates, dtype=np.float64))


def empty_daily() -> pd.DataFrame:
    e = np.empty(0)
    return BT.make_bars_frame(np.empty(0, dtype=np.int64), e, e, e, e, e, NS_PER_DAY)


def make_market(minute: pd.DataFrame, funding: pd.DataFrame | None = None, now_ns: int | None = None):
    clock = FakeClock(int(minute["close_ns"].iloc[-1]) if now_ns is None else now_ns)
    return FrameMarket(empty_daily(), minute, funding_frame() if funding is None else funding, clock), clock


def approve(conn, *, approved_ns: int, n: int = 20, atr20: float = 1_000.0, decision_ns: int = T_DECISION_NS,
            close: float = 50_000.0) -> str:
    """NEW → CARD_SENT → CONFIRM_PENDING → APPROVED (approved_ms 기록)."""
    sid = insert_test_signal(conn, n=n, decision_ns=decision_ns, atr20=atr20, close=close,
                             approval_window_s=4 * 3600)
    dms = ns_to_ms(decision_ns)
    ams = ns_to_ms(approved_ns)
    assert db.transition_signal(conn, sid, S.NEW, S.CARD_SENT, now_ms=dms, actor=Actor.ENGINE,
                                fields=dict(card_sent_ms=dms, tg_message_id=1))
    assert db.transition_signal(conn, sid, S.CARD_SENT, S.CONFIRM_PENDING, now_ms=ams, actor=Actor.TELEGRAM_USER,
                                fields=dict(confirm_requested_ms=ams, confirm_expires_ms=ams + 60_000))
    assert db.transition_signal(conn, sid, S.CONFIRM_PENDING, S.APPROVED, now_ms=ams, actor=Actor.TELEGRAM_USER,
                                fields=dict(approved_ms=ams, approval_latency_ms=ams - dms))
    return sid


def only_position(conn):
    rows = list(conn.execute("SELECT * FROM paper_positions"))
    assert len(rows) == 1
    return rows[0]


def exec_arrays(minute: pd.DataFrame) -> BT.ExecArrays:
    return BT.ExecArrays.from_frame(minute)


# ---------------------------------------------------------------------------
# 크기
# ---------------------------------------------------------------------------


def test_position_size_risk_and_cap():
    # 위험 기준: 10000 × 0.005 / 500 = 0.1 BTC, 명목 상한 10000 × 0.2 / 50000 = 0.04 → 0.04
    assert paper.position_size(10_000.0, 50_000.0, 500.0) == pytest.approx(0.04)
    # 위험 기준이 더 작음: 10000 × 0.005 / 5000 = 0.01
    assert paper.position_size(10_000.0, 50_000.0, 5_000.0) == pytest.approx(0.01)
    assert paper.position_size(10_000.0, 50_000.0, 5_000.0) * 50_000.0 <= 10_000.0 * TR.NOTIONAL_CAP_PER_SYSTEM


@pytest.mark.parametrize("args", [(0, 1, 1), (1, 0, 1), (1, 1, 0), (1, 1, -2), (1, float("nan"), 1),
                                  (float("inf"), 1, 1)])
def test_position_size_rejects_bad_inputs(args):
    with pytest.raises(ValueError):
        paper.position_size(*args)


# ---------------------------------------------------------------------------
# 체결 봉 선택
# ---------------------------------------------------------------------------


def test_fill_on_exact_minute_boundary(conn, cfg):
    minute = minute_frame([50_000.0 + i for i in range(10)])
    market, clock = make_market(minute)
    approved = T0 + 3 * NS_PER_MIN                    # 정확히 분 경계 → 그 봉
    sid = approve(conn, approved_ns=approved)
    msgs = paper.fill_approved(conn, cfg, market, clock.now_ns())
    assert [m.kind for m in msgs] == ["fill"]
    p = only_position(conn)
    assert p["entry_ms"] == ns_to_ms(approved)
    assert p["entry_price"] == 50_003.0
    assert p["active_from_ms"] == ns_to_ms(approved)
    assert db.get_signal(conn, sid)["state"] == S.FILLED.value


def test_fill_one_ns_after_boundary_takes_next_bar(conn, cfg):
    minute = minute_frame([50_000.0 + i for i in range(10)])
    market, clock = make_market(minute)
    approve(conn, approved_ns=T0 + 3 * NS_PER_MIN + NS_PER_MIN // 2)   # 00:03:30 → 00:04 봉
    paper.fill_approved(conn, cfg, market, clock.now_ns())
    p = only_position(conn)
    assert p["entry_ms"] == ns_to_ms(T0 + 4 * NS_PER_MIN)
    assert p["entry_price"] == 50_004.0


def test_fill_waits_until_fill_bar_closed(conn, cfg):
    minute = minute_frame([50_000.0 + i for i in range(10)])
    market, clock = make_market(minute)
    approved = T0 + 3 * NS_PER_MIN + 20 * NS_PER_SEC                    # 체결 봉 00:04, 마감 00:05
    sid = approve(conn, approved_ns=approved)
    assert paper.fill_approved(conn, cfg, market, T0 + 5 * NS_PER_MIN - 1) == []
    assert db.get_signal(conn, sid)["state"] == S.APPROVED.value
    paper.fill_approved(conn, cfg, market, T0 + 5 * NS_PER_MIN)
    assert db.get_signal(conn, sid)["state"] == S.FILLED.value
    assert only_position(conn)["entry_ms"] == ns_to_ms(T0 + 4 * NS_PER_MIN)


def test_fill_numbers_match_strategy_helpers(conn, cfg):
    minute = minute_frame([50_000.0] * 5)
    market, clock = make_market(minute)
    approve(conn, approved_ns=T0, atr20=1_234.5)
    paper.fill_approved(conn, cfg, market, clock.now_ns())
    p = only_position(conn)
    tc = cfg.trend_config()
    stop = ST.protective_stop(50_000.0, 1_234.5, 1, tc)
    assert stop == C.round_price(50_000.0 - 2.0 * 1_234.5)
    assert p["stop"] == stop
    assert p["risk_per_unit"] == ST.risk_per_unit(50_000.0, stop, tc)
    assert p["qty"] == paper.position_size(cfg.paper.equity_usdt, 50_000.0, p["risk_per_unit"])
    assert p["entry_fee"] == pytest.approx(C.FEE_TAKER * 50_000.0)
    assert p["entry_slippage"] == pytest.approx(C.SLIPPAGE * 50_000.0)
    trades = list(conn.execute("SELECT * FROM paper_trades"))
    assert [t["kind"] for t in trades] == ["ENTRY"]


def test_fill_failed_after_grace_when_no_bars(conn, cfg):
    minute = minute_frame([50_000.0] * 3)                                # 00:00~00:03까지만
    approved = T0 + 10 * NS_PER_MIN
    clock = FakeClock(approved + 3 * H)
    market = FrameMarket(empty_daily(), minute, funding_frame(), clock)
    sid = approve(conn, approved_ns=approved)
    first_close = approved + NS_PER_MIN
    assert paper.fill_approved(conn, cfg, market, first_close + paper.FILL_DATA_GRACE_NS - 1) == []
    assert db.get_signal(conn, sid)["state"] == S.APPROVED.value
    msgs = paper.fill_approved(conn, cfg, market, first_close + paper.FILL_DATA_GRACE_NS)
    assert [m.kind for m in msgs] == ["alert"]
    row = db.get_signal(conn, sid)
    assert row["state"] == S.SKIPPED.value and row["state_reason"] == "fill_failed"


def test_fill_ignores_non_approved_and_is_idempotent(conn, cfg):
    minute = minute_frame([50_000.0] * 5)
    market, clock = make_market(minute)
    sid = approve(conn, approved_ns=T0)
    insert_test_signal(conn, n=55)                                       # NEW — 체결 대상 아님
    assert len(paper.fill_approved(conn, cfg, market, clock.now_ns())) == 1
    assert paper.fill_approved(conn, cfg, market, clock.now_ns()) == []
    assert conn.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0] == 1
    assert db.get_signal(conn, sid)["state"] == S.FILLED.value


def test_paused_approved_signal_is_not_filled(conn, cfg):
    minute = minute_frame([50_000.0] * 5)
    market, clock = make_market(minute)
    sid = approve(conn, approved_ns=T0)
    assert db.transition_signal(conn, sid, S.APPROVED, S.SKIPPED, now_ms=ns_to_ms(T0), actor=Actor.ENGINE,
                                reason="paused")
    assert paper.fill_approved(conn, cfg, market, clock.now_ns()) == []
    assert conn.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# 손절·추세 청산 (scan_exit market 규칙과 대조)
# ---------------------------------------------------------------------------


def _open(conn, cfg, minute, approved_ns, atr20=1_000.0, funding=None):
    market, clock = make_market(minute, funding)
    sid = approve(conn, approved_ns=approved_ns, atr20=atr20)
    paper.fill_approved(conn, cfg, market, clock.now_ns())
    return market, clock, sid


def test_stop_on_fill_bar_with_gap_uses_open(conn, cfg):
    # 체결 봉 시가 50000, 손절 48000. 체결 봉 저가 47000 → 체결 봉에서 손절, 가격 min(48000, 50000) = 48000
    minute = minute_frame([50_000.0, 50_000.0, 45_000.0, 50_000.0], lows=[49_990, 47_000, 44_000, 49_990])
    market, clock, sid = _open(conn, cfg, minute, T0 + NS_PER_MIN)
    msgs = paper.monitor(conn, cfg, market, clock.now_ns())
    p = only_position(conn)
    assert [m.kind for m in msgs] == ["exit"]
    assert p["exit_ms"] == ns_to_ms(T0 + NS_PER_MIN) and p["exit_price"] == 48_000.0 and p["exit_reason"] == "stop"
    assert db.get_signal(conn, sid)["state"] == S.CLOSED.value
    j, px, why = X.scan_exit(1, 1, 48_000.0, math.inf, np.iinfo(np.int64).max, "market", exec_arrays(minute))
    assert (j, px, why) == (1, 48_000.0, "stop")


def test_stop_gap_on_later_bar_exits_at_open(conn, cfg):
    minute = minute_frame([50_000.0, 50_000.0, 47_000.0, 50_000.0], lows=[49_990, 49_990, 46_500, 49_990])
    market, clock, _ = _open(conn, cfg, minute, T0)
    paper.monitor(conn, cfg, market, clock.now_ns())
    p = only_position(conn)
    assert p["exit_ms"] == ns_to_ms(T0 + 2 * NS_PER_MIN) and p["exit_price"] == 47_000.0


def test_stop_exact_touch_on_fill_bar(conn, cfg):
    # 체결 봉 시가 자체가 손절 아래일 수는 없다(손절 = 시가 − 2ATR). 대신 손절 가격 = 저가 경계 정확히 닿음 검사.
    minute = minute_frame([50_000.0, 50_000.0], lows=[48_000.0, 49_990])
    market, clock, _ = _open(conn, cfg, minute, T0)
    paper.monitor(conn, cfg, market, clock.now_ns())
    p = only_position(conn)
    assert p["exit_reason"] == "stop" and p["exit_price"] == 48_000.0 and p["exit_ms"] == ns_to_ms(T0)


def test_trend_exit_excludes_fill_bar(conn, cfg):
    minute = minute_frame([50_000.0 + 100 * i for i in range(6)])
    market, clock, _ = _open(conn, cfg, minute, T0 + 2 * NS_PER_MIN)
    pos = only_position(conn)
    # 예정 시각이 체결 봉 시작보다 앞이어도 체결 봉에서는 청산하지 않는다 → 다음 봉 시가
    assert db.set_exit_plan(conn, pos["position_id"], exit_signal_close_ms=ns_to_ms(T0 - H),
                            exit_due_ms=ns_to_ms(T0), now_ms=ns_to_ms(T0))
    paper.monitor(conn, cfg, market, clock.now_ns())
    p = only_position(conn)
    assert p["exit_reason"] == "trend" and p["exit_ms"] == ns_to_ms(T0 + 3 * NS_PER_MIN)
    assert p["exit_price"] == 50_300.0
    assert X.scan_exit(1, 2, p["stop"], math.inf, T0, "market", exec_arrays(minute))[:2] == (3, 50_300.0)


def test_trend_exit_first_bar_at_or_after_due(conn, cfg):
    minute = minute_frame([50_000.0 + 100 * i for i in range(10)])
    market, clock, _ = _open(conn, cfg, minute, T0)
    pos = only_position(conn)
    due = T0 + 5 * NS_PER_MIN + 1                                          # 00:05 + 1ns → 00:06 봉
    db.set_exit_plan(conn, pos["position_id"], exit_signal_close_ms=ns_to_ms(T0), exit_due_ms=ns_to_ms(due) + 1,
                     now_ms=ns_to_ms(T0))
    paper.monitor(conn, cfg, market, clock.now_ns())
    p = only_position(conn)
    assert p["exit_ms"] == ns_to_ms(T0 + 6 * NS_PER_MIN) and p["exit_price"] == 50_600.0


def test_stop_before_due_wins_and_trend_bar_beats_stop(conn, cfg):
    # (a) 예정 전 봉에서 손절 닿음 → 손절
    minute = minute_frame([50_000.0] * 6, lows=[49_990, 49_990, 47_000, 49_990, 40_000, 49_990])
    market, clock, _ = _open(conn, cfg, minute, T0)
    pos = only_position(conn)
    db.set_exit_plan(conn, pos["position_id"], exit_signal_close_ms=ns_to_ms(T0),
                     exit_due_ms=ns_to_ms(T0 + 4 * NS_PER_MIN), now_ms=ns_to_ms(T0))
    paper.monitor(conn, cfg, market, clock.now_ns())
    p = only_position(conn)
    assert p["exit_reason"] == "stop" and p["exit_ms"] == ns_to_ms(T0 + 2 * NS_PER_MIN)
    # (b) 예정 봉에서 손절도 닿으면 추세 청산(시가)이 먼저 — scan_exit의 시간 청산 우선과 같다
    c2 = db.connect(":memory:", mode=Mode.PAPER, now_ms=ns_to_ms(T0))
    minute2 = minute_frame([50_000.0] * 6, lows=[49_990, 49_990, 49_990, 49_990, 40_000, 49_990])
    market2, clock2, _ = _open(c2, cfg, minute2, T0)
    pos2 = only_position(c2)
    db.set_exit_plan(c2, pos2["position_id"], exit_signal_close_ms=ns_to_ms(T0),
                     exit_due_ms=ns_to_ms(T0 + 4 * NS_PER_MIN), now_ms=ns_to_ms(T0))
    paper.monitor(c2, cfg, market2, clock2.now_ns())
    p2 = only_position(c2)
    assert p2["exit_reason"] == "trend" and p2["exit_ms"] == ns_to_ms(T0 + 4 * NS_PER_MIN)
    assert p2["exit_price"] == 50_000.0
    assert X.scan_exit(1, 0, p2["stop"], math.inf, T0 + 4 * NS_PER_MIN, "market",
                       exec_arrays(minute2))[2] == "time"
    c2.close()


def test_monitor_only_uses_closed_bars_and_advances_cursor(conn, cfg):
    minute = minute_frame([50_000.0] * 10)
    market, clock, _ = _open(conn, cfg, minute, T0)
    paper.monitor(conn, cfg, market, T0 + 4 * NS_PER_MIN + 30 * NS_PER_SEC)
    p = only_position(conn)
    assert p["last_bar_close_ms"] == ns_to_ms(T0 + 4 * NS_PER_MIN)          # 00:04 봉은 아직 미마감
    assert all(u <= clock.now_ns() for kind, _, u in market.calls)
    paper.monitor(conn, cfg, market, T0 + 4 * NS_PER_MIN + 30 * NS_PER_SEC)  # 같은 시각 재호출 = 변화 없음
    assert only_position(conn)["last_bar_close_ms"] == ns_to_ms(T0 + 4 * NS_PER_MIN)
    paper.monitor(conn, cfg, market, clock.now_ns())
    assert only_position(conn)["last_bar_close_ms"] == ns_to_ms(T0 + 10 * NS_PER_MIN)


# ---------------------------------------------------------------------------
# 펀딩
# ---------------------------------------------------------------------------


def test_funding_window_boundaries(conn, cfg):
    # 확인 00:02:30 → 체결 봉 00:03 (f_start = min(00:03, 00:02:30) = 00:02:30)
    # 펀딩: 00:02:30(= f_start, 제외) · 00:02:45(체결 전, 포함 — 00:02 봉 시가) · 00:05(포함) ·
    #       00:08(= 청산 봉 시작, 포함) · 00:08:30(청산 봉 안쪽, 제외)
    opens = [50_000.0 + 10 * i for i in range(12)]
    lows = [o - 5 for o in opens]
    lows[8] = 40_000.0                                                    # 00:08 봉 손절
    minute = minute_frame(opens, lows=lows)
    approved = T0 + 2 * NS_PER_MIN + 30 * NS_PER_SEC
    ft = [approved, T0 + 2 * NS_PER_MIN + 45 * NS_PER_SEC, T0 + 5 * NS_PER_MIN, T0 + 8 * NS_PER_MIN,
          T0 + 8 * NS_PER_MIN + 30 * NS_PER_SEC]
    fr = [0.01, 0.001, 0.002, -0.0005, 0.03]
    funding = funding_frame(ft, fr)
    market, clock, _ = _open(conn, cfg, minute, approved, funding=funding)
    paper.monitor(conn, cfg, market, clock.now_ns())
    p = only_position(conn)
    assert p["exit_ms"] == ns_to_ms(T0 + 8 * NS_PER_MIN)
    rows = list(conn.execute("SELECT ts_ms, price, funding, rate FROM paper_trades WHERE kind='FUNDING' ORDER BY ts_ms"))
    assert [r["ts_ms"] for r in rows] == [ns_to_ms(t) for t in ft[1:4]]
    assert [r["price"] for r in rows] == [opens[2], opens[5], opens[8]]
    expect = 0.001 * opens[2] + 0.002 * opens[5] + (-0.0005) * opens[8]
    assert p["funding"] == pytest.approx(expect, rel=1e-12)
    # 백테스트 함수와 같은 값
    xb, fa = exec_arrays(minute), BT.FundingArrays.from_frame(funding)
    f_start = int(X.funding_start("market", T0 + 3 * NS_PER_MIN, approved))
    assert p["funding"] == pytest.approx(X.funding_cost(1, f_start, T0 + 8 * NS_PER_MIN, xb, fa), rel=1e-12)
    assert p["net_pnl"] == pytest.approx(p["gross_pnl"] - p["fees"] - p["slippage"] - p["funding"], rel=1e-12)


def test_funding_not_charged_twice_across_calls(conn, cfg):
    minute = minute_frame([50_000.0] * 30)
    ft = [T0 + k * 5 * NS_PER_MIN for k in range(1, 6)]
    market, clock, _ = _open(conn, cfg, minute, T0, funding=funding_frame(ft, [0.0001] * 5))
    for t in range(T0 + NS_PER_MIN, clock.now_ns() + 1, NS_PER_MIN // 3):
        paper.monitor(conn, cfg, market, t)
    n = conn.execute("SELECT COUNT(*) FROM paper_trades WHERE kind='FUNDING'").fetchone()[0]
    assert n == 5
    assert only_position(conn)["funding"] == pytest.approx(5 * 0.0001 * 50_000.0)


# ---------------------------------------------------------------------------
# 합성 시장: 백테스트 simulate_trend_trade와 거래 단위 대조 + 감시 주기 무관
# ---------------------------------------------------------------------------


def _bt_trades(market):
    daily = TR.DailyData.from_frame(market.bars["1d"])
    xb, fa = market.exec_arrays(), market.funding_arrays()
    trades, _ = TR.run_trend_combo(daily, TR.TrendConfig("E0", "L"), xb, fa)
    return [t for t in TR.filled(trades) if t.exit_reason in ("stop", "trend")]


def _schedule(t, kind, end: int, due: int | None) -> list[int]:
    """tick 시각 목록. None=끝에서 한 번, int=그 간격, 'fine'=체결 앞뒤·청산 앞뒤 3시간은 1분, 나머지는 하루."""
    a = int(t.active_from)
    if kind is None:
        return [end]
    if kind == "fine":
        pts = set(range(a - NS_PER_MIN, a + 3 * H, NS_PER_MIN))
        pts |= set(range(a, end, NS_PER_DAY))
        ex = int(t.exit_time)
        pts |= set(range(ex - 90 * NS_PER_MIN, ex + 90 * NS_PER_MIN, NS_PER_MIN))
        if due is not None:
            pts |= set(range(due - 90 * NS_PER_MIN, due + 90 * NS_PER_MIN, NS_PER_MIN))
        return sorted(p for p in pts if a <= p <= end) + [end]
    return list(range(a, end + 1, int(kind))) + [end]


def _replay_trade(conn, cfg, market, t, *, step_ns):
    """백테스트 거래 t 하나를 모의로 재현: 확인 = active_from, 청산 예약 = 청산 신호 판단 시각 + 30분.

    step_ns: _schedule 참고 (tick = fill_approved + monitor).
    """
    n = int(t.meta["n"])
    sid = approve(conn, approved_ns=int(t.active_from), n=n, atr20=float(t.meta["atr20"]),
                  decision_ns=int(t.approval_time))
    end = int(t.exit_bar_close_ns) + 5 * NS_PER_MIN
    clock = FakeClock(end)
    fm = frame_market_from(market, clock)
    due = None
    if t.meta.get("exit_signal_time"):
        exit_decision = int(pd.Timestamp(t.meta["exit_signal_time"]).value)
        due = exit_decision + cfg.trend_config().latency_ns
    times = _schedule(t, step_ns, end, due)
    planned = False
    for now in times:
        paper.fill_approved(conn, cfg, fm, now)
        # 엔진처럼: 청산 신호 판단 시각이 된 뒤에만 청산 예약 (catch_up(판단)을 먼저 한 뒤)
        if due is not None and not planned and now >= due - cfg.trend_config().latency_ns:
            dec = due - cfg.trend_config().latency_ns
            paper.monitor(conn, cfg, fm, dec)
            pos = db.open_position_for_subsystem(conn, n)
            if pos is not None:
                db.set_exit_plan(conn, pos["position_id"], exit_signal_close_ms=ns_to_ms(dec - 60 * NS_PER_SEC),
                                 exit_due_ms=ns_to_ms(due), now_ms=ns_to_ms(dec))
            planned = True
        paper.monitor(conn, cfg, fm, now)
    return conn.execute("SELECT * FROM paper_positions WHERE signal_id = ?", (sid,)).fetchone()


def _assert_same(p, t):
    assert p is not None and p["state"] == "CLOSED"
    assert p["entry_ms"] == ns_to_ms(t.entry_time)
    assert p["entry_price"] == t.entry_price
    assert p["stop"] == t.stop
    assert p["risk_per_unit"] == t.risk_per_unit
    assert p["exit_ms"] == ns_to_ms(t.exit_time)
    assert p["exit_bar_close_ms"] == ns_to_ms(t.exit_bar_close_ns)
    assert p["exit_price"] == t.exit_price
    assert p["exit_reason"] == t.exit_reason
    assert p["fees"] == pytest.approx(t.fees, rel=0, abs=1e-9)
    assert p["slippage"] == pytest.approx(t.slippage, rel=0, abs=1e-9)
    assert p["funding"] == pytest.approx(t.funding, rel=1e-9, abs=1e-9)
    assert p["gross_pnl"] == pytest.approx(t.gross_pnl, abs=1e-9)
    assert p["net_pnl"] == pytest.approx(t.net_pnl, rel=1e-9, abs=1e-9)
    assert p["r_multiple"] == pytest.approx(t.r_multiple, rel=1e-9, abs=1e-12)


def test_matches_backtest_trade_by_trade(cfg, trend_market_small):
    trades = _bt_trades(trend_market_small)
    assert len(trades) >= 6
    assert {t.exit_reason for t in trades} == {"stop", "trend"}
    for t in trades:
        c = db.connect(":memory:", mode=Mode.REPLAY, now_ms=0)
        try:
            p = _replay_trade(c, cfg, trend_market_small, t, step_ns=None)
            _assert_same(p, t)
            assert p["funding"] != 0.0 or t.funding == 0.0
        finally:
            c.close()


def test_result_independent_of_tick_interval(cfg, trend_market_small):
    """끝에서 한 번 / 하루 한 번 / 13분·6시간 7분 간격 / 체결·청산 앞뒤 1분 — 체결·청산·펀딩이 비트 단위로 같다."""
    trades = _bt_trades(trend_market_small)
    t = max(trades, key=lambda x: x.exit_time - x.entry_time)            # 가장 긴 보유(펀딩 많음)
    short = min(trades, key=lambda x: x.exit_time - x.entry_time)
    for tr, steps in ((t, (None, NS_PER_DAY, "fine", 6 * H + 7 * NS_PER_MIN)),
                      (short, (None, "fine", 13 * NS_PER_MIN, NS_PER_DAY))):
        results = []
        for step in steps:
            c = db.connect(":memory:", mode=Mode.REPLAY, now_ms=0)
            try:
                p = _replay_trade(c, cfg, trend_market_small, tr, step_ns=step)
                _assert_same(p, tr)
                f = [tuple(r) for r in c.execute(
                    "SELECT kind, ts_ms, price, qty, fee, slippage, funding, rate FROM paper_trades ORDER BY trade_id")]
                results.append((tuple(p[k] for k in ("entry_ms", "entry_price", "exit_ms", "exit_price",
                                                      "funding", "net_pnl", "r_multiple")), f))
            finally:
                c.close()
        assert all(r == results[0] for r in results[1:])


# ---------------------------------------------------------------------------
# 원장 일치
# ---------------------------------------------------------------------------


def test_ledger_matches_position_totals(conn, cfg):
    opens = [50_000.0 + 50 * i for i in range(40)]
    minute = minute_frame(opens)
    ft = [T0 + k * 7 * NS_PER_MIN for k in range(1, 6)]
    market, clock, _ = _open(conn, cfg, minute, T0, funding=funding_frame(ft, [0.0001, -0.0002, 0.0003, 0.0001, 0.0]))
    pos = only_position(conn)
    db.set_exit_plan(conn, pos["position_id"], exit_signal_close_ms=ns_to_ms(T0),
                     exit_due_ms=ns_to_ms(T0 + 30 * NS_PER_MIN), now_ms=ns_to_ms(T0))
    paper.monitor(conn, cfg, market, clock.now_ns())
    p = only_position(conn)
    assert p["state"] == "CLOSED" and p["exit_reason"] == "trend"
    rows = list(conn.execute("SELECT * FROM paper_trades WHERE position_id = ?", (p["position_id"],)))
    kinds = [r["kind"] for r in rows]
    assert kinds.count("ENTRY") == 1 and kinds.count("EXIT") == 1 and kinds.count("FUNDING") == 4  # 00:35는 청산(00:30) 뒤
    fee_sum = sum(r["fee"] for r in rows if r["kind"] in ("ENTRY", "EXIT"))
    slip_sum = sum(r["slippage"] for r in rows if r["kind"] in ("ENTRY", "EXIT"))
    fund_sum = sum(r["funding"] for r in rows if r["kind"] == "FUNDING")
    assert fee_sum == pytest.approx(p["fees"], abs=1e-9)
    assert slip_sum == pytest.approx(p["slippage"], abs=1e-9)
    assert fund_sum == pytest.approx(p["funding"], abs=1e-9)
    ex = [r for r in rows if r["kind"] == "EXIT"][0]
    assert ex["price"] == p["exit_price"] and ex["ts_ms"] == p["exit_ms"] and ex["qty"] == p["qty"]
    assert p["pnl_usdt"] == pytest.approx(p["net_pnl"] * p["qty"])
    assert p["r_multiple"] == pytest.approx(p["net_pnl"] / p["risk_per_unit"])
    # 청산 뒤 다시 감시해도 아무 일 없음
    assert paper.monitor(conn, cfg, market, clock.now_ns()) == []
    assert conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0] == len(rows)
    events = [r["event_type"] for r in conn.execute("SELECT event_type FROM audit_log")]
    assert "PAPER_FILL" in events and "PAPER_EXIT" in events and events.count("PAPER_FUNDING") == 4


def test_catch_up_fills_then_monitors(conn, cfg):
    minute = minute_frame([50_000.0, 50_000.0, 50_000.0], lows=[49_990, 45_000, 49_990])
    market, clock = make_market(minute)
    approve(conn, approved_ns=T0)
    msgs = paper.catch_up(conn, cfg, market, clock.now_ns())
    assert [m.kind for m in msgs] == ["fill", "exit"]
    assert only_position(conn)["exit_reason"] == "stop"


def test_messages_have_mode_tag_and_no_parse_markup(conn, cfg):
    minute = minute_frame([50_000.0, 50_000.0, 50_000.0], lows=[49_990, 45_000, 49_990])
    market, clock = make_market(minute)
    approve(conn, approved_ns=T0)
    msgs = paper.catch_up(conn, cfg, market, clock.now_ns())
    for m in msgs:
        assert m.text.startswith("[PAPER]")
        assert "<" not in m.text and "http" not in m.text
        assert m.buttons == ()


# ---------------------------------------------------------------------------
# 일일 리포트
# ---------------------------------------------------------------------------


def test_daily_report_contents(conn, cfg):
    # 포지션 1: 20일, 손절로 닫힘 / 포지션 2: 55일, 열림 / 신호: 패스 1, 만료 1
    minute = minute_frame([50_000.0] * 20, lows=[49_990] * 3 + [45_000] + [49_990] * 16)
    market, clock = make_market(minute)
    approve(conn, approved_ns=T0, n=20)
    paper.catch_up(conn, cfg, market, T0 + 5 * NS_PER_MIN)
    approve(conn, approved_ns=T0 + 6 * NS_PER_MIN, n=55, decision_ns=T_DECISION_NS + 1000)
    paper.catch_up(conn, cfg, market, clock.now_ns())
    p_pass = insert_test_signal(conn, n=100)
    ms = ns_to_ms(T_DECISION_NS)
    db.transition_signal(conn, p_pass, S.NEW, S.CARD_SENT, now_ms=ms, actor=Actor.ENGINE)
    db.transition_signal(conn, p_pass, S.CARD_SENT, S.PASSED, now_ms=ms, actor=Actor.TELEGRAM_USER)
    p_exp = insert_test_signal(conn, n=100, decision_ns=T_DECISION_NS - NS_PER_DAY)
    db.transition_signal(conn, p_exp, S.NEW, S.EXPIRED, now_ms=ms, actor=Actor.ENGINE)

    msg = paper.daily_report(conn, cfg, clock.now_ns() + H, mark_price=51_000.0)
    text = msg.text
    assert msg.kind == "report" and text.startswith("[PAPER] 일일 리포트")
    assert "열린 포지션 1개" in text and "55일" in text
    assert "체결 2건" in text and "청산 1건" in text
    assert "보호 손절" in text
    assert "누적: 청산 1건" in text
    assert "승인 2" in text and "패스 1" in text and "만료 1" in text
    assert "승인 지연: 평균" in text
    p55 = db.open_position_for_subsystem(conn, 55)
    ur = (51_000.0 - p55["entry_price"] - p55["funding"]) / p55["risk_per_unit"]
    assert f"{ur:+.2f}R" in text
    # 표시는 KST
    assert "KST" in text
    # 현재가 없으면 미실현 '-'
    assert "미실현 -" in paper.daily_report(conn, cfg, clock.now_ns() + H).text


def test_daily_report_empty_db(conn, cfg):
    text = paper.daily_report(conn, cfg, T_DECISION_NS).text
    assert "열린 포지션 0개" in text and "청산 거래 없음" in text and "승인 지연: 기록 없음" in text


def test_daily_report_claude_vs_human(conn, cfg):
    from bot.tests.conftest import ok_analysis
    aid_ok = db.insert_analysis(conn, ok_analysis(opinion="approve"), signal_day="2024-03-01",
                                now_ms=ns_to_ms(T_DECISION_NS))
    aid_pass = db.insert_analysis(conn, ok_analysis(opinion="pass"), signal_day="2024-03-01",
                                  now_ms=ns_to_ms(T_DECISION_NS))
    ms = ns_to_ms(T_DECISION_NS)
    s1 = insert_test_signal(conn, n=20)
    db.transition_signal(conn, s1, S.NEW, S.CARD_SENT, now_ms=ms, actor=Actor.ENGINE, fields=dict(analysis_id=aid_ok))
    db.transition_signal(conn, s1, S.CARD_SENT, S.PASSED, now_ms=ms, actor=Actor.TELEGRAM_USER)
    s2 = insert_test_signal(conn, n=55)
    db.transition_signal(conn, s2, S.NEW, S.CARD_SENT, now_ms=ms, actor=Actor.ENGINE,
                         fields=dict(analysis_id=aid_pass))
    db.transition_signal(conn, s2, S.CARD_SENT, S.PASSED, now_ms=ms, actor=Actor.TELEGRAM_USER)
    text = paper.daily_report(conn, cfg, T_DECISION_NS + H).text
    assert "Claude 승인/사람 패스 1" in text and "Claude 패스/사람 패스 1" in text


def test_report_uses_utc_window(conn, cfg):
    minute = minute_frame([50_000.0] * 5)
    market, clock = make_market(minute)
    approve(conn, approved_ns=T0)
    paper.catch_up(conn, cfg, market, clock.now_ns())
    # 체결 시각 + 24시간 뒤에는 '지난 24시간 체결'에서 빠진다
    assert "체결 1건" in paper.daily_report(conn, cfg, T0 + NS_PER_DAY - NS_PER_MIN).text
    assert "체결 0건" in paper.daily_report(conn, cfg, T0 + NS_PER_DAY + NS_PER_MIN).text
    assert MS_PER_DAY == ns_to_ms(NS_PER_DAY) and ms_to_ns(1) == 1_000_000
