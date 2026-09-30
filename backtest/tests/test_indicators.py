"""지표 테스트 (T-IND, DESIGN §9) — 손으로 계산할 수 있는 작은 합성 데이터 위주.

- 각 지표 값의 손 계산 예, 경계(동률·0 나눗셈·NaN), 현재 봉 제외 규칙(C-3)
- 전체 열을 느린 기준 구현(봉마다 창을 직접 잘라 계산)과 비교
- 앞부분 절단·미래 변경 불변 (미래 참조 없음, C-12)
- 스윙 고저의 엄격성과 확정 지연 (i+2 시점에는 보이지 않음, C-4)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import config as C
from backtest import indicators as I
from backtest import types as T
from backtest.tests.conftest import make_bars, random_walk_bars

NAN = np.nan


# ---------------------------------------------------------------------------
# 느린 기준 구현 (정의를 문자 그대로: 봉마다 창을 잘라 계산)
# ---------------------------------------------------------------------------


def _naive_trailing_mean(x, n):
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), NAN)
    for t in range(n, len(x)):
        out[t] = np.mean(x[t - n:t])  # 창 [t−n, t−1], NaN이 있으면 NaN
    return out


def _naive_trailing_quantile(x, n, q):
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), NAN)
    for t in range(n, len(x)):
        out[t] = np.quantile(x[t - n:t], q)
    return out


def _naive_indicators(bars: pd.DataFrame) -> dict[str, np.ndarray]:
    """RULES_SPEC §3·DESIGN §6.4를 봉 단위 반복으로 그대로 옮긴 기준 구현."""
    o, h, l, c, v = (bars[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close", "volume"))
    n = len(c)
    body = np.abs(c - o)
    rng = h - l
    tr = np.full(n, NAN)
    for t in range(1, n):
        tr[t] = max(h[t] - l[t], abs(h[t] - c[t - 1]), abs(l[t] - c[t - 1]))
    atr = _naive_trailing_mean(tr, 14)
    vol_avg = _naive_trailing_mean(v, 20)
    vr = np.full(n, NAN)
    for t in range(n):
        if vol_avg[t] > 0:
            vr[t] = v[t] / vol_avg[t]
    body_avg = _naive_trailing_mean(body, 20)
    upper = np.zeros(n)
    lower = np.zeros(n)
    for t in range(n):
        if rng[t] > 0:
            upper[t] = (h[t] - max(o[t], c[t])) / rng[t]
            lower[t] = (min(o[t], c[t]) - l[t]) / rng[t]
    ma = {p: _naive_trailing_mean(c, p) for p in (20, 60, 120)}
    spread = np.full(n, NAN)
    for t in range(n):
        vals = [ma[20][t], ma[60][t], ma[120][t]]
        if not np.isnan(vals).any():
            spread[t] = (max(vals) - min(vals)) / c[t]
    spread_q80 = _naive_trailing_quantile(spread, 500, 0.8)
    slope = {}
    for p in (20, 60, 120):
        s = np.full(n, NAN)
        for t in range(p, n):
            s[t] = 1.0 if c[t] > c[t - p] else (-1.0 if c[t] < c[t - p] else 0.0)
        slope[p] = s
    atr_q20 = _naive_trailing_quantile(atr, 100, 0.2)

    def ge(a, b):  # NaN이면 False
        return np.array([bool(x >= y) if not (np.isnan(x) or np.isnan(y)) else False for x, y in zip(a, b)])

    valid = np.ones(n, dtype=bool)
    for arr in (atr, vr, body_avg, ma[120], spread_q80, slope[120], atr_q20):
        valid &= ~np.isnan(arr)
    return {
        "body": body, "range": rng, "tr": tr, "atr": atr, "vol_avg": vol_avg, "vr": vr, "body_avg": body_avg,
        "long_bar": ge(body, 2 * body_avg), "upper_wick": upper, "lower_wick": lower,
        "ma20": ma[20], "ma60": ma[60], "ma120": ma[120], "spread": spread, "spread_q80": spread_q80,
        "spread_on": ge(spread, spread_q80), "slope20": slope[20], "slope60": slope[60], "slope120": slope[120],
        "atr_q20": atr_q20, "surge": ge(rng, 3 * atr), "buffer": 0.1 * atr, "valid": valid,
    }


def _ladder_bars(n: int = 40) -> pd.DataFrame:
    """TR[t] = t 인 봉: 시가 = 종가 = 100, 고가·저가 = 100 ± t/2 (직전 종가 100이라 갭 없음)."""
    t = np.arange(n, dtype=float)
    rows = [(100.0, 100.0 + x / 2, 100.0 - x / 2, 100.0) for x in t]
    return make_bars(rows, tf="1h")


# ---------------------------------------------------------------------------
# T-IND-1: trailing_mean
# ---------------------------------------------------------------------------


def test_trailing_mean_example():
    np.testing.assert_array_equal(I.trailing_mean([1, 2, 3, 4, 5], 2), [NAN, NAN, 1.5, 2.5, 3.5])


def test_trailing_mean_nan_window_short_input_and_bad_n():
    out = I.trailing_mean([1, NAN, 3, 4, 5, 6], 2)
    np.testing.assert_array_equal(out, [NAN, NAN, NAN, NAN, 3.5, 4.5])  # 창에 NaN이 있으면 NaN
    assert np.isnan(I.trailing_mean([1.0, 2.0], 5)).all()
    assert I.trailing_mean([], 3).shape == (0,)
    for bad in (0, -1, 2.5):
        with pytest.raises(ValueError):
            I.trailing_mean([1.0, 2.0, 3.0], bad)


def test_trailing_mean_matches_naive(rng):
    x = rng.normal(30000, 1000, 400)
    x[:7] = NAN
    x[200] = NAN
    for n in (1, 14, 20, 120):
        np.testing.assert_allclose(I.trailing_mean(x, n), _naive_trailing_mean(x, n), rtol=1e-12, equal_nan=True)


# ---------------------------------------------------------------------------
# T-IND-2: true_range · atr · buffer · surge
# ---------------------------------------------------------------------------


def test_true_range_hand_cases():
    bars = make_bars([
        (100, 102, 99, 101),   # 0: 직전 종가 없음 → NaN
        (101, 103, 100, 102),  # 1: 보통 봉 → max(3, 2, 1) = 3
        (105, 107, 104, 106),  # 2: 위로 갭(직전 종가 102) → max(3, 5, 2) = 5
        (100, 101, 98, 99),    # 3: 아래로 갭(직전 종가 106) → max(3, 5, 8) = 8
    ])
    tr = I.true_range(bars["high"].to_numpy(), bars["low"].to_numpy(), bars["close"].to_numpy())
    np.testing.assert_array_equal(tr, [NAN, 3.0, 5.0, 8.0])
    with pytest.raises(ValueError):
        I.true_range(np.ones(3), np.ones(2), np.ones(3))


def test_atr_is_mean_of_previous_14_tr_excluding_current():
    ind = I.compute_indicators(_ladder_bars(40))
    tr, atr = ind["tr"].to_numpy(), ind["atr"].to_numpy()
    np.testing.assert_array_equal(tr[1:], np.arange(1, 40, dtype=float))  # TR[t] = t
    assert np.isnan(tr[0])
    assert np.isnan(atr[:15]).all()                  # atr[14]까지 NaN (tr[0]이 NaN, I-4)
    assert atr[15] == pytest.approx(7.5)             # mean(tr[1..14]) = mean(1..14)
    assert atr[16] == pytest.approx(8.5)             # mean(tr[2..15])
    np.testing.assert_allclose(atr[15:], np.arange(15, 40) - 7.5)  # mean(t−14..t−1) = t − 7.5
    np.testing.assert_allclose(ind["buffer"].to_numpy()[15:], 0.1 * (np.arange(15, 40) - 7.5))  # b = 0.1 × ATR


def test_atr_ignores_current_bar_tr():
    base = _ladder_bars(30)
    changed = base.copy()
    changed.loc[changed.index[20], "high"] = 200.0   # 봉 20의 TR만 크게
    a0 = I.compute_indicators(base)["atr"].to_numpy()
    a1 = I.compute_indicators(changed)["atr"].to_numpy()
    assert a1[20] == a0[20]                          # 현재 봉 TR은 ATR에 안 들어감 (§3 "직전 14개")
    assert a1[21] > a0[21]                           # 다음 봉부터 반영


def test_surge_uses_own_atr_and_boundary_is_inclusive():
    rows = [(100.0, 100.0 + x / 2, 100.0 - x / 2, 100.0) for x in range(30)]
    rows[20] = (100.0, 118.75, 81.25, 100.0)          # 범위 37.5 = 3 × atr[20](= 12.5) → 경계 포함 True
    rows[25] = (100.0, 118.0, 82.0, 100.0)            # 범위 36 < 3 × atr[25]
    ind = I.compute_indicators(make_bars(rows))
    atr, surge = ind["atr"].to_numpy(), ind["surge"].to_numpy()
    assert atr[20] == pytest.approx(12.5)
    assert surge[20]
    assert not surge[25] and atr[25] * 3 > 36
    assert not surge[:15].any()                       # ATR 없음(NaN) → False
    assert ind["surge"].dtype == bool


# ---------------------------------------------------------------------------
# T-IND-3: VR (현재 봉 제외 직전 20개 평균)
# ---------------------------------------------------------------------------


def test_vr_hand_value_and_window():
    vol = [10.0] * 20 + [30.0, 10.0]
    ind = I.compute_indicators(make_bars(closes=np.linspace(100, 110, 22), volume=vol))
    vr, vol_avg = ind["vr"].to_numpy(), ind["vol_avg"].to_numpy()
    assert np.isnan(vr[:20]).all()
    assert vol_avg[20] == 10.0 and vr[20] == 3.0      # 30 ÷ mean(직전 20개 = 10)
    assert vol_avg[21] == pytest.approx(11.0) and vr[21] == pytest.approx(10 / 11)


def test_vr_depends_on_previous_20_only():
    bars = random_walk_bars(120, seed=11)
    t = 80
    base = I.compute_indicators(bars)["vr"].to_numpy()
    far = bars.copy()
    far.loc[far.index[t - 21], "volume"] *= 50.0      # 창 밖(t−21) → vr[t] 불변
    near = bars.copy()
    near.loc[near.index[t - 1], "volume"] *= 50.0     # 창 안(t−1) → vr[t] 변함
    assert I.compute_indicators(far)["vr"].to_numpy()[t] == base[t]
    assert I.compute_indicators(near)["vr"].to_numpy()[t] < base[t]


def test_vr_nan_when_average_volume_zero():
    ind = I.compute_indicators(make_bars(closes=np.full(22, 100.0), volume=[0.0] * 20 + [5.0, 5.0]))
    assert np.isnan(ind["vr"].to_numpy()[20])          # 평균 0 → 계산 불가
    assert ind["vr"].to_numpy()[21] == pytest.approx(5.0 / 0.25)


# ---------------------------------------------------------------------------
# T-IND-4: 장대봉 · 꼬리 비율
# ---------------------------------------------------------------------------


def test_long_bar_boundary():
    rows = [(100.0, 101.5, 99.5, 101.0) if i % 2 == 0 else (101.0, 101.5, 99.5, 100.0) for i in range(20)]  # 몸통 1
    exact = make_bars(rows + [(100.0, 102.5, 99.5, 102.0)])    # 몸통 2 = 2 × 평균 1 → 장대봉(경계 포함)
    short = make_bars(rows + [(100.0, 102.5, 99.5, 101.99)])   # 몸통 1.99 → 아님
    ie, is_ = I.compute_indicators(exact), I.compute_indicators(short)
    assert ie["body_avg"].to_numpy()[20] == pytest.approx(1.0)
    assert bool(ie["long_bar"].to_numpy()[20]) is True
    assert bool(is_["long_bar"].to_numpy()[20]) is False
    assert not ie["long_bar"].to_numpy()[:20].any()            # body_avg NaN → False


def test_long_bar_ignores_current_body_in_average():
    rows = [(100.0, 101.5, 99.5, 101.0)] * 20 + [(100.0, 150.0, 99.0, 149.0)]
    ind = I.compute_indicators(make_bars(rows))
    assert ind["body_avg"].to_numpy()[20] == pytest.approx(1.0)  # 현재 봉(몸통 49) 제외
    assert ind["long_bar"].to_numpy()[20]


def test_wick_ratios_hand_values_and_zero_range():
    bars = make_bars([
        (100, 110, 95, 105),   # 양봉: 범위 15, 윗꼬리 (110−105)/15, 아랫꼬리 (100−95)/15
        (105, 106, 96, 99),    # 음봉: 범위 10, 윗꼬리 (106−105)/10 = 0.1, 아랫꼬리 (99−96)/10 = 0.3
        (100, 100, 100, 100),  # 범위 0 → 0, 0
    ])
    ind = I.compute_indicators(bars)
    np.testing.assert_allclose(ind["upper_wick"].to_numpy(), [1 / 3, 0.1, 0.0])
    np.testing.assert_allclose(ind["lower_wick"].to_numpy(), [1 / 3, 0.3, 0.0])
    np.testing.assert_array_equal(ind["range"].to_numpy(), [15.0, 10.0, 0.0])
    np.testing.assert_array_equal(ind["body"].to_numpy(), [5.0, 6.0, 0.0])
    unknown = T.make_bars_frame([0], [100.0], [NAN], [99.0], [100.0], [1.0], C.TF_NS["1h"])  # 범위를 모름 → NaN
    ind_u = I.compute_indicators(unknown)
    assert np.isnan(ind_u["upper_wick"].iloc[0]) and np.isnan(ind_u["lower_wick"].iloc[0])


# ---------------------------------------------------------------------------
# T-IND-5: 기울기
# ---------------------------------------------------------------------------


def test_slope_sign_ties_and_warmup():
    np.testing.assert_array_equal(I.slope_sign([10, 11, 10, 12, 9], 2), [NAN, NAN, 0.0, 1.0, -1.0])
    assert np.isnan(I.slope_sign([1.0, 2.0], 5)).all()
    closes = np.r_[np.linspace(100, 120, 130)]
    ind = I.compute_indicators(make_bars(closes=closes))
    for p in C.SLOPE_NS:
        s = ind[f"slope{p}"].to_numpy()
        assert np.isnan(s[:p]).all() and (s[p:] == 1.0).all()   # t < N은 NaN, 상승 경로는 +1
    flat = I.compute_indicators(make_bars(closes=np.full(130, 100.0)))
    assert (flat["slope20"].to_numpy()[20:] == 0.0).all()        # 동률 → 0 (상승도 하락도 아님, I-5)


# ---------------------------------------------------------------------------
# T-IND-6: trailing_quantile = naive np.quantile
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n,q", [(500, 0.8), (100, 0.2)])
def test_trailing_quantile_matches_naive(rng, n, q):
    x = rng.normal(0.0, 1.0, 1600).cumsum()
    x[:37] = NAN                    # 앞부분 NaN (워밍업)
    x[900] = NAN                    # 가운데 NaN → 그 값을 담은 창은 모두 NaN
    got = I.trailing_quantile(x, n, q)
    ref = _naive_trailing_quantile(x, n, q)
    np.testing.assert_array_equal(np.isnan(got), np.isnan(ref))
    ok = ~np.isnan(ref)
    assert ok.sum() > 100
    assert np.max(np.abs(got[ok] - ref[ok])) <= 1e-9
    assert np.isnan(got[901:901 + n]).all() and not np.isnan(got[901 + n])


def test_trailing_quantile_edges():
    x = np.array([3.0, 1.0, 2.0, 5.0, 4.0])
    np.testing.assert_array_equal(I.trailing_quantile(x, 3, 0.0), [NAN, NAN, NAN, 1.0, 1.0])  # 최솟값
    np.testing.assert_array_equal(I.trailing_quantile(x, 3, 1.0), [NAN, NAN, NAN, 3.0, 5.0])  # 최댓값
    np.testing.assert_allclose(I.trailing_quantile(x, 3, 0.5), [NAN, NAN, NAN, 2.0, 2.0], equal_nan=True)
    # linear: 창 [1, 2, 5] (정렬), q=0.8 → 위치 1.6 → 2 + 0.6 × 3 = 3.8
    assert I.trailing_quantile(x, 3, 0.8)[4] == pytest.approx(3.8)
    assert np.isnan(I.trailing_quantile(x, 10, 0.5)).all()
    with pytest.raises(ValueError):
        I.trailing_quantile(x, 3, 1.5)


# ---------------------------------------------------------------------------
# T-IND-7: 이평(현재 제외) · 확산
# ---------------------------------------------------------------------------


def test_moving_averages_exclude_current_bar_and_spread_hand_value():
    closes = np.arange(1, 201, dtype=float)            # close[t] = t + 1
    ind = I.compute_indicators(make_bars(closes=closes))
    t = 150
    assert ind["ma20"].to_numpy()[t] == pytest.approx(t - 9.5)     # mean(close[t−20..t−1]) = mean(t−19..t)
    assert ind["ma60"].to_numpy()[t] == pytest.approx(t - 29.5)
    assert ind["ma120"].to_numpy()[t] == pytest.approx(t - 59.5)
    assert ind["spread"].to_numpy()[t] == pytest.approx(50.0 / 151.0)  # (ma20 − ma120) ÷ close[t]
    assert np.isnan(ind["ma120"].to_numpy()[119]) and not np.isnan(ind["ma120"].to_numpy()[120])


def test_ma_ignores_current_close_but_spread_uses_it():
    bars = random_walk_bars(300, seed=5)
    t = 250
    base = I.compute_indicators(bars)
    mod = bars.copy()
    c = mod["close"].to_numpy(copy=True)
    c[t] *= 1.05
    mod["close"] = c
    mod.loc[mod.index[t], "high"] = max(mod["high"].iloc[t], c[t])
    ind = I.compute_indicators(mod)
    for col in ("ma20", "ma60", "ma120"):
        assert ind[col].to_numpy()[t] == base[col].to_numpy()[t]   # 현재 종가 제외 (I-2, T-IND-7)
    assert ind["spread"].to_numpy()[t] != base["spread"].to_numpy()[t]  # 분모 = 현재 종가


def test_spread_on_is_spread_at_or_above_q80():
    ind = I.compute_indicators(random_walk_bars(1300, seed=9))
    s, q, on = (ind[k].to_numpy() for k in ("spread", "spread_q80", "spread_on"))
    ok = ~np.isnan(q)
    np.testing.assert_array_equal(on[ok], s[ok] >= q[ok])
    assert not on[~ok].any()
    assert on[ok].any() and not on[ok].all()


# ---------------------------------------------------------------------------
# T-IND-8: 열 계약 · 첫 유효 봉 620 · 기준 구현과 전체 일치
# ---------------------------------------------------------------------------


def test_columns_dtypes_and_first_valid_index():
    bars = random_walk_bars(1500, seed=1)
    ind = I.compute_indicators(bars)
    assert list(ind.columns) == list(I.INDICATOR_COLUMNS)
    assert ind.index.equals(bars.index)
    for col in I.INDICATOR_COLUMNS:
        want = bool if col in I.BOOL_INDICATOR_COLUMNS else np.float64
        assert ind[col].dtype == want, col
    valid = ind["valid"].to_numpy()
    assert int(np.flatnonzero(valid)[0]) == 620 == I.FIRST_VALID_INDEX
    assert valid[620:].all()
    first = {c: int(np.flatnonzero(~np.isnan(ind[c].to_numpy()))[0])
             for c in I.INDICATOR_COLUMNS if c not in I.BOOL_INDICATOR_COLUMNS}
    assert first == {"body": 0, "range": 0, "tr": 1, "atr": 15, "vol_avg": 20, "vr": 20, "body_avg": 20,
                     "upper_wick": 0, "lower_wick": 0, "ma20": 20, "ma60": 60, "ma120": 120, "spread": 120,
                     "spread_q80": 620, "slope20": 20, "slope60": 60, "slope120": 120, "atr_q20": 115,
                     "buffer": 15}  # DESIGN §6.4 "첫 유효 t"


def test_all_columns_match_naive_reference():
    bars = random_walk_bars(1100, seed=21, burst_prob=0.03)
    ind = I.compute_indicators(bars)
    ref = _naive_indicators(bars)
    for col in I.INDICATOR_COLUMNS:
        got = ind[col].to_numpy()
        if col in I.BOOL_INDICATOR_COLUMNS:
            np.testing.assert_array_equal(got, ref[col], err_msg=col)
        else:
            np.testing.assert_allclose(got, ref[col], rtol=1e-12, atol=1e-12, equal_nan=True, err_msg=col)
    assert ind["long_bar"].any() and ind["surge"].any() and ind["spread_on"].any()


def test_short_input_is_all_warmup():
    ind = I.compute_indicators(random_walk_bars(50, seed=2))
    assert not ind["valid"].any() and np.isnan(ind["spread_q80"]).all()
    empty = I.compute_indicators(random_walk_bars(50, seed=2).iloc[:0])
    assert list(empty.columns) == list(I.INDICATOR_COLUMNS) and len(empty) == 0


# ---------------------------------------------------------------------------
# T-IND-9: 앞부분 절단·미래 변경 불변 (미래 참조 없음)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def walk_1300() -> pd.DataFrame:
    return random_walk_bars(1300, seed=4)


@pytest.mark.parametrize("k", [700, 1000])
def test_prefix_invariance(walk_1300, k):
    full = I.compute_indicators(walk_1300)
    part = I.compute_indicators(walk_1300.iloc[:k])
    pd.testing.assert_frame_equal(part, full.iloc[:k], check_exact=True)


def test_future_change_invariance(walk_1300):
    k = 900
    full = I.compute_indicators(walk_1300)
    fut = walk_1300.copy()
    for col, mult in (("open", 1.2), ("high", 1.3), ("low", 1.1), ("close", 1.2), ("volume", 7.0)):
        arr = fut[col].to_numpy(copy=True)
        arr[k:] *= mult
        fut[col] = arr
    changed = I.compute_indicators(fut)
    pd.testing.assert_frame_equal(changed.iloc[:k], full.iloc[:k], check_exact=True)
    assert not changed.iloc[k:].equals(full.iloc[k:])


# ---------------------------------------------------------------------------
# 스윙 고저 (§3, I-6) · 확정 지연 (C-4)
# ---------------------------------------------------------------------------


def test_swing_strict_inequality():
    h = np.array([1, 2, 3, 5, 3, 2, 1], dtype=float)
    is_sh, is_sl = I.swing_points(h, h)
    np.testing.assert_array_equal(np.flatnonzero(is_sh), [3])
    assert not is_sl.any()
    h2 = np.array([1, 2, 5, 5, 3, 2, 1, 0], dtype=float)          # 동률 → 스윙 아님
    assert not I.swing_points(h2, h2)[0].any()
    lows = np.array([5, 4, 3, 1, 3, 4, 5], dtype=float)
    np.testing.assert_array_equal(np.flatnonzero(I.swing_points(lows + 10, lows)[1]), [3])
    edge = np.array([1, 9, 2, 3, 4, 5, 6, 7, 8, 10, 1], dtype=float)  # 앞뒤 3개가 모자란 봉은 스윙 아님
    assert not I.swing_points(edge, edge)[0][[0, 1, 2, 8, 9, 10]].any()


def test_swing_confirmation_delay():
    high = np.array([10, 11, 12, 20, 12, 11, 10, 9, 8, 9, 10, 11], dtype=float)
    low = high - 1
    is_sh, _ = I.swing_points(high, low)
    i = 3
    assert np.flatnonzero(is_sh).tolist() == [i]
    last = I.last_confirmed_swing(is_sh)
    assert last[i + 2] == -1                                     # i+2 마감 시점에는 아직 모름
    assert last[i + 3] == i and (last[i + 3:] == i).all()        # i+3 마감에 확정
    assert (last[:i + 3] == -1).all()
    # 데이터를 i+2까지만 주면 스윙을 알 수 없고, i+3까지 주면 안다 (미래 참조 없음)
    assert not I.swing_points(high[:i + 3], low[:i + 3])[0].any()
    assert I.swing_points(high[:i + 4], low[:i + 4])[0][i]
    # 확정 시각 = 봉 i+3의 마감 시각
    bars = make_bars([(h - 0.5, h, lo, h - 0.5) for h, lo in zip(high, low)], tf="1h")
    conf = I.swing_confirm_ns(bars["close_ns"].to_numpy(), is_sh)
    assert conf[i] == bars["close_ns"].iloc[i + 3] == bars["open_ns"].iloc[i] + 4 * C.TF_NS["1h"]
    assert (np.delete(conf, i) == -1).all()


def test_last_confirmed_uses_only_past_bars(rng):
    high = rng.normal(0, 1, 400).cumsum() + 100
    low = high - rng.uniform(0.1, 1.0, 400)
    sh, sl = I.swing_points(high, low)
    full_h, full_l = I.last_confirmed_swing(sh), I.last_confirmed_swing(sl)
    assert sh.sum() > 10 and sl.sum() > 10
    for t in rng.integers(0, 400, 40):
        psh, psl = I.swing_points(high[:t + 1], low[:t + 1])      # t까지 마감된 봉만
        assert I.last_confirmed_swing(psh)[t] == full_h[t]
        assert I.last_confirmed_swing(psl)[t] == full_l[t]
    idx = np.flatnonzero(sh)
    for t in range(400):                                          # 정의 그대로: max{i : i + 3 ≤ t}
        cand = idx[idx + 3 <= t]
        assert full_h[t] == (cand.max() if cand.size else -1)


def test_swings_agree_with_structure_module():
    """structure.find_swings·last_confirmed(구조 팀)가 구현돼 있으면 같은 결과인지 확인한다 (단일 규칙 I-6)."""
    from backtest import structure as S
    bars = random_walk_bars(600, seed=13)
    h, l = bars["high"].to_numpy(), bars["low"].to_numpy()
    try:
        sh, sl = S.find_swings(h, l)
        last = S.last_confirmed(sh)
    except NotImplementedError:
        pytest.skip("structure.find_swings 아직 구현 전")
    mine_sh, mine_sl = I.swing_points(h, l)
    np.testing.assert_array_equal(sh, mine_sh)
    np.testing.assert_array_equal(sl, mine_sl)
    np.testing.assert_array_equal(last, I.last_confirmed_swing(mine_sh))
