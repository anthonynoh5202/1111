"""strategy 어댑터 시험 — 핵심 담당 (DESIGN §3, §10).

- 잘린 프레임(판단 시각까지)의 마지막 값 == 전체 프레임으로 계산한 같은 봉 값 (모든 t, 미래 참조 없음)
- ENTRY/EXIT/HOLD/NONE/BUSY 분기, 워밍업 NONE, decision_ns 불일치 거부
- 손절·R 분모 == backtest.simulate_trend_trade 값, 숏 신호 무시, Claude 입력 JSON 형식
"""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from backtest import config as C
from backtest import trend as TR
from backtest.types import ExecArrays, FundingArrays
from bot import strategy as ST
from bot.types import NS_PER_DAY, SubsystemAction as A

DELAY = C.AVAIL_DELAY_NS


@pytest.fixture(scope="module")
def market(trend_market_small):
    return trend_market_small


@pytest.fixture(scope="module")
def full(market):
    daily = TR.DailyData.from_frame(market.bars["1d"])
    return daily, {n: TR.channel_signals(daily, n) for n in TR.PERIODS}


def _eval(frame, t, **kw):
    sub = frame.iloc[: t + 1]
    dec = int(sub["close_ns"].iloc[-1]) + DELAY
    kw.setdefault("open_subsystems", {})
    kw.setdefault("busy_subsystems", set())
    return ST.evaluate_day(sub, decision_ns=dec, **kw)


def test_trend_config_is_e0_l_ens():
    cfg = ST.trend_config()
    assert cfg.base_key == "E0-L-ENS" and cfg.periods == (20, 55, 100)
    assert cfg.latency_min == 30 and cfg.stop_atr_mult == 2.0 and cfg.cost_multiplier == 1.0
    assert not cfg.allow_short and cfg.order_type == "market"


def test_truncated_frame_matches_full_frame_every_bar(market, full):
    """판단 시각까지 자른 프레임의 마지막 값 == 전체 기간 계산의 같은 봉 값 (모든 t)."""
    frame = market.bars["1d"]
    daily, sigs = full
    for t in range(len(frame)):
        out = _eval(frame, t)
        assert [s.n for s in out] == [20, 55, 100]
        for s in out:
            g = sigs[s.n]
            assert s.m == g.m == TR.exit_period(s.n)
            assert s.valid == bool(g.valid[t])
            assert s.signal_close_ns == int(daily.close_ns[t]) and s.decision_ns == int(daily.decision_ns[t])
            assert s.close == daily.close[t]
            for got, want in ((s.entry_level, g.up[t]), (s.exit_level, g.ex_lo[t]), (s.atr20, daily.atr[t])):
                assert (math.isnan(got) and math.isnan(want)) or got == want
            want_action = A.ENTRY if bool(g.long_entry[t]) else A.NONE
            assert s.action == want_action
            assert s.side == (1 if want_action == A.ENTRY else 0)


def test_entry_days_equal_backtest_long_entry_days(market, full):
    frame = market.bars["1d"]
    daily, sigs = full
    for n in (20, 55, 100):
        want = set(np.flatnonzero(sigs[n].long_entry).tolist())
        got = {t for t in range(len(frame)) if _eval(frame, t)[[20, 55, 100].index(n)].action == A.ENTRY}
        assert got == want and want, n


def test_branches_exit_hold_busy(market, full):
    frame = market.bars["1d"]
    daily, sigs = full
    g20 = sigs[20]
    t_exit = int(np.flatnonzero(g20.long_exit)[0])
    t_hold = int(np.flatnonzero(g20.valid & ~g20.long_exit)[0])
    out = _eval(frame, t_exit, open_subsystems={20: True})
    assert out[0].action == A.EXIT and out[0].side == 1
    out = _eval(frame, t_hold, open_subsystems={20: True})
    assert out[0].action == A.HOLD
    t_entry = int(np.flatnonzero(g20.long_entry)[0])
    out = _eval(frame, t_entry, busy_subsystems={20})
    assert out[0].action == A.BUSY and out[0].side == 0
    # 보유가 BUSY보다 우선, 다른 하위 시스템에는 영향 없음
    out = _eval(frame, t_entry, open_subsystems={20: True}, busy_subsystems={20})
    assert out[0].action in (A.HOLD, A.EXIT)
    assert out[1].n == 55 and out[1].action in (A.ENTRY, A.NONE)


def test_warmup_is_none_invalid(market):
    frame = market.bars["1d"]
    out = _eval(frame, 5)
    assert all(s.action == A.NONE and not s.valid for s in out)
    # 첫 유효 봉 = max(N, 21) (T-7)
    out = _eval(frame, 20)
    assert not out[0].valid
    out = _eval(frame, 21)
    assert out[0].valid and not out[1].valid


def test_decision_mismatch_rejected(market):
    frame = market.bars["1d"].iloc[:150]
    dec = int(frame["close_ns"].iloc[-1]) + DELAY
    with pytest.raises(ValueError, match="판단 시각 불일치"):
        ST.evaluate_day(frame, decision_ns=dec + NS_PER_DAY, open_subsystems={}, busy_subsystems=set())  # 오래된 데이터
    with pytest.raises(ValueError, match="판단 시각 불일치"):
        ST.evaluate_day(frame.iloc[:149], decision_ns=dec, open_subsystems={}, busy_subsystems=set())


def test_bad_frames_rejected(market):
    frame = market.bars["1d"].iloc[:150]
    with pytest.raises(ValueError):
        ST.daily_data(frame.iloc[:0])
    with pytest.raises(ValueError):
        ST.daily_data(frame.drop(frame.index[100]))            # 빈 구간
    with pytest.raises(ValueError):
        ST.daily_data(market.exec_bars.iloc[:100])              # 1분봉을 일봉으로


def test_short_signals_ignored(market, full):
    """숏 진입 조건(close < D_N)이 있는 날도 NONE (롱만 조합)."""
    frame = market.bars["1d"]
    daily, sigs = full
    t = int(np.flatnonzero(sigs[20].short_entry)[0])
    out = _eval(frame, t)
    assert out[0].action == A.NONE and out[0].side == 0
    with pytest.raises(ValueError):
        _eval(frame, t, cfg=TR.TrendConfig("E0", "LS"))


def test_stop_and_risk_match_simulate_trend_trade(market, full):
    daily, sigs = full
    cfg = ST.trend_config()
    xb = ExecArrays.from_frame(market.exec_bars)
    fa = FundingArrays.from_frame(market.funding)
    checked = 0
    for n in (20, 55, 100):
        for t in np.flatnonzero(sigs[n].long_entry)[:3]:
            tr = TR.simulate_trend_trade(daily, sigs[n], int(t), 1, cfg, xb, fa).trade
            if tr.entry_price is None:
                continue
            stop = ST.protective_stop(tr.entry_price, float(daily.atr[t]))
            assert stop == tr.stop
            assert ST.risk_per_unit(tr.entry_price, stop) == tr.risk_per_unit
            checked += 1
    assert checked >= 5


def test_exit_due_is_decision_plus_30min():
    assert ST.trend_exit_due_ns(1_000) == 1_000 + 30 * 60 * 10**9


def test_analysis_input_shape_and_numbers_only(market):
    frame = market.bars["1d"].iloc[:230]
    dec = int(frame["close_ns"].iloc[-1]) + DELAY
    sigs = ST.evaluate_day(frame, decision_ns=dec, open_subsystems={55: True}, busy_subsystems=set())
    payload = ST.analysis_input(frame, sigs, open_positions=[
        dict(n=55, entry_price=31000.123, stop=29000.0, unrealized_r=0.456, days_held=3.25, note="무시되어야 함")])
    assert set(payload) == {"schema", "symbol", "timeframe", "decision_time_utc", "strategy", "recent_daily",
                            "indicators", "subsystems", "open_positions"}
    assert payload["schema"] == "analyst_input_v1" and payload["strategy"]["key"] == "E0-L-ENS"
    assert payload["decision_time_utc"].endswith("00:01:00Z")
    assert len(payload["recent_daily"]) == 30 and payload["recent_daily"][-1]["close"] == round(frame["close"].iloc[-1], 2)
    assert set(payload["indicators"]) == {"sma20", "sma50", "sma100", "sma200", "atr20", "atr20_pct", "ret_7d_pct",
                                          "ret_30d_pct", "dist_from_100d_high_pct"}
    assert payload["indicators"]["sma200"] is not None
    assert [s["n"] for s in payload["subsystems"]] == [20, 55, 100]
    assert payload["open_positions"] == [dict(n=55, entry_price=31000.12, stop=29000.0, unrealized_r=0.46,
                                              days_held=3.2)]
    text = json.dumps(payload, allow_nan=False)                 # NaN 없음
    assert "무시되어야" not in text

    # 모든 문자열 값은 코드가 만든 고정 값·날짜뿐
    def strings(o):
        if isinstance(o, dict):
            for v in o.values():
                yield from strings(v)
        elif isinstance(o, list):
            for v in o:
                yield from strings(v)
        elif isinstance(o, str):
            yield o
    allowed = {"analyst_input_v1", "BTCUSDT", "1d", "E0-L-ENS", "TREND v1.0", "ENTRY", "EXIT", "HOLD", "NONE", "BUSY"}
    for s in strings(payload):
        assert s in allowed or s[:4].isdigit(), s


def test_analysis_input_warmup_has_nulls_not_nan(market):
    frame = market.bars["1d"].iloc[:15]
    dec = int(frame["close_ns"].iloc[-1]) + DELAY
    sigs = ST.evaluate_day(frame, decision_ns=dec, open_subsystems={}, busy_subsystems=set())
    payload = ST.analysis_input(frame, sigs, open_positions=[])
    json.dumps(payload, allow_nan=False)
    assert payload["indicators"]["sma20"] is None and payload["subsystems"][0]["entry_level"] is None
