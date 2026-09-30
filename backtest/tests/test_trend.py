"""추세추종 엔진 손 계산 테스트 (docs/TREND_SPEC.md v1.0, backtest/trend.py).

합성 데이터: 일봉 종가 목록 → 실행 봉 = 1시간봉 24개/일. 0시 봉은 전날 종가 → 오늘 종가로 움직이고 1~23시 봉은 오늘 종가에
머문다(고가·저가 = 시가·종가 ± 0.5). 그래서 평평한 날의 TR = 1, ATR20 = 1이고, 활성(마감 + 60초 + 30분 = 00:31) 뒤
첫 실행 봉은 01:00 봉, 그 시가 = 그날 종가다. 필요한 날은 1시간봉 24개를 직접 준다(override).
펀딩은 없음(손익 = 가격 차 − 수수료 − 슬리피지).
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from backtest import config as C
from backtest import trend as TR
from backtest import types as T
from backtest.indicators import trailing_mean, true_range
from backtest.tests.conftest import aggregate_bars, ns

HOUR = C.NS_PER_HOUR
W = 0.5
START = "2024-01-01"
NO_FUNDING = T.FundingArrays(time_ns=np.array([], dtype=np.int64), rate=np.array([], dtype=np.float64))
WARM = [100.0] * 25          # 0~24일: 평평(ATR20 = 1), 25일부터 사건


def flat_hours(c: float, n: int = 23) -> list:
    return [(c, c + W, c - W, c)] * n


def build(closes, override=None, start=START):
    """일봉 종가 → (DailyData, ExecArrays, 1시간봉 프레임, 일봉 프레임)."""
    closes = [float(c) for c in closes]
    override = override or {}
    rows = []
    for d, c in enumerate(closes):
        pc = closes[d - 1] if d else c
        if d in override:
            bars = override[d]
            assert len(bars) == 24 and bars[-1][3] == c, f"day {d} override는 24개, 마지막 종가 = {c}"
        else:
            bars = [(pc, max(pc, c) + W, min(pc, c) - W, c)] + flat_hours(c)
        rows.extend(bars)
    arr = np.asarray(rows, dtype=np.float64)
    open_ns = ns(start) + HOUR * np.arange(len(rows), dtype=np.int64)
    hourly = T.make_bars_frame(open_ns, arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], np.ones(len(rows)), HOUR)
    T.check_bars_frame(hourly, contiguous=True)
    daily = aggregate_bars(hourly, "1d")
    return TR.DailyData.from_frame(daily), T.ExecArrays.from_frame(hourly), hourly, daily


def day_ns(d: int, hour: int = 0, start=START) -> int:
    return ns(start) + d * C.NS_PER_DAY + hour * HOUR


def cfg4(entry="E0", direction="LS", **kw) -> TR.TrendConfig:
    """손 계산용 하위 시스템 N = 4 (M = 2)."""
    return TR.TrendConfig(entry=entry, direction=direction, periods=(4,), **kw)


def run(closes, cfg, override=None):
    daily, xb, _, _ = build(closes, override)
    trades, logs = TR.run_trend_combo(daily, cfg, xb, NO_FUNDING)
    return trades, logs, daily, xb


def expected_r(side, entry, exit_, stop, *, entry_rate, entry_slip, exit_rate=C.FEE_TAKER, exit_slip=C.SLIPPAGE):
    gross = side * (exit_ - entry)
    net = gross - entry_rate * entry - entry_slip * entry - exit_rate * exit_ - exit_slip * exit_
    risk = abs(entry - stop) + entry_rate * entry + entry_slip * entry + (C.FEE_TAKER + C.SLIPPAGE) * stop
    return net / risk


# ---------------------------------------------------------------------------
# 기본 규칙
# ---------------------------------------------------------------------------


def test_exit_period_rounding():
    assert [TR.exit_period(n) for n in (20, 55, 100)] == [10, 28, 50]    # TREND_SPEC §1
    assert TR.exit_period(4) == 2


def test_combos_and_keys():
    keys = [c.key for c in TR.trend_combos()]
    assert keys == ["E0-LS-ENS", "E0-LS-N55", "E0-L-ENS", "E0-L-N55",
                    "E1-LS-ENS", "E1-LS-N55", "E1-L-ENS", "E1-L-N55"]
    c = TR.trend_combos()[0]
    assert c.periods == (20, 55, 100) and c.latency_min == 30 and c.stop_atr_mult == 2.0
    assert c.order_type == "market" and c.entry_slip_rate == C.SLIPPAGE
    e1 = TR.trend_combos()[4]
    assert e1.order_type == "limit" and e1.entry_rate == C.FEE_MAKER and e1.entry_slip_rate == 0.0
    assert c.replace(latency_min=120).key == "E0-LS-ENS_lat120"
    assert c.replace(stop_atr_mult=3.0).key == "E0-LS-ENS_stop3"
    assert c.replace(cost_multiplier=2.0).key == "E0-LS-ENS_cost2"
    with pytest.raises(ValueError):
        TR.TrendConfig("E2", "LS")


def test_channels_exclude_current_bar_and_atr20():
    closes = WARM + [105, 106, 107, 108, 109]
    daily, *_ = build(closes)
    sig = TR.channel_signals(daily, 4)
    assert sig.up[25] == 100 and sig.dn[25] == 100 and sig.long_entry[25]      # 당일 제외 직전 4개
    assert sig.up[26] == 105 and sig.ex_lo[26] == 100
    assert sig.first_valid == 21                                               # ATR20 준비(T-7)
    tr = true_range(daily.high, daily.low, daily.close)
    np.testing.assert_allclose(daily.atr, trailing_mean(tr, 20))
    assert daily.atr[25] == pytest.approx(1.0)                                 # 평평한 날 TR = 1
    np.testing.assert_array_equal(daily.decision_ns, daily.close_ns + C.AVAIL_DELAY_NS)
    s55 = TR.channel_signals(daily, 20)
    assert s55.m == 10


# ---------------------------------------------------------------------------
# E0 손 계산
# ---------------------------------------------------------------------------

TREND_UP = WARM + [105, 106, 107, 108, 109, 107.5, 107, 107, 107, 107]


def test_e0_long_entry_trend_exit_hand_calc():
    trades, logs, daily, xb = run(TREND_UP, cfg4())
    assert len(trades) == 1
    t = trades[0]
    assert t.status == "filled" and t.side == 1
    assert t.signal_time == day_ns(26)                                  # 25일 봉 마감
    assert t.approval_time == day_ns(26) + 60 * C.NS_PER_SEC
    assert t.active_from == day_ns(26) + 31 * C.NS_PER_MIN
    assert t.entry_time == day_ns(26, 1) and t.entry_price == 106.0      # 00:31 뒤 첫 실행 봉(01:00) 시가
    assert t.stop == 104.0                                               # 106 − 2 × ATR20(1)
    # 30일 종가 107.5 < D_2 = min(108, 109) → 31일 00:31 뒤 01:00 봉 시가 107에 추세 청산
    assert t.exit_reason == TR.EXIT_TREND
    assert t.exit_time == day_ns(31, 1) and t.exit_price == 107.0
    assert t.meta["exit_signal_time"] == C.ns_to_iso(day_ns(31) + 60 * C.NS_PER_SEC)
    r = expected_r(1, 106.0, 107.0, 104.0, entry_rate=C.FEE_TAKER, entry_slip=C.SLIPPAGE)
    assert t.r_multiple == pytest.approx(r, abs=1e-12)
    assert t.r_multiple == pytest.approx(0.8509 / 2.147, abs=1e-4)
    assert t.slippage == pytest.approx(C.SLIPPAGE * (106 + 107))         # 진입·청산 슬리피지
    assert t.fees == pytest.approx(C.FEE_TAKER * (106 + 107))
    assert [g.status for g in logs] == ["passed"]


def test_e0_latency_120_uses_later_bar():
    trades, *_ = run(TREND_UP, cfg4(latency_min=120))
    t = trades[0]
    assert t.entry_time == day_ns(26, 3)                                # 00:01 + 120분 = 02:01 → 03:00 봉
    assert t.exit_time == day_ns(31, 3)


def test_e0_stop_same_bar_and_gap():
    # 28일 05시 봉에서 손절 104를 건드림(시가 107) → 손절가 104
    touch = {28: flat_hours(107, 5) + [(107, 107.5, 103.5, 104.2)] + flat_hours(104.2, 18)}
    closes = WARM + [105, 106, 107, 104.2] + [104.2] * 6
    trades, *_ = run(closes, cfg4(direction="L"), touch)
    t = trades[0]
    assert t.exit_reason == "stop" and t.exit_price == 104.0 and t.exit_time == day_ns(28, 5)
    assert t.r_multiple == pytest.approx(-1.0, abs=1e-12)                # 펀딩 없음 → 정확히 −1R
    # 갭: 05시 봉이 103.5에서 시작 → 시가 청산 (더 불리)
    gap = {28: flat_hours(107, 5) + [(103.5, 104.0, 103.0, 103.8)] + flat_hours(103.8, 18)}
    closes = WARM + [105, 106, 107, 103.8] + [103.8] * 6
    trades, *_ = run(closes, cfg4(direction="L"), gap)
    t = trades[0]
    assert t.exit_reason == "stop" and t.exit_price == 103.5
    r = expected_r(1, 106.0, 103.5, 104.0, entry_rate=C.FEE_TAKER, entry_slip=C.SLIPPAGE)
    assert t.r_multiple == pytest.approx(r, abs=1e-12) and t.r_multiple < -1.0


def test_reentry_after_stop_uses_first_decision_after_stop():
    # 손절(28일 05시) 뒤 28일 종가가 다시 U_4 위면 28일 판단(29일 00:01)에 재진입 (T-2)
    ov = {28: flat_hours(107, 5) + [(107, 108.2, 103.5, 108.0)] + flat_hours(108.0, 18)}
    closes = WARM + [105, 106, 107, 108.0, 108.0, 108.0]
    trades, *_ = run(closes, cfg4(direction="L"), ov)
    assert len(trades) == 2
    assert trades[0].exit_reason == "stop"
    assert trades[1].signal_time == day_ns(29) and trades[1].entry_time == day_ns(29, 1)


def test_reversal_exit_and_opposite_entry_same_bar():
    closes = WARM + [105, 106, 107, 108, 109, 95, 94, 94, 94, 94]
    trades, *_ = run(closes, cfg4(stop_atr_mult=20.0))
    assert len(trades) == 2
    a, b = trades
    assert a.side == 1 and a.exit_reason == TR.EXIT_TREND
    assert b.side == -1 and b.signal_time == day_ns(31)                 # 30일 종가 95 < D_4 = 106
    assert a.exit_time == b.entry_time == day_ns(31, 1)                 # 청산 후 같은 시각 반대 진입
    assert a.exit_price == b.entry_price == 94.0
    # ATR20[30] = (15 × 1 + 6 + 2 + 2 + 2 + 2) ÷ 20 = 1.45 → 숏 손절 94 + 20 × 1.45 = 123
    assert b.meta["atr20"] == pytest.approx(1.45)
    assert b.stop == 123.0 and b.exit_reason == "eod"


def test_long_only_mode_ignores_short_signals():
    closes = WARM + [105, 106, 107, 108, 109, 95, 94, 94, 94, 94]
    trades, logs, *_ = run(closes, cfg4(direction="L", stop_atr_mult=20.0))
    assert len(trades) == 1 and trades[0].side == 1 and trades[0].exit_reason == TR.EXIT_TREND
    # 처음부터 하락만 있는 경로: 롱만 모드는 거래 없음, 롱·숏은 숏 1건
    down = WARM + [95, 94, 93, 92, 91, 90]
    assert run(down, cfg4(direction="L"))[0] == []
    ls = run(down, cfg4(direction="LS"))[0]
    assert len(ls) == 1 and ls[0].side == -1 and ls[0].entry_price == 94.0 and ls[0].stop == 96.0


def test_no_signal_during_warmup():
    closes = [100.0] * 5 + [110.0] + [100.0] * 10 + [120.0] * 3     # 20일 이전 돌파는 ATR20 준비 전
    trades, logs, *_ = run(closes, cfg4())
    assert trades == [] and logs == []


# ---------------------------------------------------------------------------
# E1 (돌파 레벨 지정가) 손 계산
# ---------------------------------------------------------------------------


def test_e1_fill_on_pullback_hand_calc():
    ov = {27: [(104, 104.5, 103.5, 104), (104, 104.2, 99.5, 100.5), (100.5, 106.2, 100.3, 106)] + flat_hours(106, 21)}
    closes = WARM + [105, 104, 106, 107, 108, 105, 104, 104, 104]
    trades, logs, *_ = run(closes, cfg4(entry="E1", direction="L"), ov)
    assert len(trades) == 1
    t = trades[0]
    assert t.order_type == "limit" and t.plan_entry == 100.0            # U_4[25] = 100
    assert t.entry_time == day_ns(27, 1) and t.entry_price == 100.0     # low 99.5 < 100 관통 → 지정가
    assert t.stop == 98.0
    assert t.exit_reason == TR.EXIT_TREND and t.exit_time == day_ns(31, 1) and t.exit_price == 104.0
    r = expected_r(1, 100.0, 104.0, 98.0, entry_rate=C.FEE_MAKER, entry_slip=0.0)
    assert t.r_multiple == pytest.approx(r, abs=1e-12)
    assert t.r_multiple == pytest.approx(3.9072 / 2.0886, abs=1e-4)
    assert t.slippage == pytest.approx(C.SLIPPAGE * 104.0)             # E1 진입 슬리피지 없음


def test_e1_touch_is_not_fill_and_same_bar_stop():
    # 저가가 정확히 100(닿기만) → 미체결, 이후 상승 → 5일 뒤 만료
    ov = {27: [(104, 104.5, 103.5, 104), (104, 104.2, 100.0, 100.5), (100.5, 106.2, 100.3, 106)] + flat_hours(106, 21)}
    closes = WARM + [105, 104, 106, 107, 108, 109, 110]
    trades, *_ = run(closes, cfg4(entry="E1", direction="L"), ov)
    assert trades[0].status == "expired"
    # 체결 봉에서 손절(98)까지 내려감 → 같은 봉 손절, 손절가 체결, 정확히 −1R
    ov = {27: [(104, 104.5, 103.5, 104), (104, 104.2, 97.5, 98.5), (98.5, 99.0, 98.0, 99.0)] + flat_hours(99.0, 21)}
    closes = WARM + [105, 104, 99.0, 99.0, 99.0]
    trades, *_ = run(closes, cfg4(entry="E1", direction="L"), ov)
    t = trades[0]
    assert t.entry_time == t.exit_time == day_ns(27, 1)
    assert t.exit_reason == "stop" and t.exit_price == 98.0
    assert t.r_multiple == pytest.approx(-1.0, abs=1e-12)


def test_e1_expiry_after_5_days_and_f9_logs():
    closes = WARM + [105, 106, 107, 108, 109, 110, 111, 112]
    trades, logs, daily, xb = run(closes, cfg4(entry="E1", direction="L"))
    a = trades[0]
    assert a.status == "expired" and a.plan_entry == 100.0
    assert a.busy_until == day_ns(26) + 5 * C.NS_PER_DAY                # 신호 마감 + 5일
    # 대기 중(26~29일) 같은 방향 돌파는 새 신호가 아님 → F9 기록 4건, 30일 판단에서 새 주문
    f9 = [g for g in logs if g.reasons == ("F9",)]
    assert [g.signal_time for g in f9][:4] == [day_ns(d) for d in (27, 28, 29, 30)]
    b = trades[1]
    assert b.signal_time == day_ns(31) and b.plan_entry == 109.0        # U_4[30] = max(106..109)
    # 두 번째 주문은 데이터 끝(32일 마감)에 아직 살아 있음 → not_filled, 그 뒤 돌파(31·32일)도 F9
    assert b.status == "not_filled"
    assert [g.signal_time for g in f9][4:] == [day_ns(32), day_ns(33)]


def test_e1_cancel_on_exit_signal_before_fill():
    # 27일 종가 101 < D_2 = min(105, 104) → 청산 신호 → 대기 주문 취소(28일 00:01부터). 28일에 100 아래로 가도 체결 없음
    closes = WARM + [105, 104, 101, 99, 99, 99]
    trades, logs, *_ = run(closes, cfg4(entry="E1", direction="L"))
    assert len(trades) == 1
    t = trades[0]
    assert t.status == "cancelled" and t.meta["cancel_reason"] == "exit_signal"
    assert t.busy_until == day_ns(28) + 60 * C.NS_PER_SEC
    # 롱·숏이면 28일 종가 99 < D_4 = 100 → 숏 지정가 @ 100
    trades, *_ = run(closes, cfg4(entry="E1", direction="LS"))
    assert [x.side for x in trades] == [1, -1] and trades[1].plan_entry == 100.0
    assert trades[1].signal_time == day_ns(29)


def test_e1_fill_before_cancel_time_is_kept():
    # 청산 신호 날(27일)의 장중 23시 봉에서 체결 → 취소 효력(28일 00:01) 전이므로 유효, 청산은 28일 01:00 봉 시가
    ov = {27: [(104, 104.5, 101.5, 102)] + flat_hours(102, 22) + [(102, 102.2, 99.8, 101)]}
    closes = WARM + [105, 104, 101, 101, 101]
    trades, *_ = run(closes, cfg4(entry="E1", direction="L"), ov)
    t = trades[0]
    assert t.status == "filled" and t.entry_time == day_ns(27, 23)
    assert t.exit_reason == TR.EXIT_TREND and t.exit_time == day_ns(28, 1)


def test_cost_multiplier_changes_only_costs():
    base, *_ = run(TREND_UP, cfg4())
    dbl, *_ = run(TREND_UP, cfg4(cost_multiplier=2.0))
    a, b = base[0], dbl[0]
    assert (a.entry_time, a.exit_time, a.exit_price, a.risk_per_unit) == (b.entry_time, b.exit_time, b.exit_price,
                                                                          b.risk_per_unit)
    assert b.fees == pytest.approx(2 * a.fees) and b.slippage == pytest.approx(2 * a.slippage)


def test_subsystems_are_independent():
    closes = WARM + [105, 106, 107, 108, 109, 107.5, 107, 107, 107, 107]
    daily, xb, *_ = build(closes)
    both, _ = TR.run_trend_combo(daily, TR.TrendConfig("E0", "LS", periods=(4, 6)), xb, NO_FUNDING)
    one4, _ = TR.run_trend_combo(daily, TR.TrendConfig("E0", "LS", periods=(4,)), xb, NO_FUNDING)
    one6, _ = TR.run_trend_combo(daily, TR.TrendConfig("E0", "LS", periods=(6,)), xb, NO_FUNDING)
    key = lambda t: (t.scenario, t.entry_time, t.exit_time, t.r_multiple)
    assert sorted(map(key, both)) == sorted(map(key, one4 + one6))
    assert {t.scenario for t in both} == {"N4", "N6"}


def test_funding_charged_like_engine():
    daily, xb, hourly, _ = build(TREND_UP)
    times = np.arange(day_ns(0), day_ns(len(TREND_UP)) + 1, 8 * HOUR, dtype=np.int64)
    fa = T.FundingArrays(time_ns=times, rate=np.full(times.shape, 0.0001))
    trades, _ = TR.run_trend_combo(daily, cfg4(), xb, fa)
    t = trades[0]
    # 진입 26일 01:00 < f ≤ 청산 31일 01:00 → 26일 08·16시, 27~30일 각 3회, 31일 00시 = 2 + 12 + 1 = 15회
    f = times[(times > t.entry_time) & (times <= t.exit_time)]
    assert len(f) == 15
    j = np.searchsorted(xb.open_ns, f, side="right") - 1
    assert t.funding == pytest.approx(float(np.sum(0.0001 * xb.open[j])))
    assert t.net_pnl == pytest.approx(t.gross_pnl - t.fees - t.slippage - t.funding)
