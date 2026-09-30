"""공용 도우미 자체 검사: 합성 시장의 성질(다른 테스트가 기대는 값)과 FrameMarket 미래 참조 차단 (설계 담당)."""
from __future__ import annotations

from collections import Counter

import pytest

from backtest import trend as TR
from backtest.types import ExecArrays, FundingArrays
from bot.tests.conftest import FakeTransport, FrameMarket, LookaheadError, frame_market_from, run_async
from bot.types import NS_PER_DAY, NS_PER_MIN, FakeClock, MarketData, ChatTransport


def test_trend_market_has_trades_in_all_subsystems(trend_market_small):
    m = trend_market_small
    daily = TR.DailyData.from_frame(m.bars["1d"])
    trades, _ = TR.run_trend_combo(daily, TR.TrendConfig("E0", "L"), ExecArrays.from_frame(m.exec_bars),
                                   FundingArrays.from_frame(m.funding))
    f = TR.filled(trades)
    assert Counter(t.scenario for t in f) == {"N20": 4, "N55": 2, "N100": 2}
    assert Counter(t.exit_reason for t in f) == {"trend": 4, "stop": 4}
    assert (m.exec_bars["close_ns"] - m.exec_bars["open_ns"] == NS_PER_MIN).all()   # 실행 봉 전부 1분봉


def test_frame_market_blocks_lookahead(trend_market_small):
    d0 = int(trend_market_small.bars["1d"]["close_ns"].iloc[120])
    clock = FakeClock(d0 + 60 * 10**9)
    fm = frame_market_from(trend_market_small, clock)
    assert isinstance(fm, MarketData)
    daily = fm.daily_bars(clock.now_ns())
    assert int(daily["close_ns"].iloc[-1]) == d0 and len(daily) == 121
    mins = fm.minute_bars(d0 - NS_PER_DAY, clock.now_ns())
    assert int(mins["close_ns"].max()) <= clock.now_ns() and len(mins) == 1441
    with pytest.raises(LookaheadError):
        fm.daily_bars(clock.now_ns() + 1)
    with pytest.raises(LookaheadError):
        fm.minute_bars(d0, clock.now_ns() + NS_PER_MIN)


def test_fake_transport_protocol_and_failure():
    t = FakeTransport(fail_next=1)
    assert isinstance(t, ChatTransport)
    with pytest.raises(ConnectionError):
        run_async(t.send("x"))
    mid = run_async(t.send("[PAPER] hello"))
    assert t.sent[0].message_id == mid and t.sent[0].text.startswith("[PAPER]")
    assert isinstance(FrameMarket, type)
