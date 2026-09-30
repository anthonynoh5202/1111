"""미래 참조 금지 테스트 (DESIGN §4 C-1~C-12, §9 T-NLA) — G1에서 가장 중요한 테스트.

실데이터(바이낸스 BTCUSDT, 2024-07-01까지)의 P1·P2로 검사한다.
1. 앞부분 불변: 봉 k개만 넣어 계산한 구조·필터 배열 = 전체로 계산한 것의 [0, k) (T-NLA-1)
2. 절단 불변: truncate_market(T)(close_ns ≤ T 인 봉만)으로 만든 후보 중 신호 시각 ≤ T 인 것
   = 전체 데이터로 만든 후보 중 신호 시각 ≤ T 인 것. 사유·가격·시각·meta까지 완전히 같다.
   취소 효력 시각: 전체 쪽 취소 봉이 T까지 마감됐으면 같고, 아니면 절단 쪽은 None (T-NLA-2).
   16조합 전부 + 민감도(허리 (고+저)÷2, VR 3, 지연 5분). T는 고정 시각 + "후보의 신호 봉이 마지막 봉이 되는" 시각.
3. 미래 변경 불변: T 뒤에 마감하는 봉(모든 간격)의 가격·거래량을 바꿔도 신호 시각 ≤ T 후보가 같다 (T-NLA-3).
4. as-of: 판단 시각 q에 쓰는 D 봉 j는 close[j] + 60초 ≤ q < close[j+1] + 60초 (T-NLA-4).
5. 체결: 청산 봉 뒤 실행 봉을 잘라내거나 활성 시각 전 실행 봉을 바꿔도 TradeResult가 같다 (T-NLA-5).
6. 끝까지 절단 불변(@slow): 후보 → 순차 엔진(F8·F9·방해 금지·하루 6건) → 체결·청산·펀딩 전체가 절단 시각 전
   결정·완료 거래·걸친 거래에서 같다 (실데이터 P1·P2, 16조합 × 두 모드 × 실제 후보·강제 계획) (T-NLA-6).
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from backtest import config as C
from backtest import execution as X
from backtest import filters as F
from backtest import indicators as IND
from backtest import scenarios as SC
from backtest import structure as ST
from backtest import types as T
from backtest.config import ComboConfig
from backtest.tests.conftest import truncate_market
from backtest.types import Reason

AVAIL = C.AVAIL_DELAY_NS
FULL_END = C.ts_ns("2024-07-01")
START = {"P1": C.ts_ns("2023-06-01"), "P2": C.ts_ns("2020-01-01")}   # P1: 4h D 워밍업 ~103일, P2: 일봉 D 워밍업(620일)
FIXED_T = ("2024-02-13 17:00", "2024-04-02 09:07", "2024-05-20 00:00", "2024-06-11 13:45")
SCENARIO_ORDER = C.SCENARIOS


# ---------------------------------------------------------------------------
# 데이터·비교 도우미
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_bars():
    from backtest import data as D
    try:
        bars = {tf: D.load_klines(tf) for tf in ("15m", "1h", "4h", "1d")}
    except FileNotFoundError as exc:
        pytest.skip(f"실데이터 없음: {exc}")
    return {tf: b[b["close_ns"] <= FULL_END] for tf, b in bars.items()}


def market_for(bars: dict, setting: str) -> T.MarketData:
    sel = {tf: b[b["open_ns"] >= START[setting]] for tf, b in bars.items()}
    empty_funding = T.make_funding_frame(np.array([], dtype=np.int64), np.array([], dtype=np.float64))
    return T.MarketData(bars=sel, exec_bars=sel["1h"], funding=empty_funding, events_ns=None)


def combos(setting: str) -> list[ComboConfig]:
    return [cfg for cfg in C.g1_combos() if cfg.setting == setting]


def _eq(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


def meta_equal(a: dict, b: dict) -> bool:
    return a.keys() == b.keys() and all(_eq(a[k], b[k]) for k in a)


def cancel_known(plan: T.Plan, t_ns: int) -> bool:
    """취소 조건이 성립한 신호 봉이 t_ns까지 마감했는가 (효력 = 그 봉 마감 + 60초)."""
    return plan.cancel_effective_time is not None and plan.cancel_effective_time - AVAIL <= t_ns


def assert_same_candidate(a: T.Candidate, b: T.Candidate, t_ns: int, mode: str) -> None:
    """a = 기준(전체), b = 절단/변경 쪽. 신호 시각 ≤ t_ns 인 후보끼리."""
    la, lb = a.log, b.log
    key = la.meta["cand_id"]
    for f in ("time", "signal_time", "scenario", "side", "status", "reasons", "plan_id", "madi_id"):
        assert getattr(la, f) == getattr(lb, f), (key, f, getattr(la, f), getattr(lb, f))
    assert meta_equal(la.meta, lb.meta), (key, la.meta, lb.meta)
    assert (a.plan is None) == (b.plan is None), key
    if a.plan is None:
        return
    pa, pb = a.plan, b.plan
    for f in dataclasses.fields(T.Plan):
        if f.name in ("cancel_effective_time", "cancel_reason", "meta"):
            continue
        assert getattr(pa, f.name) == getattr(pb, f.name), (key, f.name, getattr(pa, f.name), getattr(pb, f.name))
    assert meta_equal(pa.meta, pb.meta), key
    ka, kb = cancel_known(pa, t_ns), cancel_known(pb, t_ns)
    if mode == "trunc":
        if ka:                                                     # T까지 마감한 봉에서 성립한 취소는 같아야 한다
            assert (pb.cancel_effective_time, pb.cancel_reason) == (pa.cancel_effective_time, pa.cancel_reason), key
        else:                                                      # 모르는 취소를 미리 알면 미래 참조
            assert pb.cancel_effective_time is None and pb.cancel_reason is None, key
    else:
        assert ka == kb, key
        if ka:
            assert (pb.cancel_effective_time, pb.cancel_reason) == (pa.cancel_effective_time, pa.cancel_reason), key


def assert_same_upto(full: list[T.Candidate], other: list[T.Candidate], t_ns: int, mode: str) -> int:
    """신호 시각 ≤ t_ns 인 후보 목록이 (순서까지) 같은지. 비교한 후보 수를 돌려준다."""
    fa = [c for c in full if c.log.signal_time <= t_ns]
    fb = [c for c in other if c.log.signal_time <= t_ns]
    if mode == "trunc":
        assert len(fb) == len(other), "절단 데이터로 T 뒤의 신호가 나옴"
    ida = [c.log.meta["cand_id"] for c in fa]
    idb = [c.log.meta["cand_id"] for c in fb]
    assert len(set(ida)) == len(ida)
    missing, extra = sorted(set(ida) - set(idb))[:5], sorted(set(idb) - set(ida))[:5]
    assert ida == idb, f"후보 집합·순서 다름: 빠짐 {missing} / 더 있음 {extra}"
    for a, b in zip(fa, fb):
        assert_same_candidate(a, b, t_ns, mode)
    return len(fa)


def edge_times(full: dict[str, list[T.Candidate]], setting: str) -> list[int]:
    """시나리오마다 2024-01-15 ~ 2024-06-25 후보 하나의 신호 시각 (그 신호 봉이 절단 데이터의 마지막 봉이 됨).

    통과 후보가 있으면 그것을, 없으면 plan이 있는 후보를 고른다(결정적으로 가운데 것).
    """
    lo, hi = C.ts_ns("2024-01-15"), C.ts_ns("2024-06-25")
    out = []
    for scen in SCENARIO_ORDER:
        cands = [c for c in full[f"{scen}-DB-{setting}"] if lo <= c.log.signal_time <= hi and c.plan is not None]
        passed = [c for c in cands if not c.log.reasons]
        pick = passed or cands
        if pick:
            out.append(pick[len(pick) // 2].log.signal_time)
    return out


# ---------------------------------------------------------------------------
# T-NLA-2 절단 불변 (핵심)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def full_runs(real_bars):
    """설정별 전체 문맥과 16조합 후보 (절단·변경 테스트의 기준)."""
    out = {}
    for setting in C.SETTING_NAMES:
        market = market_for(real_bars, setting)
        ctx = SC.build_context(market, setting)
        cands = {cfg.base_key: SC.generate_candidates(ctx, cfg) for cfg in combos(setting)}
        out[setting] = (market, ctx, cands)
    return out


@pytest.mark.parametrize("setting", C.SETTING_NAMES)
def test_candidates_truncation_invariance_all_combos(full_runs, setting):
    market, _, full = full_runs[setting]
    t_list = [C.ts_ns(t) for t in FIXED_T] + edge_times(full, setting)
    assert len(t_list) >= len(FIXED_T) + 3
    compared = {k: 0 for k in full}
    near = {k: 0 for k in full}
    for t_ns in t_list:
        ctx_t = SC.build_context(truncate_market(market, t_ns), setting)
        for cfg in combos(setting):
            got = SC.generate_candidates(ctx_t, cfg)
            compared[cfg.base_key] += assert_same_upto(full[cfg.base_key], got, t_ns, "trunc")
            near[cfg.base_key] += sum(1 for c in got if t_ns - c.log.signal_time <= 24 * cfg.s_dur_ns)
    for key, n in compared.items():                               # 모든 조합에서 실제로 비교가 일어났는지
        assert n > 0, key
    # 절단 시각 바로 앞(24 신호 봉 안)의 후보도 충분히 비교됐는지 — 미래 참조가 드러나는 곳
    for scen in SCENARIO_ORDER:
        assert near[f"{scen}-DB-{setting}"] + near[f"{scen}-DA-{setting}"] > 0, (scen, setting)


def test_edge_cut_includes_signal_bar_as_last_bar(full_runs):
    """신호 봉이 절단 데이터의 마지막 봉일 때(T = 신호 시각) 그 후보가 그대로 나오고, 1ns 전이면 안 나온다."""
    market, _, full = full_runs["P1"]
    for scen in SCENARIO_ORDER:
        cands = [c for c in full[f"{scen}-DB-P1"] if C.ts_ns("2024-01-15") <= c.log.signal_time <= FULL_END - C.NS_PER_DAY]
        c = cands[len(cands) // 2]
        cfg = ComboConfig(scen, "DB", "P1")
        t_ns = c.log.signal_time
        at = SC.generate_candidates(SC.build_context(truncate_market(market, t_ns), "P1"), cfg)
        ids = [x.log.meta["cand_id"] for x in at]
        assert c.log.meta["cand_id"] == ids[-1] or c.log.meta["cand_id"] in ids
        before = SC.generate_candidates(SC.build_context(truncate_market(market, t_ns - 1), "P1"), cfg)
        assert c.log.meta["cand_id"] not in [x.log.meta["cand_id"] for x in before]


def _window_market(bars: dict, start_ns: int, end_ns: int) -> T.MarketData:
    sel = {tf: b[(b["open_ns"] >= start_ns) & (b["close_ns"] <= end_ns)] for tf, b in bars.items()}
    empty_funding = T.make_funding_frame(np.array([], dtype=np.int64), np.array([], dtype=np.float64))
    return T.MarketData(bars=sel, exec_bars=sel["1h"], funding=empty_funding, events_ns=None)


def _extreme_future(market: T.MarketData, t_ns: int, factor: float, vol_mult: float) -> T.MarketData:
    """T 뒤에 마감하는 봉(모든 간격)을 극단적으로 바꾼다: 가격 × factor(폭락 0.7 / 폭등 1.3), 거래량 × vol_mult.

    다음 봉을 몰래 보는 참/거짓 조건(기울기·종가·거래량 비교)은 이런 미래에서 뒤집혀 드러난다.
    """
    bars = {}
    for tf, b in market.bars.items():
        fut = b["close_ns"].to_numpy() > t_ns
        b = b.copy()
        for col, mult in (("open", factor), ("high", factor), ("low", factor), ("close", factor), ("volume", vol_mult)):
            v = b[col].to_numpy(copy=True)
            v[fut] = v[fut] * mult
            b[col] = v
        bars[tf] = b
    return T.MarketData(bars=bars, exec_bars=market.exec_bars, funding=market.funding, events_ns=None)


@pytest.mark.parametrize("setting,per_scen,days", [("P1", 6, 150), ("P2", 3, 240)])
def test_many_edge_cuts_short_windows(real_bars, full_runs, setting, per_scen, days):
    """후보의 신호 봉이 마지막 봉이 되게 자르는 시각(T = 신호 시각)을 시나리오마다 여러 개 검사한다.

    다음 봉 값을 쓰는 참/거짓 조건(예: 기울기·종가 비교)은 T가 바로 그 신호 봉이고 미래가 크게 다를 때 드러난다.
    시각마다 짧은 창 [T − days, T](절단)과 [T − days, T + 20일](미래를 폭락·폭등으로 바꿈, 같은 시작)으로
    문맥을 두 번 만들어 비교한다(시작이 같으면 T까지의 후보는 같아야 한다).
    """
    _, _, full = full_runs[setting]
    lo, hi = C.ts_ns("2024-01-20"), C.ts_ns("2024-06-10")
    picks = []
    for scen in SCENARIO_ORDER:
        cands = [c for c in full[f"{scen}-DB-{setting}"] if lo <= c.log.signal_time <= hi]
        idx = np.unique(np.linspace(0, len(cands) - 1, per_scen).round().astype(int))
        picks += [(scen, cands[i].log.signal_time) for i in idx]
    present = 0
    for n, (scen, t_ns) in enumerate(picks):
        start = (t_ns - days * C.NS_PER_DAY) // C.NS_PER_DAY * C.NS_PER_DAY   # UTC 자정 (일봉 경계)
        future = _window_market(real_bars, start, t_ns + 20 * C.NS_PER_DAY)
        crash_or_rally = _extreme_future(future, t_ns, 0.7 if n % 2 == 0 else 1.3, 10.0 if n % 2 == 0 else 0.1)
        ctx_f = SC.build_context(crash_or_rally, setting)
        ctx_t = SC.build_context(_window_market(real_bars, start, t_ns), setting)
        for fil in C.DIRECTION_FILTERS:
            cfg = ComboConfig(scen, fil, setting)
            got = SC.generate_candidates(ctx_t, cfg)
            assert_same_upto(SC.generate_candidates(ctx_f, cfg), got, t_ns, "trunc")
            present += any(c.log.signal_time == t_ns for c in got)   # (S3 ID의 sup{번호}는 창 시작에 따라 달라짐)
    assert present >= 0.9 * 2 * len(picks)                        # 짧은 창에서도 그 신호 봉의 후보가 마지막에 있다


def test_sensitivity_variants_truncation_invariance(full_runs, real_bars):
    """민감도 변형도 절단 불변: P2는 허리 (고+저)÷2·지연 5분·VR 3을 두 시각, P1은 허리 (고+저)÷2를 한 시각."""
    for setting, t_strs in (("P2", FIXED_T[0::2]), ("P1", FIXED_T[1:2])):
        market, ctx, _ = full_runs[setting]
        with_vr3 = setting == "P2"                                 # VR 3 문맥은 P2만 (P1은 시간 절약)
        ctx3 = SC.build_context(market, setting, C.KIJUN_VR_SENSITIVITY) if with_vr3 else None
        variants = []
        for cfg in combos(setting):
            variants.append((ctx, cfg.replace(waist_method="midpoint")))
            if with_vr3:                                           # P2: 지연 5분·VR 3도 (P1은 허리 방식만)
                variants.append((ctx, cfg.replace(latency_min=5)))
                variants.append((ctx3, cfg.replace(vr_threshold=C.KIJUN_VR_SENSITIVITY)))
        full = [SC.generate_candidates(cx, cfg) for cx, cfg in variants]
        for t_str in t_strs:
            t_ns = C.ts_ns(t_str)
            tm = truncate_market(market, t_ns)
            tctx = {2.0: SC.build_context(tm, setting)}
            if with_vr3:
                tctx[3.0] = SC.build_context(tm, setting, C.KIJUN_VR_SENSITIVITY)
            for (cx, cfg), fc in zip(variants, full):
                got = SC.generate_candidates(tctx[cfg.vr_threshold], cfg)
                assert_same_upto(fc, got, t_ns, "trunc")


# ---------------------------------------------------------------------------
# T-NLA-3 미래 변경 불변
# ---------------------------------------------------------------------------


def perturb_after(market: T.MarketData, t_ns: int, seed: int) -> T.MarketData:
    """T 뒤에 마감하는 봉(모든 간격)의 가격을 무작위 경로로 곱하고 거래량을 흔든다(각 봉 OHLC 논리는 유지)."""
    rng = np.random.default_rng(seed)
    bars = {}
    for tf, b in market.bars.items():
        b = b.copy()
        fut = b["close_ns"].to_numpy() > t_ns
        k = int(fut.sum())
        if k:
            f = np.exp(np.cumsum(rng.normal(0.0, 0.01, k)) + rng.normal(0.0, 0.05))
            for col in ("open", "high", "low", "close"):
                v = b[col].to_numpy(copy=True)
                v[fut] = v[fut] * f
                b[col] = v
            vol = b["volume"].to_numpy(copy=True)
            vol[fut] = vol[fut] * rng.lognormal(0.0, 1.0, k)
            b["volume"] = vol
            T.check_bars_frame(b, contiguous=True)
        bars[tf] = b
    return T.MarketData(bars=bars, exec_bars=market.exec_bars, funding=market.funding, events_ns=None)


@pytest.mark.parametrize("setting", C.SETTING_NAMES)
def test_candidates_future_modification_invariance(full_runs, setting):
    market, _, full = full_runs[setting]
    for i, t_str in enumerate(("2024-03-07 05:00", "2024-05-02 11:30")):
        t_ns = C.ts_ns(t_str)
        ctx_m = SC.build_context(perturb_after(market, t_ns, seed=100 + i), setting)
        changed_after = 0
        for cfg in combos(setting):
            got = SC.generate_candidates(ctx_m, cfg)
            assert_same_upto(full[cfg.base_key], got, t_ns, "modified")
            after_a = [c.log.meta["cand_id"] for c in full[cfg.base_key] if c.log.signal_time > t_ns]
            after_b = [c.log.meta["cand_id"] for c in got if c.log.signal_time > t_ns]
            changed_after += after_a != after_b
        assert changed_after > 0                                   # 변경이 실제로 미래 후보를 바꿨다(테스트가 헛돌지 않음)


# ---------------------------------------------------------------------------
# T-NLA-1 앞부분 불변 (구조·필터 배열)
# ---------------------------------------------------------------------------


def test_structure_and_filter_prefix_invariance(full_runs):
    _, ctx, _ = full_runs["P1"]
    bars, ind = ctx.s_bars, ctx.s_ind
    full_st = ctx.s_struct
    full_trap = F.trap_counts(bars, full_st)
    full_sup = SC.s3_support(ctx)
    m_full = full_st.madis
    n = len(bars)
    for k in (n - 1, n - 7, n // 2 + 13, 700):
        b, i = bars.iloc[:k], IND.compute_indicators(bars.iloc[:k])
        for col in IND.INDICATOR_COLUMNS:                         # 지표는 비트 단위로 같다
            np.testing.assert_array_equal(i[col].to_numpy(), ind[col].to_numpy()[:k], err_msg=col)
        st = ST.build_structure(b, i, ctx.s_tf)
        np.testing.assert_array_equal(st.is_sh[:k - 3], full_st.is_sh[:k - 3])   # 끝 3봉은 아직 미확정(C-4)
        assert not st.is_sh[k - 3:].any() and not st.is_sl[k - 3:].any()
        for name in ("last_sh", "last_sl", "kijun_up", "kijun_dn", "alive_up", "alive_dn"):
            np.testing.assert_array_equal(getattr(st, name), getattr(full_st, name)[:k], err_msg=name)
        pre = m_full[m_full["tb_idx"] < k].reset_index(drop=True)
        cols = [c for c in T.MADI_COLUMNS if c not in ("death_idx", "end_idx")]
        assert st.madis[cols].equals(pre[cols])                    # 확정된 마디는 같다 (C-5)
        dead = pre["death_idx"] < k                                # 이미 죽은 마디는 죽음 봉까지 같다
        np.testing.assert_array_equal(st.madis["death_idx"][dead], pre["death_idx"][dead])
        np.testing.assert_array_equal(F.trap_counts(b, st), full_trap[:k])
        fl = F.fixed_filter_flags(b, i, st)
        assert fl.equals(ctx.s_flags.iloc[:k])
        cx = T.ScenarioContext(setting="P1", vr_threshold=2.0, s_tf=ctx.s_tf, d_tf=ctx.d_tf, c_tf=ctx.c_tf,
                                s_bars=b, s_ind=i, s_struct=st, d_bars=ctx.d_bars, d_ind=ctx.d_ind,
                                d_struct=ctx.d_struct, c_bars=ctx.c_bars, s_flags=fl)
        np.testing.assert_array_equal(SC.s3_support(cx), full_sup[:k])


def test_known_times_never_after_signal(full_runs):
    """모든 후보가 쓴 구조의 알게 된 시각 ≤ 신호 시각, 마디 확정 시각 = close_ns[tb_idx] (C-1, C-5)."""
    for setting, (_, ctx, full) in full_runs.items():
        s_close = ctx.s_bars["close_ns"].to_numpy()
        m = ctx.s_struct.madis
        np.testing.assert_array_equal(m["tb_close_ns"].to_numpy(), s_close[m["tb_idx"].to_numpy()])
        known_sw = ST.swing_known_ns(s_close, ctx.s_struct.is_sl)
        for key, cands in full.items():
            for c in cands:
                meta = c.log.meta
                ks = [v for k, v in meta.items() if k.endswith("known_ns") and v is not None]
                assert all(v <= c.log.signal_time for v in ks), (key, meta)
                if meta.get("tb_close_ns"):
                    assert meta["tb_close_ns"] <= c.log.signal_time
                if "support_idx" in meta:
                    assert known_sw[meta["support_idx"]] == meta["support_known_ns"] <= c.log.signal_time
                if meta.get("d_idx", -1) >= 0:
                    assert ctx.d_bars["close_ns"].iloc[meta["d_idx"]] + AVAIL <= c.log.time


# ---------------------------------------------------------------------------
# T-NLA-4 as-of
# ---------------------------------------------------------------------------


def test_asof_boundaries_random(full_runs):
    rng = np.random.default_rng(7)
    for setting, (_, ctx, _) in full_runs.items():
        d_close = ctx.d_bars["close_ns"].to_numpy()
        q = rng.integers(d_close[0] - C.NS_PER_DAY, d_close[-1] + C.NS_PER_DAY, 2000)
        q = np.r_[q, d_close[:50] + AVAIL, d_close[:50] + AVAIL - 1]            # 경계 그 자체
        j = F.direction_asof_index(ctx, q)
        ok = j >= 0
        assert (d_close[j[ok]] + AVAIL <= q[ok]).all()
        nxt = j + 1
        has_next = ok & (nxt < len(d_close))
        assert (q[has_next] < d_close[nxt[has_next]] + AVAIL).all()
        assert (q[~ok] < d_close[0] + AVAIL).all()
        lo, sh = F.direction_at(ctx, "DB", "cluster", q)
        lb, sb = F.direction_permission(ctx.d_bars, ctx.d_ind, ctx.d_struct, "DB")
        np.testing.assert_array_equal(lo, np.where(ok, lb[np.clip(j, 0, None)], False))
        np.testing.assert_array_equal(sh, np.where(ok, sb[np.clip(j, 0, None)], False))


# ---------------------------------------------------------------------------
# T-NLA-5 체결 (실행 봉)
# ---------------------------------------------------------------------------


def trade_equal(a: T.TradeResult, b: T.TradeResult) -> bool:
    ra, rb = a.as_record(), b.as_record()
    return ra.keys() == rb.keys() and all(_eq(ra[k], rb[k]) for k in ra)


def _slice_exec(xb: T.ExecArrays, j0: int, j1: int) -> T.ExecArrays:
    return T.ExecArrays(**{f.name: getattr(xb, f.name)[j0:j1] for f in dataclasses.fields(T.ExecArrays)})


def _with_values(xb: T.ExecArrays, sel: np.ndarray, factor: float) -> T.ExecArrays:
    arrs = {f.name: np.array(getattr(xb, f.name), copy=True) for f in dataclasses.fields(T.ExecArrays)}
    for k in ("open", "high", "low", "close"):
        arrs[k][sel] = arrs[k][sel] * factor
    arrs["low"][sel] = arrs["low"][sel] * 0.5                     # 무엇이든 관통하는 봉으로
    arrs["high"][sel] = arrs["high"][sel] * 2.0
    return T.ExecArrays(**arrs)


def test_execution_ignores_bars_after_exit_and_before_activation(full_runs):
    from backtest import data as D
    try:
        xb_all = T.ExecArrays.from_frame(D.load_exec_bars())
        fa = T.FundingArrays.from_frame(D.load_funding(until_ns=FULL_END))
    except FileNotFoundError as exc:
        pytest.skip(f"실행 봉 데이터 없음: {exc}")
    _, _, full = full_runs["P1"]
    plans = []
    for key, cands in sorted(full.items()):
        ps = [c.plan for c in cands if c.plan is not None and c.plan.signal_time >= C.ts_ns("2024-01-01")]
        plans += ps[:: max(1, len(ps) // 12)][:12]
    assert {p.scenario for p in plans} == set(C.SCENARIOS)
    lo = int(np.searchsorted(xb_all.open_ns, C.ts_ns("2023-12-01")))
    hi = int(np.searchsorted(xb_all.open_ns, C.ts_ns("2024-09-01")))
    xb_big = _slice_exec(xb_all, lo, hi)                           # 계산량을 줄이려고 2023-12 ~ 2024-08만
    statuses = set()
    for p in plans:
        big = X.simulate_plan(p, xb_big, fa)
        # 계획 주변만 잘라도(활성 1일 전 ~ 끝 + 4일) 결과가 같다 → 먼 과거·먼 미래 실행 봉은 쓰지 않는다
        end_ns = big.exit_bar_close_ns if big.is_filled else max(p.order_end, big.busy_until)
        j0 = int(np.searchsorted(xb_big.open_ns, p.active_from - C.NS_PER_DAY))
        j1 = int(np.searchsorted(xb_big.open_ns, end_ns + 4 * C.NS_PER_DAY))
        xb = _slice_exec(xb_big, j0, j1)
        base = X.simulate_plan(p, xb, fa)
        assert trade_equal(base, big), p.plan_id
        statuses.add(base.status)
        j_end = int(np.searchsorted(xb.close_ns, end_ns, side="right"))
        assert j_end < len(xb)
        cut = X.simulate_plan(p, _slice_exec(xb, 0, j_end), fa)   # 청산(또는 주문 끝) 봉 뒤를 잘라도 같다
        assert trade_equal(cut, base), (p.plan_id, base, cut)
        wild = X.simulate_plan(p, _with_values(xb, np.arange(len(xb)) >= j_end, 1.7), fa)
        assert trade_equal(wild, base), p.plan_id                  # 청산 뒤 봉을 마구 바꿔도 같다
        j_act = int(np.searchsorted(xb.open_ns, p.active_from, side="left"))
        before = np.arange(len(xb)) < j_act                        # 활성 시각 전에 시작한 봉: 체결 없음
        assert trade_equal(X.simulate_plan(p, _with_values(xb, before, 0.6), fa), base), p.plan_id
    assert "filled" in statuses and len(statuses) >= 2


# ---------------------------------------------------------------------------
# T-NLA-6 끝까지(후보 → 순차 엔진 F8·F9·방해 금지·하루 6건 → 체결·청산·펀딩) 절단 불변
# (검토 LA-1: review_lookahead_test.py에서 옮겨 옴. 위 T-NLA-2·5는 후보 단계와 계획 하나의 체결만 봐서, 순차 단계의
#  미래 참조 — 예: 끝내 체결되지 않은 주문을 승인 시점 F9에서 "자리 없음"으로 보기 — 를 잡지 못한다.)
# ---------------------------------------------------------------------------

MIN15 = 15 * C.NS_PER_MIN
E2E_MIN_DECISIONS = 50_000     # 검정력 하한: 절단 시각들에서 비교한 결정 수 합
E2E_MIN_DONE = 5_000           # 검정력 하한: 절단 시각까지 끝난(필드까지 비교한) 거래 수 합

# 끝까지 절단 테스트의 창과 고정 절단 시각 (P1: 5분→1분 실행 봉 전환 포함, P2: 일봉 D 워밍업 620일 포함)
E2E = {
    "P1": dict(window=("2023-01-01", "2024-10-01"),
               cuts=("2023-09-30 21:00", "2023-10-01 06:00", "2024-01-17 13:00", "2024-04-02 09:45",
                     "2024-06-30 23:00")),
    "P2": dict(window=("2020-06-01", "2024-10-01"),
               cuts=("2022-06-01 04:00", "2023-03-15 12:00", "2023-09-30 20:00", "2023-10-02 08:00",
                     "2024-07-01 00:00")),
}


@pytest.fixture(scope="module")
def real_all():
    """실데이터 전체 (신호·방향·확인 봉, 실행 봉, 펀딩). 위 real_bars는 2024-07-01까지 잘라 둔 것이라 따로 읽는다."""
    from backtest import data as D
    try:
        bars = {tf: D.load_klines(tf) for tf in ("15m", "1h", "4h", "1d")}
        xb = D.load_exec_bars()
        fund = D.load_funding(until_ns=int(xb["close_ns"].iloc[-1]))
    except FileNotFoundError as exc:
        pytest.skip(f"실데이터 없음: {exc}")
    return bars, xb, fund


def e2e_window_market(bars: dict, exec_df: pd.DataFrame | None, fund: pd.DataFrame | None, start, end) -> T.MarketData:
    """[start, end] 안에서 시작·마감하는 봉만 남긴 시장 (실행 봉이 없으면 1h 봉으로 대신, 펀딩 없으면 빈 표)."""
    s, e = C.ts_ns(start), C.ts_ns(end)
    sel = {tf: b[(b["open_ns"] >= s) & (b["close_ns"] <= e)] for tf, b in bars.items()}
    if exec_df is None:
        xb = sel["1h"]
    else:
        xb = exec_df[(exec_df["open_ns"] >= s) & (exec_df["close_ns"] <= e)]
    if fund is None:
        f = T.make_funding_frame(np.array([], dtype=np.int64), np.array([], dtype=np.float64))
    else:
        f = fund[(fund["time_ns"] >= s) & (fund["time_ns"] <= e)].reset_index(drop=True)
    return T.MarketData(bars=sel, exec_bars=xb, funding=f, events_ns=None)


def forced_candidates(cands: list[T.Candidate]) -> list[T.Candidate]:
    """가격이 있는 모든 후보의 사유를 지운 "강제 계획" (순차 엔진·체결 엔진의 검정력을 높이려고)."""
    out = []
    for c in cands:
        p = c.plan
        if p is None or Reason.SC_BAD_GEOMETRY in c.log.reasons:
            continue
        if not all(math.isfinite(v) for v in (p.entry_price, p.stop, p.target)):
            continue
        out.append(T.Candidate(log=dataclasses.replace(c.log, reasons=(), status="passed"), plan=p))
    return out


def run_all(ctx: T.ScenarioContext, market: T.MarketData, setting: str) -> dict:
    """설정 하나의 8조합 × (실행 가능·전체) × (실제 후보·강제 계획) 순차 실행 결과.

    키 (조합, 모드, 종류) → (trades, logs). 후보 목록은 키 (조합, "cands")에 둔다(후보 단계 비교용).
    """
    xb, fa = market.exec_arrays(), market.funding_arrays()
    out = {}
    for cfg in (c for c in C.g1_combos() if c.setting == setting):
        cands = SC.generate_candidates(ctx, cfg)
        out[(cfg.base_key, "cands")] = cands
        forced = forced_candidates(cands)
        for mode, mcfg in (("exec", cfg), ("all", cfg.replace(apply_availability_mask=False))):
            out[(cfg.base_key, mode, "real")] = X.run_sequence(cands, xb, fa, mcfg)
            out[(cfg.base_key, mode, "forced")] = X.run_sequence(forced, xb, fa, mcfg)
    return out


def compare_candidates(full: list[T.Candidate], other: list[T.Candidate], t_ns: int) -> int:
    """신호 시각 ≤ T인 후보(순차 전)가 사유·가격·시각·meta까지 같은지. 취소는 T까지 마감한 봉에서 성립했으면 같고,
    아니면 다른 쪽은 그 취소를 몰라야 한다(절단) / 같은 시각에 알면 안 된다(변경). 비교한 후보 수를 돌려준다."""
    fa_ = [c for c in full if c.log.signal_time <= t_ns]
    fb_ = [c for c in other if c.log.signal_time <= t_ns]
    ida, idb = [c.log.meta["cand_id"] for c in fa_], [c.log.meta["cand_id"] for c in fb_]
    assert ida == idb, (C.ns_to_iso(t_ns), sorted(set(ida) ^ set(idb))[:5])
    for a, b in zip(fa_, fb_):
        la, lb = a.log, b.log
        assert (la.time, la.reasons, la.plan_id, la.madi_id) == (lb.time, lb.reasons, lb.plan_id, lb.madi_id), \
            (la.meta["cand_id"], la.reasons, lb.reasons)
        assert la.meta.keys() == lb.meta.keys() and all(_eq(la.meta[k], lb.meta[k]) for k in la.meta), la.meta
        if a.plan is None:
            assert b.plan is None
            continue
        pa, pb = a.plan, b.plan
        for f in dataclasses.fields(T.Plan):
            if f.name not in ("cancel_effective_time", "cancel_reason", "meta"):
                assert _eq(getattr(pa, f.name), getattr(pb, f.name)), (pa.plan_id, f.name)
        known_a = pa.cancel_effective_time is not None and pa.cancel_effective_time - AVAIL <= t_ns
        known_b = pb.cancel_effective_time is not None and pb.cancel_effective_time - AVAIL <= t_ns
        assert known_a == known_b, (pa.plan_id, pa.cancel_effective_time, pb.cancel_effective_time)
        if known_a:
            assert (pa.cancel_effective_time, pa.cancel_reason) == (pb.cancel_effective_time, pb.cancel_reason)
    return len(fa_)


def compare_upto(full: dict, other: dict, t_ns: int, xb_full: T.ExecArrays, truncated: bool) -> dict:
    """승인 시각 < T인 결정(통과/폐기·사유)이 같고, T까지 끝난 거래(busy_until ≤ T)는 필드까지 같은지.

    T에 걸친 거래: T 전에 마감한 실행 봉에서 체결했으면 다른 쪽도 같은 봉·같은 가격에 체결, 아니면 체결 없음.
    절단 쪽은 T에 걸친 체결 거래가 마지막 실행 봉(마감 = T)에서 eod로 끝나야 한다.
    """
    stats = dict(cands=0, decisions=0, done=0, straddle=0, straddle_filled=0)
    for key, val in full.items():
        if key[-1] == "cands":
            stats["cands"] += compare_candidates(val, other[key], t_ns)
            continue
        tr_f, lg_f = val
        tr_o, lg_o = other[key]
        lf = [(lg.meta["cand_id"], lg.status, lg.reasons) for lg in lg_f if lg.time < t_ns]
        lo = [(lg.meta["cand_id"], lg.status, lg.reasons) for lg in lg_o if lg.time < t_ns]
        if lf != lo:
            diff = [(a, b) for a, b in zip(lf, lo) if a != b][:3]
            raise AssertionError(f"{key}: T={C.ns_to_iso(t_ns)} 전 결정이 다름 {diff} (개수 {len(lf)} vs {len(lo)})")
        stats["decisions"] += len(lf)
        by_id = {t.plan_id: t for t in tr_o}
        for tr in tr_f:
            if tr.approval_time >= t_ns:
                continue
            o = by_id[tr.plan_id]
            if tr.busy_until <= t_ns:
                assert trade_equal(tr, o), (key, C.ns_to_iso(t_ns), tr, o)
                stats["done"] += 1
                continue
            stats["straddle"] += 1
            filled_by_t = False
            if tr.is_filled:
                j = int(np.searchsorted(xb_full.open_ns, tr.entry_time))
                filled_by_t = int(xb_full.close_ns[j]) <= t_ns
            if filled_by_t:
                stats["straddle_filled"] += 1
                assert o.is_filled and (o.entry_time, o.entry_price) == (tr.entry_time, tr.entry_price), (key, tr, o)
                if truncated:
                    assert o.exit_reason == T.Exit.EOD and o.exit_bar_close_ns == t_ns, (key, tr, o)
            else:
                # T 전 실행 봉에서 체결이 없었다면, T 뒤를 모르는(또는 바뀐) 쪽도 T 전에 체결되면 안 된다
                if o.is_filled:
                    j = int(np.searchsorted(xb_full.open_ns, o.entry_time))
                    assert int(xb_full.close_ns[j]) > t_ns, (key, tr, o)
    return stats


def adaptive_cuts(full: dict, xb: T.ExecArrays, s_dur: int) -> list[int]:
    """민감한 절단 시각 (DB 조합의 강제 계획 거래·후보에서 고른다. DA는 같은 후보 시각이라 뺀다)
    - 청산 사유(stop·target·time)마다 한 거래: 청산 봉 끝(T에 정확히 끝남)과 청산 봉 시작(청산 봉이 아직 안 옴).
      조합마다 5분 구간 / 1분 구간을 번갈아 고른다. — 청산을 한 봉이라도 미리 알면 여기서 드러난다
    - 체결: 체결 봉 시작(아직 체결 전), 체결 봉 끝(체결 봉이 마지막 실행 봉), 그 뒤 15분 경계(거래가 걸침)
    - 신호 시각(신호 봉·확인 봉이 마지막 봉) — L1b는 S 봉 경계가 아닌 C 봉 마감도
    - 취소 조건 봉 k가 진행 중인 시각(close[k] − 15분): 취소를 미리 알면 여기서 드러난다
    - IOC 첫 실행 봉 시작(활성 직후 봉이 아직 안 옴)
    """
    out = set()
    runs = sorted(k for k in full if len(k) == 3 and k[1] == "all" and k[2] == "forced" and "-DB-" in k[0])
    for i, key in enumerate(runs):
        filled = [t for t in full[key][0] if t.is_filled]
        for reason in (T.Exit.STOP, T.Exit.TARGET, T.Exit.TIME):
            sel = [t for t in filled if t.exit_reason == reason]
            era = [t for t in sel if (t.exit_time < C.EXEC_SWITCH_NS) == (i % 2 == 0)] or sel
            if era:
                tr = era[len(era) // 2]
                out.update((int(tr.exit_bar_close_ns), int(tr.exit_time)))
        if filled:
            tr = filled[len(filled) // 2]
            j = int(np.searchsorted(xb.open_ns, tr.entry_time))
            out.update((int(tr.entry_time), int(xb.close_ns[j]), -(-int(xb.close_ns[j]) // MIN15) * MIN15))
    for key in sorted(k for k in full if k[-1] == "cands" and "-DB-" in k[0]):
        cands = [c for c in full[key] if c.plan is not None]
        if not cands:
            continue
        off = [c for c in cands if c.log.signal_time % s_dur]           # S 봉 경계가 아닌 신호(L1b)
        picks = [cands[len(cands) // 3], cands[(2 * len(cands)) // 3]] + off[len(off) // 2: len(off) // 2 + 2]
        out.update(int(c.log.signal_time) for c in picks)
        canc = [c for c in cands if c.plan.cancel_effective_time is not None]
        for c in canc[len(canc) // 5:: max(1, len(canc) // 3)][:3]:
            out.add(int(c.plan.cancel_effective_time) - AVAIL - MIN15)
        ioc = [c for c in cands if c.plan.order_type == "ioc_cap"]
        if ioc:                                                          # 첫 실행 봉(활성 뒤 첫 봉) 시작 = 절단 시각
            j0 = int(np.searchsorted(xb.open_ns, ioc[len(ioc) // 2].plan.active_from, side="left"))
            if j0 < len(xb):
                out.add(int(xb.open_ns[j0]))
    return sorted(out)


def build_e2e_full(bars: dict, exec_df, fund) -> dict:
    """설정별 (창 시장, 전체 결과) — E2E 창마다 run_all."""
    out = {}
    for setting, spec in E2E.items():
        m = e2e_window_market(bars, exec_df, fund, *spec["window"])
        out[setting] = (m, run_all(SC.build_context(m, setting), m, setting))
    return out


@pytest.fixture(scope="module")
def e2e_full(real_all):
    return build_e2e_full(*real_all)


@pytest.mark.slow
@pytest.mark.parametrize("setting", tuple(E2E))
def test_end_to_end_truncation_invariance(e2e_full, setting):
    """T-NLA-6: 후보 → 순차(F8·F9·마스크) → 체결·청산·펀딩 전체가 절단 불변 (실제 후보 + 강제 계획, 두 모드).

    절단 시각: 고정 시각 + 청산 사유(stop·target·time)별 청산 봉 끝·시작 + 체결 봉 시작·끝 + 신호 봉이 마지막 봉
    (L1b는 C 봉 마감 포함) + 취소 조건 봉 진행 중 + IOC 첫 실행 봉 시작 (adaptive_cuts).
    """
    m, full = e2e_full[setting]
    xb = m.exec_arrays()
    cuts = [C.ts_ns(t) for t in E2E[setting]["cuts"]] + adaptive_cuts(full, xb, C.TF_NS[C.SETTINGS[setting].signal])
    assert len(cuts) >= 20
    tot = dict(cands=0, decisions=0, done=0, straddle=0, straddle_filled=0)
    for t_ns in cuts:
        mt = truncate_market(m, t_ns)
        assert int(mt.exec_bars["close_ns"].iloc[-1]) == t_ns     # 절단 시각이 실행 봉 경계 (공정한 비교)
        got = run_all(SC.build_context(mt, setting), mt, setting)
        s = compare_upto(full, got, t_ns, xb, truncated=True)
        for k in tot:
            tot[k] += s[k]
    # 검정력: 실제로 많은 결정·완료 거래·걸친 거래를 비교했는지
    assert tot["decisions"] > E2E_MIN_DECISIONS and tot["done"] > E2E_MIN_DONE, tot
    assert tot["straddle_filled"] >= 10, tot
