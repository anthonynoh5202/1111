"""무작위 진입 기준선 테스트 (DESIGN §9 T-RB, RULES_SPEC §8.4·§12.4, I-40)."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from backtest import config as C
from backtest import execution as X
from backtest import random_baseline as RB
from backtest import types as T
from backtest.tests.conftest import make_bars, make_exec_bars, make_market, ns

CFG = C.ComboConfig("L1a", "DA", "P1")           # 실행 가능 모드, 지연 10분, 72시간 보유
NO_FUNDING = T.FundingArrays(time_ns=np.array([], dtype=np.int64), rate=np.array([], dtype=np.float64))


@pytest.fixture(scope="module")
def market():
    """75일 합성 시장: 2024-02-15 전 5분 실행 봉, 이후 1분 실행 봉, 8시간 펀딩 0.01%."""
    m = make_market(days=75, seed=4, start="2024-01-01", one_minute_from="2024-02-15")
    closes = m.bars["1h"]["close_ns"].to_numpy()[:-1]   # 마지막 마감(데이터 끝) 뒤에는 실행 봉이 없어 뺀다
    return m.exec_arrays(), m.funding_arrays(), closes


def mk_trade(entry_time, entry_price, side, stop_pct, target_pct, status=T.Status.FILLED) -> T.TradeResult:
    """기준으로 쓸 '실제' 체결 거래 (필요한 칸만 채움)."""
    stop = C.round_price(entry_price * (1 - side * stop_pct))
    target = C.round_price(entry_price * (1 + side * target_pct))
    t = ns(entry_time)
    return T.TradeResult(plan_id=f"base_{t}", scenario="L1a", side=side, order_type="limit", signal_time=t,
                         approval_time=t, active_from=t, plan_entry=entry_price, stop=stop, target=target,
                         status=status, busy_until=t, risk_per_unit=1.0,
                         entry_time=t if status == T.Status.FILLED else None,
                         entry_price=entry_price if status == T.Status.FILLED else None)


def base_trades(xb: T.ExecArrays) -> list[T.TradeResult]:
    """1~3월에 걸친 거래 12건(롱·숏 섞음, 손절 0.5~1.5%, 목표 0.8~3%)."""
    rng = np.random.default_rng(8)
    out = []
    for i, day in enumerate(["2024-01-05", "2024-01-09", "2024-01-20", "2024-01-28", "2024-02-02", "2024-02-11",
                             "2024-02-16", "2024-02-25", "2024-03-01", "2024-03-06", "2024-03-10", "2024-03-12"]):
        t = ns(f"{day} 13:15")
        j = int(np.searchsorted(xb.open_ns, t))
        side = 1 if i % 3 else -1
        out.append(mk_trade(t, float(xb.open[j]), side, float(rng.uniform(0.005, 0.015)),
                            float(rng.uniform(0.008, 0.03))))
    return out


# ---------------------------------------------------------------------------
# 달 번호·추출
# ---------------------------------------------------------------------------


def test_month_index():
    got = RB.month_index(np.array([ns("2024-01-15"), ns("2024-02-01 00:00"), ns("2024-01-31 23:59:59"),
                                   ns("2020-01-01"), ns("2026-09-28 23:59")]))
    np.testing.assert_array_equal(got, [2024 * 12, 2024 * 12 + 1, 2024 * 12, 2020 * 12, 2026 * 12 + 8])
    assert got.dtype == np.int64
    assert int(RB.month_index(ns("1970-01-01"))) == 1970 * 12


def test_draw_signal_closes_same_month_uniform_and_deterministic():
    daily = ns("2024-01-01") + C.NS_PER_DAY * np.arange(1, 92, dtype=np.int64)   # 일봉 마감 1/2 ~ 4/1
    months = np.repeat(RB.month_index(np.array([ns("2024-01-10"), ns("2024-02-10")])), 60_000).reshape(2, -1)
    draws = RB.draw_signal_closes(months, daily, np.random.default_rng(1))
    assert draws.shape == months.shape
    np.testing.assert_array_equal(RB.month_index(draws), months)                # 모두 같은 달
    jan = daily[RB.month_index(daily) == 2024 * 12]
    counts = pd.Series(draws[0]).value_counts()
    assert set(counts.index) == set(jan.tolist())                               # 그 달의 모든 마감이 뽑힌다
    assert counts.max() / counts.min() < 1.25                                   # 대략 균등
    again = RB.draw_signal_closes(months, daily, np.random.default_rng(1))
    np.testing.assert_array_equal(draws, again)
    with pytest.raises(ValueError):
        RB.draw_signal_closes(np.array([RB.month_index(ns("2024-06-01"))]), daily, np.random.default_rng(1))
    assert RB.draw_signal_closes(np.array([], dtype=np.int64), daily, np.random.default_rng(1)).shape == (0,)


# ---------------------------------------------------------------------------
# 거래 하나: 진입 시각·가격·비용 (I-40)
# ---------------------------------------------------------------------------


def _hand_market():
    """5분봉 10:00~, 10:15 봉 시가 30000, 10:20 봉에서 손절(29700) 닿음. 10:25부터는 1분봉."""
    five = make_bars([(29990.0, 30010.0, 29980.0, 30000.0), (30000.0, 30020.0, 29990.0, 30000.0),
                      (30000.0, 30030.0, 29990.0, 30010.0), (30000.0, 30050.0, 29950.0, 30000.0),
                      (30000.0, 30010.0, 29650.0, 29680.0)], start="2023-06-01 10:00", tf="5m")
    one = make_bars([(29680.0, 29700.0, 29600.0, 29650.0)] * 30, start="2023-06-01 10:25", tf="1m")
    return T.ExecArrays.from_frame(make_exec_bars(five, one))


def test_market_trade_entry_is_first_open_after_close_plus_60s_plus_latency():
    xb = _hand_market()
    tr = RB.simulate_market_trade(1, ns("2023-06-01 10:00"), 0.01, 0.02, xb, NO_FUNDING, CFG)
    assert tr.order_type == "market" and tr.approval_time == ns("2023-06-01 10:01")
    assert tr.active_from == ns("2023-06-01 10:11")
    assert tr.entry_time == ns("2023-06-01 10:15") and tr.entry_price == 30000.0   # 10:11 뒤 첫 5분봉 시가
    assert (tr.stop, tr.target) == (29700.0, 30600.0)
    assert (tr.exit_reason, tr.exit_price) == (T.Exit.STOP, 29700.0)
    assert tr.fees == pytest.approx(0.0005 * 30000 + 0.0005 * 29700, abs=1e-9)    # 진입도 테이커
    assert tr.risk_per_unit == pytest.approx(300 + 0.0005 * 30000 + 0.0007 * 29700, abs=1e-9)
    assert tr.r_multiple == pytest.approx(-1.0, abs=1e-12)
    short = RB.simulate_market_trade(-1, ns("2023-06-01 10:00"), 0.01, 0.02, xb, NO_FUNDING, CFG)
    assert (short.stop, short.target) == (30300.0, 29400.0)
    lat5 = RB.simulate_market_trade(1, ns("2023-06-01 10:14"), 0.01, 0.02, xb, NO_FUNDING,
                                    CFG.replace(latency_min=5))              # 10:15 + 5분 = 10:20 봉
    assert lat5.entry_time == ns("2023-06-01 10:20") and lat5.entry_price == 30000.0
    one_min = RB.simulate_market_trade(1, ns("2023-06-01 10:30"), 0.01, 0.02, xb, NO_FUNDING, CFG)
    assert one_min.entry_time == ns("2023-06-01 10:41")                        # 1분봉 구간: 정확히 +11분
    late = RB.simulate_market_trade(1, ns("2023-06-01 10:50"), 0.01, 0.02, xb, NO_FUNDING, CFG)
    assert late.status == T.Status.NOT_FILLED                                  # 활성 뒤 실행 봉 없음


def test_batch_matches_single_trade(market):
    xb, fa, closes = market
    rng = np.random.default_rng(2)
    k = 150
    side = rng.choice([1, -1], k)
    pick = rng.choice(closes[:-2], k)
    sp = rng.uniform(0.003, 0.02, k)
    tp = rng.uniform(0.005, 0.04, k)
    for cfg in (CFG, C.ComboConfig("S2", "DB", "P2", cost_multiplier=2.0)):
        sim = RB.simulate_market_batch(side, pick, sp, tp, xb, fa, cfg)
        for i in range(k):
            tr = RB.simulate_market_trade(int(side[i]), int(pick[i]), float(sp[i]), float(tp[i]), xb, fa, cfg)
            assert bool(sim["filled"][i]) == tr.is_filled
            if not tr.is_filled:
                assert np.isnan(sim["r"][i]) and tr.status == T.Status.NOT_FILLED
                continue
            assert sim["entry_price"][i] == tr.entry_price and sim["stop"][i] == tr.stop
            assert sim["target"][i] == tr.target and sim["exit_reason"][i] == tr.exit_reason
            assert sim["exit_time"][i] == tr.exit_time and sim["exit_price"][i] == tr.exit_price
            assert sim["funding"][i] == pytest.approx(tr.funding, abs=1e-9)
            assert sim["r"][i] == pytest.approx(tr.r_multiple, abs=1e-9)
    assert set(sim["exit_reason"]) >= {T.Exit.STOP, T.Exit.TARGET}


# ---------------------------------------------------------------------------
# 분포 (run_random_baseline)
# ---------------------------------------------------------------------------


def test_preserves_month_side_and_distances(market):
    xb, fa, closes = market
    base = base_trades(xb)
    reps = 40
    out = RB.run_random_baseline(base, closes, xb, fa, CFG, n_reps=reps)
    # 같은 난수로 추출을 재현해 거래 단위로 확인
    months = RB.month_index(np.array([t.entry_time for t in base]))
    rng = C.make_rng("random_baseline", CFG.key)
    draws = RB.draw_signal_closes(np.broadcast_to(months, (reps, len(base))), closes, rng)
    side = np.array([t.side for t in base])
    entry = np.array([t.entry_price for t in base])
    sp = np.abs(entry - np.array([t.stop for t in base])) / entry
    tp = np.abs(np.array([t.target for t in base]) - entry) / entry
    sim = RB.simulate_market_batch(np.tile(side, reps), draws.ravel(), np.tile(sp, reps), np.tile(tp, reps),
                                   xb, fa, CFG)
    r = sim["r"].reshape(reps, -1)
    np.testing.assert_allclose(out["means"], r.mean(axis=1), rtol=0, atol=1e-12)  # 파이프라인 그대로
    assert sim["filled"].all()
    np.testing.assert_array_equal(RB.month_index(sim["entry_time"]), np.tile(months, reps))   # 같은 달
    np.testing.assert_array_equal(np.sign(sim["target"] - sim["entry_price"]), np.tile(side, reps))
    got_sp = np.abs(sim["entry_price"] - sim["stop"]) / sim["entry_price"]
    got_tp = np.abs(sim["target"] - sim["entry_price"]) / sim["entry_price"]
    tol = 0.05 / sim["entry_price"] + 1e-12                                     # 0.1 USDT 반올림 오차
    assert np.all(np.abs(got_sp - np.tile(sp, reps)) <= tol)
    assert np.all(np.abs(got_tp - np.tile(tp, reps)) <= tol)
    long_ = np.tile(side, reps) > 0
    assert np.all(sim["stop"][long_] < sim["entry_price"][long_])
    assert np.all(sim["stop"][~long_] > sim["entry_price"][~long_])
    assert out["n_trades"] == len(base) and out["n_not_filled"] == 0


def test_deterministic_and_key_dependent(market):
    xb, fa, closes = market
    base = base_trades(xb)
    a = RB.run_random_baseline(base, closes, xb, fa, CFG, n_reps=30)
    b = RB.run_random_baseline(base, pd.Series(closes), xb, fa, CFG, n_reps=30)   # Series도 받는다
    np.testing.assert_array_equal(a["means"], b["means"])
    assert a["seed_parts"] == ["random_baseline", "L1a-DA-P1_exec"]
    other = RB.run_random_baseline(base, closes, xb, fa, CFG.replace(direction_filter="DB"), n_reps=30)
    assert not np.array_equal(a["means"], other["means"])                         # 키가 다르면 시드도 다름
    explicit = RB.run_random_baseline(base, closes, xb, fa, CFG, n_reps=30,
                                      rng=C.make_rng("random_baseline", CFG.key))
    np.testing.assert_array_equal(a["means"], explicit["means"])


def test_quantiles_and_summary_fields(market):
    xb, fa, closes = market
    out = RB.run_random_baseline(base_trades(xb), closes, xb, fa, CFG, n_reps=60)
    means = out["means"]
    assert out["reps"] == 60 and means.shape == (60,) and np.isfinite(means).all()
    assert out["p95"] == float(np.quantile(means, 0.95))
    assert out["p05"] == float(np.quantile(means, 0.05)) and out["p50"] == float(np.quantile(means, 0.5))
    assert out["mean"] == pytest.approx(float(means.mean()), abs=1e-15)
    assert out["p05"] <= out["p50"] <= out["p95"]


def test_zero_trades_and_unfilled_base_trades_ignored(market):
    xb, fa, closes = market
    empty = RB.run_random_baseline([], closes, xb, fa, CFG, n_reps=10)
    assert empty["means"].shape == (0,) and empty["n_trades"] == 0 and empty["n_not_filled"] == 0
    assert all(np.isnan(empty[k]) for k in ("mean", "p05", "p50", "p95"))
    unfilled = mk_trade("2024-01-05 13:15", 30000.0, 1, 0.01, 0.02, status=T.Status.EXPIRED)
    assert RB.run_random_baseline([unfilled], closes, xb, fa, CFG, n_reps=10)["n_trades"] == 0
    base = base_trades(xb)
    with_unfilled = RB.run_random_baseline(base[:3] + [unfilled], closes, xb, fa, CFG, n_reps=10)
    only_filled = RB.run_random_baseline(base[:3], closes, xb, fa, CFG, n_reps=10)
    assert with_unfilled["n_trades"] == 3
    np.testing.assert_array_equal(with_unfilled["means"], only_filled["means"])


def test_draws_after_exec_data_end_are_not_filled(market):
    xb, fa, closes = market
    cut = int(np.searchsorted(xb.open_ns, ns("2024-03-14 12:00")))              # 실행 봉을 3/14 12:00에서 자름
    short_xb = T.ExecArrays(*(getattr(xb, f)[:cut] for f in ("open_ns", "close_ns", "open", "high", "low", "close")))
    base = [mk_trade("2024-03-02 13:15", float(xb.open[int(np.searchsorted(xb.open_ns, ns("2024-03-02 13:15")))]),
                     1, 0.01, 0.02)]
    out = RB.run_random_baseline(base, closes, short_xb, fa, CFG, n_reps=400)   # 3월 마감 중 약 10%는 봉 없음
    assert 0 < out["n_not_filled"] < 400
    assert np.isnan(out["means"]).sum() == out["n_not_filled"]                   # 거래 1건 → 미체결 반복은 NaN
    finite = out["means"][np.isfinite(out["means"])]
    assert out["p95"] == float(np.quantile(finite, 0.95)) and out["mean"] == pytest.approx(finite.mean())


def test_cost_multiplier_lowers_mean_on_same_draws(market):
    xb, fa, closes = market
    base = base_trades(xb)
    one = RB.run_random_baseline(base, closes, xb, fa, CFG, n_reps=20, rng=np.random.default_rng(5))
    two = RB.run_random_baseline(base, closes, xb, fa, CFG.replace(cost_multiplier=2.0), n_reps=20,
                                 rng=np.random.default_rng(5))
    assert np.all(two["means"] < one["means"])


def test_speed_1000_reps(market):
    xb, fa, closes = market
    base = base_trades(xb) * 4                                                  # 48건 × 1,000회 = 48,000 거래
    t0 = time.perf_counter()
    out = RB.run_random_baseline(base, closes, xb, fa, CFG, n_reps=C.RANDOM_REPS)
    assert time.perf_counter() - t0 < 20.0
    assert out["reps"] == 1000 and out["means"].shape == (1000,)


def test_uses_same_exit_engine_as_execution(market, monkeypatch):
    """무작위 거래의 청산은 execution.scan_exit 그대로다 (창 크기를 바꿔도 결과 동일)."""
    xb, fa, closes = market
    base = base_trades(xb)
    a = RB.run_random_baseline(base, closes, xb, fa, CFG, n_reps=15)
    monkeypatch.setattr(X, "SCAN_WINDOW", 3)
    monkeypatch.setattr(X, "SCAN_GROWTH", 2)
    b = RB.run_random_baseline(base, closes, xb, fa, CFG, n_reps=15)
    np.testing.assert_array_equal(a["means"], b["means"])


# ---------------------------------------------------------------------------
# 검토 반영: 펀딩 창(F3), 같은 진입 수수료 분포(F2, 보고용)
# ---------------------------------------------------------------------------


def test_market_funding_counts_from_activation_in_5m_era():
    """검토 F3: 5분봉 구간에서 활성 07:56 → 08:00 봉 시가 진입이면 08:00 펀딩을 낸다(활성 < f ≤ 청산). 단일·배열판 같음."""
    xb = T.ExecArrays.from_frame(make_bars([(30000.0, 30010.0, 29990.0, 30000.0)] * 24, start="2023-06-01 07:50",
                                           tf="5m"))
    fa = T.FundingArrays(time_ns=np.array([ns("2023-06-01 08:00")], dtype=np.int64), rate=np.array([0.0003]))
    tr = RB.simulate_market_trade(1, ns("2023-06-01 07:45"), 0.01, 0.02, xb, fa, CFG)   # 07:46 승인, 07:56 활성
    assert tr.active_from == ns("2023-06-01 07:56") and tr.entry_time == ns("2023-06-01 08:00")
    assert tr.funding == pytest.approx(0.0003 * 30000.0, abs=1e-12)
    sim = RB.simulate_market_batch(np.array([1, -1]), np.array([ns("2023-06-01 07:45")] * 2), 0.01, 0.02, xb, fa, CFG)
    np.testing.assert_allclose(sim["funding"], [9.0, -9.0], rtol=0, atol=1e-12)          # 숏은 받는다
    assert sim["r"][0] == pytest.approx(tr.r_multiple, abs=1e-12)


def test_same_fee_distribution_is_reported_not_judged(market):
    """검토 F2: 같은 추출·같은 청산에서 진입 수수료만 조합의 주문 형태 요율로 바꾼 분포(보고용).
    지정가 조합(L1a)은 메이커 요율로 분자·분모를 다시 계산하고, L1b(IOC = 테이커)는 판정 분포와 같다. 판정 p95는 그대로."""
    xb, fa, closes = market
    base = base_trades(xb)
    out = RB.run_random_baseline(base, closes, xb, fa, CFG, n_reps=25)
    assert out["same_fee"]["entry_fee_rate"] == C.FEE_MAKER
    rng = C.make_rng("random_baseline", CFG.key)                                # 같은 추출을 다시 만들어 손으로 확인
    months = RB.month_index(np.array([t.entry_time for t in base]))
    draws = RB.draw_signal_closes(np.broadcast_to(months, (25, len(base))), closes, rng)
    side = np.array([t.side for t in base])
    entry = np.array([t.entry_price for t in base])
    sp = np.abs(entry - np.array([t.stop for t in base])) / entry
    tp = np.abs(np.array([t.target for t in base]) - entry) / entry
    sim = RB.simulate_market_batch(np.tile(side, 25), draws.ravel(), np.tile(sp, 25), np.tile(tp, 25), xb, fa, CFG)
    is_t = sim["exit_reason"] == T.Exit.TARGET
    fees = C.FEE_MAKER * sim["entry_price"] + np.where(is_t, C.FEE_MAKER, C.FEE_TAKER) * sim["exit_price"]
    risk = np.abs(sim["entry_price"] - sim["stop"]) + C.FEE_MAKER * sim["entry_price"] + \
        (C.FEE_TAKER + C.SLIPPAGE) * sim["stop"]
    r_same = (sim["gross"] - fees - sim["slippage"] - sim["funding"]) / risk
    np.testing.assert_allclose(sim["r_same_fee"], r_same, rtol=0, atol=1e-12)
    means_same = r_same.reshape(25, -1).mean(axis=1)
    assert out["same_fee"]["p95"] == pytest.approx(float(np.quantile(means_same, 0.95)), abs=1e-12)
    assert out["p95"] == float(np.quantile(out["means"], 0.95))                  # 판정 분포는 그대로(테이커)
    assert out["same_fee"]["p95"] > out["p95"]                                   # 진입 수수료가 싸면 무작위도 좋아진다
    l1b = C.ComboConfig("L1b", "DA", "P1")
    o2 = RB.run_random_baseline(base, closes, xb, fa, l1b, n_reps=10)
    assert o2["same_fee"]["entry_fee_rate"] == C.FEE_TAKER and o2["same_fee"]["p95"] == o2["p95"]
    empty = RB.run_random_baseline([], closes, xb, fa, CFG, n_reps=10)
    assert np.isnan(empty["same_fee"]["p95"]) and empty["same_fee"]["entry_fee_rate"] == C.FEE_MAKER
