"""적대적 검토: 추세추종 엔진 미래 참조·체결·비용 손 계산 (docs/TREND_SPEC.md v1.0, backtest/trend.py).

합성 데이터(1분 실행 봉): 일봉 d의 0번 분봉은 전날 종가 → 오늘 종가로 움직이고, 나머지 1,439개 분봉은 오늘 종가에
머문다(고가·저가 = 가격 ± 0.5). 평평한 날 TR = 1, ATR20 = 1. 판단 = 마감 + 60초 = 00:01, 활성(L=30) = 00:31,
첫 실행 봉 = 00:31 분봉. 필요한 분봉은 override[(day, minute)] = (o, h, l, c)로 직접 준다(일봉은 분봉을 합쳐 만든다).
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from backtest import config as C
from backtest import metrics as M
from backtest import trend as TR
from backtest import types as T
from backtest.tests.conftest import aggregate_bars, ns

MIN = C.NS_PER_MIN
DAY = C.NS_PER_DAY
W = 0.5
START = "2024-01-01"
NOF = T.FundingArrays(time_ns=np.array([], dtype=np.int64), rate=np.array([], dtype=np.float64))
WARM = [100.0] * 25
TK, SL, MK = C.FEE_TAKER, C.SLIPPAGE, C.FEE_MAKER


def build(closes, override=None, start=START):
    closes = [float(c) for c in closes]
    override = override or {}
    rows = np.empty((len(closes) * 1440, 4))
    for d, c in enumerate(closes):
        pc = closes[d - 1] if d else c
        blk = np.tile([c, c + W, c - W, c], (1440, 1))
        blk[0] = (pc, max(pc, c) + W, min(pc, c) - W, c)
        rows[d * 1440:(d + 1) * 1440] = blk
    for (d, m), bar in override.items():
        rows[d * 1440 + m] = bar
    for d, c in enumerate(closes):
        assert rows[d * 1440 + 1439, 3] == c, f"day {d} 마지막 종가는 {c}"
    open_ns = ns(start) + MIN * np.arange(rows.shape[0], dtype=np.int64)
    bars = T.make_bars_frame(open_ns, rows[:, 0], rows[:, 1], rows[:, 2], rows[:, 3], np.ones(rows.shape[0]), MIN)
    daily = aggregate_bars(bars, "1d")
    return TR.DailyData.from_frame(daily), T.ExecArrays.from_frame(bars)


def t_ns(d, minute=0):
    return ns(START) + d * DAY + minute * MIN


def cfg4(entry="E0", direction="LS", **kw):
    return TR.TrendConfig(entry=entry, direction=direction, periods=(4,), **kw)


def run(closes, cfg, override=None, fa=NOF):
    daily, xb = build(closes, override)
    trades, logs = TR.run_trend_combo(daily, cfg, xb, fa)
    return trades, logs, daily, xb


def r_hand(side, e, x, s, *, er, es, xr=TK, xs=SL, funding=0.0, m=1.0):
    net = side * (x - e) - (er * e + es * e + xr * x + xs * x) * m - funding
    risk = abs(e - s) + er * e + es * e + (TK + SL) * s          # 분모: 기본 비용(배수 없음)
    return net / risk


UP = WARM + [105, 106, 107, 108, 109, 107.5, 107, 107, 107, 107]   # 25일 돌파, 30일 종가 < D_2 → 31일 청산


# ---------------------------------------------------------------------------
# 신호: 당일 제외, 엄격 부등호, 신호일 ATR
# ---------------------------------------------------------------------------


def test_channel_excludes_today_and_strict_inequality():
    rng = np.random.default_rng(3)
    closes = list(np.round(100 + np.cumsum(rng.normal(0, 1, 70)), 1))
    daily, _ = build(closes)
    c = daily.close
    for n in (4, 20):
        sig = TR.channel_signals(daily, n)
        m = TR.exit_period(n)
        for t in range(sig.first_valid, len(c)):
            assert sig.up[t] == max(c[t - n:t]) and sig.dn[t] == min(c[t - n:t])    # 당일 제외
            assert sig.ex_hi[t] == max(c[t - m:t]) and sig.ex_lo[t] == min(c[t - m:t])
            assert sig.long_entry[t] == (c[t] > max(c[t - n:t]))
            assert sig.short_exit[t] == (c[t] > max(c[t - m:t]))
    # 종가 = U_N(같음)은 진입 아님
    tr, *_ = run(WARM + [100, 100, 100], cfg4())
    assert tr == []


def test_atr_is_signal_day_trailing_20_excluding_today():
    # 25일 봉 TR이 크더라도(105 − 99.5 = 5.5+) 신호일 ATR20[25]은 5~24일 TR(각 1)의 평균 = 1 (RULES §3 방식, 당일 제외)
    trades, *_ = run(UP, cfg4())
    t = trades[0]
    assert t.meta["atr20"] == pytest.approx(1.0)
    assert t.stop == pytest.approx(round(t.entry_price - 2.0, 1))


# ---------------------------------------------------------------------------
# 판단·활성 시각, 첫 실행 봉 시가
# ---------------------------------------------------------------------------


def test_e0_entry_first_1m_bar_open_at_or_after_active():
    ov = {(26, 30): (106.0, 106.5, 105.5, 106.0), (26, 31): (106.3, 106.8, 105.8, 106.0)}
    trades, *_ = run(UP, cfg4(), ov)
    t = trades[0]
    assert t.approval_time == t_ns(26, 1)
    assert t.active_from == t_ns(26, 31)
    assert t.entry_time == t_ns(26, 31) and t.entry_price == 106.3      # 00:30 봉(시작 < 활성)은 안 씀
    assert t.stop == 104.3
    for lat, minute in ((10, 11), (120, 121)):
        tt = run(UP, cfg4(latency_min=lat))[0][0]
        assert tt.entry_time == t_ns(26, minute)
    # 추세 청산: 30일 종가 107.5 < D_2 → 31일 00:31 분봉 시가
    assert t.exit_reason == "trend" and t.exit_time == t_ns(31, 31) and t.exit_price == 107.0


def test_e0_r_denominator_includes_entry_slippage_and_stop_is_minus_one_r():
    ov = {(28, m): (107.0, 107.5, 106.5, 107.0) for m in range(100)}
    ov[(28, 100)] = (107.0, 107.0, 104.0, 104.0)
    for m in range(101, 1440):
        ov[(28, m)] = (104.0, 104.5, 104.0, 104.0)
    closes = WARM + [105, 106, 107, 104.0, 104.0, 104.0]
    trades, *_ = run(closes, cfg4(direction="L"), ov)
    t = trades[0]
    assert t.entry_price == 106.0 and t.stop == 104.0 and t.exit_reason == "stop" and t.exit_price == 104.0
    risk = 2.0 + (TK + SL) * 106 + (TK + SL) * 104
    assert t.risk_per_unit == pytest.approx(risk, abs=1e-12)
    assert t.r_multiple == pytest.approx(-1.0, abs=1e-12)


def test_e0_stop_gap_exit_at_open_with_costs():
    ov = {(28, m): (107.0, 107.5, 106.5, 107.0) for m in range(200)}
    ov[(28, 200)] = (103.0, 103.2, 102.8, 103.0)
    for m in range(201, 1440):
        ov[(28, m)] = (103.0, 103.5, 102.5, 103.0)
    closes = WARM + [105, 106, 107, 103.0, 103.0]
    trades, *_ = run(closes, cfg4(direction="L"), ov)
    t = trades[0]
    assert t.exit_reason == "stop" and t.exit_price == 103.0 and t.exit_time == t_ns(28, 200)
    assert t.r_multiple == pytest.approx(r_hand(1, 106, 103, 104, er=TK, es=SL), abs=1e-12)
    assert t.slippage == pytest.approx(SL * 106 + SL * 103)


def test_stop_in_minute_after_close_then_reentry_on_same_closed_day():
    """T-2 경계: 29일 종가 109 > U_4(롱 신호, 이미 보유 중이라 무시). 30일 00:00 분봉(끝 = 29일 판단 시각 00:01)에서
    손절 → 판단 시각에 포지션 없음 → 29일 신호로 00:31 재진입(명세 문자 그대로, 미래 참조 아님: 00:01까지의 정보만)."""
    closes = WARM + [105, 106, 107, 108, 109, 95, 95, 95]
    trades, *_ = run(closes, cfg4())
    a, b, c = trades
    assert a.exit_reason == "stop" and a.exit_time == t_ns(30, 0) and a.exit_bar_close_ns == t_ns(30, 1)
    assert b.side == 1 and b.signal_time == t_ns(30) and b.entry_time == t_ns(30, 31) and b.entry_price == 95.0
    assert b.meta["level"] == 108.0
    # 30일 종가 95 < D_2 → 31일 00:31 롱 청산 + 같은 봉 숏 진입
    assert b.exit_reason == "trend" and c.side == -1 and b.exit_time == c.entry_time == t_ns(31, 31)


def test_stop_during_exit_latency_window_is_stop_and_reversal_still_checked():
    # 넓은 손절(20 × ATR = 20 → 86). 30일 종가 95 < D_4 → 롱 청산·숏 진입 신호(판단 31일 00:01, 활성 00:31).
    # 31일 00:10(판단 뒤, 활성 전)에 85까지 떨어져 손절 → 사유 stop, 숏 진입은 그대로 00:31
    closes = WARM + [105, 106, 107, 108, 109, 95, 95, 95]
    ov = {(31, 10): (95.0, 95.0, 85.0, 95.0)}
    trades, *_ = run(closes, cfg4(stop_atr_mult=20.0), ov)
    a, b = trades
    assert a.stop == 86.0 and a.exit_reason == "stop" and a.exit_time == t_ns(31, 10) and a.exit_price == 86.0
    assert b.side == -1 and b.signal_time == t_ns(31) and b.entry_time == t_ns(31, 31)


def test_reversal_same_bar_order_with_1m_bars():
    closes = WARM + [105, 106, 107, 108, 109, 95, 94, 94, 94]
    ov = {(31, 31): (94.2, 94.7, 93.7, 94.0)}
    trades, *_ = run(closes, cfg4(stop_atr_mult=30.0), ov)
    a, b = trades[:2]
    assert a.exit_reason == "trend" and a.exit_time == b.entry_time == t_ns(31, 31)
    assert a.exit_price == b.entry_price == 94.2
    # 청산: 테이커 + 슬리피지, 새 진입: 테이커 + 슬리피지
    assert a.fees == pytest.approx(TK * (106 + 94.2)) and a.slippage == pytest.approx(SL * (106 + 94.2))
    assert b.order_type == "market" and b.slippage >= SL * 94.2


# ---------------------------------------------------------------------------
# E1: 관통·지연 구간·만료·취소
# ---------------------------------------------------------------------------

# 25일 종가 105 > U_4 = 100 → 지정가 100. 26~29일 종가 103 (청산 없음 D_2 ≥ 100 까지) — 30일에도 103.
E1_BASE = WARM + [105, 103, 103, 103, 103, 103, 103, 103, 103, 103]


def _dip(d, m, low):
    return {(d, m): (103.0, 103.0, low, 103.0)}


def test_e1_touch_equal_limit_does_not_fill_penetration_does():
    tr = run(E1_BASE, cfg4("E1", "L"), _dip(27, 500, 100.0))[0]
    assert tr[0].status == "expired"                          # 저가 = 지정가 → 미체결 (엄격)
    tr = run(E1_BASE, cfg4("E1", "L"), _dip(27, 500, 99.9))[0]
    t = tr[0]
    assert t.status == "filled" and t.entry_price == 100.0 and t.entry_time == t_ns(27, 500)
    assert t.stop == 98.0                                    # 100 − 2 × ATR20[25] (= 1)
    # 같은 분봉 저가 99.9 > 98 → 손절 안 남. 이후 eod
    assert t.fees == pytest.approx(MK * 100 + TK * t.exit_price)
    assert t.risk_per_unit == pytest.approx(2.0 + MK * 100 + (TK + SL) * 98, abs=1e-12)
    assert t.r_multiple == pytest.approx(r_hand(1, 100, t.exit_price, 98, er=MK, es=0.0), abs=1e-12)


def test_e1_dip_in_latency_window_ignored():
    # 26일 00:10 (판단 00:01 뒤, 활성 00:31 전) 관통 → 체결 아님
    tr = run(E1_BASE, cfg4("E1", "L"), _dip(26, 10, 99.0))[0]
    assert tr[0].status == "expired"
    tr = run(E1_BASE, cfg4("E1", "L"), _dip(26, 31, 99.0))[0]
    assert tr[0].status == "filled" and tr[0].entry_time == t_ns(26, 31)


def test_e1_expiry_boundary_five_days():
    # 유효 = 25일 마감(26일 00:00) + 5일 = 31일 00:00. 30일 23:59 분봉(끝 = 31일 00:00)까지 체결 가능
    tr = run(E1_BASE, cfg4("E1", "L"), _dip(30, 1439, 99.0) | {(30, 1439): (103.0, 103.0, 99.0, 103.0)})[0]
    assert tr[0].status == "filled" and tr[0].entry_time == t_ns(30, 1439)
    tr = run(E1_BASE + [103], cfg4("E1", "L"), {(31, 0): (103.0, 103.0, 99.0, 103.0)})[0]
    assert tr[0].status == "expired"


def test_e1_cancel_on_exit_signal_effective_at_decision():
    # 27일 종가 100.5 < D_2 = min(105, 103) = 103 → 롱 청산 신호 → 28일 00:01부터 취소
    closes = WARM + [105, 103, 100.5, 100.5, 100.5, 100.5, 100.5]
    before = {(28, 0): (100.5, 100.5, 99.5, 100.5)}                  # 28일 00:00~00:01 (끝 = 판단 시각) → 유효
    after = {(28, 1): (100.5, 100.5, 99.5, 100.5)}                   # 00:01~00:02 → 취소 뒤
    tr = run(closes, cfg4("E1", "L"), after)[0]
    assert tr[0].status == "cancelled"
    tr = run(closes, cfg4("E1", "L"), before)[0]
    t = tr[0]
    assert t.status == "filled" and t.entry_time == t_ns(28, 0)
    # 체결 뒤 곧바로 27일 청산 신호의 활성(28일 00:31) 시가로 청산
    assert t.exit_reason == "trend" and t.exit_time == t_ns(28, 31)


def test_e1_fill_and_stop_same_bar_uses_stop_price():
    closes = WARM + [105, 103, 103, 103, 103, 103]
    ov = {(27, 600): (103.0, 103.0, 97.0, 103.0)}                    # 지정가 100 관통 + 손절 98 도달
    t = run(closes, cfg4("E1", "L"), ov)[0][0]
    assert t.status == "filled" and t.exit_reason == "stop" and t.exit_price == 98.0
    assert t.exit_time == t_ns(27, 600)
    assert t.r_multiple == pytest.approx(-1.0, abs=1e-12)


def test_e1_short_symmetric():
    closes = WARM + [95, 97, 97, 97, 97, 97]
    ov = {(27, 700): (97.0, 100.1, 97.0, 97.0)}
    t = run(closes, cfg4("E1", "LS"), ov)[0][0]
    assert t.side == -1 and t.status == "filled" and t.entry_price == 100.0 and t.stop == 102.0
    assert t.r_multiple == pytest.approx(r_hand(-1, 100, t.exit_price, 102, er=MK, es=0.0), abs=1e-12)


# ---------------------------------------------------------------------------
# 펀딩 부호·비용 배수
# ---------------------------------------------------------------------------


def _fa(times, rates):
    return T.FundingArrays(time_ns=np.asarray(times, dtype=np.int64), rate=np.asarray(rates, dtype=np.float64))


def test_funding_window_sign_and_cost_multiplier():
    # 롱 26일 00:31 진입(106) ~ 31일 00:31 청산(107). 펀딩: 26일 00:00(진입 전, 제외), 26일 08:00(+0.001, 지불),
    # 28일 08:00(−0.002, 수취), 31일 00:00(+0.001, 청산 전 → 포함), 31일 08:00(청산 뒤, 제외)
    fa = _fa([t_ns(26, 0), t_ns(26, 480), t_ns(28, 480), t_ns(31, 0), t_ns(31, 480)],
             [0.01, 0.001, -0.002, 0.001, 0.01])
    t = run(UP, cfg4(), fa=fa)[0][0]
    fund = 0.001 * 106 - 0.002 * 108 + 0.001 * 107.5   # 그 시각 분봉 시가 (31일 00:00 봉 시가 = 30일 종가)
    assert t.funding == pytest.approx(fund, abs=1e-12)
    assert t.r_multiple == pytest.approx(r_hand(1, 106, 107, 104, er=TK, es=SL, funding=fund), abs=1e-12)
    t2 = run(UP, cfg4(cost_multiplier=2.0), fa=fa)[0][0]
    fund2 = 2 * (0.001 * 106 + 0.001 * 107.5) - 0.002 * 108   # 지불만 2배
    assert t2.funding == pytest.approx(fund2, abs=1e-12)
    assert t2.fees == pytest.approx(2 * t.fees) and t2.slippage == pytest.approx(2 * t.slippage)
    assert t2.risk_per_unit == pytest.approx(t.risk_per_unit)          # R 분모는 기본 비용
    assert t2.r_multiple == pytest.approx(r_hand(1, 106, 107, 104, er=TK, es=SL, funding=fund2, m=2.0), abs=1e-12)
    # 숏은 부호 반대: 양의 비율에서 받음
    down = WARM + [95, 94, 93, 92, 91, 92.5, 93, 93]
    fa_s = _fa([t_ns(26, 480)], [0.001])
    s = run(down, cfg4(), fa=fa_s)[0][0]
    assert s.side == -1 and s.funding == pytest.approx(-0.001 * 94)
    s2 = run(down, cfg4(cost_multiplier=2.0), fa=fa_s)[0][0]
    assert s2.funding == pytest.approx(-0.001 * 94)                     # 수취는 배수 없음


def test_cost_stress_same_trades():
    rng = np.random.default_rng(5)
    closes = list(np.round(100 + np.cumsum(rng.normal(0, 1.5, 120)), 1))
    daily, xb = build(closes)
    for entry in ("E0", "E1"):
        c = TR.TrendConfig(entry, "LS", (4, 10))
        a, _ = TR.run_trend_combo(daily, c, xb, NOF)
        b, _ = TR.run_trend_combo(daily, c.replace(cost_multiplier=2.0), xb, NOF)
        cs = M.summarize_cost_stress(a, b, rng_key="x")
        assert cs["same_trades"] and cs["n"] > 5
        assert cs["mean_r"] < cs["mean_r_base"]


# ---------------------------------------------------------------------------
# 무작위 기준선: 같은 청산 규칙·비용·손절 배수·지연
# ---------------------------------------------------------------------------


def _rand_market():
    rng = np.random.default_rng(9)
    closes = list(np.round(100 + np.cumsum(rng.normal(0.05, 1.5, 80)), 1))
    return build(closes)


def test_random_table_matches_engine_rules_under_variants():
    daily, xb = _rand_market()
    for kw in ({}, {"stop_atr_mult": 3.0}, {"cost_multiplier": 2.0}, {"latency_min": 120}):
        cfg = cfg4("E1", "LS", **kw)
        sig = TR.channel_signals(daily, 4)
        for side in (1, -1):
            tb = TR.random_table(daily, 4, side, cfg, xb, NOF)
            for i in range(0, tb.days.size, 7):
                d = int(tb.days[i])
                o = TR.simulate_trend_trade(daily, sig, d, side, cfg, xb, NOF, entry_mode="E0").trade
                assert o.order_type == "market"
                assert o.active_from == daily.decision_ns[d] + cfg.latency_ns
                assert o.stop == pytest.approx(round(o.entry_price - side * cfg.stop_atr_mult * daily.atr[d], 1))
                assert o.fees == pytest.approx(TK * o.entry_price * cfg.cost_multiplier
                                               + TK * o.exit_price * cfg.cost_multiplier)
                if tb.filled[i]:
                    assert tb.r[i] == pytest.approx(o.r_multiple, abs=1e-12)
                    # 청산 = 첫 M일 반대 돌파 활성 뒤 시가 / 손절 / 끝
                    assert o.exit_reason in ("trend", "stop", "eod")
                    if o.exit_reason == "trend":
                        k = TR.next_exit_day(sig, side, d)
                        jt = int(np.searchsorted(xb.open_ns, daily.decision_ns[k] + cfg.latency_ns))
                        assert o.exit_time == int(xb.open_ns[jt]) and o.exit_price == xb.open[jt]


def test_random_baseline_draws_only_same_month_side_n():
    # 표를 손으로: N=4 롱은 달마다 R이 달의 번호, 숏은 −달 번호. 실제 거래 3건(롱 2월, 롱 3월, 숏 2월)
    months = np.array([24289] * 3 + [24290] * 3)             # 2024-02, 2024-03 (연×12 + 월−1)
    days = np.arange(6)
    tl = TR.RandomTable(4, 1, days, months, np.ones(6, bool), np.array([2., 2, 2, 3, 3, 3]),
                        np.array([2.5, 2.5, 2.5, 3.5, 3.5, 3.5]))
    ts = TR.RandomTable(4, -1, days, months, np.ones(6, bool), np.array([-2., -2, -2, -3, -3, -3]),
                        np.array([-1.5] * 6))
    mk = lambda side, iso: T.TradeResult(status="filled", busy_until=0, plan_entry=1.0, stop=1.0,
                                         risk_per_unit=1.0, plan_id=iso, scenario="N4", side=side,
                                         order_type="market", signal_time=0, approval_time=0, active_from=0,
                                         target=math.inf, madi_id=None, entry_time=ns(iso), entry_price=1.0,
                                         exit_time=ns(iso), exit_price=1.0, exit_reason="trend", r_multiple=0.0,
                                         meta={"n": 4})
    trades = [mk(1, "2024-02-10"), mk(1, "2024-03-05"), mk(-1, "2024-02-20")]
    out = TR.run_trend_random_baseline(trades, {(4, 1): tl, (4, -1): ts}, cfg4("E0"), n_reps=50)
    np.testing.assert_allclose(out["means"], (2 + 3 - 2) / 3)
    assert out["threshold"] == pytest.approx(1.0)
    out1 = TR.run_trend_random_baseline(trades, {(4, 1): tl, (4, -1): ts}, cfg4("E1"), n_reps=50)
    assert out1["threshold"] == pytest.approx(max(1.0, (2.5 + 3.5 - 1.5) / 3))   # E1: 두 분포 중 큰 p95


def test_random_baseline_deterministic():
    daily, xb = _rand_market()
    cfg = cfg4("E0", "LS")
    trades, _ = TR.run_trend_combo(daily, cfg, xb, NOF)
    tables = TR.random_tables_for(daily, cfg, xb, NOF)
    a = TR.run_trend_random_baseline(trades, tables, cfg, n_reps=200)
    b = TR.run_trend_random_baseline(trades, tables, cfg, n_reps=200)
    np.testing.assert_array_equal(a["means"], b["means"])


# ---------------------------------------------------------------------------
# 계좌 곡선: 명목 상한
# ---------------------------------------------------------------------------


def test_equity_single_trade_hand_calc_capped_notional():
    trades, _, daily, xb = run(UP, cfg4())
    t = trades[0]
    start = TR.combo_start_day(daily, cfg4())
    e = TR.equity_curve(trades, daily, start, sizing="risk", trim=False)
    # 위험 기반 명목 = 0.005 ÷ (risk ÷ 106) = 0.2469 > 0.2 → 0.2 상한
    q = 0.2 / 106
    assert e["final_equity"] == pytest.approx(1.0 + q * t.net_pnl, abs=1e-12)
    assert e["max_notional_ratio"] > 0.2                      # 수량 고정(trim=False)은 가격 상승으로 0.2배를 넘는다(참고값)
    et = TR.equity_curve(trades, daily, start, sizing="risk", trim=True)
    assert et["max_notional_ratio"] <= 0.2 + 1e-9 and et["n_trims"] > 0
    # 손절이 넓으면 위험 기반 (0.005 × 106 ÷ risk) × 자산
    t20 = run(UP, cfg4(stop_atr_mult=20.0))[0][0]
    e20 = TR.equity_curve([t20], daily, start, sizing="risk", trim=False)
    q20 = 0.005 / t20.risk_per_unit
    assert e20["final_equity"] == pytest.approx(1.0 + q20 * t20.net_pnl, abs=1e-12)


def test_equity_notional_cap_per_system_with_reversal():
    """(TX-1 회귀) 한 하위 시스템에서 반대 신호(같은 봉 청산·진입)가 나도 명목 합은 0.2배를 넘지 않아야 한다."""
    closes = WARM + [105, 106, 107, 108, 109, 95, 94, 94, 94]
    trades, _, daily, xb = run(closes, cfg4(stop_atr_mult=30.0))
    f = TR.filled(trades)
    assert any(a.exit_time == b.entry_time for a in f for b in f if a is not b)   # 반대 진입이 실제로 있음
    start = TR.combo_start_day(daily, cfg4())
    e = TR.equity_curve(trades, daily, start, sizing="fixed")
    assert e["max_notional_ratio"] <= 0.2 + 1e-6, e["max_notional_ratio"]
    assert e["max_notional_ratio"] >= 0.2 - 1e-6                                 # 진입 순간 = 정확히 0.2배


def test_equity_notional_stop_then_same_day_reentry_counted_once():
    """(TX-1 회귀) 00:00 분봉 손절 → 같은 날 00:31 재진입: 손절된 포지션은 재진입 순간 이미 닫혀 있어 세지 않는다."""
    closes = WARM + [105, 106, 107, 108, 109, 95, 95, 95]
    trades, _, daily, xb = run(closes, cfg4())
    a, b, c = trades
    assert a.exit_reason == "stop" and a.exit_time < b.entry_time
    assert int(np.searchsorted(daily.close_ns, a.exit_time, side="right")) == \
        int(np.searchsorted(daily.close_ns, b.entry_time, side="right"))      # 같은 날(곡선 기준)
    start = TR.combo_start_day(daily, cfg4())
    et = TR.equity_curve(trades, daily, start, sizing="fixed", trim=True)
    assert et["max_notional_ratio"] <= 0.2 + 1e-6, et["max_notional_ratio"]
    # 수량 고정(trim=False)은 손절 전 시가에 가격 상승분만큼 0.2배를 조금 넘을 수 있으나, 두 포지션 합(≈0.4배)은 아니다
    e = TR.equity_curve(trades, daily, start, sizing="fixed", trim=False)
    assert e["max_notional_ratio"] < 0.25, e["max_notional_ratio"]


def test_equity_trim_keeps_notional_below_cap_on_rally():
    # 롱 보유 중 가격이 2배 → 매일 시가에 0.2배 초과분 줄임
    closes = WARM + [105 + 5 * i for i in range(25)]
    trades, _, daily, xb = run(closes, cfg4("E0", "L", stop_atr_mult=30.0))
    start = TR.combo_start_day(daily, cfg4())
    e = TR.equity_curve(trades, daily, start, sizing="fixed", trim=True)
    assert e["n_trims"] > 0
    assert e["max_notional_ratio"] <= 0.2 * (1 + 1e-6)


def test_equity_trim_single_trade_independent_hand_sim():
    """거래 하나(명목 0.2배 고정 + 매일 시가 초과분 줄이기)를 따로 손으로 굴려 equity_curve와 비교."""
    trades, _, daily, xb = run(UP, cfg4())
    t = trades[0]
    start = TR.combo_start_day(daily, cfg4())
    e = TR.equity_curve(trades, daily, start, sizing="fixed", trim=True)
    ent_i = int(np.searchsorted(daily.close_ns, t.entry_time, side="right"))
    ex_i = int(np.searchsorted(daily.close_ns, t.exit_time, side="right"))
    assert (ent_i, ex_i) == (26, 31)
    cash, prev, q, out = 1.0, 1.0, 0.0, []
    for i in range(start, len(daily)):
        o = daily.open[i]
        if i > start and q > 0 and q * o > 0.2 * prev * (1 + 1e-9):
            nq = 0.2 * prev / o
            cash += (q - nq) * ((o - t.entry_price) - (TK + SL) * t.entry_price - (TK + SL) * o)
            q = nq
        if i == ent_i:
            q = 0.2 * prev / t.entry_price
        if i == ex_i:
            cash += q * t.net_pnl
            q = 0.0
        v = cash + q * (daily.close[i] - t.entry_price)
        out.append(v)
        prev = v
    np.testing.assert_allclose(e["equity"], out, rtol=0, atol=1e-12)
    assert e["n_trims"] >= 2


def test_random_table_month_is_utc_month_of_entry_close():
    # 일봉 d의 마감(= 다음 날 00:00 UTC) 달이 무작위 표의 달: 1월 31일 봉 → 2월(시장가 진입 2월 1일 00:31과 같은 달)
    closes = [100.0 + (i % 3) for i in range(60)]
    daily, xb = build(closes)
    tb = TR.random_table(daily, 4, 1, cfg4(), xb, NOF)
    jan31 = int(np.searchsorted(daily.open_ns, ns("2024-01-31")))
    i = int(np.searchsorted(tb.days, jan31))
    assert tb.days[i] == jan31 and tb.months[i] == 2024 * 12 + 1        # 2월 (연×12 + 월−1)
    assert tb.months[i - 1] == 2024 * 12 + 0
