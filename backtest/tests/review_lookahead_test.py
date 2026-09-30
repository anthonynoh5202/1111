"""적대적 검토: 미래 참조(look-ahead)·데이터 누수 감사 테스트 (검토자 전용 파일, 제품 코드는 고치지 않는다).

기존 test_no_lookahead.py(후보 단계 절단·미래 변경, 계획 하나의 체결)를 넘어서 다음을 확인한다.
1. 끝까지(후보 → 순차 엔진 F8·F9·마스크 → 체결·청산·펀딩) 절단 불변 — 실데이터 P1·P2, 16조합 × 두 모드.
   [수정 담당 메모] 이 절의 기본 절단 테스트(test_end_to_end_truncation_invariance)와 도우미는 검토 LA-1에 따라
   팀 파일 test_no_lookahead.py(T-NLA-6)로 옮겼다. 여기에는 미래 변경·민감도 변형 판본이 남아 있다.
   필터를 통과한 실제 후보만으로는 거래가 적어(1.5년에 몇 건) 검정력이 없으므로, 가격이 있는 모든 후보의
   사유를 지우고 순차 엔진에 넣는 "강제 계획" 실행을 같이 비교한다(계획 가격·시각은 인과적으로 만들어졌으므로
   엔진이 미래를 보지 않으면 결과도 절단 불변이어야 한다). 비교: 신호 시각 ≤ T 후보(순차 전), 승인 시각 < T 결정,
   T까지 끝난 거래(필드 전부), T에 걸친 거래(체결 여부·가격, 절단 쪽 eod). 절단 시각(adaptive_cuts): 고정 시각 +
   청산 사유(stop·target·time)별 청산 봉 끝·시작(5분/1분 구간 번갈아) + 체결 봉 시작·끝 + 신호 봉이 마지막 봉
   (L1b는 S 봉 경계가 아닌 C 봉 마감 포함) + 취소 조건 봉 진행 중(close[k] − 15분) + IOC 첫 실행 봉 시작.
   검정력 확인(2026-09-30, 검토자): 일부러 넣은 미래 참조 5종(진행 중 D 봉, 취소 한 봉 일찍, L1b 진행 중 S 봉,
   대기 주문 F9 무시, 목표 한 봉 일찍)을 이 테스트 하나가 모두 잡는다. 나머지 절(3~14)은 절단으로 드러나지 않는
   "같은 시각 안" 위반(현재 봉 포함 평균, 스윙 i+2 확정, 허리에 B 뒤 봉, 활성 전 체결, 당일 종가 체결 등)을 잡는다.
2. 끝까지 미래 변경 불변 — T 뒤 모든 간격(S·D·C·실행 봉)과 펀딩을 바꿔도 T 전 결정·T까지 끝난 거래가 같다.
3. 지표: 모든 "직전 n개" 통계가 현재 봉을 빼는지(현재 봉만 바꿔 보는 의존성 지도), 분위 창이 [t−500, t−1]인지.
4. 스윙: i+3 봉 마감 전에는 절대 보이지 않고, i+3에서 정확히 보인다(실데이터 1h·4h·1d 전수).
5. 허리: A~B 밖의 봉(허리 구간 안 가격 + 거래량 100배로 바꿔도)을 쓰지 않는다.
6. 기준봉 조건 4: 아직 확정 안 된 스윙은 보지 않고, 확정되는 봉(i+3)부터 본다(합성 사례).
7. 마디: 확정 봉 tb 직전까지 자른 데이터에는 그 마디가 없고, tb까지 자르면 같은 값으로 있다(마디마다 경계 절단).
8. 취소 효력 시각: 독립 구현으로 "신호 봉 다음 봉부터 처음 성립한 봉 k의 마감 + 60초"인지 전수 확인.
9. L1b: 준비 봉 마감 < 확인 C 봉 마감, k_last는 확인 시각에 마감된 마지막 S 봉, 최저가·폐기 규칙이 확인 시각까지의 값만.
10. as-of: 모든 S 봉·C 봉 판단 시각에서 쓴 D 봉은 마감 + 60초 ≤ 판단 시각, 다음 D 봉은 아직 마감 전.
11. F2·F5·F6: 순진한(느린) 독립 구현과 전수 일치.
12. 체결: 진입 봉 시작 ≥ 활성 시각, 지정가는 봉 끝 ≤ 주문 끝, IOC는 활성 뒤 첫 봉, 지정가는 처음 관통한 봉.
13. 돈치안: 일봉 절단 불변(자산 곡선), 신호 다음 날 시가 체결(당일 종가 체결 아님).
14. 무작위 기준선: 진입 = 뽑은 신호 봉 마감 + 60초 + L 뒤 첫 실행 봉 시가, 활성 전 실행 봉을 바꿔도 결과가 같다.
실데이터가 없으면 건너뛴다. 실행 봉 전체를 읽는 테스트는 @slow.
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from backtest import baselines as B
from backtest import config as C
from backtest import execution as X
from backtest import filters as F
from backtest import indicators as IND
from backtest import random_baseline as RB
from backtest import scenarios as SC
from backtest import structure as ST
from backtest import types as T
from backtest.config import ComboConfig
from backtest.tests.conftest import make_bars, truncate_market
# 끝까지(후보 → 순차 → 체결) 절단 도우미는 팀 테스트 T-NLA-6(test_no_lookahead.py)로 옮겼다 (검토 LA-1). 여기서는 가져다 쓴다.
from backtest.tests.test_no_lookahead import (E2E, _eq, adaptive_cuts, build_e2e_full, compare_upto,  # noqa: F401
                                              e2e_window_market as window_market, forced_candidates, run_all,
                                              trade_equal)
from backtest.types import Reason

AVAIL = C.AVAIL_DELAY_NS

# ---------------------------------------------------------------------------
# 데이터 준비
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_bars():
    from backtest import data as D
    try:
        return {tf: D.load_klines(tf) for tf in ("15m", "1h", "4h", "1d")}
    except FileNotFoundError as exc:
        pytest.skip(f"실데이터 없음: {exc}")


@pytest.fixture(scope="module")
def real_exec():
    from backtest import data as D
    try:
        xb = D.load_exec_bars()
        fund = D.load_funding(until_ns=int(xb["close_ns"].iloc[-1]))
    except FileNotFoundError as exc:
        pytest.skip(f"실행 봉·펀딩 데이터 없음: {exc}")
    return xb, fund


def nan_equal(a: np.ndarray, b: np.ndarray) -> bool:
    a, b = np.asarray(a), np.asarray(b)
    if a.dtype == bool or b.dtype == bool:
        return bool(np.array_equal(a, b))
    return bool(np.array_equal(a, b, equal_nan=True))


# ---------------------------------------------------------------------------
# 1·2. 끝까지(후보 → 순차 → 체결) 절단·미래 변경 불변
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def e2e_full(real_bars, real_exec):
    """설정별 (창 시장, 전체 결과) — 공용 도우미(test_no_lookahead.build_e2e_full)."""
    xb_df, fund = real_exec
    return build_e2e_full(real_bars, xb_df, fund)


def perturb_future(market: T.MarketData, t_ns: int, seed: int) -> T.MarketData:
    """T 뒤에 마감하는 봉(모든 간격 + 실행 봉)의 가격을 시간의 매끄러운 함수로 곱하고(최대 ±8% 안팎 + 추세),
    거래량을 1~9배로, T 뒤 펀딩 비율을 무작위로 바꾼다. 봉마다 OHLC 순서는 유지된다."""
    rng = np.random.default_rng(seed)
    amp, per = rng.uniform(0.04, 0.08), rng.uniform(1.5, 4.0) * C.NS_PER_DAY
    phase, drift = rng.uniform(0, 2 * np.pi), rng.choice([-1.0, 1.0]) * 0.02 / C.NS_PER_DAY

    def factor(open_ns: np.ndarray) -> np.ndarray:
        x = (open_ns - t_ns).astype(np.float64)
        return np.exp(amp * (np.sin(2 * np.pi * x / per + phase) - np.sin(phase)) + drift * x)

    def pert(df: pd.DataFrame) -> pd.DataFrame:
        fut = df["close_ns"].to_numpy() > t_ns
        if not fut.any():
            return df
        o_ns = df["open_ns"].to_numpy()
        f = factor(o_ns[fut])
        cols = {}
        for col in ("open", "high", "low", "close"):
            v = df[col].to_numpy(copy=True)
            v[fut] = np.round(v[fut] * f, 1)
            cols[col] = v
        vol = df["volume"].to_numpy(copy=True)
        vol[fut] = vol[fut] * (1.0 + 8.0 * (0.5 + 0.5 * np.sin(2 * np.pi * (o_ns[fut] - t_ns) / (0.7 * per))))
        out = T.make_bars_frame(o_ns, cols["open"], cols["high"], cols["low"], cols["close"], vol,
                                df["close_ns"].to_numpy() - o_ns)
        T.check_bars_frame(out, contiguous=True)
        return out

    fund = market.funding.copy()
    late = fund["time_ns"].to_numpy() > t_ns
    rate = fund["rate"].to_numpy(copy=True)
    rate[late] = rng.normal(0.0, 5e-4, int(late.sum()))
    fund["rate"] = rate
    return T.MarketData(bars={tf: pert(b) for tf, b in market.bars.items()}, exec_bars=pert(market.exec_bars),
                        funding=fund, events_ns=None)


@pytest.mark.slow
@pytest.mark.parametrize("setting", tuple(E2E))
def test_end_to_end_future_modification_invariance(e2e_full, setting):
    """T 뒤 모든 데이터(신호·방향·확인·실행 봉, 펀딩)를 바꿔도 T 전 결정과 T까지 끝난 거래가 같다."""
    m, full = e2e_full[setting]
    xb = m.exec_arrays()
    cuts = [C.ts_ns(t) for t in E2E[setting]["cuts"][1:4]] + adaptive_cuts(full, xb, C.TF_NS[C.SETTINGS[setting].signal])[::4]
    changed_after = 0
    tot = dict(cands=0, decisions=0, done=0, straddle=0, straddle_filled=0)
    for i, t_ns in enumerate(cuts):
        mp = perturb_future(m, t_ns, seed=1000 + i)
        got = run_all(SC.build_context(mp, setting), mp, setting)
        s = compare_upto(full, got, t_ns, xb, truncated=False)
        for k in tot:
            tot[k] += s[k]
        for key in (k for k in full if k[-1] != "cands"):           # 변경이 T 뒤 결과를 실제로 바꿨는가
            after_a = [(lg.meta["cand_id"], lg.reasons) for lg in full[key][1] if lg.time >= t_ns]
            after_b = [(lg.meta["cand_id"], lg.reasons) for lg in got[key][1] if lg.time >= t_ns]
            changed_after += after_a != after_b
    assert changed_after > 0
    assert tot["done"] > 1_000, tot


def run_variants(market: T.MarketData, setting: str, variants: list[tuple[str, dict]]) -> dict:
    """민감도 변형(실행 가능 모드)마다 실제 후보·강제 계획 순차 실행 결과. VR 3은 따로 문맥을 만든다."""
    xb, fa = market.exec_arrays(), market.funding_arrays()
    ctxs: dict[float, T.ScenarioContext] = {}
    out = {}
    for base in (c for c in C.g1_combos() if c.setting == setting):
        for tag, changes in variants:
            cfg = base.replace(**changes)
            vr = float(cfg.vr_threshold)
            if vr not in ctxs:
                ctxs[vr] = SC.build_context(market, setting, vr)
            cands = SC.generate_candidates(ctxs[vr], cfg)
            out[(cfg.base_key, tag, "cands")] = cands
            out[(cfg.base_key, tag, "real")] = X.run_sequence(cands, xb, fa, cfg)
            out[(cfg.base_key, tag, "forced")] = X.run_sequence(forced_candidates(cands), xb, fa, cfg)
    return out


@pytest.mark.slow
def test_end_to_end_truncation_invariance_sensitivity_variants(e2e_full):
    """민감도 변형(지연 5·15분, 허리 (고+저)÷2, VR 3, 비용 2배)도 끝까지 절단 불변 (P1)."""
    m, full_default = e2e_full["P1"]
    xb = m.exec_arrays()
    variants = [(tag, ch) for tag, ch in C.SENSITIVITY_VARIANTS]
    full = run_variants(m, "P1", variants)
    cuts = [C.ts_ns(t) for t in E2E["P1"]["cuts"][::2]] + adaptive_cuts(full_default, xb, C.TF_NS["1h"])[1::6]
    tot = dict(cands=0, decisions=0, done=0, straddle=0, straddle_filled=0)
    for t_ns in cuts:
        mt = truncate_market(m, t_ns)
        s = compare_upto(full, run_variants(mt, "P1", variants), t_ns, xb, truncated=True)
        for k in tot:
            tot[k] += s[k]
    assert tot["done"] > 3_000, tot


# ---------------------------------------------------------------------------
# 3. 지표: 현재 봉 제외 (의존성 지도) · 분위 창
# ---------------------------------------------------------------------------

# 현재 봉 값을 쓰면 안 되는 열(모두 "직전 n개" 통계)과 현재 봉에 반드시 반응해야 하는 열
TRAILING_COLS = ("atr", "vol_avg", "body_avg", "ma20", "ma60", "ma120", "spread_q80", "atr_q20", "buffer")
CURRENT_COLS = ("body", "range", "vr", "spread")


def _perturb_bar(bars: pd.DataFrame, t: int) -> pd.DataFrame:
    o, h, l, c, v = (bars[k].to_numpy(copy=True) for k in ("open", "high", "low", "close", "volume"))
    o[t], c[t] = o[t] * 1.013, c[t] * 0.981
    h[t] = max(h[t] * 1.04, o[t], c[t])
    l[t] = min(l[t] * 0.96, o[t], c[t])
    v[t] = v[t] * 37.0
    return T.make_bars_frame(bars["open_ns"].to_numpy(), o, h, l, c, v, bars["close_ns"].to_numpy()
                             - bars["open_ns"].to_numpy())


def test_indicator_trailing_stats_exclude_current_bar(real_bars):
    """봉 t 하나만 크게 바꾸면: [0, t)의 모든 지표는 그대로, t의 '직전 n개' 통계도 그대로, t의 현재 값만 바뀐다."""
    b = real_bars["1h"].iloc[20_000:23_000]
    base = IND.compute_indicators(b)
    for t in (700, 1234, 2000, 2999):
        pert = IND.compute_indicators(_perturb_bar(b, t))
        for col in IND.INDICATOR_COLUMNS:
            assert nan_equal(pert[col].to_numpy()[:t], base[col].to_numpy()[:t]), (t, col)
        for col in TRAILING_COLS:
            assert nan_equal(pert[col].to_numpy()[t:t + 1], base[col].to_numpy()[t:t + 1]), (t, col)
        for col in CURRENT_COLS:
            assert pert[col].to_numpy()[t] != base[col].to_numpy()[t], (t, col)
        if t + 1 < len(b):                                          # 다음 봉의 직전 창에는 들어간다
            assert pert["atr"].to_numpy()[t + 1] != base["atr"].to_numpy()[t + 1]
            assert pert["vol_avg"].to_numpy()[t + 1] != base["vol_avg"].to_numpy()[t + 1]
            assert pert["ma20"].to_numpy()[t + 1] != base["ma20"].to_numpy()[t + 1]


def test_spread_quantile_and_ma_windows_real(real_bars):
    """spread_q80[t] = quantile(spread[t−500..t−1], 0.8), spread_on = spread[t] ≥ 그 값, ma·atr·vol_avg = 직전 창 평균."""
    b = real_bars["1h"].iloc[:6000]
    ind = IND.compute_indicators(b)
    c, v = b["close"].to_numpy(), b["volume"].to_numpy()
    sp, q80, tr = ind["spread"].to_numpy(), ind["spread_q80"].to_numpy(), ind["tr"].to_numpy()
    rng = np.random.default_rng(3)
    for t in np.r_[620, 621, 5999, rng.integers(620, 6000, 60)]:
        t = int(t)
        assert q80[t] == np.quantile(sp[t - 500:t], 0.8)
        assert ind["spread_on"].to_numpy()[t] == (sp[t] >= q80[t])
        assert ind["ma20"].to_numpy()[t] == np.mean(c[t - 20:t])
        assert math.isclose(ind["ma120"].to_numpy()[t], np.mean(c[t - 120:t]), rel_tol=1e-12)
        assert math.isclose(ind["atr"].to_numpy()[t], np.mean(tr[t - 14:t]), rel_tol=1e-12)
        assert math.isclose(ind["vol_avg"].to_numpy()[t], np.mean(v[t - 20:t]), rel_tol=1e-12)
    first_valid = int(np.argmax(ind["valid"].to_numpy()))
    assert first_valid == 620 and not ind["valid"].to_numpy()[:620].any()


# ---------------------------------------------------------------------------
# 4. 스윙 확정 시각 (실데이터 전수)
# ---------------------------------------------------------------------------


def test_swings_confirmed_exactly_at_i_plus_3_real(real_bars):
    for tf in ("1h", "4h", "1d"):
        b = real_bars[tf]
        h, l = b["high"].to_numpy(), b["low"].to_numpy()
        n = h.shape[0]
        t = np.arange(n)
        is_sh, is_sl = ST.find_swings(h, l)
        for is_sw in (is_sh, is_sl):
            last = ST.last_confirmed(is_sw)
            assert ((last == -1) | (last <= t - 3)).all(), tf      # 어떤 시점에도 i+3 > t인 스윙은 안 보임
            idx = np.flatnonzero(is_sw)
            idx = idx[idx + 3 < n]
            assert (last[idx + 2] < idx).all(), tf                 # i+2 마감 때는 아직 모름
            assert (last[idx + 3] == idx).all(), tf                # i+3 마감 때 정확히 보임
        # 국소성: 봉 i의 스윙 판정은 [0, i+4) 봉만으로 같고, [0, i+3)으로는 판정되지 않는다
        rng = np.random.default_rng(11)
        for i in rng.choice(np.flatnonzero(is_sh[:-3]), 40, replace=False):
            i = int(i)
            assert ST.find_swings(h[:i + 4], l[:i + 4])[0][i]
            assert not ST.find_swings(h[:i + 3], l[:i + 3])[0][i]


# ---------------------------------------------------------------------------
# 5. 허리는 A~B 봉만
# ---------------------------------------------------------------------------


def test_waist_ignores_bars_outside_a_to_b(real_bars):
    """A 전·B 뒤 봉을 허리 구간 안 가격(한 칸에 몰리게) + 거래량 100배로 바꿔도 허리가 같다."""
    m = window_market(real_bars, None, None, "2023-01-01", "2024-07-01")
    ctx = SC.build_context(m, "P1")
    bars, madis = ctx.s_bars, ctx.s_struct.madis
    assert len(madis) >= 20
    o, h, l, c, v = (bars[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
    for row in madis.itertuples():
        a, b = int(row.a_idx), int(row.b_idx)
        A, Bp, W = float(row.a_price), float(row.b_price), float(row.w)
        assert ST.waist_cluster(bars, a, b, A, Bp)[0] == row.h_cluster
        d = 1.0 if Bp > A else -1.0
        bait = A + d * 0.37 * W                                      # 구간 [A+0.35W, A+0.65W] 안쪽 낮은 칸
        outside = np.ones(len(bars), dtype=bool)
        outside[a:b + 1] = False
        o2, h2, l2, c2, v2 = (x.copy() for x in (o, h, l, c, v))
        for arr in (o2, h2, l2, c2):
            arr[outside] = bait
        v2[outside] = v2[outside] * 100.0
        fake = T.make_bars_frame(bars["open_ns"].to_numpy(), o2, h2, l2, c2, v2, C.TF_NS["1h"])
        assert ST.waist_cluster(fake, a, b, A, Bp) == (row.h_cluster, bool(row.waist_fallback)), row.madi_id


# ---------------------------------------------------------------------------
# 6. 기준봉 조건 4 = 봉 t 시점에 확정된 스윙 고점만
# ---------------------------------------------------------------------------


def _kijun_ind(n: int) -> pd.DataFrame:
    """조건 4 말고는 모두 만족하는 지표 프레임(valid·장대봉·VR 3·기울기 +·꼬리 0.1·확산 아님)."""
    return pd.DataFrame({"valid": np.ones(n, bool), "long_bar": np.ones(n, bool), "spread_on": np.zeros(n, bool),
                         "vr": np.full(n, 3.0), "slope20": np.ones(n), "slope60": np.ones(n),
                         "upper_wick": np.full(n, 0.1), "lower_wick": np.full(n, 0.1)})


def test_kijun_condition4_uses_only_confirmed_swing():
    """t−2의 더 높은 스윙(아직 미확정)은 무시, 확정된 옛 스윙(100)만 본다. t+1(확정 = i+3)부터는 새 스윙(110)을 본다."""
    n = 40
    rows = [(90.0, 90.0, 89.0, 90.0)] * n
    rows[10] = (90.0, 100.0, 89.0, 90.0)                             # 스윙 고점 10 (13 마감에 확정)
    rows[28] = (90.0, 110.0, 89.0, 90.0)                             # 스윙 고점 28 (31 마감에 확정)
    rows[30] = (95.0, 106.0, 94.0, 105.0)                            # 기준봉 후보 t = 30: 100 < 105 < 110
    rows[31] = (95.0, 106.0, 94.0, 105.0)                            # 같은 모양 t = 31: 이제 110이 확정됨
    bars = make_bars(rows)
    h, l = bars["high"].to_numpy(), bars["low"].to_numpy()
    is_sh, is_sl = ST.find_swings(h, l)
    assert is_sh[10] and is_sh[28]
    last_sh, last_sl = ST.last_confirmed(is_sh), ST.last_confirmed(is_sl)
    assert last_sh[30] == 10 and last_sh[31] == 28
    up, _ = ST.detect_kijun(bars, _kijun_ind(n), last_sh, last_sl)
    assert up[30]                                                    # 미확정 스윙 110을 봤다면 False
    assert not up[31]                                                # 확정 뒤에는 110 기준


# ---------------------------------------------------------------------------
# 7. 마디는 tb 봉 마감에야 존재 (마디마다 경계 절단)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tf,window", [("1h", ("2023-01-01", "2024-07-01")), ("4h", ("2021-01-01", "2024-07-01"))])
def test_madi_appears_exactly_at_tb(real_bars, tf, window):
    b = real_bars[tf]
    b = b[(b["open_ns"] >= C.ts_ns(window[0])) & (b["close_ns"] <= C.ts_ns(window[1]))]
    ind = IND.compute_indicators(b)
    full = ST.build_structure(b, ind, tf).madis
    assert len(full) >= 10
    cols = [c for c in T.MADI_COLUMNS if c not in ("death_idx", "end_idx")]
    rng = np.random.default_rng(5)
    rows = rng.choice(len(full), min(25, len(full)), replace=False)
    for r in sorted(int(x) for x in rows):
        row = full.iloc[r]
        tb = int(row["tb_idx"])
        before = ST.build_structure(b.iloc[:tb], ind.iloc[:tb], tf).madis
        assert row["madi_id"] not in set(before["madi_id"]), row["madi_id"]      # tb 봉 마감 전에는 모름
        at = ST.build_structure(b.iloc[:tb + 1], ind.iloc[:tb + 1], tf).madis
        got = at[at["madi_id"] == row["madi_id"]]
        assert len(got) == 1, row["madi_id"]
        for col in cols:
            assert _eq(got.iloc[0][col], row[col]), (row["madi_id"], col)
        assert int(got.iloc[0]["end_idx"]) == tb                     # tb 봉에서는 살아 있음(끝 = 데이터 끝)


# ---------------------------------------------------------------------------
# 8. 취소 효력 시각 — 독립 구현
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ctx_p1(real_bars):
    m = window_market(real_bars, None, None, "2022-06-01", "2024-07-01")
    return SC.build_context(m, "P1")


@pytest.fixture(scope="module")
def ctx_p2(real_bars):
    m = window_market(real_bars, None, None, "2020-01-01", "2024-07-01")
    return SC.build_context(m, "P2")


@pytest.mark.parametrize("ctx_name", ["ctx_p1", "ctx_p2"])
def test_cancel_effective_time_reference(request, ctx_name):
    """L1a·S2·S3 계획의 취소 효력 = (신호 봉 다음 봉부터 N봉 안) 처음 성립한 봉 k의 close_ns + 60초 (§12.1, I-46·I-47)."""
    ctx = request.getfixturevalue(ctx_name)
    sb = ctx.s_bars
    c, hi, v, cns = (sb[k].to_numpy() for k in ("close", "high", "volume", "close_ns"))
    n = c.shape[0]
    madis = ctx.s_struct.madis
    checked = 0
    for scen, nvalid in (("L1a", C.L1A_VALID_BARS), ("S2", C.S2_VALID_BARS), ("S3", C.S3_VALID_BARS)):
        cfg = ComboConfig(scen, "DB", ctx.setting)
        for cand in SC.generate_candidates(ctx, cfg):
            p = cand.plan
            if p is None:
                continue
            t = int(p.meta["s_idx"])
            assert int(cns[t]) == p.signal_time
            ks = range(t + 1, min(t + nvalid, n - 1) + 1)
            first = None
            for k in ks:
                if scen == "L1a":
                    A, Bp, W = p.meta["A"], p.meta["B"], p.meta["W"]
                    row = madis.iloc[int(p.meta["madi_row"])]
                    b_idx, vol_ab = int(row["b_idx"]), float(row["vol_ab_mean"])
                    hits = [("close_below", c[k] < A), ("high_above", hi[k] > Bp + C.L1A_EXTENSION_W * W),
                            ("unhealthy_volume", v[b_idx + 1:k + 1].mean() >= vol_ab)]
                elif scen == "S2":
                    hits = [("close_above", c[k] > p.meta["B"])]
                else:
                    hits = [("close_above", c[k] > p.meta["S"])]
                hit = [name for name, ok in hits if ok]
                if hit:
                    first = (int(cns[k]) + AVAIL, hit[0])
                    break
            got = (p.cancel_effective_time, p.cancel_reason)
            assert got == (first if first else (None, None)), (p.plan_id, got, first)
            if first:
                assert first[0] >= p.signal_time + ctx_s_dur(ctx) + AVAIL   # 신호 봉 자신은 취소 근거가 아님
            checked += 1
    assert checked > 300


def ctx_s_dur(ctx: T.ScenarioContext) -> int:
    return C.TF_NS[ctx.s_tf]


# ---------------------------------------------------------------------------
# 9. L1b 시각 (준비 → 확인 → k_last → 최저가)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ctx_name", ["ctx_p1", "ctx_p2"])
def test_l1b_timing_reference(request, ctx_name):
    ctx = request.getfixturevalue(ctx_name)
    s, cb = ctx.s_bars, ctx.c_bars
    s_low, s_close, s_cns = s["low"].to_numpy(), s["close"].to_numpy(), s["close_ns"].to_numpy()
    c_open, c_high, c_low, c_close = (cb[k].to_numpy() for k in ("open", "high", "low", "close"))
    c_ons, c_cns = cb["open_ns"].to_numpy(), cb["close_ns"].to_numpy()
    madis = ctx.s_struct.madis
    s_dur = C.TF_NS[ctx.s_tf]
    # [수정 담당] 기본은 마디당 준비 1회(검토 SPEC-L1B-REARM)라 후보가 적어, 재준비 진단(l1b_rearm)도 같이 검사해
    # 검정력을 유지한다. 기본 쪽은 "준비 = T_B 뒤 처음으로 저가가 구간에 들어온 봉"도 확인한다.
    cands = []
    for rearm in (False, True):
        got = SC.generate_candidates(ctx, ComboConfig("L1b", "DB", ctx.setting, l1b_rearm=rearm))
        assert len(got) > (40 if not rearm else 100), rearm
        cands += [(rearm, cn) for cn in got]
    for rearm, cand in cands:
        mt = cand.log.meta
        sig = cand.log.signal_time
        row = madis.iloc[int(mt["madi_row"])]
        H, W, tb = mt["H"], mt["W"], int(row["tb_idx"])
        arm, k_last, ci = int(mt["arm_idx"]), int(mt["k_last"]), int(mt["c_idx"])
        assert tb < arm and H <= s_low[arm] <= H + C.L1B_ZONE_W * W                 # 준비: T_B 뒤, 저가가 구간 안
        if not rearm:                                                               # §7.2 마디당 준비 1회 = 첫 준비
            pre = s_low[tb + 1:arm]
            assert not ((pre >= H) & (pre <= H + C.L1B_ZONE_W * W)).any(), mt["cand_id"]
        assert mt["arm_known_ns"] == s_cns[arm] < sig                              # 준비 봉 마감 "뒤" 확인
        assert sig <= s_cns[arm] + C.L1B_ARM_BARS * s_dur                          # 24 S 봉 창 안
        assert c_cns[ci] == sig                                                    # 신호 = 확인 C 봉 마감
        assert c_close[ci] > c_open[ci] and c_close[ci] > c_high[ci - 1] and c_close[ci] > H
        assert s_cns[k_last] <= sig and (k_last + 1 == len(s_cns) or s_cns[k_last + 1] > sig)  # 마감된 마지막 S 봉
        assert k_last <= int(row["end_idx"])                                       # 확인 시점에 마디가 살아 있음
        sel = (c_ons >= int(row["tb_close_ns"])) & (c_cns <= sig)
        assert mt["lowest"] == c_low[sel].min()                                     # 최저가 = T_B 뒤 ~ 확인까지
        # 첫 확인: 준비 봉 마감 뒤 확인 C 봉 전까지 확인 조건을 만족한 C 봉이 없다
        between = np.flatnonzero((c_cns > s_cns[arm]) & (c_cns < sig))
        ok = (c_close[between] > c_open[between]) & (c_close[between] > c_high[between - 1]) & (c_close[between] > H)
        assert not ok.any(), cand.log.meta["cand_id"]
        # 폐기 규칙: 확인 시각까지 마감한 S 봉 중 종가 < H가 두 번 이상이면 안 된다
        assert int(np.sum(s_close[arm + 1:k_last + 1] < H)) <= 1, cand.log.meta["cand_id"]
        assert cand.plan is None or cand.plan.atr_at_signal == ctx.s_ind["atr"].to_numpy()[k_last]


# ---------------------------------------------------------------------------
# 10. as-of: 모든 판단 시각의 D 봉
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ctx_name", ["ctx_p1", "ctx_p2"])
def test_direction_asof_every_decision_time(request, ctx_name):
    ctx = request.getfixturevalue(ctx_name)
    d_cns = ctx.d_bars["close_ns"].to_numpy()
    for src in (ctx.s_bars, ctx.c_bars):                             # S 봉(L1a·S2·S3)과 C 봉(L1b) 판단 시각
        q = src["close_ns"].to_numpy() + AVAIL
        j = F.direction_asof_index(ctx, q)
        ok = j >= 0
        assert (d_cns[j[ok]] <= q[ok] - AVAIL).all()                  # 쓴 D 봉은 판단 시각 60초 전까지 마감
        nxt = j + 1
        has = nxt < len(d_cns)
        assert (d_cns[nxt[has]] > q[has] - AVAIL).all()               # 다음 D 봉은 아직(진행 중) → 안 씀
        # 같은 순간 마감한 D 봉은 쓴다(I-1): S 봉 마감 = D 봉 마감이면 그 D 봉
        same = np.isin(q - AVAIL, d_cns)
        assert (d_cns[j[same]] == q[same] - AVAIL).all()


# ---------------------------------------------------------------------------
# 11. F2·F5·F6 순진한 독립 구현
# ---------------------------------------------------------------------------


def test_fixed_filters_naive_reference(ctx_p1):
    ctx = ctx_p1
    b, ind, st = ctx.s_bars, ctx.s_ind, ctx.s_struct
    lo_i, hi_i = 3000, 5500
    c, low, high = b["close"].to_numpy(), b["low"].to_numpy(), b["high"].to_numpy()
    vr, atr, q20 = ind["vr"].to_numpy(), ind["atr"].to_numpy(), ind["atr_q20"].to_numpy()
    surge = ind["surge"].to_numpy()
    flags = ctx.s_flags
    # 트랩(I-17) 순진한 목록: 완성 봉 m마다 개수
    done = {}
    for j in range(1, hi_i):
        for kind, last, px, sgn in (("s", st.last_sl, low, 1.0), ("r", st.last_sh, high, -1.0)):
            ref = int(last[j - 1])
            if ref < 0:
                continue
            L = px[ref]
            if sgn * c[j - 1] >= sgn * L > sgn * c[j]:
                for m in range(j + 1, min(j + C.F6_RETURN_BARS, len(c) - 1) + 1):
                    if sgn * c[m] > sgn * L:
                        done[m] = done.get(m, 0) + 1
                        break
    for t in range(lo_i, hi_i):
        f2 = bool(vr[t] < C.F2_VR_MAX and atr[t] <= q20[t])
        f5 = bool(surge[t - C.F5_LOOKBACK:t].any())
        traps = sum(done.get(m, 0) for m in range(t - C.F6_LOOKBACK, t))    # 완성 봉 ∈ [t−48, t−1]
        f6 = traps >= C.F6_MIN_TRAPS
        assert (flags["F2"].iloc[t], flags["F5"].iloc[t], flags["F6"].iloc[t]) == (f2, f5, f6), t
    assert flags["F6"].iloc[lo_i:hi_i].any() and flags["F5"].iloc[lo_i:hi_i].any()


# ---------------------------------------------------------------------------
# 12. 체결: 활성 시각·주문 수명·첫 관통
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("setting", tuple(E2E))
def test_fills_respect_activation_and_order_life(e2e_full, setting):
    m, full = e2e_full[setting]
    xb = m.exec_arrays()
    ctx = SC.build_context(m, setting)
    plans = {c.plan.plan_id: c.plan for cfg in C.g1_combos() if cfg.setting == setting
             for c in SC.generate_candidates(ctx, cfg) if c.plan is not None}
    n_limit = n_ioc = 0
    for key, val in full.items():
        if key[-1] == "cands":
            continue
        for tr in val[0]:
            plan = plans[tr.plan_id]
            assert tr.active_from == tr.approval_time + C.LATENCY_DEFAULT_MIN * C.NS_PER_MIN
            assert tr.approval_time == tr.signal_time + AVAIL
            if not tr.is_filled:
                continue
            j = int(np.searchsorted(xb.open_ns, tr.entry_time))
            j0 = int(np.searchsorted(xb.open_ns, tr.active_from, side="left"))
            assert xb.open_ns[j] == tr.entry_time and j >= j0 and xb.open_ns[j] >= tr.active_from
            assert tr.exit_time >= tr.entry_time
            if tr.order_type == "ioc_cap":
                n_ioc += 1
                assert j == j0 and tr.entry_price == xb.open[j] <= tr.plan_entry
            else:
                n_limit += 1
                side = tr.side
                crossed = (xb.low[j0:j + 1] < tr.plan_entry) if side > 0 else (xb.high[j0:j + 1] > tr.plan_entry)
                assert crossed[-1] and not crossed[:-1].any()        # 처음 관통한 봉
                assert tr.entry_price == tr.plan_entry
                assert xb.close_ns[j] <= plan.order_end              # 봉 전체가 주문 수명 안 (I-31)
    assert n_limit > 100 and n_ioc > 50


def test_limit_fill_bar_must_end_before_cancel_effect():
    """5분 실행 봉: 취소 효력(11:01)을 넘겨 끝나는 봉(11:00~11:05)에서의 관통은 체결로 인정하지 않는다(I-31)."""
    xb_df = make_bars(closes=[100.0] * 40, start="2023-06-01 09:00", tf="5m", wick=0.0001)
    lo = xb_df["low"].to_numpy(copy=True)
    t_1100 = C.ts_ns("2023-06-01 11:00")
    j_1100 = int(np.searchsorted(xb_df["open_ns"].to_numpy(), t_1100))
    lo[j_1100] = 98.0                                               # 11:00~11:05 봉에서만 관통
    xb_df = T.make_bars_frame(xb_df["open_ns"].to_numpy(), xb_df["open"].to_numpy(), xb_df["high"].to_numpy(), lo,
                              xb_df["close"].to_numpy(), xb_df["volume"].to_numpy(), C.TF_NS["5m"])
    xb = T.ExecArrays.from_frame(xb_df)
    fa = T.FundingArrays(time_ns=np.array([], dtype=np.int64), rate=np.array([], dtype=np.float64))
    sig = C.ts_ns("2023-06-01 10:00")
    base = dict(plan_id="x", scenario="L1a", side=1, signal_time=sig, approval_time=sig + AVAIL,
                active_from=sig + AVAIL + 10 * C.NS_PER_MIN, order_type="limit", entry_price=99.0, stop=97.0,
                target=110.0, valid_until=sig + 24 * C.NS_PER_HOUR, max_hold_ns=72 * C.NS_PER_HOUR, atr_at_signal=1.0)
    cancelled = X.simulate_plan(T.Plan(**base, cancel_effective_time=t_1100 + AVAIL, cancel_reason="close_below"), xb, fa)
    assert cancelled.status == T.Status.CANCELLED and cancelled.busy_until == t_1100 + AVAIL
    later = X.simulate_plan(T.Plan(**base, cancel_effective_time=t_1100 + 5 * C.NS_PER_MIN + AVAIL,
                                   cancel_reason="close_below"), xb, fa)
    assert later.is_filled and later.entry_time == t_1100


# ---------------------------------------------------------------------------
# 13. 돈치안: 절단 불변, 다음 날 시가 체결
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_donchian_truncation_invariance(real_bars, real_exec):
    xb_df, fund = real_exec
    daily = real_bars["1d"]
    xb, fa = T.ExecArrays.from_frame(xb_df), T.FundingArrays.from_frame(fund)
    full = B.donchian_ensemble(daily, fa, xb)
    close = daily["close"].to_numpy()
    for cut in (260, 700, 1301, 2000, 2400):
        t_ns = int(daily["close_ns"].iloc[cut])
        d = daily.iloc[:cut + 1]
        xb_t = T.ExecArrays.from_frame(xb_df[xb_df["close_ns"] <= t_ns])
        fa_t = T.FundingArrays.from_frame(fund[fund["time_ns"] <= t_ns].reset_index(drop=True))
        tr = B.donchian_ensemble(d, fa_t, xb_t)
        k = len(tr["equity"]) - 1                                   # 마지막 값은 절단 쪽만 데이터 끝 청산 수수료 포함
        np.testing.assert_array_equal(tr["equity"][:k], full["equity"][:k])
        for p in C.DONCHIAN_PERIODS:
            m = p // C.DONCHIAN_EXIT_DIVISOR
            np.testing.assert_array_equal(B.donchian_positions(close[:cut + 1], p, m),
                                          B.donchian_positions(close, p, m)[:cut + 1])


def test_donchian_fills_at_open_ignore_same_day_close(real_bars):
    """하루 안 미래 변경: d일 종가(·고저)를 ±12% 바꿔도 d일 시가 체결(와 그 전 체결)은 같다 — 당일 종가로 당일 체결 금지."""
    daily = real_bars["1d"]
    o, h, l, c = (daily[k].to_numpy() for k in ("open", "high", "low", "close"))
    start = max(C.DONCHIAN_PERIODS)
    fund = np.zeros(len(c))

    def fills(close):
        targets = np.stack([B._positions(close, p, p // C.DONCHIAN_EXIT_DIVISOR, start) for p in C.DONCHIAN_PERIODS])
        weight = C.DONCHIAN_NOTIONAL_CAP / len(C.DONCHIAN_PERIODS)
        return B._simulate(o, close, fund, targets, weight, start, trim=True)["fills"]

    base = fills(c)
    days_with_fills = sorted({f["day"] for f in base if f["action"] == "enter"})
    assert len(days_with_fills) > 20
    rng = np.random.default_rng(21)
    for d in rng.choice(days_with_fills, 15, replace=False):
        d = int(d)
        for mult in (0.88, 1.12):
            c2 = c.copy()
            c2[d] = c[d] * mult
            got = fills(c2)
            a = [f for f in base if f["day"] <= d]
            b = [f for f in got if f["day"] <= d]
            assert a == b, (d, mult)


def test_donchian_fills_next_open_not_same_close():
    """t일 종가 돌파 → t+1일 시가(갭)에 체결. 당일 종가(돌파가)나 t+1 종가가 아니다."""
    n = 140
    closes = 100.0 + np.array([0.0, 0.2, 0.4, 0.2, 0.0])[np.arange(n) % 5]   # 주기 5: 신고가·신저가 없음
    rows = [(c, c + 0.6, c - 0.6, c) for c in closes]
    rows[120] = (100.0, 111.0, 99.5, 110.0)                         # 돌파(종가 110)
    rows[121] = (130.0, 131.0, 129.0, 130.5)                        # 다음 날 갭 시가 130
    daily = make_bars(rows, start="2020-01-01", tf="1d")
    o, c = daily["open"].to_numpy(), daily["close"].to_numpy()
    targets = np.stack([B._positions(c, p, p // 2, 100) for p in (20,)])
    assert targets[0, 119] == 0 and targets[0, 120] == 1
    fund = np.zeros(n)
    sim = B._simulate(o, c, fund, targets, 0.2, 100, trim=True)
    enter = [f for f in sim["fills"] if f["action"] == "enter"]
    assert enter[0]["day"] == 121 and enter[0]["price"] == 130.0
    c2 = c.copy()
    c2[121] = 150.0                                                 # t+1 종가를 바꿔도 체결가는 시가
    sim2 = B._simulate(o, c2, fund, targets, 0.2, 100, trim=True)
    assert [f for f in sim2["fills"] if f["action"] == "enter"][0]["price"] == 130.0


# ---------------------------------------------------------------------------
# 14. 무작위 기준선 진입 시각
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_random_baseline_entry_after_approval_and_latency(real_bars, real_exec):
    xb_df, fund = real_exec
    lo, hi = C.ts_ns("2023-08-01"), C.ts_ns("2024-02-01")          # 5분 → 1분 실행 봉 전환 포함
    sel = xb_df[(xb_df["open_ns"] >= lo) & (xb_df["close_ns"] <= hi)]
    xb = T.ExecArrays.from_frame(sel)
    fa = T.FundingArrays.from_frame(fund[(fund["time_ns"] >= lo) & (fund["time_ns"] <= hi)].reset_index(drop=True))
    s_cns = real_bars["1h"]["close_ns"].to_numpy()
    s_cns = s_cns[(s_cns >= lo) & (s_cns <= hi - C.NS_PER_DAY)]
    rng = np.random.default_rng(9)
    closes = rng.choice(s_cns, 4000)
    side = rng.choice([-1, 1], 4000)
    for lat in (5, 10, 15):
        cfg = ComboConfig("L1b", "DB", "P1", latency_min=lat)
        sim = RB.simulate_market_batch(side, closes, 0.006, 0.012, xb, fa, cfg)
        act = closes + AVAIL + lat * C.NS_PER_MIN
        ej = sim["entry_j"]
        assert sim["filled"].all()
        assert (xb.open_ns[ej] >= act).all()                        # 판단 + L 전에는 진입하지 않는다
        assert ((ej == 0) | (xb.open_ns[ej - 1] < act)).all()       # 그 뒤 첫 실행 봉
        assert (sim["entry_price"] == xb.open[ej]).all()
    # 활성 전 실행 봉을 마구 바꿔도 무작위 거래 결과가 같다
    cfg = ComboConfig("S3", "DB", "P1")
    for i in range(0, 4000, 400):
        base = RB.simulate_market_trade(int(side[i]), int(closes[i]), 0.006, 0.012, xb, fa, cfg)
        act = int(closes[i]) + AVAIL + cfg.latency_ns
        before = xb.open_ns < act
        arrs = {f.name: np.array(getattr(xb, f.name), copy=True) for f in dataclasses.fields(T.ExecArrays)}
        for k in ("open", "high", "low", "close"):
            arrs[k][before] = arrs[k][before] * 0.5
        arrs["high"][before] = arrs["high"][before] * 3.0
        wild = RB.simulate_market_trade(int(side[i]), int(closes[i]), 0.006, 0.012, T.ExecArrays(**arrs), fa, cfg)
        assert trade_equal(base, wild), i
