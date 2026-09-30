"""필터 테스트 (DESIGN §9 T-FIL, RULES_SPEC §5 방향 필터·§6 F1~F7·§8.1 리스크 검사).

손 계산 사례 + 명세 문장을 그대로 옮긴 느린 참조 구현(F2·F5·F6)과의 무작위 대조.
"""
from __future__ import annotations

import numpy as np
import pytest

from backtest import config as C
from backtest import execution as X
from backtest import filters as F
from backtest import indicators as IND
from backtest import structure as S
from backtest.config import ComboConfig
from backtest.types import REASON_ORDER, Reason
from backtest.tests.conftest import make_bars, random_walk_bars
from backtest.tests.test_structure import madi_frame, make_ctx, make_ind, make_struct, mask



# ---------------------------------------------------------------------------
# 느린 참조 구현
# ---------------------------------------------------------------------------


def ref_trap_counts(close, low, high, last_sl, last_sh):
    n = len(close)
    done = [0] * n
    for j in range(1, n):
        for support in (True, False):
            ref = last_sl[j - 1] if support else last_sh[j - 1]
            if ref < 0:
                continue
            L = low[ref] if support else high[ref]
            brk = (close[j - 1] >= L > close[j]) if support else (close[j - 1] <= L < close[j])
            if not brk:
                continue
            for m in range(j + 1, min(j + 5, n - 1) + 1):
                if (close[m] > L) if support else (close[m] < L):
                    done[m] += 1
                    break
    return np.array([sum(done[max(t - 48, 0):t]) for t in range(n)])


# ---------------------------------------------------------------------------
# T-FIL-1·2 방향 필터 (§5)
# ---------------------------------------------------------------------------


def _d_setup():
    d_bars = make_bars(closes=[100.0] * 20, tf="4h")
    madis = madi_frame([dict(direction=1, a_idx=1, b_idx=2, a_price=90.0, b_price=110.0, h_cluster=100.0,
                             h_mid=100.5, end_idx=15),
                        dict(direction=-1, a_idx=6, b_idx=7, a_price=120.0, b_price=100.0, h_cluster=110.0,
                             h_mid=109.0, end_idx=18)], d_bars)
    return d_bars, madis


def test_direction_da_long_short_and_waist_method():
    d_bars, madis = _d_setup()                                    # 상승 마디: 살아 있음 5~15, H 100 (mid 100.5)
    close = np.full(20, 100.0)                                    # 하락 마디: 살아 있음 10~18, H 110 (mid 109)
    close[[8, 11, 12, 13, 14]] = [100.3, 109.5, 100.0, 110.0, 108.5]
    d_bars = d_bars.copy()
    d_bars["close"] = close
    d_bars["high"] = np.maximum(d_bars["high"], close)
    struct = make_struct(d_bars, madis, tf="4h")
    ind = make_ind(d_bars)
    lo, sh = F.direction_permission(d_bars, ind, struct, "DA", "cluster")
    assert lo[8] and not lo[12]                                   # 롱: 종가 > H 만 허용 (== H 는 아님)
    assert not lo[4] and not lo[16]                               # 마디 확정(tb=5) 전, end_idx 15 뒤
    assert sh[11] and not sh[13] and sh[14]                       # 숏: 종가 < H (110)
    assert not sh[9]                                              # 하락 마디 확정(tb=10) 전
    lo_m, sh_m = F.direction_permission(d_bars, ind, struct, "DA", "midpoint")
    assert not lo_m[8] and not sh_m[11] and sh_m[14]              # 허리 = h_mid (100.5 / 109.0)


def test_direction_db_slopes_and_ties():
    d_bars = make_bars(closes=[100.0] * 6, tf="4h")
    ind = make_ind(d_bars, slope60=[1, 1, 0, -1, -1, np.nan], slope120=[1, 0, 1, -1, 0, 1])
    lo, sh = F.direction_permission(d_bars, ind, make_struct(d_bars), "DB")
    assert lo.tolist() == [True, False, False, False, False, False]      # 동률(0)·NaN → 불허 (I-5)
    assert sh.tolist() == [False, False, False, True, False, False]
    with pytest.raises(ValueError):
        F.direction_permission(d_bars, ind, make_struct(d_bars), "DC")


def test_direction_at_asof_boundary_and_cache():
    s_bars = make_bars(closes=[100.0] * 48)                               # 1h 48개 → 4h 12개
    ctx = make_ctx(s_bars, d_slope=1.0)
    d_close = ctx.d_bars["close_ns"].to_numpy()
    q = np.array([d_close[3] + C.AVAIL_DELAY_NS, d_close[3] + C.AVAIL_DELAY_NS - 1, d_close[0] + C.AVAIL_DELAY_NS - 1])
    assert F.direction_asof_index(ctx, q).tolist() == [3, 2, -1]          # 마감+60초부터 사용 (I-1), 1ns 이르면 이전 봉
    lo, sh = F.direction_at(ctx, "DB", "cluster", q)
    assert lo.tolist() == [True, True, False] and not sh.any()            # as-of −1 → 둘 다 불허 (C-10)
    assert ("dir", "DB", "cluster") in ctx.cache
    # D 봉 3의 기울기만 반대로 바꾸면 경계 앞뒤 결과가 갈린다 (진행 중인 D 봉은 안 씀)
    ind = ctx.d_ind.copy()
    ind.loc[ind.index[3], ["slope60", "slope120"]] = -1.0
    ctx.d_ind = ind
    ctx.cache.clear()
    lo, sh = F.direction_at(ctx, "DB", "cluster", q[:2])
    assert lo.tolist() == [False, True] and sh.tolist() == [True, False]


# ---------------------------------------------------------------------------
# T-FIL-3·4 F2·F4·F5
# ---------------------------------------------------------------------------


def test_f2_needs_both_conditions_and_f4_f5():
    bars = make_bars(closes=[100.0] * 20)
    vr = np.full(20, 1.0)
    atr = np.full(20, 1.0)
    q20 = np.full(20, 0.5)
    vr[[3, 4, 5]] = [0.6, 0.6, 0.7]
    atr[[3, 4, 5, 6]] = [0.5, 0.6, 0.5, 0.4]                          # 3: 둘 다 → F2, 4: ATR 하위 아님, 5: VR 0.7(경계)
    surge = mask(20, [10])
    spread_on = mask(20, [7])
    ind = make_ind(bars, vr=vr, atr=atr, atr_q20=q20, surge=surge, spread_on=spread_on)
    fl = F.fixed_filter_flags(bars, ind, make_struct(bars))
    assert list(fl.columns) == list(F.FIXED_FLAG_COLUMNS) and (fl.dtypes == bool).all()
    assert fl.index.equals(bars.index)
    assert np.flatnonzero(fl["F2"]).tolist() == [3]                   # VR < 0.7 그리고 ATR ≤ 하위 20% 분위
    assert np.flatnonzero(fl["F4"]).tolist() == [7]
    assert np.flatnonzero(fl["F5"]).tolist() == [11, 12, 13, 14, 15]  # [t−5, t−1]: 급등 봉 자신은 아님 (I-16)


def test_fixed_flags_match_reference_random():
    bars = random_walk_bars(2500, seed=11)
    ind = IND.compute_indicators(bars)
    st = S.build_structure(bars, ind, "1h")
    fl = F.fixed_filter_flags(bars, ind, st)
    vr, atr, q = ind["vr"].to_numpy(), ind["atr"].to_numpy(), ind["atr_q20"].to_numpy()
    surge = ind["surge"].to_numpy()
    ref_f2 = [bool(vr[t] < 0.7 and atr[t] <= q[t]) for t in range(len(bars))]
    ref_f5 = [bool(surge[max(t - 5, 0):t].any()) for t in range(len(bars))]
    np.testing.assert_array_equal(fl["F2"].to_numpy(), ref_f2)
    np.testing.assert_array_equal(fl["F5"].to_numpy(), ref_f5)
    np.testing.assert_array_equal(fl["F4"].to_numpy(), ind["spread_on"].to_numpy())
    tc = F.trap_counts(bars, st)
    ref = ref_trap_counts(bars["close"].to_numpy(), bars["low"].to_numpy(), bars["high"].to_numpy(),
                          st.last_sl, st.last_sh)
    np.testing.assert_array_equal(tc, ref)
    assert tc.max() >= 2 and fl["F6"].any()
    np.testing.assert_array_equal(fl["F6"].to_numpy(), ref >= 2)


# ---------------------------------------------------------------------------
# T-FIL-5 F6 트랩
# ---------------------------------------------------------------------------


def _trap_bars(closes, swing_low_at=5, level=100.0, swing_high_at=None, high_level=None):
    rows = [[c, max(c, 101.0), min(c, 100.5), c, 100.0] for c in closes]
    rows[swing_low_at][2] = level                                      # 스윙 저점의 저가 = 기준 L
    if swing_high_at is not None:
        rows[swing_high_at][1] = high_level
    bars = make_bars(rows)
    n = len(bars)
    return bars, make_struct(bars, is_sl=mask(n, [swing_low_at]),
                             is_sh=mask(n, [swing_high_at]) if swing_high_at is not None else None)


def test_f6_trap_definition_and_window():
    closes = np.full(80, 101.0)
    closes[10] = 99.5                                                  # 이탈 (직전 101 ≥ 100 > 99.5)
    closes[11] = 99.8
    closes[12] = 100.5                                                 # 5봉 안 첫 복귀 → 완성 봉 12
    closes[20] = 99.0                                                  # 두 번째 이탈, 21에서 복귀
    bars, st = _trap_bars(closes)
    ev = F.trap_events(bars, st)
    assert ev[["break_idx", "done_idx"]].values.tolist() == [[10, 12], [20, 21]]
    assert ev["known_ns"].tolist() == bars["close_ns"].iloc[[12, 21]].tolist()   # 알게 된 시각 = 완성 봉 마감
    tc = F.trap_counts(bars, st)
    assert tc[12] == 0 and tc[13] == 1                                 # t에 완성된 트랩은 t+1부터 셈
    assert tc[21] == 1 and tc[22] == 2 and tc[60] == 2                 # 완성 봉 ∈ [t−48, t−1]
    assert tc[61] == 1 and tc[69] == 1 and tc[70] == 0
    fl = F.fixed_filter_flags(bars, make_ind(bars), st)
    assert not fl["F6"].iloc[21] and fl["F6"].iloc[22] and fl["F6"].iloc[60] and not fl["F6"].iloc[61]


def test_f6_not_a_trap_cases():
    closes = np.full(60, 101.0)
    closes[10:16] = 99.5                                               # 이탈 뒤 5봉(11~15) 안에 복귀 없음
    closes[16] = 100.5
    closes[30:32] = [99.0, 98.5]                                       # 31: 이미 아래에 있던 종가 → 이탈 아님
    closes[40] = 100.0                                                 # 종가 == L → 이탈 아님 (L > close 필요)
    closes[41] = 100.5
    bars, st = _trap_bars(closes)
    ev = F.trap_events(bars, st)
    assert ev["break_idx"].tolist() == [30]                            # 30은 이탈, 32 복귀
    assert ev["done_idx"].tolist() == [32]
    closes2 = np.full(20, 101.0)
    closes2[6] = 99.0                                                  # 스윙(5) 확정 전(8) 이탈 → 기준 없음
    closes2[7] = 101.0
    bars2, st2 = _trap_bars(closes2)
    assert len(F.trap_events(bars2, st2)) == 0


def test_f6_resistance_trap():
    closes = np.full(30, 100.0)
    closes[12:14] = [106.0, 106.5]                                     # 스윙 고점 105 위로 돌파 (13은 이미 위)
    closes[14] = 104.0                                                 # 5봉 안 아래로 복귀
    rows = [[c, max(c, 100.5), min(c, 99.5), c, 100.0] for c in closes]
    rows[5][1] = 105.0
    bars = make_bars(rows)
    st = make_struct(bars, is_sh=mask(30, [5]))
    ev = F.trap_events(bars, st)
    assert ev[["kind", "break_idx", "done_idx"]].values.tolist() == [["resistance", 12, 14]]
    assert F.trap_counts(bars, st)[15] == 1


# ---------------------------------------------------------------------------
# T-FIL-6·7 F7·F3·filter_reasons
# ---------------------------------------------------------------------------


def _reason_ctx(**kw):
    s_bars = make_bars(closes=[100.0] * 48)
    up = dict(direction=1, a_idx=2, b_idx=5, a_price=90.0, b_price=110.0, end_idx=30)     # 살아 있음: 8~30
    dn = dict(direction=-1, a_idx=12, b_idx=17, a_price=120.0, b_price=100.0, end_idx=40)  # 20~40
    return make_ctx(s_bars, s_madis=madi_frame([up, dn], s_bars), **kw)


def test_f7_by_side():
    ctx = _reason_ctx()
    idx = np.array([7, 8, 25, 35, 41])
    assert F.f7_block(ctx.s_struct, idx, +1).tolist() == [False, False, True, True, False]   # 롱: 살아 있는 하락 마디
    assert F.f7_block(ctx.s_struct, idx, -1).tolist() == [False, True, True, False, False]   # 숏: 살아 있는 상승 마디


def test_filter_reasons_codes_order_and_scenario_f7():
    flags = {"F2": mask(48, [25]), "F4": mask(48, [25]), "F5": mask(48, [26]), "F6": mask(48, [25, 27])}
    ctx = _reason_ctx(flags=flags, d_slope=-1.0)                       # DB: 숏만 허용
    close_ns = ctx.s_bars["close_ns"].to_numpy()
    s_idx = np.array([25, 26, 27, 44])
    appr = close_ns[s_idx] + C.AVAIL_DELAY_NS
    got = F.filter_reasons(ctx, ComboConfig("L1a", "DB", "P1"), s_idx, appr)
    assert got == [("F1", "F2", "F4", "F6", "F7"), ("F1", "F5", "F7"), ("F1", "F6", "F7"), ("F1",)]
    for rs in got:
        assert list(rs) == [r for r in REASON_ORDER if r in rs]        # REASON_ORDER 순서
    s2 = F.filter_reasons(ctx, ComboConfig("S2", "DB", "P1"), s_idx, appr)
    assert s2 == [("F2", "F4", "F6"), ("F5",), ("F6",), ()]            # S2: F7 없음 (§7.3), 숏 허용
    s3 = F.filter_reasons(ctx, ComboConfig("S3", "DB", "P1"), s_idx, appr)
    assert s3 == [("F2", "F4", "F6", "F7"), ("F5", "F7"), ("F6", "F7"), ()]
    assert F.filter_reasons(ctx, ComboConfig("S3", "DB", "P1"), np.array([], dtype=np.int64), np.array([])) == []


def test_event_filter_f3():
    e = C.ts_ns("2024-01-01 14:30")
    ev = np.array([e], dtype=np.int64)
    q = np.array([e - 2 * C.NS_PER_HOUR, e - 2 * C.NS_PER_HOUR - 1, e + C.NS_PER_HOUR, e + C.NS_PER_HOUR + 1, e])
    assert F.event_block(q, ev).tolist() == [True, False, True, False, True]    # [e−2h, e+1h] 양 끝 포함
    assert not F.event_block(q, None).any() and not F.event_block(q, np.array([], dtype=np.int64)).any()
    s_bars = make_bars(closes=[100.0] * 48)
    ctx = make_ctx(s_bars, events_ns=ev)
    s_idx = np.array([12, 20])                                         # 판단 13:01(블록), 21:01(아님)
    appr = s_bars["close_ns"].to_numpy()[s_idx] + C.AVAIL_DELAY_NS
    cfg = ComboConfig("L1a", "DB", "P1")
    assert F.filter_reasons(ctx, cfg, s_idx, appr) == [(), ()]         # 꺼져 있으면 F3 없음 (§10-2)
    assert F.filter_reasons(ctx, cfg.replace(event_filter_on=True), s_idx, appr) == [("F3",), ()]
    ctx.events_ns = None
    with pytest.raises(FileNotFoundError):
        F.filter_reasons(ctx, cfg.replace(event_filter_on=True), s_idx, appr)


# ---------------------------------------------------------------------------
# T-FIL-8·9 리스크 검사 (§8.1, §12.2)
# ---------------------------------------------------------------------------


def test_stop_band_boundaries():
    assert F.stop_band_ok(100.0, 99.6, 0.3)                            # d 0.4 = max(0.4%, 1×ATR 0.3)
    assert not F.stop_band_ok(100.0, 99.61, 0.3)                       # d 0.39
    assert F.stop_band_ok(100.0, 99.1, 0.3)                            # d 0.9 = min(2%, 3×0.3) (부동소수 경계 포함)
    assert not F.stop_band_ok(100.0, 99.09, 0.3)                       # d 0.91
    assert F.stop_band_ok(100.0, 100.4, 0.3)                           # 숏(손절이 위)도 |d|
    assert not F.stop_band_ok(100.0, 99.5, np.nan)
    ok = F.stop_band_ok(np.array([100.0, 100.0]), np.array([99.6, 99.61]), np.array([0.3, 0.3]))
    assert ok.tolist() == [True, False]
    for args in ((100.0, 99.6, 0.3), (100.0, 99.09, 0.3), (50000.0, 49700.0, 150.0)):
        assert F.stop_band_ok(*args) == X.stop_band_ok(*args)          # 체결 엔진 식이 단일 출처


def test_net_rr_and_risk_reasons_hand_computed():
    rr = (2.0 - 0.0002 * 100 - 0.0002 * 102) / (1.0 + 0.0002 * 100 + 0.0007 * 99)   # §12.2 식 그대로
    assert rr == pytest.approx(1.798953) and C.net_rr(1, 100.0, 99.0, 102.0, C.FEE_MAKER) == pytest.approx(rr)
    assert F.risk_reasons(1, 100.0, 99.0, 102.0, 0.5, "limit") == ()
    rr2 = (1.5 - 0.0002 * 100 - 0.0002 * 101.5) / (1.0 + 0.0002 * 100 + 0.0007 * 99)
    assert rr2 == pytest.approx(1.340035, abs=1e-6)
    assert F.risk_reasons(1, 100.0, 99.0, 101.5, 0.5, "limit") == (Reason.RISK_RR,)
    rr_ioc = (2.0 - 0.0005 * 100 - 0.0002 * 102) / (1.0 + 0.0005 * 100 + 0.0007 * 99)  # ioc_cap: 테이커 진입
    assert C.net_rr(1, 100.0, 99.0, 102.0, C.entry_fee_rate("ioc_cap")) == pytest.approx(rr_ioc)
    assert F.risk_reasons(1, 100.0, 99.0, 102.0, 0.2, "ioc_cap") == (Reason.RISK_STOP_BAND,)   # 3×0.2 < 1
    assert F.risk_reasons(-1, 100.0, 101.0, 98.0, 0.5, "limit") == ()                      # 숏 대칭
    assert F.risk_reasons(-1, 100.0, 101.0, 102.0, 0.5, "limit") == (Reason.RISK_RR,)      # 목표가 반대편
    assert F.risk_reasons(1, 100.0, 97.0, 101.0, 0.5, "limit") == (Reason.RISK_STOP_BAND, Reason.RISK_RR)
