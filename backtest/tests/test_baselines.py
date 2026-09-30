"""돈치안 기준선 테스트 (DESIGN §9 T-BAS, RULES_SPEC §8.4·§12.4, I-43).

합성 추세 경로로 진입·청산 시점, 다음 날 시가 체결, 수수료·펀딩 손 계산, 명목 상한, 미래 참조 없음을 확인한다.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from backtest import baselines as B
from backtest import config as C
from backtest import execution as X
from backtest import types as T
from backtest.tests.conftest import make_bars, make_funding, random_walk_bars, split_bars

NO_FUNDING = T.FundingArrays(time_ns=np.array([], dtype=np.int64), rate=np.array([], dtype=np.float64))


def daily_rows(oc_pairs, start="2024-01-01"):
    """(시가, 종가) 목록 → 일봉 (고가·저가 = 시가·종가의 최대·최소)."""
    rows = [(o, max(o, c), min(o, c), c) for o, c in oc_pairs]
    return make_bars(rows, start=start, tf="1d")


def xb_of(daily) -> T.ExecArrays:
    return T.ExecArrays.from_frame(daily)


def fa_of(frame) -> T.FundingArrays:
    return T.FundingArrays.from_frame(frame)


# 손 계산용 경로 (기간 4, 청산 2). 진입가 = 청산가라서 손익은 수수료·펀딩뿐.
# 롱: t=4 종가 110 > 직전 4일 최고 100 → t=5 시가 111 체결, t=7 종가 107 < 직전 2일 최저 108 → t=8 시가 111 청산.
#     보유 중 시가(108, 109)가 진입가보다 낮아 명목이 예산(0.6 × 자산) 아래 → 줄이기 없음.
HAND_LONG = [(100, 100), (100, 100), (100, 100), (100, 100), (100, 110),
             (111, 108), (108, 109), (109, 107), (111, 109), (109, 109)]   # 청산 뒤 종가는 채널 안(재진입 없음)
# 숏: t=4 종가 190 < 직전 4일 최저 200 → t=5 시가 189 체결, t=7 종가 188 > 직전 2일 최고 186 → t=8 시가 189 청산.
HAND_SHORT = [(200, 200), (200, 200), (200, 200), (200, 200), (200, 190),
              (189, 186), (186, 185), (185, 188), (189, 189), (189, 189)]
# 진입 뒤 계속 오르는 롱: 수량 고정이면 명목이 예산을 넘는다 → 기본(trim)은 줄이고, entry_only는 그대로 둔다.
HAND_UP = [(100, 100), (100, 100), (100, 100), (100, 100), (100, 110),
           (111, 120), (120, 125), (125, 110), (111, 111), (111, 111)]


# ---------------------------------------------------------------------------
# 채널·목표 포지션 (I-43)
# ---------------------------------------------------------------------------


def test_trailing_extremes_exclude_current_bar():
    hi, lo = B.trailing_extremes(np.array([1.0, 3.0, 2.0, 5.0, 4.0]), 2)
    np.testing.assert_array_equal(hi, [np.nan, np.nan, 3.0, 3.0, 5.0])
    np.testing.assert_array_equal(lo, [np.nan, np.nan, 1.0, 2.0, 2.0])


def rising_then_falling():
    """t=0..29 종가 100+t (상승), t=30부터 하루 1씩 하락."""
    up = [100.0 + t for t in range(30)]
    down = [129.0 - k for k in range(1, 15)]
    return np.array(up + down)


def test_rising_path_long_after_21st_close_and_exit_on_10day_low():
    close = rising_then_falling()
    pos = B.donchian_positions(close, 20, 10)
    assert pos.dtype == np.int8
    assert np.all(pos[:20] == 0)                      # 직전 20개 종가가 없으면 판단 없음
    assert pos[20] == 1                               # 21번째 종가 120 > 직전 20일 최고 119 → 롱
    # t=34 종가 124 = 직전 10일 최저 124 → 유지(엄격한 부등호), t=35 종가 123 < 124 → 청산
    assert np.all(pos[20:35] == 1) and pos[35] == 0
    # t=39 종가 119 = 직전 20일 최저 119 → 진입 아님, t=40 종가 118 < 119 → 숏
    assert np.all(pos[35:40] == 0) and np.all(pos[40:] == -1)


def test_short_side_is_mirror_of_long_side():
    close = rising_then_falling()
    for p, m in ((20, 10), (5, 2)):
        np.testing.assert_array_equal(B.donchian_positions(300.0 - close, p, m),
                                      -B.donchian_positions(close, p, m))


def test_tie_with_channel_is_not_breakout():
    close = np.array([100.0, 101.0, 102.0, 102.0, 103.0])
    pos = B.donchian_positions(close, 3, 1)
    assert pos[3] == 0 and pos[4] == 1                # 102 = 직전 최고 102 → 돌파 아님, 103 → 롱


def test_exit_and_reverse_on_same_bar():
    close = np.r_[np.arange(100.0, 130.0), 90.0]     # t=30 급락: 10일 최저 이탈 + 20일 최저 이탈
    pos = B.donchian_positions(close, 20, 10)
    assert pos[29] == 1 and pos[30] == -1             # 같은 봉에서 롱 청산 후 숏 진입


def test_positions_have_no_lookahead():
    rng = np.random.default_rng(0)
    close = random_walk_bars(400, seed=3, tf="1d")["close"].to_numpy()
    base = B.donchian_positions(close, 20, 10)
    for t in (25, 60, 150, 300, 398):
        changed = close.copy()
        changed[t + 1:] = changed[t + 1:] * np.exp(rng.normal(0, 0.2, changed.shape[0] - t - 1))
        np.testing.assert_array_equal(B.donchian_positions(changed, 20, 10)[:t + 1], base[:t + 1])


# ---------------------------------------------------------------------------
# 체결·수수료·펀딩 손 계산 (I-43, §12.2)
# ---------------------------------------------------------------------------


def test_fill_next_open_and_round_trip_fee_hand_case():
    daily = daily_rows(HAND_LONG)
    res = B.donchian_ensemble(daily, NO_FUNDING, xb_of(daily), periods=(4,), notional_cap=0.6)
    q = 0.6 / 111.0                                   # 자산 1.0 × 0.6 ÷ 체결가(t=5 시가 111, t=4 종가 110 아님)
    eq = res["equity"]
    assert eq.shape == (6,) and eq[0] == 1.0          # t=4 마감부터
    assert eq[1] == pytest.approx(1.0 - 0.0005 * 0.6 + q * (108 - 111), abs=1e-12)
    assert eq[3] == pytest.approx(eq[2] + q * (107 - 109), abs=1e-12)
    # 왕복 수수료 = 2 × 0.0005 × 명목(진입가 = 청산가 = 111 → 명목 0.6 양쪽 같음)
    assert res["final_equity"] == pytest.approx(1.0 - 2 * 0.0005 * 0.6, abs=1e-12)
    assert res["total_fees"] == pytest.approx(2 * 0.0005 * 0.6, abs=1e-15)
    assert res["n_trades"] == 1 and res["n_trims"] == 0 and res["total_funding"] == 0.0

    start = 4
    close = daily["close"].to_numpy()
    sim = B._simulate(daily["open"].to_numpy(), close, np.zeros(len(close)),
                      np.stack([B._positions(close, 4, 2, start)]), 0.6, start)
    enter, exit_ = sim["fills"]
    assert (enter["action"], enter["day"], enter["price"]) == ("enter", 5, 111.0)   # 판단 t=4 → t+1 시가
    assert (exit_["action"], exit_["day"], exit_["price"]) == ("exit", 8, 111.0)    # 판단 t=7 → t+1 시가


def test_funding_long_pays_short_receives_hand_case():
    # 8시간마다 0.0001, 가격 = 그 시각을 포함하는 실행 봉(여기서는 일봉) 시가
    for sign, pairs in ((+1, HAND_LONG), (-1, HAND_SHORT)):
        daily = daily_rows(pairs)
        fund = make_funding("2024-01-01", "2024-01-11", rate=0.0001)
        res = B.donchian_ensemble(daily, fa_of(fund), xb_of(daily), periods=(4,), notional_cap=0.6)
        o = daily["open"].to_numpy()
        # 보유 (t=5 시가, t=8 시가]: t5 08·16시(o5 ×2), t6 00·08·16시(o6 ×3), t7 ×3(o7), t8 00시(o8)
        price_sum = 2 * o[5] + 3 * o[6] + 3 * o[7] + o[8]
        q = 0.6 / o[5]
        expected = 1.0 - 2 * 0.0005 * 0.6 - sign * q * 0.0001 * price_sum
        assert res["n_trades"] == 1 and res["n_trims"] == 0
        assert res["final_equity"] == pytest.approx(expected, abs=1e-12)
        assert res["total_funding"] == pytest.approx(sign * q * 0.0001 * price_sum, abs=1e-15)


def test_funding_prices_follow_execution_rule():
    # 실행 봉이 일봉보다 잘면 "그 시각을 포함하는 실행 봉 시가" (execution.funding_cost와 같은 규칙, I-35)
    daily = random_walk_bars(12, seed=5, tf="1d", sigma=0.02)
    xb = T.ExecArrays.from_frame(split_bars(daily, "4h"))
    fund = make_funding("2024-01-01", "2024-01-13", rate=np.linspace(-0.0003, 0.0005, 37))
    fa = fa_of(fund)
    o_ns, c_ns = daily["open_ns"].to_numpy(), daily["close_ns"].to_numpy()
    per_day = B.funding_per_day(o_ns, c_ns, fa, xb)
    for a, b in ((0, 3), (2, 9), (5, 12)):
        # 롱 1단위를 open_ns[a]에 진입해 open_ns[b](= close_ns[b−1])에 청산 → 진입 < f ≤ 청산
        expected = X.funding_cost(1, int(o_ns[a]), int(c_ns[b - 1]), xb, fa)
        assert per_day[a:b].sum() == pytest.approx(expected, rel=1e-12, abs=1e-15)


# ---------------------------------------------------------------------------
# 크기: 전략마다 자산의 0.2배, 합 ≤ 0.6배 (§12.4)
# ---------------------------------------------------------------------------


def test_simultaneous_entries_total_notional_is_cap():
    close = np.r_[np.full(100, 100.0), np.linspace(101.0, 110.0, 10)]   # t=100 종가가 세 채널 모두 돌파
    daily = make_bars(closes=close, start="2023-01-01", tf="1d")
    start = max(C.DONCHIAN_PERIODS)
    targets = np.stack([B._positions(close, p, p // 2, start) for p in C.DONCHIAN_PERIODS])
    assert np.all(targets[:, start] == 1)
    sim = B._simulate(daily["open"].to_numpy(), close, np.zeros(len(close)), targets, 0.2, start)
    enters = [f for f in sim["fills"] if f["action"] == "enter"]
    assert len(enters) == 3 and {f["day"] for f in enters} == {start + 1}
    total = sum(f["qty"] * f["price"] for f in enters)
    assert total == pytest.approx(0.6 * enters[0]["equity"], rel=1e-12)          # 합 = 0.6 × 자산
    assert all(f["qty"] * f["price"] == pytest.approx(0.2 * f["equity"], rel=1e-12) for f in enters)


def test_every_entry_is_02_of_equity_on_random_data():
    daily = random_walk_bars(700, seed=11, tf="1d", sigma=0.03, trend_len=60, trend_strength=0.4)
    close = daily["close"].to_numpy()
    start = max(C.DONCHIAN_PERIODS)
    targets = np.stack([B._positions(close, p, p // 2, start) for p in C.DONCHIAN_PERIODS])
    sim = B._simulate(daily["open"].to_numpy(), close, np.zeros(len(close)), targets, 0.2, start)
    enters = [f for f in sim["fills"] if f["action"] == "enter"]
    assert len(enters) >= 5
    for f in enters:
        assert f["qty"] * f["price"] == pytest.approx(0.2 * f["equity"], rel=1e-12)   # 진입 시점 자산의 0.2배
    for day in {f["day"] for f in enters}:
        same_day = [f for f in enters if f["day"] == day]
        assert sum(f["qty"] * f["price"] for f in same_day) <= 0.6 * same_day[0]["equity"] * (1 + 1e-12)


def test_trim_keeps_each_strategy_within_budget_hand_case():
    daily = daily_rows(HAND_UP)
    start, close, open_ = 4, daily["close"].to_numpy(), daily["open"].to_numpy()
    targets = np.stack([B._positions(close, 4, 2, start)])
    sim = B._simulate(open_, close, np.zeros(len(close)), targets, 0.6, start)
    q0 = 0.6 / 111.0
    e_size = 1.0 - 0.0005 * 0.6 + q0 * (120 - 111)           # t=6 시가 120에서 평가한 자산
    trim = [f for f in sim["fills"] if f["action"] == "trim"]
    assert trim[0]["day"] == 6 and trim[0]["price"] == 120.0
    assert trim[0]["qty"] == pytest.approx(q0 - 0.6 * e_size / 120.0, rel=1e-12)   # 예산 넘는 만큼만
    assert trim[0]["fee"] == pytest.approx(0.0005 * trim[0]["qty"] * 120.0, rel=1e-12)
    assert np.all(sim["open_notional"] <= sim["open_budget"] * (1 + 1e-9))
    assert sim["max_notional_ratio"] <= 0.6 * (1 + 1e-3)      # 진입·줄이기 수수료만큼의 오차
    # 설계 문장 그대로(entry_only): 수량 고정 → 명목이 예산을 넘고, 손익 = 수수료뿐(진입가 = 청산가 = 111)
    fixed = B.donchian_ensemble(daily, NO_FUNDING, xb_of(daily), periods=(4,), cap_mode="entry_only")
    assert fixed["n_trims"] == 0 and fixed["max_notional_ratio"] > 0.6
    assert fixed["final_equity"] == pytest.approx(1.0 - 2 * 0.0005 * 0.6, abs=1e-12)
    trimmed = B.donchian_ensemble(daily, NO_FUNDING, xb_of(daily), periods=(4,))
    assert trimmed["cap_mode"] == "trim" and trimmed["n_trims"] >= 1
    with pytest.raises(ValueError):
        B.donchian_ensemble(daily, NO_FUNDING, xb_of(daily), periods=(4,), cap_mode="rebalance")


def test_trim_only_reduces_and_bounds_total_on_random_data():
    daily = random_walk_bars(700, seed=11, tf="1d", sigma=0.03, trend_len=60, trend_strength=0.4)
    close, open_ = daily["close"].to_numpy(), daily["open"].to_numpy()
    start = max(C.DONCHIAN_PERIODS)
    targets = np.stack([B._positions(close, p, p // 2, start) for p in C.DONCHIAN_PERIODS])
    sim = B._simulate(open_, close, np.zeros(len(close)), targets, 0.2, start)
    assert sim["n_trims"] > 0
    assert all(f["qty"] > 0 for f in sim["fills"] if f["action"] == "trim")    # 줄이기만, 늘리지 않음
    assert np.all(sim["open_notional"] <= sim["open_budget"] * (1 + 1e-9))       # 전략마다 ≤ 0.2 × 자산
    assert np.all(sim["open_notional"].sum(axis=0) <= 3 * sim["open_budget"] * (1 + 1e-9))   # 합 ≤ 0.6 × 자산
    fixed = B._simulate(open_, close, np.zeros(len(close)), targets, 0.2, start, trim=False)
    assert fixed["n_trims"] == 0 and fixed["n_trades"] == sim["n_trades"]         # 진입·청산 시점은 같다


# ---------------------------------------------------------------------------
# 미래 참조 없음·결정성·결과 형식
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def synthetic_daily():
    return random_walk_bars(420, seed=21, tf="1d", sigma=0.03, trend_len=50, trend_strength=0.4)


def test_ensemble_equity_has_no_lookahead(synthetic_daily):
    daily = synthetic_daily
    fund = fa_of(make_funding("2024-01-01", "2025-03-01", rate=0.0001))
    xb = xb_of(daily)
    full = B.donchian_ensemble(daily, fund, xb)["equity"]
    for k in (130, 250, 419):
        part = B.donchian_ensemble(daily.iloc[:k], fund, xb)["equity"]
        # 마지막 점은 데이터 끝 청산 수수료가 들어가므로 뺀다
        np.testing.assert_array_equal(part[:-1], full[:part.shape[0] - 1])


def test_ensemble_result_format_and_determinism(synthetic_daily):
    daily = synthetic_daily
    fund = fa_of(make_funding("2024-01-01", "2025-03-01", rate=0.0001))
    res = B.donchian_ensemble(daily, fund, xb_of(daily))
    for k in ("cagr", "max_drawdown", "sharpe", "n_trades", "final_equity", "start_utc", "end_utc", "per_period",
              "equity"):
        assert k in res
    assert list(res["per_period"]) == list(C.DONCHIAN_PERIODS)
    assert res["exit_periods"] == [10, 27, 50] and res["notional_per_strategy"] == pytest.approx(0.2)
    assert res["equity"].shape == (len(daily) - 100,) and res["n_days"] == len(daily) - 101
    assert res["start_utc"] == C.ns_to_iso(int(daily["close_ns"].iloc[100]))
    assert res["n_trades"] == sum(v["n_trades"] for v in res["per_period"].values())
    assert res["max_drawdown"] >= 0 and math.isfinite(res["sharpe"]) and math.isfinite(res["cagr"])
    assert res["final_equity"] == res["equity"][-1]
    payload = T.to_jsonable({k: v for k, v in res.items() if k != "equity"})
    json.dumps(payload, allow_nan=False)
    again = B.donchian_ensemble(daily, fund, xb_of(daily))
    assert json.dumps(payload) == json.dumps(T.to_jsonable({k: v for k, v in again.items() if k != "equity"}))
    np.testing.assert_array_equal(res["equity"], again["equity"])


def test_performance_hand_values():
    eq = np.array([1.0, 1.1, 0.99, 1.2])
    perf = B.performance(eq, days=3.0)
    ret = np.array([0.1, -0.1, 1.2 / 0.99 - 1])
    assert perf["max_drawdown"] == pytest.approx(0.1)                       # 1.1 → 0.99
    assert perf["cagr"] == pytest.approx(1.2 ** (365 / 3) - 1)
    assert perf["sharpe"] == pytest.approx(ret.mean() / ret.std(ddof=1) * math.sqrt(365))
    assert all(math.isnan(v) for v in B.performance(np.array([1.0]), days=1.0).values())


def test_too_short_history_gives_nan_without_error():
    daily = random_walk_bars(60, seed=1, tf="1d")
    res = B.donchian_ensemble(daily, NO_FUNDING, xb_of(daily))
    assert res["n_trades"] == 0 and math.isnan(res["cagr"]) and math.isnan(res["sharpe"])
    assert res["equity"].shape == (0,)


@pytest.mark.slow
def test_real_data_runs():
    from backtest import data as D
    daily = D.load_klines("1d")
    xb = T.ExecArrays.from_frame(D.load_exec_bars())
    fa = T.FundingArrays.from_frame(D.load_funding(until_ns=int(xb.close_ns[-1])))
    res = B.donchian_ensemble(daily, fa, xb)
    assert res["start_utc"] == "2020-04-11T00:00:00Z" and res["end_utc"] == "2026-09-29T00:00:00Z"
    assert res["n_trades"] > 50 and 0 < res["max_drawdown"] < 1
    assert all(math.isfinite(res[k]) for k in ("cagr", "sharpe", "final_equity"))
    assert res["max_notional_ratio"] <= 0.6 * (1 + 1e-3)                        # §12.4 전체 명목 ≤ 0.6배
    fixed = B.donchian_ensemble(daily, fa, xb, cap_mode="entry_only")
    assert fixed["n_trades"] == res["n_trades"] and fixed["max_notional_ratio"] > 0.6   # 수량 고정은 상한을 넘는다
