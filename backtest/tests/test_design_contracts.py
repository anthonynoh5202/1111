"""설계 계약 테스트 (설계 담당): config 숫자·조합, 공용 소형 함수, 표준 프레임, conftest 도우미."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import config as C
from backtest import types as T
from backtest.tests.conftest import (aggregate_bars, bars_from_path, make_bars, make_exec_bars, make_funding,
                                     make_market, ns, random_walk_bars, split_bars, truncate_market)

# ---------------------------------------------------------------------------
# config: 명세 숫자 고정 (RULES_SPEC v1.0) — 실수로 바뀌지 않게
# ---------------------------------------------------------------------------


def test_spec_numbers_frozen():
    assert C.SPEC_VERSION == "v1.0"
    assert C.SETTINGS["P1"] == ("1h", "4h", "15m") and C.SETTINGS["P2"] == ("4h", "1d", "1h")  # §2
    assert (C.LATENCY_DEFAULT_MIN, C.LATENCY_SENSITIVITY_MIN) == (10, (5, 15))
    assert (C.ATR_N, C.VR_N, C.BODY_AVG_N, C.LONG_BAR_MULT, C.SWING_K) == (14, 20, 20, 2.0, 3)  # §3
    assert (C.SPREAD_LOOKBACK, C.SPREAD_QUANTILE, C.BUFFER_ATR_MULT) == (500, 0.80, 0.1)
    assert (C.KIJUN_VR_MIN, C.KIJUN_MAX_WICK, C.MADI_B_MAX_BARS, C.MADI_ALIVE_BARS) == (2.0, 0.5, 60, 300)  # §4
    assert (C.WAIST_BAND, C.WAIST_BIN_FRAC) == ((0.35, 0.65), 0.001)
    assert (C.F2_VR_MAX, C.F2_ATR_LOOKBACK, C.F5_LOOKBACK, C.F5_RANGE_ATR_MULT) == (0.7, 100, 5, 3.0)  # §6
    assert (C.F6_LOOKBACK, C.F6_RETURN_BARS, C.F6_MIN_TRAPS, C.F8_MAX_STOPS) == (48, 5, 2, 2)
    assert (C.L1A_VALID_BARS, C.L1B_ARM_BARS, C.S2_VALID_BARS, C.S3_VALID_BARS) == (24, 24, 12, 12)  # §7
    assert (C.L1B_ZONE_W, C.L1B_CAP_MULT, C.S3_LOOKBACK, C.S3_TOUCH_TOL) == (0.25, 1.001, 100, 0.001)
    assert (C.STOP_MIN_PCT, C.STOP_MAX_PCT, C.STOP_MIN_ATR, C.STOP_MAX_ATR, C.MIN_NET_RR) == (0.004, 0.02, 1.0, 3.0, 1.5)
    assert (C.FEE_MAKER, C.FEE_TAKER, C.SLIPPAGE, C.MAX_HOLD_BARS) == (0.0002, 0.0005, 0.0002, 72)  # §8.2, §12.2
    assert (C.RISK_FRACTION, C.MAX_NOTIONAL_FRAC, C.DAILY_APPROVAL_CAP) == (0.005, 0.6, 6)
    assert (C.G1_MIN_MEAN_R, C.G1_MIN_PF, C.G1_MIN_POSITIVE_YEARS, C.G1_MIN_TRADES) == (0.15, 1.2, 4, 30)  # §8.3
    assert C.G1_YEARS == (2020, 2021, 2022, 2023, 2024, 2025, 2026)
    assert (C.BOOTSTRAP_N, C.DSR_N_TRIALS, C.RANDOM_REPS, C.RANDOM_REPS_REDUCED) == (10_000, 16, 1_000, 300)  # §12.4
    assert C.DONCHIAN_PERIODS == (20, 55, 100)
    assert C.EXEC_SWITCH_NS == 1_696_118_400 * C.NS_PER_SEC                        # 2023-10-01 00:00 UTC
    assert C.FUNDING_FALLBACK_FROM_NS == ns("2026-09-01 00:00")


# ---------------------------------------------------------------------------
# config: 조합
# ---------------------------------------------------------------------------


def test_g1_combos_16_in_fixed_order():
    combos = C.g1_combos()
    assert len(combos) == 16
    assert len({c.key for c in combos}) == 16
    assert [c.base_key for c in combos[:4]] == ["L1a-DA-P1", "L1a-DA-P2", "L1a-DB-P1", "L1a-DB-P2"]
    assert combos[-1].base_key == "S3-DB-P2"
    assert all(c.apply_availability_mask and c.key.endswith("_exec") for c in combos)
    assert all(not c.apply_availability_mask and c.key.endswith("_all") for c in C.g1_combos(False))


def test_sensitivity_combos():
    sens = C.sensitivity_combos()
    assert len(sens) == 80
    tags = [t for t, _ in sens]
    assert tags[:5] == ["lat5", "lat15", "mid", "vr3", "cost2"]
    keys = [c.key for _, c in sens]
    assert len(set(keys)) == 80
    assert keys[:5] == ["L1a-DA-P1_lat5_exec", "L1a-DA-P1_lat15_exec", "L1a-DA-P1_mid_exec",
                        "L1a-DA-P1_vr3_exec", "L1a-DA-P1_cost2_exec"]
    assert all(c.apply_availability_mask for _, c in sens)


def test_combo_properties_and_validation():
    c = C.ComboConfig("L1b", "DB", "P2")
    assert c.bars.signal == "4h" and c.side == +1 and c.order_type == "ioc_cap"
    assert c.latency_ns == 10 * C.NS_PER_MIN and c.s_dur_ns == 4 * C.NS_PER_HOUR
    assert c.max_hold_ns == 72 * 4 * C.NS_PER_HOUR
    assert C.ComboConfig("S2", "DA", "P1").side == -1
    assert c.replace(latency_min=5, event_filter_on=True).variant == "lat5_ev"
    d = c.as_dict()
    assert d["key"] == "L1b-DB-P2_exec" and d["scenario"] == "L1b"
    for bad in (dict(scenario="L2"), dict(direction_filter="DC"), dict(setting="P3"),
                dict(waist_method="median"), dict(latency_min=-1), dict(vr_threshold=0.0),
                dict(cost_multiplier=-1.0)):
        kw = dict(scenario="L1a", direction_filter="DA", setting="P1") | bad
        with pytest.raises(ValueError):
            C.ComboConfig(**kw)
    with pytest.raises(Exception):
        c.latency_min = 5  # frozen
    # L1b 재준비 진단(보고용, 검토 SPEC-L1B-REARM): L1b 전용, 꼬리표 'rearm', 민감도 80개에는 없음
    r = c.replace(**C.L1B_REARM_VARIANT[1])
    assert r.l1b_rearm and r.variant == "rearm" and r.key == "L1b-DB-P2_rearm_exec" and r.as_dict()["l1b_rearm"]
    assert not c.l1b_rearm and c.as_dict()["l1b_rearm"] is False
    with pytest.raises(ValueError):
        C.ComboConfig("S2", "DA", "P1", l1b_rearm=True)
    assert all(not cfg.l1b_rearm for _, cfg in C.sensitivity_combos())


# ---------------------------------------------------------------------------
# config: 공용 소형 함수
# ---------------------------------------------------------------------------


def test_round_price():
    assert C.round_price(7189.43) == 7189.4
    assert C.round_price(7189.46) == 7189.5
    assert isinstance(C.round_price(1.0), float)
    np.testing.assert_array_equal(C.round_price(np.array([1.04, 2.06])), [1.0, 2.1])


def test_cost_formulas_hand_computed():
    assert C.entry_fee_rate("limit") == C.FEE_MAKER
    assert C.entry_fee_rate("ioc_cap") == C.entry_fee_rate("market") == C.FEE_TAKER
    with pytest.raises(ValueError):
        C.entry_fee_rate("stop")
    # 롱 entry 100, stop 99, target 102, 지정가: c_stop = 0.02 + 0.0007×99 = 0.0893
    assert C.c_stop_per_unit(100.0, 99.0, C.FEE_MAKER) == pytest.approx(0.0893, abs=1e-12)
    assert C.risk_per_unit(100.0, 99.0, C.FEE_MAKER) == pytest.approx(1.0893, abs=1e-12)
    assert C.net_rr(+1, 100.0, 99.0, 102.0, C.FEE_MAKER) == pytest.approx((2 - 0.02 - 0.0204) / 1.0893, abs=1e-12)
    assert C.net_rr(+1, 100.0, 99.0, 101.5, C.FEE_MAKER) == pytest.approx(1.340035, abs=1e-6)
    # 숏 entry 100, stop 101, target 98
    assert C.net_rr(-1, 100.0, 101.0, 98.0, C.FEE_MAKER) == pytest.approx(
        (2 - 0.02 - 0.0196) / (1 + 0.02 + 0.0007 * 101), abs=1e-12)
    # 목표가 반대편이면 음수
    assert C.net_rr(+1, 100.0, 99.0, 99.5, C.FEE_MAKER) < 0


def test_time_helpers():
    assert C.ts_ns("2023-10-01") == C.EXEC_SWITCH_NS
    assert C.ts_ns(pd.Timestamp("2023-10-01 09:00", tz="Asia/Seoul")) == C.EXEC_SWITCH_NS
    assert C.ns_to_iso(C.EXEC_SWITCH_NS) == "2023-10-01T00:00:00Z"
    assert C.ns_to_iso(None) == ""
    # 방해 금지 KST [00:30, 07:30) = UTC [15:30, 22:30)
    assert bool(C.in_dnd(ns("2024-01-01 15:30")))
    assert not bool(C.in_dnd(ns("2024-01-01 15:29:59")))
    assert bool(C.in_dnd(ns("2024-01-01 22:29:59")))
    assert not bool(C.in_dnd(ns("2024-01-01 22:30")))
    np.testing.assert_array_equal(C.in_dnd(np.array([ns("2024-01-01 15:30"), ns("2024-01-01 10:00")])), [True, False])
    # KST 날짜: UTC 14:59는 전날, 15:00은 다음 날
    assert int(C.kst_day_index(ns("2024-01-01 15:00"))) == int(C.kst_day_index(ns("2024-01-01 14:59"))) + 1
    # 시간대가 하루를 빠짐없이 덮음
    minutes = np.arange(24 * 60) * C.NS_PER_MIN + ns("2024-01-01 15:00")  # KST 00:00부터
    names = [C.kst_session(int(t)) for t in minutes]
    assert names.count("night") == 7 * 60 and names.count("day") == 10 * 60 + 30
    assert names.count("evening") == 6 * 60 + 30


def test_asof_index():
    avail = np.array([10, 20, 30], dtype=np.int64)
    assert C.asof_index(avail, 9) == -1
    assert C.asof_index(avail, 20) == 1          # 사용 가능 시각과 같으면 사용
    assert C.asof_index(avail, 29) == 1
    np.testing.assert_array_equal(C.asof_index(avail, np.array([5, 10, 35])), [-1, 0, 2])
    # 1H 판단(마감+60초)에서 같은 순간 마감한 4H 봉은 쓴다 (I-1)
    d_close = np.array([ns("2024-01-01 04:00"), ns("2024-01-01 08:00")])
    s_close = ns("2024-01-01 04:00")
    assert C.asof_index(d_close + C.AVAIL_DELAY_NS, s_close + C.AVAIL_DELAY_NS) == 0
    assert C.asof_index(d_close + C.AVAIL_DELAY_NS, s_close + C.AVAIL_DELAY_NS - 1) == -1


def test_make_rng_deterministic():
    a = C.make_rng("random_baseline", "L1a-DA-P1_exec").random(5)
    b = C.make_rng("random_baseline", "L1a-DA-P1_exec").random(5)
    c = C.make_rng("random_baseline", "L1a-DA-P2_exec").random(5)
    np.testing.assert_array_equal(a, b)
    assert not np.array_equal(a, c)
    assert C.stable_seed("abc") == 891568578  # crc32 고정값


# ---------------------------------------------------------------------------
# types: 표준 프레임·자료형
# ---------------------------------------------------------------------------


def test_bars_frame_contract():
    df = make_bars([(100, 101, 99, 100.5), (100.5, 102, 100, 101)], tf="1h")
    assert list(df.columns) == list(T.BAR_COLUMNS)
    assert df.index.unit == "ns" and str(df.index.tz) == "UTC" and df.index.name == "open_time"
    assert df["open_ns"].iloc[0] == ns("2024-01-01")
    assert df["close_ns"].iloc[0] == ns("2024-01-01") + C.TF_NS["1h"]
    T.check_bars_frame(df, dur_ns=C.TF_NS["1h"])
    with pytest.raises(ValueError):
        T.check_bars_frame(df, dur_ns=C.TF_NS["4h"])
    bad = df.copy()
    bad.index = bad.index.as_unit("us")
    with pytest.raises(ValueError):
        T.check_bars_frame(bad)
    gap = pd.concat([df.iloc[:1], make_bars([(1, 2, 0.5, 1.5)], start="2024-01-01 05:00")])
    with pytest.raises(ValueError):
        T.check_bars_frame(gap)
    T.check_bars_frame(gap, contiguous=False)
    wrong = df.copy()
    wrong.loc[wrong.index[0], "high"] = 50.0
    with pytest.raises(ValueError):
        T.check_bars_frame(wrong)


def test_funding_frame_and_arrays():
    f = make_funding("2024-01-01 01:00", "2024-01-02 00:00")
    assert f["time_ns"].tolist() == [ns("2024-01-01 08:00"), ns("2024-01-01 16:00"), ns("2024-01-02 00:00")]
    T.check_funding_frame(f)
    fa = T.FundingArrays.from_frame(f)
    assert fa.time_ns.dtype == np.int64 and fa.rate.dtype == np.float64
    xb = T.ExecArrays.from_frame(make_bars(closes=[1, 2, 3], tf="1m"))
    assert len(xb) == 3 and xb.close_ns[0] == xb.open_ns[1]


def _plan(**kw) -> T.Plan:
    base = dict(plan_id="L1a_202401010100_1hU-202312311800", scenario="L1a", side=1,
                signal_time=ns("2024-01-01 01:00"), approval_time=ns("2024-01-01 01:01"),
                active_from=ns("2024-01-01 01:11"), order_type="limit", entry_price=100.0, stop=98.0,
                target=104.0, valid_until=ns("2024-01-02 01:00"), max_hold_ns=72 * C.NS_PER_HOUR,
                atr_at_signal=1.0)
    base.update(kw)
    return T.Plan(**base)


def test_plan_trade_signal_records():
    p = _plan(cancel_effective_time=ns("2024-01-01 05:01"), cancel_reason="close_below",
              cancel_rules=(T.CancelRule("close_below", 97.0, "종가 < A"),), madi_id="1hU-202312311800",
              meta={"A": 97.0})
    assert p.order_end == ns("2024-01-01 05:01")
    assert _plan().order_end == ns("2024-01-02 01:00")
    rec = p.as_record()
    assert rec["signal_time"] == "2024-01-01T01:00:00Z" and rec["signal_time_ns"] == p.signal_time
    assert rec["cancel_rules"] == "close_below:97.0" and '"A": 97.0' in rec["meta"]
    tr = T.TradeResult(plan_id=p.plan_id, scenario="L1a", side=1, order_type="limit",
                       signal_time=p.signal_time, approval_time=p.approval_time, active_from=p.active_from,
                       plan_entry=100.0, stop=98.0, target=104.0, status=T.Status.FILLED,
                       busy_until=ns("2024-01-01 03:00"), risk_per_unit=2.1, r_multiple=1.5, size_fraction=0.5,
                       entry_time=ns("2024-01-01 01:30"))
    assert tr.is_filled and tr.r_account == pytest.approx(0.75)
    rec = tr.as_record()
    assert rec["entry_time"] == "2024-01-01T01:30:00Z" and rec["exit_time"] == "" and rec["exit_time_ns"] is None
    log = T.SignalLog(time=p.approval_time, signal_time=p.signal_time, scenario="L1a", side=1,
                      status="discarded", reasons=T.sort_reasons(["RISK_RR", "F1", "F1"]))
    assert log.reasons == ("F1", "RISK_RR") and log.reason == "F1"
    assert T.records_frame([log])["reasons"].iloc[0] == "F1;RISK_RR"
    with pytest.raises(ValueError):
        T.sort_reasons(["F10"])
    with pytest.raises(ValueError):
        T.Candidate(log=T.SignalLog(time=0, signal_time=0, scenario="S3", side=-1, status="passed"), plan=None)
    assert T.REASON_ORDER.index("RISK_RR") < T.REASON_ORDER.index("F8")
    assert set(T.PRECOMPUTED_REASONS) | set(T.SEQUENTIAL_REASONS) == set(T.REASON_ORDER)


def test_to_jsonable():
    out = T.to_jsonable({"a": np.float64("nan"), "b": np.inf, "c": -np.inf, "d": np.int64(3),
                         "e": np.array([1.5, np.nan]), "f": np.bool_(True), "g": (1, 2)})
    assert out == {"a": None, "b": "inf", "c": "-inf", "d": 3, "e": [1.5, None], "f": True, "g": [1, 2]}


# ---------------------------------------------------------------------------
# conftest 도우미 계약
# ---------------------------------------------------------------------------


def test_make_bars_variants():
    a = make_bars(closes=[100, 101, 99], volume=[1, 2, 3], wick=0.01)
    assert a["open"].tolist() == [100, 100, 101] and a["volume"].tolist() == [1, 2, 3]
    assert a["high"].iloc[1] == pytest.approx(101 * 1.01)
    b = make_bars([(1, 2, 0.5, 1.5, 7.0)], tf="4h", start="2024-01-01 04:00")
    assert b["volume"].iloc[0] == 7.0 and b["close_ns"].iloc[0] - b["open_ns"].iloc[0] == C.TF_NS["4h"]
    with pytest.raises(ValueError):
        make_bars()
    p = bars_from_path([100, 110, 105], legs=[5, 5])
    assert len(p) == 11 and p["close"].iloc[5] == 110 and p["close"].iloc[-1] == 105


def test_random_walk_bars_valid_and_deterministic():
    a = random_walk_bars(3000, seed=3)
    b = random_walk_bars(3000, seed=3)
    pd.testing.assert_frame_equal(a, b)
    T.check_bars_frame(a, dur_ns=C.TF_NS["1h"])
    px = a[["open", "high", "low", "close"]].to_numpy()
    assert np.allclose(px * 10, np.round(px * 10))                     # 0.1 격자
    vr = a["volume"] / a["volume"].shift(1).rolling(20).mean()
    assert (vr >= 2).sum() > 5                                        # 거래량 급증이 있다


def test_split_then_aggregate_roundtrip():
    coarse = random_walk_bars(200, seed=5, tf="5m")
    fine = split_bars(coarse, "1m")
    assert len(fine) == 5 * len(coarse)
    back = aggregate_bars(fine, "5m")
    for col in ("open", "high", "low", "close", "open_ns", "close_ns"):
        np.testing.assert_array_equal(back[col].to_numpy(), coarse[col].to_numpy())
    np.testing.assert_allclose(back["volume"].to_numpy(), coarse["volume"].to_numpy(), rtol=1e-12)
    # 불완전 구간은 버린다: 1시간봉은 12개 5분봉이 다 있어야 함
    assert len(aggregate_bars(coarse.iloc[:30], "1h")) == 2


def test_make_market_consistency(market_small):
    m = market_small
    for tf, b in m.bars.items():
        T.check_bars_frame(b, dur_ns=C.TF_NS[tf])
    T.check_bars_frame(m.exec_bars, contiguous=True)
    ex = m.exec_bars
    k = int(np.searchsorted(ex["open_ns"].to_numpy(), ns("2023-10-01")))
    assert ex["close_ns"].iloc[k - 1] - ex["open_ns"].iloc[k - 1] == C.TF_NS["5m"]
    assert ex["close_ns"].iloc[k] - ex["open_ns"].iloc[k] == C.TF_NS["1m"]
    assert ex["close_ns"].iloc[k - 1] == ex["open_ns"].iloc[k]
    # 실행 봉을 합치면 각 간격 봉과 정확히 같다
    for tf in ("15m", "1h", "4h", "1d"):
        agg = aggregate_bars(ex, tf)
        ref = m.bars[tf]
        for col in ("open", "high", "low", "close", "open_ns"):
            np.testing.assert_array_equal(agg[col].to_numpy(), ref[col].to_numpy())
    assert m.events_ns is None and len(m.funding) == 150 * 3 + 1


def test_truncate_market(market_small):
    t = ns("2023-11-01 00:00")
    tm = truncate_market(market_small, t)
    assert all(b["close_ns"].max() <= t for b in tm.bars.values())
    assert tm.exec_bars["close_ns"].max() == t and tm.funding["time_ns"].max() <= t
    assert tm.bars["1d"]["close_ns"].iloc[-1] == t


def test_make_exec_bars_joins_and_rejects_gap():
    five = make_bars(closes=[1, 2], tf="5m", start="2024-01-01 00:00")      # 00:00~00:10
    one = make_bars(closes=[3, 4], tf="1m", start="2024-01-01 00:10")       # 00:10~00:12
    joined = make_exec_bars(five, one.iloc[:0], one)                        # 빈 프레임은 무시
    assert len(joined) == 4
    assert (joined["close_ns"] - joined["open_ns"]).tolist() == [C.TF_NS["5m"]] * 2 + [C.TF_NS["1m"]] * 2
    late = make_bars(closes=[3, 4], tf="1m", start="2024-01-01 00:11")      # 1분 빈 구간
    with pytest.raises(ValueError):
        make_exec_bars(five, late)


def test_conftest_importable_as_module():
    import backtest.tests.conftest as cf
    assert cf.make_bars is make_bars
